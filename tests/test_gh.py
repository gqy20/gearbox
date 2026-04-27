"""测试 core/gh.py 模块"""

import subprocess
from unittest.mock import MagicMock

import pytest

from gearbox.core.gh import (
    VALID_ISSUE_LABELS,
    IssueSummary,
    add_issue_labels,
    build_issue_body,
    build_review_body,
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
    """测试 Git push 认证配置。"""

    def test_uses_pat_origin_and_removes_checkout_extraheader(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        commands: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs) -> MagicMock:
            del kwargs
            commands.append(cmd)
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setenv("GH_TOKEN", "pat-token")
        monkeypatch.setattr(subprocess, "run", fake_run)

        configure_authenticated_origin("owner/repo")

        assert commands == [
            [
                "git",
                "config",
                "--unset-all",
                "http.https://github.com/.extraheader",
            ],
            [
                "git",
                "remote",
                "set-url",
                "origin",
                "https://x-access-token:pat-token@github.com/owner/repo.git",
            ],
        ]


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

    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock(
            return_value=MagicMock(stdout="https://github.com/owner/repo/issues/5")
        )
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = create_issue("owner/repo", "Test Title", "Test Body", ["enhancement"])
        assert result.success is True
        assert "issues/5" in (result.pr_url or "")

    def test_labels_filtered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)

        # "invalid-label" is not in VALID_ISSUE_LABELS, should be filtered
        create_issue("owner/repo", "Title", "Body", ["enhancement", "invalid-label"])
        call_args = mock_run.call_args[0][0]
        assert "--label" in call_args
        # Should only have enhancement, not invalid-label
        assert "invalid-label" not in call_args


class TestFinalizeAndCreatePr:
    """测试分支提交和 PR 创建。"""

    def test_configures_origin_with_gh_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GH_TOKEN", "pat-token")
        commands: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs) -> MagicMock:
            del kwargs
            commands.append(cmd)
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        configure_authenticated_origin("owner/repo")

        assert [
            "git",
            "remote",
            "set-url",
            "origin",
            "https://x-access-token:pat-token@github.com/owner/repo.git",
        ] in commands

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


class TestBuildIssueBody:
    """测试 build_issue_body"""

    def test_basic_body(self) -> None:
        body = build_issue_body("P1", "M", None, True)
        assert "P1" in body
        assert "M" in body
        assert "✅" in body

    def test_with_clarification(self) -> None:
        body = build_issue_body("P2", "L", "What use case?", False)
        assert "P2" in body
        assert "需要澄清" in body
        assert "What use case?" in body


class TestValidIssueLabels:
    """测试 VALID_ISSUE_LABELS"""

    def test_contains_standard_labels(self) -> None:
        standard = {"bug", "enhancement", "documentation", "help wanted"}
        assert standard.issubset(VALID_ISSUE_LABELS)

    def test_is_frozenset(self) -> None:
        from gearbox.core.gh import VALID_ISSUE_LABELS

        assert isinstance(VALID_ISSUE_LABELS, (set, frozenset))
