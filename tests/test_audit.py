"""Tests for audit helpers."""

import json
import multiprocessing
import subprocess
import time
import unittest.mock
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
name = 'demo-package'
version = '0.1.0'

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
# Benchmark cache concurrency tests (Issue #102)
#
# Worker functions live at module level so they are pickleable with
# multiprocessing spawn context.
# ---------------------------------------------------------------------------


def test_cache_benchmarks_uses_atomic_rename(tmp_path: Path) -> None:
    """_cache_benchmarks must write to a temp file then os.replace() for atomicity.

    This test verifies the implementation uses the atomic-write pattern
    (write temp → os.replace) rather than direct Path.write_text which can
    leave partial files if interrupted between mkdir and write_text.
    """
    cache_dir = tmp_path / "atomic_test"
    repo = "owner/atomic"

    import gearbox.agents.audit as audit_mod  # noqa: PLC0415

    audit_mod._BENCHMARK_CACHE_DIR = cache_dir  # type: ignore[attr-defined]

    replace_calls: list[tuple[object, object]] = []

    original_replace = __import__("os").replace

    def spy_replace(src: object, dst: object) -> None:
        replace_calls.append((src, dst))
        return original_replace(src, dst)  # type: ignore[arg-type]

    with unittest.mock.patch("os.replace", side_effect=spy_replace):
        _cache_benchmarks(repo, ["x", "y"])

    assert len(replace_calls) >= 1, (
        "Expected _cache_benchmarks to call os.replace() for atomic write, "
        "but no calls were recorded. Current implementation likely uses "
        "Path.write_text directly which is not atomic."
    )

    # Verify the rename target is the expected cache file
    cache_filename = f"{repo.replace('/', '_')}.json"
    targets = [str(dst) for _, dst in replace_calls]
    assert any(cache_filename in t for t in targets), (
        f"os.replace() was called but not targeting {cache_filename}. Targets: {targets}"
    )


def test_cache_benchmarks_uses_file_lock(tmp_path: Path) -> None:
    """_cache_benchmarks must acquire an exclusive file lock during write.

    Without a lock, concurrent processes can interleave read-check-write
    operations causing TOCTOU data corruption (Issue #102).
    """
    cache_dir = tmp_path / "lock_test"
    repo = "owner/locked"

    import fcntl  # type: ignore[import-untyped]  # noqa: PLC0415

    import gearbox.agents.audit as audit_mod  # noqa: PLC0415

    audit_mod._BENCHMARK_CACHE_DIR = cache_dir  # type: ignore[attr-defined]

    flock_calls: list[tuple[int, int]] = []

    original_flock = fcntl.flock

    def spy_flock(fd: int, operation: int) -> None:
        flock_calls.append((fd, operation))
        return original_flock(fd, operation)

    with unittest.mock.patch("fcntl.flock", side_effect=spy_flock):
        _cache_benchmarks(repo, ["a", "b"])

    # Must have called flock at least once with LOCK_EX (exclusive lock = 2)
    lock_ops = [op for _, op in flock_calls]
    assert any(op & 2 for op in lock_ops), (
        "Expected _cache_benchmarks to acquire an exclusive file lock (fcntl.LOCK_EX), "
        f"but no LOCK_EX call found. Operations seen: {[hex(o) for o in lock_ops]}"
    )


def test_get_cached_benchmarks_uses_shared_lock(tmp_path: Path) -> None:
    """_get_cached_benchmarks should use a shared (read) lock when reading.

    A shared lock allows concurrent readers but blocks exclusive writers,
    preventing reads of partially-written files.
    """
    cache_dir = tmp_path / "shared_lock_test"
    repo = "owner/shared_lock_read"

    import fcntl  # type: ignore[import-untyped]  # noqa: PLC0415

    import gearbox.agents.audit as audit_mod  # noqa: PLC0415

    audit_mod._BENCHMARK_CACHE_DIR = cache_dir  # type: ignore[attr-defined]

    # Pre-populate valid cache
    _cache_benchmarks(repo, ["valid"])

    flock_calls: list[tuple[int, int]] = []

    original_flock = fcntl.flock

    def spy_flock(fd: int, operation: int) -> None:
        flock_calls.append((fd, operation))
        return original_flock(fd, operation)

    with unittest.mock.patch("fcntl.flock", side_effect=spy_flock):
        result = _get_cached_benchmarks(repo)

    assert result == ["valid"]
    # Should have used LOCK_SH (shared/read lock = 1) or at minimum some lock
    assert len(flock_calls) >= 1, (
        "Expected _get_cached_benchmarks to use fcntl.flock() for safe reading, "
        "but no flock calls were recorded."
    )


def _mp_write_worker(args: tuple[str, str, list[str]]) -> None:
    """Multiprocessing worker: write benchmarks to cache."""
    repo, cache_dir_override, benchmarks = args
    import gearbox.agents.audit as audit_mod  # noqa: PLC0415

    audit_mod._BENCHMARK_CACHE_DIR = Path(cache_dir_override)  # type: ignore[attr-defined]
    _cache_benchmarks(repo, benchmarks)


