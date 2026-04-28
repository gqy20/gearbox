"""瞬态故障重试机制 (Issue #29)

提供统一的 retry 装饰器和工具函数，用于保护：
- subprocess.run() 网络调用（gh CLI、git 等）
- SDK query() 调用
- 扫描器命令执行

支持的瞬态错误类型：
- subprocess.TimeoutExpired
- subprocess.CalledProcessError (returncode >= 500)
- ConnectionResetError / socket.timeout
- OSError with ETIMEDOUT errno
"""

from __future__ import annotations

import errno
import functools
import socket
import subprocess
import time
from dataclasses import dataclass

try:
    from typing import Protocol, runtime_checkable
except ImportError:
    from typing_extensions import Protocol, runtime_checkable  # type: ignore[assignment]


@dataclass(frozen=True)
class RetryConfig:
    """重试策略配置。"""

    max_attempts: int = 3
    wait_base: float = 1.0  # 初始等待秒数（指数退避基数）
    wait_max: float = 10.0  # 最大等待秒数


# 默认配置：3 次尝试，1s~10s 指数退避
DEFAULT_RETRY_CONFIG = RetryConfig()


def is_transient_error(error: BaseException) -> bool:
    """判断异常是否属于瞬态/可重试类型。

    Args:
        error: 待判断的异常对象

    Returns:
        True 表示该异常应触发重试
    """
    if isinstance(error, subprocess.TimeoutExpired):
        return True

    if isinstance(error, (ConnectionResetError,)):
        return True

    if isinstance(error, socket.timeout):
        return True

    if isinstance(error, OSError):
        # ETIMEDOUT = 110, EHOSTUNREACH = 113, ENETUNREACH = 101
        if error.errno in (errno.ETIMEDOUT, errno.EHOSTUNREACH, errno.ENETUNREACH):
            return True

    if isinstance(error, subprocess.CalledProcessError):
        return should_retry_subprocess(error)

    return False


def should_retry_subprocess(error: BaseException) -> bool:
    """判断异常是否表示 subprocess 服务端瞬态故障。

    HTTP 服务端错误码 (5xx) 应重试，客户端错误码 (4xx) 不应重试。
    GitHub CLI 的 exit code 不直接映射 HTTP status，但我们将
    returncode >= 500 视为服务端错误的代理信号。

    Args:
        error: 异常实例（非 CalledProcessError 直接返回 False）

    Returns:
        True 表示应重试
    """
    if not isinstance(error, subprocess.CalledProcessError):
        return False
    # 仅对疑似服务端错误的重试
    return error.returncode >= 500


@runtime_checkable
class _AsyncCallable(Protocol):
    """用于检测异步可调用对象的协议。"""

    def __call__(self, *args, **kwargs): ...  # pragma: no cover


def _wait_with_backoff(attempt: int, config: RetryConfig) -> None:
    """指数退避等待，带抖动。"""
    delay = min(config.wait_base * (2 ** (attempt - 1)), config.wait_max)
    # 添加 ±20% 抖动避免惊群效应
    jitter = delay * 0.2
    import random

    actual_delay = delay + (random.uniform(-jitter, jitter))
    time.sleep(max(0, actual_delay))


def retry_on_transient(
    config: RetryConfig = DEFAULT_RETRY_CONFIG,
):
    """装饰器：在瞬态故障时自动重试。

    同时支持同步和异步函数。仅对 is_transient_error() 返回 True 的异常重试，
    其他异常直接抛出。

    Args:
        config: 重试策略配置

    Returns:
        装饰器函数
    """

    def decorator(fn):
        if asyncio and asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                last_error: BaseException | None = None
                for attempt in range(1, config.max_attempts + 1):
                    try:
                        return await fn(*args, **kwargs)
                    except Exception as e:
                        last_error = e
                        if not is_transient_error(e) or attempt == config.max_attempts:
                            raise
                        _wait_with_backoff(attempt, config)
                assert last_error is not None
                raise last_error

            return async_wrapper
        else:

            @functools.wraps(fn)
            def sync_wrapper(*args, **kwargs):
                last_error: BaseException | None = None
                for attempt in range(1, config.max_attempts + 1):
                    try:
                        return fn(*args, **kwargs)
                    except Exception as e:
                        last_error = e
                        if not is_transient_error(e) or attempt == config.max_attempts:
                            raise
                        _wait_with_backoff(attempt, config)
                assert last_error is not None
                raise last_error

            return sync_wrapper

    return decorator


# 延迟导入 asyncio 以减少同步路径的开销
asyncio = None  # type: ignore[assignment]

# 在模块加载时尝试导入 asyncio（Python 3.10+ 内置）
try:
    import asyncio as _asyncio

    asyncio = _asyncio
except ImportError:  # pragma: no cover
    pass


def retry_sdk_query(
    query_fn,
    config: RetryConfig = DEFAULT_RETRY_CONFIG,
):
    """包装 SDK query() 异步生成器，在瞬态故障时自动重试。

    query() 是异步生成器，无法直接用装饰器包装。
    此函数返回一个新的异步生成器，在迭代过程中遇到瞬态异常时
    自动重新调用 query_fn 并从头开始消费。

    Args:
        query_fn: 原始 query 异步生成器函数 (prompt, options) -> AsyncGenerator
        config: 重试策略配置

    Returns:
        包装后的异步生成器
    """

    async def _wrapped(prompt: str, options):
        last_error: BaseException | None = None
        for attempt in range(1, config.max_attempts + 1):
            try:
                async for message in query_fn(prompt, options):
                    yield message
                return  # 正常完成
            except Exception as e:
                last_error = e
                if not is_transient_error(e) or attempt == config.max_attempts:
                    raise
                _wait_with_backoff(attempt, config)
        assert last_error is not None
        raise last_error

    return _wrapped


class CostBudgetExceededError(Exception):
    """审计成本超过预算限制。"""

    def __init__(self, budget_usd: float, actual_usd: float) -> None:
        self.budget_usd = budget_usd
        self.actual_usd = actual_usd
        super().__init__(f"Cost budget exceeded: ${actual_usd:.4f} > ${budget_usd:.2f}")
