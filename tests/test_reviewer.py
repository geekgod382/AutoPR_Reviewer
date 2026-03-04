from app.reviewer import _format_comment


class TestFormatComment:
    def _base_ai_result(self, **overrides) -> dict:
        result = {
            "summary": "Added a new utility module.",
            "bugs": [],
            "style_issues": [],
            "performance": [],
            "security": [],
        }
        result.update(overrides)
        return result

    def _base_risk(self, **overrides) -> dict:
        result = {"level": "low", "score": 1, "reasons": []}
        result.update(overrides)
        return result

    def test_basic_comment_structure(self):
        comment = _format_comment(
            self._base_ai_result(),
            [],
            self._base_risk(),
            [{"filename": "utils.py", "changes": 10}],
        )
        assert "## 🤖 AutoPR Review" in comment
        assert "### 📋 Summary" in comment
        assert "Added a new utility module." in comment
        assert "Risk: **LOW**" in comment
        assert "AutoPR Reviewer" in comment

    def test_bugs_section(self):
        ai = self._base_ai_result(
            bugs=[{"description": "Null pointer", "file": "main.py", "severity": "high"}]
        )
        comment = _format_comment(ai, [], self._base_risk(), [])
        assert "### 🐛 Potential Bugs" in comment
        assert "Null pointer" in comment
        assert "[HIGH]" in comment

    def test_style_issues_section(self):
        ai = self._base_ai_result(
            style_issues=[{"description": "Missing docstring", "file": "foo.py"}]
        )
        comment = _format_comment(ai, [], self._base_risk(), [])
        assert "### 🎨 Style Issues" in comment
        assert "Missing docstring" in comment

    def test_performance_section(self):
        ai = self._base_ai_result(
            performance=[{"description": "Use list comprehension", "file": "bar.py"}]
        )
        comment = _format_comment(ai, [], self._base_risk(), [])
        assert "### ⚡ Performance" in comment

    def test_static_findings(self):
        findings = [{"message": "E501 line too long"}]
        comment = _format_comment(
            self._base_ai_result(), findings, self._base_risk(), []
        )
        assert "### 🔍 Static Analysis" in comment
        assert "E501" in comment

    def test_static_findings_truncated(self):
        findings = [{"message": f"E{i}"} for i in range(20)]
        comment = _format_comment(
            self._base_ai_result(), findings, self._base_risk(), []
        )
        assert "... and 5 more" in comment

    def test_security_section(self):
        ai = self._base_ai_result(
            security=[{"description": "XSS risk", "file": "view.py", "severity": "high"}]
        )
        comment = _format_comment(ai, [], self._base_risk(), [])
        assert "### 🛡️ Security Concerns" in comment
        assert "XSS risk" in comment

    def test_no_premium_by_default(self):
        comment = _format_comment(
            self._base_ai_result(), [], self._base_risk(), []
        )
        assert "Pro Analysis" not in comment

    def test_premium_sections_included(self):
        premium = {
            "complexity_score": {
                "score": 15,
                "level": "high",
                "files_changed": 8,
                "lines_changed": 300,
                "cyclomatic_estimate": 20,
            },
            "estimated_review_time": "30-60 minutes",
            "security_patterns": [
                {"type": "hardcoded_secret", "severity": "high", "message": "Secret found"}
            ],
            "large_functions": [
                {"function": "process", "lines": 80, "message": "Function `process` is 80 lines long (>50)."}
            ],
            "nested_loops": [
                {"line": 42, "depth": 4, "message": "Deeply nested loop (depth: 4) at line 42."}
            ],
            "missing_error_handling": [
                {"line": 10, "message": "Bare `except:` at line 10"}
            ],
        }
        comment = _format_comment(
            self._base_ai_result(),
            [],
            self._base_risk(),
            [],
            premium_result=premium,
        )
        assert "### 💎 Pro Analysis" in comment
        assert "Complexity:" in comment
        assert "HIGH" in comment
        assert "30-60 minutes" in comment
        assert "🔐 Security Pattern" in comment
        assert "Secret found" in comment
        assert "📏 Large Functions" in comment
        assert "🔄 Deeply Nested" in comment
        assert "⚠️ Missing Error Handling" in comment
