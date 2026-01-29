"""对比矩阵工具 - 生成目标仓库与对标仓库的能力对比"""

from typing import Any

from claude_agent_sdk import tool

# 15 个能力维度
CAPABILITY_DIMENSIONS = [
    "has_ci",  # 是否有 CI/CD
    "has_lint",  # 是否有代码检查
    "has_type_check",  # 是否有类型检查
    "has_coverage",  # 是否有测试覆盖
    "has_dependabot",  # 是否有依赖更新
    "has_plugin_system",  # 是否有插件系统
    "has_config_schema",  # 是否有配置 Schema
    "has_error_handling",  # 是否有统一错误处理
    "has_logging",  # 是否有日志系统
    "has_tests",  # 是否有测试套件
    "has_docker",  # 是否有 Docker 支持
    "has_documentation",  # 是否有文档
    "has_changelog",  # 是否有变更日志
    "has_contributing_guide",  # 是否有贡献指南
    "has_code_of_conduct",  # 是否有行为准则
]


@tool("create_comparison", "创建对比矩阵", {"target_profile": dict, "benchmarks": list})
async def create_comparison(args: dict[str, Any]) -> dict[str, Any]:
    """
    生成目标仓库与对标仓库的 15 个能力维度对比矩阵。

    每个维度需要提供：
    - 目标仓库状态
    - 对标仓库状态
    - 证据来源
    """
    _target_profile = args["target_profile"]
    benchmarks = args["benchmarks"]

    # TODO: 实现实际的对比逻辑
    # 1. 分析目标仓库的每个维度
    # 2. 分析对标仓库的每个维度
    # 3. 生成对比矩阵

    matrix = {
        "target": {dim: False for dim in CAPABILITY_DIMENSIONS},
        "benchmarks": [
            {
                "name": b["name"],
                "capabilities": {dim: True for dim in CAPABILITY_DIMENSIONS},
            }
            for b in benchmarks
        ],
    }

    # 格式化对比表格
    table = "| 能力项 | 目标 | " + " | ".join(b["name"] for b in benchmarks) + " |\n"
    table += "|" + "---|" * (len(benchmarks) + 2) + "\n"

    for dim in CAPABILITY_DIMENSIONS:
        target_status = "✅" if matrix["target"][dim] else "❌"
        benchmark_statuses = " | ".join(
            "✅" if b["capabilities"][dim] else "❌" for b in matrix["benchmarks"]
        )
        table += f"| {dim} | {target_status} | {benchmark_statuses} |\n"

    return {
        "content": [{"type": "text", "text": f"## 对比矩阵\n\n{table}"}],
        "structured_output": matrix,
    }
