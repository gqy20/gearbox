"""Tests for the Evaluator agent — prompt building, result parsing, and run_evaluator SDK integration."""

import asyncio

import pytest

from gearbox.agents.evaluator import (
    DEFAULT_EVALUATOR_MAX_TURNS,
    _format_result_for_prompt,
    build_evaluation_prompt,
)
from gearbox.agents.schemas import EvaluationResult
from gearbox.agents.schemas.evaluator import ScoreItem

# ---------------------------------------------------------------------------
# Pure function tests: _format_result_for_prompt
# ---------------------------------------------------------------------------


class TestFormatResultForPrompt:
    def test_model_dump_result(self) -> None:
        class FakeModel:
            def model_dump(self) -> dict:
                return {"key": "value", "nested": {"a": 1}}

        result = _format_result_for_prompt(FakeModel())
        assert '"key": "value"' in result
        assert '"nested":' in result

    def test_dict_result(self) -> None:
        result = _format_result_for_prompt({"foo": "bar"})
        assert '"foo": "bar"' in result

    def test_plain_object_uses_dict(self) -> None:
        class PlainObj:
            def __init__(self) -> None:
                self.public = "yes"
                self._private = "no"

        result = _format_result_for_prompt(PlainObj())
        assert '"public": "yes"' in result
        assert "_private" not in result

    def test_string_fallback(self) -> None:
        result = _format_result_for_prompt(42)
        assert result == "42"

    def test_none_and_bool(self) -> None:
        assert _format_result_for_prompt(None) == "None"
        assert _format_result_for_prompt(True) == "True"


# ---------------------------------------------------------------------------
# Pure function tests: build_evaluation_prompt
# ---------------------------------------------------------------------------


class TestBuildEvaluationPrompt:
    def test_single_result_without_names(self) -> None:
        prompt = build_evaluation_prompt([{"a": 1}], "Audit 结果")
        assert "1 个 Audit 结果" in prompt
        assert "结果 0" in prompt
        assert '"a": 1' in prompt

    def test_multiple_results_with_custom_names(self) -> None:
        results = [{"id": 1}, {"id": 2}]
        prompt = build_evaluation_prompt(results, "Backlog 结果", ["质量角度", "安全角度"])
        assert "2 个 Backlog 结果" in prompt
        assert "质量角度" in prompt
        assert "安全角度" in prompt

    def test_includes_system_prompt(self) -> None:
        prompt = build_evaluation_prompt([], "test")
        # SYSTEM_PROMPT should be appended at the end
        assert "评估专家" in prompt
        assert "评估维度" in prompt

    def test_empty_results_list(self) -> None:
        prompt = build_evaluation_prompt([], "empty type")
        assert "0 个 empty type" in prompt

    def test_name_count_less_than_results_falls_back_to_default(self) -> None:
        """When result_names has fewer entries than results, extra ones use default."""
        results = [{"a": 1}, {"b": 2}, {"c": 3}]
        prompt = build_evaluation_prompt(results, "test", ["only_one"])
        assert "only_one" in prompt
        assert "结果 1" in prompt  # fallback for index 1
        assert "结果 2" in prompt  # fallback for index 2

    def test_result_names_none_uses_defaults(self) -> None:
        results = [{"x": "y"}]
        prompt = build_evaluation_prompt(results, "test", None)
        assert "结果 0" in prompt


# ---------------------------------------------------------------------------
# Integration test: run_evaluator with mocked SDK
# ---------------------------------------------------------------------------


