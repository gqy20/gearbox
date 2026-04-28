"""Agent CLI commands."""

import asyncio
import subprocess
from pathlib import Path
from typing import cast

import click

from gearbox.agents.audit import AuditResult, load_audit_result, promote_audit_outputs, run_audit
from gearbox.agents.backlog import (
    BacklogItemResult,
    BacklogResult,
    load_backlog_result,
    parse_issue_numbers,
    run_backlog_item,
    write_backlog_result,
)
from gearbox.agents.implement import (
    load_implement_result,
    run_implement,
    write_implement_result,
)
from gearbox.agents.review import ReviewResult, load_review_result, run_review, write_review_result
from gearbox.agents.shared.github_output import format_currency, result_to_github_output
from gearbox.agents.shared.selection import select_best_result
from gearbox.config import AGENT_DEFAULTS
from gearbox.core.gh import (
    build_review_body,
    create_pr,
    finalize_and_create_pr,
    finalize_and_push,
    post_review_comment,
    prepare_working_branch,
)

from .shared import (
    _apply_backlog_item,
    _apply_backlog_item_with_comments,
    _candidate_result_files,
    _select_single,
)


def _with_branch_suffix(branch_name: str, suffix: str) -> str:
    """Append a sanitized suffix to keep parallel candidate branches distinct."""
    clean_suffix = suffix.strip().strip("/")
    if not clean_suffix:
        return branch_name
    return f"{branch_name}-{clean_suffix}"


@click.group()
def agent() -> None:
    """运行 Agent (Audit/Backlog/Review/Implement)"""
    pass


@agent.command(name="backlog")
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--issues", required=True, help="逗号或空格分隔的 Issue 编号")
@click.option("--model", default="", help="使用的模型（默认从 provider 配置读取）")
@click.option(
    "--max-turns", default=AGENT_DEFAULTS["max_turns"]["backlog"], type=int, help="最大对话轮次"
)
@click.option("--artifact-path", default="", help="可选: 写出结构化 backlog artifact")
@click.option(
    "--apply-side-effects/--no-apply-side-effects",
    default=False,
    help="是否应用 GitHub 标签/评论副作用（并行时建议关闭）",
)
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def backlog(
    repo: str,
    issues: str,
    model: str,
    max_turns: int,
    artifact_path: str,
    apply_side_effects: bool,
    output: str,
) -> None:
    """运行 Backlog Agent - 统一处理单个或多个 Issue 分类。"""
    from gearbox.config import get_anthropic_model

    issue_numbers = parse_issue_numbers(issues)
    if not issue_numbers:
        raise click.ClickException("--issues must contain at least one issue number")

    resolved_model = model or get_anthropic_model()
    items = [
        asyncio.run(
            run_backlog_item(
                repo,
                issue_number,
                model=resolved_model,
                max_turns=max_turns,
            )
        )
        for issue_number in issue_numbers
    ]
    result = BacklogResult(items=items)
    click.echo(f"✅ Backlog: issues={','.join(str(item.issue_number) for item in items)}")

    if artifact_path:
        write_backlog_result(result, Path(artifact_path))

    if apply_side_effects:
        for item in result.items:
            _apply_backlog_item(repo, item)

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
            raise click.ClickException(f"发布 Review 失败: {review_result.url}")

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
    "--push-candidate-branch/--no-push-candidate-branch",
    default=True,
    help="是否推送候选实现分支（并行实现时开启，最终聚合时从候选分支中择优）",
)
@click.option(
    "--create-pr/--no-create-pr",
    default=False,
    help="是否创建 PR（通常只应由聚合阶段或单路实现开启）",
)
@click.option("--candidate-branch-suffix", default="", help="候选分支后缀，用于并行实现隔离")
@click.option("--run-id", default=0, type=int, help="并行运行 ID（注入分支名确保唯一）")
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def implement(
    repo: str,
    issue: int,
    model: str,
    base_branch: str,
    max_turns: int,
    artifact_path: str,
    push_candidate_branch: bool,
    create_pr: bool,
    candidate_branch_suffix: str,
    run_id: int,
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
                run_id=run_id,
            )
        )

        if create_pr and result.ready_for_review and result.branch_name:
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
        elif push_candidate_branch and result.ready_for_review and result.branch_name:
            final_branch = (
                _with_branch_suffix(result.branch_name, candidate_branch_suffix)
                if candidate_branch_suffix
                else result.branch_name
            )
            result.branch_name = final_branch
            commit_msg = f"feat: {result.summary}\n\nCloses #{issue}"
            pushed = finalize_and_push(
                repo=repo,
                temp_branch=temp_branch,
                final_branch=final_branch,
                commit_message=commit_msg,
                files=result.files_changed,
            )
            if pushed:
                click.echo(f"✅ Branch pushed: {result.branch_name}")
            else:
                click.echo(
                    f"⚠️ Push failed for branch: {result.branch_name} "
                    "(another parallel run may have pushed first)",
                    err=True,
                )
                result.ready_for_review = False
                result.branch_name = ""

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

    # Load results with per-directory error handling (audit stores artifacts in subdirs)
    candidates: list[tuple[str, object]] = []
    for run_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            candidates.append((run_dir.name, load_audit_result(run_dir)))
        except FileNotFoundError as exc:
            click.echo(f"⚠️ 跳过无效结果目录 {run_dir.name}: {exc}")

    if not candidates:
        click.echo("❌ 没有可用于聚合的 audit 结果", err=True)
        raise click.Abort()

    def promote_winner(result: object, winner_name: str) -> None:
        typed = cast(AuditResult, result)
        winner_dir = next(p for p in root.iterdir() if p.name == winner_name)
        promote_audit_outputs(winner_dir, Path(output_dir))
        click.echo(f"✅ Selected audit result: winner={winner_name}, issues={len(typed.issues)}")

    asyncio.run(
        _select_single(
            candidates,
            result_type="Audit 审计结果",
            model=model or "",
            max_turns=max_turns,
            winner_callback=promote_winner,
            output=output,
        )
    )


