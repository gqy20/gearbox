"""Tests for select_best_result — single-item fast path and multi-candidate evaluation."""

import asyncio

import pytest

from gearbox.agents.shared.selection import select_best_result

# ---------------------------------------------------------------------------
# Single-candidate fast path
# ---------------------------------------------------------------------------


class TestSelectBestResultSingleCandidate:
    """When only one result is provided, it should be returned immediately without calling the evaluator."""

    def test_single_item_returns_index_zero_and_item(self) -> None:
        item = {"data": "only-result"}

        async def _run():
            return await select_best_result(
                [item],
                result_type="Test",
            )

        idx, result = asyncio.run(_run())
        assert idx == 0
        assert result is item

    def test_single_item_with_extra_params_ignored(self) -> None:
        """model, max_turns, result_names should be irrelevant for single item."""
        item = {"x": 1}

        async def _run():
            return await select_best_result(
                [item],
                result_type="Test",
                model="unused-model",
                max_turns=99,
                result_names=["name"],
            )

        idx, result = asyncio.run(_run())
        assert idx == 0
        assert result is item


# ---------------------------------------------------------------------------
# Empty input error
# ---------------------------------------------------------------------------


class TestSelectBestResultEmpty:
    def test_empty_list_raises_valueerror(self) -> None:
        async def _run():
            return await select_best_result([], result_type="Test")

        with pytest.raises(ValueError, match="must not be empty"):
            asyncio.run(_run())


# ---------------------------------------------------------------------------
# Multi-candidate with mocked evaluator
# ---------------------------------------------------------------------------


class TestSelectBestResultMultiCandidate:
    """Verify multi-candidate path delegates to run_evaluator and returns winner."""

    def test_two_candidates_winner_is_first(self, monkeypatch) -> None:
        import asyncio

        from gearbox.agents.schemas.evaluator import EvaluationResult, ScoreItem

        fake_result = EvaluationResult(
            winner=0,
            scores={
                0: ScoreItem(score=0.9, justification="best"),
                1: ScoreItem(score=0.5, justification="worse"),
            },
            reasoning="First is better",
        )

        async def _fake_run_evaluator(*args, **kwargs):
            del args, kwargs
            return fake_result

        monkeypatch.setattr("gearbox.agents.evaluator.run_evaluator", _fake_run_evaluator)

        items = [{"id": "a"}, {"id": "b"}]

        async def _run():
            return await select_best_result(
                items,
                result_type="Test",
                result_names=["candidate_a", "candidate_b"],
            )

        idx, result = asyncio.run(_run())
        assert idx == 0
        assert result == {"id": "a"}

    def test_two_candidates_winner_is_second(self, monkeypatch) -> None:
        import asyncio

        from gearbox.agents.schemas.evaluator import EvaluationResult, ScoreItem

        fake_result = EvaluationResult(
            winner=1,
            scores={
                0: ScoreItem(score=0.4, justification="weak"),
                1: ScoreItem(score=0.95, justification="strong"),
            },
            reasoning="Second is much better",
        )

        async def _fake_run_evaluator(*args, **kwargs):
            del args, kwargs
            return fake_result

        monkeypatch.setattr("gearbox.agents.evaluator.run_evaluator", _fake_run_evaluator)

        items = ["first", "second"]

        async def _run():
            return await select_best_result(items, result_type="T")

        idx, result = asyncio.run(_run())
        assert idx == 1
        assert result == "second"

    def test_out_of_range_winner_clamps_to_zero(self, monkeypatch) -> None:
        """If winner index exceeds results length, should clamp to 0."""
        import asyncio

        from gearbox.agents.schemas.evaluator import EvaluationResult, ScoreItem

        fake_result = EvaluationResult(
            winner=99,  # out of range
            scores={
                0: ScoreItem(score=0.5, justification="ok"),
                1: ScoreItem(score=0.5, justification="ok"),
            },
            reasoning="bad winner index",
        )

        async def _fake_run_evaluator(*args, **kwargs):
            del args, kwargs
            return fake_result

        monkeypatch.setattr("gearbox.agents.evaluator.run_evaluator", _fake_run_evaluator)

        items = ["a", "b"]

        async def _run():
            return await select_best_result(items, result_type="T")

        idx, result = asyncio.run(_run())
        # Out-of-range winner → clamped to 0
        assert idx == 0
        assert result == "a"
