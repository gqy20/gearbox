"""GitHub 操作模块 - 集中管理所有 gh/git 操作"""

import json
import os
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


@dataclass
class IssueSummary:
    number: int
    title: str
    labels: list[str]
    url: str
    created_at: str


BACKLOG_LABEL_METADATA: dict[str, tuple[str, str]] = {
    "P0": ("b60205", "生产环境故障、数据丢失风险"),
    "P1": ("d93f0b", "核心功能受损、用户体验严重下降"),
    "P2": ("fbca04", "一般功能问题、边界情况"),
    "P3": ("0e8a16", "优化建议、便利性改进"),
    "complexity:S": ("c2e0c6", "低复杂度，预计 1 小时内"),
    "complexity:M": ("fef2c0", "中等复杂度，预计 1-3 天"),
    "complexity:L": ("f9d0c4", "高复杂度，预计超过 3 天"),
    "needs-clarification": ("d876e3", "需要补充信息或进一步澄清"),
    "ready-to-implement": ("0e8a16", "需求清晰，可进入实现阶段"),
    "in-progress": ("fbca04", "Gearbox 正在处理"),
    "has-pr": ("0e8a16", "已有关联 PR"),
}

MANAGED_BACKLOG_LABELS = frozenset(BACKLOG_LABEL_METADATA)


def _label_metadata(label: str) -> tuple[str, str]:
    return BACKLOG_LABEL_METADATA.get(label, ("cfd3d7", "由 Gearbox 自动分类创建"))


def create_repo_label(repo: str, label: str) -> PostReviewResult:
    """创建单个仓库标签（兼容旧调用方）。"""
    result = create_repo_labels_batch(repo, [label])
    return result


