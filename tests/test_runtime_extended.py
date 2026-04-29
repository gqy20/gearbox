"""Extended tests for SdkEventLogger — heartbeat, result/rate-limit, thinking, and lifecycle."""

from claude_agent_sdk import (
    AssistantMessage,
    RateLimitEvent,
    ResultMessage,
    StreamEvent,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
    TextBlock,
)

from gearbox.agents.shared.runtime import (
    SdkEventLogger,
    _format_tool_input,
    _format_usage,
    _truncate,
)

# ---------------------------------------------------------------------------
# Helper format functions
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_text_unchanged(self) -> None:
        assert _truncate("hello", 10) == "hello"

    def test_exact_limit_unchanged(self) -> None:
        assert _truncate("a" * 100, 100) == "a" * 100

    def test_long_text_truncated_with_ellipsis(self) -> None:
        result = _truncate("a" * 200, 10)
        assert result.endswith("...")
        assert len(result) <= 13  # limit - 3 + "..."

    def test_empty_string(self) -> None:
        assert _truncate("", 10) == ""


class TestFormatUsage:
    def test_none_returns_empty(self) -> None:
        assert _format_usage(None) == ""

    def test_dict_with_total_tokens(self) -> None:
        assert "tokens=42" in _format_usage({"total_tokens": 42})

    def test_dict_with_tool_uses(self) -> None:
        assert "tool_uses=5" in _format_usage({"tool_uses": 5})

    def test_dict_with_duration_ms(self) -> None:
        assert "duration_ms=1000" in _format_usage({"duration_ms": 1000})

    def test_dict_combined(self) -> None:
        result = _format_usage({"total_tokens": 100, "tool_uses": 3, "duration_ms": 500})
        assert "tokens=100" in result
        assert "tool_uses=3" in result
        assert "duration_ms=500" in result

    def test_empty_dict_returns_empty(self) -> None:
        assert _format_usage({}) == ""


class TestFormatToolInput:
    def test_read_with_path_and_range(self) -> None:
        result = _format_tool_input("Read", {"file_path": "src/main.py", "offset": 10, "limit": 50})
        assert "path=src/main.py" in result
        assert "offset=10" in result
        assert "limit=50" in result

    def test_glob_with_pattern_and_path(self) -> None:
        result = _format_tool_input("Glob", {"pattern": "**/*.py", "path": "src"})
        assert "pattern=**/*.py" in result
        assert "path=src" in result

    def test_grep_with_pattern(self) -> None:
        result = _format_tool_input("Grep", {"pattern": "def test_", "path": "tests"})
        assert "pattern=def test_" in result
        assert "path=tests" in result

    def test_bash_with_command(self) -> None:
        cmd = "uv run pytest tests/test_audit.py -q"
        result = _format_tool_input("Bash", {"command": cmd})
        assert f"command={cmd}" in result

    def test_bash_truncates_long_commands(self) -> None:
        long_cmd = "x" * 200
        result = _format_tool_input("Bash", {"command": long_cmd})
        assert len(result) <= 163  # "command=" (8) + truncated (157 max) + possible ...
        assert "..." in result or len(long_cmd) <= 140

    def test_none_input_returns_empty(self) -> None:
        assert _format_tool_input("Read", None) == ""

    def test_empty_input_returns_empty(self) -> None:
        assert _format_tool_input("Read", {}) == ""

    def test_unknown_tool_uses_preferred_keys(self) -> None:
        result = _format_tool_input("CustomTool", {"file_path": "f.txt", "query": "search"})
        assert "file_path=f.txt" in result
        assert "query=search" in result

    def test_unknown_tool_falls_back_to_mapping(self) -> None:
        result = _format_tool_input("WeirdTool", {"custom_key": "val"})
        assert "custom_key=val" in result


# ---------------------------------------------------------------------------
# Heartbeat lifecycle
# ---------------------------------------------------------------------------


