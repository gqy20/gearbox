"""Tests for audit helpers."""

import json
import subprocess
from pathlib import Path

from gearbox.agents.audit import _cache_benchmarks, _get_cached_benchmarks
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


# ---------------------------------------------------------------------------
# Benchmark cache path traversal protection (Issue #51)
# ---------------------------------------------------------------------------


def test_sanitize_repo_name_accepts_normal_format() -> None:
    """Normal owner/repo names must pass sanitization."""
    from gearbox.agents.audit import _sanitize_repo_name

    assert _sanitize_repo_name("owner/repo") == "owner/repo"
    assert _sanitize_repo_name("my-org/my-repo_v2") == "my-org/my-repo_v2"


def test_sanitize_repo_name_rejects_dotdot() -> None:
    """Repo names containing '..' must be rejected."""
    import pytest

    from gearbox.agents.audit import _sanitize_repo_name

    with pytest.raises(ValueError, match="invalid repo"):
        _sanitize_repo_name("../../etc/evil")


def test_sanitize_repo_name_rejects_dots() -> None:
    """Repo names containing standalone '.' must be rejected."""
    import pytest

    from gearbox.agents.audit import _sanitize_repo_name

    with pytest.raises(ValueError, match="invalid repo"):
        _sanitize_repo_name("../secret/backup")
    with pytest.raises(ValueError, match="invalid repo"):
        _sanitize_repo_name(".")


def test_sanitize_repo_name_rejects_special_chars() -> None:
    """Repo names with path-special characters must be rejected."""
    import pytest

    from gearbox.agents.audit import _sanitize_repo_name

    with pytest.raises(ValueError, match="invalid repo"):
        _sanitize_repo_name("owner/null\x00/repo")
    with pytest.raises(ValueError, match="invalid repo"):
        _sanitize_repo_name("owner/../repo")


def test_cache_benchmarks_normal_repo_works(tmp_path: Path, monkeypatch) -> None:
    """Normal owner/repo names should cache and retrieve without error."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", cache_dir)

    _cache_benchmarks("owner/repo", ["bench/a", "bench/b"])
    result = _get_cached_benchmarks("owner/repo")
    assert result == ["bench/a", "bench/b"]


def test_cache_benchmarks_rejects_path_traversal_write(tmp_path: Path, monkeypatch) -> None:
    """Writing with a traversal repo must not create files outside cache dir."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", cache_dir)

    _cache_benchmarks("../../etc/evil", ["malicious"])
    evil_file = tmp_path / "etc" / "evil.json"
    assert not evil_file.exists(), "Path traversal write was not blocked"


def test_get_cached_benchmarks_rejects_path_traversal_read(tmp_path: Path, monkeypatch) -> None:
    """Reading with a traversal repo name must return None (not escape)."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", cache_dir)

    result = _get_cached_benchmarks("../../etc/passwd")
    assert result is None, "Path traversal read was not blocked"


def test_resolved_cache_path_stays_within_cache_dir(tmp_path: Path, monkeypatch) -> None:
    """After sanitization, the resolved cache file must be relative to cache dir."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", cache_dir)

    _cache_benchmarks("valid-owner/valid-repo", ["ok"])
    expected = cache_dir / "valid-owner_valid-repo.json"
    assert expected.exists()
    assert expected.resolve().is_relative_to(cache_dir.resolve())
