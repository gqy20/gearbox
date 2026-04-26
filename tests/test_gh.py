"""测试 core/gh.py 模块"""

import subprocess
from unittest.mock import MagicMock

import pytest

from gearbox.core.gh import (
    VALID_ISSUE_LABELS,
    add_issue_labels,
    build_issue_body,
    build_review_body,
    create_issue,
    get_repo_labels,
    post_issue_comment,
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
