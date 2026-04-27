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
    assert "sudo apt-get update -qq && sudo apt-get install -y -qq $TOOLS" in setup_action
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


def test_cleanup_action_and_workflow_are_conservative() -> None:
    root = Path(__file__).resolve().parents[1]

    action = (root / "actions" / "cleanup" / "action.yml").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "cleanup.yml").read_text(encoding="utf-8")
    workflow_entry = (root / "actions" / "workflow-entry" / "action.yml").read_text(
        encoding="utf-8"
    )

    assert "gearbox cleanup" in action
    assert "--dry-run" in action
    assert "--no-dry-run" in action
    assert "--protect-open-prs" in action
    assert "--no-protect-open-prs" in action
    assert "pull_request:" in workflow
    assert "types: [closed]" in workflow
    assert "workflow_dispatch:" in workflow
    assert "protect_open_prs:" in workflow
    # Branch naming pattern is now in workflow-entry action
    assert r"^feat/issue-([0-9]+)-run-[0-9]+$" in workflow_entry
    assert r"^gearbox/issue-([0-9]+)$" not in workflow
    assert "github.event.pull_request.merged == false" in workflow
    assert "cleanup-restore-unmerged-pr" in workflow
    assert "contents: write" in workflow
    assert "issues: write" in workflow


def test_matrix_action_exposes_step_output_and_local_callers_checkout_first() -> None:
    root = Path(__file__).resolve().parents[1]

    matrix_action = (root / "actions" / "matrix" / "action.yml").read_text(encoding="utf-8")
    local_matrix_workflows = [
        root / ".github" / "workflows" / "audit.yml",
        root / ".github" / "workflows" / "backlog.yml",
        root / ".github" / "workflows" / "reusable-implement.yml",
    ]

    assert "value: ${{ steps.build.outputs.matrix_json }}" in matrix_action

    for workflow_path in local_matrix_workflows:
        workflow = workflow_path.read_text(encoding="utf-8")
        matrix_use = workflow.index("uses: ./actions/matrix")
        checkout_use = workflow.index("uses: actions/checkout")
        assert checkout_use < matrix_use


def test_workflow_entry_keeps_target_repo_override_and_has_no_dead_inputs() -> None:
    root = Path(__file__).resolve().parents[1]

    action = (root / "actions" / "workflow-entry" / "action.yml").read_text(encoding="utf-8")

    assert 'TARGET_REPO="${TARGET_REPO:-$DEFAULT_REPO}"' in action
    assert "bot_logins:" not in action
    assert "installation_id:" not in action


def test_reusable_implement_pushes_candidates_without_creating_prs() -> None:
    root = Path(__file__).resolve().parents[1]

    workflow = (root / ".github" / "workflows" / "reusable-implement.yml").read_text(
        encoding="utf-8"
    )

    assert "push_candidate_branch: 'true'" in workflow
    assert "create_pr: 'false'" in workflow
    assert "candidate_branch_suffix: run-${{ matrix.run_id }}" in workflow
    assert "apply_side_effects" not in workflow


