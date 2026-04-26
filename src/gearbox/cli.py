"""CLI 命令定义"""

import asyncio
import json
import traceback
from pathlib import Path

import click

from .agents.audit import run_audit
from .agents.implement import run_implement
from .agents.review import run_review
from .agents.triage import run_triage
from .config import (
    AGENT_DEFAULTS,
    get_config_path,
    get_github_token,
    load_config,
    set_anthropic_api_key,
    set_anthropic_base_url,
    set_anthropic_model,
    set_github_token,
    set_provider,
)
from .core import run_parallel
from .core.gh import (
    add_issue_labels,
    build_review_body,
    create_issue,
    finalize_and_create_pr,
    post_issue_comment,
    post_review_comment,
    prepare_working_branch,
    write_outputs,
)


@click.group()
@click.version_option(version="0.1.0", prog_name="gearbox")
def cli() -> None:
    """Gearbox - AI 驱动的仓库自动化飞轮系统"""
    pass


# =============================================================================
# Audit 命令
# =============================================================================


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


# =============================================================================
# Agent 命令
# =============================================================================


def _result_to_github_output(result, output_file: str = "/tmp/github_output") -> None:
    """通用结果转 GitHub Output 文件"""
    data = {}
    for key, value in vars(result).items():
        if isinstance(value, list):
            data[key] = json.dumps(value)
        elif isinstance(value, bool):
            data[key] = str(value).lower()
        elif value is None:
            data[key] = ""
        else:
            data[key] = str(value)
    data["status"] = "success"
    write_outputs(data, output_file)


@cli.group()
def agent() -> None:
    """运行 Agent (Audit/Triage/Review/Implement)"""
    pass


@agent.command()
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--issue", required=True, type=int, help="Issue 编号")
@click.option("--model", default="", help="使用的模型（默认从 provider 配置读取）")
@click.option(
    "--max-turns", default=AGENT_DEFAULTS["max_turns"]["triage"], type=int, help="最大对话轮次"
)
@click.option(
    "--parallel-count",
    default=AGENT_DEFAULTS["parallel_count"],
    type=int,
    help="并行执行次数（1=不并行）",
)
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def triage(
    repo: str,
    issue: int,
    model: str,
    max_turns: int,
    parallel_count: int,
    output: str,
) -> None:
    """运行 Triage Agent - 分析 Issue 并打标签/定优先级"""
    from gearbox.agents.evaluator import run_evaluator
    from gearbox.config import get_anthropic_model

    resolved_model = model or get_anthropic_model()

    if parallel_count > 1:
        # 同一任务并行执行多次
        async def agent_factory(_: str):
            return await run_triage(repo, issue, model=resolved_model, max_turns=max_turns)

        angles = [f"run_{i}" for i in range(parallel_count)]
        all_results = asyncio.run(run_parallel(agent_factory, angles, model=resolved_model))

        if not all_results:
            click.echo("❌ No results from parallel execution")
            return

        evaluation = asyncio.run(
            run_evaluator(
                results=all_results,
                result_type="Triage 分类结果",
                result_names=angles[: len(all_results)],
                model=resolved_model,
            )
        )

        result = (
            all_results[evaluation.winner]
            if evaluation.winner < len(all_results)
            else all_results[0]
        )
        click.echo(f"✅ Triage (parallel): winner={evaluation.winner}, scores={evaluation.scores}")
    else:
        result = asyncio.run(
            run_triage(
                repo,
                issue,
                model=resolved_model,
                max_turns=max_turns,
            )
        )
        click.echo(f"✅ Triage: labels={result.labels}, priority={result.priority}")

    # GitHub 操作
    add_issue_labels(repo, issue, result.labels)
    if result.needs_clarification and result.clarification_question:
        post_issue_comment(repo, issue, f"👋 {result.clarification_question}")
    if result.ready_to_implement:
        post_issue_comment(repo, issue, "✅ 此 Issue 分类完成，标记为 ready-to-implement")

    _result_to_github_output(result, output)


