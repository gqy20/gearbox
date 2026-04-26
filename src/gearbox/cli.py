"""CLI 命令定义"""

import asyncio
import json
import subprocess
import traceback
from pathlib import Path

import click

from .agents.audit import load_audit_result, promote_audit_outputs, run_audit
from .agents.implement import (
    load_implement_result,
    run_implement,
    write_implement_result,
)
from .agents.review import load_review_result, run_review, write_review_result
from .agents.shared.github_output import format_currency, result_to_github_output
from .agents.shared.selection import select_best_result
from .agents.triage import load_triage_result, run_triage, write_triage_result
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
from .core.gh import (
    add_issue_labels,
    build_review_body,
    create_issue,
    create_pr,
    finalize_and_create_pr,
    finalize_and_push,
    post_issue_comment,
    post_review_comment,
    prepare_working_branch,
)
from .release import build_marketplace_bundle, release_notes_for_version


def _candidate_result_files(input_root: Path) -> list[tuple[str, Path]]:
    """Return result.json files from both flat and per-artifact layouts."""
    candidates: list[tuple[str, Path]] = []
    flat_result = input_root / "result.json"
    if flat_result.exists():
        candidates.append((input_root.name, flat_result))

    if input_root.exists():
        for run_dir in sorted(path for path in input_root.iterdir() if path.is_dir()):
            result_path = run_dir / "result.json"
            if result_path.exists():
                candidates.append((run_dir.name, result_path))

    return candidates


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


@cli.command("package-marketplace")
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


@cli.command("release-notes")
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


# =============================================================================
# Agent 命令
# =============================================================================


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
@click.option("--artifact-path", default="", help="可选: 写出结构化结果 artifact")
@click.option(
    "--apply-side-effects/--no-apply-side-effects",
    default=False,
    help="是否应用 GitHub 标签/评论副作用（并行时建议关闭）",
)
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def triage(
    repo: str,
    issue: int,
    model: str,
    max_turns: int,
    artifact_path: str,
    apply_side_effects: bool,
    output: str,
) -> None:
    """运行 Triage Agent - 分析 Issue 并打标签/定优先级"""
    from gearbox.config import get_anthropic_model

    resolved_model = model or get_anthropic_model()

    result = asyncio.run(
        run_triage(
            repo,
            issue,
            model=resolved_model,
            max_turns=max_turns,
        )
    )
    click.echo(f"✅ Triage: labels={result.labels}, priority={result.priority}")

    if artifact_path:
        write_triage_result(result, Path(artifact_path))

    if apply_side_effects:
        label_result = add_issue_labels(repo, issue, result.labels)
        if not label_result.success:
            click.echo(f"⚠️ 添加标签失败: {label_result.url}", err=True)
        if result.needs_clarification and result.clarification_question:
            comment_result = post_issue_comment(repo, issue, f"👋 {result.clarification_question}")
            if not comment_result.success:
                click.echo(f"⚠️ 发布评论失败: {comment_result.url}", err=True)
        if result.ready_to_implement:
            comment_result = post_issue_comment(
                repo, issue, "✅ 此 Issue 分类完成，标记为 ready-to-implement"
            )
            if not comment_result.success:
                click.echo(f"⚠️ 发布评论失败: {comment_result.url}", err=True)

    result_to_github_output(result, output)


