"""Backlog CLI commands."""

import json
from dataclasses import asdict

import click

from gearbox.flow import BacklogPlan, build_backlog_plan


def _echo_backlog_plan(plan: BacklogPlan, *, as_json: bool = False) -> None:
    if as_json:
        click.echo(json.dumps(asdict(plan), ensure_ascii=False, indent=2))
        return

    click.echo(f"📋 Backlog plan: repo={plan.repo}")
    click.echo(f"候选: {len(plan.items)} | 跳过: {plan.skipped_count}")
    for index, item in enumerate(plan.items, start=1):
        click.echo(f"{index}. #{item.issue_number} {item.title}")
        click.echo(f"   {item.reason}")
        if item.url:
            click.echo(f"   {item.url}")


@click.group()
def backlog() -> None:
    """规划需要进入 backlog 分类的 Issue。"""
    pass


@backlog.command("plan")
@click.option("--repo", required=True, help="仓库标识 (owner/name)")
@click.option("--max-items", default=5, type=int, help="最多选择多少个 Issue")
@click.option("--since-days", default=2, type=int, help="超过多少天未更新分类标签则重新评估")
@click.option("--json-output", is_flag=True, help="输出 JSON 计划")
def backlog_plan(repo: str, max_items: int, since_days: int, json_output: bool) -> None:
    """只生成 backlog 分类计划，不调用 Agent。"""
    try:
        plan = build_backlog_plan(repo, max_items=max_items, since_days=since_days)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    _echo_backlog_plan(plan, as_json=json_output)
