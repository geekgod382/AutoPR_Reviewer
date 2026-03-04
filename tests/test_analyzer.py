import json
from unittest.mock import patch, MagicMock

import pytest

from app.analyzer.risk import calculate_risk_score
from app.analyzer.static import _extract_added_lines
from app.analyzer.premium import (
    detect_large_functions,
    detect_nested_loops,
    detect_missing_error_handling,
    calculate_complexity_score,
    estimate_review_time,
    detect_security_patterns,
    run_premium_analysis,
)


# ── Risk Score ──────────────────────────────────────────────────────

class TestRiskScore:
    def test_low_risk(self):
        files = [{"filename": "readme.md", "changes": 5}]
        ai = {"bugs": [], "security": []}
        result = calculate_risk_score(files, ai, [])
        assert result["level"] == "low"
        assert result["score"] < 3

    def test_high_risk_many_files(self):
        files = [{"filename": f"file{i}.py", "changes": 10} for i in range(15)]
        ai = {"bugs": [], "security": []}
        result = calculate_risk_score(files, ai, [])
        assert result["level"] in ("medium", "high")

    def test_high_risk_bugs(self):
        files = [{"filename": "auth.py", "changes": 100}]
        ai = {
            "bugs": [{"severity": "high", "description": "null ref"}],
            "security": [{"description": "xss"}],
        }
        result = calculate_risk_score(files, ai, [])
        assert result["level"] == "high"
        assert any("high-severity" in r for r in result["reasons"])

    def test_sensitive_file_detected(self):
        files = [{"filename": "migrations/001.py", "changes": 10}]
        ai = {"bugs": [], "security": []}
        result = calculate_risk_score(files, ai, [])
        assert any("Sensitive" in r for r in result["reasons"])


# ── Static Analysis Helpers ─────────────────────────────────────────

class TestExtractAddedLines:
    def test_extracts_additions(self):
        patch_text = (
            "@@ -1,3 +1,4 @@\n"
            " existing_line\n"
            "+new_line\n"
            "-removed_line\n"
            " another_existing\n"
        )
        result = _extract_added_lines(patch_text)
        assert "new_line" in result
        assert "removed_line" not in result
        assert "existing_line" in result

    def test_empty_patch(self):
        assert _extract_added_lines("") == ""


# ── Premium: Large Functions ────────────────────────────────────────

class TestDetectLargeFunctions:
    def test_detects_large_function(self):
        lines = ["def big_function():"] + [f"+    line_{i}" for i in range(60)]
        diff = "\n".join(lines)
        findings = detect_large_functions(diff)
        assert len(findings) == 1
        assert findings[0]["function"] == "big_function"

    def test_ignores_small_function(self):
        lines = ["def small():"] + ["+    pass" for _ in range(10)]
        diff = "\n".join(lines)
        findings = detect_large_functions(diff)
        assert len(findings) == 0


# ── Premium: Nested Loops ──────────────────────────────────────────

class TestDetectNestedLoops:
    def test_detects_deeply_nested(self):
        diff = (
            "+for a in x:\n"
            "+    for b in y:\n"
            "+        for c in z:\n"
            "+            for d in w:\n"
            "+                pass\n"
        )
        findings = detect_nested_loops(diff)
        assert len(findings) > 0

    def test_ignores_shallow_loops(self):
        diff = "+for a in x:\n+    for b in y:\n+        pass\n"
        findings = detect_nested_loops(diff)
        assert len(findings) == 0


# ── Premium: Missing Error Handling ─────────────────────────────────

class TestDetectMissingErrorHandling:
    def test_detects_bare_except(self):
        diff = "+try:\n+    pass\n+except:\n+    pass\n"
        findings = detect_missing_error_handling(diff)
        assert any("Bare" in f["message"] for f in findings)

    def test_detects_io_without_try(self):
        diff = "+data = open('file.txt')\n"
        findings = detect_missing_error_handling(diff)
        assert any("I/O" in f["message"] for f in findings)


# ── Premium: Complexity & Review Time ──────────────────────────────

class TestComplexityScore:
    def test_low_complexity(self):
        files = [{"filename": "a.py", "additions": 5, "deletions": 2}]
        diff = "pass"
        result = calculate_complexity_score(files, diff)
        assert result["level"] == "low"

    def test_high_complexity(self):
        files = [{"filename": f"f{i}.py", "additions": 100, "deletions": 50} for i in range(15)]
        diff = " ".join(["if else for while try except"] * 30)
        result = calculate_complexity_score(files, diff)
        assert result["level"] in ("high", "very high")


class TestEstimateReviewTime:
    def test_quick_review(self):
        assert estimate_review_time({"score": 2}) == "5-15 minutes"

    def test_long_review(self):
        assert estimate_review_time({"score": 25}) == "60+ minutes"


# ── Premium: Security Patterns ─────────────────────────────────────

class TestSecurityPatterns:
    def test_detects_hardcoded_secret(self):
        diff = "+api_key = 'sk_live_abc123456789'\n"
        findings = detect_security_patterns(diff)
        assert any(f["type"] == "hardcoded_secret" for f in findings)

    def test_detects_eval(self):
        diff = "+result = eval(user_input)\n"
        findings = detect_security_patterns(diff)
        assert any(f["type"] == "dangerous_function" for f in findings)

    def test_detects_sql_injection(self):
        diff = "+cursor.execute(f\"SELECT * FROM users WHERE id = {user_id}\")\n"
        findings = detect_security_patterns(diff)
        assert any(f["type"] == "sql_injection" for f in findings)

    def test_clean_code(self):
        diff = "+x = 1 + 2\n"
        findings = detect_security_patterns(diff)
        assert len(findings) == 0


# ── Premium: Full Pipeline ─────────────────────────────────────────

class TestRunPremiumAnalysis:
    def test_returns_all_keys(self):
        files = [{"filename": "a.py", "additions": 5, "deletions": 2}]
        diff = "+x = 1\n"
        result = run_premium_analysis(files, diff)
        assert "large_functions" in result
        assert "nested_loops" in result
        assert "missing_error_handling" in result
        assert "complexity_score" in result
        assert "estimated_review_time" in result
        assert "security_patterns" in result