@agent.command()
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--pr", required=True, type=int, help="PR 编号")
@click.option("--model", default="", help="使用的模型（默认从 provider 配置读取）")
@click.option(
    "--max-turns", default=AGENT_DEFAULTS["max_turns"]["review"], type=int, help="最大对话轮次"
)
@click.option("--artifact-path", default="", help="可选: 写出结构化结果 artifact")
@click.option(
    "--apply-side-effects/--no-apply-side-effects",
    default=False,
    help="是否应用 GitHub Review 副作用（并行时建议关闭）",
)
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def review(
    repo: str,
    pr: int,
    model: str,
    max_turns: int,
    artifact_path: str,
    apply_side_effects: bool,
    output: str,
) -> None:
    """运行 Review Agent - 审查 PR 代码"""
    from gearbox.config import get_anthropic_model

    resolved_model = model or get_anthropic_model()

    result = asyncio.run(
        run_review(
            repo,
            pr,
            model=resolved_model,
            max_turns=max_turns,
        )
    )
    click.echo(f"✅ Review: verdict={result.verdict}, score={result.score}")

    if artifact_path:
        write_review_result(result, Path(artifact_path))

    if apply_side_effects:
        comments = [
            {"file": c.file, "line": c.line, "body": c.body, "severity": c.severity}
            for c in result.comments
        ]
        body = build_review_body(result.verdict, result.score, result.summary, comments)
        event = {"LGTM": "APPROVE", "Request Changes": "REQUEST_CHANGES"}.get(
            result.verdict, "COMMENT"
        )
        review_result = post_review_comment(repo, pr, body, event)
        if not review_result.success:
            click.echo(f"⚠️ 发布 Review 失败: {review_result.url}", err=True)

    result_to_github_output(result, output)
    click.echo(f"✅ Review: verdict={result.verdict}, score={result.score}")


