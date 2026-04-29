"""测试 Fix Agent — TDD 驱动。"""

from typing import Any

import pytest
from claude_agent_sdk import ResultMessage
from pydantic import ValidationError

from gearbox.agents.schemas import parse_with_model


class TestFixResultSchema:
    """FixResult Pydantic 模型校验。"""

    def _result(self, data: dict[str, Any]) -> ResultMessage:
        return ResultMessage(
            subtype="result",
            duration_ms=100,
            duration_api_ms=80,
            is_error=False,
            num_turns=1,
            session_id="session",
            structured_output=data,
        )

    def test_fix_result_from_valid_data(self) -> None:
        from gearbox.agents.schemas.fix import FixResult

        result = FixResult.model_validate(
            {
                "verdict": "fixed",
                "commits_pushed": 2,
                "files_modified": ["src/foo.py", "tests/test_foo.py"],
                "still_has_issues": False,
            }
        )
        assert result.verdict == "fixed"
        assert result.commits_pushed == 2
        assert len(result.files_modified) == 2
        assert result.still_has_issues is False
        assert result.failure_reason is None

    def test_fix_result_defaults(self) -> None:
        from gearbox.agents.schemas.fix import FixResult

        result = FixResult.model_validate(
            {
                "verdict": "skipped",
                "commits_pushed": 0,
                "files_modified": [],
                "still_has_issues": True,
            }
        )
        assert result.verdict == "skipped"
        assert result.commits_pushed == 0
        assert result.files_modified == []
        assert result.still_has_issues is True
        assert result.failure_reason is None

    def test_fix_result_rejects_invalid_verdict(self) -> None:
        from gearbox.agents.schemas.fix import FixResult

        with pytest.raises(ValidationError):
            FixResult.model_validate(
                {
                    "verdict": "invalid",
                    "commits_pushed": 1,
                    "files_modified": ["x.py"],
                    "still_has_issues": False,
                }
            )

    def test_fix_result_rejects_negative_commits(self) -> None:
        from gearbox.agents.schemas.fix import FixResult

        with pytest.raises(ValidationError):
            FixResult.model_validate(
                {
                    "verdict": "fixed",
                    "commits_pushed": -1,
                    "files_modified": [],
                    "still_has_issues": False,
                }
            )

    def test_fix_result_accepts_failure_reason(self) -> None:
        from gearbox.agents.schemas.fix import FixResult

        result = FixResult.model_validate(
            {
                "verdict": "partial",
                "commits_pushed": 1,
                "files_modified": ["x.py"],
                "still_has_issues": True,
                "failure_reason": "Could not resolve import conflict",
            }
        )
        assert result.verdict == "partial"
        assert result.failure_reason == "Could not resolve import conflict"

    def test_parse_with_model_fix_result(self) -> None:
        from gearbox.agents.schemas.fix import FixResult

        message = self._result(
            {
                "verdict": "fixed",
                "commits_pushed": 3,
                "files_modified": ["a.py", "b.py"],
                "still_has_issues": False,
            }
        )
        result = parse_with_model(message, FixResult)
        assert result is not None
        assert result.verdict == "fixed"

    def test_fix_result_model_dump_roundtrip(self) -> None:
        from gearbox.agents.schemas.fix import FixResult

        original = {
            "verdict": "fixed",
            "commits_pushed": 1,
            "files_modified": ["hello.py"],
            "still_has_issues": False,
        }
        model = FixResult.model_validate(original)
        dumped = model.model_dump()
        roundtrip = FixResult.model_validate(dumped)
        assert roundtrip.verdict == model.verdict
        assert roundtrip.commits_pushed == model.commits_pushed


