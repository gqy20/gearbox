"""测试 agents/shared/git.py 克隆操作"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from gearbox.agents.shared.git import clone_repository


class TestCloneRepositoryTimeout:
    """clone_repository() 超时保护 (Issue #91)"""

    def test_clone_timeout_raises_runtime_error(self, tmp_path: Path) -> None:
        """超时时应抛出包含 'timeout' 的 RuntimeError"""
        fake_repo = str(tmp_path / "fake-local-repo")
        Path(fake_repo).mkdir()

        def slow_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=kwargs.get("cmd", ["git"]), timeout=600)

        with patch("gearbox.agents.shared.git.subprocess.run", side_effect=slow_run):
            with pytest.raises(RuntimeError, match="timeout"):
                clone_repository(fake_repo)

    def test_clone_timeout_default_is_600_seconds(self) -> None:
        """默认超时应为 600 秒（10 分钟）"""
        import inspect

        sig = inspect.signature(clone_repository)
        assert "timeout" in sig.parameters
        default = sig.parameters["timeout"].default
        assert default == 600

    def test_clone_custom_timeout_passed_to_subprocess(self, tmp_path: Path) -> None:
        """自定义 timeout 值应传递给 subprocess.run"""
        fake_repo = str(tmp_path / "local-repo")
        Path(fake_repo).mkdir()
        captured_kwargs: dict = {}

        def capture_run(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

        with patch("gearbox.agents.shared.git.subprocess.run", side_effect=capture_run):
            clone_repository(fake_repo, timeout=120)

        assert captured_kwargs.get("timeout") == 120
