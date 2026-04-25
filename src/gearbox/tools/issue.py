"""Issue 生成工具 - 基于对比结果生成改进建议"""

from typing import Any

from claude_agent_sdk import tool

# 维度名 → (中文描述, 解决方案要点, 标签)
GAP_META = {
    "has_ci": (
        "CI/CD 流水线",
        "添加 .github/workflows/ci.yml，使用 GitHub Actions 配置构建和测试",
        "ci,enhancement",
    ),
    "has_lint": (
        "代码规范检查",
        "在 pyproject.toml 中配置 ruff 并添加到 CI 流程",
        "linting,enhancement",
    ),
    "has_type_check": (
        "类型检查",
        "在 pyproject.toml 中配置 mypy，添加 --strict 参数并在 CI 中运行",
        "type-safety,enhancement",
    ),
    "has_coverage": (
        "测试覆盖率",
        "添加 .coveragerc 配置文件，在 CI 中集成 coverage 报告并设置最低阈值",
        "testing,enhancement",
    ),
    "has_dependabot": (
        "依赖自动更新",
        "添加 .github/dependabot.yml 配置文件，启用安全更新和版本更新",
        "security,enhancement",
    ),
    "has_plugin_system": (
        "插件系统",
        "参考对标项目设计插件架构，使用 entry_points 暴露插件接口",
        "extensibility,enhancement",
    ),
    "has_config_schema": (
        "配置 schema",
        "在 pyproject.toml 中添加 project.metadata 定义，使用 tomli-w 做配置校验",
        "configuration,enhancement",
    ),
    "has_error_handling": (
        "错误处理",
        "添加统一的异常类层次结构和错误码定义，完善各层错误处理逻辑",
        "reliability,enhancement",
    ),
    "has_logging": (
        "日志记录",
        "在关键路径添加结构化日志，使用 Python logging 模块配置多级别输出",
        "observability,enhancement",
    ),
    "has_tests": (
        "测试框架",
        "添加 pytest 配置和测试用例，覆盖核心业务逻辑和边界情况",
        "testing,enhancement",
    ),
    "has_docker": (
        "Docker 支持",
        "添加 Dockerfile 和 .dockerignore，优化镜像大小和多阶段构建",
        "infrastructure,enhancement",
    ),
    "has_documentation": (
        "项目文档",
        "完善 README.md，添加 API 文档和使用示例到 docs/ 目录",
        "documentation,enhancement",
    ),
    "has_changelog": (
        "变更日志",
        "添加 CHANGELOG.md 或使用 auto-changelog 工具管理版本变更记录",
        "documentation,enhancement",
    ),
    "has_contributing_guide": (
        "贡献指南",
        "添加 CONTRIBUTING.md 说明开发流程、代码规范和 PR 提交流程",
        "community,enhancement",
    ),
    "has_code_of_conduct": (
        "行为准则",
        "添加 CODE_OF_CONDUCT.md 遵循社区行为规范",
        "community,enhancement",
    ),
}