class TestReviewFixLoop:
    """Review-Fix Loop 编排逻辑 — 纯决策单元测试。"""

    def _make_review(self, verdict, score, **kwargs) -> Any:
        from gearbox.agents.schemas.review import ReviewResult

        return ReviewResult.model_validate(
            {
                "verdict": verdict,
                "score": score,
                "summary": "test",
                "comments": [],
                **kwargs,
            }
        )

    def test_lgtm_skips_fix_loop(self) -> None:
        from gearbox.commands.agent import should_abandon, should_fix, should_merge_directly

        review = self._make_review("LGTM", 9)
        assert should_fix(review) is False
        assert should_merge_directly(review) is True
        assert should_abandon(review) is False

    def test_high_score_changes_requested_merges_directly(self) -> None:
        from gearbox.commands.agent import should_abandon, should_fix, should_merge_directly

        review = self._make_review("Request Changes", 8)
        assert should_fix(review) is False
        assert should_merge_directly(review) is True
        assert should_abandon(review) is False

    def test_high_score_9_merges_directly(self) -> None:
        from gearbox.commands.agent import should_merge_directly

        review = self._make_review("Request Changes", 9)
        assert should_merge_directly(review) is True

    def test_medium_score_enters_fix_loop(self) -> None:
        from gearbox.commands.agent import should_abandon, should_fix, should_merge_directly

        review = self._make_review("Request Changes", 6)
        assert should_fix(review) is True
        assert should_merge_directly(review) is False
        assert should_abandon(review) is False

    def test_low_score_abandons_pr(self) -> None:
        from gearbox.commands.agent import should_abandon, should_fix, should_merge_directly

        review = self._make_review("Request Changes", 3)
        assert should_fix(review) is False
        assert should_merge_directly(review) is False
        assert should_abandon(review) is True

    def test_comment_only_does_not_enter_fix(self) -> None:
        from gearbox.commands.agent import should_fix

        review = self._make_review("Comment Only", 5)
        assert should_fix(review) is False

    def test_fix_loop_max_two_iterations(self) -> None:
        from gearbox.commands.agent import FixLoopDecision, FixLoopOutcome, evaluate_fix_loop

        # Simulate: round 1 score goes 5→7 (improving), round 2 stays at 7
        decisions = [
            FixLoopDecision(
                round_num=1,
                review=self._make_review("Request Changes", 5),
                should_fix=True,
                should_merge=False,
                should_abandon=False,
            ),
            FixLoopDecision(
                round_num=2,
                review=self._make_review("Request Changes", 7),
                should_fix=True,  # still in 5-7 range after improvement
                should_merge=False,
                should_abandon=False,
            ),
            FixLoopDecision(
                round_num=3,
                review=self._make_review("Request Changes", 7),
                should_fix=False,  # max 2 rounds reached
                should_merge=True,  # force merge after max rounds
                should_abandon=False,
            ),
        ]
        result = evaluate_fix_loop(decisions, max_rounds=2)
        assert result == FixLoopOutcome.MERGE_AFTER_MAX_ROUNDS

    def test_fix_loop_score_decrease_aborts(self) -> None:
        from gearbox.commands.agent import FixLoopDecision, FixLoopOutcome, evaluate_fix_loop

        decisions = [
            FixLoopDecision(
                round_num=1,
                review=self._make_review("Request Changes", 6),
                should_fix=True,
                should_merge=False,
                should_abandon=False,
            ),
            FixLoopDecision(
                round_num=2,
                review=self._make_review("Request Changes", 4),  # score dropped!
                should_fix=True,
                should_merge=False,
                should_abandon=True,  # abort on degradation
            ),
        ]
        result = evaluate_fix_loop(decisions, max_rounds=2)
        assert result == FixLoopOutcome.ABANDONDED_SCORE_DROPPED

    def test_fix_loop_second_round_lgtm_merges(self) -> None:
        from gearbox.commands.agent import FixLoopDecision, FixLoopOutcome, evaluate_fix_loop

        decisions = [
            FixLoopDecision(
                round_num=1,
                review=self._make_review("Request Changes", 6),
                should_fix=True,
                should_merge=False,
                should_abandon=False,
            ),
            FixLoopDecision(
                round_num=2,
                review=self._make_review("LGTM", 10),
                should_fix=False,
                should_merge=True,
                should_abandon=False,
            ),
        ]
        result = evaluate_fix_loop(decisions, max_rounds=2)
        assert result == FixLoopOutcome.MERGED

    def test_fix_loop_first_round_lgtm_merges(self) -> None:
        from gearbox.commands.agent import FixLoopDecision, FixLoopOutcome, evaluate_fix_loop

        decisions = [
            FixLoopDecision(
                round_num=1,
                review=self._make_review("LGTM", 10),
                should_fix=False,
                should_merge=True,
                should_abandon=False,
            ),
        ]
        result = evaluate_fix_loop(decisions, max_rounds=2)
        assert result == FixLoopOutcome.MERGED

    def test_fix_loop_all_skipped_abandons(self) -> None:
        from gearbox.commands.agent import FixLoopDecision, FixLoopOutcome, evaluate_fix_loop

        decisions = [
            FixLoopDecision(
                round_num=1,
                review=self._make_review("Request Changes", 0),
                should_fix=False,
                should_merge=False,
                should_abandon=True,
            ),
        ]
        result = evaluate_fix_loop(decisions, max_rounds=2)
        assert result == FixLoopOutcome.ABANDONDED