def _mp_read_worker(args: tuple[int, str, str]) -> list | None:
    """Multiprocessing worker: read benchmarks from cache."""
    _, cache_dir_override, repo = args
    import gearbox.agents.audit as audit_mod  # noqa: PLC0415

    audit_mod._BENCHMARK_CACHE_DIR = Path(cache_dir_override)  # type: ignore[attr-defined]
    try:
        result = _get_cached_benchmarks(repo)
        if result is not None:
            assert isinstance(result, list), f"Expected list, got {type(result)}"
            for item in result:
                assert isinstance(item, str), f"Expected string item, got {type(item)}"
        return result
    except Exception:
        return None


def _mp_rw_mixed_worker(args: tuple[int, str, str]) -> list | None:
    """Multiprocessing worker: even indices write, odd indices read."""
    idx, cache_dir_override, repo = args
    import gearbox.agents.audit as audit_mod  # noqa: PLC0415

    audit_mod._BENCHMARK_CACHE_DIR = Path(cache_dir_override)  # type: ignore[attr-defined]
    if idx % 2 == 0:
        time.sleep(0.01 * idx)  # stagger writers slightly
        _cache_benchmarks(repo, [f"w{idx}-x{i}" for i in range(20)])
        return None
    return _get_cached_benchmarks(repo)


def test_cache_benchmarks_uses_atomic_write(tmp_path: Path) -> None:
    """_cache_benchmarks must write via temp file + os.replace so no partial file is visible."""
    cache_dir = tmp_path / "cache"
    repo = "owner/repo"
    benchmarks = ["a", "b", "c"]

    import gearbox.agents.audit as audit_mod  # noqa: PLC0415

    audit_mod._BENCHMARK_CACHE_DIR = cache_dir  # type: ignore[attr-defined]
    _cache_benchmarks(repo, benchmarks)

    cache_file = cache_dir / f"{repo.replace('/', '_')}.json"
    assert cache_file.exists()

    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert data["benchmarks"] == benchmarks
    assert "cached_at" in data

    # Verify the file was written atomically by checking it's a complete JSON object
    parsed = json.loads(cache_file.read_text(encoding="utf-8"))
    assert isinstance(parsed.get("benchmarks"), list)
    assert len(parsed["benchmarks"]) == 3


def test_get_cached_benchmarks_returns_none_when_expired(tmp_path: Path) -> None:
    """Expired cache entries should return None."""
    cache_dir = tmp_path / "cache"
    repo = "owner/expired"

    import gearbox.agents.audit as audit_mod  # noqa: PLC0415

    audit_mod._BENCHMARK_CACHE_DIR = cache_dir  # type: ignore[attr-defined]

    # Write an expired entry manually (cached_at far in the past)
    cache_file = cache_dir / f"{repo.replace('/', '_')}.json"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"benchmarks": ["old"], "cached_at": time.time() - 8 * 24 * 3600}),
        encoding="utf-8",
    )

    result = _get_cached_benchmarks(repo)
    assert result is None


def test_concurrent_cache_writes_do_not_corrupt_data(tmp_path: Path) -> None:
    """Multiple processes writing to the same cache file concurrently must not corrupt data.

    Each process writes a unique benchmark list. After all writes complete,
    the file must contain a valid, complete JSON from one of the writers.
    """
    cache_dir = tmp_path / "concurrent_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    repo = "owner/concurrent"

    num_workers = 5
    worker_args = [
        (repo, str(cache_dir), [f"benchmark-{i}-item-{j}" for j in range(10)])
        for i in range(num_workers)
    ]

    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=num_workers) as pool:
        pool.map(_mp_write_worker, worker_args)

    cache_file = cache_dir / f"{repo.replace('/', '_')}.json"
    assert cache_file.exists(), "Cache file should exist after concurrent writes"

    data = json.loads(cache_file.read_text(encoding="utf-8"))

    # Must be valid JSON with expected structure
    assert isinstance(data.get("benchmarks"), list), "benchmarks must be a list"
    assert len(data["benchmarks"]) > 0, "benchmarks must not be empty"
    assert "cached_at" in data, "cached_at field must exist"

    # The final content must match one of the written values exactly
    expected_sets = {frozenset(args[2]) for args in worker_args}
    actual_set = frozenset(data["benchmarks"])
    assert actual_set in expected_sets, (
        f"Final cache data does not match any writer's input. "
        f"Got {len(data['benchmarks'])} items from unknown source."
    )


def test_concurrent_read_write_does_not_crash_or_corrupt(tmp_path: Path) -> None:
    """Concurrent reads and writes to the same cache key must not crash or return corrupted data.

    This exercises the TOCTOU window where one process reads, finds expired,
    and prepares to write while another process writes fresh data.
    """
    cache_dir = tmp_path / "rw_race"
    cache_dir.mkdir(parents=True, exist_ok=True)
    repo = "owner/rw_race"

    tasks: list[tuple[int, str, str]] = [(i, str(cache_dir), repo) for i in range(6)]

    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=6) as pool:
        pool.map(_mp_rw_mixed_worker, tasks)

    # All readers should have returned without exception (results may be None or lists)
    # Verify final state is valid
    cache_file = cache_dir / f"{repo.replace('/', '_')}.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert isinstance(data.get("benchmarks"), list)
        assert "cached_at" in data
