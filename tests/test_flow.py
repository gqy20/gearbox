"""Tests for deterministic flow orchestration."""

from gearbox.core.gh import IssueSummary
from gearbox.flow.backlog import (
    _is_already_classified,
    build_backlog_plan,
    select_backlog_items,
)
from gearbox.flow.dispatch import (
    DispatchItem,
    _is_dispatchable,
    _label_value,
    _sort_key,
    _to_dispatch_item,
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


# ---------------------------------------------------------------------------
# dispatch: pure function unit tests
# ---------------------------------------------------------------------------


class TestLabelValue:
    """_label_value 边界情况"""

    def test_returns_first_matching_label(self) -> None:
        # 按允许列表的顺序匹配，不是按 labels 的顺序
        assert _label_value(["P1", "P0"], {"P0": 0, "P1": 1}, "P3") == "P0"

    def test_returns_default_when_no_match(self) -> None:
        assert _label_value(["bug"], {"P0": 0, "P1": 1}, "P3") == "P3"

    def test_empty_labels_returns_default(self) -> None:
        assert _label_value([], {"P0": 0}, "fallback") == "fallback"

    def test_empty_allowed_returns_default(self) -> None:
        assert _label_value(["P0"], {}, "X") == "X"


class TestIsDispatchable:
    """_is_dispatchable 标签组合真值表"""

    def test_ready_implement_alone_is_dispatchable(self) -> None:
        assert _is_dispatchable(_issue(1, ["ready-to-implement"])) is True

    def test_ready_with_blocking_needs_clarification(self) -> None:
        assert _is_dispatchable(_issue(1, ["ready-to-implement", "needs-clarification"])) is False

    def test_ready_with_blocking_in_progress(self) -> None:
        assert _is_dispatchable(_issue(1, ["ready-to-implement", "in-progress"])) is False

    def test_ready_with_blocking_has_pr(self) -> None:
        assert _is_dispatchable(_issue(1, ["ready-to-implement", "has-pr"])) is False

    def test_no_ready_label_not_dispatchable(self) -> None:
        assert _is_dispatchable(_issue(1, ["P0", "complexity:S"])) is False

    def test_empty_labels_not_dispatchable(self) -> None:
        assert _is_dispatchable(_issue(1, [])) is False


class TestToDispatchItem:
    """_to_dispatch_item 字段映射"""

    def test_maps_priority_and_complexity(self) -> None:
        item = _to_dispatch_item(_issue(1, ["ready-to-implement", "P2", "complexity:S"]))
        assert item.priority == "P2"
        assert item.complexity == "S"
        assert item.issue_number == 1

    def test_defaults_to_p3_when_no_priority_label(self) -> None:
        item = _to_dispatch_item(_issue(1, ["ready-to-implement", "complexity:L"]))
        assert item.priority == "P3"

    def test_defaults_to_m_when_no_complexity_label(self) -> None:
        item = _to_dispatch_item(_issue(1, ["ready-to-implement", "P1"]))
        assert item.complexity == "M"


class TestSortKey:
    """_sort_key 排序稳定性"""

    def test_p0_before_p1(self) -> None:
        p0 = DispatchItem(1, "", [], "P0", "S", "", "")
        p1 = DispatchItem(2, "", [], "P1", "S", "", "")
        assert _sort_key(p0) < _sort_key(p1)

    def test_s_before_m_same_priority(self) -> None:
        s = DispatchItem(1, "", [], "P0", "S", "", "")
        m = DispatchItem(2, "", [], "P0", "M", "", "")
        assert _sort_key(s) < _sort_key(m)

    def test_lower_issue_number_breaks_tie(self) -> None:
        a = DispatchItem(1, "", [], "P0", "S", "", "")
        b = DispatchItem(2, "", [], "P0", "S", "", "")
        assert _sort_key(a) < _sort_key(b)

    def test_unknown_priority_falls_back_to_p3(self) -> None:
        unknown = DispatchItem(1, "", [], "PX", "S", "", "")
        p3 = DispatchItem(2, "", [], "P3", "S", "", "")
        # 未知优先级默认为 P3 的排序值，之后按 issue_number 排序
        assert _sort_key(unknown)[0] == _sort_key(p3)[0]


# ---------------------------------------------------------------------------
# dispatch: 集成级测试
# ---------------------------------------------------------------------------


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


def test_select_dispatch_items_empty_input_returns_empty() -> None:
    items, skipped = select_dispatch_items([], max_items=5)
    assert items == []
    assert skipped == 0


def test_select_dispatch_items_all_blocked_returns_empty() -> None:
    items, skipped = select_dispatch_items(
        [
            _issue(1, ["needs-clarification"]),
            _issue(2, ["in-progress"]),
            _issue(3, ["has-pr"]),
            _issue(4, ["P0"]),  # no ready-to-implement
        ],
        max_items=5,
    )
    assert items == []
    assert skipped == 4


def test_select_dispatch_items_max_items_exceeds_available_returns_all() -> None:
    items, skipped = select_dispatch_items(
        [
            _issue(1, ["ready-to-implement", "P0", "complexity:S"]),
            _issue(2, ["ready-to-implement", "P1", "complexity:M"]),
        ],
        max_items=10,
    )
    assert len(items) == 2
    assert skipped == 0


def test_select_dispatch_items_can_filter_to_p0_only() -> None:
    items, skipped = select_dispatch_items(
        [
            _issue(1, ["ready-to-implement", "P1", "complexity:S"]),
            _issue(2, ["ready-to-implement", "P0", "complexity:M"]),
            _issue(3, ["ready-to-implement", "P0", "complexity:S"]),
            _issue(4, ["ready-to-implement", "P2", "complexity:S"]),
        ],
        max_items=1,
        allowed_priorities={"P0"},
    )

    assert [item.issue_number for item in items] == [3]
    assert skipped == 3


def test_select_dispatch_items_none_allowed_priorities_means_no_filter() -> None:
    # 空集合是 falsy，等价于不限制优先级
    items, skipped = select_dispatch_items(
        [_issue(1, ["ready-to-implement", "P0", "complexity:S"])],
        max_items=5,
        allowed_priorities=set(),
    )
    assert len(items) == 1
    assert skipped == 0


def test_dispatch_branch_name_is_stable_per_issue() -> None:
    assert dispatch_branch_name(2) == "feat/issue-2-run-0"


def test_dispatch_branch_name_format_for_large_numbers() -> None:
    assert dispatch_branch_name(999) == "feat/issue-999-run-0"


def test_build_dispatch_plan_raises_on_zero_max_items() -> None:
    import pytest

    with pytest.raises(ValueError, match="max_items must be"):
        build_dispatch_plan("owner/repo", max_items=0)


def test_build_dispatch_plan_raises_on_negative_max_items() -> None:
    import pytest

    with pytest.raises(ValueError, match="max_items must be"):
        build_dispatch_plan("owner/repo", max_items=-1)


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


def test_build_dispatch_plan_can_filter_allowed_priorities(monkeypatch) -> None:
    monkeypatch.setattr(
        "gearbox.flow.dispatch.list_open_issues",
        lambda *args, **kwargs: [
            _issue(7, ["ready-to-implement", "P1", "complexity:S"]),
            _issue(8, ["ready-to-implement", "P0", "complexity:S"]),
        ],
    )

    plan = build_dispatch_plan("owner/repo", max_items=1, allowed_priorities={"P0"})

    assert [item.issue_number for item in plan.items] == [8]


def test_build_dispatch_plan_specific_issue_falls_back_to_empty_when_missing(monkeypatch) -> None:
    monkeypatch.setattr("gearbox.flow.dispatch.get_issue_summary", lambda *args, **kwargs: None)
    plan = build_dispatch_plan("owner/repo", issue_number=999)
    assert plan.items == []


# ---------------------------------------------------------------------------
# backlog: pure function unit tests
# ---------------------------------------------------------------------------


class TestIsAlreadyClassified:
    """_is_already_classified 需要同时有优先级和复杂度标签"""

    def test_both_present(self) -> None:
        assert _is_already_classified({"P1", "complexity:S"}) is True

    def test_only_priority(self) -> None:
        assert _is_already_classified({"P1"}) is False

    def test_only_complexity(self) -> None:
        assert _is_already_classified({"complexity:M"}) is False

    def test_neither_present(self) -> None:
        assert _is_already_classified({"bug"}) is False

    def test_empty_set(self) -> None:
        assert _is_already_classified(set()) is False


# ---------------------------------------------------------------------------
# backlog: 集成级测试
# ---------------------------------------------------------------------------


def test_select_backlog_items_filters_already_triaged_and_blocked(monkeypatch) -> None:
    from gearbox.core.gh import LabelEvent

    monkeypatch.setattr(
        "gearbox.flow.backlog.get_issue_label_events",
        lambda repo, issue_number, labels, since_days=2: [
            LabelEvent(label="P1", event="labeled", created_at="2026-04-27T12:00:00Z")
        ],
    )
    items, skipped = select_backlog_items(
        "owner/repo",
        [
            _issue(1, []),
            _issue(2, ["ready-to-implement"]),
            _issue(3, ["needs-clarification"]),
            _issue(4, ["in-progress"]),
            _issue(5, ["has-pr"]),
            _issue(6, ["P1", "complexity:S"]),
            _issue(7, ["bug"]),
        ],
        max_items=3,
    )

    assert [item.issue_number for item in items] == [1, 7]
    assert skipped == 5


def test_select_backlog_items_empty_input_returns_empty(monkeypatch) -> None:
    items, skipped = select_backlog_items("owner/repo", [], max_items=5)
    assert items == []
    assert skipped == 0


def test_select_backlog_items_raises_on_zero_max_items() -> None:
    import pytest

    with pytest.raises(ValueError, match="max_items must be"):
        select_backlog_items("owner/repo", [_issue(1, [])], max_items=0)


def test_select_backlog_items_raises_on_negative_max_items() -> None:
    import pytest

    with pytest.raises(ValueError, match="max_items must be"):
        select_backlog_items("owner/repo", [_issue(1, [])], max_items=-1)


def test_select_backlog_items_max_items_exceeds_candidates(monkeypatch) -> None:
    monkeypatch.setattr("gearbox.flow.backlog.get_issue_label_events", lambda *args, **kwargs: [])
    items, skipped = select_backlog_items(
        "owner/repo",
        [_issue(1, []), _issue(2, ["bug"])],
        max_items=10,
    )
    assert len(items) == 2
    assert skipped == 0


def test_select_backlog_items_partial_classification_is_candidate(monkeypatch) -> None:
    """只有优先级或只有复杂度标签 → 视为未完整分类，应入选"""
    monkeypatch.setattr("gearbox.flow.backlog.get_issue_label_events", lambda *args, **kwargs: [])
    items, skipped = select_backlog_items(
        "owner/repo",
        [
            _issue(1, ["P1"]),  # 只有优先级
            _issue(2, ["complexity:S"]),  # 只有复杂度
            _issue(3, ["P2", "complexity:M"]),  # 完整分类且新鲜
        ],
        max_items=5,
    )
    numbers = [item.issue_number for item in items]
    assert 1 in numbers
    assert 2 in numbers
    assert 3 not in numbers  # 完整分类且无 stale 事件，不入选


def test_select_backlog_items_reason_distinguishes_unclassified_vs_stale(monkeypatch) -> None:
    from gearbox.core.gh import LabelEvent

    monkeypatch.setattr(
        "gearbox.flow.backlog.get_issue_label_events",
        lambda *args, **kwargs: [
            LabelEvent(label="P1", event="labeled", created_at="2026-01-01T00:00:00Z")
        ],
    )
    items, _ = select_backlog_items(
        "owner/repo",
        [_issue(1, []), _issue(2, ["P1", "complexity:S"])],
        max_items=5,
    )

    reasons = {item.issue_number: item.reason for item in items}
    assert "without complete Gearbox classification" in reasons[1]
    assert "stale" in reasons[2]


def test_build_backlog_plan_lists_open_issues_without_label_filter(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_list_open_issues(repo: str, labels: list[str] | None = None, limit: int = 100):
        captured["repo"] = repo
        captured["labels"] = labels
        captured["limit"] = limit
        return [_issue(9, [])]

    monkeypatch.setattr("gearbox.flow.backlog.list_open_issues", fake_list_open_issues)

    plan = build_backlog_plan("owner/repo", max_items=5)

    assert captured["repo"] == "owner/repo"
    assert captured["labels"] is None
    assert captured["limit"] == 100
    assert [item.issue_number for item in plan.items] == [9]


def test_build_backlog_plan_raises_on_invalid_max_items() -> None:
    import pytest

    with pytest.raises(ValueError, match="max_items must be"):
        build_backlog_plan("owner/repo", max_items=0)
