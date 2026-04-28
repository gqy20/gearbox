"""Evaluator Agent — 通用评估器，评判多个结果的优劣"""

import json
from typing import Any

from gearbox.agents.schemas import EvaluationResult as _EvaluationResultModel

# Re-export for backward compat
EvaluationResult = _EvaluationResultModel

DEFAULT_EVALUATOR_MAX_TURNS = 29


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
) -> str:
    """
    构建评估 prompt。

    Args:
        results: 结果列表
        result_type: 结果类型描述（如 "Audit 结果"、"Backlog 结果"）
        result_names: 可选的名称列表（如 ["质量角度", "安全角度"]）

    Returns:
        完整的评估 prompt
    """
    prompt_parts = [
        f"请评估以下 {len(results)} 个 {result_type}，选出最佳的一个。\n",
    ]

    for i, result in enumerate(results):
        name = result_names[i] if result_names and i < len(result_names) else f"结果 {i}"
        prompt_parts.append(f"\n## {name} (索引: {i})\n")
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
    model: str | None = None,
    max_turns: int = DEFAULT_EVALUATOR_MAX_TURNS,
) -> EvaluationResult:
    """
    运行评估器。

    Args:
        results: 待评估的结果列表
        result_type: 结果类型描述
        result_names: 可选的名称列表
        model: 使用的模型（默认使用 get_anthropic_model()）
        max_turns: 最大对话轮次

    Returns:
        EvaluationResult
    """
    from claude_agent_sdk import (
        ClaudeAgentOptions,
        query,
    )

    from gearbox.agents.schemas import output_format_schema, parse_with_model
    from gearbox.agents.shared.runtime import prepare_agent_options
    from gearbox.config import get_anthropic_model

    if model is None:
        model = get_anthropic_model()

    prompt = build_evaluation_prompt(results, result_type, result_names)

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
