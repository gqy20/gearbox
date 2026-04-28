"""测试 Claude Agent SDK 日志适配。"""

import logging
import os

import pytest
from claude_agent_sdk import ClaudeAgentOptions, StreamEvent

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

    def test_warns_on_non_claude_model(self, caplog: pytest.LogCaptureFixture) -> None:
        """非 claude-* 前缀的模型应发出 warning 日志"""
        with caplog.at_level(logging.WARNING):
            prepare_agent_options(
                ClaudeAgentOptions(model="glm-5-turbo"),
                agent_name="audit",
            )
        warnings_found = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and "claude" in r.message.lower()
        ]
        assert len(warnings_found) > 0, (
            "Expected a warning when using a non-Claude model with claude-agent-sdk"
        )

    def test_no_warning_for_claude_model(self, caplog: pytest.LogCaptureFixture) -> None:
        """claude-* 前缀的模型不应发出 warning"""
        with caplog.at_level(logging.WARNING):
            prepare_agent_options(
                ClaudeAgentOptions(model="claude-sonnet-4-6"),
                agent_name="audit",
            )
        warnings_found = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings_found) == 0, (
            f"Unexpected warnings for Claude model: {[r.message for r in warnings_found]}"
        )


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
