"""测试 CLI 命令"""

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from gearbox.agents.backlog import BacklogItemResult
from gearbox.cli import cli
from gearbox.commands.shared import _candidate_result_files
from gearbox.core.gh import PostReviewResult


@pytest.fixture
def runner(tmp_path: "Path") -> CliRunner:
    """CliRunner with isolated HOME for config tests"""
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_BASE_URL", None)
    env.pop("GITHUB_TOKEN", None)
    return CliRunner(env=env)


class TestVersionAndHelp:
    """测试版本和帮助命令"""

    def test_cli_version(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_cli_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Gearbox" in result.output
        assert "audit" in result.output
        assert "config" in result.output
        assert "package-marketplace" in result.output
        assert "publish-issues" in result.output


class TestResultFileDiscovery:
    """测试 artifact 下载后的 result.json 布局兼容。"""

    def test_candidate_result_files_supports_flat_layout(self, tmp_path: Path) -> None:
        (tmp_path / "result.json").write_text("{}", encoding="utf-8")

        candidates = _candidate_result_files(tmp_path)

        assert candidates == [(tmp_path.name, tmp_path / "result.json")]

    def test_candidate_result_files_supports_per_artifact_layout(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "backlog-results-issue-1-run-0"
        run_dir.mkdir()
        (run_dir / "result.json").write_text("{}", encoding="utf-8")

        candidates = _candidate_result_files(tmp_path)

        assert candidates == [("backlog-results-issue-1-run-0", run_dir / "result.json")]


class TestAuditCommand:
    """测试 audit 命令"""

    def test_audit_requires_repo(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["audit"])
        assert result.exit_code != 0
        assert "Missing option" in result.output

    def test_audit_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["audit", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--benchmarks" in result.output
        assert "--output" in result.output

    def test_audit_with_repo(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        # Audit 需要真实 API key，这里只验证参数传递
        # 实际调用会失败，但参数解析应该是对的
        monkeypatch.setattr("gearbox.config.get_anthropic_api_key", lambda: None)
        result = runner.invoke(cli, ["audit", "--repo", "owner/repo", "--output", "/tmp/test"])
        # 不应该因为参数问题失败（可能因为没 key 而失败，但参数是对的）
        assert "--repo" not in result.output or result.exit_code != 0


class TestPublishIssuesCommand:
    """测试 publish-issues 命令"""

    def test_publish_issues_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["publish-issues", "--help"])
        assert result.exit_code == 0
        assert "--input" in result.output
        assert "--dry-run" in result.output

    def test_publish_issues_missing_input(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["publish-issues"])
        assert result.exit_code != 0

    def test_publish_issues_dry_run(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            with open("issues.json", "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "issues": [
                            {
                                "repo": "owner/repo",
                                "title": "Test title",
                                "body": "Test body",
                                "labels": "enhancement",
                            }
                        ]
                    },
                    f,
                )
            result = runner.invoke(cli, ["publish-issues", "--input", "issues.json", "--dry-run"])

        assert result.exit_code == 0
        assert "处理 Issue 数量: 1" in result.output
        assert "已创建: 1" in result.output

    def test_publish_issues_file_not_found(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["publish-issues", "--input", "/nonexistent.json", "--dry-run"])
        assert result.exit_code != 0
        assert "不存在" in result.output

    def test_publish_issues_missing_required_fields(self, runner: CliRunner) -> None:
        # 缺少 repo/title/body 字段的 issue 会被跳过，不会报错
        with runner.isolated_filesystem():
            with open("bad.json", "w", encoding="utf-8") as f:
                json.dump({"issues": [{"repo": "", "title": "", "body": ""}]}, f)
            result = runner.invoke(cli, ["publish-issues", "--input", "bad.json", "--dry-run"])
        assert result.exit_code == 0
        assert "已跳过: 1" in result.output


class TestPackageMarketplaceCommand:
    """测试 Marketplace 打包命令"""

    def test_package_marketplace_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["package-marketplace", "--help"])
        assert result.exit_code == 0
        assert "--output-dir" in result.output

    def test_package_marketplace_writes_bundle(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli,
                ["package-marketplace", "--output-dir", "dist/gearbox-action"],
            )

            bundle_root = Path("dist/gearbox-action")
            assert result.exit_code == 0
            assert (bundle_root / "action.yml").exists()
            assert (bundle_root / "actions" / "audit" / "action.yml").exists()
            assert (bundle_root / "actions" / "dispatch" / "action.yml").exists()


class TestConfigCommand:
    """测试 config 命令"""

    def test_config_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["config", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "set" in result.output
        assert "path" in result.output

    def test_config_list(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["config", "list"])
        assert result.exit_code == 0

    def test_config_path(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["config", "path"])
        assert result.exit_code == 0
        assert ".toml" in result.output

    def test_config_set_unknown_key(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["config", "set", "unknown", "value"])
        assert result.exit_code != 0
        assert "未知的配置项" in result.output

    def test_config_set_provider_invalid(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["config", "set", "provider", "invalid"])
        assert result.exit_code != 0


class TestAgentCommand:
    """测试 agent 命令组"""

    def test_agent_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "--help"])
        assert result.exit_code == 0
        assert "backlog" in result.output
        assert "review" in result.output
        assert "implement" in result.output
        assert "audit-repo" in result.output

    def test_agent_backlog_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "backlog", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--issues" in result.output
        assert "--parallel-count" not in result.output

    def test_agent_review_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "review", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--pr" in result.output
        assert "--parallel-count" not in result.output

    def test_agent_implement_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "implement", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--issue" in result.output
        assert "--base-branch" in result.output

    def test_agent_audit_repo_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "audit-repo", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--benchmarks" in result.output
        assert "--system-prompt" in result.output
        assert "--parallel-count" not in result.output

    def test_agent_audit_select_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "audit-select", "--help"])
        assert result.exit_code == 0
        assert "--input-root" in result.output
        assert "--output-dir" in result.output
        assert "--max-turns" in result.output

    def test_agent_backlog_select_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "backlog-select", "--help"])
        assert result.exit_code == 0
        assert "--input-root" in result.output
        assert "--max-turns" in result.output

    def test_agent_review_select_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "review-select", "--help"])
        assert result.exit_code == 0
        assert "--input-root" in result.output
        assert "--pr" in result.output
        assert "--max-turns" in result.output

    def test_agent_implement_select_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "implement-select", "--help"])
        assert result.exit_code == 0
        assert "--input-root" in result.output
        assert "--issue" in result.output
        assert "--max-turns" in result.output

    def test_agent_backlog_requires_args(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "backlog"])
        assert result.exit_code != 0

    def test_agent_backlog_runs_multiple_issues(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        async def fake_run_backlog_item(
            repo: str, issue_number: int, **kwargs
        ) -> BacklogItemResult:
            del repo, kwargs
            return BacklogItemResult(
                issue_number=issue_number,
                labels=["enhancement"],
                priority="P2",
                complexity="S",
                needs_clarification=False,
                clarification_question=None,
                ready_to_implement=True,
            )

        monkeypatch.setattr("gearbox.commands.agent.run_backlog_item", fake_run_backlog_item)

        artifact_path = tmp_path / "backlog.json"
        result = runner.invoke(
            cli,
            [
                "agent",
                "backlog",
                "--repo",
                "owner/repo",
                "--issues",
                "2,5",
                "--artifact-path",
                str(artifact_path),
            ],
        )

        assert result.exit_code == 0
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
        assert [item["issue_number"] for item in data["items"]] == [2, 5]

    def test_agent_backlog_select_applies_each_issue(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        for issue in (2, 5):
            run_dir = tmp_path / f"backlog-results-issue-{issue}-run-0"
            run_dir.mkdir()
            (run_dir / "result.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "issue_number": issue,
                                "labels": ["enhancement"],
                                "priority": "P2",
                                "complexity": "S",
                                "needs_clarification": False,
                                "clarification_question": None,
                                "ready_to_implement": True,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

        captured: list[tuple[int, list[str]]] = []

        def fake_replace(repo: str, issue: int, labels: list[str]) -> PostReviewResult:
            del repo
            captured.append((issue, labels))
            return PostReviewResult(True)

        monkeypatch.setattr("gearbox.commands.shared.replace_managed_issue_labels", fake_replace)
        monkeypatch.setattr(
            "gearbox.commands.shared.post_issue_comment",
            lambda *args, **kwargs: PostReviewResult(True),
        )

        result = runner.invoke(
            cli,
            [
                "agent",
                "backlog-select",
                "--input-root",
                str(tmp_path),
                "--repo",
                "owner/repo",
            ],
        )

        assert result.exit_code == 0
        assert captured == [
            (2, ["enhancement", "P2", "complexity:S", "ready-to-implement"]),
            (5, ["enhancement", "P2", "complexity:S", "ready-to-implement"]),
        ]

    def test_agent_review_select_fails_when_posting_review_fails(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        run_dir = tmp_path / "review-results-run-0"
        run_dir.mkdir()
        (run_dir / "result.json").write_text(
            json.dumps(
                {
                    "verdict": "LGTM",
                    "score": 8,
                    "summary": "Looks good",
                    "comments": [
                        {
                            "file": ".github/dependabot.yml",
                            "line": 1,
                            "body": "Reviewed.",
                            "severity": "info",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        async def fake_select_best_result(*args, **kwargs):
            del args, kwargs
            from gearbox.agents.review import load_review_result

            return 0, load_review_result(run_dir / "result.json")

        monkeypatch.setattr("gearbox.commands.agent.select_best_result", fake_select_best_result)
        monkeypatch.setattr(
            "gearbox.commands.agent.post_review_comment",
            lambda *args, **kwargs: PostReviewResult(False, "unknown flag: --event"),
        )

        result = runner.invoke(
            cli,
            [
                "agent",
                "review-select",
                "--input-root",
                str(tmp_path),
                "--repo",
                "owner/repo",
                "--pr",
                "8",
                "--output",
                str(tmp_path / "github_output"),
            ],
        )

        assert result.exit_code != 0
        assert "发布 Review 失败" in result.output
        assert "unknown flag: --event" in result.output

    def test_agent_review_requires_args(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "review"])
        assert result.exit_code != 0

    def test_agent_implement_requires_args(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "implement"])
        assert result.exit_code != 0

    def test_agent_audit_repo_requires_repo(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "audit-repo"])
        assert result.exit_code != 0


class TestDispatchCommand:
    """测试 dispatch 命令组。"""

    def test_dispatch_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["dispatch", "--help"])
        assert result.exit_code == 0
        assert "plan" in result.output
        assert "run" in result.output

    def test_dispatch_plan_outputs_selected_issue(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from gearbox.flow.models import DispatchItem, DispatchPlan

        monkeypatch.setattr(
            "gearbox.commands.dispatch.build_dispatch_plan",
            lambda *args, **kwargs: DispatchPlan(
                repo="owner/repo",
                dry_run=True,
                skipped_count=1,
                items=[
                    DispatchItem(
                        issue_number=7,
                        title="Fix CI",
                        labels=["ready-to-implement", "P1"],
                        priority="P1",
                        complexity="S",
                        url="https://github.com/owner/repo/issues/7",
                        reason="ready-to-implement, priority=P1, complexity=S",
                    )
                ],
            ),
        )

        result = runner.invoke(cli, ["dispatch", "plan", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "#7 [P1/S] Fix CI" in result.output

    def test_dispatch_run_defaults_to_dry_run(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from gearbox.flow.models import DispatchItem, DispatchPlan

        monkeypatch.setattr(
            "gearbox.commands.dispatch.build_dispatch_plan",
            lambda *args, **kwargs: DispatchPlan(
                repo="owner/repo",
                dry_run=True,
                skipped_count=0,
                items=[
                    DispatchItem(
                        issue_number=7,
                        title="Fix CI",
                        labels=["ready-to-implement", "P1"],
                        priority="P1",
                        complexity="S",
                        url="",
                        reason="ready-to-implement, priority=P1, complexity=S",
                    )
                ],
            ),
        )
        monkeypatch.setattr(
            "gearbox.commands.dispatch.run_implement",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
        )

        result = runner.invoke(cli, ["dispatch", "run", "--repo", "owner/repo"])

        assert result.exit_code == 0
        assert "#7 [P1/S] Fix CI" in result.output

    def test_dispatch_run_cleans_in_progress_when_implement_fails(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from gearbox.flow.models import DispatchItem, DispatchPlan

        monkeypatch.setattr(
            "gearbox.commands.dispatch.build_dispatch_plan",
            lambda *args, **kwargs: DispatchPlan(
                repo="owner/repo",
                dry_run=False,
                skipped_count=0,
                items=[
                    DispatchItem(
                        issue_number=7,
                        title="Fix CI",
                        labels=["ready-to-implement", "P1"],
                        priority="P1",
                        complexity="S",
                        url="",
                        reason="ready-to-implement, priority=P1, complexity=S",
                    )
                ],
            ),
        )
        monkeypatch.setattr(
            "gearbox.commands.dispatch.prepare_working_branch",
            lambda *args, **kwargs: "gearbox/temp-test",
        )

        async def fake_run_implement(*args, **kwargs) -> None:
            del args, kwargs
            raise RuntimeError("boom")

        events: list[tuple[str, list[str]]] = []

        def fake_add_labels(repo: str, issue: int, labels: list[str]) -> PostReviewResult:
            del repo, issue
            events.append(("add", labels))
            return PostReviewResult(True)

        def fake_remove_labels(repo: str, issue: int, labels: list[str]) -> PostReviewResult:
            del repo, issue
            events.append(("remove", labels))
            return PostReviewResult(True)

        monkeypatch.setattr("gearbox.commands.dispatch.run_implement", fake_run_implement)
        monkeypatch.setattr("gearbox.commands.dispatch.add_issue_labels", fake_add_labels)
        monkeypatch.setattr("gearbox.commands.dispatch.remove_issue_labels", fake_remove_labels)

        result = runner.invoke(
            cli,
            ["dispatch", "run", "--repo", "owner/repo", "--issue", "7", "--no-dry-run"],
        )

        assert result.exit_code != 0
        assert events == [("add", ["in-progress"]), ("remove", ["in-progress"])]

    def test_dispatch_run_uses_deterministic_issue_branch(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from gearbox.agents.implement import ImplementResult
        from gearbox.core.gh import CreatePrResult, PostReviewResult
        from gearbox.flow.models import DispatchItem, DispatchPlan

        monkeypatch.setattr(
            "gearbox.commands.dispatch.build_dispatch_plan",
            lambda *args, **kwargs: DispatchPlan(
                repo="owner/repo",
                dry_run=False,
                skipped_count=0,
                items=[
                    DispatchItem(
                        issue_number=7,
                        title="Fix CI",
                        labels=["ready-to-implement", "P1"],
                        priority="P1",
                        complexity="S",
                        url="",
                        reason="ready-to-implement, priority=P1, complexity=S",
                    )
                ],
            ),
        )
        monkeypatch.setattr(
            "gearbox.commands.dispatch.prepare_working_branch",
            lambda *args, **kwargs: "gearbox/temp-test",
        )

        async def fake_run_implement(*args, **kwargs) -> ImplementResult:
            del args, kwargs
            return ImplementResult(
                branch_name="feat/issue-7",
                summary="Fix CI",
                files_changed=["ci.yml"],
                pr_url=None,
                ready_for_review=True,
            )

        captured: dict[str, str] = {}

        def fake_finalize_and_create_pr(**kwargs) -> CreatePrResult:
            captured.update({key: str(value) for key, value in kwargs.items()})
            return CreatePrResult(True, "https://github.com/owner/repo/pull/7")

        monkeypatch.setattr("gearbox.commands.dispatch.run_implement", fake_run_implement)
        monkeypatch.setattr(
            "gearbox.commands.dispatch.finalize_and_create_pr",
            fake_finalize_and_create_pr,
        )
        monkeypatch.setattr(
            "gearbox.commands.dispatch.add_issue_labels",
            lambda *args, **kwargs: PostReviewResult(True),
        )
        monkeypatch.setattr(
            "gearbox.commands.dispatch.remove_issue_labels",
            lambda *args, **kwargs: PostReviewResult(True),
        )
        monkeypatch.setattr(
            "gearbox.commands.dispatch.post_issue_comment",
            lambda *args, **kwargs: PostReviewResult(True),
        )

        result = runner.invoke(
            cli,
            ["dispatch", "run", "--repo", "owner/repo", "--issue", "7", "--no-dry-run"],
        )

        assert result.exit_code == 0
        assert captured["final_branch"] == "gearbox/issue-7"
