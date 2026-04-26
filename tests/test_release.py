"""Tests for Marketplace bundle export."""

from pathlib import Path

from gearbox.release import build_marketplace_bundle


def test_build_marketplace_bundle_writes_expected_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "gearbox-action"

    build_marketplace_bundle(output_dir)

    assert (output_dir / "action.yml").exists()
    assert (output_dir / "README.md").exists()
    assert (output_dir / "pyproject.toml").exists()
    assert (output_dir / "actions" / "audit" / "action.yml").exists()
    assert (output_dir / "actions" / "_setup" / "action.yml").exists()
    assert (output_dir / "src" / "gearbox" / "cli.py").exists()


def test_build_marketplace_bundle_renders_router_and_runtime_setup(tmp_path: Path) -> None:
    output_dir = tmp_path / "gearbox-action"

    build_marketplace_bundle(output_dir)

    root_action = (output_dir / "action.yml").read_text(encoding="utf-8")
    setup_action = (output_dir / "actions" / "_setup" / "action.yml").read_text(
        encoding="utf-8"
    )

    assert "name: 'Gearbox'" in root_action
    assert "uses: ./actions/audit" in root_action
    assert "uses: ./actions/review" in root_action
    assert "python3 -m pip install" in setup_action
    assert "${GITHUB_ACTION_PATH}/../.." in setup_action