def _find_dimension(dimensions: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for dim in dimensions:
        if dim["name"] == name:
            return dim
    return None


def _collect_evidence(dim: dict[str, Any]) -> list[str]:
    """收集对标项目的具体证据（哪些项目有、如何实现的）。"""
    evidence_parts: list[str] = []
    for bench in dim.get("benchmarks", []):
        if bench.get("value") and bench.get("evidence"):
            bench_repo = bench.get("repo", "对标项目")
            for e in bench["evidence"]:
                evidence_parts.append(f"- [{bench_repo}](https://github.com/{bench_repo}) 使用 {e}")
    return evidence_parts


def _gap_to_issue(dim: dict[str, Any], index: int) -> dict[str, Any]:
    """基于单个维度差距生成一条改进建议。"""
    name = dim["name"]
    meta = GAP_META.get(name, (name, "完善相关能力建设", "enhancement"))
    label, solution_fragments, label_str = meta

    evidence_lines = _collect_evidence(dim)
    evidence_block = ""
    if evidence_lines:
        evidence_block = "\n## 对标参考\n\n" + "\n".join(evidence_lines) + "\n"

    # 找出哪些对标项目有该能力（用于 evidence 说明）
    capable = [b["repo"] for b in dim.get("benchmarks", []) if b.get("value")]

    body = f"""## 问题描述

项目缺少 {label}。对标项目 {", ".join(capable) if capable else "主流项目"} 已具备该能力。

## 解决方案

{chr(10).join(f"{i + 1}. {s}" for i, s in enumerate(solution_fragments.split("；")))}

{evidence_block}## 预期收益

- 提升项目可维护性和代码质量
- 与业界最佳实践对齐，降低协作门槛"""

    # 限制 body 长度
    if len(body) > 1000:
        body = body[:997] + "..."

    return {
        "title": f"缺少 {label}",
        "body": body,
        "labels": label_str,
    }


def _build_issues_from_comparison(
    comparison: dict[str, Any], gap_count: int
) -> list[dict[str, Any]]:
    """从 comparison structured_output 生成 issue 列表。"""
    dimensions = comparison.get("dimensions", [])
    top_gaps = comparison.get("top_gaps", [])

    if not top_gaps or not dimensions:
        # 回退：返回占位
        return [
            {
                "title": f"补齐关键能力缺口 {i + 1}",
                "body": "## 问题描述\n\n检测到与对标项目存在能力差距，建议参考对比矩阵补齐。\n\n## 解决方案\n\n1. 查看 comparison.md 了解详细差距\n2. 参考对标项目的具体实现\n3. 逐步补齐缺失能力\n\n## 预期收益\n\n- 提升项目质量\n- 与业界最佳实践对齐",
                "labels": "medium,enhancement",
            }
            for i in range(gap_count)
        ]

    issues = []
    for name in top_gaps[:gap_count]:
        dim = _find_dimension(dimensions, name)
        if dim:
            issues.append(_gap_to_issue(dim, len(issues)))

    # 如果 gap_count > top_gaps 数量，补充占位
    while len(issues) < gap_count:
        idx = len(issues)
        issues.append(
            {
                "title": f"补齐关键能力缺口 {idx + 1}",
                "body": "## 问题描述\n\n检测到与对标项目存在能力差距，建议参考对比矩阵补齐。\n\n## 解决方案\n\n1. 查看 comparison.md 了解详细差距\n2. 参考对标项目的具体实现\n3. 逐步补齐缺失能力\n\n## 预期收益\n\n- 提升项目质量\n- 与业界最佳实践对齐",
                "labels": "low,enhancement",
            }
        )

    return issues


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
    """生成格式化的 Issue 内容（供写入 issues.json 使用）。"""
    title = args["title"]
    problem = args["problem"]
    evidence = args.get("evidence", "")
    solution = args.get("solution", "")
    labels = args.get("labels", "")

    body = f"## 问题描述\n\n{problem}\n\n"
    if evidence:
        body += f"## 对标参考\n\n{evidence}\n\n"
    body += f"## 解决方案\n\n{solution}\n\n## 预期收益\n\n- 实施此改进将提升项目质量\n- 参考业界最佳实践\n"

    return {
        "content": [{"type": "text", "text": f"生成的 Issue: {title}"}],
        "structured_output": {"title": title, "body": body, "labels": labels},
    }


@tool("create_issue", "根据对比结果生成多个改进 Issue", {"comparison": dict, "gap_count": int})
async def create_issue(args: dict[str, Any]) -> dict[str, Any]:
    """
    基于 comparison structured_output 生成改进建议 Issue。

    comparison 格式（来自 create_comparison 工具）:
        {
            "dimensions": [{name, target, benchmarks, gap_level}, ...],
            "top_gaps": ["has_coverage", "has_dependabot", ...]
        }
    """
    comparison = args.get("comparison", {})
    gap_count = max(int(args.get("gap_count", 3)), 1)

    issues = _build_issues_from_comparison(comparison, gap_count)

    return {
        "content": [{"type": "text", "text": f"基于对比矩阵生成 {len(issues)} 条改进建议"}],
        "structured_output": issues,
    }
