"""Tests for Marketplace bundle export."""

from pathlib import Path

from gearbox.release import build_marketplace_bundle, release_notes_for_version


def test_build_marketplace_bundle_writes_expected_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "gearbox-action"

    build_marketplace_bundle(output_dir)

    assert (output_dir / "action.yml").exists()
    assert (output_dir / "README.md").exists()
    assert (output_dir / "CHANGELOG.md").exists()
    assert (output_dir / "pyproject.toml").exists()
    assert (output_dir / "uv.lock").exists()
    assert (output_dir / "actions" / "audit" / "action.yml").exists()
    assert (output_dir / "actions" / "cleanup" / "action.yml").exists()
    assert (output_dir / "actions" / "dispatch" / "action.yml").exists()
    assert (output_dir / "actions" / "_runtime" / "action.yml").exists()
    assert (output_dir / "actions" / "_setup" / "action.yml").exists()
    assert (output_dir / "actions" / "workflow-entry" / "action.yml").exists()
    assert (output_dir / "actions" / "matrix" / "action.yml").exists()
    assert (output_dir / "src" / "gearbox" / "cli.py").exists()


def test_build_marketplace_bundle_renders_router_and_runtime_setup(tmp_path: Path) -> None:
    output_dir = tmp_path / "gearbox-action"

    build_marketplace_bundle(output_dir)

    root_action = (output_dir / "action.yml").read_text(encoding="utf-8")
    runtime_action = (output_dir / "actions" / "_runtime" / "action.yml").read_text(
        encoding="utf-8"
    )
    setup_action = (output_dir / "actions" / "_setup" / "action.yml").read_text(encoding="utf-8")
    audit_action = (output_dir / "actions" / "audit" / "action.yml").read_text(encoding="utf-8")
    publish_action = (output_dir / "actions" / "publish" / "action.yml").read_text(encoding="utf-8")
    readme = (output_dir / "README.md").read_text(encoding="utf-8")

    assert "name: Gearbox AI Flywheel" in root_action
    assert "uses: ./actions/audit" in root_action
    assert "uses: ./actions/cleanup" in root_action
    assert "uses: ./actions/dispatch" in root_action
    assert "uses: ./actions/review" in root_action
    assert "curl -LsSf https://astral.sh/uv/install.sh | sh" in runtime_action
    assert 'uv sync --directory "${GITHUB_ACTION_PATH}/../.."' in runtime_action
    assert "uses: ./actions/_runtime" in setup_action
    assert "uv tool install semgrep" in setup_action
    assert "uv tool install deptry" in setup_action
    assert 'sudo apt-get update -qq && sudo apt-get install -y -qq "$TOOLS"' in setup_action
    assert "python3 -m pip install" not in setup_action
    assert "pip install deptry" not in setup_action
    assert "uses: ./actions/_runtime" in publish_action
    assert "uses: ./actions/_setup" not in publish_action
    assert 'echo "::error::No issues.json found"' in audit_action
    assert 'export PATH=\\"' not in audit_action
    assert 'uv run --directory \\"' not in audit_action
    assert "python <<'PY'" in audit_action
    assert "# Gearbox Action" in readme
    assert "Marketplace 发布仓" in readme
    assert "- `audit`" in readme
    assert "- `review`" in readme


def test_composite_actions_write_outputs_to_workspace() -> None:
    root = Path(__file__).resolve().parents[1]

    review_action = (root / "actions" / "review" / "action.yml").read_text(encoding="utf-8")
    backlog_action = (root / "actions" / "backlog" / "action.yml").read_text(encoding="utf-8")
    implement_action = (root / "actions" / "implement" / "action.yml").read_text(encoding="utf-8")
    audit_action = (root / "actions" / "audit" / "action.yml").read_text(encoding="utf-8")

    assert 'ARTIFACT_PATH="${GITHUB_WORKSPACE}/' in review_action
    assert 'ARTIFACT_PATH="${GITHUB_WORKSPACE}/' in backlog_action
    assert 'ARTIFACT_PATH="${GITHUB_WORKSPACE}/' in implement_action
    assert 'OUTPUT_DIR="${GITHUB_WORKSPACE}/' in audit_action


def test_implement_action_runs_agent_from_checked_out_workspace() -> None:
    root = Path(__file__).resolve().parents[1]

    implement_action = (root / "actions" / "implement" / "action.yml").read_text(encoding="utf-8")

    assert (
        'uv run --project "${GITHUB_ACTION_PATH}/../.." '
        '--directory "$GITHUB_WORKSPACE" gearbox agent implement'
    ) in implement_action
    assert 'uv run --directory "${GITHUB_ACTION_PATH}/../.." gearbox agent implement' not in (
        implement_action
    )


def test_implement_action_uses_explicit_branch_and_pr_controls() -> None:
    root = Path(__file__).resolve().parents[1]

    implement_action = (root / "actions" / "implement" / "action.yml").read_text(encoding="utf-8")

    assert "push_candidate_branch:" in implement_action
    assert "create_pr:" in implement_action
    assert "candidate_branch_suffix:" in implement_action
    assert "--push-candidate-branch" in implement_action
    assert "--create-pr" in implement_action
    assert "--candidate-branch-suffix" in implement_action
    assert "apply_side_effects" not in implement_action
    assert "--apply-side-effects" not in implement_action


def test_build_marketplace_bundle_excludes_python_cache_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "gearbox-action"

    build_marketplace_bundle(output_dir)

    assert not list(output_dir.rglob("__pycache__"))
    assert not list(output_dir.rglob("*.pyc"))


def test_build_marketplace_bundle_readme_tracks_router_actions(tmp_path: Path) -> None:
    output_dir = tmp_path / "gearbox-action"

    build_marketplace_bundle(output_dir)

    readme = (output_dir / "README.md").read_text(encoding="utf-8")

    expected_actions = ["audit", "backlog", "cleanup", "dispatch", "implement", "review", "publish"]
    for action in expected_actions:
        assert f"- `{action}`" in readme


def test_release_notes_for_version_returns_section() -> None:
    changelog = """
# Changelog

## [v1.2.0] - 2026-04-26

### Added

- Something new

## [v1.1.0] - 2026-04-25

### Fixed

- Something old
"""

    notes = release_notes_for_version("v1.2.0", changelog)

    assert "## [v1.2.0] - 2026-04-26" in notes
    assert "Something new" in notes
    assert "v1.1.0" not in notes


def test_release_notes_for_version_requires_matching_section() -> None:
    changelog = """
# Changelog

## [v1.0.0] - 2026-04-26
"""

    try:
        release_notes_for_version("v9.9.9", changelog)
    except ValueError as exc:
        assert "v9.9.9" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing version entry")
