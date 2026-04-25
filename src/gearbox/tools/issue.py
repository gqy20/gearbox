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


@tool("create_issue", "根据对比结果生成多个改进 Issue", {"comparison": dict, "gap_count": int})
async def create_issue(args: dict[str, Any]) -> dict[str, Any]:
    """
    兼容旧测试和调用方的简化 Issue 生成接口。

    当前实现基于 gap_count 返回占位 Issue 列表，后续可替换为
    基于 comparison 证据的真实优先级排序与内容生成逻辑。
    """
    gap_count = max(int(args.get("gap_count", 1)), 0)

    issues = []
    for index in range(gap_count):
        priority = "high" if index == 0 else "medium"
        issues.append(
            {
                "title": f"补齐关键能力缺口 {index + 1}",
                "body": (
                    "## 问题描述\n\n"
                    "当前仓库与对标项目相比存在待补齐的能力缺口。\n\n"
                    "## 解决方案\n\n"
                    "1. 确认缺失能力及范围\n"
                    "2. 参考对标项目补齐实现\n"
                    "3. 增加验证与文档\n\n"
                    "## 预期收益\n\n"
                    "- 降低与对标项目的差距\n"
                    "- 提升项目可维护性与可用性"
                ),
                "labels": f"{priority},enhancement",
            }
        )

    return {
        "content": [
            {
                "type": "text",
                "text": f"生成 {len(issues)} 个改进 Issue",
            }
        ],
        "structured_output": issues,
    }
