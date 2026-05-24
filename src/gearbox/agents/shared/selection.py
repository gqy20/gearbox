"""Agent 候选结果选优公共能力。"""

from __future__ import annotations

import logging
from typing import TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)

_DEGRADATION_THRESHOLD_RATIO = 0.5


def _check_degradation(actual_count: int, max_runs: int) -> None:
    """当实际结果数低于预期运行数的阈值时记录降级警告。

    仅在 ``max_runs > 0`` 时启用检测。当 ``actual_count < max_runs * 阈值`` 时
    发出 WARNING 级别日志，提示聚合器正在降级运行。
    """
    if max_runs <= 0:
        return

    threshold = max_runs * _DEGRADATION_THRESHOLD_RATIO
    if actual_count < threshold:
        ratio_pct = actual_count / max_runs * 100
        logger.warning(
            "Selection degradation detected: %d/%d results available (%.0f%%). "
            "Expected at least %d results (%.0f%% of %d runs) for reliable consensus. "
            "Evaluator selection skipped for single-result fallback.",
            actual_count,
            max_runs,
            ratio_pct,
            int(threshold),
            _DEGRADATION_THRESHOLD_RATIO * 100,
            max_runs,
        )


async def select_best_result(
    results: list[T],
    *,
    result_type: str,
    result_names: list[str] | None = None,
    model: str = "",
    max_turns: int | None = None,
    max_runs: int = 0,
) -> tuple[int, T]:
    """使用 evaluator 在多个候选结果中选出最佳结果。

    Args:
        results: 候选结果列表。
        result_type: 结果类型描述（用于 evaluator prompt）。
        result_names: 可选的名称列表。
        model: 使用的模型。
        max_turns: evaluator 最大对话轮次。
        max_runs: 预期的并行运行总数。当大于 0 且实际结果数低于阈值的 50%
            时，记录降级警告以提示聚合质量下降。
    """
    if not results:
        raise ValueError("results must not be empty")

    _check_degradation(len(results), max_runs)

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
