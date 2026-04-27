"""Backlog-to-implementation dispatch planning."""

from __future__ import annotations

from gearbox.core.gh import IssueSummary, get_issue_summary, list_open_issues

from .models import DispatchItem, DispatchPlan

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
COMPLEXITY_ORDER = {"S": 0, "M": 1, "L": 2}
BLOCKING_LABELS = {"needs-clarification", "in-progress", "has-pr"}


def dispatch_branch_name(issue_number: int) -> str:
    """Return the deterministic implementation branch for an issue."""
    return f"feat/issue-{issue_number}-run-0"


def _label_value(labels: list[str], allowed: dict[str, int], default: str) -> str:
    label_set = set(labels)
    for label in allowed:
        if label in label_set:
            return label
    return default


def _is_dispatchable(issue: IssueSummary) -> bool:
    labels = set(issue.labels)
    return "ready-to-implement" in labels and not labels.intersection(BLOCKING_LABELS)


def _to_dispatch_item(issue: IssueSummary) -> DispatchItem:
    priority = _label_value(issue.labels, PRIORITY_ORDER, "P3")
    complexity = _label_value(
        issue.labels,
        {f"complexity:{key}": value for key, value in COMPLEXITY_ORDER.items()},
        "complexity:M",
    ).split(":", 1)[1]
    reason = (
        f"ready-to-implement, priority={priority}, complexity={complexity}, "
        f"created_at={issue.created_at or 'unknown'}"
    )
    return DispatchItem(
        issue_number=issue.number,
        title=issue.title,
        labels=issue.labels,
        priority=priority,
        complexity=complexity,
        url=issue.url,
        reason=reason,
    )


def _sort_key(item: DispatchItem) -> tuple[int, int, int]:
    return (
        PRIORITY_ORDER.get(item.priority, PRIORITY_ORDER["P3"]),
        COMPLEXITY_ORDER.get(item.complexity, COMPLEXITY_ORDER["M"]),
        item.issue_number,
    )


def select_dispatch_items(
    issues: list[IssueSummary],
    max_items: int,
    *,
    allowed_priorities: set[str] | None = None,
) -> tuple[list[DispatchItem], int]:
    """Filter and rank candidate issues for implementation."""
    dispatchable = [_to_dispatch_item(issue) for issue in issues if _is_dispatchable(issue)]
    if allowed_priorities:
        dispatchable = [item for item in dispatchable if item.priority in allowed_priorities]
    dispatchable.sort(key=_sort_key)
    selected = dispatchable[:max_items]
    return selected, len(issues) - len(selected)


def build_dispatch_plan(
    repo: str,
    *,
    issue_number: int | None = None,
    max_items: int = 1,
    dry_run: bool = True,
    allowed_priorities: set[str] | None = None,
) -> DispatchPlan:
    """Build a deterministic implementation plan from backlog labels."""
    if max_items < 1:
        raise ValueError("max_items must be a positive integer")

    if issue_number is None:
        issues = list_open_issues(repo, labels=["ready-to-implement"])
    else:
        issue = get_issue_summary(repo, issue_number)
        issues = [issue] if issue is not None else []

    items, skipped_count = select_dispatch_items(
        issues,
        max_items,
        allowed_priorities=allowed_priorities,
    )
    return DispatchPlan(repo=repo, items=items, skipped_count=skipped_count, dry_run=dry_run)
