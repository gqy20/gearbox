"""测试 Claude Agent SDK 日志适配。"""

import os

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
