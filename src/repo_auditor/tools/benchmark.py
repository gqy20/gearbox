"""对标发现工具 - 基于 GitHub 搜索发现相似项目"""

from typing import Any

from claude_agent_sdk import tool


@tool(
    "discover_benchmarks",
    "发现对标项目",
    {"repo_name": str, "top": int, "min_stars": int},
)
async def discover_benchmarks(args: dict[str, Any]) -> dict[str, Any]:
    """
    基于目标仓库的 Topics、语言、依赖发现相似的标杆项目。

    搜索策略：
    1. 使用相同的 Topics 搜索
    2. 按语言筛选
    3. 按 stars 数量排序
    4. 返回相似度评分
    """
    _repo_name = args["repo_name"]
    top = args.get("top", 5)
    min_stars = args.get("min_stars", 100)

    # TODO: 使用 GitHub MCP 工具实现实际搜索
    # 1. 获取目标仓库的 topics 和 language
    # 2. 搜索相似项目
    # 3. 计算相似度评分

    benchmarks = [
        {
            "name": f"example/benchmark-{i}",
            "stars": min_stars * (i + 1),
            "similarity_score": 0.9 - (i * 0.1),
            "match_reasons": ["相同的 topics", "相同的主语言"],
        }
        for i in range(top)
    ]

    return {
        "content": [
            {
                "type": "text",
                "text": f"发现 {len(benchmarks)} 个对标项目:\n\n"
                + "\n".join(
                    f"- {b['name']} (⭐ {b['stars']}, 相似度: {b['similarity_score']})"
                    for b in benchmarks
                ),
            }
        ],
        "structured_output": benchmarks,
    }
