"""Git 操作共享工具。"""

import re
import subprocess
import tempfile
from pathlib import Path

# GitHub owner/repo 格式正则：
# - owner: 1-39 字符，字母数字开头，允许 . _ -
# - repo: 1-100 字符，允许字母数字 . _ -
# 参考: https://docs.github.com/en/rest/repos/repos?apiVersion=2022-11-28#create-an-organization-repository-for-the-authenticated-user
_REPO_PATTERN = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9._-]{0,38})/[a-zA-Z0-9._-]{1,100}")


def validate_repo_identifier(repo: str) -> None:
    """校验仓库标识符格式。

    支持两种模式：
    1. 本地路径 — 已存在的文件系统路径（以 / 或 ./ 或 ../ 开头，或包含路径分隔符）
    2. 远程仓库 — ``owner/name`` 格式的 GitHub 仓库标识符

    Args:
        repo: 仓库标识字符串

    Raises:
        ValueError: 当 repo 既不是有效本地路径也不是合法的 owner/name 格式时
    """
    if not repo:
        raise ValueError("repo 参数不能为空，期望格式: owner/repo 或本地路径")

    # 本地路径：已存在的目录或文件
    if Path(repo).exists():
        return

    # 远程仓库：必须匹配 owner/name 格式
    if not _REPO_PATTERN.fullmatch(repo):
        raise ValueError(
            f"repo '{repo}' 格式无效，期望格式: owner/repo (如 gqy20/gearbox) 或本地路径"
        )


def clone_repository(repo: str) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    """将目标仓库克隆到临时目录，供扫描和 Agent 分析统一使用。

    Args:
        repo: 仓库标识（owner/name 或本地 git 仓库路径）

    Returns:
        (clone_root, temp_dir) — clone_root 是仓库根目录，temp_dir 需在用完后 cleanup
    """
    validate_repo_identifier(repo)

    temp_dir = tempfile.TemporaryDirectory(prefix="gearbox-clone-")
    clone_root = Path(temp_dir.name) / "repo"

    if Path(repo).exists():
        source = str(Path(repo).resolve())
        cmd = ["git", "clone", "--depth", "1", source, str(clone_root)]
    else:
        cmd = ["gh", "repo", "clone", repo, str(clone_root), "--", "--depth", "1"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        temp_dir.cleanup()
        stderr = result.stderr.strip() or result.stdout.strip() or "unknown clone error"
        raise RuntimeError(f"clone failed for {repo}: {stderr}")

    return clone_root, temp_dir
