"""测试 agents 模块。"""

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from pydantic import ValidationError

from gearbox.agents import backlog, implement
from gearbox.agents.backlog import (
    BacklogResult,
    github_labels_for_backlog_item,
    parse_issue_numbers,
)
from gearbox.agents.evaluator import build_evaluation_prompt
from gearbox.agents.implement import SYSTEM_PROMPT as IMPLEMENT_SYSTEM_PROMPT
from gearbox.agents.schemas import (
    AuditResult,
    BacklogItemResult,
    EvaluationResult,
    ImplementResult,
    ReviewResult,
    parse_with_model,
)
from gearbox.agents.schemas.audit import Issue as AuditIssue
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
    """测试基于 structured output 的 Pydantic 模型解析。"""

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
        result = parse_with_model(message, AuditResult)
        assert result is not None
        assert result.repo == "owner/repo"
        assert len(result.issues) == 1

    def test_backlog_item_mapping(self) -> None:
        message = _result_message(
            {
                "labels": ["bug", "high-priority"],
                "priority": "P1",
                "complexity": "M",
                "ready_to_implement": True,
            }
        )
        result = parse_with_model(message, BacklogItemResult)
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
                        "ready_to_implement": True,
                    },
                )
            ],
        )

        result = parse_with_model(message, BacklogItemResult)

        assert result is not None
        assert result.labels == ["enhancement", "ci"]
        assert result.priority == "P2"

    def test_backlog_item_maps_metadata_to_github_labels(self) -> None:
        result = BacklogItemResult(
            labels=["documentation", "enhancement", "P1"],
            priority="P1",
            complexity="M",
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
            ready_to_implement=False,
        )

        assert github_labels_for_backlog_item(result) == [
            "question",
            "P2",
            "complexity:S",
        ]

    def test_parse_issue_numbers_basic(self) -> None:
        assert parse_issue_numbers("2, 5 6") == [2, 5, 6]

    def test_parse_issue_numbers_hash_prefix_single(self) -> None:
        assert parse_issue_numbers("#12") == [12]

    def test_parse_issue_numbers_hash_prefix_multiple(self) -> None:
        assert parse_issue_numbers("#12, #13") == [12, 13]

    def test_parse_issue_numbers_mixed_format(self) -> None:
        assert parse_issue_numbers("12 #13,14") == [12, 13, 14]

    def test_parse_issue_numbers_empty_input(self) -> None:
        assert parse_issue_numbers("") == []
        assert parse_issue_numbers("   ") == []

    def test_parse_issue_numbers_deduplication(self) -> None:
        assert parse_issue_numbers("#3, 3, #3") == [3]

    def test_parse_issue_numbers_invalid_token_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="无法解析 issue 编号: 'abc'"):
            parse_issue_numbers("12 abc")

    def test_parse_issue_numbers_invalid_token_shows_all_bad_tokens(self) -> None:
        with pytest.raises(ValueError, match="无法解析 issue 编号: 'abc', 'xyz'"):
            parse_issue_numbers("1 abc, xyz #4")

    def test_backlog_result_contains_issue_items(self) -> None:
        result = BacklogResult(
            items=[
                BacklogItemResult(
                    issue_number=5,
                    labels=["enhancement", "ci"],
                    priority="P2",
                    complexity="S",
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
        result = parse_with_model(message, ReviewResult)
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
        result = parse_with_model(message, ImplementResult)
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
                "scores": {
                    "0": {"score": 0.85, "justification": "Complete and actionable"},
                    "1": {"score": 0.72, "justification": "Missing details"},
                },
                "reasoning": "First result is more complete",
                "consensus": ["item-a"],
            }
        )

        result = parse_with_model(message, EvaluationResult)
        assert result is not None
        assert result.winner == 0
        assert 0 in result.scores
        assert result.scores[0].justification == "Complete and actionable"


class TestEvaluatorPrompt:
    """测试 evaluator prompt 构建。"""

    def test_build_prompt(self) -> None:
        class FakeResult:
            def __init__(self, labels: list, priority: str) -> None:
                self.labels = labels
                self.priority = priority

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
                issues=[AuditIssue(title="A", body="B", labels="high")],
            )
        ]
        prompt = build_evaluation_prompt(results, "Audit 审计结果", ["run_0"])
        assert "owner/repo" in prompt
        assert '"title": "A"' in prompt


