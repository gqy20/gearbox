"""测试 core/gh.py 模块"""

import os
import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from gearbox.core.gh import (
    VALID_ISSUE_LABELS,
    IssueSummary,
    PostReviewResult,
    _called_process_error_message,
    _sanitize_token_from_output,
    add_issue_labels,
    build_review_body,
    cleanup_authenticated_origin,
    configure_authenticated_origin,
    create_issue,
    finalize_and_create_pr,
    finalize_and_push,
    get_issue_summary,
    get_repo_labels,
    list_open_issues,
    post_issue_comment,
    post_review_comment,
    replace_managed_issue_labels,
)


class TestPostIssueComment:
    """测试 post_issue_comment"""

    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = post_issue_comment("owner/repo", 42, "Hello")
        assert result.success is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "issue" in call_args
        assert "comment" in call_args
        assert "owner/repo" in call_args
        assert "42" in call_args

    def test_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock(side_effect=subprocess.CalledProcessError(1, "gh", stderr="error"))
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = post_issue_comment("owner/repo", 42, "Hello")
        assert result.success is False


class TestPostReviewComment:
    """测试 post_review_comment"""

    @pytest.mark.parametrize(
        ("event", "expected_flag"),
        [
            ("APPROVE", "--approve"),
            ("COMMENT", "--comment"),
            ("REQUEST_CHANGES", "--request-changes"),
        ],
    )
    def test_maps_review_event_to_gh_cli_flag(
        self, monkeypatch: pytest.MonkeyPatch, event: str, expected_flag: str
    ) -> None:
        captured: list[str] = []

        def fake_run(cmd: list[str], **kwargs) -> MagicMock:
            del kwargs
            captured.extend(cmd)
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = post_review_comment("owner/repo", 8, "body", event)

        assert result.success is True
        assert expected_flag in captured
        assert "--event" not in captured


