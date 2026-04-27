"""Implement Agent — Issue → 分支/PR"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

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
            "type": ["string", "null"],
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


def write_implement_result(result: ImplementResult, output_path: Path) -> None:
    """写出 Implement 结果到 artifact 文件"""
    from gearbox.agents.shared.artifacts import write_json_artifact

    write_json_artifact(output_path, result)


def load_implement_result(path: Path) -> ImplementResult:
    """从 artifact 文件加载 Implement 结果"""
    from gearbox.agents.shared.artifacts import read_json_artifact

    data = read_json_artifact(path)
    return ImplementResult(
        branch_name=cast(str, data.get("branch_name", "")),
        summary=cast(str, data.get("summary", "")),
        files_changed=cast(list[str], data.get("files_changed", [])),
        pr_url=cast(str | None, data.get("pr_url")),
        ready_for_review=cast(bool, data.get("ready_for_review", False)),
    )


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
        "{title:.title,body:.body,labels:[.labels[].name]}",
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
# Prompt
# =============================================================================

SYSTEM_PROMPT = """你是代码实现专家。请根据 Issue 描述实现代码变更。

## 工作流程（必须遵循 TDD）

1. 阅读 Issue 了解需求
2. 分析代码库结构，找到相关文件
3. **先写测试**：为要实现的功能写一个会失败的测试，运行它确认失败
4. **实现功能**：编写代码让测试通过
5. **运行完整检查**：`uv run pytest` 和 `uv run ruff check src`
6. 返回结构化实现结果

## 强制约束

- `ready_for_review=true` 的前提是：测试必须全部通过，lint 必须干净
- 如果测试无法编写（例如被测代码是纯脚本），跳过此步骤但需在 summary 中说明原因
- **不要**先实现后补测试——顺序必须是：测试（失败）→ 实现（通过）→ 检查

## 安全约束

- 只修改当前工作区文件，**不要**执行 `git commit`、`git push`、`gh pr create`
- 外层 Gearbox 编排器会负责创建分支、提交、推送和 PR
- branch_name 只需要给出建议分支名，必须使用 `feat/issue-{number}` 或
  `gearbox/implement-{number}` 前缀

## 输出格式

请直接返回符合 JSON Schema 的结构化结果，不要输出 Markdown 代码块。

pr_url 请返回 null，外层编排器创建 PR 后会回填。

## 约束

- branch_name 必须以 feat/ 或 gearbox/ 开头
- files_changed 列出所有修改文件
- ready_for_review=true 表示工作区修改完成并已通过检查"""


async def run_implement(
    repo: str,
    issue_number: int,
    *,
    model: str = "claude-sonnet-4-6",
    base_branch: str = "main",
    max_turns: int = 80,
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

    from gearbox.agents.shared.runtime import prepare_agent_options
    from gearbox.agents.shared.structured import json_schema_output, parse_structured_output

    project_root = Path.cwd()
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
            output_format=json_schema_output(OUTPUT_SCHEMA),
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

    structured: ImplementResult | None = None

    try:
        async for message in query(prompt=prompt, options=options):
            sdk_logger.handle_message(message, echo_assistant_text=False)
            if structured is None:
                parsed = parse_structured_output(
                    message,
                    lambda data: ImplementResult(
                        branch_name=data.get("branch_name", ""),
                        summary=data.get("summary", ""),
                        files_changed=data.get("files_changed", []),
                        pr_url=data.get("pr_url"),
                        ready_for_review=data.get("ready_for_review", False),
                    ),
                )
                if parsed is not None:
                    structured = parsed
                    break
    finally:
        sdk_logger.log_completion()

    if structured is None:
        raise RuntimeError("Implement agent did not return structured output")

    return structured
