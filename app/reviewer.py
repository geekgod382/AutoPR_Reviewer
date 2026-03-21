import logging
from app.github_client import get_pr_files, get_pr_diff, get_pr_head_sha, post_comment, post_review
from app.analyzer.static import run_static_analysis
from app.analyzer.ai import run_ai_analysis, build_line_index
from app.analyzer.risk import calculate_risk_score
from app.analyzer.premium import run_premium_analysis
from app.payments import get_installation_plan
from app.database import get_session
from app.models import Installation, ReviewLog

logger = logging.getLogger(__name__)

RISK_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🔴"}

# Severity emoji for inline comment headers
SEV_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🔵", "style": "🎨"}


async def handle_pr_event(payload: dict):
    try:
        installation_id = payload["installation"]["id"]
        repo = payload["repository"]
        owner = repo["owner"]["login"]
        repo_name = repo["name"]
        pr = payload["pull_request"]
        pr_number = pr["number"]

        logger.info("Reviewing PR #%s on %s/%s", pr_number, owner, repo_name)

        plan = get_installation_plan(installation_id)
        is_pro = plan == "pro"

        # Fetch everything we need
        files = await get_pr_files(installation_id, owner, repo_name, pr_number)
        diff = await get_pr_diff(installation_id, owner, repo_name, pr_number)
        commit_sha = await get_pr_head_sha(installation_id, owner, repo_name, pr_number)

        # Run all analyses
        static_findings = await run_static_analysis(files)
        ai_result = await run_ai_analysis(diff, files)
        risk = calculate_risk_score(files, ai_result, static_findings)

        premium_result = None
        if is_pro:
            premium_result = run_premium_analysis(files, diff)
            logger.info("Pro plan — premium analysis included for PR #%s", pr_number)

        # Build the valid-line index from the diff patches
        line_index = build_line_index(files)

        # Split issues into inline comments vs summary-only
        inline_comments = _build_inline_comments(ai_result, line_index)

        # Build the summary comment (always posted to conversation tab)
        summary = _format_summary(ai_result, static_findings, risk, files, premium_result, inline_comments)

        # Post — try inline review first, fall back to plain comment if it fails
        try:
            if inline_comments:
                await post_review(
                    installation_id, owner, repo_name, pr_number,
                    commit_sha, summary, inline_comments,
                )
                logger.info(
                    "Posted review with %d inline comments for PR #%s",
                    len(inline_comments), pr_number,
                )
            else:
                # No inline-able issues — just post the summary comment
                await post_comment(installation_id, owner, repo_name, pr_number, summary)
                logger.info("Posted summary comment for PR #%s (no inline comments)", pr_number)

        except Exception as review_err:
            # GitHub rejects the whole review if even one inline comment has a bad line.
            # Fall back to plain summary comment so the user always gets something.
            logger.warning(
                "post_review failed (%s) — falling back to plain comment for PR #%s",
                review_err, pr_number,
            )
            await post_comment(installation_id, owner, repo_name, pr_number, summary)

        _record_review(installation_id, f"{owner}/{repo_name}", pr_number, risk["level"])

    except Exception as e:
        logger.exception("Error reviewing PR: %s", e)


def _build_inline_comments(ai_result: dict, line_index: dict) -> list[dict]:
    """
    Convert AI findings that have a valid (file, line) into inline comment dicts.
    Any finding without a line number, or whose line isn't in the diff, is skipped
    here and will appear in the summary comment instead.
    """
    inline = []

    categories = [
        ("bugs",         "🐛 Bug",          True),   # (key, label, has_severity)
        ("security",     "🔒 Security",      True),
        ("performance",  "⚡ Performance",   False),
        ("style_issues", "🎨 Style",         False),
    ]

    for key, label, has_severity in categories:
        for issue in ai_result.get(key, []):
            filename = issue.get("file", "")
            line = issue.get("line")
            if not filename or not line:
                continue
            # Validate that this line exists as an addition in the diff
            if (filename, int(line)) not in line_index:
                continue

            sev = issue.get("severity", "")
            sev_str = f" **[{sev.upper()}]**" if has_severity and sev else ""
            body = f"{label}{sev_str}\n\n{issue['description']}"

            inline.append({
                "path": filename,
                "line": int(line),
                "body": body,
            })

    return inline


