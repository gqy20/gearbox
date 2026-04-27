"""Audit Agent — 仓库审计，生成改进建议"""

import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click

from gearbox.core.gh import IssueSummary

# =============================================================================
# Schema 定义
# =============================================================================

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repo": {"type": "string", "description": "仓库标识"},
        "profile": {
            "type": "object",
            "description": "仓库 Profile",
        },
        "comparison_markdown": {
            "type": "string",
            "description": "仓库与对标项目的 Markdown 对比分析",
        },
        "benchmarks": {
            "type": "array",
            "items": {"type": "string"},
            "description": "对标仓库列表",
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "labels": {"type": "string"},
                },
                "required": ["title", "body", "labels"],
            },
            "description": "改进建议列表",
        },
        "failure_reason": {
            "type": ["string", "null"],
            "description": "无法完成审计时的原因说明",
        },
    },
    "required": ["repo", "profile", "comparison_markdown", "issues"],
}

OUTPUT_FILES = ("profile.json", "comparison.md", "issues.json")

# Benchmark 缓存
_BENCHMARK_CACHE_DIR = Path.home() / ".cache" / "gearbox" / "benchmarks"

# =============================================================================
# 数据模型
# =============================================================================


@dataclass
class Issue:
    title: str
    body: str
    labels: str


@dataclass
class AuditResult:
    """Audit Agent 结果"""

    repo: str
    profile: dict[str, Any] = field(default_factory=dict)
    comparison_markdown: str = ""
    benchmarks: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    cost: float | None = None
    failure_reason: str | None = None


def _write_audit_outputs(result: AuditResult, output_dir: Path) -> None:
    """由宿主进程统一写出 audit 产物文件。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    issues_payload = {
        "repo": result.repo,
        "profile": result.profile,
        "benchmarks": result.benchmarks,
        "issues": [
            {
                "repo": result.repo,
                "title": issue.title,
                "body": issue.body,
                "labels": issue.labels,
            }
            for issue in result.issues
        ],
    }

    (output_dir / "issues.json").write_text(
        json.dumps(issues_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "profile.json").write_text(
        json.dumps(result.profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    comparison_markdown = result.comparison_markdown.strip()
    if not comparison_markdown:
        comparison_markdown = "# Audit Comparison\n\nNo comparison markdown returned."
    (output_dir / "comparison.md").write_text(comparison_markdown + "\n", encoding="utf-8")


def _get_cached_benchmarks(repo: str, language: str | None = None) -> list[str] | None:
    """获取缓存的对标仓库列表"""
    cache_file = _BENCHMARK_CACHE_DIR / f"{repo.replace('/', '_')}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            # 缓存有效期 7 天
            if time.time() - data.get("cached_at", 0) < 7 * 24 * 3600:
                return data.get("benchmarks")  # type: ignore[return-value, no-any-return]
        except Exception:
            pass
    return None


def _cache_benchmarks(repo: str, benchmarks: list[str]) -> None:
    """缓存对标仓库列表"""
    cache_file = _BENCHMARK_CACHE_DIR / f"{repo.replace('/', '_')}.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "benchmarks": benchmarks,
                "cached_at": time.time(),
            }
        )
    )


def _clone_repository(repo: str) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    """将目标仓库克隆到临时目录，供扫描和 Agent 分析统一使用。"""
    temp_dir = tempfile.TemporaryDirectory(prefix="gearbox-audit-")
    clone_root = Path(temp_dir.name) / "repo"

    if Path(repo).exists():
        source = str(Path(repo).resolve())
        cmd = ["git", "clone", "--depth", "1", source, str(clone_root)]
    else:
        cmd = ["gh", "repo", "clone", repo, str(clone_root), "--", "--depth", "1"]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        temp_dir.cleanup()
        stderr = result.stderr.strip() or result.stdout.strip() or "unknown clone error"
        raise RuntimeError(f"clone failed for {repo}: {stderr}")

    return clone_root, temp_dir


def load_audit_result(output_dir: Path) -> AuditResult:
    """从 audit 产物目录恢复 AuditResult。"""
    issues_path = output_dir / "issues.json"
    comparison_path = output_dir / "comparison.md"

    if not issues_path.exists():
        raise FileNotFoundError(f"Missing audit artifact: {issues_path}")

    issues_payload = json.loads(issues_path.read_text(encoding="utf-8"))
    comparison_markdown = (
        comparison_path.read_text(encoding="utf-8") if comparison_path.exists() else ""
    )

    return AuditResult(
        repo=issues_payload.get("repo", ""),
        profile=issues_payload.get("profile", {}),
        comparison_markdown=comparison_markdown,
        benchmarks=issues_payload.get("benchmarks", []),
        issues=[
            Issue(
                title=item.get("title", ""),
                body=item.get("body", ""),
                labels=item.get("labels", "enhancement"),
            )
            for item in issues_payload.get("issues", [])
        ],
    )


# =============================================================================
# Prompt
# =============================================================================

SYSTEM_PROMPT = """你是 Gearbox，一个专业的代码库审计专家。

