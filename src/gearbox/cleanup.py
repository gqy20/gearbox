"""Conservative cleanup helpers for Gearbox-owned branches."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass
class CleanupPlan:
    """Cleanup result for one issue's candidate branches."""

    repo: str
    issue_number: int
    dry_run: bool
    candidate_branches: list[str]
    deleted_branches: list[str]


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


def cleanup_candidate_branches(repo: str, issue_number: int, *, dry_run: bool) -> CleanupPlan:
    """Plan or delete candidate branches for one issue."""
    branches = list_candidate_branches(repo, issue_number)
    deleted: list[str] = []
    if not dry_run:
        for branch in branches:
            delete_branch(repo, branch)
            deleted.append(branch)

    return CleanupPlan(
        repo=repo,
        issue_number=issue_number,
        dry_run=dry_run,
        candidate_branches=branches,
        deleted_branches=deleted,
    )
