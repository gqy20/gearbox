"""Tests for audit helpers."""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from gearbox.agents.audit import OUTPUT_FILES, AuditResult, Issue, _write_audit_outputs
from gearbox.agents.shared import clone_repository, scanner
from gearbox.agents.shared.scanner import scan_repository


def _make_sample_result() -> AuditResult:
    return AuditResult(
        repo="owner/repo",
        profile={"language": "Python", "files": 10},
        comparison_markdown="# Comparison\n\nSome analysis.",
        benchmarks=["benchmark/repo"],
        issues=[
            Issue(
                title="Test issue",
                body="Test body\n> **severity**: high",
                labels="enhancement",
            )
        ],
    )


class TestWriteAuditOutputsAtomic:
    """Verify _write_audit_outputs writes all three files atomically."""

    def test_writes_all_three_output_files(self, tmp_path: Path) -> None:
        result = _make_sample_result()
        _write_audit_outputs(result, tmp_path)

        for name in OUTPUT_FILES:
            assert (tmp_path / name).exists(), f"Missing output file: {name}"

    def test_issues_json_content(self, tmp_path: Path) -> None:
        result = _make_sample_result()
        _write_audit_outputs(result, tmp_path)

        data = json.loads((tmp_path / "issues.json").read_text(encoding="utf-8"))
        assert data["repo"] == "owner/repo"
        assert data["profile"]["language"] == "Python"
        assert len(data["issues"]) == 1
        assert data["issues"][0]["title"] == "Test issue"

    def test_profile_json_content(self, tmp_path: Path) -> None:
        result = _make_sample_result()
        _write_audit_outputs(result, tmp_path)

        data = json.loads((tmp_path / "profile.json").read_text(encoding="utf-8"))
        assert data["language"] == "Python"
        assert data["files"] == 10

    def test_comparison_md_content(self, tmp_path: Path) -> None:
        result = _make_sample_result()
        _write_audit_outputs(result, tmp_path)

        content = (tmp_path / "comparison.md").read_text(encoding="utf-8")
        assert content.startswith("# Comparison")
        assert "Some analysis." in content

    def test_comparison_md_fallback_when_empty(self, tmp_path: Path) -> None:
        result = _make_sample_result()
        result.comparison_markdown = ""
        _write_audit_outputs(result, tmp_path)

        content = (tmp_path / "comparison.md").read_text(encoding="utf-8")
        assert "No comparison markdown returned." in content

    def test_atomic_write_uses_temp_dir_and_replace(self, tmp_path: Path) -> None:
        """Verify files are written via temp dir + os.replace for atomicity."""
        result = _make_sample_result()

        replace_calls: list[tuple[Path, Path]] = []
        orig_replace = os.replace

        def tracking_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
            replace_calls.append((Path(src), Path(dst)))
            orig_replace(src, dst)

        with patch("os.replace", side_effect=tracking_replace):
            _write_audit_outputs(result, tmp_path)

        # All three output files must be moved atomically via os.replace
        replaced_names = {call[1].name for call in replace_calls}
        assert replaced_names == set(OUTPUT_FILES), (
            f"Expected os.replace for {set(OUTPUT_FILES)}, got {replaced_names}"
        )

    def test_no_partial_write_on_success(self, tmp_path: Path) -> None:
        """After a successful call, all three files must represent the same result."""
        old_result = AuditResult(
            repo="old/repo",
            profile={"language": "Go"},
            comparison_markdown="# Old",
            issues=[Issue(title="Old", body="old", labels="bug")],
        )
        new_result = _make_sample_result()

        # Write old data first
        _write_audit_outputs(old_result, tmp_path)
        # Write new data — must fully replace old
        _write_audit_outputs(new_result, tmp_path)

        issues_data = json.loads((tmp_path / "issues.json").read_text(encoding="utf-8"))
        profile_data = json.loads((tmp_path / "profile.json").read_text(encoding="utf-8"))
        comparison = (tmp_path / "comparison.md").read_text(encoding="utf-8")

        # All three files must reflect the NEW result, not a mix
        assert issues_data["repo"] == "owner/repo"
        assert profile_data["language"] == "Python"
        assert "# Comparison" in comparison


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