class TestConfigureAuthenticatedOrigin:
    """测试 Git push 认证配置（安全版本：不将 token 嵌入 URL）。"""

    def test_sets_clean_url_without_embedded_token(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """origin URL 不应包含明文 token。"""
        commands: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs) -> MagicMock:
            del kwargs
            commands.append(cmd)
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setenv("GH_TOKEN", "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890")
        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(
            "gearbox.core.gh.tempfile", __import__("tempfile", fromlist=["mkdtemp"])
        )
        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: str(tmp_path))

        askpass_path = configure_authenticated_origin("owner/repo")

        # 验证 extraheader 被移除
        assert ["git", "config", "--unset-all", "http.https://github.com/.extraheader"] in commands

        # 验证 URL 中不含 token
        set_url_cmd = [c for c in commands if c[0:3] == ["git", "remote", "set-url"]]
        assert len(set_url_cmd) == 1
        url = set_url_cmd[0][4]  # git remote set-url origin <url>
        assert "x-access-token:" not in url
        assert "ghp_AbCdEf" not in url
        assert url == "https://github.com/owner/repo.git"

        # 应返回 askpass 脚本路径
        assert askpass_path is not None
        assert os.path.isfile(askpass_path)

    def test_creates_askpass_script_with_token(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """askpass 脚本应包含 token 但不在命令行或 git config 中暴露。"""
        token = "ghp_SecretTokenValue1234567890"

        def fake_run(cmd: list[str], **kwargs) -> MagicMock:
            del kwargs
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setenv("GH_TOKEN", token)
        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(
            "gearbox.core.gh.tempfile", __import__("tempfile", fromlist=["mkdtemp"])
        )
        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: str(tmp_path))

        askpass_path = configure_authenticated_origin("owner/repo")

        # 验证 askpass 脚本内容包含 token（用于 git 认证）
        with open(askpass_path) as f:
            content = f.read()
        assert token in content

    def test_returns_none_when_no_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无 GH_TOKEN 时返回 None 且不调用 set-url。"""
        commands: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs) -> MagicMock:
            del kwargs
            commands.append(cmd)
            return MagicMock(returncode=0, stdout="")

        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setattr(subprocess, "run", fake_run)

        result = configure_authenticated_origin("owner/repo")

        assert result is None
        set_url_cmds = [c for c in commands if c[0:3] == ["git", "remote", "set-url"]]
        assert len(set_url_cmds) == 0

    def test_removes_checkout_extraheader(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """必须移除 actions/checkout 注入的 extraheader。"""
        commands: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs) -> MagicMock:
            del kwargs
            commands.append(cmd)
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setenv("GH_TOKEN", "ghp_test")
        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(
            "gearbox.core.gh.tempfile", __import__("tempfile", fromlist=["mkdtemp"])
        )
        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: str(tmp_path))

        configure_authenticated_origin("owner/repo")

        assert [
            "git",
            "config",
            "--unset-all",
            "http.https://github.com/.extraheader",
        ] in commands


class TestCleanupAuthenticatedOrigin:
    """测试认证资源清理。"""

    def test_removes_askpass_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """cleanup 应删除 askpass 临时文件。"""
        token = "ghp_cleanup_test"

        def fake_run(cmd: list[str], **kwargs) -> MagicMock:
            del kwargs
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setenv("GH_TOKEN", token)
        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(
            "gearbox.core.gh.tempfile", __import__("tempfile", fromlist=["mkdtemp"])
        )
        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: str(tmp_path))

        askpass_path = configure_authenticated_origin("owner/repo")
        assert askpass_path is not None
        assert os.path.exists(askpass_path)

        cleanup_authenticated_origin(askpass_path)
        assert not os.path.exists(askpass_path)

    def test_handles_none_path_gracefully(self) -> None:
        """传入 None 时不应报错。"""
        cleanup_authenticated_origin(None)  # should not raise


class TestTokenSanitization:
    """测试 token 脱敏功能。"""

    def test_sanitizes_token_from_stderr(self) -> None:
        token = "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz"
        stderr = f"error: could not access https://x-access-token:{token}@github.com/o/r.git"
        result = _sanitize_token_from_output(stderr, token)
        assert token not in result
        assert "***" in result or "REDACTED" in result

    def test_sanitizes_token_from_url_with_pat(self) -> None:
        token = "github_pat_11ABCDEF"
        url = f"https://x-access-token:{token}@github.com/owner/repo.git"
        result = _sanitize_token_from_output(url, token)
        assert token not in result

    def test_preserves_message_without_token(self) -> None:
        msg = "error: fatal: not a git repository"
        result = _sanitize_token_from_output(msg, "ghp_fake")
        assert "not a git repository" in result

    def test_called_process_error_sanitizes_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        token = "ghp_SecretInError"
        monkeypatch.setenv("GH_TOKEN", token)
        stderr = f"fatal: push failed https://x-access-token:{token}@github.com/o/r.git"
        error = subprocess.CalledProcessError(1, "git", stderr=stderr)
        msg = _called_process_error_message(error)
        assert token not in msg

    def test_handles_empty_token_gracefully(self) -> None:
        msg = "some error message"
        result = _sanitize_token_from_output(msg, "")
        assert result == msg

    def test_handles_none_output(self) -> None:
        result = _sanitize_token_from_output(None, "ghp_test")  # type: ignore[arg-type]
        assert result == ""


class TestFinalizeAndCreatePrSecureCredentials:
    """测试 finalize_and_create_pr 使用安全凭证传递。"""

    def test_passes_git_askpass_env_to_push(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """git push 应通过 GIT_ASKPASS 环境变量接收凭证，而非 URL 内嵌。"""
        token = "ghp_PushTestToken123"
        push_envs: list[dict[str, str] | None] = []

        def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            if cmd[0:2] == ["git", "push"]:
                push_envs.append(kwargs.get("env"))
            if cmd == ["git", "diff", "--staged", "--quiet"]:
                return MagicMock(returncode=1, stdout="")
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setenv("GH_TOKEN", token)
        monkeypatch.setenv("GITHUB_ACTOR", "bot")
        monkeypatch.setenv("GITHUB_ACTOR_ID", "12345")
        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(
            "gearbox.core.gh.tempfile", __import__("tempfile", fromlist=["mkdtemp"])
        )
        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: str(tmp_path))

        finalize_and_create_pr(
            repo="owner/repo",
            temp_branch="gearbox/temp",
            final_branch="feat/test",
            commit_message="feat: test",
            pr_title="test",
            pr_body="body",
        )

        assert len(push_envs) == 1
        push_env = push_envs[0]
        assert push_env is not None
        assert "GIT_ASKPASS" in push_env
        # File existed at push time (verified inside fake_run callback above)
        assert push_env["GIT_ASKPASS"].endswith("askpass.sh")

    def test_cleans_up_askpass_after_push(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """push 完成后 askpass 文件应被清理。"""
        token = "ghp_CleanupAfterPush"

        def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            if cmd == ["git", "diff", "--staged", "--quiet"]:
                return MagicMock(returncode=1, stdout="")
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setenv("GH_TOKEN", token)
        monkeypatch.setenv("GITHUB_ACTOR", "bot")
        monkeypatch.setenv("GITHUB_ACTOR_ID", "12345")
        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(
            "gearbox.core.gh.tempfile", __import__("tempfile", fromlist=["mkdtemp"])
        )
        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: str(tmp_path))

        finalize_and_create_pr(
            repo="owner/repo",
            temp_branch="gearbox/temp",
            final_branch="feat/test",
            commit_message="feat: test",
            pr_title="test",
            pr_body="body",
        )

        # askpass 文件应在操作完成后被删除
        remaining_files = list(tmp_path.glob("*"))
        assert len(remaining_files) == 0

    def test_error_messages_are_sanitized(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """push 失败时错误信息中的 token 应被脱敏。"""
        token = "ghp_ErrorSanitizationTest"

        def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            if cmd[0:2] == ["git", "push"]:
                raise subprocess.CalledProcessError(
                    1,
                    cmd,
                    stderr=f"fatal: could not read username for https://x-access-token:{token}@github.com/o/r.git",
                )
            if cmd == ["git", "diff", "--staged", "--quiet"]:
                return MagicMock(returncode=1, stdout="")
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setenv("GH_TOKEN", token)
        monkeypatch.setenv("GITHUB_ACTOR", "bot")
        monkeypatch.setenv("GITHUB_ACTOR_ID", "12345")
        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(
            "gearbox.core.gh.tempfile", __import__("tempfile", fromlist=["mkdtemp"])
        )
        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: str(tmp_path))

        result = finalize_and_create_pr(
            repo="owner/repo",
            temp_branch="gearbox/temp",
            final_branch="feat/test",
            commit_message="feat: test",
            pr_title="test",
            pr_body="body",
        )

        assert result.success is False
        assert token not in (result.error or "")


class TestFinalizePushSecureCredentials:
    """测试 finalize_and_push 使用安全凭证传递。"""

    def test_passes_git_askpass_env_to_push(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        token = "ghp_PushSecureToken"

        def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            if cmd[0:2] == ["git", "push"]:
                env = kwargs.get("env")
                assert env is not None
                assert "GIT_ASKPASS" in env
                assert env["GIT_ASKPASS"].endswith("askpass.sh")
            if cmd == ["git", "diff", "--staged", "--quiet"]:
                return MagicMock(returncode=1, stdout="")
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setenv("GH_TOKEN", token)
        monkeypatch.setenv("GITHUB_ACTOR", "bot")
        monkeypatch.setenv("GITHUB_ACTOR_ID", "12345")
        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(
            "gearbox.core.gh.tempfile", __import__("tempfile", fromlist=["mkdtemp"])
        )
        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: str(tmp_path))

        finalize_and_push(
            repo="owner/repo",
            temp_branch="gearbox/temp",
            final_branch="feat/test",
            commit_message="feat: test",
            files=["src/test.py"],
        )


class TestAddIssueLabels:
    """测试 add_issue_labels"""

    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Mock get_repo_labels to return existing labels
        monkeypatch.setattr(
            "gearbox.core.gh.get_repo_labels", lambda repo: ["bug", "high-priority"]
        )
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = add_issue_labels("owner/repo", 42, ["bug", "high-priority"])
        assert result.success is True

    def test_empty_labels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = add_issue_labels("owner/repo", 42, [])
        assert result.success is True
        mock_run.assert_not_called()

    def test_creates_missing_labels_before_edit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("gearbox.core.gh.get_repo_labels", lambda repo: ["bug"])
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = add_issue_labels("owner/repo", 42, ["bug", "P3", "complexity:M"])

        assert result.success is True
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert [
            "gh",
            "label",
            "create",
            "P3",
            "--repo",
            "owner/repo",
            "--color",
            "0e8a16",
            "--description",
            "优化建议、便利性改进",
        ] in commands
        assert [
            "gh",
            "label",
            "create",
            "complexity:M",
            "--repo",
            "owner/repo",
            "--color",
            "fef2c0",
            "--description",
            "中等复杂度，预计 1-3 天",
        ] in commands
        assert commands[-1] == [
            "gh",
            "issue",
            "edit",
            "--repo",
            "owner/repo",
            "42",
            "--add-label",
            "bug,P3,complexity:M",
        ]


class TestReplaceManagedIssueLabels:
    """测试 Gearbox 管理标签幂等替换"""

    def test_removes_old_managed_labels_before_adding_new(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("gearbox.core.gh.get_repo_labels", lambda repo: ["P1", "P2"])
        monkeypatch.setattr(
            "gearbox.core.gh.get_issue_labels",
            lambda repo, issue: ["enhancement", "P1", "complexity:M"],
        )
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = replace_managed_issue_labels(
            "owner/repo", 42, ["enhancement", "P2", "complexity:S"]
        )

        assert result.success is True
        commands = [call.args[0] for call in mock_run.call_args_list]
        assert [
            "gh",
            "issue",
            "edit",
            "--repo",
            "owner/repo",
            "42",
            "--remove-label",
            "P1,complexity:M",
        ] in commands
        assert commands[-1] == [
            "gh",
            "issue",
            "edit",
            "--repo",
            "owner/repo",
            "42",
            "--add-label",
            "enhancement,P2,complexity:S",
        ]


class TestGetRepoLabels:
    """测试 get_repo_labels"""

    def test_returns_label_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock(return_value=MagicMock(stdout='[{"name":"bug"},{"name":"docs"}]'))
        monkeypatch.setattr(subprocess, "run", mock_run)

        assert get_repo_labels("owner/repo") == ["bug", "docs"]

    def test_returns_empty_list_when_gh_label_list_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_run = MagicMock(side_effect=subprocess.CalledProcessError(4, "gh"))
        monkeypatch.setattr(subprocess, "run", mock_run)

        assert get_repo_labels("owner/repo") == []


class TestIssueListing:
    """测试 Issue 查询摘要。"""

    def test_list_open_issues_returns_summaries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock(
            return_value=MagicMock(
                stdout=(
                    '[{"number":7,"title":"T","labels":[{"name":"P1"}],'
                    '"url":"https://github.com/o/r/issues/7","createdAt":"2026-04-26T00:00:00Z"}]'
                )
            )
        )
        monkeypatch.setattr(subprocess, "run", mock_run)

        issues = list_open_issues("owner/repo", labels=["ready-to-implement"], limit=50)

        assert issues == [
            IssueSummary(
                number=7,
                title="T",
                labels=["P1"],
                url="https://github.com/o/r/issues/7",
                created_at="2026-04-26T00:00:00Z",
            )
        ]
        cmd = mock_run.call_args.args[0]
        assert cmd[-2:] == ["--label", "ready-to-implement"]
        assert "--limit" in cmd
        assert "50" in cmd

    def test_get_issue_summary_returns_none_for_closed_issue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_run = MagicMock(
            return_value=MagicMock(
                stdout='{"number":7,"title":"T","labels":[],"url":"","createdAt":"","state":"CLOSED"}'
            )
        )
        monkeypatch.setattr(subprocess, "run", mock_run)

        assert get_issue_summary("owner/repo", 7) is None


class TestCreateIssue:
    """测试 create_issue"""

    def test_creates_issue_then_adds_labels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        commands: list[list[str]] = []
        label_calls: list[tuple[str, int, list[str]]] = []

        def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            del kwargs
            commands.append(cmd)
            return MagicMock(returncode=0, stdout="https://github.com/owner/repo/issues/5\n")

        def fake_add_labels(repo: str, issue_number: int, labels: list[str]) -> PostReviewResult:
            label_calls.append((repo, issue_number, labels))
            return PostReviewResult(True)

        monkeypatch.setattr("subprocess.run", fake_run)
        monkeypatch.setattr("gearbox.core.gh.add_issue_labels", fake_add_labels)

        result = create_issue("owner/repo", "Title", "Body", ["enhancement", "P2"])

        assert result.success is True
        assert result.pr_url == "https://github.com/owner/repo/issues/5"
        assert commands[0][0:3] == ["gh", "issue", "create"]
        assert "--label" not in commands[0]
        assert label_calls == [("owner/repo", 5, ["enhancement", "P2"])]

    def test_skips_label_step_when_no_labels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        commands: list[list[str]] = []
        label_calls: list[tuple[str, int, list[str]]] = []

        def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            del kwargs
            commands.append(cmd)
            return MagicMock(returncode=0, stdout="https://github.com/owner/repo/issues/5\n")

        def fake_add_labels(repo: str, issue_number: int, labels: list[str]) -> PostReviewResult:
            label_calls.append((repo, issue_number, labels))
            return PostReviewResult(True)

        monkeypatch.setattr("subprocess.run", fake_run)
        monkeypatch.setattr("gearbox.core.gh.add_issue_labels", fake_add_labels)

        result = create_issue("owner/repo", "Title", "Body", None)

        assert result.success is True
        assert len(commands) == 1
        assert label_calls == []

    def test_filters_invalid_labels_before_adding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        label_calls: list[tuple[str, int, list[str]]] = []

        def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            del kwargs
            return MagicMock(returncode=0, stdout="https://github.com/owner/repo/issues/42\n")

        def fake_add_labels(repo: str, issue_number: int, labels: list[str]) -> PostReviewResult:
            label_calls.append((repo, issue_number, labels))
            return PostReviewResult(True)

        monkeypatch.setattr("subprocess.run", fake_run)
        monkeypatch.setattr("gearbox.core.gh.add_issue_labels", fake_add_labels)

        create_issue("owner/repo", "Title", "Body", ["enhancement", "invalid-label", "P1"])

        assert label_calls == [("owner/repo", 42, ["enhancement", "P1"])]

    def test_returns_failure_when_create_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            subprocess,
            "run",
            MagicMock(side_effect=subprocess.CalledProcessError(1, "gh", stderr="not found")),
        )

        result = create_issue("owner/repo", "Title", "Body", ["enhancement"])

        assert result.success is False
        assert "not found" in (result.error or "")

    def test_succeeds_even_if_labels_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
            del kwargs
            return MagicMock(returncode=0, stdout="https://github.com/owner/repo/issues/5\n")

        def fake_add_labels(*args: Any) -> PostReviewResult:
            return PostReviewResult(False, url="label error")

        monkeypatch.setattr("subprocess.run", fake_run)
        monkeypatch.setattr("gearbox.core.gh.add_issue_labels", fake_add_labels)

        result = create_issue("owner/repo", "Title", "Body", ["enhancement"])

        assert result.success is True


class TestFinalizeAndCreatePr:
    """测试分支提交和 PR 创建。"""

    def test_configures_origin_without_embedded_token(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """configure_authenticated_origin 不再将 token 嵌入 origin URL。"""
        monkeypatch.setenv("GH_TOKEN", "pat-token")
        commands: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs) -> MagicMock:
            del kwargs
            commands.append(cmd)
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(
            "gearbox.core.gh.tempfile", __import__("tempfile", fromlist=["mkdtemp"])
        )
        monkeypatch.setattr("tempfile.mkdtemp", lambda **kw: str(tmp_path))

        configure_authenticated_origin("owner/repo")

        set_url_cmd = [c for c in commands if c[0:3] == ["git", "remote", "set-url"]]
        assert len(set_url_cmd) == 1
        url = set_url_cmd[0][4]  # git remote set-url origin <url>
        assert "pat-token" not in url
        assert "x-access-token:" not in url

    def test_sets_git_author_before_commit_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTOR", "gqy20")
        monkeypatch.setenv("GITHUB_ACTOR_ID", "12345")
        commands: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs) -> MagicMock:
            commands.append(cmd)
            if cmd == ["git", "config", "--get", "user.name"]:
                return MagicMock(stdout="")
            if cmd == ["git", "config", "--get", "user.email"]:
                return MagicMock(stdout="")
            if cmd == ["git", "diff", "--staged", "--quiet"]:
                return MagicMock(returncode=1)
            if cmd[0:3] == ["gh", "pr", "create"]:
                return MagicMock(stdout="https://github.com/owner/repo/pull/1")
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = finalize_and_create_pr(
            repo="owner/repo",
            temp_branch="gearbox/temp",
            final_branch="feat/issue-2",
            commit_message="feat: test",
            pr_title="feat: test",
            pr_body="body",
        )

        assert result.success is True
        assert ["git", "config", "user.name", "gqy20"] in commands
        assert [
            "git",
            "config",
            "user.email",
            "12345+github-actions[bot]@users.noreply.github.com",
        ] in commands
        assert ["git", "commit", "-m", "feat: test"] in commands

    def test_push_sets_git_author_before_commit_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTOR", "gqy20")
        monkeypatch.setenv("GITHUB_ACTOR_ID", "12345")
        commands: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs) -> MagicMock:
            commands.append(cmd)
            if cmd == ["git", "config", "--get", "user.name"]:
                return MagicMock(stdout="")
            if cmd == ["git", "config", "--get", "user.email"]:
                return MagicMock(stdout="")
            if cmd == ["git", "diff", "--staged", "--quiet"]:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = finalize_and_push(
            repo="owner/repo",
            temp_branch="gearbox/temp",
            final_branch="feat/issue-2-run-0",
            commit_message="feat: test",
            files=["src/example.py"],
        )

        assert result is True
        assert ["git", "config", "user.name", "gqy20"] in commands
        assert [
            "git",
            "config",
            "user.email",
            "12345+github-actions[bot]@users.noreply.github.com",
        ] in commands
        assert ["git", "commit", "-m", "feat: test"] in commands

    def test_called_process_error_without_stderr_is_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_run(cmd: list[str], **kwargs) -> MagicMock:
            if cmd == ["git", "branch", "-m", "gearbox/temp", "feat/issue-2"]:
                raise subprocess.CalledProcessError(128, cmd)
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = finalize_and_create_pr(
            repo="owner/repo",
            temp_branch="gearbox/temp",
            final_branch="feat/issue-2",
            commit_message="feat: test",
            pr_title="feat: test",
            pr_body="body",
        )

        assert result.success is False
        assert result.error


class TestBuildReviewBody:
    """测试 build_review_body"""

    def test_basic_body(self) -> None:
        body = build_review_body("LGTM", 8, "Good work", [])
        assert "LGTM" in body
        assert "8" in body
        assert "Good work" in body

    def test_with_comments(self) -> None:
        comments = [
            {"file": "src/main.py", "line": 42, "body": "Style issue", "severity": "warning"},
            {"file": "src/utils.py", "line": 10, "body": "Bug here", "severity": "blocker"},
        ]
        body = build_review_body("Request Changes", 5, "Has issues", comments)
        assert "Request Changes" in body
        assert "src/main.py" in body
        assert "42" in body
        assert "Bug here" in body
        assert "src/utils.py" in body


class TestValidIssueLabels:
    """测试 VALID_ISSUE_LABELS"""

    def test_contains_standard_labels(self) -> None:
        standard = {"bug", "enhancement", "documentation", "help wanted"}
        assert standard.issubset(VALID_ISSUE_LABELS)

    def test_is_frozenset(self) -> None:
        from gearbox.core.gh import VALID_ISSUE_LABELS

        assert isinstance(VALID_ISSUE_LABELS, (set, frozenset))
