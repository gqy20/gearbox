"""Agent 结构化输出公共能力。"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Callable, TypeVar, cast

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, ToolUseBlock
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


def _format_validation_error(error: ValidationError) -> str:
    """Extract human-readable error details from a Pydantic ValidationError."""
    parts: list[str] = []
    for err in error.errors():
        loc = " → ".join(str(x) for x in err["loc"])
        msg = err["msg"]
        inp = err.get("input")
        input_str = repr(inp) if inp is not None else ""
        parts.append(f"  - 字段 [{loc}]: {msg} (输入值: {input_str})")
    return "\n".join(parts)


async def query_structured_with_retry(
    query_fn: Callable[..., AsyncIterator],
    options: ClaudeAgentOptions,
    prompt: str,
    model_class: type[T],
    sdk_logger: Any,
    max_retries: int = 2,
    per_message_callback: Callable[[object], None] | None = None,
) -> T:
    """Call LLM query and parse structured output with ValidationError retry.

    Wraps the common ``async for message in query(...)`` + ``parse_with_model()``
    loop used by every agent (audit / review / implement / …).  When
    ``parse_with_model`` raises **ValidationError** or returns **None**, a
    feedback prompt containing the validation error details is sent to the LLM
    so it can correct its output.

    Args:
        query_fn: The async generator callable (typically :func:`claude_agent_sdk.query`).
        options: SDK agent options.
        prompt: User prompt for the first attempt.
        model_class: Pydantic model class for structured output validation.
        sdk_logger: SdkEventLogger instance for lifecycle logging.
        max_retries: Maximum number of retries after the initial attempt (default 2).
        per_message_callback: Optional callback invoked on every SDK message
            before parsing (useful for extracting side-channel data like cost).

    Returns:
        Validated parsed instance of *model_class*.

    Raises:
        RuntimeError: If no valid structured output is obtained after all attempts.
    """
    current_prompt = prompt
    last_error: ValidationError | None = None

    for attempt in range(max_retries + 1):  # initial + up to max_retries
        try:
            async for message in query_fn(prompt=current_prompt, options=options):
                sdk_logger.handle_message(message, echo_assistant_text=False)
                if per_message_callback is not None:
                    per_message_callback(message)
                try:
                    parsed = parse_with_model(message, model_class)
                    if parsed is not None:
                        return parsed
                except ValidationError as e:
                    last_error = e
                    logger.warning(
                        "Attempt %d/%d: structured output validation failed: %s",
                        attempt + 1,
                        max_retries + 1,
                        _format_validation_error(e),
                    )
        except ValidationError as e:
            last_error = e
            logger.warning(
                "Attempt %d/%d: structured output validation failed: %s",
                attempt + 1,
                max_retries + 1,
                _format_validation_error(e),
            )

        # Prepare feedback prompt for retry
        if attempt < max_retries:
            error_details = _format_validation_error(last_error) if last_error else "未知错误"
            current_prompt = f"""{prompt}

---

**⚠️ 上次输出的结构化数据校验失败，请修正后重新输出：**

{error_details}

请确保输出完全符合 JSON Schema 要求，修正上述字段后重新返回完整的结构化结果。"""
            logger.info("Retrying structured output (attempt %d/%d)", attempt + 2, max_retries + 1)

    # All attempts exhausted
    error_summary = _format_validation_error(last_error) if last_error else "无结构化输出"
    raise RuntimeError(
        f"{model_class.__name__} agent did not return valid structured output "
        f"after {max_retries + 1} attempts. Last error:\n{error_summary}"
    )
