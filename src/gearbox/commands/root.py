"""Top-level CLI commands."""

import asyncio
import json
import traceback
from pathlib import Path

import click

from gearbox.agents.audit import run_audit
from gearbox.core.gh import create_issue
from gearbox.release import build_marketplace_bundle, release_notes_for_version


@click.command()
@click.option(
    "--repo",
    required=True,
    help="目标仓库 (格式: owner/repo 或本地路径)",
)
@click.option(
    "--benchmarks",
    help="逗号分隔的对标仓库列表 (可选，不指定则自动发现)",
)
@click.option(
    "--output",
    default="./output",
    help="输出目录 (默认: ./output)",
    show_default=True,
)
def audit(repo: str, benchmarks: str | None, output: str) -> None:
    """审计仓库 - AI 自主分析并生成改进建议

    \b
    Claude Agent 会自主完成：
    ✓ 分析仓库结构、配置、依赖
    ✓ 发现相似的对标项目
    ✓ 生成能力对比矩阵
    ✓ 产出带证据的改进 Issue

    \b
    示例:
        gearbox audit --repo owner/repo
        gearbox audit --repo owner/repo --benchmarks click/click,typer.typer
        gearbox audit --repo . --output ./audit-output
    """
    benchmark_list = benchmarks.split(",") if benchmarks else None

    from gearbox.config import get_anthropic_api_key

    if not get_anthropic_api_key():
        click.echo(
            "⚠️  未检测到 ANTHROPIC_AUTH_TOKEN",
            err=True,
        )
        click.echo("请运行: gearbox config set anthropic-api-key YOUR_KEY")
        click.echo("或设置环境变量: export ANTHROPIC_AUTH_TOKEN=YOUR_KEY")
        raise click.Abort()

    click.echo(f"🔍 Gearbox - 分析仓库: {repo}")
    if benchmark_list:
        click.echo(f"📊 指定对标: {', '.join(benchmark_list)}")

    try:
        result = asyncio.run(run_audit(repo, benchmark_list, output))

        click.echo(f"\n✅ 审计完成! 结果保存到: {output}")
        if result.cost:
            click.echo(f"💰 API 成本: ${result.cost:.4f}")
        click.echo(f"📝 生成 {len(result.issues)} 条改进建议")

    except Exception as e:
        click.echo(f"❌ 审计失败: {e}", err=True)
        traceback.print_exc()
        raise click.Abort() from e


@click.command("publish-issues")
@click.option(
    "--input",
    "input_path",
    required=True,
    help="issues.json 文件路径",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="仅校验并打印，不真正创建 GitHub Issues",
)
def publish_issues(input_path: str, dry_run: bool) -> None:
    """根据 issues.json 创建 GitHub Issues。"""
    path = Path(input_path)
    if not path.exists():
        click.echo(f"❌ 文件不存在: {input_path}", err=True)
        raise click.Abort()

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    issues = data.get("issues", [])
    if not isinstance(issues, list):
        click.echo("❌ issues.json 格式错误: 'issues' 必须是数组", err=True)
        raise click.Abort()

    created: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    for index, issue in enumerate(issues, start=1):
        repo = issue.get("repo")
        title = issue.get("title")
        body = issue.get("body")
        labels = issue.get("labels", "")

        if not all([repo, title, body]):
            skipped.append(f"{index}: {title or '(missing title)'}")
            continue

        if dry_run:
            created.append(f"DRY-RUN {repo}#{index}: {title}")
            continue

        label_list = (
            [item.strip() for item in labels.split(",") if item.strip()] if labels else None
        )
        result = create_issue(repo, title, body, label_list)

        if result.success:
            created.append(result.pr_url or f"{repo}#{index}")
        else:
            failed.append(f"{title}: {result.error}")

    click.echo(f"处理 Issue 数量: {len(issues)}")
    click.echo(f"已创建: {len(created)}")
    click.echo(f"已跳过: {len(skipped)}")
    click.echo(f"失败: {len(failed)}")

    for item in created:
        click.echo(f"✅ {item}")

    for item in skipped:
        click.echo(f"⚠️  跳过: {item}")

    for item in failed:
        click.echo(f"❌ {item}", err=True)

    if failed:
        raise click.Abort()


@click.command("package-marketplace")
@click.option(
    "--output-dir",
    default="./dist/gearbox-action",
    show_default=True,
    help="输出 Marketplace 发布产物目录",
)
def package_marketplace(output_dir: str) -> None:
    """导出 Marketplace 发布仓需要的最小目录结构。"""
    bundle_dir = build_marketplace_bundle(Path(output_dir))
    click.echo(f"✅ Marketplace bundle written to: {bundle_dir}")


@click.command("release-notes")
@click.option("--version", required=True, help="版本号，例如 v1.1.2")
@click.option("--output-file", default="", help="可选：写入目标文件")
def release_notes(version: str, output_file: str) -> None:
    """输出指定版本的 CHANGELOG 条目。"""
    notes = release_notes_for_version(version)
    if output_file:
        path = Path(output_file)
        path.write_text(notes, encoding="utf-8")
        click.echo(f"✅ Release notes written to: {path}")
        return

    click.echo(notes, nl=False)
