"""并行执行基础设施 - 通用并行执行器"""

import asyncio
import traceback
from typing import Any, Callable, Coroutine, TypeVar

T = TypeVar("T")  # Result type


async def run_parallel(
    agent_factory: Callable[[str], Coroutine[Any, Any, T]],
    angles: list[str],
    *,
    model: str | None = None,
) -> list[T]:
    """
    通用并行执行器。

    Args:
        agent_factory: 工厂函数，接受 angle 参数，返回 agent 结果
        angles: 角度列表
        model: 使用的模型（暂未使用，保留扩展性）

    Returns:
        所有 agent 实例结果的列表
    """
    # 并行运行
    tasks = [agent_factory(angle) for angle in angles]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 过滤异常
    valid_results: list[T] = []
    for angle, r in zip(angles, results, strict=False):
        if isinstance(r, Exception):
            print(f"⚠️ Instance failed [{angle}]: {type(r).__name__}: {r}")
            stderr = getattr(r, "stderr", None)
            if stderr:
                print(f"stderr[{angle}]: {stderr}")
            tb = "".join(traceback.format_exception(type(r), r, r.__traceback__))
            if tb.strip():
                print(f"traceback[{angle}]:\n{tb}")
        else:
            valid_results.append(r)  # type: ignore[arg-type]

    return valid_results