class TestHeartbeat:
    def test_log_start_starts_heartbeat_thread(self) -> None:
        logger = SdkEventLogger("test-agent")
        logger.log_start(model="m", max_turns=5, base_url=None, cwd="/tmp")
        assert logger._heartbeat_thread is not None
        assert logger._heartbeat_thread.is_alive()
        logger.log_completion()  # cleanup

    def test_log_completion_stops_heartbeat(self) -> None:
        logger = SdkEventLogger("test-agent")
        logger.log_start(model="m", max_turns=5, base_url=None, cwd="/tmp")
        logger.log_completion()
        # Thread should be stopped or None
        assert logger._heartbeat_thread is None

    def test_double_log_completion_is_safe(self) -> None:
        """Calling log_completion twice should not crash."""
        logger = SdkEventLogger("test-agent")
        logger.log_start(model="m", max_turns=5, base_url=None, cwd="/tmp")
        logger.log_completion()
        logger.log_completion()  # should not raise


# ---------------------------------------------------------------------------
# Result message handling
# ---------------------------------------------------------------------------


class TestResultMessageHandling:
    def test_result_message_logs_all_fields(self, monkeypatch) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("audit")
        msg = ResultMessage(
            subtype="result",
            duration_ms=1234,
            duration_api_ms=1000,
            is_error=False,
            num_turns=7,
            session_id="s1",
            structured_output={"key": "val"},
            total_cost_usd=0.005,
            stop_reason="end_turn",
        )
        logger.handle_message(msg)

        assert any(stage == "result" for _, stage, _ in entries)
        result_entry = [e for e in entries if e[1] == "result"][0]
        assert "turns=7" in result_entry[2]
        assert "duration_ms=1234" in result_entry[2]
        assert "cost_usd=0.0050" in result_entry[2]
        assert "stop_reason=end_turn" in result_entry[2]

    def test_result_message_with_error_flag(self, monkeypatch) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("audit")
        msg = ResultMessage(
            subtype="result",
            duration_ms=100,
            duration_api_ms=80,
            is_error=True,
            num_turns=1,
            session_id="s1",
            structured_output={"error": "fail"},
        )
        logger.handle_message(msg)

        result_entry = [e for e in entries if e[1] == "result"][0]
        assert "is_error=true" in result_entry[2]


# ---------------------------------------------------------------------------
# Rate limit event handling
# ---------------------------------------------------------------------------


class TestRateLimitEventHandling:
    def test_rate_limit_event_logged(self, monkeypatch) -> None:
        from claude_agent_sdk.types import RateLimitInfo

        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("audit")
        rate_info = RateLimitInfo(
            status="rejected",
            rate_limit_type="seven_day_sonnet",
            resets_at=1746000000,
        )
        msg = RateLimitEvent(rate_limit_info=rate_info, uuid="u1", session_id="s1")
        logger.handle_message(msg)

        assert any(stage == "rate-limit" for _, stage, _ in entries)
        rate_entry = [e for e in entries if e[1] == "rate-limit"][0]
        assert "status=rejected" in rate_entry[2]
        assert "type=seven_day_sonnet" in rate_entry[2]


# ---------------------------------------------------------------------------
# Thinking block handling
# ---------------------------------------------------------------------------


class TestThinkingBlockHandling:
    def test_thinking_content_accumulated_and_flushed_on_stop(self, monkeypatch) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("audit")

        # Start thinking block
        logger.handle_message(
            StreamEvent(
                uuid="u0",
                session_id="s1",
                event={
                    "type": "content_block_start",
                    "content_block": {"type": "thinking"},
                },
            )
        )

        # Send thinking delta
        logger.handle_message(
            StreamEvent(
                uuid="u1",
                session_id="s1",
                event={
                    "type": "content_block_delta",
                    "delta": {"thinking": "Let me think about this..."},
                },
            )
        )

        # More thinking
        logger.handle_message(
            StreamEvent(
                uuid="u2",
                session_id="s1",
                event={
                    "type": "content_block_delta",
                    "delta": {"thinking": " The answer is clear."},
                },
            )
        )

        # Stop thinking block → flush
        logger.handle_message(
            StreamEvent(
                uuid="u3",
                session_id="s1",
                event={"type": "content_block_stop"},
            )
        )

        thinking_entries = [e for e in entries if e[1] == "thinking"]
        assert len(thinking_entries) >= 1
        # Flush should contain combined thinking text
        flushed_text = thinking_entries[-1][2]
        assert "Let me think about this" in flushed_text
        assert "The answer is clear" in flushed_text

    def test_thinking_start_event_logged(self, monkeypatch) -> None:
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
                    "content_block": {"type": "thinking"},
                },
            )
        )

        assert any(e[1] == "thinking-start" for e in entries)


