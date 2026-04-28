"""Tests for GitHub Actions workflow and action file structure."""

import re
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


class TestCleanupWorkflow:
    def test_cleanup_action_and_workflow_are_conservative(self) -> None:
        root = _root()
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
        assert r"^feat/issue-([0-9]+)-run-[0-9]+$" in workflow_entry
        assert r"^gearbox/issue-([0-9]+)$" not in workflow
        assert "github.event.pull_request.merged == false" in workflow
        assert "cleanup-restore-unmerged-pr" in workflow
        assert "contents: write" in workflow
        assert "issues: write" in workflow


class TestMatrixWorkflow:
    def test_matrix_action_exposes_step_output_and_local_callers_checkout_first(self) -> None:
        root = _root()
        matrix_action = (root / "actions" / "matrix" / "action.yml").read_text(encoding="utf-8")
        local_matrix_workflows = [
            root / ".github" / "workflows" / "audit.yml",
            root / ".github" / "workflows" / "backlog.yml",
            root / ".github" / "workflows" / "reusable-implement.yml",
        ]

        assert "value: ${{ steps.build.outputs.matrix_json }}" in matrix_action
        assert "${{ fromJSON(...) }}" not in matrix_action

        for workflow_path in local_matrix_workflows:
            workflow = workflow_path.read_text(encoding="utf-8")
            matrix_use = workflow.index("uses: ./actions/matrix")
            checkout_use = workflow.index("uses: actions/checkout")
            assert checkout_use < matrix_use


class TestAggregators:
    def test_aggregators_do_not_run_when_plan_fails(self) -> None:
        root = _root()
        workflow_paths = [
            root / ".github" / "workflows" / "audit.yml",
            root / ".github" / "workflows" / "backlog.yml",
            root / ".github" / "workflows" / "reusable-audit.yml",
            root / ".github" / "workflows" / "reusable-implement.yml",
            root / ".github" / "workflows" / "reusable-review.yml",
        ]

        for workflow_path in workflow_paths:
            workflow = workflow_path.read_text(encoding="utf-8")
            assert "needs.plan.result == 'success'" in workflow

    def test_reusable_workflow_aggregators_use_action_source(self) -> None:
        root = _root()
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

    def test_implement_aggregation_runs_agent_from_checked_out_workspace(self) -> None:
        root = _root()
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

    def test_reusable_workflow_aggregators_use_workspace_artifact_paths(self) -> None:
        root = _root()
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


class TestWorkflowEntry:
    def test_workflow_entry_keeps_target_repo_override_and_has_no_dead_inputs(self) -> None:
        root = _root()
        action = (root / "actions" / "workflow-entry" / "action.yml").read_text(encoding="utf-8")

        assert 'TARGET_REPO="${TARGET_REPO:-$DEFAULT_REPO}"' in action
        assert "bot_logins:" not in action
        assert "installation_id:" not in action


class TestReusableImplement:
    def test_reusable_implement_pushes_candidates_without_creating_prs(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "reusable-implement.yml").read_text(
            encoding="utf-8"
        )

        assert "push_candidate_branch: 'true'" in workflow
        assert "create_pr: 'false'" in workflow
        assert "candidate_branch_suffix: run-${{ matrix.run_id }}" in workflow
        assert "apply_side_effects" not in workflow