@agent.command(name="backlog-select")
@click.option("--input-root", required=True, help="并行 backlog artifact 根目录")
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--model", default="", help="用于评估多个结果的模型")
@click.option("--max-turns", default=29, type=int, help="Evaluator 最大对话轮次")
@click.option("--artifact-path", default="", help="可选: 写出胜出结果 artifact")
@click.option(
    "--comment-mode",
    type=click.Choice(["auto", "never"]),
    default="auto",
    help="应用 backlog 结果时是否发布评论",
)
@click.option("--output", default="/tmp/github_output", help="输出文件路径")
def backlog_select(
    input_root: str,
    repo: str,
    model: str,
    max_turns: int,
    artifact_path: str,
    comment_mode: str,
    output: str,
) -> None:
    """聚合多个 backlog 结果并按 issue 只应用一次 GitHub 副作用。"""
    root = Path(input_root)
    candidate_files = _candidate_result_files(root)
    if not candidate_files:
        click.echo(f"❌ 未找到任何 backlog 结果: {input_root}", err=True)
        raise click.Abort()

    by_issue: dict[int, list[tuple[str, BacklogItemResult]]] = {}
    for name, result_path in candidate_files:
        backlog_result = load_backlog_result(result_path)
        for item in backlog_result.items:
            if item.issue_number is None:
                raise click.ClickException(f"{result_path} missing issue_number")
            by_issue.setdefault(item.issue_number, []).append((name, item))

    selected_items: list[BacklogItemResult] = []
    for issue_number in sorted(by_issue):
        candidates = by_issue[issue_number]
        names = [name for name, _ in candidates]
        results = [item for _, item in candidates]
        winner_index, winner_result = asyncio.run(
            select_best_result(
                results,
                result_type=f"Backlog Issue #{issue_number} 分类结果",
                result_names=names,
                model=model or "",
                max_turns=max_turns,
            )
        )
        selected_items.append(winner_result)
        _apply_backlog_item_with_comments(repo, winner_result, comment_mode=comment_mode)
        click.echo(
            f"✅ Selected backlog result: issue={issue_number}, winner={names[winner_index]}"
        )

    result = BacklogResult(items=selected_items)
    if artifact_path:
        write_backlog_result(result, Path(artifact_path))
    result_to_github_output(result, output)


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

    candidates = [(name, load_review_result(path)) for name, path in candidate_files]

    def post_winner(result: object, winner_name: str) -> None:
        typed = cast(ReviewResult, result)
        comments = [
            {"file": c.file, "line": c.line, "body": c.body, "severity": c.severity}
            for c in typed.comments
        ]
        body = build_review_body(typed.verdict, typed.score, typed.summary, comments)
        event = {"LGTM": "APPROVE", "Request Changes": "REQUEST_CHANGES"}.get(
            typed.verdict, "COMMENT"
        )
        review_result = post_review_comment(repo, pr, body, event)
        if not review_result.success:
            raise click.ClickException(f"发布 Review 失败: {review_result.url}")
        if artifact_path:
            write_review_result(typed, Path(artifact_path))
        click.echo(f"✅ Selected review result: winner={winner_name}")

    asyncio.run(
        _select_single(
            candidates,
            result_type="Review 审查结果",
            model=model or "",
            max_turns=max_turns,
            winner_callback=post_winner,
            output=output,
        )
    )


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

    candidates = [(name, load_implement_result(path)) for name, path in candidate_files]

    winner_result, winner_name = asyncio.run(
        _select_single(
            candidates,
            result_type="Implement 实现结果",
            model=resolved_model,
            max_turns=max_turns,
            output=output,
        )
    )

    click.echo(f"✅ Selected implement result: winner={winner_name}")
    click.echo(f"   branch={winner_result.branch_name}, files={len(winner_result.files_changed)}")

    if artifact_path:
        write_implement_result(winner_result, Path(artifact_path))

    if winner_result.ready_for_review and winner_result.branch_name:
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

    # Re-write output after pr_url may have been updated
    result_to_github_output(winner_result, output)
