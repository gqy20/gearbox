"""Tests for audit helpers."""

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def test_cache_benchmarks_writes_atomically(tmp_path: Path, monkeypatch) -> None:
    """_cache_benchmarks must use atomic write (temp file + os.replace).

    Under concurrent writes, every reader must always see either the old data
    or a complete new JSON document — never a truncated or corrupted file.
    """
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(
        "gearbox.agents.audit._BENCHMARK_CACHE_DIR",
        cache_dir,
    )

    repo = "owner/repo"
    benchmarks_a = ["repo-a-1", "repo-a-2"]
    benchmarks_b = ["repo-b-1", "repo-b-2", "repo-b-3"]

    # Write initial cache so _get_cached_benchmarks has something to read
    _cache_benchmarks(repo, benchmarks_a)
    cached = _get_cached_benchmarks(repo)
    assert cached == benchmarks_a

    errors: list[str] = []

    def writer(label: str, data: list[str]) -> None:
        try:
            for _ in range(50):
                _cache_benchmarks(repo, data)
                # Immediately after write, the file MUST be valid JSON
                cache_file = cache_dir / f"{repo.replace('/', '_')}.json"
                raw = cache_file.read_text(encoding="utf-8")
                parsed = json.loads(raw)  # will raise on truncation / corruption
                assert "benchmarks" in parsed
                assert "cached_at" in parsed
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    def reader() -> None:
        try:
            for _ in range(50):
                result = _get_cached_benchmarks(repo)
                # Result is either None (stale/expired), benchmarks_a, or benchmarks_b
                if result is not None:
                    assert result in (benchmarks_a, benchmarks_b), (
                        f"Unexpected benchmarks: {result}"
                    )
        except Exception as exc:
            errors.append(f"reader: {exc}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [
            pool.submit(writer, "writer-A", benchmarks_a),
            pool.submit(writer, "writer-B", benchmarks_b),
            pool.submit(reader),
            pool.submit(reader),
        ]
        for f in as_completed(futs):
            f.result()  # re-raise

    assert not errors, f"Concurrent access produced errors: {errors}"

    # Final state must be valid JSON with expected keys
    final_raw = (cache_dir / f"{repo.replace('/', '_')}.json").read_text(encoding="utf-8")
    final = json.loads(final_raw)
    assert "benchmarks" in final
    assert "cached_at" in final


def test_cache_benchmarks_replaces_not_overwrites(tmp_path: Path, monkeypatch) -> None:
    """Verify that _cache_benchmarks uses os.replace (atomic rename), not Path.write_text.

    We check this indirectly by confirming the inode changes after each write,
    which only happens with os.replace.  With direct write_text the inode stays
    the same because the file is opened in-place.
    """

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(
        "gearbox.agents.audit._BENCHMARK_CACHE_DIR",
        cache_dir,
    )

    repo = "owner/inode-test"

    _cache_benchmarks(repo, ["first"])
    cache_file = cache_dir / f"{repo.replace('/', '_')}.json"
    inode_before = cache_file.stat().st_ino

    _cache_benchmarks(repo, ["second"])
    inode_after = cache_file.stat().st_ino

    # Atomic replace creates a new inode; in-place write keeps the same one.
    assert inode_after != inode_before, (
        "_cache_benchmarks should use atomic os.replace(), "
        "but the inode did not change (suggests in-place write_text)"
    )
