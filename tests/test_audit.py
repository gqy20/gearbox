"""测试 audit 结果落盘。"""

import json

from gearbox.agents.audit import AuditResult, Issue, _write_audit_outputs


class TestWriteAuditOutputs:
    def test_writes_expected_files(self, tmp_path) -> None:
        result = AuditResult(
            repo="owner/repo",
            profile={"language": "python"},
            comparison_markdown="# Comparison\n\nok",
            benchmarks=["pallets/click"],
            issues=[Issue(title="A", body="B", labels="high,enhancement")],
        )

        _write_audit_outputs(result, tmp_path)

        issues = json.loads((tmp_path / "issues.json").read_text(encoding="utf-8"))
        profile = json.loads((tmp_path / "profile.json").read_text(encoding="utf-8"))
        comparison = (tmp_path / "comparison.md").read_text(encoding="utf-8")

        assert issues["repo"] == "owner/repo"
        assert issues["issues"][0]["title"] == "A"
        assert profile["language"] == "python"
        assert comparison.startswith("# Comparison")
