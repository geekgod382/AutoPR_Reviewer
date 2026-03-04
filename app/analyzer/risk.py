SENSITIVE_PATTERNS = [
    "migration", "auth", "security", "password", "secret",
    "config", "env", ".lock", "docker", "ci", "deploy",
    "payment", "billing", "token", "credential",
]


def calculate_risk_score(
    files: list[dict],
    ai_result: dict,
    static_findings: list[dict],
) -> dict:
    score = 0
    reasons = []

    num_files = len(files)
    if num_files > 10:
        score += 3
        reasons.append(f"{num_files} files changed")
    elif num_files > 5:
        score += 2
        reasons.append(f"{num_files} files changed")
    elif num_files > 1:
        score += 1

    total_changes = sum(f.get("changes", 0) for f in files)
    if total_changes > 500:
        score += 3
        reasons.append(f"{total_changes} lines changed")
    elif total_changes > 200:
        score += 2
        reasons.append(f"{total_changes} lines changed")
    elif total_changes > 50:
        score += 1

    sensitive_files = []
    for f in files:
        fname = f.get("filename", "").lower()
        for pattern in SENSITIVE_PATTERNS:
            if pattern in fname:
                sensitive_files.append(f["filename"])
                score += 2
                break
    if sensitive_files:
        reasons.append(f"Sensitive files: {', '.join(sensitive_files[:3])}")

    bugs = ai_result.get("bugs", [])
    high_bugs = [b for b in bugs if b.get("severity") == "high"]
    if high_bugs:
        score += 3
        reasons.append(f"{len(high_bugs)} high-severity bugs detected")
    elif bugs:
        score += 1
        reasons.append(f"{len(bugs)} potential bugs detected")

    security_issues = ai_result.get("security", [])
    if security_issues:
        score += 2
        reasons.append(f"{len(security_issues)} security concerns")

    if len(static_findings) > 10:
        score += 1
        reasons.append(f"{len(static_findings)} style issues")

    if score >= 6:
        level = "high"
    elif score >= 3:
        level = "medium"
    else:
        level = "low"

    return {
        "level": level,
        "score": score,
        "reasons": reasons,
    }
