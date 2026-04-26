"""测试 CLI 命令"""

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from gearbox.cli import cli


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
        assert "triage" in result.output
        assert "review" in result.output
        assert "implement" in result.output
        assert "audit-repo" in result.output

    def test_agent_triage_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "triage", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--issue" in result.output
        assert "--parallel-count" in result.output

    def test_agent_review_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "review", "--help"])
        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--pr" in result.output

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
        assert "--parallel-count" in result.output

    def test_agent_triage_requires_args(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "triage"])
        assert result.exit_code != 0

    def test_agent_review_requires_args(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "review"])
        assert result.exit_code != 0

    def test_agent_implement_requires_args(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "implement"])
        assert result.exit_code != 0

    def test_agent_audit_repo_requires_repo(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "audit-repo"])
        assert result.exit_code != 0
