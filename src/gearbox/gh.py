"""GitHub 操作模块 - 集中管理所有 gh/git 操作"""

import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass
class PostReviewResult:
    success: bool
    url: str | None = None


@dataclass
class CreatePrResult:
    success: bool
    pr_url: str | None = None
    error: str | None = None


def post_review_comment(
    repo: str,
    pr_number: int,
    body: str,
    event: str = "COMMENT",
) -> PostReviewResult:
    """
    发布 PR Review 评论。

    Args:
        repo: 仓库标识
        pr_number: PR 编号
        body: 评论内容 (Markdown)
        event: APPROVE / REQUEST_CHANGES / COMMENT

    Returns:
        PostReviewResult
    """
    try:
        subprocess.run(
            [
                "gh", "pr", "review",
                "--repo", repo,
                str(pr_number),
                "--body", body,
                "--event", event,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return PostReviewResult(success=True)
    except subprocess.CalledProcessError as e:
        return PostReviewResult(success=False, url=e.stderr.strip())


def post_issue_comment(
    repo: str,
    issue_number: int,
    body: str,
) -> PostReviewResult:
    """发布 Issue 评论。"""
    try:
        subprocess.run(
            [
                "gh", "issue", "comment",
                "--repo", repo,
                str(issue_number),
                "--body", body,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return PostReviewResult(success=True)
    except subprocess.CalledProcessError as e:
        return PostReviewResult(success=False, url=e.stderr.strip())


def add_issue_labels(
    repo: str,
    issue_number: int,
    labels: list[str],
) -> PostReviewResult:
    """为 Issue 添加标签。"""
    if not labels:
        return PostReviewResult(success=True)

    try:
        subprocess.run(
            [
                "gh", "issue", "edit",
                "--repo", repo,
                str(issue_number),
                "--add-label", ",".join(labels),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return PostReviewResult(success=True)
    except subprocess.CalledProcessError as e:
        return PostReviewResult(success=False, url=e.stderr.strip())


def prepare_branch(base_branch: str, temp_branch: str) -> None:
    """
    准备工作分支。

    Args:
        base_branch: 基础分支名
        temp_branch: 临时分支名
    """
    subprocess.run(["git", "fetch", "origin", base_branch], check=True)
    subprocess.run(
        ["git", "checkout", "-b", temp_branch, f"origin/{base_branch}"],
        check=True,
    )


def prepare_working_branch(base_branch: str) -> str:
    """
    准备工作分支（自动生成临时分支名）。

    Returns:
        临时分支名
    """
    import uuid
    temp_branch = f"gearbox/temp-{uuid.uuid4().hex[:8]}"
    subprocess.run(["git", "fetch", "origin", base_branch], check=True)
    subprocess.run(
        ["git", "checkout", "-b", temp_branch, f"origin/{base_branch}"],
        check=True,
    )
    return temp_branch


def finalize_and_push(
    temp_branch: str,
    final_branch: str,
    commit_message: str,
    files: list[str],
) -> bool:
    """
    重命名分支、提交并推送。

    Returns:
        True if successful, False otherwise
    """
    try:
        # 重命名分支
        subprocess.run(["git", "branch", "-m", temp_branch, final_branch], check=True)

        # 添加文件
        if files:
            for f in files:
                subprocess.run(["git", "add", f], check=True)
        else:
            subprocess.run(["git", "add", "-A"], check=True)

        # 检查是否有变更
        result = subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            capture_output=True,
        )
        if result.returncode == 1:  # 有变更
            subprocess.run(["git", "commit", "-m", commit_message], check=True)
            subprocess.run(
                ["git", "push", "-u", "origin", final_branch],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        return False
    except subprocess.CalledProcessError:
        return False


def finalize_and_create_pr(
    repo: str,
    temp_branch: str,
    final_branch: str,
    commit_message: str,
    pr_title: str,
    pr_body: str,
    base: str = "main",
) -> CreatePrResult:
    """
    重命名分支、提交、推送并创建 PR。

    Returns:
        CreatePrResult
    """
    try:
        # 重命名分支
        subprocess.run(["git", "branch", "-m", temp_branch, final_branch], check=True)

        # 添加文件
        subprocess.run(["git", "add", "-A"], check=True)

        # 检查是否有变更
        result = subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            capture_output=True,
        )
        if result.returncode == 1:
            subprocess.run(["git", "commit", "-m", commit_message], check=True)
            subprocess.run(
                ["git", "push", "-u", "origin", final_branch],
                check=True,
                capture_output=True,
                text=True,
            )

        # 创建 PR
        return create_pr(
            repo=repo,
            title=pr_title,
            body=pr_body,
            head=final_branch,
            base=base,
        )
    except subprocess.CalledProcessError as e:
        return CreatePrResult(success=False, error=e.stderr.strip())


def create_pr(
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str = "main",
) -> CreatePrResult:
    """
    创建 PR。

    Returns:
        CreatePrResult
    """
    try:
        result = subprocess.run(
            [
                "gh", "pr", "create",
                "--repo", repo,
                "--title", title,
                "--body", body,
                "--head", head,
                "--base", base,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return CreatePrResult(success=True, pr_url=result.stdout.strip())
    except subprocess.CalledProcessError as e:
        return CreatePrResult(success=False, error=e.stderr.strip())


def checkout_branch(branch_name: str) -> None:
    """切换到指定分支。"""
    subprocess.run(["git", "checkout", branch_name], check=True)


def delete_branch(branch_name: str) -> None:
    """删除本地分支。"""
    subprocess.run(["git", "branch", "-D", branch_name], check=False)


def build_review_body(
    verdict: str,
    score: int,
    summary: str,
    comments: list[dict[str, Any]],
) -> str:
    """构建 Review 评论的 Markdown body。"""
    lines = [
        "## Code Review",
        f"**评分**: {score}/10",
        f"**结论**: {verdict}",
        f"### {summary}",
    ]

    if comments:
        lines.append("### 详细意见")
        for c in comments:
            icon = {"blocker": "🔴", "warning": "🟡", "info": "🔵"}.get(
                c.get("severity", "info"), "•"
            )
            file = c.get("file", "")
            line = c.get("line")
            body = c.get("body", "")
            if line:
                lines.append(f"{icon} `{file}:{line}` — {body}")
            else:
                lines.append(f"{icon} `{file}` — {body}")

    return "\n\n".join(lines)


def build_issue_body(
    priority: str,
    complexity: str,
    clarification_question: str | None,
    ready_to_implement: bool,
) -> str:
    """构建 Triage 评论的 Markdown body。"""
    lines = [
        f"**优先级**: {priority}",
        f"**复杂度**: {complexity}",
        f"**可实现**: {'✅' if ready_to_implement else '❌'}",
    ]

    if clarification_question:
        lines.append(f"\n**需要澄清**: {clarification_question}")

    return "\n\n".join(lines)


def write_outputs(
    outputs: dict[str, str],
    path: str = "/tmp/github_output",
) -> None:
    """写入 GITHUB_OUTPUT 文件。"""
    with open(path, "w") as f:
        for key, value in outputs.items():
            f.write(f"{key}={value}\n")


VALID_ISSUE_LABELS = {
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


def create_issue(
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> CreatePrResult:
    """
    创建 GitHub Issue。

    Returns:
        CreatePrResult
    """
    cmd = [
        "gh", "issue", "create",
        "--repo", repo,
        "--title", title,
        "--body", body,
    ]
    if labels:
        filtered = [label for label in labels if label in VALID_ISSUE_LABELS]
        for label in filtered:
            cmd.extend(["--label", label])

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return CreatePrResult(success=True, pr_url=result.stdout.strip())
    except subprocess.CalledProcessError as e:
        return CreatePrResult(success=False, error=e.stderr.strip())