@agent.command()
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--pr", required=True, type=int, help="PR 编号")
@click.option("--model", default="", help="使用的模型（默认从 provider 配置读取）")
@click.option(
    "--max-turns", default=AGENT_DEFAULTS["max_turns"]["review"], type=int, help="最大对话轮次"
)
@click.option(
    "--parallel-count",
    default=AGENT_DEFAULTS["parallel_count"],
    type=int,
    help="并行执行次数（1=不并行）",
)
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def review(
    repo: str, pr: int, model: str, max_turns: int, parallel_count: int, output: str
) -> None:
    """运行 Review Agent - 审查 PR 代码"""
    from gearbox.agents.evaluator import run_evaluator
    from gearbox.config import get_anthropic_model

    resolved_model = model or get_anthropic_model()

    if parallel_count > 1:
        # 同一任务并行执行多次
        async def agent_factory(_: str):
            return await run_review(repo, pr, model=resolved_model, max_turns=max_turns)

        angles = [f"run_{i}" for i in range(parallel_count)]
        all_results = asyncio.run(run_parallel(agent_factory, angles, model=resolved_model))

        if not all_results:
            click.echo("❌ No results from parallel execution")
            return

        evaluation = asyncio.run(
            run_evaluator(
                results=all_results,
                result_type="Review 审查结果",
                result_names=angles[: len(all_results)],
                model=resolved_model,
            )
        )

        result = (
            all_results[evaluation.winner]
            if evaluation.winner < len(all_results)
            else all_results[0]
        )
        click.echo(f"✅ Review (parallel): winner={evaluation.winner}, scores={evaluation.scores}")
    else:
        result = asyncio.run(
            run_review(
                repo,
                pr,
                model=resolved_model,
                max_turns=max_turns,
            )
        )
        click.echo(f"✅ Review: verdict={result.verdict}, score={result.score}")

    # GitHub 操作
    comments = [
        {"file": c.file, "line": c.line, "body": c.body, "severity": c.severity}
        for c in result.comments
    ]
    body = build_review_body(result.verdict, result.score, result.summary, comments)
    event = {"LGTM": "APPROVE", "Request Changes": "REQUEST_CHANGES"}.get(result.verdict, "COMMENT")
    post_review_comment(repo, pr, body, event)

    _result_to_github_output(result, output)
    click.echo(f"✅ Review: verdict={result.verdict}, score={result.score}")


@agent.command()
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--issue", required=True, type=int, help="Issue 编号")
@click.option("--model", default="", help="使用的模型（默认从 provider 配置读取）")
@click.option("--base-branch", default="main", help="PR 目标分支")
@click.option(
    "--max-turns", default=AGENT_DEFAULTS["max_turns"]["implement"], type=int, help="最大对话轮次"
)
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def implement(
    repo: str, issue: int, model: str, base_branch: str, max_turns: int, output: str
) -> None:
    """运行 Implement Agent - 实现 Issue 并创建 PR"""
    from gearbox.config import get_anthropic_model

    resolved_model = model or get_anthropic_model()

    temp_branch = prepare_working_branch(base_branch)

    try:
        result = asyncio.run(
            run_implement(
                repo,
                issue,
                model=resolved_model,
                base_branch=base_branch,
                max_turns=max_turns,
            )
        )

        if result.ready_for_review and result.branch_name:
            commit_msg = f"feat: {result.summary}\n\nCloses #{issue}"
            pr_body = f"## Summary\n\n{result.summary}\n\nCloses #{issue}"
            pr_result = finalize_and_create_pr(
                repo=repo,
                temp_branch=temp_branch,
                final_branch=result.branch_name,
                commit_message=commit_msg,
                pr_title=f"feat(#{issue}): {result.summary}",
                pr_body=pr_body,
                base=base_branch,
            )
            if pr_result.success:
                result.pr_url = pr_result.pr_url
                click.echo(f"✅ PR created: {pr_result.pr_url}")
            else:
                click.echo(f"❌ PR creation failed: {pr_result.error}", err=True)

        _result_to_github_output(result, output)
        click.echo(f"✅ Implement: branch={result.branch_name}, ready={result.ready_for_review}")
    finally:
        pass  # 分支已在 finalize_and_create_pr 中处理


