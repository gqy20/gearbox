"""Cleanup CLI commands."""

import json
from dataclasses import asdict

import click

from gearbox.cleanup import CleanupPlan, cleanup_candidate_branches


def _echo_plan(plan: CleanupPlan, *, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(asdict(plan), ensure_ascii=False, indent=2))
        return

    mode = "DRY-RUN" if plan.dry_run else "APPLY"
    click.echo(f"🧹 Cleanup {mode}: repo={plan.repo}, issue=#{plan.issue_number}")
    if not plan.candidate_branches:
        click.echo("No candidate branches found.")
        return

    click.echo("Candidate branches:")
    for branch in plan.candidate_branches:
        marker = "Deleted" if branch in plan.deleted_branches else "Would delete"
        click.echo(f"- {marker}: {branch}")


@click.command("cleanup")
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--issue", "issue_number", required=True, type=int, help="Issue 编号")
@click.option(
    "--dry-run/--no-dry-run",
    default=True,
    help="只输出清理计划，不删除分支（默认开启）",
)
@click.option("--json-output", is_flag=True, help="输出 JSON 结果")
def cleanup(repo: str, issue_number: int, dry_run: bool, json_output: bool) -> None:
    """清理 Gearbox 为指定 Issue 创建的候选分支。"""
    plan = cleanup_candidate_branches(repo, issue_number, dry_run=dry_run)
    _echo_plan(plan, json_output=json_output)
