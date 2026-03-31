"""对比矩阵工具 - 生成目标仓库与对标仓库的能力对比"""

from typing import Any

from claude_agent_sdk import tool

# 15 个能力维度
CAPABILITY_DIMENSIONS = [
    "has_ci",
    "has_lint",
    "has_type_check",
    "has_coverage",
    "has_dependabot",
    "has_plugin_system",
    "has_config_schema",
    "has_error_handling",
    "has_logging",
    "has_tests",
    "has_docker",
    "has_documentation",
    "has_changelog",
    "has_contributing_guide",
    "has_code_of_conduct",
]


def _get_repo_name(profile: dict[str, Any], index: int) -> str:
    return profile.get("repo") or profile.get("name") or f"benchmark-{index}"


def _dimension_value(profile: dict[str, Any], dimension: str) -> bool:
    if dimension == "has_ci":
        return bool(profile.get("build", {}).get("ci_file"))
    if dimension == "has_lint":
        return bool(profile.get("quality", {}).get("linters"))
    if dimension == "has_type_check":
        return bool(profile.get("quality", {}).get("type_checker"))
    if dimension == "has_coverage":
        return bool(profile.get("quality", {}).get("coverage"))
    if dimension == "has_dependabot":
        return bool(profile.get("security", {}).get("dependabot"))
    if dimension == "has_plugin_system":
        return bool(profile.get("extensibility", {}).get("plugins"))
    if dimension == "has_config_schema":
        return bool(profile.get("extensibility", {}).get("config_schema"))
    if dimension == "has_error_handling":
        return bool(profile.get("quality", {}).get("has_error_handling"))
    if dimension == "has_logging":
        return bool(profile.get("quality", {}).get("has_logging"))
    if dimension == "has_tests":
        return bool(profile.get("quality", {}).get("test_framework"))
    if dimension == "has_docker":
        return bool(profile.get("platform", {}).get("has_docker"))
    if dimension == "has_documentation":
        return bool(profile.get("docs", {}).get("has_documentation"))
    if dimension == "has_changelog":
        return bool(profile.get("docs", {}).get("has_changelog"))
    if dimension == "has_contributing_guide":
        return bool(profile.get("community", {}).get("has_contributing_guide"))
    if dimension == "has_code_of_conduct":
        return bool(profile.get("community", {}).get("has_code_of_conduct"))
    return False


def _dimension_evidence(profile: dict[str, Any], dimension: str) -> list[str]:
    if dimension == "has_ci" and profile.get("build", {}).get("ci_file"):
        return [profile["build"]["ci_file"]]
    if dimension == "has_config_schema" and profile.get("extensibility", {}).get("config_schema"):
        return [profile["extensibility"]["config_schema"]]
    if dimension == "has_tests" and profile.get("quality", {}).get("test_framework"):
        return [profile["quality"]["test_framework"]]
    if dimension == "has_lint":
        return list(profile.get("quality", {}).get("linters", []))
    if dimension == "has_type_check" and profile.get("quality", {}).get("type_checker"):
        return [profile["quality"]["type_checker"]]
    return []


def _gap_level(target_value: bool, benchmark_values: list[bool]) -> str:
    if not benchmark_values:
        return "low"

    true_count = sum(1 for value in benchmark_values if value)
    if not target_value and true_count >= max(
        1, len(benchmark_values) // 2 + len(benchmark_values) % 2
    ):
        return "high"
    if target_value and true_count == 0:
        return "low"
    if target_value == all(benchmark_values):
        return "low"
    return "medium"


def _build_dimension(
    target_profile: dict[str, Any], benchmark_profiles: list[dict[str, Any]], dimension: str
) -> dict[str, Any]:
    target_value = _dimension_value(target_profile, dimension)
    benchmark_items = []

    for index, profile in enumerate(benchmark_profiles, start=1):
        benchmark_items.append(
            {
                "repo": _get_repo_name(profile, index),
                "value": _dimension_value(profile, dimension),
                "evidence": _dimension_evidence(profile, dimension),
            }
        )

    gap_level = _gap_level(target_value, [item["value"] for item in benchmark_items])

    return {
        "name": dimension,
        "target": {
            "value": target_value,
            "evidence": _dimension_evidence(target_profile, dimension),
        },
        "benchmarks": benchmark_items,
        "gap_level": gap_level,
    }


def _select_top_gaps(dimensions: list[dict[str, Any]]) -> list[str]:
    ordered = sorted(
        dimensions,
        key=lambda item: (item["gap_level"] != "high", item["gap_level"] != "medium", item["name"]),
    )
    return [item["name"] for item in ordered if item["gap_level"] != "low"][:5]


def _render_table(
    dimensions: list[dict[str, Any]], benchmark_profiles: list[dict[str, Any]]
) -> str:
    headers = [
        "能力项",
        "目标",
        *[
            _get_repo_name(profile, index)
            for index, profile in enumerate(benchmark_profiles, start=1)
        ],
        "差距",
    ]
    table = "| " + " | ".join(headers) + " |\n"
    table += "| " + " | ".join(["---"] * len(headers)) + " |\n"

    for item in dimensions:
        row = [item["name"], "✅" if item["target"]["value"] else "❌"]
        row.extend("✅" if benchmark["value"] else "❌" for benchmark in item["benchmarks"])
        row.append(item["gap_level"])
        table += "| " + " | ".join(row) + " |\n"

    return table


@tool(
    "create_comparison",
    "创建对比矩阵",
    {"target_profile": dict, "benchmark_profiles": list, "benchmarks": list},
)
async def create_comparison(args: dict[str, Any]) -> dict[str, Any]:
    """基于结构化 profile 生成能力对比矩阵。"""
    target_profile = args["target_profile"]
    benchmark_profiles = args.get("benchmark_profiles") or args.get("benchmarks", [])

    dimensions = [
        _build_dimension(target_profile, benchmark_profiles, dimension)
        for dimension in CAPABILITY_DIMENSIONS
    ]
    matrix = {
        "dimensions": dimensions,
        "top_gaps": _select_top_gaps(dimensions),
    }
    table = _render_table(dimensions, benchmark_profiles)

    return {
        "content": [{"type": "text", "text": f"## 对比矩阵\n\n{table}"}],
        "structured_output": matrix,
    }