@agent.command(name="audit-repo")
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--benchmarks", default="", help="逗号分隔的对标仓库列表（可选）")
@click.option("--output-dir", default="./output", help="输出目录")
@click.option("--model", default="", help="使用的模型")
@click.option(
    "--max-turns", default=AGENT_DEFAULTS["max_turns"]["audit"], type=int, help="最大对话轮次"
)
@click.option("--system-prompt", default="", help="自定义 System Prompt（可选）")
@click.option(
    "--parallel-count",
    default=AGENT_DEFAULTS["parallel_count"],
    type=int,
    help="并行执行次数（1=不并行）",
)
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def audit_repo(
    repo: str,
    benchmarks: str,
    output_dir: str,
    model: str,
    max_turns: int,
    system_prompt: str,
    parallel_count: int,
    output: str,
) -> None:
    """运行 Audit Agent - 审计仓库生成改进建议"""
    from gearbox.agents.evaluator import run_evaluator

    benchmark_list = benchmarks.split(",") if benchmarks else None
    model_arg = model if model else None
    system_prompt_arg = system_prompt if system_prompt else None

    if parallel_count > 1:
        # 同一任务并行执行多次
        async def agent_factory(_: str):
            return await run_audit(
                repo,
                benchmarks=benchmark_list,
                output_dir=output_dir,
                model=model_arg,
                max_turns=max_turns,
                system_prompt=system_prompt_arg,
            )

        angles = [f"run_{i}" for i in range(parallel_count)]
        all_results = asyncio.run(run_parallel(agent_factory, angles, model=model_arg))

        if not all_results:
            click.echo("❌ No results from parallel execution")
            return

        evaluation = asyncio.run(
            run_evaluator(
                results=all_results,
                result_type="Audit 审计结果",
                result_names=angles[: len(all_results)],
                model=model_arg if model_arg else "claude-sonnet-4-6",
            )
        )

        best_result = (
            all_results[evaluation.winner]
            if evaluation.winner < len(all_results)
            else all_results[0]
        )
        click.echo(
            f"✅ Audit (parallel): {len(best_result.issues)} issues, winner={evaluation.winner}"
        )
        result = best_result
    else:
        result = asyncio.run(
            run_audit(
                repo,
                benchmarks=benchmark_list,
                output_dir=output_dir,
                model=model_arg,
                max_turns=max_turns,
                system_prompt=system_prompt_arg,
            )
        )
        click.echo(f"✅ Audit: {len(result.issues)} issues, cost={result.cost}")

    _result_to_github_output(result, output)


# =============================================================================
# Config 命令
# =============================================================================


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

    for key, value in cfg.items():
        if "token" in key.lower() or "key" in key.lower():
            masked = value[:8] + "..." if len(value) > 8 else "***"
            click.echo(f"{key}: {masked}")
        else:
            click.echo(f"{key}: {value}")

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
      anthropic-api-key      API Key (必需)
      provider               预设 Provider (minimax/glm/anthropic)
      anthropic-base-url     Base URL (provider 预设时会自动设置)
      anthropic-model        模型名 (默认: glm-5.1)

    \b
    Provider 预设 (一键配置 base_url + model):
      minimax                MiniMax API (base_url + MiniMax-M2.7-highspeed)
      glm                    智谱 GLM API (base_url + glm-5v-turbo)
      anthropic              Anthropic API (base_url + claude-sonnet-4-6)

    \b
    示例:
        gearbox config set provider minimax
        gearbox config set anthropic-api-key sk-xxxxx
    """
    key_map = {
        "github-token": set_github_token,
        "anthropic-api-key": set_anthropic_api_key,
        "anthropic-base-url": set_anthropic_base_url,
        "anthropic-model": set_anthropic_model,
        "provider": set_provider,
    }

    if key not in key_map:
        click.echo(f"❌ 未知的配置项: {key}")
        click.echo("\n可用的配置项:")
        for k in key_map:
            click.echo(f"  - {k}")
        raise click.Abort()

    key_map[key](value)
    click.echo(f"✅ 已设置 {key}")

    click.echo("\n当前配置:")
    config_list()


@config.command("path")
def config_path() -> None:
    """显示配置文件路径"""
    click.echo(f"{get_config_path()}")


if __name__ == "__main__":
    cli()