## 目标

分析目标仓库，发现与业界标杆的差距，生成可执行的改进建议。

## 工作流程

1. **已预扫描**: 如果提供了扫描结果摘要，说明仓库已经过静态分析工具扫描
2. 用 `gh repo view` 查看远程仓库信息（仅远程仓库需要）
3. 用 `gh search repos` 发现对标项目（如果未提供 benchmarks）
4. **必须**使用 ctx7 查询相关技术栈的官方文档（`npx ctx7 docs <library-id> <query>`），确保建议基于最新实践
5. 自主分析并生成结构化报告

## 重要: 避免重复搜索

- **Benchmark 搜索**: 如果已提供 benchmarks 列表，直接使用，不重复搜索
- **代码扫描**: 已通过 cloc/semgrep/trivy/deptry 预扫描，不要重复执行
- **依赖分析**: 已通过 deptry/govulncheck 预扫描，不要重复执行

## 扫描结果

仓库已经过静态分析（cloc/semgrep/trivy/deptry），结果以 JSON 格式提供在下方。请直接使用这些数据生成改进建议，不要重复执行扫描。

## 输出格式

请只返回符合 JSON Schema 的结构化结果，不要自己写文件。宿主进程会把你的结果写成：
- `profile.json`
- `comparison.md`
- `issues.json`

## 质量要求

- 最多 3 个 Issues
- 每个 Issue ≤1000 字符，≤3 个要点
- 标签包含优先级（critical/high/medium/low）
- 精选最重要的改进项
- 不要尝试创建 GitHub Issue
- `comparison_markdown` 必须是完整 Markdown
- `issues` 里的每条记录都要可直接写入 `issues.json`
- 如果无法完成审计，在 `failure_reason` 中说明原因

## 已有 Issue 指引

仓库中已存在以下 open Issues（下方提供）。**对于这些已有 Issue，你的职责是：**
- **不要深入分析**其根本原因或解决方案（已有 owner 处理）
- **只需标注它们存在**，在对比分析中提及差距已记录
- **聚焦发现全新问题**：寻找扫描结果中暗示但未被这些已有 Issue 覆盖的盲区

换句话说：你应该发现"还有什么东西没被人注意到"，而不是重复已有的发现。"""


async def run_audit(
    repo: str,
    benchmarks: list[str] | None = None,
    output_dir: str = "./output",
    *,
    model: str | None = None,
    max_turns: int = 20,
    system_prompt: str | None = None,
    enable_prescan: bool = True,
) -> AuditResult:
    """
    执行仓库审计。

    Args:
        repo: 仓库标识 (owner/repo 或本地 git 仓库路径)
        benchmarks: 指定的对标仓库列表
        output_dir: 输出目录
        model: 使用的模型
        max_turns: 最大对话轮次
        system_prompt: 自定义 System Prompt（可选，默认使用内置）
        enable_prescan: 是否启用预扫描（默认 True）

    Returns:
        AuditResult 结构
    """
    from claude_agent_sdk import (
        ClaudeAgentOptions,
        query,
    )

    from gearbox.agents.shared.runtime import prepare_agent_options
    from gearbox.agents.shared.scanner import (
        format_scan_summary,
        scan_repository,
    )
    from gearbox.agents.shared.structured import (
        json_schema_output,
        parse_structured_output,
    )
    from gearbox.config import get_anthropic_base_url, get_anthropic_model

    resolved_model = model or get_anthropic_model()
    resolved_prompt = system_prompt if system_prompt else SYSTEM_PROMPT

    clone_root: Path | None = None
    clone_dir: tempfile.TemporaryDirectory[str] | None = None
    scan_result = None
    scan_summary = ""

    try:
        click.echo(f"📥 克隆目标仓库: {repo}")
        clone_root, clone_dir = _clone_repository(repo)
        click.echo(f"✅ 仓库已克隆到: {clone_root}")

        if enable_prescan:
            try:
                click.echo("🔍 执行静态分析扫描...")
                scan_result = scan_repository(clone_root)
                scan_summary = format_scan_summary(scan_result)
                click.echo("✅ 扫描完成")

                click.echo(
                    f"📊 扫描结果: {scan_result.total_files} 文件, "
                    f"{scan_result.total_lines} 行代码, "
                    f"{scan_result.project_type} 项目"
                )
                click.echo(
                    "🧪 工具状态: "
                    f"cloc={scan_result.tool_statuses.get('cloc', 'unknown')}, "
                    f"deptry={scan_result.tool_statuses.get('deptry', 'unknown')}, "
                    f"semgrep={scan_result.tool_statuses.get('semgrep', 'unknown')}, "
                    f"trivy={scan_result.tool_statuses.get('trivy', 'unknown')}, "
                    f"govulncheck={scan_result.tool_statuses.get('govulncheck', 'unknown')}"
                )
                click.echo(
                    f"📦 依赖问题: {len(scan_result.deptry_issues)} | "
                    f"⚠️ 代码问题: {len(scan_result.semgrep_findings)} | "
                    f"🔴 漏洞: {len(scan_result.trivy_vulnerabilities)} | "
                    f"🛡️ Go 漏洞: {len(scan_result.govulncheck_vulns)}"
                )
            except Exception as e:
                click.echo(f"⚠️ 扫描失败: {e}", err=True)

        if not benchmarks:
            lang = scan_result.project_type if scan_result else None
            benchmarks = _get_cached_benchmarks(repo, lang)
            if benchmarks:
                click.echo(f"📦 使用缓存的对标仓库: {len(benchmarks)} 个")

        existing_issues: list[IssueSummary] = []
        existing_issues_str = ""
        # 仅远程仓库需要拉取已有 Issues，本地路径不具备 GitHub 上下文
        if "/" in repo:
            from gearbox.agents.shared.prompt_helpers import format_issues_summary
            from gearbox.core.gh import list_open_issues

            existing_issues = list_open_issues(repo, limit=200)
            if existing_issues:
                click.echo(f"📋 已有 open Issues: {len(existing_issues)} 个")
                existing_issues_str = format_issues_summary(
                    existing_issues, header="仓库已有 Open Issues"
                )

        prompt_parts = []
        if scan_summary and enable_prescan:
            prompt_parts.append(f"```json\n{scan_summary}\n```")
        prompt_parts.append(existing_issues_str)

        if prompt_parts:
            resolved_prompt = f"""{resolved_prompt}

