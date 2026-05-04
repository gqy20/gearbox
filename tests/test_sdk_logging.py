"""测试 Claude Agent SDK 日志适配。"""

import os
from unittest.mock import patch

from claude_agent_sdk import (
    ClaudeAgentOptions,
    StreamEvent,
    TaskNotificationMessage,
    TaskStartedMessage,
)

from gearbox.agents.shared.runtime import SdkEventLogger, prepare_agent_options


class TestPrepareSdkOptions:
    def test_preserves_existing_env(self) -> None:
        prepared, _ = prepare_agent_options(
            ClaudeAgentOptions(env={"KEEP_ME": "1"}),
            agent_name="audit",
        )
        assert prepared.env["KEEP_ME"] == "1"

    def test_injects_auth_token_and_base_url_from_env(self) -> None:
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "sk-test-auth"
        os.environ["ANTHROPIC_BASE_URL"] = "https://proxy.example.com/anthropic"
        try:
            prepared, _ = prepare_agent_options(ClaudeAgentOptions(), agent_name="audit")
            assert prepared.env["ANTHROPIC_AUTH_TOKEN"] == "sk-test-auth"
            assert prepared.env["ANTHROPIC_BASE_URL"] == "https://proxy.example.com/anthropic"
            assert prepared.stderr is not None
            assert prepared.include_partial_messages is True
        finally:
            del os.environ["ANTHROPIC_AUTH_TOKEN"]
            del os.environ["ANTHROPIC_BASE_URL"]


class TestSdkEventLogger:
    def test_stream_event_partial_text_is_humanized(
        self,
        monkeypatch,
    ) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("audit")
        logger.handle_message(
            StreamEvent(
                uuid="u0",
                session_id="s1",
                event={
                    "type": "content_block_start",
                    "content_block": {"type": "text"},
                },
            )
        )
        logger.handle_message(
            StreamEvent(
                uuid="u1",
                session_id="s1",
                event={
                    "type": "content_block_delta",
                    "delta": {"text": "Inspecting repository..."},
                },
            )
        )
        logger.handle_message(
            StreamEvent(
                uuid="u2",
                session_id="s1",
                event={"type": "content_block_stop"},
            )
        )

        assert any(stage == "assistant-partial" for _, stage, _ in entries)
        assert any("Inspecting repository" in message for _, _, message in entries)

    def test_tool_use_logs_read_path_and_range(
        self,
        monkeypatch,
    ) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("audit")
        logger.handle_message(
            StreamEvent(
                uuid="u0",
                session_id="s1",
                event={
                    "type": "content_block_start",
                    "content_block": {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {
                            "file_path": "tests/test_cli.py",
                            "offset": 10,
                            "limit": 50,
                        },
                    },
                },
            )
        )

        assert (
            "audit",
            "tool-use",
            "tool=Read, path=tests/test_cli.py, offset=10, limit=50",
        ) in entries

    def test_tool_use_logs_bash_command_summary(
        self,
        monkeypatch,
    ) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("audit")
        logger.handle_message(
            StreamEvent(
                uuid="u0",
                session_id="s1",
                event={
                    "type": "content_block_start",
                    "content_block": {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {
                            "command": 'rg -n "workflow_call" .github/workflows',
                        },
                    },
                },
            )
        )

        assert any(
            stage == "tool-use" and "tool=Bash, command=rg -n" in message
            for _, stage, message in entries
        )

    def test_close_open_groups_uses_lifo_order(self) -> None:
        """Groups must close in LIFO order so ::endgroup:: matches ::group:: nesting."""
        logger = SdkEventLogger("audit")

        def _make_started(task_id: str, desc: str) -> TaskStartedMessage:
            return TaskStartedMessage(
                subtype="start",
                data={},
                task_id=task_id,
                description=desc,
                uuid=f"uuid-{task_id}",
                session_id="s1",
                task_type="agent",
            )

        started_a = _make_started("task-a", "Task A")
        started_b = _make_started("task-b", "Task B")
        started_c = _make_started("task-c", "Task C")

        # Verify _open_task_ids is an ordered sequence (list), not a set
        assert isinstance(logger._open_task_ids, list)

        logger.handle_message(started_a)
        logger.handle_message(started_b)
        logger.handle_message(started_c)

        # Internal tracking must preserve insertion order
        assert logger._open_task_ids == ["task-a", "task-b", "task-c"]

        with patch("gearbox.agents.shared.runtime._print_line") as mock_print:
            # Close all groups — should emit ::endgroup:: in reverse (LIFO) order
            logger.close_open_groups()

        endgroup_calls = [
            call[0][0] for call in mock_print.call_args_list if call[0][0] == "::endgroup::"
        ]
        assert len(endgroup_calls) == 3
        # After closing all, list must be empty
        assert logger._open_task_ids == []

    def test_task_notification_removes_correct_task(self) -> None:
        """TaskNotification should remove its own task_id and emit one ::endgroup::."""
        logger = SdkEventLogger("audit")

        started_a = TaskStartedMessage(
            subtype="start",
            data={},
            task_id="task-a",
            description="Task A",
            uuid="uuid-a",
            session_id="s1",
            task_type="agent",
        )
        started_b = TaskStartedMessage(
            subtype="start",
            data={},
            task_id="task-b",
            description="Task B",
            uuid="uuid-b",
            session_id="s1",
            task_type="agent",
        )

        with patch("gearbox.agents.shared.runtime._print_line") as mock_print:
            logger.handle_message(started_a)
            logger.handle_message(started_b)

            # Notify completion of task-b (the later-opened group)
            notification = TaskNotificationMessage(
                subtype="notification",
                data={},
                task_id="task-b",
                status="completed",
                output_file="/tmp/out",
                summary="done",
                uuid="uuid-b-done",
                session_id="s1",
                usage=None,
            )
            logger.handle_message(notification)

            # Only one endgroup should have been emitted for task-b
            endgroup_calls = [
                call[0][0]
                for call in mock_print.call_args_list
                if call[0][0] == "::endgroup::"
            ]
            assert len(endgroup_calls) == 1

            # task-a should still be open; closing it now emits exactly one more
            logger.close_open_groups()
            endgroup_calls = [
                call[0][0]
                for call in mock_print.call_args_list
                if call[0][0] == "::endgroup::"
            ]
            assert len(endgroup_calls) == 2
