"""Issue 发布逻辑。"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .config import get_github_token

VALID_LABELS = {
    "bug",
    "documentation",
    "duplicate",
    "enhancement",
    "good first issue",
    "help wanted",
    "invalid",
    "question",
    "wontfix",
}


def _load_issues(input_path: str) -> list[dict[str, Any]]:
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"issues.json not found: {input_path}")

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    issues = data.get("issues", [])
    if not isinstance(issues, list):
        raise ValueError("issues.json format invalid: 'issues' must be a list")

    return issues


def _filter_labels(labels: str) -> list[str]:
    filtered_labels = []
    for label in labels.split(",") if labels else []:
        normalized = label.strip()
        if normalized in VALID_LABELS:
            filtered_labels.append(normalized)
    return filtered_labels


def publish_issues_from_file(input_path: str, dry_run: bool = False) -> dict[str, Any]:
    """从 issues.json 发布 GitHub Issues。"""
    issues = _load_issues(input_path)

    created: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    env = os.environ.copy()
    github_token = get_github_token()
    if github_token and "GH_TOKEN" not in env and "GITHUB_TOKEN" not in env:
        env["GH_TOKEN"] = github_token

    for index, issue in enumerate(issues, start=1):
        repo = issue.get("repo")
        title = issue.get("title")
        body = issue.get("body")
        labels = issue.get("labels", "")

        if not all([repo, title, body]):
            skipped.append(f"{index}: {title or '(missing title)'}")
            continue

        filtered_labels = _filter_labels(labels)
        command = ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body]
        for label in filtered_labels:
            command.extend(["--label", label])

        if dry_run:
            created.append(f"DRY-RUN {repo}#{index}: {title}")
            continue

        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True, env=env)
            created.append(result.stdout.strip())
        except subprocess.CalledProcessError as exc:
            failed.append(title)
            error = exc.stderr.strip() or str(exc)
            failed[-1] = f"{title}: {error}"

    return {
        "total": len(issues),
        "created": created,
        "skipped": skipped,
        "failed": failed,
    }
