"""Tests for audit helpers."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from gearbox.agents.audit import run_audit
from gearbox.agents.schemas import AuditResult
from gearbox.agents.shared import clone_repository, scanner
from gearbox.agents.shared.scanner import scan_repository


def test_clone_repository_supports_local_git_repo(tmp_path: Path) -> None:
    source_repo = tmp_path / "source"
    source_repo.mkdir()

    subprocess.run(["git", "init"], cwd=source_repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.name", "Gearbox Tests"],
        cwd=source_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "gearbox-tests@example.com"],
        cwd=source_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    (source_repo / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"], cwd=source_repo, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=source_repo,
        check=True,
        capture_output=True,
        text=True,
    )

    clone_root, clone_dir = clone_repository(str(source_repo))
    try:
        assert clone_root.exists()
        assert (clone_root / "README.md").read_text(encoding="utf-8") == "hello\n"
        assert (clone_root / ".git").exists()
    finally:
        clone_dir.cleanup()


def test_scan_repository_counts_local_python_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )
    (repo / "app.py").write_text("print('hello')\n", encoding="utf-8")

    result = scan_repository(repo)

    assert result.project_type == "python"
    assert result.total_files >= 1
    assert result.total_lines >= 1
    assert result.tool_statuses["cloc"] == "ok" or result.tool_statuses["cloc"].endswith(
        "+fallback"
    )


def test_deptry_parses_json_when_issues_exit_nonzero(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        """
[project]
name = "demo-package"
version = "0.1.0"

[project.optional-dependencies]
dev = ["pytest"]
""",
        encoding="utf-8",
    )

    captured_cmd: list[str] = []

    def fake_run_command(
        cmd: list[str],
        cwd: Path,
        timeout: int = 120,
    ) -> tuple[int, str, str]:
        del cwd, timeout
        captured_cmd.extend(cmd)
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_text(
            json.dumps(
                [
                    {
                        "error": {
                            "code": "DEP002",
                            "message": "'unused' defined as a dependency but not used",
                        },
                        "module": "unused",
                    }
                ]
            ),
            encoding="utf-8",
        )
        return 1, "", "Found 1 dependency issue."

    monkeypatch.setattr(scanner, "_run_command", fake_run_command)

    issues, status = scanner.run_deptry(repo)

    assert status == "issues=1"
    assert issues[0]["error"]["code"] == "DEP002"
    assert "--known-first-party" in captured_cmd
    assert "demo_package" in captured_cmd
    assert "--optional-dependencies-dev-groups" in captured_cmd


class TestScanFailureHandling:
    """Verify that scan failures are propagated to the agent prompt and result."""

    @staticmethod
    def _make_tmp_repo(tmp_path: Path) -> str:
        """Create a minimal git repo for testing."""
        repo = tmp_path / "source"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return str(repo)

    @staticmethod
    def _mock_sdk(monkeypatch, fake_structured: AuditResult) -> MagicMock:
        """Mock all SDK dependencies needed for run_audit()."""
        captured_system_prompt: list[str] = []

        async def fake_query(*args, **kwargs):
            class FakeMsg:
                pass

            msg = FakeMsg()
            msg.total_cost_usd = 0.001
            yield msg

        monkeypatch.setattr("claude_agent_sdk.query", fake_query)
        monkeypatch.setattr("gearbox.config.get_anthropic_model", lambda: "test-model")
        monkeypatch.setattr("gearbox.config.get_anthropic_base_url", lambda: None)

        fake_logger = MagicMock()
        fake_logger.log_start = MagicMock()
        fake_logger.handle_message = MagicMock(return_value=fake_structured)
        fake_logger.log_completion = MagicMock()

        def fake_prepare(opts, agent_name):
            del agent_name
            # Capture the actual system_prompt from the options passed in
            captured_system_prompt.append(opts.system_prompt)
            return opts, fake_logger

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime.prepare_agent_options",
            fake_prepare,
        )
        # parse_with_model is called inside run_audit() to extract structured output
        monkeypatch.setattr(
            "gearbox.agents.schemas.parse_with_model",
            lambda msg, cls: fake_structured,
        )

        # Return captured so caller can inspect the system_prompt
        mock_ctx = MagicMock()
        mock_ctx.captured_system_prompt = captured_system_prompt
        return mock_ctx

    def test_scan_failure_injected_into_prompt(self, tmp_path: Path, monkeypatch) -> None:
        """When scan_repository raises, the resolved prompt must include scan failure info."""
        import asyncio

        repo = self._make_tmp_repo(tmp_path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        fake_structured = AuditResult(
            repo="test/repo",
            profile={"scan_status": "failed"},
            comparison_markdown="# Test",
            issues=[],
        )
        ctx = self._mock_sdk(monkeypatch, fake_structured)

        def _raise_scan(repo_path):
            del repo_path
            raise RuntimeError("scanner tool not found")

        monkeypatch.setattr("gearbox.agents.shared.scanner.scan_repository", _raise_scan)

        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        try:
            _loop.run_until_complete(
                run_audit(str(repo), output_dir=str(output_dir), enable_prescan=True)
            )
        finally:
            _loop.close()

        system_prompt = ctx.captured_system_prompt[0] if ctx.captured_system_prompt else None
        assert system_prompt is not None, "system_prompt should have been set"
        assert "扫描失败" in system_prompt or "扫描未完成" in system_prompt, (
            f"Prompt must include scan failure info but got: {system_prompt[:500]}"
        )

    def test_scan_failure_sets_failure_reason_on_result(self, tmp_path: Path, monkeypatch) -> None:
        """When scan fails and agent returns a result, failure_reason should reflect the scan error."""
        import asyncio

        repo = self._make_tmp_repo(tmp_path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        fake_structured = AuditResult(
            repo="test/repo",
            profile={},
            comparison_markdown="# Test\n",
            issues=[],
        )
        self._mock_sdk(monkeypatch, fake_structured)

        def _raise_scan(repo_path):
            del repo_path
            raise RuntimeError("scanner tool not found")

        monkeypatch.setattr("gearbox.agents.shared.scanner.scan_repository", _raise_scan)

        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        try:
            result = _loop.run_until_complete(
                run_audit(str(repo), output_dir=str(output_dir), enable_prescan=True)
            )
        finally:
            _loop.close()

        assert result.failure_reason is not None, "failure_reason must be set when scanning fails"
        assert "scan" in result.failure_reason.lower() or "扫描" in result.failure_reason