def _format_summary(
    ai_result: dict,
    static_findings: list[dict],
    risk: dict,
    files: list[dict],
    premium_result: dict | None,
    inline_comments: list[dict],
) -> str:
    """
    Build the top-level summary comment that always goes on the conversation tab.
    Issues that were posted as inline comments are noted but not repeated in full.
    Issues without a valid line (fell through inline validation) are listed here.
    """
    sections = []
    sections.append("## 🤖 AutoPR Review\n")

    # Summary
    summary = ai_result.get("summary", "No summary available.")
    sections.append(f"### 📋 Summary\n{summary}\n")

    # Risk Score
    level = risk["level"]
    emoji = RISK_EMOJI.get(level, "⚪")
    sections.append(f"### {emoji} Risk: **{level.upper()}** (score: {risk['score']})")
    if risk["reasons"]:
        for reason in risk["reasons"]:
            sections.append(f"- {reason}")
    sections.append("")

    # Inline comment summary line
    if inline_comments:
        sections.append(
            f"> 💬 **{len(inline_comments)} inline comment{'s' if len(inline_comments) != 1 else ''}** "
            f"posted directly on the changed lines — see the **Files changed** tab.\n"
        )

    # Issues that couldn't be inlined (no line number or line not in diff)
    # — collect them and show in summary so nothing is lost
    inlined_keys = {(c["path"], c["line"]) for c in inline_comments}

    fallthrough_bugs = [
        i for i in ai_result.get("bugs", [])
        if not _was_inlined(i, inlined_keys)
    ]
    fallthrough_security = [
        i for i in ai_result.get("security", [])
        if not _was_inlined(i, inlined_keys)
    ]
    fallthrough_perf = [
        i for i in ai_result.get("performance", [])
        if not _was_inlined(i, inlined_keys)
    ]
    fallthrough_style = [
        i for i in ai_result.get("style_issues", [])
        if not _was_inlined(i, inlined_keys)
    ]

    if fallthrough_bugs:
        sections.append("### 🐛 Potential Bugs")
        for bug in fallthrough_bugs:
            sev = bug.get("severity", "medium").upper()
            sections.append(f"- **[{sev}]** `{bug.get('file', '')}`: {bug['description']}")
        sections.append("")

    if fallthrough_security:
        sections.append("### 🔒 Security Concerns")
        for s in fallthrough_security:
            sev = s.get("severity", "medium").upper()
            sections.append(f"- **[{sev}]** `{s.get('file', '')}`: {s['description']}")
        sections.append("")

    if fallthrough_perf:
        sections.append("### ⚡ Performance Suggestions")
        for p in fallthrough_perf:
            sections.append(f"- `{p.get('file', '')}`: {p['description']}")
        sections.append("")

    if fallthrough_style:
        sections.append("### 🎨 Style Issues")
        for issue in fallthrough_style:
            sections.append(f"- `{issue.get('file', '')}`: {issue['description']}")
        sections.append("")

    # Static analysis findings (always in summary — no line mapping for these)
    if static_findings:
        sections.append(f"### 🔍 Static Analysis ({len(static_findings)} findings)")
        for finding in static_findings[:15]:
            sections.append(f"- `{finding['message']}`")
        if len(static_findings) > 15:
            sections.append(f"- ... and {len(static_findings) - 15} more")
        sections.append("")

    # Premium sections (Pro only)
    if premium_result:
        sections.append("---")
        sections.append("### 💎 Pro Analysis\n")

        complexity = premium_result.get("complexity_score", {})
        if complexity:
            sections.append(
                f"**Complexity:** {complexity.get('level', 'N/A').upper()} "
                f"(score: {complexity.get('score', 0)}) — "
                f"{complexity.get('files_changed', 0)} files, "
                f"{complexity.get('lines_changed', 0)} lines changed, "
                f"cyclomatic estimate: {complexity.get('cyclomatic_estimate', 0)}"
            )

        review_time = premium_result.get("estimated_review_time")
        if review_time:
            sections.append(f"**Estimated Review Time:** {review_time}")
        sections.append("")

        sec_patterns = premium_result.get("security_patterns", [])
        if sec_patterns:
            sections.append("#### 🔐 Security Pattern Detection")
            for s in sec_patterns:
                sev = s.get("severity", "medium").upper()
                sections.append(f"- **[{sev}]** {s['message']}")
            sections.append("")

        large_funcs = premium_result.get("large_functions", [])
        if large_funcs:
            sections.append("#### 📏 Large Functions")
            for f in large_funcs:
                sections.append(f"- {f['message']}")
            sections.append("")

        nested = premium_result.get("nested_loops", [])
        if nested:
            sections.append("#### 🔄 Deeply Nested Loops")
            for n in nested:
                sections.append(f"- {n['message']}")
            sections.append("")

        error_handling = premium_result.get("missing_error_handling", [])
        if error_handling:
            sections.append("#### ⚠️ Missing Error Handling")
            for e in error_handling:
                sections.append(f"- {e['message']}")
            sections.append("")

    sections.append("---")
    sections.append("*Reviewed by [AutoPR Reviewer](https://github.com/apps/autopr-reviewer) 🤖*")

    return "\n".join(sections)


def _was_inlined(issue: dict, inlined_keys: set) -> bool:
    """Check if this issue was already posted as an inline comment."""
    filename = issue.get("file", "")
    line = issue.get("line")
    if not filename or not line:
        return False
    return (filename, int(line)) in inlined_keys


def _record_review(
    github_installation_id: int,
    repo_full_name: str,
    pr_number: int,
    risk_level: str,
) -> None:
    session = get_session()
    try:
        installation = (
            session.query(Installation)
            .filter_by(github_installation_id=github_installation_id)
            .first()
        )
        if not installation:
            logger.warning("Installation %s not found, skipping review log", github_installation_id)
            return
        log = ReviewLog(
            installation_id=installation.id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            risk_level=risk_level,
        )
        session.add(log)
        session.commit()
    except Exception as e:
        logger.error("Failed to record review log: %s", e)
    finally:
        session.close()
