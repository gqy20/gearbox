"""Build release-safe Marketplace bundles."""

from __future__ import annotations

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


def _render_marketplace_readme() -> str:
    return """# Gearbox Action

Marketplace-facing release repository for Gearbox.

This repository is generated from the main development repository and is intended
to provide a stable GitHub Action entrypoint for external consumers.

## Usage

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: audit
    repo: ${{ github.repository }}
    anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
```

## Supported actions

- `audit`
- `triage`
- `implement`
- `review`
- `publish`

## Source of truth

Development happens in the main `gearbox` repository. This bundle is exported for
release and Marketplace publication.
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

    router_action = project_root / "actions" / "main" / "action.yml"
    shutil.copy2(router_action, output_dir / "action.yml")
    (output_dir / "README.md").write_text(_render_marketplace_readme(), encoding="utf-8")

    license_file = project_root / "LICENSE"
    if license_file.exists():
        shutil.copy2(license_file, output_dir / "LICENSE")

    return output_dir
