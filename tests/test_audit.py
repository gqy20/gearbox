"""Tests for audit helpers."""

import json
import subprocess
import time
from pathlib import Path

from gearbox.agents.audit import (
    _cache_benchmarks,
    _cleanup_benchmark_cache,
    _get_cached_benchmarks,
)
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
# Benchmark cache tests
# ---------------------------------------------------------------------------


class TestGetCachedBenchmarks:
    """Tests for _get_cached_benchmarks with schema validation."""

    def test_valid_cache_returns_benchmarks(self, tmp_path: Path, monkeypatch) -> None:
        """A well-formed cache file within TTL returns the benchmarks list."""
        monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", tmp_path / "benchmarks")
        cache_file = tmp_path / "benchmarks" / "owner_repo.json"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text(
            json.dumps(
                {
                    "benchmarks": ["repo/a", "repo/b"],
                    "cached_at": time.time(),
                }
            ),
            encoding="utf-8",
        )

        result = _get_cached_benchmarks("owner/repo")
        assert result == ["repo/a", "repo/b"]

    def test_missing_cache_returns_none(self, tmp_path: Path, monkeypatch) -> None:
        """No cache file exists → returns None."""
        monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", tmp_path / "benchmarks")

        assert _get_cached_benchmarks("owner/repo") is None

    def test_corrupted_json_returns_none(self, tmp_path: Path, monkeypatch) -> None:
        """Truncated / malformed JSON returns None instead of crashing."""
        monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", tmp_path / "benchmarks")
        cache_file = tmp_path / "benchmarks" / "owner_repo.json"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text("{broken json!!!", encoding="utf-8")

        assert _get_cached_benchmarks("owner/repo") is None

    def test_missing_benchmarks_key_returns_empty_list(self, tmp_path: Path, monkeypatch) -> None:
        """Cache missing 'benchmarks' key returns empty list (Pydantic default)."""
        monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", tmp_path / "benchmarks")
        cache_file = tmp_path / "benchmarks" / "owner_repo.json"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text(
            json.dumps({"cached_at": time.time()}),
            encoding="utf-8",
        )

        result = _get_cached_benchmarks("owner/repo")
        assert result == []

    def test_benchmarks_not_a_list_returns_none(self, tmp_path: Path, monkeypatch) -> None:
        """Cache where 'benchmarks' is a string (not list) returns None."""
        monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", tmp_path / "benchmarks")
        cache_file = tmp_path / "benchmarks" / "owner_repo.json"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text(
            json.dumps({"benchmarks": "not-a-list", "cached_at": time.time()}),
            encoding="utf-8",
        )

        assert _get_cached_benchmarks("owner/repo") is None

    def test_expired_cache_returns_none(self, tmp_path: Path, monkeypatch) -> None:
        """Cache older than 7 days returns None."""
        monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", tmp_path / "benchmarks")
        cache_file = tmp_path / "benchmarks" / "owner_repo.json"
        cache_file.parent.mkdir(parents=True)
        expired_ts = time.time() - (8 * 24 * 3600)
        cache_file.write_text(
            json.dumps({"benchmarks": ["repo/a"], "cached_at": expired_ts}),
            encoding="utf-8",
        )

        assert _get_cached_benchmarks("owner/repo") is None

    def test_empty_benchmarks_list_returns_empty_list(self, tmp_path: Path, monkeypatch) -> None:
        """Empty benchmarks list is valid and returned as-is."""
        monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", tmp_path / "benchmarks")
        cache_file = tmp_path / "benchmarks" / "owner_repo.json"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text(
            json.dumps({"benchmarks": [], "cached_at": time.time()}),
            encoding="utf-8",
        )

        result = _get_cached_benchmarks("owner/repo")
        assert result == []


class TestCacheBenchmarks:
    """Tests for _cache_benchmarks atomic write."""

    def test_write_creates_valid_cache(self, tmp_path: Path, monkeypatch) -> None:
        """Writing benchmarks produces a readable cache file."""
        monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", tmp_path / "benchmarks")

        _cache_benchmarks("owner/repo", ["repo/x", "repo/y"])

        cache_file = tmp_path / "benchmarks" / "owner_repo.json"
        assert cache_file.exists()
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert data["benchmarks"] == ["repo/x", "repo/y"]
        assert isinstance(data["cached_at"], float)

    def test_read_after_roundtrip(self, tmp_path: Path, monkeypatch) -> None:
        """Write then read returns identical data (round-trip)."""
        monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", tmp_path / "benchmarks")

        original = ["repo/a", "repo/b", "repo/c"]
        _cache_benchmarks("owner/repo", original)

        result = _get_cached_benchmarks("owner/repo")
        assert result == original


class TestCleanupBenchmarkCache:
    """Tests for _cleanup_benchmark_cache."""

    def test_removes_expired_files(self, tmp_path: Path, monkeypatch) -> None:
        """Cleanup removes cache files older than TTL."""
        monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", tmp_path / "benchmarks")
        cache_dir = tmp_path / "benchmarks"
        cache_dir.mkdir()

        # Valid (recent)
        recent = cache_dir / "recent.json"
        recent.write_text(
            json.dumps({"benchmarks": ["a"], "cached_at": time.time()}),
            encoding="utf-8",
        )

        # Expired
        expired = cache_dir / "expired.json"
        expired.write_text(
            json.dumps({"benchmarks": ["b"], "cached_at": time.time() - (10 * 24 * 3600)}),
            encoding="utf-8",
        )

        removed = _cleanup_benchmark_cache()
        assert removed == 1
        assert recent.exists()
        assert not expired.exists()

    def test_noop_when_dir_missing(self, tmp_path: Path, monkeypatch) -> None:
        """Returns 0 when cache directory does not exist."""
        monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", tmp_path / "nonexistent")

        assert _cleanup_benchmark_cache() == 0

    def test_removes_corrupted_files(self, tmp_path: Path, monkeypatch) -> None:
        """Cleanup also removes files that fail schema validation."""
        monkeypatch.setattr("gearbox.agents.audit._BENCHMARK_CACHE_DIR", tmp_path / "benchmarks")
        cache_dir = tmp_path / "benchmarks"
        cache_dir.mkdir()

        valid = cache_dir / "valid.json"
        valid.write_text(
            json.dumps({"benchmarks": ["a"], "cached_at": time.time()}),
            encoding="utf-8",
        )

        corrupted = cache_dir / "corrupted.json"
        corrupted.write_text("{{bad", encoding="utf-8")

        removed = _cleanup_benchmark_cache()
        # Corrupted file should be cleaned up; valid stays
        assert removed >= 1
        assert valid.exists()
        assert not corrupted.exists()
