import re
import logging

logger = logging.getLogger(__name__)

SECRET_PATTERNS = [
    re.compile(r"""(?:password|secret|api_key|apikey|token|auth)\s*[=:]\s*['"][^'"]{8,}['"]""", re.IGNORECASE),
    re.compile(r"""(?:AWS|AZURE|GCP|GITHUB|STRIPE|SLACK)_[A-Z_]*(?:KEY|SECRET|TOKEN)\s*[=:]\s*['"][^'"]+['"]""", re.IGNORECASE),
    re.compile(r"""-----BEGIN (?:RSA )?PRIVATE KEY-----"""),
]

SQL_INJECTION_PATTERNS = [
    re.compile(r"""(?:execute|cursor\.execute|raw|rawQuery)\s*\(\s*f?['"].*\{""", re.IGNORECASE),
    re.compile(r"""(?:execute|cursor\.execute)\s*\(\s*['"]\s*(?:SELECT|INSERT|UPDATE|DELETE).*%s""", re.IGNORECASE),
    re.compile(r"""\+\s*['"].*(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)""", re.IGNORECASE),
]

DANGEROUS_FUNCTIONS = [
    re.compile(r"""\beval\s*\("""),
    re.compile(r"""\bexec\s*\("""),
    re.compile(r"""\b__import__\s*\("""),
    re.compile(r"""\bos\.system\s*\("""),
    re.compile(r"""\bsubprocess\.call\s*\(.*shell\s*=\s*True"""),
]


def _strip_diff_prefix(line: str) -> str:
    """Remove the single-char diff prefix (+, -, or space) while preserving indentation."""
    if line and line[0] in ("+", "-", " "):
        return line[1:]
    return line


def run_premium_analysis(files: list[dict], diff: str) -> dict:
    results = {
        "large_functions": detect_large_functions(diff),
        "nested_loops": detect_nested_loops(diff),
        "missing_error_handling": detect_missing_error_handling(diff),
        "complexity_score": calculate_complexity_score(files, diff),
        "estimated_review_time": None,
        "security_patterns": detect_security_patterns(diff),
    }
    results["estimated_review_time"] = estimate_review_time(results["complexity_score"])
    return results


def detect_large_functions(diff: str) -> list[dict]:
    findings = []
    lines = diff.split("\n")
    current_func = None
    func_start = 0
    func_lines = 0

    for i, line in enumerate(lines):
        if not line.startswith("-"):
            func_match = re.match(r"^[+ ]?\s*(?:def|function|func|async def|public|private|protected)\s+(\w+)", line)
            if func_match:
                if current_func and func_lines > 50:
                    findings.append({
                        "function": current_func,
                        "lines": func_lines,
                        "message": f"Function `{current_func}` is {func_lines} lines long (>50). Consider breaking it up.",
                    })
                current_func = func_match.group(1)
                func_start = i
                func_lines = 0
            if current_func:
                func_lines += 1

    if current_func and func_lines > 50:
        findings.append({
            "function": current_func,
            "lines": func_lines,
            "message": f"Function `{current_func}` is {func_lines} lines long (>50). Consider breaking it up.",
        })

    return findings


def detect_nested_loops(diff: str) -> list[dict]:
    findings = []
    lines = diff.split("\n")
    loop_keywords = re.compile(r"^\s*(?:for|while)\s")

    for i, line in enumerate(lines):
        if line.startswith("-"):
            continue
        clean = _strip_diff_prefix(line)
        if not loop_keywords.match(clean):
            continue

        indent = len(clean) - len(clean.lstrip())
        nesting = 0
        for j in range(max(0, i - 30), i):
            prev = lines[j]
            if prev.startswith("-"):
                continue
            prev_clean = _strip_diff_prefix(prev)
            if loop_keywords.match(prev_clean):
                prev_indent = len(prev_clean) - len(prev_clean.lstrip())
                if prev_indent < indent:
                    nesting += 1

        if nesting >= 3:
            findings.append({
                "line": i + 1,
                "depth": nesting + 1,
                "message": f"Deeply nested loop (depth: {nesting + 1}) at line {i + 1}. Consider refactoring.",
            })

    return findings


def detect_missing_error_handling(diff: str) -> list[dict]:
    findings = []
    lines = diff.split("\n")

    for i, line in enumerate(lines):
        if line.startswith("-"):
            continue
        clean = _strip_diff_prefix(line)

        if re.match(r"\s*except\s*:", clean):
            findings.append({
                "line": i + 1,
                "message": f"Bare `except:` at line {i + 1} — catches all exceptions including KeyboardInterrupt. Specify exception types.",
            })

        io_patterns = [
            r"open\s*\(",
            r"requests\.\w+\s*\(",
            r"httpx\.\w+\s*\(",
            r"urllib",
            r"socket\.",
        ]
        for pattern in io_patterns:
            if re.search(pattern, clean):
                context_start = max(0, i - 5)
                context = "\n".join(lines[context_start:i])
                if "try" not in context:
                    findings.append({
                        "line": i + 1,
                        "message": f"I/O operation at line {i + 1} without try/except. Consider adding error handling.",
                    })
                break

    return findings


def calculate_complexity_score(files: list[dict], diff: str) -> dict:
    num_files = len(files)
    total_additions = sum(f.get("additions", 0) for f in files)
    total_deletions = sum(f.get("deletions", 0) for f in files)
    total_changes = total_additions + total_deletions

    branch_keywords = len(re.findall(r"\b(?:if|else|elif|switch|case|for|while|catch|except|try)\b", diff))
    logical_ops = len(re.findall(r"\b(?:and|or|&&|\|\|)\b", diff))

    cyclomatic_estimate = branch_keywords + logical_ops

    score = (
        num_files * 2
        + (total_changes // 50)
        + (cyclomatic_estimate // 10)
    )

    if score >= 20:
        level = "very high"
    elif score >= 12:
        level = "high"
    elif score >= 6:
        level = "moderate"
    else:
        level = "low"

    return {
        "score": score,
        "level": level,
        "files_changed": num_files,
        "lines_changed": total_changes,
        "cyclomatic_estimate": cyclomatic_estimate,
    }


def estimate_review_time(complexity: dict) -> str:
    score = complexity["score"]
    if score >= 20:
        return "60+ minutes"
    elif score >= 12:
        return "30-60 minutes"
    elif score >= 6:
        return "15-30 minutes"
    else:
        return "5-15 minutes"


def detect_security_patterns(diff: str) -> list[dict]:
    findings = []

    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(diff):
            findings.append({
                "type": "hardcoded_secret",
                "severity": "high",
                "message": f"Possible hardcoded secret/credential detected near: `{match.group()[:40]}...`",
            })

    for pattern in SQL_INJECTION_PATTERNS:
        for match in pattern.finditer(diff):
            findings.append({
                "type": "sql_injection",
                "severity": "high",
                "message": f"Potential SQL injection vulnerability: `{match.group()[:40]}...`",
            })

    for pattern in DANGEROUS_FUNCTIONS:
        for match in pattern.finditer(diff):
            findings.append({
                "type": "dangerous_function",
                "severity": "medium",
                "message": f"Potentially dangerous function call: `{match.group()[:30]}`",
            })

    return findings
