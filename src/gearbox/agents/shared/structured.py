"""Agent 结构化输出公共能力。"""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar, cast

from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock
from pydantic import ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T")


def json_schema_output(schema: dict[str, Any]) -> dict[str, Any]:
    """构造 Claude Agent SDK 需要的 json_schema output_format。"""
    return {"type": "json_schema", "schema": schema}


def parse_structured_output(
    message: object,
    parser: Callable[[dict[str, Any]], T],
) -> T | None:
    """从 SDK 结构化输出消息中解析结果。"""
    raw = _extract_raw_dict(message)
    if raw is None:
        return None
    return parser(raw)


def parse_with_model(message: object, model_class: type[T]) -> T | None:
    """提取 structured output 并通过 Pydantic model_validate 校验。

    比手写 lambda 更安全：类型错误会抛出精确的 ValidationError，
    而不是模糊的 ValueError 或 KeyError。
    """
    raw = _extract_raw_dict(message)
    if raw is None:
        return None
    try:
        return cast(T, model_class.model_validate(raw))  # type: ignore[attr-defined]
    except ValidationError as e:
        logger.warning(
            "Structured output validation failed for %s: %s",
            model_class.__name__,
            e,
        )
        raise


def _extract_raw_dict(message: object) -> dict[str, Any] | None:
    if isinstance(message, ResultMessage) and isinstance(message.structured_output, dict):
        return message.structured_output

    if isinstance(message, AssistantMessage):
        for block in message.content:
            if (
                isinstance(block, ToolUseBlock)
                and block.name == "StructuredOutput"
                and isinstance(block.input, dict)
            ):
                return block.input

    return None
