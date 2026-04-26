"""Triage Agent — Issue 自动分类、优先级判断和标签管理"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

# =============================================================================
# Schema 定义（形式化，代码和文档共用）
# =============================================================================

# JSON Schema 定义 — 形式化描述 Agent 应输出的结构
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {"type": "string"},
            "description": "建议添加的标签，如 bug/enhancement/documentation 等",
        },
        "priority": {
            "type": "string",
            "enum": ["P0", "P1", "P2", "P3"],
            "description": "优先级：P0=生产故障，P1=核心受损，P2=一般，P3=优化建议",
        },
        "complexity": {
            "type": "string",
            "enum": ["S", "M", "L"],
            "description": "实现复杂度：S=<1h，M=1-3天，L=>3天",
        },
        "needs_clarification": {
            "type": "boolean",
            "description": "是否需要追问澄清",
        },
        "clarification_question": {
            "type": ["string", "null"],
            "description": "如果需要澄清，填入追问内容",
        },
        "ready_to_implement": {
            "type": "boolean",
            "description": "是否清晰可实现，可以开始编码",
        },
    },
    "required": ["labels", "priority", "ready_to_implement"],
}

# =============================================================================
# 数据模型
# =============================================================================


@dataclass
class TriageResult:
    """Triage 分析结果（对应 OUTPUT_SCHEMA）"""

    labels: list[str]
    priority: str  # P0/P1/P2/P3
    complexity: str  # S/M/L
    needs_clarification: bool
    clarification_question: str | None
    ready_to_implement: bool


def write_triage_result(result: TriageResult, output_path: Path) -> None:
    from gearbox.agents.shared.artifacts import write_json_artifact

    write_json_artifact(output_path, result)


def load_triage_result(path: Path) -> TriageResult:
    from gearbox.agents.shared.artifacts import read_json_artifact

    data = read_json_artifact(path)
    return TriageResult(
        labels=cast(list[str], data.get("labels", [])),
        priority=cast(str, data.get("priority", "P3")),
        complexity=cast(str, data.get("complexity", "M")),
        needs_clarification=cast(bool, data.get("needs_clarification", False)),
        clarification_question=cast(str | None, data.get("clarification_question")),
        ready_to_implement=cast(bool, data.get("ready_to_implement", False)),
    )


# =============================================================================
# GitHub API 辅助
# =============================================================================


def _gh_issue_view(repo: str, issue_number: int) -> Any:
    """通过 gh api 获取 issue 完整信息"""
    cmd = [
        "gh",
        "api",
        f"/repos/{repo}/issues/{issue_number}",
        "--jq",
        "{title:.title,body:.body,labels:[.labels[].name],state:.state}",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


# =============================================================================
# Prompt 模板
# =============================================================================

SYSTEM_PROMPT = """你是 Issue 分类专家。请分析 GitHub Issue 并提供分类结果。

## 分析维度

1. **类型标签** (选择最合适的):
   - bug: 缺陷报告
   - enhancement: 功能增强
   - documentation: 文档改进
   - question: 疑问
   - refactor: 重构
   - performance: 性能相关
   - security: 安全相关

2. **优先级**:
   - P0: 生产环境故障、数据丢失风险
   - P1: 核心功能受损、用户体验严重下降
   - P2: 一般功能问题、边界情况
   - P3: 优化建议、便利性改进

3. **复杂度**:
   - S: 1小时内可完成
   - M: 1-3天
   - L: 超过3天

4. **是否需要澄清**: 如果 Issue 缺少复现步骤、期望行为、上下文等信息，应标记需要澄清

## 输出格式

请直接返回符合 JSON Schema 的结构化结果，不要输出 Markdown 代码块。

**约束**:
- labels 至少一个标签
- priority 只可是 P0/P1/P2/P3
- complexity 只可是 S/M/L
- needs_clarification=true 时 clarification_question 必填
- ready_to_implement=true 表示可进入实现阶段"""


async def run_triage(
    repo: str,
    issue_number: int,
    *,
    model: str = "claude-sonnet-4-6",
    max_turns: int = 5,
) -> TriageResult:
    """
    执行 Issue 分类。

    Args:
        repo: 仓库标识 (owner/name)
        issue_number: Issue 编号
        model: 使用的模型
        max_turns: 最大对话轮次

    Returns:
        TriageResult 结构
    """
    from pathlib import Path

    from claude_agent_sdk import ClaudeAgentOptions, query

    from gearbox.agents.shared.runtime import prepare_agent_options
    from gearbox.agents.shared.structured import json_schema_output, parse_structured_output

    project_root = Path(__file__).resolve().parents[3]
    issue = _gh_issue_view(repo, issue_number)

    prompt = f"""## Issue 信息

**仓库**: {repo}
**编号**: #{issue_number}
**标题**: {issue["title"]}
**正文**:

{issue["body"] or "(无正文)"}

**现有标签**: {", ".join(issue["labels"]) if issue["labels"] else "(无)"}

---
{SYSTEM_PROMPT}"""

    options, sdk_logger = prepare_agent_options(
        ClaudeAgentOptions(
            model=model,
            max_turns=max_turns,
            output_format=json_schema_output(OUTPUT_SCHEMA),
            allowed_tools=["Read", "Bash"],
            skills="all",
            cwd=project_root,
        ),
        agent_name="triage",
    )
    sdk_logger.log_start(
        model=model,
        max_turns=max_turns,
        base_url=options.env.get("ANTHROPIC_BASE_URL"),
        cwd=str(project_root),
    )

    structured: TriageResult | None = None

    try:
        async for message in query(prompt=prompt, options=options):
            sdk_logger.handle_message(message, echo_assistant_text=False)
            if not structured:
                structured = parse_structured_output(
                    message,
                    lambda data: TriageResult(
                        labels=cast(list[str], data.get("labels", [])),
                        priority=cast(str, data.get("priority", "P3")),
                        complexity=cast(str, data.get("complexity", "M")),
                        needs_clarification=cast(bool, data.get("needs_clarification", False)),
                        clarification_question=cast(str | None, data.get("clarification_question")),
                        ready_to_implement=cast(bool, data.get("ready_to_implement", False)),
                    ),
                )
    finally:
        sdk_logger.log_completion()

    if structured is None:
        raise RuntimeError("Triage agent did not return structured output")

    return structured