class TestPydanticValidation:
    """Pydantic 运行时校验 — 验证非法数据被正确拒绝。"""

    def test_evaluator_rejects_non_numeric_score_key(self) -> None:
        """Regression: the original crash was int('score') on a bad key."""
        message = _result_message(
            {
                "winner": 0,
                "scores": {
                    "score": {"score": 0.9, "justification": "bad key"},
                    "0": {"score": 0.85, "justification": "ok"},
                },
                "reasoning": "test",
            }
        )
        result = parse_with_model(message, EvaluationResult)
        assert result is not None
        # Non-numeric keys should be silently dropped by BeforeValidator
        assert 0 in result.scores
        assert "score" not in result.scores  # type: ignore[operator]

    def test_evaluator_rejects_missing_winner(self) -> None:
        with pytest.raises(ValidationError):
            EvaluationResult.model_validate(
                {
                    "scores": {},
                    "reasoning": "no winner",
                }
            )

    def test_review_rejects_invalid_verdict(self) -> None:
        with pytest.raises(ValidationError):
            ReviewResult.model_validate(
                {
                    "verdict": "INVALID",
                    "score": 5,
                    "summary": "test",
                    "comments": [],
                }
            )

    def test_review_rejects_score_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            ReviewResult.model_validate(
                {
                    "verdict": "LGTM",
                    "score": 15,
                    "summary": "test",
                    "comments": [],
                }
            )

    def test_backlog_rejects_invalid_priority(self) -> None:
        with pytest.raises(ValidationError):
            BacklogItemResult.model_validate(
                {
                    "labels": ["bug"],
                    "priority": "P5",
                    "complexity": "M",
                    "ready_to_implement": False,
                }
            )


class TestStructuredOutputErrorPaths:
    """parse_with_model / parse_structured_output 的 None 返回路径（错误/边界输入）"""

    def _result(self, data) -> ResultMessage:
        return ResultMessage(
            subtype="result",
            duration_ms=100,
            duration_api_ms=80,
            is_error=False,
            num_turns=1,
            session_id="session",
            structured_output=data,
        )

    def _assistant(self, tool_input) -> AssistantMessage:
        return AssistantMessage(
            model="test",
            content=[ToolUseBlock(id="t1", name="StructuredOutput", input=tool_input)],
        )

    def test_result_message_with_none_structured_output_returns_none(self) -> None:
        result = parse_with_model(self._result(None), AuditResult)
        assert result is None

    def test_result_message_with_string_structured_output_returns_none(self) -> None:
        result = parse_with_model(self._result("not a dict"), AuditResult)
        assert result is None

    def test_result_message_with_list_structured_output_returns_none(self) -> None:
        result = parse_with_model(self._result([1, 2, 3]), AuditResult)
        assert result is None

    def test_assistant_message_with_empty_content_returns_none(self) -> None:
        msg = AssistantMessage(model="test", content=[])
        result = parse_with_model(msg, BacklogItemResult)
        assert result is None

    def test_assistant_message_with_text_block_returns_none(self) -> None:
        msg = AssistantMessage(model="test", content=[TextBlock(text="hello")])
        result = parse_with_model(msg, BacklogItemResult)
        assert result is None

    def test_assistant_message_with_wrong_tool_name_returns_none(self) -> None:
        msg = AssistantMessage(
            model="test",
            content=[ToolUseBlock(id="t1", name="OtherTool", input={"key": "val"})],
        )
        result = parse_with_model(msg, BacklogItemResult)
        assert result is None

    def test_assistant_message_with_non_dict_tool_input_returns_none(self) -> None:
        msg = AssistantMessage(
            model="test",
            content=[ToolUseBlock(id="t1", name="StructuredOutput", input="bad")],
        )
        result = parse_with_model(msg, BacklogItemResult)
        assert result is None

    def test_non_message_object_returns_none(self) -> None:
        for bad_input in [42, "string", [1, 2], {"key": "val"}, None]:
            result = parse_with_model(bad_input, BacklogItemResult)
            assert result is None

    def test_shared_structured_parse_with_model_is_deprecated(self) -> None:
        """shared.structured.parse_with_model 应发出 DeprecationWarning 并委托给 schemas."""
        import warnings

        from gearbox.agents.schemas import parse_with_model as schemas_parse
        from gearbox.agents.shared.structured import parse_with_model as shared_parse

        message = self._result(
            {"labels": ["bug"], "priority": "P1", "complexity": "S", "ready_to_implement": False}
        )

        # 调用 shared 版本应发出 DeprecationWarning
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = shared_parse(message, BacklogItemResult)
            # 确认功能正常（向后兼容）
            assert result is not None
            assert result.priority == "P1"
            # 确认发出了 DeprecationWarning
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1
            assert "deprecated" in str(deprecation_warnings[0].message).lower()

        # schemas 版本不应发出警告，且结果一致
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            schemas_result = schemas_parse(message, BacklogItemResult)
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) == 0
        assert schemas_result is not None
        assert result.model_dump() == schemas_result.model_dump()

    # Legacy parse_structured_output backward-compat tests
    def test_legacy_parse_structured_output_none(self) -> None:
        result = parse_structured_output(self._result(None), lambda data: data["key"])
        assert result is None

    def test_legacy_parse_structured_output_string(self) -> None:
        result = parse_structured_output(self._result("not a dict"), lambda data: data["key"])
        assert result is None
