"""Pydantic-driven schema registry for agent structured output.

Replaces hand-written JSON Schema dicts + dataclass + lambda parsers
with a single source of truth: Pydantic BaseModel definitions.

Usage:
    from gearbox.agents.schemas import output_format_schema, parse_with_model

    # Generate SDK-compatible output_format from a Pydantic model
    fmt = output_format_schema(AuditResult)

    # Parse + validate structured output in one call
    result = parse_with_model(message, AuditResult)
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, TypeVar, cast

from pydantic import BaseModel, ValidationError

from .audit import AuditResult, Issue
from .backlog import BacklogItemResult
from .evaluator import EvaluationResult
from .implement import ImplementResult
from .review import ReviewComment, ReviewResult

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_REGISTRY: dict[str, type[BaseModel]] = {
    "audit": AuditResult,
    "review": ReviewResult,
    "backlog": BacklogItemResult,
    "implement": ImplementResult,
    "evaluator": EvaluationResult,
}


def output_format_schema(model_class: type[BaseModel]) -> dict[str, Any]:
    """Generate Claude Agent SDK compatible output_format from a Pydantic model.

    Auto-generates JSON schema from the model and inlines $defs references
    so the SDK StructuredOutput tool receives a self-contained schema.
    """
    json_schema = _inline_defs(model_class.model_json_schema())
    return {
        "type": "json_schema",
        "schema": json_schema,
        "name": model_class.__name__,
        "strict": True,
    }


def validate(model_class: type[T], data: dict[str, Any]) -> T:
    """Validate raw dict against a Pydantic model, returning a validated instance."""
    return model_class.model_validate(data)


def parse_with_model(message: object, model_class: type[T]) -> T | None:
    """Extract structured output from SDK message and validate via Pydantic.

    Combines raw extraction (ResultMessage.structured_output or
    ToolUseBlock named 'StructuredOutput') with model_validate() for
    type-safe, validated parsing.
    """
    raw = _extract_raw_dict(message)
    if raw is None:
        return None
    try:
        return model_class.model_validate(raw)
    except ValidationError as e:
        logger.warning(
            "Structured output validation failed for %s: %s",
            model_class.__name__,
            e,
        )
        raise


def _extract_raw_dict(message: object) -> dict[str, Any] | None:
    """Extract raw dict from SDK message (ResultMessage or AssistantMessage+ToolUseBlock)."""
    from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock

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


def _inline_defs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline $defs/$refs so the schema is self-contained.

    The SDK StructuredOutput tool works more reliably with an inlined schema
    than one that depends on $defs/$ref indirection (Pydantic default).
    """
    schema = deepcopy(schema)
    defs = schema.pop("$defs", {})

    def _resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.removeprefix("#/$defs/")
                if name in defs:
                    resolved = _resolve(deepcopy(defs[name]))
                    siblings = {k: v for k, v in node.items() if k != "$ref"}
                    if siblings and isinstance(resolved, dict):
                        resolved.update(_resolve(siblings))
                    return resolved
            return {k: _resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_resolve(item) for item in node]
        return node

    return cast("dict[str, Any]", _resolve(schema))


__all__ = [
    "output_format_schema",
    "validate",
    "parse_with_model",
    # Models
    "AuditResult",
    "Issue",
    "ReviewResult",
    "ReviewComment",
    "BacklogItemResult",
    "ImplementResult",
    "EvaluationResult",
]