class TestRunEvaluator:
    """Mock the full SDK stack to verify run_evaluator parses structured output correctly."""

    @staticmethod
    def _make_fake_query_stream(structured_data: dict):
        """Return an async generator that yields a real ResultMessage."""

        from claude_agent_sdk import ResultMessage

        msg = ResultMessage(
            subtype="result",
            duration_ms=500,
            duration_api_ms=400,
            is_error=False,
            num_turns=5,
            session_id="test-session",
            structured_output=structured_data,
        )

        async def _fake_query(*args, **kwargs):
            del args, kwargs
            yield msg

        return _fake_query

    def test_run_evaluator_returns_parsed_result(self, monkeypatch) -> None:
        expected = {
            "winner": 0,
            "scores": {
                "0": {"score": 0.9, "justification": "Best coverage"},
                "1": {"score": 0.6, "justification": "Incomplete"},
            },
            "reasoning": "Result 0 is more complete and actionable.",
            "consensus": ["add-tests"],
        }

        monkeypatch.setattr(
            "claude_agent_sdk.query",
            self._make_fake_query_stream(expected),
        )

        class FakeLogger:
            def log_start(self, **kwargs) -> None:
                del kwargs

            def handle_message(self, *args, **kwargs) -> None:
                del args, kwargs

            def log_completion(self) -> None:
                pass

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime.prepare_agent_options",
            lambda options, agent_name: (options, FakeLogger()),
        )

        from gearbox.agents.evaluator import run_evaluator

        result = asyncio.run(
            run_evaluator(
                results=[{"data": "a"}, {"data": "b"}],
                result_type="Test 结果",
                model="test-model",
                max_turns=10,
            )
        )

        assert isinstance(result, EvaluationResult)
        assert result.winner == 0
        assert 0 in result.scores
        assert result.scores[0].score == 0.9
        assert result.scores[0].justification == "Best coverage"
        assert "more complete" in result.reasoning
        assert result.consensus == ["add-tests"]

    def test_run_evaluator_raises_on_no_structured_output(self, monkeypatch) -> None:
        from claude_agent_sdk import ResultMessage

        # Yield a ResultMessage with None structured_output → parse returns None
        msg = ResultMessage(
            subtype="result",
            duration_ms=100,
            duration_api_ms=80,
            is_error=False,
            num_turns=1,
            session_id="s",
            structured_output=None,
        )

        async def _fake_query_empty(*args, **kwargs):
            del args, kwargs
            yield msg

        monkeypatch.setattr("claude_agent_sdk.query", _fake_query_empty)

        class FakeLogger:
            def log_start(self, **kwargs) -> None:
                del kwargs

            def handle_message(self, *args, **kwargs) -> None:
                del args, kwargs

            def log_completion(self) -> None:
                pass

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime.prepare_agent_options",
            lambda options, agent_name: (options, FakeLogger()),
        )

        from gearbox.agents.evaluator import run_evaluator

        with pytest.raises(RuntimeError, match="did not return structured output"):
            asyncio.run(
                run_evaluator(
                    results=[{"x": 1}],
                    result_type="Test",
                    max_turns=5,
                )
            )

    def test_run_evaluator_uses_default_max_turns(self, monkeypatch) -> None:
        """Verify DEFAULT_EVALUATOR_MAX_TURNS is used when not overridden."""
        from claude_agent_sdk import ResultMessage

        captured_options: dict = {}

        msg = ResultMessage(
            subtype="result",
            duration_ms=100,
            duration_api_ms=80,
            is_error=False,
            num_turns=1,
            session_id="s",
            structured_output={
                "winner": 0,
                "scores": {"0": {"score": 1.0, "justification": "ok"}},
                "reasoning": "test",
            },
        )

        async def _fake_query(*args, **kwargs):
            del args, kwargs
            yield msg

        monkeypatch.setattr("claude_agent_sdk.query", _fake_query)

        class FakeLogger:
            def log_start(self, **kwargs) -> None:
                del kwargs

            def handle_message(self, *args, **kwargs) -> None:
                del args, kwargs

            def log_completion(self) -> None:
                pass

        def fake_prepare(options, agent_name):
            captured_options["max_turns"] = options.max_turns
            return options, FakeLogger()

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime.prepare_agent_options",
            fake_prepare,
        )

        from gearbox.agents.evaluator import run_evaluator

        asyncio.run(run_evaluator([{}], "T"))
        assert captured_options["max_turns"] == DEFAULT_EVALUATOR_MAX_TURNS

    def test_run_evaluator_passes_custom_max_turns(self, monkeypatch) -> None:
        from claude_agent_sdk import ResultMessage

        captured_options: dict = {}

        msg = ResultMessage(
            subtype="result",
            duration_ms=100,
            duration_api_ms=80,
            is_error=False,
            num_turns=1,
            session_id="s",
            structured_output={
                "winner": 0,
                "scores": {"0": {"score": 1.0, "justification": "ok"}},
                "reasoning": "t",
            },
        )

        async def _fake_query(*args, **kwargs):
            del args, kwargs
            yield msg

        monkeypatch.setattr("claude_agent_sdk.query", _fake_query)

        class FakeLogger:
            def log_start(self, **kwargs) -> None:
                del kwargs

            def handle_message(self, *args, **kwargs) -> None:
                del args, kwargs

            def log_completion(self) -> None:
                pass

        def fake_prepare(options, agent_name):
            captured_options["max_turns"] = options.max_turns
            return options, FakeLogger()

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime.prepare_agent_options",
            fake_prepare,
        )

        from gearbox.agents.evaluator import run_evaluator

        asyncio.run(run_evaluator([{}], "T", max_turns=7))
        assert captured_options["max_turns"] == 7


# ---------------------------------------------------------------------------
# Schema-level edge case tests
# ---------------------------------------------------------------------------


class TestEvaluationResultSchema:
    def test_default_values_for_optional_fields(self) -> None:
        result = EvaluationResult(winner=0)
        assert result.winner == 0
        assert result.scores == {}
        assert result.reasoning == ""
        assert result.consensus == []

    def test_accepts_valid_full_result(self) -> None:
        result = EvaluationResult(
            winner=2,
            scores={
                0: ScoreItem(score=0.8, justification="good"),
                1: ScoreItem(score=0.6, justification="ok"),
                2: ScoreItem(score=0.95, justification="best"),
            },
            reasoning="Winner 2 has highest score and best reasoning",
            consensus=["shared-point-a", "shared-point-b"],
        )
        assert result.winner == 2
        assert len(result.scores) == 3
        assert result.scores[2].score == 0.95

    def test_rejects_winner_negative(self) -> None:
        import pytest

        with pytest.raises(Exception):  # ValidationError
            EvaluationResult(winner=-1)

    def test_rejects_score_out_of_range(self) -> None:
        import pytest

        with pytest.raises(Exception):  # ValidationError
            EvaluationResult(
                scores={0: ScoreItem(score=1.5, justification="bad")},
            )
