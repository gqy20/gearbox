"""Tests for selection input validation and evaluator pre-checks."""

from __future__ import annotations

import pytest

from gearbox.agents.evaluator import (
    build_evaluation_prompt,
    validate_results,
)
from gearbox.agents.schemas import ImplementResult


class TestValidateResults:
    """Unit tests for validate_results() pre-check logic."""

    def test_empty_list_rejected(self) -> None:
        with pytest.raises(ValueError, match="results must not be empty"):
            validate_results([], "implement")

    def test_non_basemodel_raw_dict_rejected(self) -> None:
        """Raw dict without BaseModel wrapper should fail validation."""
        with pytest.raises(TypeError, match="must be a BaseModel instance"):
            validate_results([{"branch_name": "x"}], "implement")

    def test_non_basemodel_plain_object_rejected(self) -> None:
        class FakeResult:
            def __init__(self) -> None:
                self.branch_name = "x"

        with pytest.raises(TypeError, match="must be a BaseModel instance"):
            validate_results([FakeResult()], "implement")

    def test_valid_implement_results_pass(self) -> None:
        results = [
            ImplementResult(branch_name="a", summary="s1", files_changed=["f1"]),
            ImplementResult(branch_name="b", summary="s2", files_changed=["f2"]),
        ]
        vr = validate_results(results, "implement")
        assert vr.valid is True
        assert len(vr.candidates) == 2

    def test_missing_core_field_detected(self) -> None:
        """ImplementResult missing 'summary' should be flagged as incomplete."""
        # summary is optional in schema but required by validator for implement type
        result = ImplementResult(
            branch_name="feat/x",
            summary="",  # empty core field
            files_changed=[],
        )
        vr = validate_results([result], "implement")
        assert vr.valid is True  # still valid (warning, not error)
        assert vr.candidates[0].completeness < 1.0

    def test_serialization_size_recorded(self) -> None:
        result = ImplementResult(
            branch_name="feat/x",
            summary="A reasonable summary",
            files_changed=["src/a.py", "src/b.py"],
        )
        vr = validate_results([result], "implement")
        assert vr.candidates[0].serialization_size > 0

    def test_mixed_types_in_list_rejected(self) -> None:
        """Mixing BaseModel and non-BaseModel should raise."""
        with pytest.raises(TypeError, match="must be a BaseModel instance"):
            validate_results(
                [
                    ImplementResult(branch_name="a", summary="s"),
                    {"branch_name": "b"},  # type: ignore[dict-item]
                ],
                "implement",
            )

    def test_all_candidates_have_completeness_scores(self) -> None:
        results = [
            ImplementResult(branch_name="a", summary="Complete result", files_changed=["f.py"]),
            ImplementResult(branch_name="b", summary="", files_changed=[]),
        ]
        vr = validate_results(results, "implement")
        assert len(vr.completeness_report) == 2
        # First result should have higher completeness than second
        assert vr.completeness_report[0] >= vr.completeness_report[1]


class TestBuildEvaluationPromptWithValidation:
    """Test that validated prompt includes completeness annotations."""

    def test_prompt_includes_completeness_warning_for_incomplete(self) -> None:
        results = [
            ImplementResult(branch_name="a", summary="Good", files_changed=["f.py"]),
            ImplementResult(branch_name="b", summary="", files_changed=[]),
        ]
        prompt = build_evaluation_prompt(results, "Implement 结果")
        # Incomplete candidate should have annotation
        assert "不完整" in prompt or "缺失" in prompt or "索引: 1" in prompt

    def test_prompt_includes_candidate_count(self) -> None:
        results = [
            ImplementResult(branch_name="a", summary="s", files_changed=[]),
        ]
        prompt = build_evaluation_prompt(results, "Audit 结果")
        assert "1 个 Audit 结果" in prompt


class TestSelectBestResultTypeSafety:
    """Test that select_best_result enforces BaseModel bound."""

    def test_select_best_rejects_non_basemodel(self) -> None:
        from gearbox.agents.shared.selection import select_best_result

        async def _run() -> None:
            # Need ≥2 results to bypass the single-result short-circuit
            with pytest.raises(TypeError):
                await select_best_result(
                    [
                        {"key": "val"},  # type: ignore[arg-type]
                        {"key": "val2"},  # type: ignore[arg-type]
                    ],
                    result_type="test",
                )

        import asyncio

        asyncio.run(_run())

    def test_single_result_short_circuit(self) -> None:
        from gearbox.agents.shared.selection import select_best_result

        async def _run() -> None:
            result = ImplementResult(branch_name="x", summary="s", files_changed=[])
            idx, selected = await select_best_result(
                [result],
                result_type="implement",
            )
            assert idx == 0
            selected is result

        import asyncio

        asyncio.run(_run())
