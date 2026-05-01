"""Agent 结构化输出公共能力。"""

from __future__ import annotations

import logging
import warnings
from typing import Any, Callable, TypeVar

from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock

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

    .. deprecated::
        此函数已迁移至 :mod:`gearbox.agents.schemas`。
        该实现现在委托给 :func:`gearbox.agents.schemas.parse_with_model`，
        是唯一的 canonical 实现。
    """
    warnings.warn(
        "parse_with_model is deprecated: use gearbox.agents.schemas.parse_with_model instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from gearbox.agents.schemas import parse_with_model as _canonical

    return _canonical(message, model_class)  # type: ignore[type-var]


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
