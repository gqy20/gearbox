"""Issue-to-backlog classification planning."""

from datetime import datetime, timedelta, timezone

from gearbox.core.gh import IssueSummary, get_issue_label_events, list_open_issues
from gearbox.flow.models import BacklogPlan, BacklogPlanItem

BLOCKING_LABELS = {"ready-to-implement", "needs-clarification", "in-progress", "has-pr"}
PRIORITY_LABELS = {"P0", "P1", "P2", "P3"}
COMPLEXITY_LABELS = {"complexity:S", "complexity:M", "complexity:L"}
CLASSIFICATION_LABELS = PRIORITY_LABELS | COMPLEXITY_LABELS


def _is_already_classified(labels: set[str]) -> bool:
    return bool(labels.intersection(PRIORITY_LABELS)) and bool(
        labels.intersection(COMPLEXITY_LABELS)
    )


def _needs_reclassification(
    repo: str, issue_number: int, labels: set[str], since_days: int = 2
) -> bool:
    """如果分类标签在近 N 天内有变更记录，返回 False（不需要重新分类）。"""
    events = get_issue_label_events(repo, issue_number, CLASSIFICATION_LABELS, since_days)
    if not events:  # None (failure) or [] (no events) → skip reclassification check
        return False  # 没有任何变更记录，视为需要重新评估
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    for event in events:
        event_time = datetime.fromisoformat(event.created_at.replace("Z", "+00:00"))
        if event_time >= cutoff:
            return False  # N 天内有变更，不需要重新分类
    return True  # N 天内没有变更，需要重新分类


def _is_backlog_candidate(repo: str, issue: IssueSummary, since_days: int = 2) -> bool:
    labels = set(issue.labels)
    if labels.intersection(BLOCKING_LABELS):
        return False
    if not _is_already_classified(labels):
        return True  # 还没打过完整分类标签
    if _needs_reclassification(repo, issue.number, labels, since_days):
        return True  # 打过标签但太久没更新，需要重新评估
    return False


def _to_backlog_item(issue: IssueSummary, reason: str) -> BacklogPlanItem:
    return BacklogPlanItem(
        issue_number=issue.number,
        title=issue.title,
        labels=issue.labels,
        url=issue.url,
        reason=reason,
    )


def select_backlog_items(
    repo: str,
    issues: list[IssueSummary],
    max_items: int,
    since_days: int = 2,
) -> tuple[list[BacklogPlanItem], int]:
    """Filter open issues down to unclassified or stale-classification backlog candidates."""
    if max_items < 1:
        raise ValueError("max_items must be a positive integer")

    candidates: list[BacklogPlanItem] = []
    for issue in issues:
        labels = set(issue.labels)
        if not _is_backlog_candidate(repo, issue, since_days):
            continue
        if _is_already_classified(labels):
            reason = "classification label stale (>2 days), needs re-evaluation"
        else:
            reason = "open issue without complete Gearbox classification"
        candidates.append(_to_backlog_item(issue, reason))
    return candidates[:max_items], len(issues) - min(len(candidates), max_items)


def build_backlog_plan(repo: str, max_items: int = 5, since_days: int = 2) -> BacklogPlan:
    """Build a deterministic plan for scheduled backlog classification."""
    if max_items < 1:
        raise ValueError("max_items must be a positive integer")

    issues = list_open_issues(repo) or []
    items, skipped_count = select_backlog_items(repo, issues, max_items, since_days)
    return BacklogPlan(repo=repo, items=items, skipped_count=skipped_count)
