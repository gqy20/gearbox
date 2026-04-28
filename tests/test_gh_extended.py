"""Extended tests for core/gh.py — uncovered functions and constants."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gearbox.core.gh import (
    BACKLOG_LABEL_METADATA,
    MANAGED_BACKLOG_LABELS,
    VALID_ISSUE_LABELS,
    _called_process_error_message,
    _label_metadata,
    create_repo_label,
    get_issue_label_events,
    get_issue_labels,
    remove_issue_labels,
    write_outputs,
)

# ---------------------------------------------------------------------------
# Constants and metadata helpers
# ---------------------------------------------------------------------------


class TestValidIssueLabels:
    """测试 VALID_ISSUE_LABELS 常量完整性"""

    def test_contains_all_priority_labels(self) -> None:
        for p in ("P0", "P1", "P2", "P3", "P4"):
            assert p in VALID_ISSUE_LABELS

    def test_contains_all_complexity_labels(self) -> None:
        for c in ("complexity:S", "complexity:M", "complexity:L"):
            assert c in VALID_ISSUE_LABELS

    def test_contains_status_labels(self) -> None:
        for s in ("ready-to-implement", "in-progress", "needs-clarification", "has-pr"):
            assert s in VALID_ISSUE_LABELS

    def test_contains_github_defaults(self) -> None:
        for d in ("bug", "enhancement", "documentation", "duplicate"):
            assert d in VALID_ISSUE_LABELS


class TestBacklogLabelMetadata:
    """测试 BACKLOG_LABEL_METADATA"""

    def test_has_all_managed_labels(self) -> None:
        expected = {
            "P0",
            "P1",
            "P2",
            "P3",
            "complexity:S",
            "complexity:M",
            "complexity:L",
            "needs-clarification",
            "ready-to-implement",
            "in-progress",
            "has-pr",
        }
        assert set(BACKLOG_LABEL_METADATA.keys()) == expected

    def test_each_entry_has_color_and_description(self) -> None:
        for label, (color, desc) in BACKLOG_LABEL_METADATA.items():
            assert isinstance(color, str) and len(color) == 6, f"{label} color invalid"
            assert isinstance(desc, str) and len(desc) > 0, f"{label} description empty"


class TestManagedBacklogLabels:
    """测试 MANAGED_BACKLOG_LABELS"""

    def test_is_frozenset(self) -> None:
        assert isinstance(MANAGED_BACKLOG_LABELS, frozenset)

    def test_matches_backlog_label_metadata_keys(self) -> None:
        assert MANAGED_BACKLOG_LABELS == frozenset(BACKLOG_LABEL_METADATA)


class TestLabelMetadata:
    """测试 _label_metadata"""

    def test_returns_known_metadata(self) -> None:
        color, desc = _label_metadata("P1")
        assert color == "d93f0b"
        assert "核心功能" in desc

    def test_fallback_for_unknown_label(self) -> None:
        color, desc = _label_metadata("unknown-label")
        assert color == "cfd3d7"
        assert "Gearbox" in desc


# ---------------------------------------------------------------------------
# create_repo_label
# ---------------------------------------------------------------------------


class TestCreateRepoLabel:
    """测试 create_repo_label"""

    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = create_repo_label("owner/repo", "P1")

        assert result.success is True
        cmd = mock_run.call_args[0][0]
        assert cmd[0:3] == ["gh", "label", "create"]
        assert "P1" in cmd
        assert "--color" in cmd
        assert "--description" in cmd

    def test_already_exists_treated_as_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock(
            side_effect=subprocess.CalledProcessError(1, "gh", stderr="Label already exists")
        )
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = create_repo_label("owner/repo", "bug")

        assert result.success is True

    def test_real_failure_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock(
            side_effect=subprocess.CalledProcessError(1, "gh", stderr="permission denied")
        )
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = create_repo_label("owner/repo", "P1")

        assert result.success is False
        assert "permission denied" in (result.url or "")


# ---------------------------------------------------------------------------
# remove_issue_labels
# ---------------------------------------------------------------------------


class TestRemoveIssueLabels:
    """测试 remove_issue_labels"""

    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = remove_issue_labels("owner/repo", 42, ["bug", "P1"])

        assert result.success is True
        cmd = mock_run.call_args[0][0]
        assert "issue" in cmd
        assert "edit" in cmd
        assert "--remove-label" in cmd
        assert "bug,P1" in cmd

    def test_empty_labels_no_op(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock()
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = remove_issue_labels("owner/repo", 42, [])

        assert result.success is True
        mock_run.assert_not_called()

    def test_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock(side_effect=subprocess.CalledProcessError(1, "gh", stderr="error"))
        monkeypatch.setattr(subprocess, "run", mock_run)

        result = remove_issue_labels("owner/repo", 42, ["bug"])

        assert result.success is False


# ---------------------------------------------------------------------------
# get_issue_labels
# ---------------------------------------------------------------------------


class TestGetIssueLabels:
    """测试 get_issue_labels"""

    def test_returns_labels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock(return_value=MagicMock(stdout='["bug","enhancement"]'))
        monkeypatch.setattr(subprocess, "run", mock_run)

        labels = get_issue_labels("owner/repo", 7)

        assert labels == ["bug", "enhancement"]

    def test_returns_empty_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock(side_effect=subprocess.CalledProcessError(1, "gh"))
        monkeypatch.setattr(subprocess, "run", mock_run)

        labels = get_issue_labels("owner/repo", 99)

        assert labels == []

    def test_returns_empty_on_json_decode_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock(return_value=MagicMock(stdout="not-json"))
        monkeypatch.setattr(subprocess, "run", mock_run)

        labels = get_issue_labels("owner/repo", 1)

        assert labels == []


# ---------------------------------------------------------------------------
# get_issue_label_events
# ---------------------------------------------------------------------------


class TestGetIssueLabelEvents:
    """测试 get_issue_label_events"""

    def test_filters_by_target_labels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The jq filter extracts .label.name as a string
        payload = (
            '{"event":"labeled","label":"P1","created_at":"2026-04-27T12:00:00Z"}\n'
            '{"event":"unlabeled","label":"P2","created_at":"2026-04-27T13:00:00Z"}\n'
            '{"event":"labeled","label":"other","created_at":"2026-04-27T14:00:00Z"}'
        )
        mock_run = MagicMock(return_value=MagicMock(stdout=payload))
        monkeypatch.setattr(subprocess, "run", mock_run)

        events = get_issue_label_events("owner/repo", 7, {"P1", "P2"}, since_days=2)

        assert len(events) == 2
        assert events[0].label == "P1"
        assert events[0].event == "labeled"
        assert events[1].label == "P2"
        assert events[1].event == "unlabeled"

    def test_returns_empty_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock(side_effect=subprocess.CalledProcessError(1, "gh", stderr="error"))
        monkeypatch.setattr(subprocess, "run", mock_run)

        events = get_issue_label_events("owner/repo", 7, {"P1"})

        assert events == []

    def test_skips_blank_lines(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = '\n{"event":"labeled","label":"P1","created_at":"2026-04-27T12:00:00Z"}\n\n'
        mock_run = MagicMock(return_value=MagicMock(stdout=payload))
        monkeypatch.setattr(subprocess, "run", mock_run)

        events = get_issue_label_events("owner/repo", 7, {"P1"})

        assert len(events) == 1


# ---------------------------------------------------------------------------
# write_outputs
# ---------------------------------------------------------------------------


class TestWriteOutputs:
    """测试 write_outputs"""

    def test_writes_key_value_pairs(self, tmp_path: Path) -> None:
        output_file = tmp_path / "github_output"
        write_outputs({"key1": "value1", "key2": "value2"}, str(output_file))

        content = output_file.read_text(encoding="utf-8")
        assert "key1=value1\n" in content
        assert "key2=value2\n" in content

    def test_creates_file_if_not_exists(self, tmp_path: Path) -> None:
        output_file = tmp_path / "new_output"
        write_outputs({"x": "y"}, str(output_file))

        assert output_file.exists()


# ---------------------------------------------------------------------------
# _called_process_error_message
# ---------------------------------------------------------------------------


class TestCalledProcessErrorMessage:
    """测试 _called_process_error_message"""

    def test_prefers_stderr(self) -> None:
        err = subprocess.CalledProcessError(1, "cmd", output="stdout msg", stderr="error msg")
        assert _called_process_error_message(err) == "error msg"

    def test_falls_back_to_stdout(self) -> None:
        err = subprocess.CalledProcessError(1, "cmd", output="stdout msg", stderr="")
        assert _called_process_error_message(err) == "stdout msg"

    def test_falls_back_to_str(self) -> None:
        err = subprocess.CalledProcessError(1, "cmd", output=b"", stderr=b"")
        result = _called_process_error_message(err)
        assert len(result) > 0  # should return something non-empty
