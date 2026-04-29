"""Integration tests for Backlog Agent — run_backlog_item with fully mocked SDK stack."""

import asyncio
import json

import pytest

from gearbox.agents.backlog import (
    BacklogResult,
    _gh_issue_view,
    github_labels_for_backlog_item,
    load_backlog_result,
    write_backlog_result,
)
from gearbox.agents.schemas import BacklogItemResult

# ---------------------------------------------------------------------------
# Pure function tests already in test_agents.py — add backlog-specific ones here
# ---------------------------------------------------------------------------


class TestBacklogResultRoundTrip:
    """Verify write_backlog_result / load_backlog_result round-trip."""

    def test_write_and_load_preserves_data(self, tmp_path) -> None:
        result = BacklogResult(
            items=[
                BacklogItemResult(
                    issue_number=42,
                    labels=["bug", "high-priority"],
                    priority="P1",
                    complexity="M",
                    ready_to_implement=True,
                )
            ]
        )

        output_path = tmp_path / "backlog_result.json"
        write_backlog_result(result, output_path)

        loaded = load_backlog_result(output_path)
        assert len(loaded.items) == 1
        assert loaded.items[0].issue_number == 42
        assert loaded.items[0].labels == ["bug", "high-priority"]
        assert loaded.items[0].priority == "P1"
        assert loaded.items[0].ready_to_implement is True


class TestGithubLabelsForBacklogItemEdgeCases:
    """Additional label generation edge cases beyond what's in test_agents.py."""

    def test_empty_labels_still_includes_priority_and_complexity(self) -> None:
        result = BacklogItemResult(
            labels=[],
            priority="P2",
            complexity="S",
            ready_to_implement=False,
        )
        labels = github_labels_for_backlog_item(result)
        assert labels == ["P2", "complexity:S"]

    def test_ready_to_implement_adds_label(self) -> None:
        result = BacklogItemResult(
            labels=["enhancement"],
            priority="P0",
            complexity="S",
            ready_to_implement=True,
        )
        labels = github_labels_for_backlog_item(result)
        assert "ready-to-implement" in labels
        assert "enhancement" in labels
        assert "P0" in labels

    def test_duplicate_labels_deduplicated(self) -> None:
        """If labels list contains priority or complexity as string, dedup."""
        result = BacklogItemResult(
            labels=["bug", "P1", "P1"],  # P1 duplicated
            priority="P1",
            complexity="M",
            ready_to_implement=False,
        )
        labels = github_labels_for_backlog_item(result)
        assert labels.count("P1") == 1  # deduplicated

    def test_all_fields_populated(self) -> None:
        result = BacklogItemResult(
            labels=["security", "documentation"],
            priority="P0",
            complexity="L",
            ready_to_implement=True,
        )
        labels = github_labels_for_backlog_item(result)
        assert len(labels) == 5  # 2 custom + priority + complexity + ready-to-implement
        assert "security" in labels
        assert "documentation" in labels
        assert "P0" in labels
        assert "complexity:L" in labels
        assert "ready-to-implement" in labels


# ---------------------------------------------------------------------------
# Integration: run_backlog_item with mocked SDK
# ---------------------------------------------------------------------------


