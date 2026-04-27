"""测试 agents 模块。"""

from dataclasses import dataclass

from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock

from gearbox.agents import backlog, implement
from gearbox.agents.audit import AuditResult, Issue
from gearbox.agents.backlog import (
    BacklogItemResult,
    BacklogResult,
    github_labels_for_backlog_item,
    parse_issue_numbers,
)
from gearbox.agents.evaluator import EvaluationResult, build_evaluation_prompt
from gearbox.agents.implement import SYSTEM_PROMPT as IMPLEMENT_SYSTEM_PROMPT
from gearbox.agents.implement import ImplementResult
from gearbox.agents.review import ReviewComment, ReviewResult
from gearbox.agents.shared.structured import parse_structured_output


def _result_message(data: dict) -> ResultMessage:
    return ResultMessage(
        subtype="result",
        duration_ms=100,
        duration_api_ms=80,
        is_error=False,
        num_turns=1,
        session_id="session",
        structured_output=data,
    )


class TestStructuredOutputParsing:
    """测试基于 structured_output 的结果映射。"""

    def test_audit_mapping(self) -> None:
        message = _result_message(
            {
                "repo": "owner/repo",
                "profile": {"language": "python"},
                "comparison_markdown": "# Comparison",
                "benchmarks": ["pallets/click"],
                "issues": [
                    {
                        "title": "Add type hints",
                        "body": "## Problem",
                        "labels": "high,enhancement",
                    }
                ],
            }
        )
        result = parse_structured_output(
            message,
            lambda data: AuditResult(
                repo=data["repo"],
                profile=data["profile"],
                comparison_markdown=data["comparison_markdown"],
                benchmarks=data["benchmarks"],
                issues=[Issue(**issue) for issue in data["issues"]],
            ),
        )
        assert result is not None
        assert result.repo == "owner/repo"
        assert len(result.issues) == 1

    def test_backlog_item_mapping(self) -> None:
        message = _result_message(
            {
                "labels": ["bug", "high-priority"],
                "priority": "P1",
                "complexity": "M",
                "needs_clarification": False,
                "clarification_question": None,
                "ready_to_implement": True,
            }
        )
        result = parse_structured_output(message, lambda data: BacklogItemResult(**data))
        assert result is not None
        assert result.labels == ["bug", "high-priority"]
        assert result.ready_to_implement is True

    def test_structured_output_tool_use_mapping(self) -> None:
        message = AssistantMessage(
            model="test-model",
            content=[
                ToolUseBlock(
                    id="toolu_1",
                    name="StructuredOutput",
                    input={
                        "labels": ["enhancement", "ci"],
                        "priority": "P2",
                        "complexity": "S",
                        "needs_clarification": False,
                        "clarification_question": None,
                        "ready_to_implement": True,
                    },
                )
            ],
        )

        result = parse_structured_output(message, lambda data: BacklogItemResult(**data))

        assert result is not None
        assert result.labels == ["enhancement", "ci"]
        assert result.priority == "P2"

    def test_backlog_item_maps_metadata_to_github_labels(self) -> None:
        result = BacklogItemResult(
            labels=["documentation", "enhancement", "P1"],
            priority="P1",
            complexity="M",
            needs_clarification=False,
            clarification_question=None,
            ready_to_implement=True,
        )

        assert github_labels_for_backlog_item(result) == [
            "documentation",
            "enhancement",
            "P1",
            "complexity:M",
            "ready-to-implement",
        ]

    def test_backlog_item_maps_clarification_status_to_github_label(self) -> None:
        result = BacklogItemResult(
            labels=["question"],
            priority="P2",
            complexity="S",
            needs_clarification=True,
            clarification_question="请补充复现步骤",
            ready_to_implement=False,
        )

        assert github_labels_for_backlog_item(result) == [
            "question",
            "P2",
            "complexity:S",
            "needs-clarification",
        ]

    def test_parse_issue_numbers(self) -> None:
        assert parse_issue_numbers("2, 5 6") == [2, 5, 6]

    def test_backlog_result_contains_issue_items(self) -> None:
        result = BacklogResult(
            items=[
                BacklogItemResult(
                    issue_number=5,
                    labels=["enhancement", "ci"],
                    priority="P2",
                    complexity="S",
                    needs_clarification=False,
                    clarification_question=None,
                    ready_to_implement=True,
                )
            ]
        )

        assert result.items[0].issue_number == 5

    def test_backlog_issue_view_keeps_labels_as_single_json_array(self, monkeypatch) -> None:
        captured_cmd: list[str] = []

        class FakeCompletedProcess:
            stdout = '{"title":"T","body":"B","labels":["bug","docs"],"state":"open"}'

        def fake_run(cmd: list[str], **kwargs) -> FakeCompletedProcess:
            del kwargs
            captured_cmd.extend(cmd)
            return FakeCompletedProcess()

        monkeypatch.setattr(backlog.subprocess, "run", fake_run)

        issue = backlog._gh_issue_view("owner/repo", 1)

        assert issue["labels"] == ["bug", "docs"]
        assert "{title:.title,body:.body,labels:[.labels[].name],state:.state}" in captured_cmd

    def test_review_mapping(self) -> None:
        message = _result_message(
            {
                "verdict": "Request Changes",
                "score": 6,
                "summary": "Logic correct but missing tests",
                "comments": [
                    {
                        "file": "src/main.py",
                        "line": 42,
                        "body": "Missing null check",
                        "severity": "blocker",
                    }
                ],
            }
        )
        result = parse_structured_output(
            message,
            lambda data: ReviewResult(
                verdict=data["verdict"],
                score=data["score"],
                summary=data["summary"],
                comments=[ReviewComment(**comment) for comment in data["comments"]],
            ),
        )
        assert result is not None
        assert result.comments[0].severity == "blocker"

    def test_implement_mapping(self) -> None:
        message = _result_message(
            {
                "branch_name": "feat/issue-42",
                "summary": "Add user authentication",
                "files_changed": ["src/auth.py", "tests/test_auth.py"],
                "pr_url": None,
                "ready_for_review": True,
            }
        )
        result = parse_structured_output(message, lambda data: ImplementResult(**data))
        assert result is not None
        assert result.branch_name == "feat/issue-42"

    def test_implement_prompt_leaves_git_side_effects_to_orchestrator(self) -> None:
        assert "不要" in IMPLEMENT_SYSTEM_PROMPT
        assert "git commit" in IMPLEMENT_SYSTEM_PROMPT
        assert "git push" in IMPLEMENT_SYSTEM_PROMPT
        assert "gh pr create" in IMPLEMENT_SYSTEM_PROMPT
        assert "外层 Gearbox 编排器会负责创建分支、提交、推送和 PR" in IMPLEMENT_SYSTEM_PROMPT

    def test_implement_issue_view_keeps_labels_as_single_json_array(self, monkeypatch) -> None:
        captured_cmd: list[str] = []

        class FakeCompletedProcess:
            stdout = '{"title":"T","body":"B","labels":["enhancement","P2"]}'

        def fake_run(cmd: list[str], **kwargs) -> FakeCompletedProcess:
            del kwargs
            captured_cmd.extend(cmd)
            return FakeCompletedProcess()

        monkeypatch.setattr(implement.subprocess, "run", fake_run)

        issue = implement._gh_issue_view("owner/repo", 2)

        assert issue["labels"] == ["enhancement", "P2"]
        assert "{title:.title,body:.body,labels:[.labels[].name]}" in captured_cmd

    def test_implement_agent_uses_current_workspace_as_sdk_cwd(self, monkeypatch, tmp_path) -> None:
        captured: dict[str, str] = {}

        async def fake_query(*args, **kwargs):
            del args, kwargs
            yield _result_message(
                {
                    "branch_name": "feat/issue-2",
                    "summary": "Fix parser",
                    "files_changed": ["src/gearbox/agents/backlog.py"],
                    "pr_url": None,
                    "ready_for_review": True,
                }
            )

        class FakeLogger:
            def log_start(self, **kwargs) -> None:
                del kwargs

            def handle_message(self, *args, **kwargs) -> None:
                del args, kwargs

            def log_completion(self) -> None:
                pass

        def fake_prepare_agent_options(options, agent_name):
            del agent_name
            captured["cwd"] = str(options.cwd)
            return options, FakeLogger()

        monkeypatch.setattr(implement, "_gh_issue_view", lambda *args: {"title": "T", "body": "B"})
        monkeypatch.setattr("claude_agent_sdk.query", fake_query)
        monkeypatch.setattr(
            "gearbox.agents.shared.runtime.prepare_agent_options",
            fake_prepare_agent_options,
        )
        monkeypatch.chdir(tmp_path)

        import asyncio

        asyncio.run(implement.run_implement("owner/repo", 2, model="test-model"))

        assert captured["cwd"] == str(tmp_path)

    def test_evaluator_mapping(self) -> None:
        message = _result_message(
            {
                "winner": 0,
                "scores": {"0": 0.85, "1": 0.72},
                "reasoning": "First result is more complete",
                "consensus": ["item-a"],
            }
        )
        result = parse_structured_output(
            message,
            lambda data: EvaluationResult(
                winner=int(data["winner"]),
                scores={int(k): float(v) for k, v in data["scores"].items()},
                reasoning=data["reasoning"],
                consensus=data["consensus"],
            ),
        )
        assert result is not None
        assert result.winner == 0
        assert 1 in result.scores


class TestEvaluatorPrompt:
    """测试 evaluator prompt 构建。"""

    def test_build_prompt(self) -> None:
        @dataclass
        class FakeResult:
            labels: list
            priority: str

        results = [
            FakeResult(labels=["bug"], priority="P1"),
            FakeResult(labels=["enhancement"], priority="P2"),
        ]
        prompt = build_evaluation_prompt(results, "Backlog 结果", ["run_0", "run_1"])
        assert "2 个 Backlog 结果" in prompt
        assert "run_0" in prompt
        assert "run_1" in prompt
        assert "bug" in prompt
        assert "enhancement" in prompt

    def test_build_prompt_with_nested_dataclasses(self) -> None:
        results = [
            AuditResult(
                repo="owner/repo",
                issues=[Issue(title="A", body="B", labels="high")],
            )
        ]
        prompt = build_evaluation_prompt(results, "Audit 审计结果", ["run_0"])
        assert "owner/repo" in prompt
        assert '"title": "A"' in prompt
