"""Agent 候选结果选优公共能力。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SelectionResult:
    """select_best_result 的返回值，包含选择结果和是否发生回退。"""

    index: int
    result: T
    is_fallback: bool


async def select_best_result(
    results: list[T],
    *,
    result_type: str,
    result_names: list[str] | None = None,
    model: str = "",
    max_turns: int | None = None,
) -> SelectionResult[T]:
    """使用 evaluator 在多个候选结果中选出最佳结果。"""
    if not results:
        raise ValueError("results must not be empty")

    if len(results) == 1:
        return SelectionResult(index=0, result=results[0], is_fallback=False)

    from gearbox.agents.evaluator import run_evaluator

    evaluation = await run_evaluator(
        results=results,
        result_type=result_type,
        result_names=result_names,
        model=model,
        **({"max_turns": max_turns} if max_turns is not None else {}),
    )

    if 0 <= evaluation.winner < len(results):
        return SelectionResult(
            index=evaluation.winner,
            result=results[evaluation.winner],
            is_fallback=False,
        )

    # Evaluator 返回了越界索引，回退到 index 0 并记录告警
    logger.warning(
        "Evaluator returned out-of-bounds winner=%d for %d candidates; falling back to index 0",
        evaluation.winner,
        len(results),
    )
    return SelectionResult(index=0, result=results[0], is_fallback=True)