class TestFixAgent:
    """Fix Agent 核心逻辑 — mock 测试。"""

    def _result(self, data: dict[str, Any]) -> ResultMessage:
        return ResultMessage(
            subtype="result",
            duration_ms=100,
            duration_api_ms=80,
            is_error=False,
            num_turns=1,
            session_id="session",
            structured_output=data,
        )

    def test_build_fix_prompt_includes_pr_context(self) -> None:
        from gearbox.agents.fix import build_fix_prompt

        pr_info = {
            "title": "Fix secret leakage",
            "headRefName": "feat/issue-23-run-0",
            "baseRefName": "main",
        }
        review_comments = [
            {
                "file": "actions/audit/action.yml",
                "line": 15,
                "body": "Missing env: for ANTHROPIC_AUTH_TOKEN",
                "severity": "blocker",
            },
            {"file": "actions/review/action.yml", "body": "Same issue here", "severity": "blocker"},
        ]

        prompt = build_fix_prompt("owner/repo", 42, pr_info, review_comments)

        assert "owner/repo" in prompt
        assert "#42" in prompt
        assert "feat/issue-23-run-0" in prompt
        assert "Fix secret leakage" in prompt

    def test_build_fix_prompt_includes_review_comments(self) -> None:
        from gearbox.agents.fix import build_fix_prompt

        review_comments = [
            {
                "file": "actions/audit/action.yml",
                "line": 15,
                "body": "Missing env:",
                "severity": "blocker",
            },
            {"file": "src/foo.py", "body": "Add type hints", "severity": "warning"},
        ]

        prompt = build_fix_prompt("o/r", 1, {}, review_comments)

        assert "Missing env:" in prompt
        assert "Add type hints" in prompt
        assert "blocker" in prompt
        assert "warning" in prompt

    def test_build_fix_prompt_empty_comments(self) -> None:
        from gearbox.agents.fix import build_fix_prompt

        prompt = build_fix_prompt("o/r", 1, {}, [])
        assert len(prompt) > 0  # should still produce a valid prompt

    def test_run_fix_returns_parsed_result(self, monkeypatch) -> None:
        from gearbox.agents.fix import FixResult, run_fix

        async def fake_query(*args, **kwargs):
            del args, kwargs
            yield self._result(
                {
                    "verdict": "fixed",
                    "commits_pushed": 1,
                    "files_modified": ["actions/audit/action.yml"],
                    "still_has_issues": False,
                }
            )

        class FakeLogger:
            def log_start(self, **kw) -> None:
                pass

            def handle_message(self, *args, **kwargs) -> None:
                pass

            def log_completion(self) -> None:
                pass

        def fake_prepare(*args, **kwargs):
            return args[0] if args else kwargs.get("options"), FakeLogger()

        monkeypatch.setattr(
            "gearbox.agents.fix._gh_pr_view",
            lambda *a, **k: {"title": "T", "body": "B", "headRefName": "feat/issue-1"},
        )
        monkeypatch.setattr("gearbox.agents.shared.runtime.query", fake_query)
        monkeypatch.setattr("gearbox.agents.shared.runtime.prepare_agent_options", fake_prepare)

        import asyncio

        result = asyncio.run(run_fix("owner/repo", 42))
        assert isinstance(result, FixResult)
        assert result.verdict == "fixed"
        assert result.commits_pushed == 1

    def test_run_fix_uses_correct_output_format(self, monkeypatch) -> None:
        from gearbox.agents.fix import run_fix
        from gearbox.agents.schemas import output_format_schema

        captured_options: list[dict[str, Any]] = []

        def capture_options(options):
            captured_options.append({"output_format": options.output_format})
            return options, FakeLogger()

        monkeypatch.setattr("gearbox.agents.schemas.output_format_schema", output_format_schema)
        monkeypatch.setattr(
            "gearbox.agents.fix._gh_pr_view", lambda *a, **k: {"title": "T", "headRefName": "f/i-1"}
        )

        async def fake_query(*args, **kwargs):
            del args, kwargs
            yield object()  # never yields structured output so format is still captured

        class FakeLogger:
            def log_start(self, **kw) -> None:
                pass

            def handle_message(self, *args, **kwargs) -> None:
                pass

            def log_completion(self) -> None:
                pass

        def fake_prepare(*args, **kwargs):
            opts = args[0] if args else kwargs.get("options")
            capture_options(opts)
            return opts, FakeLogger()

        monkeypatch.setattr("gearbox.agents.shared.runtime.query", fake_query)
        monkeypatch.setattr("gearbox.agents.shared.runtime.prepare_agent_options", fake_prepare)

        import asyncio

        try:
            asyncio.run(run_fix("o/r", 1))
        except RuntimeError:
            pass  # expected: no structured output

        assert len(captured_options) >= 1
        fmt = captured_options[0]["output_format"]
        assert fmt["name"] == "FixResult"
        schema = fmt["schema"]
        assert "verdict" in schema["properties"]
        assert "commits_pushed" in schema["properties"]

    def test_run_fix_failure_raises(self, monkeypatch) -> None:
        from gearbox.agents.fix import run_fix

        async def fake_query_no_structured(*args, **kwargs):
            del args, kwargs
            yield object()  # not a ResultMessage with structured_output

        class FakeLogger:
            def log_start(self, **kw) -> None:
                pass

            def handle_message(self, *args, **kwargs) -> None:
                pass

            def log_completion(self) -> None:
                pass

        def fake_prepare(*args, **kwargs):
            return args[0] if args else kwargs.get("options"), FakeLogger()

        monkeypatch.setattr(
            "gearbox.agents.fix._gh_pr_view", lambda *a, **k: {"title": "T", "headRefName": "f/i-1"}
        )
        monkeypatch.setattr("gearbox.agents.shared.runtime.query", fake_query_no_structured)
        monkeypatch.setattr("gearbox.agents.shared.runtime.prepare_agent_options", fake_prepare)

        import asyncio

        with pytest.raises(RuntimeError, match="did not return structured output"):
            asyncio.run(run_fix("o/r", 1))


class TestFixCLI:
    """Fix Agent CLI 集成 — Click 命令注册测试。"""

    def test_fix_command_exists(self) -> None:
        from gearbox.commands.agent import agent

        fix_cmd = agent.commands.get("fix")
        assert fix_cmd is not None
        assert fix_cmd.name == "fix"

    def test_fix_command_requires_repo(self) -> None:
        import click.testing

        from gearbox.commands.agent import agent

        runner = click.testing.CliRunner()
        result = runner.invoke(agent, ["fix"])
        assert result.exit_code != 0
        assert "--repo" in result.output

    def test_fix_command_requires_pr(self) -> None:
        import click.testing

        from gearbox.commands.agent import agent

        runner = click.testing.CliRunner()
        result = runner.invoke(agent, ["fix", "--repo", "owner/repo"])
        assert result.exit_code != 0
        assert "--pr" in result.output

    def test_fix_command_accepts_all_options(self) -> None:
        from gearbox.commands.agent import agent

        fix_cmd = agent.commands.get("fix")
        assert fix_cmd is not None
        params = {p.name for p in fix_cmd.params}
        assert "repo" in params
        assert "pr" in params
        assert "model" in params
        assert "max_turns" in params