@agent.command()
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--issue", required=True, type=int, help="Issue 编号")
@click.option("--model", default="", help="使用的模型（默认从 provider 配置读取）")
@click.option("--base-branch", default="main", help="PR 目标分支")
@click.option(
    "--max-turns", default=AGENT_DEFAULTS["max_turns"]["implement"], type=int, help="最大对话轮次"
)
@click.option("--artifact-path", default="", help="可选: 写出结构化结果 artifact")
@click.option(
    "--apply-side-effects/--no-apply-side-effects",
    default=False,
    help="是否创建分支/PR（并行时建议关闭）",
)
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def implement(
    repo: str,
    issue: int,
    model: str,
    base_branch: str,
    max_turns: int,
    artifact_path: str,
    apply_side_effects: bool,
    output: str,
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

        if apply_side_effects and result.ready_for_review and result.branch_name:
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
        elif result.ready_for_review and result.branch_name:
            # Push branch without creating PR (for parallel execution)
            commit_msg = f"feat: {result.summary}\n\nCloses #{issue}"
            pushed = finalize_and_push(
                temp_branch=temp_branch,
                final_branch=result.branch_name,
                commit_message=commit_msg,
                files=result.files_changed,
            )
            if pushed:
                click.echo(f"✅ Branch pushed: {result.branch_name}")
            else:
                click.echo(f"⚠️ No changes to push for branch: {result.branch_name}")

        if artifact_path:
            write_implement_result(result, Path(artifact_path))

        result_to_github_output(result, output)
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
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
@click.option("--no-prescan", is_flag=True, help="跳过预扫描步骤（静态分析）")
def audit_repo(
    repo: str,
    benchmarks: str,
    output_dir: str,
    model: str,
    max_turns: int,
    system_prompt: str,
    output: str,
    no_prescan: bool,
) -> None:
    """运行单次 Audit Agent - 审计仓库生成改进建议。"""
    benchmark_list = benchmarks.split(",") if benchmarks else None
    model_arg = model if model else None
    system_prompt_arg = system_prompt if system_prompt else None

    result = asyncio.run(
        run_audit(
            repo,
            benchmarks=benchmark_list,
            output_dir=output_dir,
            model=model_arg,
            max_turns=max_turns,
            system_prompt=system_prompt_arg,
            enable_prescan=not no_prescan,
        )
    )
    click.echo(f"✅ Audit: {len(result.issues)} issues, cost={format_currency(result.cost)}")

    result_to_github_output(result, output)


@agent.command(name="audit-select")
@click.option("--input-root", required=True, help="并行 audit artifact 根目录")
@click.option("--output-dir", default="./output", help="胜出结果输出目录")
@click.option("--model", default="", help="用于评估多个结果的模型")
@click.option("--max-turns", default=29, type=int, help="Evaluator 最大对话轮次")
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def audit_select(input_root: str, output_dir: str, model: str, max_turns: int, output: str) -> None:
    """聚合多个 audit 结果并选出最佳结果。"""
    root = Path(input_root)
    if not root.exists():
        click.echo(f"❌ 目录不存在: {input_root}", err=True)
        raise click.Abort()

    candidate_dirs = sorted(path for path in root.iterdir() if path.is_dir())
    if not candidate_dirs:
        click.echo(f"❌ 未找到任何 audit 结果目录: {input_root}", err=True)
        raise click.Abort()

    results = []
    names = []
    valid_dirs: list[Path] = []

    for run_dir in candidate_dirs:
        try:
            results.append(load_audit_result(run_dir))
            names.append(run_dir.name)
            valid_dirs.append(run_dir)
        except FileNotFoundError as exc:
            click.echo(f"⚠️ 跳过无效结果目录 {run_dir.name}: {exc}")

    if not results:
        click.echo("❌ 没有可用于聚合的 audit 结果", err=True)
        raise click.Abort()

    winner_index, winner_result = asyncio.run(
        select_best_result(
            results,
            result_type="Audit 审计结果",
            result_names=names,
            model=model or "",
            max_turns=max_turns,
        )
    )
    winner_dir = valid_dirs[winner_index]
    promote_audit_outputs(winner_dir, Path(output_dir))
    result_to_github_output(winner_result, output)
    click.echo(
        f"✅ Selected audit result: winner={winner_dir.name}, issues={len(winner_result.issues)}"
    )


@agent.command(name="triage-select")
@click.option("--input-root", required=True, help="并行 triage artifact 根目录")
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--issue", required=True, type=int, help="Issue 编号")
@click.option("--model", default="", help="用于评估多个结果的模型")
@click.option("--max-turns", default=29, type=int, help="Evaluator 最大对话轮次")
@click.option("--artifact-path", default="", help="可选: 写出胜出结果 artifact")
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def triage_select(
    input_root: str,
    repo: str,
    issue: int,
    model: str,
    max_turns: int,
    artifact_path: str,
    output: str,
) -> None:
    """聚合多个 triage 结果并只应用一次 GitHub 副作用。"""
    root = Path(input_root)
    candidate_files = _candidate_result_files(root)
    if not candidate_files:
        click.echo(f"❌ 未找到任何 triage 结果: {input_root}", err=True)
        raise click.Abort()

    results = []
    names = []
    for name, result_path in candidate_files:
        results.append(load_triage_result(result_path))
        names.append(name)

    if not results:
        click.echo("❌ 没有可用于聚合的 triage 结果", err=True)
        raise click.Abort()

    winner_index, winner_result = asyncio.run(
        select_best_result(
            results,
            result_type="Triage 分类结果",
            result_names=names,
            model=model or "",
            max_turns=max_turns,
        )
    )
    if artifact_path:
        write_triage_result(winner_result, Path(artifact_path))

    label_result = add_issue_labels(repo, issue, winner_result.labels)
    if not label_result.success:
        click.echo(f"⚠️ 添加标签失败: {label_result.url}", err=True)
    if winner_result.needs_clarification and winner_result.clarification_question:
        comment_result = post_issue_comment(
            repo, issue, f"👋 {winner_result.clarification_question}"
        )
        if not comment_result.success:
            click.echo(f"⚠️ 发布评论失败: {comment_result.url}", err=True)
    if winner_result.ready_to_implement:
        comment_result = post_issue_comment(
            repo, issue, "✅ 此 Issue 分类完成，标记为 ready-to-implement"
        )
        if not comment_result.success:
            click.echo(f"⚠️ 发布评论失败: {comment_result.url}", err=True)

    result_to_github_output(winner_result, output)
    click.echo(f"✅ Selected triage result: winner={names[winner_index]}")


@agent.command(name="review-select")
@click.option("--input-root", required=True, help="并行 review artifact 根目录")
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--pr", required=True, type=int, help="PR 编号")
@click.option("--model", default="", help="用于评估多个结果的模型")
@click.option("--max-turns", default=29, type=int, help="Evaluator 最大对话轮次")
@click.option("--artifact-path", default="", help="可选: 写出胜出结果 artifact")
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def review_select(
    input_root: str,
    repo: str,
    pr: int,
    model: str,
    max_turns: int,
    artifact_path: str,
    output: str,
) -> None:
    """聚合多个 review 结果并只应用一次 GitHub 副作用。"""
    root = Path(input_root)
    candidate_files = _candidate_result_files(root)
    if not candidate_files:
        click.echo(f"❌ 未找到任何 review 结果: {input_root}", err=True)
        raise click.Abort()

    results = []
    names = []
    for name, result_path in candidate_files:
        results.append(load_review_result(result_path))
        names.append(name)

    if not results:
        click.echo("❌ 没有可用于聚合的 review 结果", err=True)
        raise click.Abort()

    winner_index, winner_result = asyncio.run(
        select_best_result(
            results,
            result_type="Review 审查结果",
            result_names=names,
            model=model or "",
            max_turns=max_turns,
        )
    )
    if artifact_path:
        write_review_result(winner_result, Path(artifact_path))

    comments = [
        {"file": c.file, "line": c.line, "body": c.body, "severity": c.severity}
        for c in winner_result.comments
    ]
    body = build_review_body(
        winner_result.verdict, winner_result.score, winner_result.summary, comments
    )
    event = {"LGTM": "APPROVE", "Request Changes": "REQUEST_CHANGES"}.get(
        winner_result.verdict, "COMMENT"
    )
    review_result = post_review_comment(repo, pr, body, event)
    if not review_result.success:
        click.echo(f"⚠️ 发布 Review 失败: {review_result.url}", err=True)

    result_to_github_output(winner_result, output)
    click.echo(f"✅ Selected review result: winner={names[winner_index]}")


@agent.command(name="implement-select")
@click.option("--input-root", required=True, help="并行 implement artifact 根目录")
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--issue", required=True, type=int, help="Issue 编号")
@click.option("--base-branch", default="main", help="PR 目标分支")
@click.option("--model", default="", help="用于评估多个结果的模型")
@click.option("--max-turns", default=29, type=int, help="Evaluator 最大对话轮次")
@click.option("--artifact-path", default="", help="可选: 写出胜出结果 artifact")
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def implement_select(
    input_root: str,
    repo: str,
    issue: int,
    base_branch: str,
    model: str,
    max_turns: int,
    artifact_path: str,
    output: str,
) -> None:
    """聚合多个 implement 结果并创建最佳 PR。"""
    from gearbox.config import get_anthropic_model

    resolved_model = model or get_anthropic_model()

    root = Path(input_root)
    candidate_files = _candidate_result_files(root)
    if not candidate_files:
        click.echo(f"❌ 未找到任何 implement 结果: {input_root}", err=True)
        raise click.Abort()

    results = []
    names = []
    for name, result_path in candidate_files:
        results.append(load_implement_result(result_path))
        names.append(name)

    if not results:
        click.echo("❌ 没有可用于聚合的 implement 结果", err=True)
        raise click.Abort()

    winner_index, winner_result = asyncio.run(
        select_best_result(
            results,
            result_type="Implement 实现结果",
            result_names=names,
            model=resolved_model,
            max_turns=max_turns,
        )
    )

    click.echo(f"✅ Selected implement result: winner={names[winner_index]}")
    click.echo(f"   branch={winner_result.branch_name}, files={len(winner_result.files_changed)}")

    if artifact_path:
        write_implement_result(winner_result, Path(artifact_path))

    # Create PR for the winning result
    if winner_result.ready_for_review and winner_result.branch_name:
        # Fetch the branch that was pushed by the parallel run
        subprocess.run(
            ["git", "fetch", "origin", winner_result.branch_name],
            check=True,
        )
        pr_body = f"## Summary\n\n{winner_result.summary}\n\nCloses #{issue}"
        pr_result = create_pr(
            repo=repo,
            title=f"feat(#{issue}): {winner_result.summary}",
            body=pr_body,
            head=winner_result.branch_name,
            base=base_branch,
        )
        if pr_result.success:
            winner_result.pr_url = pr_result.pr_url
            click.echo(f"✅ PR created: {pr_result.pr_url}")
        else:
            click.echo(f"❌ PR creation failed: {pr_result.error}", err=True)

    result_to_github_output(winner_result, output)


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
