"""Audit Agent — 仓库审计，生成改进建议"""

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# =============================================================================
# Schema 定义
# =============================================================================

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repo": {"type": "string", "description": "仓库标识"},
        "profile": {
            "type": "object",
            "description": "仓库 Profile",
        },
        "benchmarks": {
            "type": "array",
            "items": {"type": "string"},
            "description": "对标仓库列表",
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "labels": {"type": "string"},
                },
                "required": ["title", "body", "labels"],
            },
            "description": "改进建议列表",
        },
    },
    "required": ["repo", "issues"],
}

OUTPUT_FILES = ("profile.json", "comparison.md", "issues.json")

# =============================================================================
# 数据模型
# =============================================================================


@dataclass
class Issue:
    title: str
    body: str
    labels: str


@dataclass
class AuditResult:
    """Audit Agent 结果"""

    repo: str
    profile: dict[str, Any] = field(default_factory=dict)
    benchmarks: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    cost: float | None = None


# =============================================================================
# 结果解析
# =============================================================================


def _parse_result(text: str) -> AuditResult | None:
    """从 Agent 输出解析 AuditResult"""
    try:
        match = re.search(r"```json\s*(\{.*?)\s*```", text, re.DOTALL)
        if not match:
            return None

        data = json.loads(match.group(1))
        issues_data = data.get("issues", [])

        if "file_content" in data:
            file_content = data["file_content"]
            if "issues" in file_content:
                issues_data = file_content["issues"]

        issues = [
            Issue(
                title=i.get("title", ""),
                body=i.get("body", ""),
                labels=i.get("labels", "enhancement"),
            )
            for i in issues_data
        ]

        return AuditResult(
            repo=data.get("repo", ""),
            profile=data.get("profile", {}),
            benchmarks=data.get("benchmarks", []),
            issues=issues,
        )
    except (json.JSONDecodeError, KeyError):
        return None


# =============================================================================
# Prompt
# =============================================================================

SYSTEM_PROMPT = """你是 Gearbox，一个专业的代码库审计专家。

## 目标

分析目标仓库，发现与业界标杆的差距，生成可执行的改进建议。

## 工作流程

1. 用 Read 分析本地仓库结构，或用 `gh repo view` 查看远程仓库
2. 用 `gh search repos` 发现对标项目
3. 用 ctx7 查询相关库的官方文档（`npx ctx7 docs <library-id> <query>`）
4. 自主分析并生成报告

## 输出格式

**必须生成以下文件**（使用 Write 工具保存到指定目录）:
- `profile.json` - 仓库 Profile（类型、语言、构建配置、质量工具等）
- `comparison.md` - 对比矩阵（Markdown 表格）
- `issues.json` - 改进建议列表（**重要！必须创建**）

**issues.json 格式**:
```json
{
  "repo": "owner/repo",
  "profile": {...},
  "benchmarks": ["pallets/click", "fastapi/typer"],
  "issues": [
    {
      "title": "简短明确的标题",
      "body": "## 问题\n一句话描述\n\n## 解决方案\n1. 要点一\n2. 要点二\n3. 要点三",
      "labels": "high,enhancement"
    }
  ]
}
```

## 质量要求

- 最多 3 个 Issues
- 每个 Issue ≤1000 字符，≤3 个要点
- 标签包含优先级（critical/high/medium/low）
- 精选最重要的改进项
- 不要尝试创建 GitHub Issue，只生成 JSON 文件"""


async def run_audit(
    repo: str,
    benchmarks: list[str] | None = None,
    output_dir: str = "./output",
    *,
    model: str | None = None,
    max_turns: int = 20,
    system_prompt: str | None = None,
) -> AuditResult:
    """
    执行仓库审计。

    Args:
        repo: 仓库标识 (owner/repo 或本地路径)
        benchmarks: 指定的对标仓库列表
        output_dir: 输出目录
        model: 使用的模型
        max_turns: 最大对话轮次
        system_prompt: 自定义 System Prompt（可选，默认使用内置）

    Returns:
        AuditResult 结构
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    from gearbox.agents.sdk_logging import prepare_sdk_options
    from gearbox.config import get_anthropic_base_url, get_anthropic_model

    resolved_model = model or get_anthropic_model()
    resolved_prompt = system_prompt if system_prompt else SYSTEM_PROMPT

    # 项目根目录（用于定位 .claude/skills/）
    project_root = Path(__file__).parent.parent.parent

    options, sdk_logger = prepare_sdk_options(
        ClaudeAgentOptions(
            model=resolved_model,
            system_prompt=resolved_prompt,
            max_turns=max_turns,
            skills="all",
            cwd=project_root,
        ),
        agent_name="audit",
    )
    sdk_logger.log_start(
        model=resolved_model,
        max_turns=max_turns,
        base_url=get_anthropic_base_url(),
        cwd=str(project_root),
    )

    if benchmarks:
        benchmark_str = ", ".join(benchmarks)
        prompt = f"""请审计仓库: {repo}

对标项目: {benchmark_str}

输出目录: {output_dir}

请生成 profile.json、comparison.md 和 issues.json。"""
    else:
        prompt = f"""请审计仓库: {repo}

请自主发现对标项目（约 5 个），然后进行对比分析。

输出目录: {output_dir}

请生成 profile.json、comparison.md 和 issues.json。"""

    result_text = ""
    structured: AuditResult | None = None
    total_cost: float | None = None

    try:
        async for message in query(prompt=prompt, options=options):
            sdk_logger.handle_message(message, echo_assistant_text=False)
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        result_text += block.text
            elif isinstance(message, ResultMessage):
                if message.total_cost_usd is not None:
                    total_cost = message.total_cost_usd

            parsed = _parse_result(result_text)
            if parsed and not structured:
                structured = parsed
    finally:
        sdk_logger.log_completion()

    if structured is None:
        structured = _parse_result(result_text)

    if structured is None:
        structured = AuditResult(
            repo=repo,
            issues=[],
        )
    structured.cost = total_cost

    return structured


def promote_audit_outputs(source_dir: Path, target_dir: Path) -> None:
    """将胜出实例的产物提升到最终输出目录。"""
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename in OUTPUT_FILES:
        source = source_dir / filename
        if source.exists():
            shutil.copy2(source, target_dir / filename)
