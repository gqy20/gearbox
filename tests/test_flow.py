"""Tests for deterministic flow orchestration."""

from gearbox.core.gh import IssueSummary
from gearbox.flow.dispatch import (
    build_dispatch_plan,
    dispatch_branch_name,
    select_dispatch_items,
)


def _issue(number: int, labels: list[str]) -> IssueSummary:
    return IssueSummary(
        number=number,
        title=f"Issue {number}",
        labels=labels,
        url=f"https://github.com/owner/repo/issues/{number}",
        created_at=f"2026-04-{number:02d}T00:00:00Z",
    )


def test_select_dispatch_items_filters_blocked_and_ranks_priority_then_complexity() -> None:
    items, skipped = select_dispatch_items(
        [
            _issue(3, ["ready-to-implement", "P2", "complexity:S"]),
            _issue(1, ["ready-to-implement", "P1", "complexity:M"]),
            _issue(2, ["ready-to-implement", "P1", "complexity:S"]),
            _issue(4, ["ready-to-implement", "P0", "needs-clarification"]),
            _issue(5, ["P0", "complexity:S"]),
            _issue(6, ["ready-to-implement", "P0", "has-pr"]),
        ],
        max_items=3,
    )

    assert [item.issue_number for item in items] == [2, 1, 3]
    assert skipped == 3


def test_dispatch_branch_name_is_stable_per_issue() -> None:
    assert dispatch_branch_name(2) == "gearbox/issue-2"


def test_build_dispatch_plan_uses_ready_to_implement_label(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_list_open_issues(repo: str, labels: list[str] | None = None, limit: int = 100):
        captured["repo"] = repo
        captured["labels"] = labels
        captured["limit"] = limit
        return [_issue(7, ["ready-to-implement", "P3", "complexity:S"])]

    monkeypatch.setattr("gearbox.flow.dispatch.list_open_issues", fake_list_open_issues)

    plan = build_dispatch_plan("owner/repo", max_items=1)

    assert captured["repo"] == "owner/repo"
    assert captured["labels"] == ["ready-to-implement"]
    assert [item.issue_number for item in plan.items] == [7]
