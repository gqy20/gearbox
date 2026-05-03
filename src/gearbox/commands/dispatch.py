"""Dispatch CLI commands."""

import asyncio
import json
from dataclasses import asdict

import click

from gearbox.agents.implement import run_implement
from gearbox.config import AGENT_DEFAULTS
from gearbox.core.gh import (
    add_issue_labels,
    finalize_and_create_pr,
    post_issue_comment,
    prepare_working_branch,
    remove_issue_labels,
)
from gearbox.flow import DispatchPlan, build_dispatch_plan, dispatch_branch_name


def _parse_allowed_priorities(value: str) -> set[str] | None:
    priorities = {part.strip() for part in value.split(",") if part.strip()}
    if not priorities:
        return None
    allowed = {"P0", "P1", "P2", "P3"}
    unknown = sorted(priorities - allowed)
    if unknown:
        raise click.ClickException(
            f"allowed priorities must be one of P0,P1,P2,P3, got: {','.join(unknown)}"
        )
    return priorities


def _cleanup_failed_dispatch(repo: str, issue_number: int, branch_name: str) -> None:
    """清理 dispatch 失败后遗留的远程分支，并记录失败评论。

    每个清理步骤独立 try/except 包裹，避免清理失败掩盖原始异常。
    """
    import subprocess

    # 1. 删除远程分支
    try:
        subprocess.run(
            ["git", "push", "origin", "--delete", branch_name],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        click.echo(f"🧹 已清理远程分支: {branch_name}", err=True)
    except Exception as exc:
        click.echo(f"⚠️ 清理远程分支失败 {branch_name}: {exc}", err=True)

    # 2. 发布失败评论
    try:
        post_issue_comment(
            repo,
            issue_number,
            f"❌ Gearbox dispatch 失败：已回滚远程分支 `{branch_name}`，请检查日志排查原因。",
        )
    except Exception as exc:
        click.echo(f"⚠️ 发布失败评论失败 #{issue_number}: {exc}", err=True)


def _echo_dispatch_plan(plan: DispatchPlan, *, as_json: bool = False) -> None:
    if as_json:
        click.echo(json.dumps(asdict(plan), ensure_ascii=False, indent=2))
        return

    click.echo(f"📋 Dispatch plan: repo={plan.repo}, dry_run={plan.dry_run}")
    click.echo(f"候选: {len(plan.items)} | 跳过: {plan.skipped_count}")
    for index, item in enumerate(plan.items, start=1):
        click.echo(
            f"{index}. #{item.issue_number} [{item.priority}/{item.complexity}] {item.title}"
        )
        click.echo(f"   {item.reason}")
        if item.url:
            click.echo(f"   {item.url}")


@click.group()
def dispatch() -> None:
    """从 ready backlog 中选择 Issue 并触发实现。"""
    pass


@dispatch.command("plan")
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--issue", "issue_number", type=int, default=None, help="只规划指定 Issue")
@click.option("--max-items", default=1, type=int, help="最多选择多少个 Issue")
@click.option("--allowed-priorities", default="", help="只选择指定优先级，例如 P0 或 P0,P1")
@click.option("--json-output", is_flag=True, help="输出 JSON 计划")
def dispatch_plan(
    repo: str,
    issue_number: int | None,
    max_items: int,
    allowed_priorities: str,
    json_output: bool,
) -> None:
    """只生成实现计划，不创建分支或 PR。"""
    try:
        plan = build_dispatch_plan(
            repo,
            issue_number=issue_number,
            max_items=max_items,
            dry_run=True,
            allowed_priorities=_parse_allowed_priorities(allowed_priorities),
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    _echo_dispatch_plan(plan, as_json=json_output)


@dispatch.command("run")
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--issue", "issue_number", type=int, default=None, help="只实现指定 Issue")
@click.option("--max-items", default=1, type=int, help="最多实现多少个 Issue")
@click.option("--allowed-priorities", default="", help="只选择指定优先级，例如 P0 或 P0,P1")
@click.option("--base-branch", default="main", help="PR 目标分支")
@click.option("--model", default="", help="使用的模型（默认从 provider 配置读取）")
@click.option(
    "--max-turns", default=AGENT_DEFAULTS["max_turns"]["implement"], type=int, help="最大对话轮次"
)
@click.option(
    "--dry-run/--no-dry-run",
    default=True,
    help="默认只展示计划；显式 --no-dry-run 才会创建分支和 PR",
)
def dispatch_run(
    repo: str,
    issue_number: int | None,
    max_items: int,
    allowed_priorities: str,
    base_branch: str,
    model: str,
    max_turns: int,
    dry_run: bool,
) -> None:
    """执行 dispatch 计划，复用已有 Implement Agent。"""
    from gearbox.config import get_anthropic_model

    try:
        plan = build_dispatch_plan(
            repo,
            issue_number=issue_number,
            max_items=max_items,
            dry_run=dry_run,
            allowed_priorities=_parse_allowed_priorities(allowed_priorities),
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    _echo_dispatch_plan(plan)
    if dry_run or not plan.items:
        return

    resolved_model = model or get_anthropic_model()
    for item in plan.items:
        click.echo(f"🚀 Dispatching issue #{item.issue_number}")
        label_result = add_issue_labels(repo, item.issue_number, ["in-progress"])
        if not label_result.success:
            click.echo(f"⚠️ 标记 in-progress 失败: {label_result.url}", err=True)

        # 在 try 外初始化，以便 except 分支可访问
        final_branch: str | None = None

        try:
            temp_branch = prepare_working_branch(base_branch)
            result = asyncio.run(
                run_implement(
                    repo,
                    item.issue_number,
                    model=resolved_model,
                    base_branch=base_branch,
                    max_turns=max_turns,
                )
            )
            if not result.ready_for_review or not result.branch_name:
                raise click.ClickException(f"Issue #{item.issue_number} 未生成可 review 的实现")

            final_branch = dispatch_branch_name(item.issue_number)
            commit_msg = f"feat: {result.summary}\n\nCloses #{item.issue_number}"
            pr_body = (
                f"## Summary\n\n{result.summary}\n\n"
                f"## Dispatch\n\n{item.reason}\n\nCloses #{item.issue_number}"
            )
            pr_result = finalize_and_create_pr(
                repo=repo,
                temp_branch=temp_branch,
                final_branch=final_branch,
                commit_message=commit_msg,
                pr_title=f"feat(#{item.issue_number}): {result.summary}",
                pr_body=pr_body,
                base=base_branch,
            )
            if not pr_result.success:
                raise click.ClickException(f"PR creation failed: {pr_result.error}")

            add_issue_labels(repo, item.issue_number, ["has-pr"])
            remove_issue_labels(repo, item.issue_number, ["in-progress"])
            post_issue_comment(
                repo,
                item.issue_number,
                f"✅ Gearbox 已创建实现 PR: {pr_result.pr_url}",
            )
            click.echo(f"✅ PR created: {pr_result.pr_url}")
        except Exception:
            remove_issue_labels(repo, item.issue_number, ["in-progress"])
            # 清理可能已推送的远程分支（push 成功但 PR 创建失败的场景）
            if final_branch:
                _cleanup_failed_dispatch(repo, item.issue_number, final_branch)
            raise
