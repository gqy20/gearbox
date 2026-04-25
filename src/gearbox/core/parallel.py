"""并行执行基础设施 - 通用并行执行器"""

import asyncio
from typing import Any, Callable, Coroutine, TypeVar

from gearbox.agents.evaluator import run_evaluator
from gearbox.config import get_anthropic_model

T = TypeVar("T")  # Result type


async def run_parallel(
    agent_factory: Callable[[str], Coroutine[Any, Any, T]],
    angles: list[str],
    result_type: str,
    *,
    model: str | None = None,
    max_turns: int = 5,
) -> dict[str, Any]:
    """
    通用并行执行器。

    Args:
        agent_factory: 工厂函数，接受 angle 参数，返回 agent 结果
        angles: 角度列表
        result_type: 结果类型描述
        model: 使用的模型
        max_turns: 最大对话轮次

    Returns:
        {
            "result": T,                    # 最佳结果
            "all_results": list[T],          # 所有结果
            "evaluation": EvaluationResult, # 评估结果
        }
    """
    resolved_model = model or get_anthropic_model()

    # 并行运行
    tasks = [agent_factory(angle) for angle in angles]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 过滤异常
    valid_results: list[T] = []
    for r in results:
        if isinstance(r, Exception):
            print(f"⚠️ Instance failed: {r}")
        else:
            valid_results.append(r)  # type: ignore[arg-type]

    if not valid_results:
        return {
            "result": None,
            "all_results": [],
            "evaluation": None,
        }

    # 使用 Evaluator 选择最佳结果
    evaluation = await run_evaluator(
        results=valid_results,
        result_type=result_type,
        result_names=angles[: len(valid_results)],
        model=resolved_model,
        max_turns=max_turns,
    )

    # 获取评估选中的最佳结果
    best_result = (
        valid_results[evaluation.winner]
        if evaluation.winner < len(valid_results)
        else valid_results[0]
    )

    return {
        "result": best_result,
        "all_results": valid_results,
        "evaluation": evaluation,
    }
