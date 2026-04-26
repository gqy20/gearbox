"""Agent 执行公共能力。"""

from __future__ import annotations

import asyncio
import traceback
from typing import Any, Callable, Coroutine, TypeVar

T = TypeVar("T")


async def run_parallel(
    agent_factory: Callable[[str], Coroutine[Any, Any, T]],
    angles: list[str],
    *,
    model: str | None = None,
) -> list[T]:
    """并行运行多个 agent 实例，并打印更完整的异常诊断。"""
    _ = model
    tasks = [agent_factory(angle) for angle in angles]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid_results: list[T] = []
    for angle, result in zip(angles, results, strict=False):
        if isinstance(result, Exception):
            print(f"⚠️ Instance failed [{angle}]: {type(result).__name__}: {result}")
            stderr = getattr(result, "stderr", None)
            if stderr:
                print(f"stderr[{angle}]: {stderr}")
            tb = "".join(traceback.format_exception(type(result), result, result.__traceback__))
            if tb.strip():
                print(f"traceback[{angle}]:\n{tb}")
            continue
        valid_results.append(result)

    return valid_results
