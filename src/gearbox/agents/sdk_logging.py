"""Claude Agent SDK 原生日志集成。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

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


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%H:%M:%S")


def _log(agent: str, stage: str, message: str) -> None:
    print(f"[{_timestamp()}] [{agent}] [{stage}] {message}")


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


class SdkEventLogger:
    """把 SDK 原生事件转成适合终端和 GitHub Actions 的日志。"""

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self._open_task_ids: set[str] = set()

    def stderr_callback(self, line: str) -> None:
        _log(self.agent_name, "claude-stderr", line)

    def log_start(
        self,
        *,
        model: str | None,
        max_turns: int | None,
        base_url: str | None,
        cwd: str,
    ) -> None:
        _log(
            self.agent_name,
            "start",
            f"model={model or '(default)'}, max_turns={max_turns}, "
            f"base_url={base_url or '(default)'}, cwd={cwd}",
        )

    def log_completion(self) -> None:
        self.close_open_groups()
        _log(self.agent_name, "done", "agent execution finished")

    def close_open_groups(self) -> None:
        while self._open_task_ids:
            self._open_task_ids.pop()
            print("::endgroup::")

    def handle_message(self, message: object, *, echo_assistant_text: bool = False) -> None:
        if isinstance(message, TaskStartedMessage):
            print(f"::group::[{self.agent_name}] {message.description}")
            self._open_task_ids.add(message.task_id)
            _log(
                self.agent_name,
                "task-started",
                f"id={message.task_id}, type={message.task_type or 'unknown'}, session={message.session_id}",
            )
            return

        if isinstance(message, TaskProgressMessage):
            usage = _format_usage(message.usage)
            suffix = f", last_tool={message.last_tool_name}" if message.last_tool_name else ""
            _log(
                self.agent_name,
                "task-progress",
                f"{message.description}{' | ' + usage if usage else ''}{suffix}",
            )
            return

        if isinstance(message, TaskNotificationMessage):
            usage = _format_usage(message.usage)
            _log(
                self.agent_name,
                f"task-{message.status}",
                f"{message.summary} | output_file={message.output_file}"
                f"{' | ' + usage if usage else ''}",
            )
            if message.task_id in self._open_task_ids:
                self._open_task_ids.remove(message.task_id)
                print("::endgroup::")
            return

        if isinstance(message, ResultMessage):
            fields = [
                f"turns={message.num_turns}",
                f"duration_ms={message.duration_ms}",
                f"api_ms={message.duration_api_ms}",
            ]
            if message.total_cost_usd is not None:
                fields.append(f"cost_usd={message.total_cost_usd:.4f}")
            if message.stop_reason:
                fields.append(f"stop_reason={message.stop_reason}")
            if message.is_error:
                fields.append("is_error=true")
            if message.errors:
                fields.append(f"errors={'; '.join(message.errors)}")
            usage = _format_mapping(message.usage if isinstance(message.usage, dict) else None)
            if usage:
                fields.append(f"usage[{usage}]")
            model_usage = _format_mapping(
                message.model_usage if isinstance(message.model_usage, dict) else None
            )
            if model_usage:
                fields.append(f"model_usage[{model_usage}]")
            _log(self.agent_name, "result", ", ".join(fields))
            return

        if isinstance(message, RateLimitEvent):
            _log(
                self.agent_name,
                "rate-limit",
                f"status={message.rate_limit_info.status}, "
                f"type={message.rate_limit_info.rate_limit_type}, "
                f"resets_at={message.rate_limit_info.resets_at}",
            )
            return

        if isinstance(message, StreamEvent):
            _log(self.agent_name, "stream-event", f"type={message.event.get('type', 'unknown')}")
            return

        if echo_assistant_text and isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    _log(self.agent_name, "assistant", block.text.strip())


def prepare_sdk_options(
    options: ClaudeAgentOptions,
    *,
    agent_name: str,
) -> tuple[ClaudeAgentOptions, SdkEventLogger]:
    """为 SDK 选项注入统一环境变量和 stderr 日志回调。"""
    logger = SdkEventLogger(agent_name)
    env = dict(options.env)

    api_key = get_anthropic_api_key()
    base_url = get_anthropic_base_url()
    if api_key:
        env.setdefault("ANTHROPIC_AUTH_TOKEN", api_key)
    if base_url:
        env.setdefault("ANTHROPIC_BASE_URL", base_url)

    return replace(options, env=env, stderr=logger.stderr_callback), logger
