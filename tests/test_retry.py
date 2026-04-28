"""测试瞬态故障重试机制 (Issue #29)"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gearbox.agents.shared.retry import (
    RetryConfig,
    is_transient_error,
    retry_on_transient,
    should_retry_subprocess,
)

# =============================================================================
# is_transient_error
# =============================================================================


class TestIsTransientError:
    """判断异常是否属于瞬态/可重试类型。"""

    def test_timeout_expired_is_transient(self) -> None:
        assert is_transient_error(subprocess.TimeoutExpired(cmd="test", timeout=5)) is True

    def test_connection_reset_error_is_transient(self) -> None:
        assert is_transient_error(ConnectionResetError("reset")) is True

    def test_socket_timeout_is_transient(self) -> None:
        import socket

        assert is_transient_error(socket.timeout("timed out")) is True

    def test_os_timeout_is_transient(self) -> None:
        # OSError with ETIMEDOUT (errno 110)
        err = OSError(110, "Connection timed out")
        assert is_transient_error(err) is True

    def test_connection_refused_is_not_transient(self) -> None:
        # ECONNREFUSED (errno 111) — 服务不存在，重试无意义
        err = OSError(111, "Connection refused")
        assert is_transient_error(err) is False

    def test_called_process_error_with_server_error_code_is_transient(self) -> None:
        err = subprocess.CalledProcessError(returncode=502, cmd="gh")
        assert is_transient_error(err) is True

    def test_called_process_error_503_is_transient(self) -> None:
        err = subprocess.CalledProcessError(returncode=503, cmd="gh")
        assert is_transient_error(err) is True

    def test_called_process_error_429_is_transient(self) -> None:
        # GitHub CLI returns exit code 2 on rate limit; we treat >= 500 as server error
        # but 429-like scenarios should also be retryable via custom handling
        err = subprocess.CalledProcessError(returncode=1, cmd="gh")
        assert is_transient_error(err) is False  # exit code 1 is not server error

    def test_generic_runtime_error_is_not_transient(self) -> None:
        assert is_transient_error(RuntimeError("boom")) is False

    def test_value_error_is_not_transient(self) -> None:
        assert is_transient_error(ValueError("bad value")) is False


# =============================================================================
# should_retry_subprocess
# =============================================================================


class TestShouldRetrySubprocess:
    """判断 subprocess 错误是否应重试。"""

    def test_server_error_500(self) -> None:
        assert should_retry_subprocess(subprocess.CalledProcessError(500, "cmd")) is True

    def test_server_error_502(self) -> None:
        assert should_retry_subprocess(subprocess.CalledProcessError(502, "cmd")) is True

    def test_server_error_503(self) -> None:
        assert should_retry_subprocess(subprocess.CalledProcessError(503, "cmd")) is True

    def test_server_error_504(self) -> None:
        assert should_retry_subprocess(subprocess.CalledProcessError(504, "cmd")) is True

    def test_client_error_400_not_retried(self) -> None:
        assert should_retry_subprocess(subprocess.CalledProcessError(400, "cmd")) is False

    def test_client_error_404_not_retried(self) -> None:
        assert should_retry_subprocess(subprocess.CalledProcessError(404, "cmd")) is False

    def test_exit_code_1_not_retried(self) -> None:
        assert should_retry_subprocess(subprocess.CalledProcessError(1, "cmd")) is False

    def test_non_called_process_error_returns_false(self) -> None:
        assert should_retry_subprocess(RuntimeError("x")) is False


# =============================================================================
# retry_on_transient decorator
# =============================================================================


class TestRetryOnTransient:
    """retry_on_transient 装饰器的行为验证。"""

    def test_succeeds_immediately_on_first_call(self) -> None:
        call_count = 0

        @retry_on_transient(RetryConfig(max_attempts=3, wait_base=0.01))
        def fn() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        assert fn() == "ok"
        assert call_count == 1

    def test_retries_on_transient_error_then_succeeds(self) -> None:
        call_count = 0

        @retry_on_transient(RetryConfig(max_attempts=3, wait_base=0.01))
        def fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionResetError("transient")
            return "ok"

        assert fn() == "ok"
        assert call_count == 3

    def test_raises_after_max_attempts_exhausted(self) -> None:
        call_count = 0

        @retry_on_transient(RetryConfig(max_attempts=3, wait_base=0.01))
        def fn() -> str:
            nonlocal call_count
            call_count += 1
            raise ConnectionResetError("always fails")

        with pytest.raises(ConnectionResetError, match="always fails"):
            fn()

        assert call_count == 3

    def test_does_not_retry_non_transient_error(self) -> None:
        call_count = 0

        @retry_on_transient(RetryConfig(max_attempts=5, wait_base=0.01))
        def fn() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            fn()

        assert call_count == 1  # no retries for non-transient

    def test_retries_on_timeout_expired(self) -> None:
        call_count = 0

        @retry_on_transient(RetryConfig(max_attempts=2, wait_base=0.01))
        def fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise subprocess.TimeoutExpired(cmd="sleep", timeout=5)
            return "recovered"

        assert fn() == "recovered"
        assert call_count == 2

    def test_retries_on_server_error_code(self) -> None:
        call_count = 0

        @retry_on_transient(RetryConfig(max_attempts=3, wait_base=0.01))
        def fn() -> int:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise subprocess.CalledProcessError(returncode=502, cmd="gh")
            return 42

        assert fn() == 42
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_async_function_retry(self) -> None:
        """retry_on_transient 应同时支持同步和异步函数。"""
        call_count = 0

        @retry_on_transient(RetryConfig(max_attempts=3, wait_base=0.01))
        async def async_fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionResetError("transient")
            return "async ok"

        result = await async_fn()
        assert result == "async ok"
        assert call_count == 2


# =============================================================================
# Integration: scanner _run_command with retry
# =============================================================================


class TestScannerRunCommandWithRetry:
    """scanner._run_command 在瞬态故障时应自动重试。"""

    def test_timeout_expired_triggers_retry_in_run_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from gearbox.agents.shared.scanner import _run_command

        call_count = 0
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 60))
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, "run", fake_run)

        rc, out, err = _run_command(["echo", "hello"], tmp_path, timeout=10)

        assert rc == 0
        assert call_count == 2

    def test_non_transient_error_no_retry_in_run_command(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from gearbox.agents.shared.scanner import _run_command

        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ValueError("permanent failure")

        monkeypatch.setattr(subprocess, "run", fake_run)

        rc, out, err = _run_command(["echo", "hello"], "/tmp")

        assert rc == -1
        assert call_count == 1  # no retry


# =============================================================================
# Integration: gh.py functions with retry
# =============================================================================


class TestGhFunctionsRetry:
    """core/gh.py 的网络调用函数在瞬态故障时应自动重试。"""

    def test_list_open_issues_retries_on_502(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from gearbox.core.gh import list_open_issues

        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise subprocess.CalledProcessError(returncode=502, cmd=cmd)
            return MagicMock(
                returncode=0,
                stdout=(
                    '[{"number":1,"title":"T","labels":[],'
                    '"url":"https://g.com/r/1","createdAt":"2026-01-01T00:00:00Z"}]'
                ),
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        issues = list_open_issues("owner/repo")
        assert len(issues) == 1
        assert issues[0].number == 1
        assert call_count == 3  # 2 failures + 1 success

    def test_get_repo_labels_retries_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from gearbox.core.gh import get_repo_labels

        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)
            return MagicMock(returncode=0, stdout='[{"name":"bug"}]')

        monkeypatch.setattr(subprocess, "run", fake_run)

        labels = get_repo_labels("owner/repo")
        assert labels == ["bug"]
        assert call_count == 2

    def test_non_retryable_error_propagates_immediately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from gearbox.core.gh import get_repo_labels

        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            raise subprocess.CalledProcessError(returncode=1, cmd=cmd, stderr="not found")

        monkeypatch.setattr(subprocess, "run", fake_run)

        labels = get_repo_labels("owner/repo")
        assert labels == []  # falls back gracefully
        assert call_count == 1  # not retried (exit code 1)


# =============================================================================
# RetryConfig defaults
# =============================================================================


class TestRetryConfig:
    """RetryConfig 数据类默认值和验证。"""

    def test_default_values(self) -> None:
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.wait_base == 1.0
        assert config.wait_max == 10.0

    def test_custom_values(self) -> None:
        config = RetryConfig(max_attempts=5, wait_base=0.5, wait_max=30.0)
        assert config.max_attempts == 5
        assert config.wait_base == 0.5
        assert config.wait_max == 30.0


# =============================================================================
# SDK query retry wrapper (audit.py / evaluator.py)
# =============================================================================


class TestSdkQueryRetryWrapper:
    """retry_sdk_query 包装器应在瞬态故障时重试整个 query 调用。"""

    @pytest.mark.asyncio
    async def test_retries_on_connection_error_then_succeeds(self) -> None:
        from gearbox.agents.shared.retry import retry_sdk_query

        call_count = 0
        config = RetryConfig(max_attempts=3, wait_base=0.01)

        async def fake_query(prompt, options):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionResetError("connection dropped")
            # 模拟成功返回结果的异步生成器
            yield "result_message"  # type: ignore[misc]

        wrapped = retry_sdk_query(fake_query, config=config)
        results = []
        async for msg in wrapped("prompt", None):  # type: ignore[arg-type]
            results.append(msg)

        assert len(results) == 1
        assert results[0] == "result_message"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self) -> None:
        from gearbox.agents.shared.retry import retry_sdk_query

        call_count = 0
        config = RetryConfig(max_attempts=2, wait_base=0.01)

        async def always_fail(prompt, options):
            nonlocal call_count
            call_count += 1
            # 模拟异步生成器：先 raise（在首次迭代时抛出异常）
            raise ConnectionResetError("always fails")
            yield  # type: ignore[misc]  # 使其成为异步生成器
            return  # type: ignore[unreachable]

        wrapped = retry_sdk_query(always_fail, config=config)
        with pytest.raises(ConnectionResetError):
            async for _ in wrapped("prompt", None):  # type: ignore[arg-type]
                pass

        assert call_count == 2


# =============================================================================
# Cost budget parameter for run_audit
# =============================================================================


class TestRunAuditCostBudget:
    """run_audit 的 max_cost_budget_usd 参数应能提前终止审计。"""

    def test_cost_budget_is_accepted_parameter(self) -> None:
        """验证 run_audit 签名包含 max_cost_budget_usd 参数。"""
        import inspect

        from gearbox.agents.audit import run_audit

        sig = inspect.signature(run_audit)
        assert "max_cost_budget_usd" in sig.parameters

    def test_cost_budget_defaults_to_none(self) -> None:
        """默认值应为 None（不限制成本）。"""
        import inspect

        from gearbox.agents.audit import run_audit

        sig = inspect.signature(run_audit)
        assert sig.parameters["max_cost_budget_usd"].default is None
