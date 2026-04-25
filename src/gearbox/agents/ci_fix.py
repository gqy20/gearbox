"""CI Fix Agent — CI 失败 → 自动修复分支/PR"""

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
            "description": "修复分支名，格式 gearbox/ci-fix-{run_id}",
        },
        "root_cause": {
            "type": "string",
            "description": "根本原因分析",
        },
        "fix_description": {
            "type": "string",
            "description": "修复方案简述",
        },
        "files_changed": {
            "type": "array",
            "items": {"type": "string"},
            "description": "修改的文件",
        },
        "pr_url": {
            "type": "string",
            "description": "创建的 PR URL，尚未创建时为 null",
        },
        "fixed": {
            "type": "boolean",
            "description": "是否已成功修复并推送",
        },
    },
    "required": ["branch_name", "root_cause", "fix_description", "fixed"],
}

# =============================================================================
# 数据模型
# =============================================================================


@dataclass
class CiFixResult:
    """CI Fix Agent 结果"""

    branch_name: str
    root_cause: str
    fix_description: str
    files_changed: list[str]
    pr_url: str | None
    fixed: bool


# =============================================================================
# GitHub API 辅助
# =============================================================================


def _gh_workflow_run_view(repo: str, run_id: int) -> dict[str, Any]:
    """获取 workflow run 信息"""
    cmd = [
        "gh",
        "api",
        f"/repos/{repo}/actions/runs/{run_id}",
        "--jq",
        "{name:.name,headBranch:.head_branch,headSha:.head_sha,conclusion:.conclusion,status:.status}",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _gh_workflow_logs_url(repo: str, run_id: int) -> str:
    """获取 workflow 日志下载 URL"""
    cmd = [
        "gh",
        "api",
        f"/repos/{repo}/actions/runs/{run_id}/logs",
        "--jq",
        ".[0].url",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _download_and_extract_logs(repo: str, run_id: int) -> str:
    """下载并提取 CI 日志内容"""
    try:
        cmd = [
            "gh",
            "api",
            f"/repos/{repo}/actions/runs/{run_id}/logs",
            "--jq",
            ".[0].url",
        ]
        url = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()
        if not url or url == "null":
            return ""

        log_cmd = ["gh", "api", url]
        log_result = subprocess.run(log_cmd, check=True, capture_output=True, text=True)
        return log_result.stdout[-15000:]  # 截取末尾 15KB
    except subprocess.CalledProcessError:
        return ""


def _get_failing_job(repo: str, run_id: int) -> dict[str, Any]:
    """获取失败的 job 信息"""
    cmd = [
        "gh",
        "api",
        f"/repos/{repo}/actions/runs/{run_id}/jobs",
        "--jq",
        '.jobs[] | select(.conclusion=="failure") | {name:.name,id:.id,htmlUrl:.html_url}',
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            return json.loads(line)
    return {}


# =============================================================================
# 结果解析
# =============================================================================


def _parse_result(text: str) -> CiFixResult | None:
    """从 Agent 输出解析 CiFixResult"""
    try:
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group(1))
        return CiFixResult(
            branch_name=data.get("branch_name", ""),
            root_cause=data.get("root_cause", ""),
            fix_description=data.get("fix_description", ""),
            files_changed=data.get("files_changed", []),
            pr_url=data.get("pr_url"),
            fixed=data.get("fixed", False),
        )
    except (json.JSONDecodeError, KeyError):
        return None


# =============================================================================
# Prompt
# =============================================================================

SYSTEM_PROMPT = """你是 CI 故障排查专家。请分析 CI 失败日志，定位根因并生成修复代码。

## 工作流程

1. 分析 CI 日志，识别失败的步骤和错误信息
2. 定位相关源代码文件
3. 分析根因（版本不兼容/语法错误/配置问题/依赖问题等）
4. 生成修复代码
5. 提交到新分支并创建 PR

## 安全约束

- **防死循环**: 禁止修改 `.github/workflows/` 中的配置文件，只改业务代码
- **分支命名**: 必须使用 `gearbox/ci-fix-{run_id}` 前缀
- **最小修改**: 只改必要文件，不做无关重构
- **不删文件**: 只修复问题，不删除文件

## 输出格式

```json
{
  "branch_name": "gearbox/ci-fix-12345",
  "root_cause": "Python 3.13 与某依赖的 typed_dict 不兼容",
  "fix_description": "将依赖版本从 1.0.0 升级到 1.1.0 修复兼容性问题",
  "files_changed": ["pyproject.toml", "src/utils.py"],
  "pr_url": null,
  "fixed": true
}
```

## 约束

- branch_name 必须以 gearbox/ 开头
- fixed=true 表示已完成推送
- 优先分析最后几条失败日志
- 关注 Python 版本、依赖版本、API 变更等常见问题"""


async def run_ci_fix(
    repo: str,
    run_id: int,
    *,
    model: str = "claude-opus-4-7",
    base_branch: str = "main",
    max_turns: int = 15,
) -> CiFixResult:
    """
    执行 CI 失败修复。

    Args:
        repo: 仓库标识
        run_id: workflow run ID
        model: 使用的模型（建议用 Opus 强推理）
        base_branch: PR 目标分支
        max_turns: 最大对话轮次

    Returns:
        CiFixResult 结构
    """
    from claude_agent_sdk import ClaudeAgentOptions, query

    run_info = _gh_workflow_run_view(repo, run_id)
    failing_job = _get_failing_job(repo, run_id)
    log_text = _download_and_extract_logs(repo, run_id)

    prompt = f"""## CI 失败信息

**仓库**: {repo}
**Run ID**: {run_id}
**Workflow**: {run_info.get("name", "unknown")}
**分支**: {run_info.get("headBranch", "unknown")}
**SHA**: {run_info.get("headSha", "unknown")[:8]}
**失败 Job**: {failing_job.get("name", "unknown")}

## CI 日志（最后 15KB）

{log_text or "(日志获取失败)"}

---
{SYSTEM_PROMPT}"""

    options = ClaudeAgentOptions(
        model=model,
        max_turns=max_turns,
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        permission_mode="acceptEdits",
    )

    result_text = ""
    structured: CiFixResult | None = None

    async for message in query(prompt=prompt, options=options):
        if hasattr(message, "content"):
            for block in message.content:
                if hasattr(block, "text"):
                    result_text += block.text

        parsed = _parse_result(result_text)
        if parsed and not structured:
            structured = parsed

    if structured is None:
        structured = _parse_result(result_text)

    if structured is None:
        structured = CiFixResult(
            branch_name="",
            root_cause="分析失败或超时",
            fix_description="",
            files_changed=[],
            pr_url=None,
            fixed=False,
        )

    return structured
