"""Issue 创建工具 - 实际创建 GitHub Issue"""

import subprocess
from typing import Any

from claude_agent_sdk import tool


@tool(
    "create_github_issue",
    "创建 GitHub Issue",
    {
        "repo": str,
        "title": str,
        "body": str,
        "labels": str,  # 逗号分隔的标签
    },
)
async def create_github_issue(args: dict[str, Any]) -> dict[str, Any]:
    """
    在指定仓库创建一个 GitHub Issue。

    Args:
        repo: 仓库标识 (格式: owner/repo)
        title: Issue 标题
        body: Issue 内容 (支持 Markdown)
        labels: 标签 (逗号分隔，如: "enhancement,documentation")

    Returns:
        创建结果，包含 issue URL 和编号
    """
    repo = args["repo"]
    title = args["title"]
    body = args["body"]
    labels = args.get("labels", "")

    # 构建 gh 命令
    cmd = ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body]

    if labels:
        for label in labels.split(","):
            cmd.extend(["--label", label.strip()])

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )

        # gh issue create 输出格式: https://github.com/owner/repo/issues/123
        issue_url = result.stdout.strip()

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"✅ Issue 创建成功: {issue_url}",
                }
            ],
            "structured_output": {
                "success": True,
                "url": issue_url,
                "repo": repo,
                "title": title,
            },
        }
    except subprocess.CalledProcessError as e:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"❌ 创建 Issue 失败: {e.stderr}",
                }
            ],
            "structured_output": {
                "success": False,
                "error": e.stderr,
            },
        }
