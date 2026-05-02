"""Evaluator Agent — 通用评估器，评判多个结果的优劣"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from gearbox.agents.schemas import EvaluationResult as _EvaluationResultModel

logger = logging.getLogger(__name__)

# Re-export for backward compat
EvaluationResult = _EvaluationResultModel

DEFAULT_EVALUATOR_MAX_TURNS = 29

# Core fields required per result type for completeness scoring
_CORE_FIELDS: dict[str, list[str]] = {
    "implement": ["branch_name", "summary"],
    "audit": ["repo", "issues"],
    "review": ["verdict", "score", "summary"],
    "backlog": ["labels", "priority"],
}


@dataclass
class CandidateInfo:
    """Per-candidate metadata produced by validation."""

    index: int
    serialization_size: int
    completeness: float
    missing_fields: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of validating a list of candidate results."""

    valid: bool
    candidates: list[CandidateInfo]
    completeness_report: list[float] = field(default_factory=list)


def validate_results(
    results: list[Any],
    result_type: str,
) -> ValidationResult:
    """Validate candidate results before sending to evaluator.

    Checks:
    1. Results list is not empty
    2. All elements are BaseModel instances (consistent serialisation)
    3. Each element serialises to a non-empty dict
    4. Core fields for *result_type* are present and non-empty

    Returns a ``ValidationResult`` with per-candidate metadata including
    completeness scores (0.0–1.0) that can be injected into the prompt.

    Raises:
        ValueError: if *results* is empty.
        ValidationError: if any element is not a BaseModel instance.
    """
    if not results:
        raise ValueError("results must not be empty")

    core_fields = _CORE_FIELDS.get(result_type, [])
    candidates: list[CandidateInfo] = []
    completeness_report: list[float] = []

    for i, result in enumerate(results):
        # --- type consistency guard ---
        if not isinstance(result, BaseModel):
            raise TypeError(
                f"results[{i}] must be a BaseModel instance, got {type(result).__name__}",
            )

        data = result.model_dump()
        if not isinstance(data, dict) or len(data) == 0:
            raise ValidationError(
                f"results[{i}] serialised to an empty or non-dict value",
            )

        # --- core-field completeness ---
        missing: list[str] = []
        for fname in core_fields:
            val = data.get(fname)
            if val is None or val == "":
                missing.append(fname)

        completeness = 1.0 - (len(missing) / max(len(core_fields), 1))
        ser_size = len(json.dumps(data, ensure_ascii=False))

        info = CandidateInfo(
            index=i,
            serialization_size=ser_size,
            completeness=completeness,
            missing_fields=missing,
        )
        candidates.append(info)
        completeness_report.append(completeness)

        level = logging.DEBUG if completeness >= 1.0 else logging.WARNING
        logger.log(
            level,
            "candidate[%d]: serialization_size=%d, completeness=%.2f, missing_fields=%s",
            i,
            ser_size,
            completeness,
            missing,
        )

    return ValidationResult(
        valid=True,
        candidates=candidates,
        completeness_report=completeness_report,
    )


# =============================================================================
# Prompt 模板
# =============================================================================

SYSTEM_PROMPT = """你是结果评估专家。请评估多个候选结果，选出最佳的一个。

## 评估维度

1. **完整性** — 结果是否包含所有必要字段
2. **正确性** — 内容是否符合预期格式和规范
3. **可执行性** — 建议是否具体、可操作
4. **一致性** — 多个结果之间是否有共识

## 输入格式

你会收到 N 个候选结果，每个结果对应一个索引 (0 到 N-1)。
每个结果旁边会标注其来源或角度。

## 输出要求

请直接返回符合 JSON Schema 的结构化结果，不要输出 Markdown 代码块。

- winner: 最佳结果的索引 (0-9)
- scores: 每个结果的评分 (0-1) 及评分依据 justification（必须说明具体证据）
- reasoning: 详细解释，不少于 100 字。必须包含：为什么 winner 比其他的好？其他结果被拒绝的具体原因是什么？共识项有哪些？
- consensus: 多个结果一致认为重要的项列表（可选）"""


