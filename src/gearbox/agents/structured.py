"""Agent 结构化输出公共能力。"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

T = TypeVar("T")


def json_schema_output(schema: dict[str, Any]) -> dict[str, Any]:
    """构造 Claude Agent SDK 需要的 json_schema output_format。"""
    return {"type": "json_schema", "schema": schema}


def append_assistant_text(buffer: str, message: object) -> str:
    """把 AssistantMessage 文本块追加到现有缓冲区。"""
    if not isinstance(message, AssistantMessage):
        return buffer
    parts = [block.text for block in message.content if isinstance(block, TextBlock)]
    if not parts:
        return buffer
    return buffer + "".join(parts)


def parse_structured_output(
    message: object,
    parser: Callable[[dict[str, Any]], T],
) -> T | None:
    """从 ResultMessage.structured_output 中解析结构化结果。"""
    if not isinstance(message, ResultMessage):
        return None
    if not isinstance(message.structured_output, dict):
        return None
    return parser(message.structured_output)
