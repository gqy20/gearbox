"""Fix Agent — 根据 Review 反馈修补 PR"""

import json
import subprocess
from pathlib import Path
from typing import Any

from gearbox.agents.schemas import FixResult as _FixResultModel
from gearbox.agents.schemas import output_format_schema
from gearbox.agents.shared.structured import query_structured_with_retry

FixResult = _FixResultModel

DEFAULT_FIX_MAX_TURNS = 20

SYSTEM_PROMPT = """你是代码修复专家。请根据 Code Review 的反馈意见，精确修改 PR 中的代码。

## 工作原则

1. **只改已有文件** — 不要创建新文件或删除文件
2. **精准修补** — 每个修改必须对应一条具体的 review comment
3. **最小改动** — 只改 review 指出的地方，不要顺便重构
4. **保持风格一致** — 遵循项目现有代码风格

## Review 反馈

以下是需要处理的 review comment（按严重程度排序）：

{review_comments_section}

## 约束

- `commits_pushed`: 本次推送的 commit 数量
- `files_modified`: 本次修改的文件列表
- 如果某条 comment 无法修复（如架构性问题），设置 `verdict=partial` 并在 `failure_reason` 说明
- 如果所有 comment 都已处理，设置 `verdict=fixed`
- 如果无法执行任何修复，设置 `verdict=skipped`

## 输出格式

请直接返回符合 JSON Schema 的结构化结果。"""


def build_fix_prompt(
    repo: str,
    pr_number: int,
    pr_info: dict[str, Any],
    review_comments: list[dict[str, Any]],
) -> str:
    """组装 fix agent prompt。"""
    comments_section = ""
    if review_comments:
        lines = []
        for i, c in enumerate(review_comments, 1):
            loc = f" ({c.get('file', '')}:{c.get('line', '')})" if c.get("file") else ""
            sev = f"[{c.get('severity', 'info')}]" if c.get("severity") else ""
            lines.append(f"{i}. {sev}{loc}: {c.get('body', '')}")
        comments_section = "\n".join(lines)
    else:
        comments_section = "(无具体 review comments)"

    title = pr_info.get("title", "")
    head = pr_info.get("headRefName", "unknown")
    base = pr_info.get("baseRefName", "main")

    return f"""## PR 信息

**仓库**: {repo}
**编号**: #{pr_number}
**标题**: {title}
**分支**: {head} -> {base}

## Review Comments

{comments_section}

---
{SYSTEM_PROMPT}"""


def _gh_pr_view(repo: str, pr_number: int) -> dict[str, Any]:
    """获取 PR 信息"""
    cmd = [
        "gh",
        "api",
        f"/repos/{repo}/pulls/{pr_number}",
        "--jq",
        "{title:.title,headRefName:.head.ref,baseRefName:.base.ref}",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return dict(json.loads(result.stdout))  # type: ignore[no-any-return]


async def run_fix(
    repo: str,
    pr_number: int,
    *,
    model: str = "claude-sonnet-4-6",
    max_turns: int = DEFAULT_FIX_MAX_TURNS,
) -> FixResult:
    """
    执行 Fix Agent — 根据 Review 反馈修补 PR。

    Args:
        repo: 仓库标识
        pr_number: PR 编号
        model: 使用的模型
        max_turns: 最大对话轮次

    Returns:
        FixResult 结构
    """
    from claude_agent_sdk import ClaudeAgentOptions, query

    from gearbox.agents.shared.runtime import prepare_agent_options
    from gearbox.config import get_anthropic_model

    resolved_model = model or get_anthropic_model()
    pr_info = _gh_pr_view(repo, pr_number)

    # Fetch actual review comments from GitHub for context
    # (The caller may also pass in pre-fetched comments)
    prompt = build_fix_prompt(repo, pr_number, pr_info, [])

    options, sdk_logger = prepare_agent_options(
        ClaudeAgentOptions(
            model=resolved_model,
            system_prompt=SYSTEM_PROMPT.format(review_comments_section="(见上方 Review Comments)"),
            max_turns=max_turns,
            output_format=output_format_schema(FixResult),
            allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
            permission_mode="acceptEdits",
            skills="all",
            cwd=Path.cwd(),
        ),
        agent_name="fix",
    )
    sdk_logger.log_start(
        model=resolved_model,
        max_turns=max_turns,
        base_url=options.env.get("ANTHROPIC_BASE_URL"),
        cwd=str(Path.cwd()),
    )

    try:
        structured = await query_structured_with_retry(
            query_fn=query,
            options=options,
            prompt=prompt,
            model_class=FixResult,
            sdk_logger=sdk_logger,
        )
    finally:
        sdk_logger.log_completion()

    return structured
