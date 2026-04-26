"""Agent 候选结果选优公共能力。"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


async def select_best_result(
    results: list[T],
    *,
    result_type: str,
    result_names: list[str] | None = None,
    model: str = "",
    max_turns: int | None = None,
) -> tuple[int, T]:
    """使用 evaluator 在多个候选结果中选出最佳结果。"""
    if not results:
        raise ValueError("results must not be empty")

    if len(results) == 1:
        return 0, results[0]

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
