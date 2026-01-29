"""Issue 生成工具 - 生成 Issue 内容供 workflow 使用"""

from typing import Any

from claude_agent_sdk import tool


@tool(
    "generate_issue_content",
    "生成 Issue 内容模板",
    {
        "title": str,
        "problem": str,
        "evidence": str,
        "solution": str,
        "labels": str,
    },
)
async def generate_issue_content(args: dict[str, Any]) -> dict[str, Any]:
    """
    生成格式化的 Issue 内容（供写入 issues.json 使用）。

    Args:
        title: Issue 标题
        problem: 问题描述
        evidence: 对标参考（带链接）
        solution: 解决方案
        labels: 标签（逗号分隔）

    Returns:
        格式化的 Issue 内容
    """
    title = args["title"]
    problem = args["problem"]
    evidence = args.get("evidence", "")
    solution = args.get("solution", "")
    labels = args.get("labels", "")

    body = f"""## 问题描述

{problem}

"""

    if evidence:
        body += f"""## 对标参考

{evidence}

"""

    body += f"""## 解决方案

{solution}

## 预期收益

- 实施此改进将提升项目质量
- 参考业界最佳实践
"""

    return {
        "content": [
            {
                "type": "text",
                "text": f"生成的 Issue: {title}",
            }
        ],
        "structured_output": {
            "title": title,
            "body": body,
            "labels": labels,
        },
    }
