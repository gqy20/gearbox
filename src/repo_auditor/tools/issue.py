"""Issue 生成工具 - 基于对比矩阵生成改进建议"""

from typing import Any

from claude_agent_sdk import tool


@tool("create_issue", "生成改进Issue", {"comparison": dict, "gap_count": int})
async def create_issue(args: dict[str, Any]) -> dict[str, Any]:
    """
    基于对比矩阵生成带证据的高质量改进建议 Issue。

    每个 Issue 应包含：
    1. 清晰的标题
    2. 问题描述和影响
    3. 对标项目的参考（带链接）
    4. 具体的实施路线
    5. 预期收益
    """
    _comparison = args["comparison"]
    gap_count = args.get("gap_count", 5)

    # TODO: 实现实际的 Issue 生成逻辑
    # 1. 分析差距（target 为 false 但 benchmark 为 true 的维度）
    # 2. 按优先级排序
    # 3. 生成具体的 Issue 草稿

    issues = [
        {
            "title": f"添加 {capability} 能力",
            "body": f"""## 问题描述

当前仓库缺少 `{capability}` 能力。

## 对标参考

- benchmark/repo1: 有完善的实现
- benchmark/repo2: 实现了类似功能

## 实施方案

1. 分析对标项目的实现方式
2. 适配到当前项目
3. 添加测试和文档

## 预期收益

- 提升代码质量
- 改善开发体验
""",
            "labels": ["enhancement", capability.replace("has_", "")],
            "priority": "medium",
        }
        for capability in ["has_ci", "has_lint", "has_coverage"][:gap_count]
    ]

    return {
        "content": [
            {
                "type": "text",
                "text": f"生成了 {len(issues)} 个改进建议:\n\n"
                + "\n\n".join(f"### {i['title']}\n{i['body'][:200]}..." for i in issues),
            }
        ],
        "structured_output": issues,
    }
