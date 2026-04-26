"""Agent 运行时公共能力。"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    RateLimitEvent,
    ResultMessage,
    StreamEvent,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
    TextBlock,
)

from gearbox.config import get_anthropic_api_key, get_anthropic_base_url

_HEARTBEAT_INTERVAL_SECONDS = 20.0
_HEARTBEAT_IDLE_THRESHOLD_SECONDS = 20.0


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%H:%M:%S")


def _print_line(text: str) -> None:
    print(text, flush=True)


def _log(agent: str, stage: str, message: str) -> None:
    _print_line(f"[{_timestamp()}] [{agent}] [{stage}] {message}")


def _format_usage(usage: dict[str, int] | None) -> str:
    if not usage:
        return ""

    parts: list[str] = []
    if usage.get("total_tokens") is not None:
        parts.append(f"tokens={usage['total_tokens']}")
    if usage.get("tool_uses") is not None:
        parts.append(f"tool_uses={usage['tool_uses']}")
    if usage.get("duration_ms") is not None:
        parts.append(f"duration_ms={usage['duration_ms']}")
    return ", ".join(parts)


def _format_mapping(data: dict[str, object] | None) -> str:
    if not data:
        return ""
    return ", ".join(f"{key}={value}" for key, value in data.items())


def _truncate(text: str, limit: int = 160) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _format_tool_input(tool_name: str, tool_input: dict[str, Any] | None) -> str:
    if not tool_input:
        return ""

    if tool_name == "Read":
        path = tool_input.get("file_path") or tool_input.get("path")
        offset = tool_input.get("offset")
        limit = tool_input.get("limit")
        details = []
        if path:
            details.append(f"path={path}")
        if offset is not None:
            details.append(f"offset={offset}")
        if limit is not None:
            details.append(f"limit={limit}")
        return ", ".join(details)

    if tool_name == "Glob":
        pattern = tool_input.get("pattern")
        path = tool_input.get("path")
        details = []
        if pattern:
            details.append(f"pattern={pattern}")
        if path:
            details.append(f"path={path}")
        return ", ".join(details)

    if tool_name == "Grep":
        pattern = tool_input.get("pattern")
        path = tool_input.get("path")
        details = []
        if pattern:
            details.append(f"pattern={_truncate(str(pattern), 120)}")
        if path:
            details.append(f"path={path}")
        return ", ".join(details)

    if tool_name == "Bash":
        command = tool_input.get("command")
        if command:
            return f"command={_truncate(str(command), 140)}"
        return ""

    preferred_keys = ["file_path", "path", "pattern", "command", "query", "url"]
    details = []
    for key in preferred_keys:
        value = tool_input.get(key)
        if value:
            details.append(f"{key}={_truncate(str(value), 120)}")
    if details:
        return ", ".join(details)

    return _truncate(_format_mapping(tool_input), 160)


def _safe_get(mapping: Any, *path: str) -> Any | None:
    current = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


class SdkEventLogger:
    """把 SDK 原生事件转成适合终端和 GitHub Actions 的日志。"""

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self._open_task_ids: set[str] = set()
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._started_at = time.monotonic()
        self._last_activity_at = self._started_at
        self._last_activity_label = "startup"
        self._stream_text_buffer = ""
        self._thinking_buffer = ""
        self._current_block_type: str | None = None
        self._lock = threading.Lock()

    def _mark_activity(self, label: str) -> None:
        with self._lock:
            self._last_activity_at = time.monotonic()
            self._last_activity_label = label

    def _log(self, stage: str, message: str) -> None:
        self._mark_activity(stage)
        _log(self.agent_name, stage, message)

    def _start_heartbeat(self) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        self._heartbeat_stop.clear()

        def _run() -> None:
            while not self._heartbeat_stop.wait(_HEARTBEAT_INTERVAL_SECONDS):
                with self._lock:
                    now = time.monotonic()
                    idle_for = now - self._last_activity_at
                    elapsed = now - self._started_at
                    label = self._last_activity_label
                if idle_for >= _HEARTBEAT_IDLE_THRESHOLD_SECONDS:
                    _log(
                        self.agent_name,
                        "heartbeat",
                        f"still running, elapsed={int(elapsed)}s, idle={int(idle_for)}s, last_activity={label}",
                    )

        self._heartbeat_thread = threading.Thread(
            target=_run,
            name=f"{self.agent_name}-sdk-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=1.0)
        self._heartbeat_thread = None

    def _flush_stream_text(self) -> None:
        text = self._stream_text_buffer.strip()
        if text:
            self._log("assistant-partial", text[:400])
        self._stream_text_buffer = ""

    def _flush_thinking(self) -> None:
        text = " ".join(self._thinking_buffer.split()).strip()
        if text:
            self._log("thinking", text[:240])
        self._thinking_buffer = ""

    def stderr_callback(self, line: str) -> None:
        self._log("claude-stderr", line)

    def log_start(
        self,
        *,
        model: str | None,
        max_turns: int | None,
        base_url: str | None,
        cwd: str,
    ) -> None:
        self._log(
            "start",
            f"model={model or '(default)'}, max_turns={max_turns}, "
            f"base_url={base_url or '(default)'}, cwd={cwd}",
        )
        self._start_heartbeat()

    def log_completion(self) -> None:
        self._flush_stream_text()
        self.close_open_groups()
        self._stop_heartbeat()
        self._log("done", "agent execution finished")

    def close_open_groups(self) -> None:
        while self._open_task_ids:
            self._open_task_ids.pop()
            _print_line("::endgroup::")

    def _handle_stream_event(self, message: StreamEvent) -> None:
        event = message.event
        event_type = event.get("type", "unknown")

        if event_type == "content_block_delta":
            text = _safe_get(event, "delta", "text")
            if isinstance(text, str) and text:
                self._stream_text_buffer += text
                if "\n" in text or len(self._stream_text_buffer) >= 160:
                    self._flush_stream_text()
                else:
                    self._mark_activity("assistant-partial")
                return

            thinking = _safe_get(event, "delta", "thinking")
            if isinstance(thinking, str) and thinking.strip():
                self._thinking_buffer += thinking
                self._mark_activity("thinking")
                return

        if event_type == "message_delta":
            stop_reason = _safe_get(event, "delta", "stop_reason")
            usage = event.get("usage")
            details = []
            if stop_reason:
                details.append(f"stop_reason={stop_reason}")
            if isinstance(usage, dict):
                usage_text = _format_mapping(usage)
                if usage_text:
                    details.append(f"usage[{usage_text}]")
            self._log("stream-message-delta", ", ".join(details) or "message delta")
            return

        if event_type == "content_block_start":
            block_type = _safe_get(event, "content_block", "type")
            self._current_block_type = str(block_type or "unknown")
            if self._current_block_type == "thinking":
                self._log("thinking-start", "thinking started")
                return
            if self._current_block_type == "text":
                self._log("assistant-start", "assistant text started")
                return
            if self._current_block_type == "tool_use":
                tool_name = _safe_get(event, "content_block", "name")
                tool_input = _safe_get(event, "content_block", "input")
                details = _format_tool_input(
                    str(tool_name or "unknown"),
                    tool_input if isinstance(tool_input, dict) else None,
                )
                if details:
                    self._log("tool-use", f"tool={tool_name or 'unknown'}, {details}")
                else:
                    self._log("tool-use", f"tool={tool_name or 'unknown'}")
                return
            self._log("stream-content-start", f"block_type={self._current_block_type}")
            return

        if event_type == "content_block_stop":
            if self._current_block_type == "thinking":
                self._flush_thinking()
            elif self._current_block_type == "text":
                self._flush_stream_text()
            self._current_block_type = None
            return

        if event_type == "message_start":
            model = _safe_get(event, "message", "model")
            self._log("stream-message-start", f"model={model or 'unknown'}")
            return

        if event_type == "message_stop":
            self._flush_thinking()
            self._flush_stream_text()
            self._log("stream-message-stop", "message completed")
            return

    def handle_message(self, message: object, *, echo_assistant_text: bool = False) -> None:
        if isinstance(message, TaskStartedMessage):
            _print_line(f"::group::[{self.agent_name}] {message.description}")
            self._open_task_ids.add(message.task_id)
            self._log(
                "task-started",
                f"id={message.task_id}, type={message.task_type or 'unknown'}, session={message.session_id}",
            )
            return

        if isinstance(message, TaskProgressMessage):
            usage = _format_usage(message.usage)
            suffix = f", last_tool={message.last_tool_name}" if message.last_tool_name else ""
            self._log(
                "task-progress",
                f"{message.description}{' | ' + usage if usage else ''}{suffix}",
            )
            return

        if isinstance(message, TaskNotificationMessage):
            usage = _format_usage(message.usage)
            self._log(
                f"task-{message.status}",
                f"{message.summary} | output_file={message.output_file}"
                f"{' | ' + usage if usage else ''}",
            )
            if message.task_id in self._open_task_ids:
                self._open_task_ids.remove(message.task_id)
                _print_line("::endgroup::")
            return

        if isinstance(message, ResultMessage):
            self._flush_stream_text()
            fields = [
                f"turns={message.num_turns}",
                f"duration_ms={message.duration_ms}",
                f"api_ms={message.duration_api_ms}",
            ]
            if message.total_cost_usd is not None:
                fields.append(f"cost_usd={message.total_cost_usd:.4f}")
            if getattr(message, "stop_reason", None):
                fields.append(f"stop_reason={message.stop_reason}")
            if message.is_error:
                fields.append("is_error=true")
            errors = getattr(message, "errors", None)
            if errors:
                fields.append(f"errors={'; '.join(errors)}")
            usage = _format_mapping(message.usage if isinstance(message.usage, dict) else None)
            if usage:
                fields.append(f"usage[{usage}]")
            model_usage = _format_mapping(
                getattr(message, "model_usage", None)
                if isinstance(getattr(message, "model_usage", None), dict)
                else None
            )
            if model_usage:
                fields.append(f"model_usage[{model_usage}]")
            self._log("result", ", ".join(fields))
            return

        if isinstance(message, RateLimitEvent):
            self._log(
                "rate-limit",
                f"status={message.rate_limit_info.status}, "
                f"type={message.rate_limit_info.rate_limit_type}, "
                f"resets_at={message.rate_limit_info.resets_at}",
            )
            return

        if isinstance(message, StreamEvent):
            self._handle_stream_event(message)
            return

        if echo_assistant_text and isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    self._log("assistant", block.text.strip())


def prepare_agent_options(
    options: ClaudeAgentOptions,
    *,
    agent_name: str,
) -> tuple[ClaudeAgentOptions, SdkEventLogger]:
    """为 SDK 选项注入统一环境变量、partial messages 和 stderr 日志回调。"""
    logger = SdkEventLogger(agent_name)
    env = dict(options.env)

    api_key = get_anthropic_api_key()
    base_url = get_anthropic_base_url()
    if api_key:
        env.setdefault("ANTHROPIC_AUTH_TOKEN", api_key)
    if base_url:
        env.setdefault("ANTHROPIC_BASE_URL", base_url)

    return (
        replace(
            options,
            env=env,
            stderr=logger.stderr_callback,
            include_partial_messages=True,
        ),
        logger,
    )
