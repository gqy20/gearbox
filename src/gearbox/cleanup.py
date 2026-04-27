"""Conservative cleanup helpers for Gearbox-owned branches."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

from gearbox.core.gh import add_issue_labels, post_issue_comment, remove_issue_labels


@dataclass
class CleanupPlan:
    """Cleanup result for one issue's candidate branches."""

    repo: str
    issue_number: int
    dry_run: bool
    candidate_branches: list[str]
    deleted_branches: list[str]
    skipped_branches: list[str] = field(default_factory=list)


def candidate_branch_prefix(issue_number: int) -> str:
    """Return the only branch prefix this cleanup version is allowed to delete."""
    return f"feat/issue-{issue_number}-run-"


def _branch_from_ref(ref: str) -> str:
    prefix = "refs/heads/"
    if ref.startswith(prefix):
        return ref[len(prefix) :]
    return ref


def list_candidate_branches(repo: str, issue_number: int) -> list[str]:
    """List Gearbox candidate branches for a single issue."""
    prefix = candidate_branch_prefix(issue_number)
    result = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{repo}/git/matching-refs/heads/{prefix}",
            "--paginate",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    refs = json.loads(result.stdout or "[]")
    branches = [
        _branch_from_ref(item.get("ref", ""))
        for item in refs
        if _branch_from_ref(item.get("ref", "")).startswith(prefix)
    ]
    return sorted(branches)


def list_open_pr_head_branches(repo: str) -> set[str]:
    """List branch names currently used as heads of open pull requests."""
    result = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--json",
            "headRefName",
            "--limit",
            "1000",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    prs = json.loads(result.stdout or "[]")
    return {item["headRefName"] for item in prs if item.get("headRefName")}


def delete_branch(repo: str, branch: str) -> None:
    """Delete a branch ref through GitHub's API."""
    subprocess.run(
        [
            "gh",
            "api",
            "-X",
            "DELETE",
            f"repos/{repo}/git/refs/heads/{branch}",
        ],
        check=True,
    )


def cleanup_candidate_branches(
    repo: str,
    issue_number: int,
    *,
    dry_run: bool,
    protect_open_prs: bool = True,
) -> CleanupPlan:
    """Plan or delete candidate branches for one issue."""
    branches = list_candidate_branches(repo, issue_number)
    protected_branches = list_open_pr_head_branches(repo) if protect_open_prs else set()
    deleted: list[str] = []
    skipped = sorted(branch for branch in branches if branch in protected_branches)
    if not dry_run:
        for branch in branches:
            if branch in protected_branches:
                continue
            delete_branch(repo, branch)
            deleted.append(branch)

    return CleanupPlan(
        repo=repo,
        issue_number=issue_number,
        dry_run=dry_run,
        candidate_branches=branches,
        deleted_branches=deleted,
        skipped_branches=skipped,
    )


def restore_issue_after_unmerged_pr(
    repo: str,
    issue_number: int,
    *,
    pr_number: int,
    pr_url: str,
) -> None:
    """Restore an issue to dispatchable state when its implementation PR is closed unmerged."""
    remove_issue_labels(repo, issue_number, ["has-pr"])
    add_issue_labels(repo, issue_number, ["ready-to-implement"])
    post_issue_comment(
        repo,
        issue_number,
        (
            f"⚠️ Gearbox 检测到实现 PR #{pr_number} 已关闭但未合并：{pr_url}\n\n"
            "已移除 `has-pr` 并重新添加 `ready-to-implement`，该 Issue 可再次进入 dispatch。"
        ),
    )