class TestIssueCommentWorkflows:
    def test_issue_command_workflows_do_not_subscribe_to_all_issue_changes(self) -> None:
        root = _root()

        for workflow_name in ["audit.yml", "backlog.yml"]:
            workflow = (root / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
            assert "\n  issues:\n    types:" not in workflow
            assert "github.event_name == 'issues'" not in workflow
            assert "issue_comment:" in workflow

    def test_review_and_audit_commands_do_not_listen_to_inline_review_comments(self) -> None:
        root = _root()

        for workflow_name in ["review.yml", "audit.yml"]:
            workflow = (root / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
            assert "pull_request_review_comment:" not in workflow
            assert "github.event_name == 'pull_request_review_comment'" not in workflow
            assert "issue_comment:" in workflow
            assert "copilot-pull-request-reviewer" in workflow
            assert "github-actions[bot]" in workflow
            assert "dependabot[bot]" in workflow

    def test_audit_action_does_not_support_removed_comment_events(self) -> None:
        root = _root()
        action = (root / "actions" / "audit" / "action.yml").read_text(encoding="utf-8")
        reusable = (root / ".github" / "workflows" / "reusable-audit.yml").read_text(
            encoding="utf-8"
        )

        assert "pull_request_review_comment" not in action
        assert 'event_type in ("issue_comment", "issues")' not in action
        assert 'event_type == "pull_request_review_comment"' not in action
        assert "github.event_name == 'issues'" not in reusable
        assert "github.event_name == 'pull_request_review_comment'" not in reusable

    def test_review_command_requires_pr_conversation_comment(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "review.yml").read_text(encoding="utf-8")

        assert "github.event.issue.pull_request" in workflow
        assert "contains(github.event.comment.body, '@review')" in workflow
        assert (
            "pr_number: ${{ github.event_name == 'workflow_dispatch' && inputs.pr_number || "
            "github.event.pull_request.number || github.event.issue.number }}" in workflow
        )


class TestBacklogWorkflow:
    def test_backlog_schedule_uses_quiet_planning_mode(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "backlog.yml").read_text(encoding="utf-8")

        assert "schedule:" in workflow
        assert re.search(r"cron:\s*'[^\']+'", workflow)
        assert "gearbox backlog plan" in workflow
        assert "--comment-mode" in workflow
        assert "needs.plan.outputs.comment_mode" in workflow


class TestDispatchWorkflow:
    def test_dispatch_workflow_uses_parallel_implement_aggregation(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "dispatch.yml").read_text(encoding="utf-8")

        assert "uses: ./.github/workflows/reusable-implement.yml" in workflow
        assert "parallel_runs: ${{ needs.plan.outputs.max_parallel }}" in workflow
        assert (
            "if: ${{ needs.plan.outputs.has_items == 'true' "
            "&& needs.plan.outputs.dry_run == 'false' }}" in workflow
        )
        assert "mark-has-pr:" in workflow
        assert "needs.implement.result == 'success'" in workflow
        assert "--add-label has-pr" in workflow
        assert "uses: ./actions/dispatch" not in workflow

    def test_dispatch_workflow_restores_issue_on_implement_failure(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "dispatch.yml").read_text(encoding="utf-8")

        assert "restore-failed-issues:" in workflow
        assert "needs.implement.result != 'success'" in workflow
        assert "--remove-label in-progress" in workflow
        assert "--add-label ready-to-implement" in workflow
        assert "Gearbox dispatch failed" in workflow

    def test_dispatch_workflow_does_not_auto_merge(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "dispatch.yml").read_text(encoding="utf-8")

        assert "enable-auto-merge:" not in workflow
        assert "gh pr merge" not in workflow

    def test_dispatch_schedule_has_no_priority_restriction(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "dispatch.yml").read_text(encoding="utf-8")

        assert "schedule:" in workflow
        assert re.search(r"cron:\s*'[^\']+'", workflow)
        assert "ALLOWED_PRIORITIES: ''" in workflow
        assert (
            "DRY_RUN: ${{ github.event_name == 'workflow_dispatch' && inputs.dry_run == false && 'false' || github.event_name == 'schedule' && 'false' || 'true' }}"
            in workflow
        )


class TestAutoMergeWorkflow:
    def test_auto_merge_triggers_on_pull_request_review_submitted(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "auto-merge.yml").read_text(encoding="utf-8")

        assert "pull_request_review:" in workflow
        assert "types: [submitted]" in workflow

    def test_auto_merge_supports_manual_workflow_dispatch(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "auto-merge.yml").read_text(encoding="utf-8")

        assert "workflow_dispatch:" in workflow
        assert "pr_number:" in workflow

    def test_auto_merge_filters_bot_reviewers(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "auto-merge.yml").read_text(encoding="utf-8")

        assert "github.event.review.state == 'approved'" in workflow
        assert "github-actions[bot]" in workflow
        assert "dependabot[bot]" in workflow
        assert "copilot-pull-request-reviewer" in workflow
        assert "github.event.installation_id" in workflow

    def test_auto_merge_validates_gearbox_branch_pattern(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "auto-merge.yml").read_text(encoding="utf-8")

        assert r"^feat/issue-" in workflow
        assert "headRefName" in workflow

    def test_auto_merge_rejects_draft_and_non_open_prs(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "auto-merge.yml").read_text(encoding="utf-8")

        assert "isDraft" in workflow
        assert '"OPEN"' in workflow
        assert "mergeStateStatus" in workflow

    def test_auto_merge_prevents_self_review_approval(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "auto-merge.yml").read_text(encoding="utf-8")

        assert "self-review" in workflow.lower() or "AUTHOR_LOGIN" in workflow
        assert "review.user.login" in workflow
        assert "author.login" in workflow

    def test_auto_merge_uses_squash_with_auto_flag(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "auto-merge.yml").read_text(encoding="utf-8")

        assert "gh pr merge" in workflow
        assert "--auto" in workflow
        assert "--squash" in workflow
        assert "--delete-branch" in workflow

    def test_auto_merge_has_correct_permissions(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "auto-merge.yml").read_text(encoding="utf-8")

        assert "contents: write" in workflow
        assert "pull-requests: write" in workflow

    def test_auto_merge_uses_concurrency_group_with_pr_number(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "auto-merge.yml").read_text(encoding="utf-8")

        assert "concurrency:" in workflow
        assert "cancel-in-progress: false" in workflow
        assert "auto-merge-${{ github.event.pull_request.number" in workflow

    def test_auto_merge_provides_clear_skip_output_on_validation_failure(self) -> None:
        root = _root()
        workflow = (root / ".github" / "workflows" / "auto-merge.yml").read_text(encoding="utf-8")

        assert "skip=true" in workflow
        assert "skip_reason=" in workflow
        assert "::notice::" in workflow
        assert "::warning::" in workflow
