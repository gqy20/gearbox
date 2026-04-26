"""Review Agent — PR 自动 Code Review"""

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
        "verdict": {
            "type": "string",
            "enum": ["LGTM", "Request Changes", "Comment Only"],
            "description": "审查结论",
        },
        "score": {
            "type": "integer",
            "minimum": 0,
            "maximum": 10,
            "description": "代码质量评分 0-10",
        },
        "summary": {
            "type": "string",
            "description": "总体评价摘要",
        },
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "body": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["blocker", "warning", "info"],
                    },
                },
                "required": ["file", "body", "severity"],
            },
            "description": "具体审查意见列表",
        },
    },
    "required": ["verdict", "score", "summary", "comments"],
}

# =============================================================================
# 数据模型
# =============================================================================


@dataclass
class ReviewComment:
    """单条审查意见"""

    file: str
    line: int | None
    body: str
    severity: str  # blocker/warning/info


@dataclass
class ReviewResult:
    """Review Agent 结果"""

    verdict: str
    score: int
    summary: str
    comments: list[ReviewComment]


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
# 结果解析
# =============================================================================


def _parse_result(text: str) -> ReviewResult | None:
    """从 Agent 输出解析 ReviewResult"""
    try:
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group(1))
        comments = [
            ReviewComment(
                file=c.get("file", ""),
                line=c.get("line"),
                body=c.get("body", ""),
                severity=c.get("severity", "info"),
            )
            for c in data.get("comments", [])
        ]
        return ReviewResult(
            verdict=data.get("verdict", "Comment Only"),
            score=int(data.get("score", 5)),
            summary=data.get("summary", ""),
            comments=comments,
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


# =============================================================================
# Prompt
# =============================================================================

SYSTEM_PROMPT = """你是资深 Code Review 专家。请对 PR 进行全面审查。

## 审查维度

1. **逻辑正确性** — 是否有 bug、边界情况未处理
2. **安全漏洞** — SQL注入、XSS、敏感信息泄露等
3. **性能问题** — N+1查询、不必要的重复计算等
4. **测试覆盖** — 核心逻辑是否有对应测试
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

请严格按以下 JSON 格式输出:

```json
{
  "verdict": "Request Changes",
  "score": 6,
  "summary": "逻辑正确但存在安全问题和测试缺失",
  "comments": [
    {
      "file": "src/auth.py",
      "line": 42,
      "body": "此处直接拼接 SQL，存在注入风险",
      "severity": "blocker"
    }
  ]
}
```

## 约束

- blocker 意见必须修复才能 LGTM
- comments 最少 1 条，最多 20 条
- 优先关注安全和逻辑问题"""


async def run_review(
    repo: str,
    pr_number: int,
    *,
    model: str = "claude-sonnet-4-6",
    max_turns: int = 10,
) -> ReviewResult:
    """
    执行 PR Code Review。

    Args:
        repo: 仓库标识
        pr_number: PR 编号
        model: 使用的模型
        max_turns: 最大对话轮次

    Returns:
        ReviewResult 结构
    """
    from pathlib import Path

    from claude_agent_sdk import ClaudeAgentOptions, query

    project_root = Path(__file__).parent.parent.parent
    pr_info = _gh_pr_view(repo, pr_number)
    diff_text = _gh_pr_diff(repo, pr_number)

    prompt = f"""## PR 信息

**仓库**: {repo}
**编号**: #{pr_number}
**标题**: {pr_info["title"]}
**分支**: {pr_info["headRefName"]} → {pr_info["baseRefName"]}

**Diff**:

{diff_text[:8000]}

---
{SYSTEM_PROMPT}"""

    options = ClaudeAgentOptions(
        model=model,
        max_turns=max_turns,
        allowed_tools=["Read", "Grep", "Glob"],
        skills="all",
        cwd=project_root,
    )

    result_text = ""
    structured: ReviewResult | None = None

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
        structured = ReviewResult(
            verdict="Comment Only",
            score=5,
            summary="Review completed with parsing issues",
            comments=[],
        )

    return structured
