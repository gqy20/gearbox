"""Backlog Agent — Issue 自动分类、优先级判断和标签管理"""

import json
import re
import subprocess
from pathlib import Path
from typing import Any, cast

import click

from gearbox.agents.schemas import BacklogItemResult as _BacklogItemResultModel

# Re-export for backward compat
BacklogItemResult = _BacklogItemResultModel


class BacklogResult:
    """Backlog 分类结果，单 issue 是多 issue 的特例。"""

    def __init__(self, items: list[BacklogItemResult]) -> None:
        self.items = items


def parse_issue_numbers(value: str) -> list[int]:
    """Parse comma/space separated issue numbers, supporting ``#`` prefix.

    Accepts inputs like ``#12``, ``#12, #13``, ``12 #13,14``.
    Returns an empty list for blank input.
    Raises :class:`ValueError` with a helpful message when a token
    cannot be parsed as an integer.
    """
    if not value.strip():
        return []

    raw_tokens = re.split(r"[\s,]+", value.strip())
    numbers: list[int] = []
    bad_tokens: list[str] = []

    for token in raw_tokens:
        if not token:
            continue
        stripped = token.lstrip("#")
        try:
            numbers.append(int(stripped))
        except ValueError:
            bad_tokens.append(token)

    if bad_tokens:
        raise ValueError(
            f"无法解析 issue 编号: {', '.join(repr(t) for t in bad_tokens)}。"
            f"请使用数字或 #数字 格式，例如 '12, 13' 或 '#12 #13'"
        )

    return list(dict.fromkeys(numbers))


def github_labels_for_backlog_item(result: BacklogItemResult) -> list[str]:
    """Return GitHub labels that represent the full backlog classification decision."""
    labels = [
        *result.labels,
        result.priority,
        f"complexity:{result.complexity}",
    ]

    if result.ready_to_implement:
        labels.append("ready-to-implement")

    return list(dict.fromkeys(label for label in labels if label))


def write_backlog_result(result: BacklogResult, output_path: Path) -> None:
    from gearbox.agents.shared.artifacts import write_json_artifact

    write_json_artifact(output_path, result)


def load_backlog_result(path: Path) -> BacklogResult:
    from gearbox.agents.shared.artifacts import read_json_artifact

    data = read_json_artifact(path)
    raw_items = data.get("items", [])
    assert isinstance(raw_items, list)
    return BacklogResult(
        items=[
            BacklogItemResult.model_validate(item)
            for item in cast(list[dict[str, object]], raw_items)
        ]
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

## 源码分析

在分类前，你应当使用 Read/Bash 工具了解相关代码上下文，结合源码判断：
- 问题的本质（是否真的影响核心功能）
- 修复所需改动的大小（影响几个文件、是否需要改公共接口）
- 依赖和测试覆盖情况（是否容易引入回归）

## 输出格式

请直接返回符合 JSON Schema 的结构化结果，不要输出 Markdown 代码块。

**约束**:
- labels 至少一个标签
- priority 只可是 P0/P1/P2/P3
- complexity 只可是 S/M/L
- ready_to_implement=true 表示可进入实现阶段
- 如果无法完成分类，在 failure_reason 中说明原因"""


async def run_backlog_item(
    repo: str,
    issue_number: int,
    *,
    model: str = "claude-sonnet-4-6",
    max_turns: int = 15,
) -> BacklogItemResult:
    """
    执行 Issue 分类。

    Args:
        repo: 仓库标识 (owner/name)
        issue_number: Issue 编号
        model: 使用的模型
        max_turns: 最大对话轮次

    Returns:
        BacklogItemResult 结构
    """
    import tempfile

    from claude_agent_sdk import ClaudeAgentOptions, query

    from gearbox.agents.schemas import output_format_schema, parse_with_model
    from gearbox.agents.shared import clone_repository
    from gearbox.agents.shared.prompt_helpers import format_issues_summary
    from gearbox.agents.shared.runtime import prepare_agent_options
    from gearbox.core.gh import list_open_issues

    issue = _gh_issue_view(repo, issue_number)
    all_issues = list_open_issues(repo, limit=50)
    issues_summary = format_issues_summary(all_issues, current_issue_number=issue_number)

    clone_root: Path | None = None
    clone_dir: tempfile.TemporaryDirectory[str] | None = None
    clone_failed = False

    # 仅远程仓库（owner/repo 格式）需要克隆，本地路径不具备 GitHub API 上下文
    if "/" in repo:
        try:
            clone_root, clone_dir = clone_repository(repo)
        except (RuntimeError, OSError) as exc:
            click.echo(
                f"⚠️ 克隆目标仓库 {repo} 失败 "
                f"({exc.__class__.__name__}: {exc})，"
                f"将回退到当前工作目录，Agent 将基于 Issue 正文进行分类。",
                err=True,
            )
            clone_failed = True

    cwd = clone_root if clone_root else Path.cwd()

    _clone_fallback_notice = (
        "\n> **注意**: 当前未加载目标仓库源码（克隆失败），请基于 Issue 正文和标签进行分类。\n"
        if clone_failed
        else ""
    )

    prompt = f"""## 当前 Issue 信息

**仓库**: {repo}
**编号**: #{issue_number}
**标题**: {issue["title"]}
**正文**:

{issue["body"] or "(无正文)"}

**现有标签**: {", ".join(issue["labels"]) if issue["labels"] else "(无)"}

## {issues_summary}

{_clone_fallback_notice}---
{SYSTEM_PROMPT}"""

    options, sdk_logger = prepare_agent_options(
        ClaudeAgentOptions(
            model=model,
            max_turns=max_turns,
            output_format=output_format_schema(BacklogItemResult),
            allowed_tools=["Read", "Bash"],
            skills="all",
            cwd=cwd,
        ),
        agent_name="backlog",
    )
    sdk_logger.log_start(
        model=model,
        max_turns=max_turns,
        base_url=options.env.get("ANTHROPIC_BASE_URL"),
        cwd=str(cwd),
    )

    structured: BacklogItemResult | None = None

    try:
        async for message in query(prompt=prompt, options=options):
            sdk_logger.handle_message(message, echo_assistant_text=False)
            if structured is None:
                parsed = parse_with_model(message, BacklogItemResult)
                if parsed is not None:
                    structured = parsed
                    # Inject issue_number since it's not part of the schema output
                    structured.issue_number = issue_number
                    break
    finally:
        sdk_logger.log_completion()
        if clone_dir is not None:
            clone_dir.cleanup()

    if structured is None:
        raise RuntimeError("Backlog agent did not return structured output")

    return structured
