"""Review Agent — PR 自动 Code Review"""

import json
import subprocess
from pathlib import Path
from typing import Any

from gearbox.agents.schemas import ReviewComment as _ReviewCommentModel
from gearbox.agents.schemas import ReviewResult as _ReviewResultModel

# Re-export for backward compat
ReviewComment = _ReviewCommentModel
ReviewResult = _ReviewResultModel


def _coerce_optional_line(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return None


def write_review_result(result: ReviewResult, output_path: Path) -> None:
    from gearbox.agents.shared.artifacts import write_json_artifact

    write_json_artifact(output_path, result)


def load_review_result(path: Path) -> ReviewResult:
    from gearbox.agents.shared.artifacts import read_json_artifact

    data = read_json_artifact(path)
    return ReviewResult.model_validate(data)


# =============================================================================
# GitHub API 辅助
# =============================================================================


def _gh_pr_view(repo: str, pr_number: int) -> Any:
    """获取 PR 信息"""
    cmd = [
        "gh",
        "api",
        f"/repos/{repo}/pulls/{pr_number}",
        "--jq",
        "{title:.title,body:.body,headRefName:.head.ref,baseRefName:.base.ref,state:.state}",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _gh_pr_diff(repo: str, pr_number: int) -> str:
    """获取 PR diff"""
    cmd = ["gh", "pr", "diff", "--repo", repo, str(pr_number)]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout


# =============================================================================
# Prompt
# =============================================================================

SYSTEM_PROMPT = """你是资深 Code Review 专家。请对 PR 进行全面审查。

## 审查维度

1. **逻辑正确性** — 是否有 bug、边界情况未处理
2. **安全漏洞** — SQL注入、XSS、敏感信息泄露等
3. **性能问题** — N+1查询、不必要的重复计算等
4. **测试覆盖**（强制）— 核心逻辑缺少测试必须在 comments 中指出，标记为 `warning` 级别
5. **代码规范** — 命名、注释、重复代码等

## 审查意见级别

- `blocker`: 必须修复才能合并
- `warning`: 建议修复
- `info`: 参考意见

## verdict 说明

- `LGTM`: 可以合并
- `Request Changes`: 需要修复后才能合并
- `Comment Only`: 仅提供意见，不阻止合并

## 输出格式

请直接返回符合 JSON Schema 的结构化结果，不要输出 Markdown 代码块。

## 约束

- blocker 意见必须修复才能 LGTM
- comments 最少 1 条，最多 20 条
- 优先关注安全和逻辑问题
- 如果无法完成审查，在 `failure_reason` 中说明原因"""


async def run_review(
    repo: str,
    pr_number: int,
    *,
    model: str = "claude-sonnet-4-6",
    max_turns: int = 10,
    max_cost_usd: float | None = 3.0,
    previous_review_summary: str | None = None,
) -> ReviewResult:
    """
    执行 PR Code Review。

    Args:
        repo: 仓库标识
        pr_number: PR 编号
        model: 使用的模型
        max_turns: 最大对话轮次
        max_cost_usd: 成本上限（美元），None 表示不限制
        previous_review_summary: 上一次审查的摘要，用于增量审查（可选）

    Returns:
        ReviewResult 结构
    """
    from pathlib import Path

    from claude_agent_sdk import ClaudeAgentOptions

    from gearbox.agents.schemas import output_format_schema, parse_with_model
    from gearbox.agents.shared.runtime import prepare_agent_options, query_with_budget

    project_root = Path(__file__).resolve().parents[3]
    pr_info = _gh_pr_view(repo, pr_number)
    diff_text = _gh_pr_diff(repo, pr_number)

    prev_summary_block = (
        f"**上次审查摘要**（请重点关注新增变化）:\n{previous_review_summary}\n\n"
        if previous_review_summary
        else ""
    )

    prompt = f"""## PR 信息

**仓库**: {repo}
**编号**: #{pr_number}
**标题**: {pr_info["title"]}
**分支**: {pr_info["headRefName"]} -> {pr_info["baseRefName"]}

{prev_summary_block}**Diff**:

{diff_text[:8000]}

---
{SYSTEM_PROMPT}"""

    options, sdk_logger = prepare_agent_options(
        ClaudeAgentOptions(
            model=model,
            max_turns=max_turns,
            output_format=output_format_schema(ReviewResult),
            allowed_tools=["Read", "Grep", "Glob"],
            skills="all",
            cwd=project_root,
        ),
        agent_name="review",
    )
    sdk_logger.log_start(
        model=model,
        max_turns=max_turns,
        base_url=options.env.get("ANTHROPIC_BASE_URL"),
        cwd=str(project_root),
    )

    structured: ReviewResult | None = None

    try:
        async for message in query_with_budget(
            prompt=prompt,
            options=options,
            max_cost_usd=max_cost_usd,
        ):
            sdk_logger.handle_message(message, echo_assistant_text=False)
            if structured is None:
                parsed = parse_with_model(message, ReviewResult)
                if parsed is not None:
                    structured = parsed
                    break
    finally:
        sdk_logger.log_completion()

    if structured is None:
        raise RuntimeError("Review agent did not return structured output")

    return structured
