"""Implement Agent — Issue → 分支/PR"""

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any

# =============================================================================
# Schema 定义
# =============================================================================

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "branch_name": {
            "type": "string",
            "description": "创建的分支名，格式 feat/issue-{number} 或 gearbox/implement-{number}",
        },
        "summary": {
            "type": "string",
            "description": "本次修改的简要说明",
        },
        "files_changed": {
            "type": "array",
            "items": {"type": "string"},
            "description": "修改的文件路径列表",
        },
        "pr_url": {
            "type": "string",
            "description": "创建的 PR URL，尚未创建时为 null",
        },
        "ready_for_review": {
            "type": "boolean",
            "description": "是否已提交并准备好等待 review",
        },
    },
    "required": ["branch_name", "summary", "files_changed", "ready_for_review"],
}

# =============================================================================
# 数据模型
# =============================================================================


@dataclass
class ImplementResult:
    """Implement Agent 执行结果"""

    branch_name: str
    summary: str
    files_changed: list[str]
    pr_url: str | None
    ready_for_review: bool


# =============================================================================
# GitHub API 辅助
# =============================================================================


def _gh_issue_view(repo: str, issue_number: int) -> Any:
    """获取 issue 信息"""
    cmd = [
        "gh",
        "api",
        f"/repos/{repo}/issues/{issue_number}",
        "--jq",
        "{title:.title,body:.body,labels:.labels[*].name}",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _gh_pr_view(repo: str, pr_number: int) -> Any:
    """获取 PR 信息"""
    cmd = [
        "gh",
        "api",
        f"/repos/{repo}/pulls/{pr_number}",
        "--jq",
        "{title:.title,body:.body,headRefName:.head.ref}",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


# =============================================================================
# 结果解析
# =============================================================================


def _parse_result(text: str) -> ImplementResult | None:
    """从 Agent 输出解析 ImplementResult"""
    try:
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group(1))
        return ImplementResult(
            branch_name=data.get("branch_name", ""),
            summary=data.get("summary", ""),
            files_changed=data.get("files_changed", []),
            pr_url=data.get("pr_url"),
            ready_for_review=data.get("ready_for_review", False),
        )
    except (json.JSONDecodeError, KeyError):
        return None


# =============================================================================
# Prompt
# =============================================================================

SYSTEM_PROMPT = """你是代码实现专家。请根据 Issue 描述实现代码变更，并创建 PR。

## 工作流程

1. 阅读 Issue 了解需求
2. 分析代码库结构，找到相关文件
3. 实现代码变更
4. 提交到新分支
5. 创建 PR（关联 Issue）

## 安全约束

- **分支命名**: 必须使用 `feat/issue-{number}` 或 `gearbox/implement-{number}` 前缀
- **绝不直接 push 到 main/master**
- 提交前运行测试和 lint
- PR body 必须关联 Issue: `Closes #{issue_number}`

## 输出格式

请严格按以下 JSON 格式输出:

```json
{
  "branch_name": "feat/issue-42",
  "summary": "添加用户认证中间件",
  "files_changed": ["src/auth/middleware.py", "tests/test_auth.py"],
  "pr_url": null,
  "ready_for_review": true
}
```

创建 PR 后，将 pr_url 填入 JSON。

## 约束

- branch_name 必须以 feat/ 或 gearbox/ 开头
- files_changed 列出所有修改文件
- ready_for_review=true 表示已完成并推送"""


async def run_implement(
    repo: str,
    issue_number: int,
    *,
    model: str = "claude-sonnet-4-6",
    base_branch: str = "main",
    max_turns: int = 20,
) -> ImplementResult:
    """
    执行 Issue 实现。

    Args:
        repo: 仓库标识
        issue_number: Issue 编号
        model: 使用的模型
        base_branch: PR 目标分支
        max_turns: 最大对话轮次

    Returns:
        ImplementResult 结构
    """
    from pathlib import Path

    from claude_agent_sdk import ClaudeAgentOptions, query

    from gearbox.agents.runtime import prepare_agent_options
    from gearbox.agents.structured import append_assistant_text
    project_root = Path(__file__).parent.parent.parent
    issue = _gh_issue_view(repo, issue_number)
    issue_title = issue["title"]
    issue_body = issue["body"] or "(无正文)"

    prompt = f"""## Issue 信息

**仓库**: {repo}
**编号**: #{issue_number}
**标题**: {issue_title}
**正文**:

{issue_body}

---
{SYSTEM_PROMPT}"""

    options, sdk_logger = prepare_agent_options(
        ClaudeAgentOptions(
            model=model,
            max_turns=max_turns,
            allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
            permission_mode="acceptEdits",
            skills="all",
            cwd=project_root,
        ),
        agent_name="implement",
    )
    sdk_logger.log_start(
        model=model,
        max_turns=max_turns,
        base_url=options.env.get("ANTHROPIC_BASE_URL"),
        cwd=str(project_root),
    )

    result_text = ""
    structured: ImplementResult | None = None

    try:
        async for message in query(prompt=prompt, options=options):
            sdk_logger.handle_message(message, echo_assistant_text=False)
            result_text = append_assistant_text(result_text, message)

            # 尝试解析中间结果（Agent 可能分多次输出）
            parsed = _parse_result(result_text)
            if parsed and not structured:
                structured = parsed
    finally:
        sdk_logger.log_completion()

    # 最终解析
    if structured is None:
        structured = _parse_result(result_text)

    if structured is None:
        structured = ImplementResult(
            branch_name="",
            summary="实现失败或超时",
            files_changed=[],
            pr_url=None,
            ready_for_review=False,
        )

    return structured