# ---------------------------------------------------------------------------
# Task lifecycle messages
# ---------------------------------------------------------------------------


class TestTaskMessages:
    def test_task_started_opens_group(self, monkeypatch) -> None:
        printed: list[str] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._print_line",
            lambda text: printed.append(text),
        )
        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: None,
        )

        logger = SdkEventLogger("audit")
        msg = TaskStartedMessage(
            subtype="task_start",
            data={},
            task_id="t1",
            description="Cloning repository",
            uuid="u1",
            session_id="s1",
            task_type="subagent",
        )
        logger.handle_message(msg)

        assert any("::group::" in line for line in printed)
        assert logger._open_task_ids == {"t1"}

    def test_task_notification_closes_group(self, monkeypatch) -> None:
        printed: list[str] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._print_line",
            lambda text: printed.append(text),
        )
        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: None,
        )

        logger = SdkEventLogger("audit")

        # First open a task group
        start_msg = TaskStartedMessage(
            subtype="task_start",
            data={},
            task_id="t1",
            description="Test task",
            uuid="u1",
            session_id="s1",
            task_type="subagent",
        )
        logger.handle_message(start_msg)

        # Then send notification for same task
        notif_msg = TaskNotificationMessage(
            subtype="task_done",
            data={},
            task_id="t1",
            status="completed",
            output_file="/tmp/out.json",
            summary="Done",
            uuid="u2",
            session_id="s1",
        )
        logger.handle_message(notif_msg)

        assert "::endgroup::" in printed
        assert "t1" not in logger._open_task_ids

    def test_task_progress_logged(self, monkeypatch) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("audit")
        from claude_agent_sdk.types import TaskUsage

        msg = TaskProgressMessage(
            subtype="progress",
            data={},
            task_id="t1",
            description="Reading files",
            usage=TaskUsage(tool_uses=3),
            uuid="u1",
            session_id="s1",
            last_tool_name="Read",
        )
        logger.handle_message(msg)

        progress_entries = [e for e in entries if e[1] == "task-progress"]
        assert len(progress_entries) == 1
        assert "Reading files" in progress_entries[0][2]
        assert "last_tool=Read" in progress_entries[0][2]


# ---------------------------------------------------------------------------
# Stream event edge cases
# ---------------------------------------------------------------------------