def create_repo_labels_batch(
    repo: str,
    labels: list[str],
) -> PostReviewResult:
    """
    批量创建仓库标签，使用单次 GraphQL 调用减少子进程开销。

    Args:
        repo: 仓库标识（owner/name 格式）
        labels: 待创建的标签名称列表

    Returns:
        PostReviewResult: 全部成功返回 success=True；任一失败返回 success=False
    """
    if not labels:
        return PostReviewResult(success=True)

    # 构建 GraphQL 批量创建 mutation：先查 repositoryId，再逐个 createLabel
    # 使用别名避免字段名冲突
    mutation_parts: list[str] = []
    for i, label in enumerate(labels):
        color, description = _label_metadata(label)
        escaped_name = json.dumps(label)
        escaped_color = json.dumps(color)
        escaped_desc = json.dumps(description)
        alias = f"cl{i}"
        mutation_parts.append(
            f"{alias}: createLabel(input: {{repositoryId: $repoId, name: {escaped_name}, "
            f"color: {escaped_color}, description: {escaped_desc}}}) "
            "{{ label { name } }}"
        )

    mutation_body = "\n  ".join(mutation_parts)
    query = (
        f"query($owner: String!, $name: String!) {{\n"
        f"  repository(owner: $owner, name: $name) {{ id }}\n"
        f"}}\n"
        f"mutation($repoId: ID!) {{\n"
        f"  {mutation_body}\n"
        f"}}"
    )

    try:
        # 第一步：获取 repository node ID
        owner, name = repo.split("/", 1)
        id_result = subprocess.run(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                "query=query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ id }} }}",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={name}",
                "--jq",
                ".data.repository.id",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        repo_id = id_result.stdout.strip()
        if not repo_id:
            return PostReviewResult(success=False, url="无法获取 repository ID")

        # 第二步：批量创建标签
        create_result = subprocess.run(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"repoId={repo_id}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # 检查响应中是否包含 errors
        response = json.loads(create_result.stdout)
        if response.get("errors"):
            error_msgs = [e.get("message", "") for e in response["errors"]]
            return PostReviewResult(success=False, url="; ".join(error_msgs))

        return PostReviewResult(success=True)

    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip() if isinstance(e.stderr, str) else ""
        # "already exists" 在批量场景下视为成功（幂等）
        if "already exists" in stderr.lower():
            return PostReviewResult(success=True)
        return PostReviewResult(success=False, url=stderr)
    except (json.JSONDecodeError, ValueError):
        return PostReviewResult(success=False, url="标签创建响应解析失败")


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
    event_flag = {
        "APPROVE": "--approve",
        "COMMENT": "--comment",
        "REQUEST_CHANGES": "--request-changes",
    }.get(event, "--comment")

    try:
        subprocess.run(
            [
                "gh",
                "pr",
                "review",
                "--repo",
                repo,
                str(pr_number),
                "--body",
                body,
                event_flag,
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
                "gh",
                "issue",
                "comment",
                "--repo",
                repo,
                str(issue_number),
                "--body",
                body,
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
    """
    为 Issue 添加标签。

    优化：使用批量创建减少子进程调用（2+N → 3 次：list + graphql-id + graphql-batch + edit），
    并采用 fail-fast 语义——任一标签创建失败则不执行 issue edit。
    """
    if not labels:
        return PostReviewResult(success=True)

    # 入口处仅查询一次现有标签
    existing_labels = get_repo_labels(repo)
    unknown_labels = [label for label in labels if label not in existing_labels]

    if unknown_labels:
        import sys

        print(
            f"⚠️ 警告: 以下标签在仓库中不存在，正在批量创建: {', '.join(unknown_labels)}",
            file=sys.stderr,
        )

        # 批量创建所有缺失标签，fail-fast：任一失败则直接返回错误
        batch_result = create_repo_labels_batch(repo, unknown_labels)
        if not batch_result.success:
            print(
                f"❌ 批量创建标签失败，已中止 issue edit: {batch_result.url}",
                file=sys.stderr,
            )
            return PostReviewResult(success=False, url=batch_result.url)

    try:
        subprocess.run(
            [
                "gh",
                "issue",
                "edit",
                "--repo",
                repo,
                str(issue_number),
                "--add-label",
                ",".join(labels),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return PostReviewResult(success=True)
    except subprocess.CalledProcessError as e:
        return PostReviewResult(success=False, url=e.stderr.strip())


def remove_issue_labels(
    repo: str,
    issue_number: int,
    labels: list[str],
) -> PostReviewResult:
    """从 Issue 移除标签。"""
    if not labels:
        return PostReviewResult(success=True)

    try:
        subprocess.run(
            [
                "gh",
                "issue",
                "edit",
                "--repo",
                repo,
                str(issue_number),
                "--remove-label",
                ",".join(labels),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return PostReviewResult(success=True)
    except subprocess.CalledProcessError as e:
        return PostReviewResult(success=False, url=e.stderr.strip())


def get_issue_labels(repo: str, issue_number: int) -> list[str]:
    """获取 Issue 当前标签列表。"""
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "view",
                str(issue_number),
                "--repo",
                repo,
                "--json",
                "labels",
                "--jq",
                "[.labels[].name]",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        labels = json.loads(result.stdout)
        return [str(label) for label in labels]
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []


@dataclass
class LabelEvent:
    label: str
    event: str  # "labeled" or "unlabeled"
    created_at: str


def get_issue_label_events(
    repo: str,
    issue_number: int,
    labels: set[str],
    since_days: int = 2,
) -> list[LabelEvent]:
    """获取指定标签在近 N 天内的变更事件（labeled/unlabeled）。"""
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{repo}/issues/{issue_number}/timeline",
                "--jq",
                '.[] | select(.event == "labeled" or .event == "unlabeled") | {event: .event, label: .label.name, created_at: .created_at}',
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        events: list[LabelEvent] = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            obj = json.loads(line)
            if obj["label"] in labels:
                events.append(
                    LabelEvent(
                        label=obj["label"],
                        event=obj["event"],
                        created_at=obj["created_at"],
                    )
                )
        return events
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []


def list_open_issues(
    repo: str, labels: list[str] | None = None, limit: int = 100
) -> list[IssueSummary]:
    """列出开放 Issue 摘要。"""
    cmd = [
        "gh",
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--limit",
        str(limit),
        "--json",
        "number,title,labels,url,createdAt",
    ]
    for label in labels or []:
        cmd.extend(["--label", label])

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        issues = json.loads(result.stdout)
        return [
            IssueSummary(
                number=int(issue["number"]),
                title=str(issue["title"]),
                labels=[str(label["name"]) for label in issue.get("labels", [])],
                url=str(issue.get("url", "")),
                created_at=str(issue.get("createdAt", "")),
            )
            for issue in issues
        ]
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, TypeError):
        return []


def get_issue_summary(repo: str, issue_number: int) -> IssueSummary | None:
    """获取单个开放 Issue 摘要。"""
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "view",
                str(issue_number),
                "--repo",
                repo,
                "--json",
                "number,title,labels,url,createdAt,state",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        issue = json.loads(result.stdout)
        if issue.get("state") != "OPEN":
            return None
        return IssueSummary(
            number=int(issue["number"]),
            title=str(issue["title"]),
            labels=[str(label["name"]) for label in issue.get("labels", [])],
            url=str(issue.get("url", "")),
            created_at=str(issue.get("createdAt", "")),
        )
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, TypeError):
        return None


def replace_managed_issue_labels(
    repo: str,
    issue_number: int,
    labels: list[str],
) -> PostReviewResult:
    """幂等替换 Gearbox 管理标签，再添加新的分类标签。"""
    current_labels = get_issue_labels(repo, issue_number)
    next_labels = list(dict.fromkeys(labels))
    managed_to_remove = [
        label
        for label in current_labels
        if label in MANAGED_BACKLOG_LABELS and label not in next_labels
    ]

    remove_result = remove_issue_labels(repo, issue_number, managed_to_remove)
    if not remove_result.success:
        return remove_result

    return add_issue_labels(repo, issue_number, next_labels)


def get_repo_labels(repo: str) -> list[str]:
    """
    获取仓库现有的标签列表。

    Args:
        repo: 仓库标识

    Returns:
        标签名称列表
    """
    try:
        result = subprocess.run(
            ["gh", "label", "list", "--repo", repo, "--json", "name"],
            check=True,
            capture_output=True,
            text=True,
        )
        labels = json.loads(result.stdout)
        return [label["name"] for label in labels]
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []


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
    repo: str,
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
        configure_authenticated_origin(repo)

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
            ensure_git_author()
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
        configure_authenticated_origin(repo)

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
            ensure_git_author()
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
        return CreatePrResult(success=False, error=_called_process_error_message(e))


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
                "gh",
                "pr",
                "create",
                "--repo",
                repo,
                "--title",
                title,
                "--body",
                body,
                "--head",
                head,
                "--base",
                base,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return CreatePrResult(success=True, pr_url=result.stdout.strip())
    except subprocess.CalledProcessError as e:
        return CreatePrResult(success=False, error=_called_process_error_message(e))


def checkout_branch(branch_name: str) -> None:
    """切换到指定分支。"""
    subprocess.run(["git", "checkout", branch_name], check=True)


def delete_branch(branch_name: str) -> None:
    """删除本地分支。"""
    subprocess.run(["git", "branch", "-D", branch_name], check=False)


def ensure_git_author() -> None:
    """Ensure git commits have an identity in non-interactive CI runners."""
    name = subprocess.run(
        ["git", "config", "--get", "user.name"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    email = subprocess.run(
        ["git", "config", "--get", "user.email"],
        capture_output=True,
        text=True,
    ).stdout.strip()

    actor_id: str | None = None
    if not name or not email:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_PAT")
        if token:
            try:
                result = subprocess.run(
                    [
                        "gh",
                        "api",
                        "user",
                        "--jq",
                        ".login,.id",
                    ],
                    env={**os.environ, "GH_TOKEN": token, "NO_COLOR": "1"},
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                parts = result.stdout.strip().split(",")
                if len(parts) == 2 and parts[0]:
                    name = name or parts[0]
                    actor_id = actor_id or parts[1]
            except Exception:
                pass

    if not name:
        actor = os.environ.get("GITHUB_ACTOR") or "github-actions"
        subprocess.run(["git", "config", "user.name", actor], check=True)
    if not email:
        actor_id = os.environ.get("GITHUB_ACTOR_ID") or "41898282"
        subprocess.run(
            [
                "git",
                "config",
                "user.email",
                f"{actor_id}+github-actions[bot]@users.noreply.github.com",
            ],
            check=True,
        )


def configure_authenticated_origin(repo: str) -> None:
    """Prefer GH_TOKEN for git push so checkout credentials do not shadow PAT scopes."""
    token = os.environ.get("GH_TOKEN")
    if not token:
        return

    # actions/checkout injects an extraheader for github.token that overrides
    # origin credentials. Remove it so PAT scopes on GH_TOKEN are honored.
    subprocess.run(
        ["git", "config", "--unset-all", "http.https://github.com/.extraheader"],
        check=False,
    )
    subprocess.run(
        [
            "git",
            "remote",
            "set-url",
            "origin",
            f"https://x-access-token:{token}@github.com/{repo}.git",
        ],
        check=True,
    )


def _called_process_error_message(error: subprocess.CalledProcessError) -> str:
    stderr = error.stderr.strip() if isinstance(error.stderr, str) else ""
    stdout = error.stdout.strip() if isinstance(error.stdout, str) else ""
    return stderr or stdout or str(error)


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


def write_outputs(
    outputs: dict[str, str],
    path: str = "/tmp/github_output",
) -> None:
    """写入 GITHUB_OUTPUT 文件。"""
    with open(path, "w") as f:
        for key, value in outputs.items():
            f.write(f"{key}={value}\n")


VALID_ISSUE_LABELS = {
    # GitHub defaults
    "bug",
    "documentation",
    "duplicate",
    "enhancement",
    "good first issue",
    "help wanted",
    "invalid",
    "question",
    "wontfix",
    # Priority
    "P0",
    "P1",
    "P2",
    "P3",
    "P4",
    # Complexity
    "complexity:S",
    "complexity:M",
    "complexity:L",
    # Status
    "ready-to-implement",
    "in-progress",
    "needs-clarification",
    "has-pr",
    # Categories
    "security",
    "ci",
}


def create_issue(
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> CreatePrResult:
    """
    创建 GitHub Issue。

    先不带标签创建 Issue（确保一定能创建成功），
    成功后单独调用 add_issue_labels 添加标签（自动创建缺失标签）。
    """
    import re

    cmd = [
        "gh",
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        title,
        "--body",
        body,
    ]

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        url = result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return CreatePrResult(success=False, error=e.stderr.strip())

    if not labels:
        return CreatePrResult(success=True, pr_url=url)

    match = re.search(r"/(\d+)$", url)
    if not match:
        return CreatePrResult(success=True, pr_url=url)

    issue_number = int(match.group(1))
    filtered = [label for label in labels if label in VALID_ISSUE_LABELS]
    if filtered:
        label_result = add_issue_labels(repo, issue_number, filtered)
        if not label_result.success:
            pass  # 标签失败不影响 Issue 创建结果

    return CreatePrResult(success=True, pr_url=url)
