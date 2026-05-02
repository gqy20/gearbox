"""Tests for audit helpers."""

import json
import subprocess
from pathlib import Path

import pytest

from gearbox.agents.shared import clone_repository, scanner
from gearbox.agents.shared.git import validate_repo_identifier
from gearbox.agents.shared.scanner import scan_repository

# =============================================================================
# validate_repo_identifier tests
# =============================================================================


class TestValidateRepoIdentifier:
    """测试仓库标识符格式校验。"""

    def test_valid_owner_repo_format(self) -> None:
        """标准 owner/repo 格式应通过校验。"""
        validate_repo_identifier("owner/repo")
        validate_repo_identifier("gqy20/gearbox")
        validate_repo_identifier("abc123/def-456.repo")

    def test_valid_owner_repo_with_underscore_and_dot(self) -> None:
        """允许下划线和点号的 owner/repo 格式。"""
        validate_repo_identifier("my_org.my_repo/sub_package")

    def test_rejects_empty_string(self) -> None:
        """空字符串应被拒绝。"""
        with pytest.raises(ValueError, match="repo.*格式"):
            validate_repo_identifier("")

    def test_rejects_no_slash(self) -> None:
        """缺少斜杠的字符串应被拒绝（非本地路径时）。"""
        with pytest.raises(ValueError, match="repo.*格式"):
            validate_repo_identifier("justaname")

    def test_rejects_multiple_slashes(self) -> None:
        """多个斜杠的路径式字符串应被拒绝。"""
        with pytest.raises(ValueError, match="repo.*格式"):
            validate_repo_identifier("a/b/c")

    def test_rejects_path_traversal(self) -> None:
        """包含 .. 路径遍历的值应被拒绝。"""
        with pytest.raises(ValueError, match="repo.*格式"):
            validate_repo_identifier("../etc/passwd")

    def test_rejects_special_characters(self) -> None:
        """包含特殊字符的值应被拒绝。"""
        with pytest.raises(ValueError, match="repo.*格式"):
            validate_repo_identifier("owner/repo;rm -rf /")

    def test_accepts_local_existing_path(self, tmp_path: Path) -> None:
        """已存在的本地路径应通过校验。"""
        validate_repo_identifier(str(tmp_path))

    def test_rejects_non_local_non_owner_repo(self) -> None:
        """既不是本地路径也不是 owner/repo 格式的值应被拒绝。"""
        with pytest.raises(ValueError, match="repo.*格式"):
            validate_repo_identifier("not-a-valid-repo-identifier")


class TestCachePathSecurity:
    """测试缓存路径安全防护。"""

    def test_cache_filename_sanitizes_slash(self) -> None:
        """缓存文件名中的 / 应被替换为 _ 。"""
        from gearbox.agents.audit import _safe_cache_filename

        result = _safe_cache_filename("owner/repo")
        assert "/" not in result
        assert result == "owner_repo"

    def test_cache_path_resolves_within_cache_dir(self, tmp_path: Path) -> None:
        """解析后的缓存路径必须在缓存目录内，防止路径遍历。"""
        from gearbox.agents.audit import _assert_cache_path_safe

        # 正常情况不应抛异常
        _assert_cache_path_safe(tmp_path / "owner_repo.json", tmp_path)

    def test_cache_path_rejects_traversal(self, tmp_path: Path) -> None:
        """包含 .. 的路径应被拒绝。"""
        from gearbox.agents.audit import _assert_cache_path_safe

        traversal_path = tmp_path / ".." / "etc" / "passwd.json"
        with pytest.raises(ValueError, match="路径遍历"):
            _assert_cache_path_safe(traversal_path.resolve(), tmp_path)


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