class TestStreamEventEdgeCases:
    def test_unknown_content_block_type(self, monkeypatch) -> None:
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
                    "content_block": {"type": "unknown_type"},
                },
            )
        )

        assert any("block_type=unknown_type" in e[2] for e in entries)

    def test_message_delta_with_stop_reason_and_usage(self, monkeypatch) -> None:
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
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"total_tokens": 1500},
                },
            )
        )

        delta_entries = [e for e in entries if e[1] == "stream-message-delta"]
        assert len(delta_entries) == 1
        assert "stop_reason=end_turn" in delta_entries[0][2]
        assert "usage[" in delta_entries[0][2]

    def test_message_start_logs_model(self, monkeypatch) -> None:
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
                    "type": "message_start",
                    "message": {"model": "claude-sonnet-4-6"},
                },
            )
        )

        start_entries = [e for e in entries if e[1] == "stream-message-start"]
        assert len(start_entries) == 1
        assert "model=claude-sonnet-4-6" in start_entries[0][2]

    def test_message_stop_flushes_buffers(self, monkeypatch) -> None:
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
                event={"type": "message_stop"},
            )
        )

        assert any(e[1] == "stream-message-stop" for e in entries)

    def test_text_buffer_flushes_on_newline(self, monkeypatch) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("audit")

        # Start text block
        logger.handle_message(
            StreamEvent(
                uuid="u0",
                session_id="s1",
                event={"type": "content_block_start", "content_block": {"type": "text"}},
            )
        )

        # Send text with newline → triggers flush
        logger.handle_message(
            StreamEvent(
                uuid="u1",
                session_id="s1",
                event={"type": "content_block_delta", "delta": {"text": "Line one\n"}},
            )
        )

        partial_entries = [e for e in entries if e[1] == "assistant-partial"]
        assert len(partial_entries) >= 1
        assert "Line one" in partial_entries[0][2]

    def test_assistant_text_echoed_when_enabled(self, monkeypatch) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("audit")
        msg = AssistantMessage(
            model="test-model",
            content=[TextBlock(text="Hello from assistant")],
        )
        logger.handle_message(msg, echo_assistant_text=True)

        assistant_entries = [e for e in entries if e[1] == "assistant"]
        assert len(assistant_entries) == 1
        assert "Hello from assistant" in assistant_entries[0][2]

    def test_assistant_text_not_echoed_when_disabled(self, monkeypatch) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("audit")
        msg = AssistantMessage(
            model="test-model",
            content=[TextBlock(text="Should not appear")],
        )
        logger.handle_message(msg, echo_assistant_text=False)

        assistant_entries = [e for e in entries if e[1] == "assistant"]
        assert len(assistant_entries) == 0


# ---------------------------------------------------------------------------
# close_open_groups
# ---------------------------------------------------------------------------


class TestCloseOpenGroups:
    def test_closes_multiple_groups(self, monkeypatch) -> None:
        printed: list[str] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._print_line",
            lambda text: printed.append(text),
        )

        logger = SdkEventLogger("audit")
        logger._open_task_ids = {"t1", "t2", "t3"}
        logger.close_open_groups()

        assert printed.count("::endgroup::") == 3
        assert len(logger._open_task_ids) == 0

    def test_no_groups_is_safe(self, monkeypatch) -> None:
        printed: list[str] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._print_line",
            lambda text: printed.append(text),
        )

        logger = SdkEventLogger("audit")
        logger.close_open_groups()

        assert printed == []


# ---------------------------------------------------------------------------
# stderr_callback
# ---------------------------------------------------------------------------


class TestStderrCallback:
    def test_stderr_callback_logs_line(self, monkeypatch) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("audit")
        logger.stderr_callback("error: something went wrong")

        assert any(e[1] == "claude-stderr" and "something went wrong" in e[2] for e in entries)


# ---------------------------------------------------------------------------
# log_start / log_completion output
# ---------------------------------------------------------------------------


class TestLogStartOutput:
    def test_log_start_includes_config(self, monkeypatch) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("my-agent")
        logger.log_start(
            model="claude-sonnet-4-6",
            max_turns=25,
            base_url="https://proxy.example.com",
            cwd="/workspace/project",
        )

        start_entries = [e for e in entries if e[1] == "start"]
        assert len(start_entries) == 1
        msg = start_entries[0][2]
        assert "model=claude-sonnet-4-6" in msg
        assert "max_turns=25" in msg
        assert "base_url=https://proxy.example.com" in msg
        assert "cwd=/workspace/project" in msg

    def test_log_start_defaults_for_none_values(self, monkeypatch) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )

        logger = SdkEventLogger("agent")
        logger.log_start(model=None, max_turns=None, base_url=None, cwd="(default)")

        start_entries = [e for e in entries if e[1] == "start"]
        msg = start_entries[0][2]
        assert "(default)" in msg  # model defaults to (default)

    def test_log_completion_emits_done(self, monkeypatch) -> None:
        entries: list[tuple[str, str, str]] = []

        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._log",
            lambda agent, stage, message: entries.append((agent, stage, message)),
        )
        monkeypatch.setattr(
            "gearbox.agents.shared.runtime._print_line",
            lambda text: None,
        )

        logger = SdkEventLogger("agent")
        logger.log_completion()

        done_entries = [e for e in entries if e[1] == "done"]
        assert len(done_entries) == 1
        assert "finished" in done_entries[0][2]
