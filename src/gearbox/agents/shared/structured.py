"""Agent 结构化输出公共能力。"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock

T = TypeVar("T")


def json_schema_output(schema: dict[str, Any]) -> dict[str, Any]:
    """构造 Claude Agent SDK 需要的 json_schema output_format。"""
    return {"type": "json_schema", "schema": schema}


def parse_structured_output(
    message: object,
    parser: Callable[[dict[str, Any]], T],
) -> T | None:
    """从 SDK 结构化输出消息中解析结果。"""
    if isinstance(message, ResultMessage) and isinstance(message.structured_output, dict):
        return parser(message.structured_output)

    if isinstance(message, AssistantMessage):
        for block in message.content:
            if (
                isinstance(block, ToolUseBlock)
                and block.name == "StructuredOutput"
                and isinstance(block.input, dict)
            ):
                return parser(block.input)

    return None
