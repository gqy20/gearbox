"""Shared helpers for CLI command modules."""

from pathlib import Path

import click

from gearbox.agents.backlog import github_labels_for_backlog_item
from gearbox.core.gh import (
    post_issue_comment,
    replace_managed_issue_labels,
)


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


def _apply_backlog_item(repo: str, result: object, fallback_issue: int | None = None) -> None:
    """Apply one backlog classification item to GitHub with idempotent managed labels."""
    issue_number = getattr(result, "issue_number", None) or fallback_issue
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
