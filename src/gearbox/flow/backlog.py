"""Issue-to-backlog classification planning."""

from gearbox.core.gh import IssueSummary, list_open_issues
from gearbox.flow.models import BacklogPlan, BacklogPlanItem

BLOCKING_LABELS = {"ready-to-implement", "needs-clarification", "in-progress", "has-pr"}
PRIORITY_LABELS = {"P0", "P1", "P2", "P3"}
COMPLEXITY_LABELS = {"complexity:S", "complexity:M", "complexity:L"}


def _is_already_classified(labels: set[str]) -> bool:
    return bool(labels.intersection(PRIORITY_LABELS)) and bool(
        labels.intersection(COMPLEXITY_LABELS)
    )


def _is_backlog_candidate(issue: IssueSummary) -> bool:
    labels = set(issue.labels)
    return not labels.intersection(BLOCKING_LABELS) and not _is_already_classified(labels)


def _to_backlog_item(issue: IssueSummary) -> BacklogPlanItem:
    return BacklogPlanItem(
        issue_number=issue.number,
        title=issue.title,
        labels=issue.labels,
        url=issue.url,
        reason="open issue without Gearbox terminal/status labels or complete classification",
    )


def select_backlog_items(
    issues: list[IssueSummary], max_items: int
) -> tuple[list[BacklogPlanItem], int]:
    """Filter open issues down to unclassified backlog candidates."""
    if max_items < 1:
        raise ValueError("max_items must be a positive integer")

    candidates = [_to_backlog_item(issue) for issue in issues if _is_backlog_candidate(issue)]
    return candidates[:max_items], len(issues) - min(len(candidates), max_items)


def build_backlog_plan(repo: str, max_items: int = 5) -> BacklogPlan:
    """Build a deterministic plan for scheduled backlog classification."""
    if max_items < 1:
        raise ValueError("max_items must be a positive integer")

    issues = list_open_issues(repo)
    items, skipped_count = select_backlog_items(issues, max_items)
    return BacklogPlan(repo=repo, items=items, skipped_count=skipped_count)
