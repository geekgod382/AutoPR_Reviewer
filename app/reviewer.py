import logging
from app.github_client import get_pr_files, get_pr_diff, post_comment
from app.analyzer.static import run_static_analysis
from app.analyzer.ai import run_ai_analysis
from app.analyzer.risk import calculate_risk_score
from app.analyzer.premium import run_premium_analysis
from app.payments import get_installation_plan
from app.database import get_session
from app.models import Installation, ReviewLog

logger = logging.getLogger(__name__)

RISK_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🔴"}


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

        files = await get_pr_files(installation_id, owner, repo_name, pr_number)
        diff = await get_pr_diff(installation_id, owner, repo_name, pr_number)

        static_findings = await run_static_analysis(files)
        ai_result = await run_ai_analysis(diff, files)
        risk = calculate_risk_score(files, ai_result, static_findings)

        premium_result = None
        if is_pro:
            premium_result = run_premium_analysis(files, diff)
            logger.info("Pro plan — premium analysis included for PR #%s", pr_number)

        comment = _format_comment(ai_result, static_findings, risk, files, premium_result)

        await post_comment(installation_id, owner, repo_name, pr_number, comment)
        logger.info("Posted review for PR #%s", pr_number)

        _record_review(installation_id, f"{owner}/{repo_name}", pr_number, risk["level"])

    except Exception as e:
        logger.exception("Error reviewing PR: %s", e)


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


def _format_comment(
    ai_result: dict,
    static_findings: list[dict],
    risk: dict,
    files: list[dict],
    premium_result: dict | None = None,
) -> str:
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

    # Bugs
    bugs = ai_result.get("bugs", [])
    if bugs:
        sections.append("### 🐛 Potential Bugs")
        for bug in bugs:
            sev = bug.get("severity", "medium").upper()
            sections.append(f"- **[{sev}]** `{bug.get('file', '')}`: {bug['description']}")
        sections.append("")

    # Style Issues
    style_issues = ai_result.get("style_issues", [])
    if style_issues:
        sections.append("### 🎨 Style Issues")
        for issue in style_issues:
            sections.append(f"- `{issue.get('file', '')}`: {issue['description']}")
        sections.append("")

    # Performance
    perf = ai_result.get("performance", [])
    if perf:
        sections.append("### ⚡ Performance Suggestions")
        for p in perf:
            sections.append(f"- `{p.get('file', '')}`: {p['description']}")
        sections.append("")

    # Static Analysis
    if static_findings:
        sections.append(f"### 🔍 Static Analysis ({len(static_findings)} findings)")
        for finding in static_findings[:15]:
            sections.append(f"- `{finding['message']}`")
        if len(static_findings) > 15:
            sections.append(f"- ... and {len(static_findings) - 15} more")
        sections.append("")

    # Security (from AI)
    security = ai_result.get("security", [])
    if security:
        sections.append("### 🛡️ Security Concerns")
        for s in security:
            sev = s.get("severity", "medium").upper()
            sections.append(f"- **[{sev}]** `{s.get('file', '')}`: {s['description']}")
        sections.append("")

    # Premium sections (Pro plan only)
    if premium_result:
        sections.append("---")
        sections.append("### 💎 Pro Analysis\n")

        # Complexity Score
        complexity = premium_result.get("complexity_score", {})
        if complexity:
            sections.append(
                f"**Complexity:** {complexity.get('level', 'N/A').upper()} "
                f"(score: {complexity.get('score', 0)}) — "
                f"{complexity.get('files_changed', 0)} files, "
                f"{complexity.get('lines_changed', 0)} lines changed, "
                f"cyclomatic estimate: {complexity.get('cyclomatic_estimate', 0)}"
            )

        # Estimated Review Time
        review_time = premium_result.get("estimated_review_time")
        if review_time:
            sections.append(f"**Estimated Review Time:** {review_time}")
        sections.append("")

        # Security Patterns
        sec_patterns = premium_result.get("security_patterns", [])
        if sec_patterns:
            sections.append("#### 🔐 Security Pattern Detection")
            for s in sec_patterns:
                sev = s.get("severity", "medium").upper()
                sections.append(f"- **[{sev}]** {s['message']}")
            sections.append("")

        # Large Functions
        large_funcs = premium_result.get("large_functions", [])
        if large_funcs:
            sections.append("#### 📏 Large Functions")
            for f in large_funcs:
                sections.append(f"- {f['message']}")
            sections.append("")

        # Nested Loops
        nested = premium_result.get("nested_loops", [])
        if nested:
            sections.append("#### 🔄 Deeply Nested Loops")
            for n in nested:
                sections.append(f"- {n['message']}")
            sections.append("")

        # Missing Error Handling
        error_handling = premium_result.get("missing_error_handling", [])
        if error_handling:
            sections.append("#### ⚠️ Missing Error Handling")
            for e in error_handling:
                sections.append(f"- {e['message']}")
            sections.append("")

    sections.append("---")
    sections.append("*Reviewed by [AutoPR Reviewer](https://github.com/apps/autopr-reviewer) 🤖*")

    return "\n".join(sections)