def test_issue_command_workflows_do_not_subscribe_to_all_issue_changes() -> None:
    root = Path(__file__).resolve().parents[1]

    for workflow_name in ["audit.yml", "backlog.yml"]:
        workflow = (root / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
        assert "\n  issues:\n    types:" not in workflow
        assert "github.event_name == 'issues'" not in workflow
        assert "issue_comment:" in workflow


def test_review_and_audit_commands_do_not_listen_to_inline_review_comments() -> None:
    root = Path(__file__).resolve().parents[1]

    for workflow_name in ["review.yml", "audit.yml"]:
        workflow = (root / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
        assert "pull_request_review_comment:" not in workflow
        assert "github.event_name == 'pull_request_review_comment'" not in workflow
        assert "issue_comment:" in workflow
        assert "copilot-pull-request-reviewer" in workflow
        assert "github-actions[bot]" in workflow
        assert "dependabot[bot]" in workflow


def test_audit_action_does_not_support_removed_comment_events() -> None:
    root = Path(__file__).resolve().parents[1]

    action = (root / "actions" / "audit" / "action.yml").read_text(encoding="utf-8")
    reusable = (root / ".github" / "workflows" / "reusable-audit.yml").read_text(encoding="utf-8")

    assert "pull_request_review_comment" not in action
    assert 'event_type in ("issue_comment", "issues")' not in action
    assert 'event_type == "pull_request_review_comment"' not in action
    assert "github.event_name == 'issues'" not in reusable
    assert "github.event_name == 'pull_request_review_comment'" not in reusable


def test_review_command_requires_pr_conversation_comment() -> None:
    root = Path(__file__).resolve().parents[1]

    workflow = (root / ".github" / "workflows" / "review.yml").read_text(encoding="utf-8")

    assert "github.event.issue.pull_request" in workflow
    assert "contains(github.event.comment.body, '@review')" in workflow
    assert (
        "pr_number: ${{ github.event_name == 'workflow_dispatch' && inputs.pr_number || "
        "github.event.pull_request.number || github.event.issue.number }}" in workflow
    )


def test_reusable_workflow_aggregators_use_action_source() -> None:
    root = Path(__file__).resolve().parents[1]

    workflow_paths = [
        root / ".github" / "workflows" / "reusable-review.yml",
        root / ".github" / "workflows" / "reusable-implement.yml",
        root / ".github" / "workflows" / "backlog.yml",
        root / ".github" / "workflows" / "audit.yml",
        root / ".github" / "workflows" / "reusable-audit.yml",
    ]

    for workflow_path in workflow_paths:
        workflow = workflow_path.read_text(encoding="utf-8")
        assert 'uv run --directory "$GITHUB_WORKSPACE" gearbox agent' not in workflow
        assert (
            'uv run --directory "$GEARBOX_ACTION_ROOT" gearbox agent' in workflow
            or 'uv run --project "$GEARBOX_ACTION_ROOT" --directory "$GITHUB_WORKSPACE" gearbox agent'
            in workflow
        )


def test_implement_aggregation_runs_agent_from_checked_out_workspace() -> None:
    root = Path(__file__).resolve().parents[1]

    workflow = (root / ".github" / "workflows" / "reusable-implement.yml").read_text(
        encoding="utf-8"
    )

    assert (
        'uv run --project "$GEARBOX_ACTION_ROOT" '
        '--directory "$GITHUB_WORKSPACE" gearbox agent implement-select'
    ) in workflow
    assert 'uv run --directory "$GEARBOX_ACTION_ROOT" gearbox agent implement-select' not in (
        workflow
    )


def test_reusable_workflow_aggregators_use_workspace_artifact_paths() -> None:
    root = Path(__file__).resolve().parents[1]

    workflow_paths = [
        root / ".github" / "workflows" / "reusable-review.yml",
        root / ".github" / "workflows" / "reusable-implement.yml",
        root / ".github" / "workflows" / "backlog.yml",
        root / ".github" / "workflows" / "audit.yml",
        root / ".github" / "workflows" / "reusable-audit.yml",
    ]

    for workflow_path in workflow_paths:
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "--input-root ./" not in workflow
        assert "--artifact-path ./" not in workflow
        assert "--output-dir ./" not in workflow
        assert "path: ${{ github.workspace }}/" in workflow


def test_dispatch_workflow_uses_parallel_implement_aggregation() -> None:
    root = Path(__file__).resolve().parents[1]

    workflow = (root / ".github" / "workflows" / "dispatch.yml").read_text(encoding="utf-8")

    assert "uses: ./.github/workflows/reusable-implement.yml" in workflow
    assert "parallel_runs: ${{ needs.plan.outputs.max_parallel }}" in workflow
    assert (
        "if: ${{ needs.plan.outputs.has_items == 'true' "
        "&& needs.plan.outputs.dry_run == 'false' }}" in workflow
    )
    assert "uses: ./actions/dispatch" not in workflow


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
