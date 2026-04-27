"""Shared helpers for CLI command modules."""

from pathlib import Path
from typing import Any, Callable

import click

from gearbox.agents.backlog import github_labels_for_backlog_item
from gearbox.agents.shared.github_output import result_to_github_output
from gearbox.agents.shared.selection import select_best_result
from gearbox.core.gh import (
    post_issue_comment,
    replace_managed_issue_labels,
)


def _candidate_result_files(input_root: Path) -> list[tuple[str, Path]]:
    """Return result.json files from downloaded per-artifact directories."""
    candidates: list[tuple[str, Path]] = []
    if input_root.exists():
        for run_dir in sorted(path for path in input_root.iterdir() if path.is_dir()):
            result_path = run_dir / "result.json"
            if result_path.exists():
                candidates.append((run_dir.name, result_path))

    return candidates


def _apply_backlog_item(repo: str, result: object) -> None:
    """Apply one backlog classification item to GitHub with idempotent managed labels."""
    issue_number = getattr(result, "issue_number", None)
    if issue_number is None:
        raise click.ClickException("backlog item missing issue_number")

    labels = github_labels_for_backlog_item(result)  # type: ignore[arg-type]
    label_result = replace_managed_issue_labels(repo, issue_number, labels)
    if not label_result.success:
        click.echo(f"⚠️ 添加标签失败: {label_result.url}", err=True)

    needs_clarification = bool(getattr(result, "needs_clarification", False))
    clarification_question = getattr(result, "clarification_question", None)
    ready_to_implement = bool(getattr(result, "ready_to_implement", False))
    if needs_clarification and clarification_question:
        comment_result = post_issue_comment(repo, issue_number, f"👋 {clarification_question}")
        if not comment_result.success:
            click.echo(f"⚠️ 发布评论失败: {comment_result.url}", err=True)
    if ready_to_implement:
        comment_result = post_issue_comment(
            repo, issue_number, "✅ 此 Issue 分类完成，标记为 ready-to-implement"
        )
        if not comment_result.success:
            click.echo(f"⚠️ 发布评论失败: {comment_result.url}", err=True)


async def _select_single(
    candidates: list[tuple[str, Any]],
    result_type: str,
    *,
    model: str,
    max_turns: int,
    winner_callback: Callable[[Any, str], None] | None = None,
    output: str = "/tmp/github_output",
) -> tuple[Any, str]:
    """Run selection from pre-loaded candidates, handle winner, write GitHub output.

    Returns (winner_result, winner_name).
    """
    if not candidates:
        raise click.ClickException("No candidates found")

    results = [r for _, r in candidates]
    names = [n for n, _ in candidates]

    winner_index, winner_result = await select_best_result(
        results,
        result_type=result_type,
        result_names=names,
        model=model,
        max_turns=max_turns,
    )
    winner_name = names[winner_index]

    if winner_callback:
        winner_callback(winner_result, winner_name)

    result_to_github_output(winner_result, output)
    return winner_result, winner_name
