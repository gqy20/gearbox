"""GitHub 操作模块 - 集中管理所有 gh/git 操作"""

import json
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Rate-limit retry configuration (Issue #45)
# ---------------------------------------------------------------------------
_RETRY_MAX_ATTEMPTS: int = 3
_RETRY_BASE_DELAY: float = 1.0  # seconds, doubled each attempt


def _is_rate_limit_error(error: subprocess.CalledProcessError) -> bool:
    """判断是否为 GitHub API 限流错误（可重试）。"""
    stderr = error.stderr.strip() if isinstance(error.stderr, str) else ""
    stdout = error.stdout.strip() if isinstance(error.stdout, str) else ""
    msg = (stderr + " " + stdout).lower()
    return any(
        phrase in msg
        for phrase in (
            "rate limit",
            "secondary rate limit",
            "api rate limit exceeded",
            "abuse detection",
        )
    )


def _run_with_retry(
    cmd: list[str],
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """带指数退避重试的 subprocess.run 封装。

    仅对 GitHub API 限流类错误进行重试；其他错误立即抛出。
    """
    last_exception: subprocess.CalledProcessError | None = None
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        try:
            return subprocess.run(cmd, **kwargs)
        except subprocess.CalledProcessError as exc:
            last_exception = exc
            if not _is_rate_limit_error(exc) or attempt >= _RETRY_MAX_ATTEMPTS:
                raise
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
            time.sleep(delay)
    # Should never reach here because the loop raises on last attempt
    raise last_exception  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Label cache with TTL (Issue #45)
# ---------------------------------------------------------------------------

_LABEL_CACHE_TTL: float = 60.0  # seconds
_label_cache: dict[str, tuple[float, list[str]]] = {}  # repo -> (timestamp, labels)


def clear_label_cache() -> None:
    """清除标签缓存，供测试和需要强制刷新时使用。"""
    _label_cache.clear()


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
    """创建仓库标签。"""
    color, description = _label_metadata(label)
    try:
        subprocess.run(
            [
                "gh",
                "label",
                "create",
                label,
                "--repo",
                repo,
                "--color",
                color,
                "--description",
                description,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return PostReviewResult(success=True)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip()
        if "already exists" in stderr.lower():
            return PostReviewResult(success=True)
        return PostReviewResult(success=False, url=stderr)


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
    """为 Issue 添加标签。"""
    if not labels:
        return PostReviewResult(success=True)

    # 验证标签是否存在（使用缓存版本）
    existing_labels = get_repo_labels(repo)
    unknown_labels = [label for label in labels if label not in existing_labels]
    if unknown_labels:
        import sys

        print(
            f"⚠️ 警告: 以下标签在仓库中不存在，正在创建: {', '.join(unknown_labels)}",
            file=sys.stderr,
        )
        for label in unknown_labels:
            create_result = create_repo_label(repo, label)
            if not create_result.success:
                print(f"⚠️ 创建标签失败: {label}: {create_result.url}", file=sys.stderr)

    return _add_labels_to_issue(repo, issue_number, labels)


def batch_add_issue_labels(
    repo: str,
    issues: list[tuple[int, list[str]]],
) -> list[PostReviewResult]:
    """批量为多个 Issue 添加标签（Issue #45）。

    优化点：
    - 仅调用一次 ``get_repo_labels()``（利用 TTL 缓存）
    - 先一次性创建所有缺失标签，再逐 Issue 添加

    Args:
        repo: 仓库标识
        issues: (issue_number, labels) 列表

    Returns:
        每个 Issue 对应的 PostReviewResult 列表
    """
    if not issues:
        return []

    # Collect all unique labels needed across all issues
    all_labels: set[str] = set()
    for _, labels in issues:
        all_labels.update(labels)

    if not all_labels:
        return [PostReviewResult(success=True) for _ in issues]

    # Single label lookup (cached)
    existing_labels = set(get_repo_labels(repo))
    unknown_labels = sorted(all_labels - existing_labels)

    # Bulk-create all missing labels upfront
    if unknown_labels:
        import sys

        print(
            f"⚠️ 警告: 以下标签在仓库中不存在，正在创建: {', '.join(unknown_labels)}",
            file=sys.stderr,
        )
        for label in unknown_labels:
            create_result = create_repo_label(repo, label)
            if not create_result.success:
                print(
                    f"⚠️ 创建标签失败: {label}: {create_result.url}",
                    file=sys.stderr,
                )

    # Add labels to each issue individually
    results: list[PostReviewResult] = []
    for issue_number, labels in issues:
        filtered = [lb for lb in labels if lb in all_labels]
        if not filtered:
            results.append(PostReviewResult(success=True))
            continue
        result = _add_labels_to_issue(repo, issue_number, filtered)
        results.append(result)

    return results


def _add_labels_to_issue(
    repo: str,
    issue_number: int,
    labels: list[str],
) -> PostReviewResult:
    """为单个 Issue 添加标签（内部方法，不检查/创建标签）。"""
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
    获取仓库现有的标签列表（带 60s TTL 缓存）。

    Args:
        repo: 仓库标识

    Returns:
        标签名称列表
    """
    # Check cache first (Issue #45)
    cached = _label_cache.get(repo)
    if cached is not None:
        timestamp, labels = cached
        if time.monotonic() - timestamp < _LABEL_CACHE_TTL:
            return labels
        # Expired – remove stale entry
        del _label_cache[repo]

    try:
        result = _run_with_retry(
            ["gh", "label", "list", "--repo", repo, "--json", "name"],
            check=True,
            capture_output=True,
            text=True,
        )
        labels = json.loads(result.stdout)
        label_names = [label["name"] for label in labels]
        _label_cache[repo] = (time.monotonic(), label_names)
        return label_names
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
