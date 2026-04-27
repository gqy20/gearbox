"""Git 操作共享工具。"""

import subprocess
import tempfile
from pathlib import Path


def clone_repository(repo: str) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    """将目标仓库克隆到临时目录，供扫描和 Agent 分析统一使用。

    Args:
        repo: 仓库标识（owner/name 或本地 git 仓库路径）

    Returns:
        (clone_root, temp_dir) — clone_root 是仓库根目录，temp_dir 需在用完后 cleanup
    """
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
