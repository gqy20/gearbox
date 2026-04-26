"""Build release-safe Marketplace bundles."""

from __future__ import annotations

import re
import shutil
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ignore_runtime_junk(_directory: str, entries: list[str]) -> set[str]:
    ignored: set[str] = set()
    for entry in entries:
        if entry == "__pycache__" or entry.endswith(".pyc"):
            ignored.add(entry)
    return ignored


def _supported_actions(router_action_text: str) -> list[str]:
    actions = re.findall(r"inputs\.action == '([^']+)'", router_action_text)
    deduped: list[str] = []
    for action in actions:
        if action not in deduped:
            deduped.append(action)
    return deduped


def changelog_path() -> Path:
    return _project_root() / "CHANGELOG.md"


def release_notes_for_version(version: str, changelog_text: str | None = None) -> str:
    normalized_version = version if version.startswith("v") else f"v{version}"
    source = changelog_text
    if source is None:
        source = changelog_path().read_text(encoding="utf-8")

    heading = f"## [{normalized_version}]"
    start = source.find(heading)
    if start == -1:
        raise ValueError(f"Version entry not found in CHANGELOG.md: {normalized_version}")

    next_heading = source.find("\n## [", start + len(heading))
    if next_heading == -1:
        section = source[start:]
    else:
        section = source[start:next_heading]

    return section.strip() + "\n"


def _render_marketplace_readme(actions: list[str]) -> str:
    action_lines = "\n".join(f"- `{action}`" for action in actions)
    return f"""# Gearbox Action

Gearbox 的 Marketplace 发布仓。

这个仓库由主开发仓自动导出，用于提供稳定的 GitHub Action 对外入口。

## 用法

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: audit
    repo: ${{{{ github.repository }}}}
    anthropic_api_key: ${{{{ secrets.ANTHROPIC_AUTH_TOKEN }}}}
```

需要真正的 matrix 并行编排时，请改用主开发仓中的 reusable workflows：

```yaml
jobs:
  audit:
    uses: gqy20/gearbox/.github/workflows/reusable-audit.yml@main
    with:
      repo: owner/repo
      parallel_runs: '3'
      create_issues: false
    secrets: inherit
```

## 支持的动作

{action_lines}

## 仓库说明

- 主开发仓：`gqy20/gearbox`
- 当前仓库：面向 Marketplace 的发布产物
- 如需修改功能、提 issue 或提交代码，请回到主开发仓进行
"""


def build_marketplace_bundle(output_dir: Path) -> Path:
    """Write a Marketplace-ready repository bundle to ``output_dir``."""
    project_root = _project_root()
    output_dir = Path(output_dir)

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    shutil.copytree(
        project_root / "actions",
        output_dir / "actions",
        ignore=_ignore_runtime_junk,
    )
    shutil.copytree(
        project_root / "src",
        output_dir / "src",
        ignore=_ignore_runtime_junk,
    )
    shutil.copy2(project_root / "pyproject.toml", output_dir / "pyproject.toml")
    shutil.copy2(project_root / "uv.lock", output_dir / "uv.lock")
    shutil.copy2(changelog_path(), output_dir / "CHANGELOG.md")

    router_action = project_root / "actions" / "main" / "action.yml"
    router_text = router_action.read_text(encoding="utf-8")
    shutil.copy2(router_action, output_dir / "action.yml")
    (output_dir / "README.md").write_text(
        _render_marketplace_readme(_supported_actions(router_text)),
        encoding="utf-8",
    )

    license_file = project_root / "LICENSE"
    if license_file.exists():
        shutil.copy2(license_file, output_dir / "LICENSE")

    return output_dir
