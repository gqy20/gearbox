"""Tests for cleanup planning and execution."""

import json
import subprocess
from unittest.mock import MagicMock

from gearbox.cleanup import (
    CleanupPlan,
    candidate_branch_prefix,
    cleanup_candidate_branches,
    list_candidate_branches,
    list_open_pr_head_branches,
)


def test_candidate_branch_prefix_is_issue_scoped() -> None:
    assert candidate_branch_prefix(13) == "feat/issue-13-run-"


def test_list_candidate_branches_only_returns_exact_issue_run_branches(monkeypatch) -> None:
    payload = [
        {"ref": "refs/heads/feat/issue-13-run-0"},
        {"ref": "refs/heads/feat/issue-13-run-1"},
        {"ref": "refs/heads/feat/issue-130-run-0"},
        {"ref": "refs/heads/main"},
    ]
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs) -> MagicMock:
        del kwargs
        commands.append(cmd)
        return MagicMock(stdout=json.dumps(payload))

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert list_candidate_branches("owner/repo", 13) == [
        "feat/issue-13-run-0",
        "feat/issue-13-run-1",
    ]
    assert commands == [
        [
            "gh",
            "api",
            "repos/owner/repo/git/matching-refs/heads/feat/issue-13-run-",
            "--paginate",
        ]
    ]


def test_cleanup_candidate_branches_dry_run_does_not_delete(monkeypatch) -> None:
    monkeypatch.setattr(
        "gearbox.cleanup.list_candidate_branches",
        lambda repo, issue_number: ["feat/issue-13-run-0"],
    )
    monkeypatch.setattr("gearbox.cleanup.list_open_pr_head_branches", lambda repo: set())
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs) -> MagicMock:
        del kwargs
        commands.append(cmd)
        return MagicMock(stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    plan = cleanup_candidate_branches("owner/repo", 13, dry_run=True)

    assert plan == CleanupPlan(
        repo="owner/repo",
        issue_number=13,
        dry_run=True,
        candidate_branches=["feat/issue-13-run-0"],
        deleted_branches=[],
    )
    assert commands == []


def test_cleanup_candidate_branches_deletes_each_candidate(monkeypatch) -> None:
    monkeypatch.setattr(
        "gearbox.cleanup.list_candidate_branches",
        lambda repo, issue_number: ["feat/issue-13-run-0", "feat/issue-13-run-1"],
    )
    monkeypatch.setattr("gearbox.cleanup.list_open_pr_head_branches", lambda repo: set())
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs) -> MagicMock:
        del kwargs
        commands.append(cmd)
        return MagicMock(stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    plan = cleanup_candidate_branches("owner/repo", 13, dry_run=False)

    assert plan.deleted_branches == ["feat/issue-13-run-0", "feat/issue-13-run-1"]
    assert commands == [
        [
            "gh",
            "api",
            "-X",
            "DELETE",
            "repos/owner/repo/git/refs/heads/feat/issue-13-run-0",
        ],
        [
            "gh",
            "api",
            "-X",
            "DELETE",
            "repos/owner/repo/git/refs/heads/feat/issue-13-run-1",
        ],
    ]


def test_list_open_pr_head_branches_returns_open_pr_heads(monkeypatch) -> None:
    payload = [
        {"headRefName": "feat/issue-13-run-0"},
        {"headRefName": "docs/update-readme"},
        {"headRefName": ""},
    ]
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs) -> MagicMock:
        del kwargs
        commands.append(cmd)
        return MagicMock(stdout=json.dumps(payload))

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert list_open_pr_head_branches("owner/repo") == {
        "feat/issue-13-run-0",
        "docs/update-readme",
    }
    assert commands == [
        [
            "gh",
            "pr",
            "list",
            "--repo",
            "owner/repo",
            "--state",
            "open",
            "--json",
            "headRefName",
            "--limit",
            "1000",
        ]
    ]


def test_cleanup_candidate_branches_skips_open_pr_head_branches(monkeypatch) -> None:
    monkeypatch.setattr(
        "gearbox.cleanup.list_candidate_branches",
        lambda repo, issue_number: ["feat/issue-13-run-0", "feat/issue-13-run-1"],
    )
    monkeypatch.setattr(
        "gearbox.cleanup.list_open_pr_head_branches",
        lambda repo: {"feat/issue-13-run-0"},
    )
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs) -> MagicMock:
        del kwargs
        commands.append(cmd)
        return MagicMock(stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    plan = cleanup_candidate_branches("owner/repo", 13, dry_run=False)

    assert plan.deleted_branches == ["feat/issue-13-run-1"]
    assert plan.skipped_branches == ["feat/issue-13-run-0"]
    assert commands == [
        [
            "gh",
            "api",
            "-X",
            "DELETE",
            "repos/owner/repo/git/refs/heads/feat/issue-13-run-1",
        ],
    ]


def test_cleanup_candidate_branches_can_delete_open_pr_heads_when_unprotected(monkeypatch) -> None:
    monkeypatch.setattr(
        "gearbox.cleanup.list_candidate_branches",
        lambda repo, issue_number: ["feat/issue-13-run-0"],
    )
    monkeypatch.setattr(
        "gearbox.cleanup.list_open_pr_head_branches",
        lambda repo: {"feat/issue-13-run-0"},
    )
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs) -> MagicMock:
        del kwargs
        commands.append(cmd)
        return MagicMock(stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    plan = cleanup_candidate_branches(
        "owner/repo",
        13,
        dry_run=False,
        protect_open_prs=False,
    )

    assert plan.deleted_branches == ["feat/issue-13-run-0"]
    assert plan.skipped_branches == []
