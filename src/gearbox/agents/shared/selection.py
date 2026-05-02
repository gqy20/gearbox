"""Agent 候选结果选优公共能力。"""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel

from gearbox.agents.evaluator import validate_results

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


async def select_best_result(
    results: list[T],
    *,
    result_type: str,
    result_names: list[str] | None = None,
    model: str = "",
    max_turns: int | None = None,
) -> tuple[int, T]:
    """使用 evaluator 在多个候选结果中选出最佳结果。

    All *results* must be ``BaseModel`` instances so that serialisation
    format is consistent across candidates.  A pre-validation step checks
    type consistency and field completeness before the LLM evaluator is
    called.
    """
    if not results:
        raise ValueError("results must not be empty")

    if len(results) == 1:
        return 0, results[0]

    # Pre-validate for type consistency and field completeness
    try:
        vr = validate_results(results, result_type)
    except (TypeError, ValueError) as exc:
        logger.error("select_best_result validation failed: %s", exc)
        raise

    logger.info(
        "select_best_result: %d candidates validated, completeness=%s",
        len(results),
        [f"{c:.2f}" for c in vr.completeness_report],
    )

    from gearbox.agents.evaluator import run_evaluator

    evaluation = await run_evaluator(
        results=results,
        result_type=result_type,
        result_names=result_names,
        model=model,
        **({"max_turns": max_turns} if max_turns is not None else {}),
    )
    winner_index = evaluation.winner if 0 <= evaluation.winner < len(results) else 0
    return winner_index, results[winner_index]
