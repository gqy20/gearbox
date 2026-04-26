"""测试 agents 模块"""

from gearbox.agents.audit import _parse_result as audit_parse
from gearbox.agents.evaluator import _parse_evaluation_result, build_evaluation_prompt
from gearbox.agents.implement import _parse_result as implement_parse
from gearbox.agents.review import _parse_result as review_parse
from gearbox.agents.triage import _parse_result as triage_parse


class TestAuditParse:
    """测试 audit 结果解析"""

    def test_valid_json(self) -> None:
        text = """
        Here's the audit result:

        ```json
        {
          "repo": "owner/repo",
          "profile": {"language": "python"},
          "benchmarks": ["pallets/click"],
          "issues": [
            {
              "title": "Add type hints",
              "body": "## Problem\\nMissing type hints\\n\\n## Solution\\n1. Add types",
              "labels": "high,enhancement"
            }
          ]
        }
        ```
        """
        result = audit_parse(text)
        assert result is not None
        assert result.repo == "owner/repo"
        assert len(result.issues) == 1
        assert result.issues[0].title == "Add type hints"

    def test_invalid_json_returns_none(self) -> None:
        result = audit_parse("no json here")
        assert result is None

    def test_empty_issues(self) -> None:
        text = '```json\n{"repo": "owner/repo", "issues": []}\n```'
        result = audit_parse(text)
        assert result is not None
        assert len(result.issues) == 0


class TestTriageParse:
    """测试 triage 结果解析"""

    def test_valid_triage(self) -> None:
        text = """
        ```json
        {
          "labels": ["bug", "high-priority"],
          "priority": "P1",
          "complexity": "M",
          "needs_clarification": false,
          "clarification_question": null,
          "ready_to_implement": true
        }
        ```
        """
        result = triage_parse(text)
        assert result is not None
        assert result.labels == ["bug", "high-priority"]
        assert result.priority == "P1"
        assert result.complexity == "M"
        assert result.ready_to_implement is True

    def test_needs_clarification(self) -> None:
        text = """
        ```json
        {
          "labels": ["question"],
          "priority": "P3",
          "complexity": "S",
          "needs_clarification": true,
          "clarification_question": "What is the expected behavior?",
          "ready_to_implement": false
        }
        ```
        """
        result = triage_parse(text)
        assert result is not None
        assert result.needs_clarification is True
        assert "expected behavior" in (result.clarification_question or "")

    def test_invalid_returns_none(self) -> None:
        result = triage_parse("not json")
        assert result is None


class TestReviewParse:
    """测试 review 结果解析"""

    def test_valid_review(self) -> None:
        text = """
        ```json
        {
          "verdict": "Request Changes",
          "score": 6,
          "summary": "Logic correct but missing tests",
          "comments": [
            {
              "file": "src/main.py",
              "line": 42,
              "body": "Missing null check",
              "severity": "blocker"
            }
          ]
        }
        ```
        """
        result = review_parse(text)
        assert result is not None
        assert result.verdict == "Request Changes"
        assert result.score == 6
        assert len(result.comments) == 1
        assert result.comments[0].file == "src/main.py"
        assert result.comments[0].severity == "blocker"

    def test_invalid_returns_none(self) -> None:
        result = review_parse("no json")
        assert result is None


class TestImplementParse:
    """测试 implement 结果解析"""

    def test_valid_implement(self) -> None:
        text = """
        ```json
        {
          "branch_name": "feat/issue-42",
          "summary": "Add user authentication",
          "files_changed": ["src/auth.py", "tests/test_auth.py"],
          "pr_url": null,
          "ready_for_review": true
        }
        ```
        """
        result = implement_parse(text)
        assert result is not None
        assert result.branch_name == "feat/issue-42"
        assert len(result.files_changed) == 2
        assert result.ready_for_review is True

    def test_invalid_returns_none(self) -> None:
        result = implement_parse("not json")
        assert result is None


class TestEvaluatorPrompt:
    """测试 evaluator prompt 构建和解析"""

    def test_build_prompt(self) -> None:
        from dataclasses import dataclass

        @dataclass
        class FakeResult:
            labels: list
            priority: str

        results = [
            FakeResult(labels=["bug"], priority="P1"),
            FakeResult(labels=["enhancement"], priority="P2"),
        ]
        prompt = build_evaluation_prompt(results, "Triage 结果", ["run_0", "run_1"])
        assert "2 个 Triage 结果" in prompt
        assert "run_0" in prompt
        assert "run_1" in prompt
        assert "bug" in prompt
        assert "enhancement" in prompt

    def test_parse_evaluation_valid(self) -> None:
        text = """
        ```json
        {
          "winner": 0,
          "scores": {"0": 0.85, "1": 0.72},
          "reasoning": "First result is more complete"
        }
        ```
        """
        result = _parse_evaluation_result(text)
        assert result is not None
        assert result.winner == 0
        assert 0 in result.scores
        assert 1 in result.scores

    def test_parse_evaluation_no_json_returns_none(self) -> None:
        result = _parse_evaluation_result("no json here")
        assert result is None