class TestRunBacklogItem:
    """Full integration test for run_backlog_item mocking SDK, gh, and clone."""

    @staticmethod
    def _make_fake_query_stream(structured_data: dict):
        from claude_agent_sdk import ResultMessage

        msg = ResultMessage(
            subtype="result",
            duration_ms=800,
            duration_api_ms=600,
            is_error=False,
            num_turns=3,
            session_id="test-session",
            structured_output=structured_data,
        )

        async def _fake_query(*args, **kwargs):
            del args, kwargs
            yield msg

        return _fake_query

    def test_run_backlog_returns_parsed_result(self, monkeypatch) -> None:
        expected_structured = {
            "labels": ["bug", "performance"],
            "priority": "P1",
            "complexity": "M",
            "ready_to_implement": True,
        }

        monkeypatch.setattr(
            "gearbox.agents.backlog._gh_issue_view",
            lambda repo, number: {
                "title": "Slow query performance",
                "body": "## Problem\nQueries are slow\n\n## Solution\nAdd index",
                "labels": ["bug"],
                "state": "open",
            },
        )
        monkeypatch.setattr(
            "gearbox.core.gh.list_open_issues",
            lambda *args, **kwargs: [],
        )
        monkeypatch.setattr(
            "claude_agent_sdk.query",
            self._make_fake_query_stream(expected_structured),
        )

        class FakeLogger:
            def log_start(self, **kwargs) -> None:
                del kwargs

            def handle_message(self, *args, **kwargs) -> None:
                del args, kwargs

            def log_completion(self) -> None:
                pass

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime.prepare_agent_options",
            lambda options, agent_name: (options, FakeLogger()),
        )
        # Prevent actual git clone
        monkeypatch.setattr(
            "gearbox.agents.shared.clone_repository",
            lambda repo: (None, None),
        )

        from gearbox.agents.backlog import run_backlog_item

        result = asyncio.run(run_backlog_item("owner/repo", 42, model="test-model", max_turns=5))

        assert isinstance(result, BacklogItemResult)
        assert result.labels == ["bug", "performance"]
        assert result.priority == "P1"
        assert result.complexity == "M"
        assert result.ready_to_implement is True
        # issue_number should be injected after parsing
        assert result.issue_number == 42

    def test_run_backlog_raises_on_no_structured_output(self, monkeypatch) -> None:
        from claude_agent_sdk import ResultMessage

        msg = ResultMessage(
            subtype="result",
            duration_ms=100,
            duration_api_ms=80,
            is_error=False,
            num_turns=1,
            session_id="s",
            structured_output=None,
        )

        async def _fake_query(*args, **kwargs):
            del args, kwargs
            yield msg

        monkeypatch.setattr(
            "gearbox.agents.backlog._gh_issue_view",
            lambda repo, number: {"title": "T", "body": "B", "labels": [], "state": "open"},
        )
        monkeypatch.setattr(
            "gearbox.core.gh.list_open_issues",
            lambda *args, **kwargs: [],
        )
        monkeypatch.setattr("claude_agent_sdk.query", _fake_query)

        class FakeLogger:
            def log_start(self, **kwargs) -> None:
                del kwargs

            def handle_message(self, *args, **kwargs) -> None:
                del args, kwargs

            def log_completion(self) -> None:
                pass

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime.prepare_agent_options",
            lambda options, agent_name: (options, FakeLogger()),
        )
        monkeypatch.setattr(
            "gearbox.agents.shared.clone_repository",
            lambda repo: (None, None),
        )

        from gearbox.agents.backlog import run_backlog_item

        with pytest.raises(RuntimeError, match="did not return structured output"):
            asyncio.run(run_backlog_item("owner/repo", 1))

    def test_run_backlog_injects_issue_number(self, monkeypatch) -> None:
        """Verify that issue_number is set on the result even though it's not in schema output."""
        expected = {
            "labels": ["enhancement"],
            "priority": "P2",
            "complexity": "S",
            "ready_to_implement": False,
        }

        monkeypatch.setattr(
            "gearbox.agents.backlog._gh_issue_view",
            lambda repo, number: {"title": "T", "body": "B", "labels": [], "state": "open"},
        )
        monkeypatch.setattr(
            "gearbox.core.gh.list_open_issues",
            lambda *args, **kwargs: [],
        )
        monkeypatch.setattr(
            "claude_agent_sdk.query",
            self._make_fake_query_stream(expected),
        )

        class FakeLogger:
            def log_start(self, **kwargs) -> None:
                del kwargs

            def handle_message(self, *args, **kwargs) -> None:
                del args, kwargs

            def log_completion(self) -> None:
                pass

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime.prepare_agent_options",
            lambda options, agent_name: (options, FakeLogger()),
        )
        monkeypatch.setattr(
            "gearbox.agents.shared.clone_repository",
            lambda repo: (None, None),
        )

        from gearbox.agents.backlog import run_backlog_item

        result = asyncio.run(run_backlog_item("owner/repo", 99))
        assert result.issue_number == 99

    def test_run_backlog_handles_clone_failure_gracefully(self, monkeypatch) -> None:
        """Clone failure should not crash; cwd falls back to Path.cwd()."""
        expected = {
            "labels": ["question"],
            "priority": "P3",
            "complexity": "L",
            "ready_to_implement": False,
        }

        monkeypatch.setattr(
            "gearbox.agents.backlog._gh_issue_view",
            lambda repo, number: {"title": "T", "body": "B", "labels": [], "state": "open"},
        )
        monkeypatch.setattr(
            "gearbox.core.gh.list_open_issues",
            lambda *args, **kwargs: [],
        )
        monkeypatch.setattr(
            "claude_agent_sdk.query",
            self._make_fake_query_stream(expected),
        )

        class FakeLogger:
            def log_start(self, **kwargs) -> None:
                del kwargs

            def handle_message(self, *args, **kwargs) -> None:
                del args, kwargs

            def log_completion(self) -> None:
                pass

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime.prepare_agent_options",
            lambda options, agent_name: (options, FakeLogger()),
        )
        # Make clone raise an exception
        monkeypatch.setattr(
            "gearbox.agents.shared.clone_repository",
            lambda repo: (_ for _ in ()).throw(RuntimeError("clone failed")),
        )

        from gearbox.agents.backlog import run_backlog_item

        # Should not raise despite clone failure
        result = asyncio.run(run_backlog_item("owner/repo", 1))
        assert isinstance(result, BacklogItemResult)
        assert result.labels == ["question"]


# ---------------------------------------------------------------------------
# _gh_issue_view subprocess interaction
# ---------------------------------------------------------------------------


class TestGhIssueViewForBacklog:
    def test_gh_issue_view_calls_correct_jq(self, monkeypatch) -> None:
        captured_cmd: list[str] = []

        class FakeCompletedProcess:
            stdout = json.dumps(
                {
                    "title": "Test Issue",
                    "body": "Body text",
                    "labels": ["bug", "docs"],
                    "state": "open",
                }
            )

        def fake_run(cmd: list[str], **kwargs):
            captured_cmd.extend(cmd)
            return FakeCompletedProcess()

        monkeypatch.setattr("gearbox.agents.backlog.subprocess.run", fake_run)

        result = _gh_issue_view("owner/repo", 7)

        assert result["title"] == "Test Issue"
        assert result["labels"] == ["bug", "docs"]
        # Verify jq includes state field (backlog-specific format)
        jq_arg = captured_cmd[captured_cmd.index("--jq") + 1]
        assert "state:.state" in jq_arg