def build_evaluation_prompt(
    results: list[Any],
    result_type: str,
    result_names: list[str] | None = None,
    *,
    validation: ValidationResult | None = None,
) -> str:
    """
    构建评估 prompt。

    Args:
        results: 结果列表
        result_type: 结果类型描述（如 "Audit 结果"、"Backlog 结果"）
        result_names: 可选的名称列表（如 ["质量角度", "安全角度"]）
        validation: Optional pre-validation result for completeness annotations.

    Returns:
        完整的评估 prompt
    """
    prompt_parts = [
        f"请评估以下 {len(results)} 个 {result_type}，选出最佳的一个。\n",
    ]

    for i, result in enumerate(results):
        name = result_names[i] if result_names and i < len(result_names) else f"结果 {i}"
        prompt_parts.append(f"\n## {name} (索引: {i})\n")

        # Inject completeness warning when validation metadata is available
        if validation is not None:
            cand = validation.candidates[i]
            if cand.completeness < 1.0:
                prompt_parts.append(
                    f"> ⚠️ 此结果不完整 (完整度 {cand.completeness:.0%})，"
                    f"缺失字段: {', '.join(cand.missing_fields) or '无'}。\n"
                )
            else:
                prompt_parts.append(f"> ✅ 完整度 {cand.completeness:.0%}\n")

        prompt_parts.append(_format_result_for_prompt(result))

    prompt_parts.append(f"\n{SYSTEM_PROMPT}")

    return "".join(prompt_parts)


def _format_result_for_prompt(result: Any) -> str:
    """将结果格式化为 prompt 文本"""
    if hasattr(result, "model_dump"):
        data = result.model_dump()
    elif hasattr(result, "__dict__"):
        data = {
            k: v for k, v in result.__dict__.items() if not k.startswith("_") and not callable(v)
        }
    elif isinstance(result, dict):
        data = result
    else:
        return str(result)

    return json.dumps(data, ensure_ascii=False, indent=2)


# =============================================================================
# 运行评估
# =============================================================================


async def run_evaluator(
    results: list[Any],
    result_type: str,
    result_names: list[str] | None = None,
    *,
    model: str = "claude-sonnet-4-6",
    max_turns: int = DEFAULT_EVALUATOR_MAX_TURNS,
) -> EvaluationResult:
    """
    运行评估器。

    Args:
        results: 待评估的结果列表
        result_type: 结果类型描述
        result_names: 可选的名称列表
        model: 使用的模型
        max_turns: 最大对话轮次

    Returns:
        EvaluationResult
    """
    # --- input consistency pre-validation ---
    validation = validate_results(results, result_type)
    logger.info(
        "Evaluator input validated: %d candidates, avg_completeness=%.2f",
        len(results),
        sum(validation.completeness_report) / len(validation.completeness_report),
    )

    from claude_agent_sdk import (
        ClaudeAgentOptions,
        query,
    )

    from gearbox.agents.schemas import output_format_schema, parse_with_model
    from gearbox.agents.shared.runtime import prepare_agent_options
    from gearbox.config import get_anthropic_model

    model = model or get_anthropic_model()

    prompt = build_evaluation_prompt(
        results,
        result_type,
        result_names,
        validation=validation,
    )

    options, sdk_logger = prepare_agent_options(
        ClaudeAgentOptions(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            max_turns=max_turns,
            output_format=output_format_schema(EvaluationResult),
        ),
        agent_name="evaluator",
    )
    sdk_logger.log_start(
        model=model,
        max_turns=max_turns,
        base_url=options.env.get("ANTHROPIC_BASE_URL"),
        cwd="(sdk default)",
    )

    structured: EvaluationResult | None = None

    try:
        async for message in query(prompt=prompt, options=options):
            sdk_logger.handle_message(message, echo_assistant_text=False)
            if structured is None:
                parsed = parse_with_model(message, EvaluationResult)
                if parsed is not None:
                    structured = parsed
                    break
    finally:
        sdk_logger.log_completion()

    if structured is None:
        raise RuntimeError("Evaluator agent did not return structured output")

    return structured
