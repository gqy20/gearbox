"""CLI 命令定义"""

import click

from .audit import run_audit_sync
from .config import (
    get_config_path,
    get_github_token,
    load_config,
    set_anthropic_api_key,
    set_anthropic_base_url,
    set_anthropic_model,
    set_github_token,
)
from .publish import publish_issues_from_file


@click.group()
@click.version_option(version="0.1.0", prog_name="repo-auditor")
def cli() -> None:
    """Repo Auditor - AI 驱动的仓库审计工具

    通过对标分析，自动发现差距并生成改进建议。
    """
    pass


@cli.command()
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
        repo-auditor audit --repo owner/repo
        repo-auditor audit --repo owner/repo --benchmarks click/click,typer.typer
        repo-auditor audit --repo . --output ./audit-output
    """
    benchmark_list = benchmarks.split(",") if benchmarks else None

    # 检查 API Key
    from repo_auditor.config import get_anthropic_api_key

    if not get_anthropic_api_key():
        click.echo(
            "⚠️  未检测到 ANTHROPIC_AUTH_TOKEN",
            err=True,
        )
        click.echo("请运行: repo-auditor config set anthropic-api-key YOUR_KEY")
        click.echo("或设置环境变量: export ANTHROPIC_AUTH_TOKEN=YOUR_KEY")
        raise click.Abort()

    click.echo(f"🔍 Repo Auditor - 分析仓库: {repo}")
    if benchmark_list:
        click.echo(f"📊 指定对标: {', '.join(benchmark_list)}")

    try:
        result = run_audit_sync(repo, benchmark_list, output)

        click.echo(f"\n✅ 审计完成! 结果保存到: {output}")
        if "cost" in result:
            click.echo(f"💰 API 成本: ${result['cost']:.4f}")

    except Exception as e:
        click.echo(f"❌ 审计失败: {e}", err=True)
        raise click.Abort()


@cli.command("publish-issues")
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
    try:
        result = publish_issues_from_file(input_path=input_path, dry_run=dry_run)
    except Exception as e:
        click.echo(f"❌ 发布失败: {e}", err=True)
        raise click.Abort()

    click.echo(f"处理 Issue 数量: {result['total']}")
    click.echo(f"已创建: {len(result['created'])}")
    click.echo(f"已跳过: {len(result['skipped'])}")
    click.echo(f"失败: {len(result['failed'])}")

    for item in result["created"]:
        click.echo(f"✅ {item}")

    for item in result["skipped"]:
        click.echo(f"⚠️  跳过: {item}")

    for item in result["failed"]:
        click.echo(f"❌ {item}", err=True)

    if result["failed"]:
        raise click.Abort()


@cli.group()
def config() -> None:
    """配置管理 - 设置密钥和选项"""
    pass


@config.command("list")
def config_list() -> None:
    """查看当前配置"""
    cfg = load_config()

    click.echo(f"配置文件: {get_config_path()}")
    click.echo()

    if not cfg:
        click.echo("（空配置）")
        return

    # 隐藏敏感信息
    for key, value in cfg.items():
        if "token" in key.lower() or "key" in key.lower():
            masked = value[:8] + "..." if len(value) > 8 else "***"
            click.echo(f"{key}: {masked}")
        else:
            click.echo(f"{key}: {value}")

    # 显示环境变量
    click.echo()
    click.echo("环境变量:")
    click.echo(f"  GITHUB_TOKEN: {'***已设置***' if get_github_token() else '(未设置)'}")


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """设置配置项

    \b
    可用的 KEY:
      github-token           GitHub Token (用于 gh 命令)
      anthropic-api-key      Anthropic API Key (必需)
      anthropic-base-url     Anthropic Base URL (可选，用于代理)
      anthropic-model        Agent 模型名 (默认: glm-5.1)

    \b
    环境变量（优先级更高）:
      ANTHROPIC_AUTH_TOKEN   API Key (官方推荐)
      ANTHROPIC_BASE_URL     Base URL
      ANTHROPIC_MODEL        Model
      GITHUB_TOKEN           GitHub Token

    \b
    示例:
        repo-auditor config set github-token ghp_xxxxx
        repo-auditor config set anthropic-api-key sk-ant-xxxxx
        repo-auditor config set anthropic-base-url https://api.anthropic.com
        repo-auditor config set anthropic-model glm-5.1
    """
    key_map = {
        "github-token": set_github_token,
        "anthropic-api-key": set_anthropic_api_key,
        "anthropic-base-url": set_anthropic_base_url,
        "anthropic-model": set_anthropic_model,
    }

    if key not in key_map:
        click.echo(f"❌ 未知的配置项: {key}")
        click.echo("\n可用的配置项:")
        for k in key_map:
            click.echo(f"  - {k}")
        raise click.Abort()

    key_map[key](value)
    click.echo(f"✅ 已设置 {key}")

    # 验证
    click.echo("\n当前配置:")
    config_list()


@config.command("path")
def config_path() -> None:
    """显示配置文件路径"""
    click.echo(f"{get_config_path()}")


if __name__ == "__main__":
    cli()