{"".join(prompt_parts)}"""

        options, sdk_logger = prepare_agent_options(
            ClaudeAgentOptions(
                model=resolved_model,
                system_prompt=resolved_prompt,
                max_turns=max_turns,
                output_format=json_schema_output(OUTPUT_SCHEMA),
                skills="all",
                cwd=clone_root,
            ),
            agent_name="audit",
        )
        sdk_logger.log_start(
            model=resolved_model,
            max_turns=max_turns,
            base_url=get_anthropic_base_url(),
            cwd=str(clone_root),
        )

        if benchmarks:
            benchmark_str = ", ".join(benchmarks)
            prompt = f"""请审计仓库: {repo}

本地分析目录: {clone_root}

对标项目: {benchmark_str}

输出目录: {output_dir}

请返回完整的结构化审计结果。"""
        else:
            prompt = f"""请审计仓库: {repo}

本地分析目录: {clone_root}

请自主发现对标项目（约 5 个），然后进行对比分析。

输出目录: {output_dir}

请返回完整的结构化审计结果。"""

        structured: AuditResult | None = None
        total_cost: float | None = None

        try:
            async for message in query(prompt=prompt, options=options):
                sdk_logger.handle_message(message, echo_assistant_text=False)
                total_cost = getattr(message, "total_cost_usd", total_cost)
                if structured is None:
                    parsed = parse_structured_output(
                        message,
                        lambda data: AuditResult(
                            repo=data.get("repo", repo),
                            profile=data.get("profile", {}),
                            comparison_markdown=data.get("comparison_markdown", ""),
                            benchmarks=data.get("benchmarks", benchmarks or []),
                            issues=[
                                Issue(
                                    title=item.get("title", ""),
                                    body=item.get("body", ""),
                                    labels=item.get("labels", "enhancement"),
                                )
                                for item in data.get("issues", [])
                            ],
                            failure_reason=data.get("failure_reason"),
                        ),
                    )
                    if parsed is not None:
                        structured = parsed
                        break
        finally:
            sdk_logger.log_completion()

        if structured is None:
            raise RuntimeError("Audit agent did not return structured output")
        structured.cost = total_cost

        if structured.benchmarks and not benchmarks:
            _cache_benchmarks(repo, structured.benchmarks)
            click.echo(f"💾 已缓存 {len(structured.benchmarks)} 个对标仓库")

        _write_audit_outputs(structured, Path(output_dir))
        return structured
    finally:
        if clone_dir is not None:
            clone_dir.cleanup()


def promote_audit_outputs(source_dir: Path, target_dir: Path) -> None:
    """将胜出实例的产物提升到最终输出目录。"""
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename in OUTPUT_FILES:
        source = source_dir / filename
        if source.exists():
            shutil.copy2(source, target_dir / filename)
