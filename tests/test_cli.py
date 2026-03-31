"""测试 CLI 命令"""

import json

from click.testing import CliRunner

from repo_auditor.cli import cli


def test_cli_version() -> None:
    """测试版本命令"""
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_help() -> None:
    """测试帮助命令"""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Repo Auditor" in result.output
    assert "audit" in result.output
    assert "config" in result.output
    assert "publish-issues" in result.output


def test_audit_requires_repo() -> None:
    """测试 audit 必须指定 --repo 参数"""
    runner = CliRunner()
    result = runner.invoke(cli, ["audit"])
    assert result.exit_code != 0
    assert "Missing option" in result.output


def test_audit_help() -> None:
    """测试 audit 帮助"""
    runner = CliRunner()
    result = runner.invoke(cli, ["audit", "--help"])
    assert result.exit_code == 0
    assert "--repo" in result.output


def test_config_help() -> None:
    """测试 config 帮助"""
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "set" in result.output
    assert "path" in result.output


def test_config_set_unknown_key() -> None:
    """测试设置未知配置项"""
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "set", "unknown", "value"])
    assert result.exit_code != 0
    assert "未知的配置项" in result.output


def test_publish_issues_help() -> None:
    """测试 publish-issues 帮助"""
    runner = CliRunner()
    result = runner.invoke(cli, ["publish-issues", "--help"])
    assert result.exit_code == 0
    assert "--input" in result.output
    assert "--dry-run" in result.output


def test_publish_issues_dry_run() -> None:
    """测试 publish-issues dry-run"""
    runner = CliRunner()

    with runner.isolated_filesystem():
        with open("issues.json", "w", encoding="utf-8") as file:
            json.dump(
                {
                    "issues": [
                        {
                            "repo": "owner/repo",
                            "title": "Test title",
                            "body": "Test body",
                            "labels": "enhancement,invalid-label",
                        }
                    ]
                },
                file,
            )

        result = runner.invoke(cli, ["publish-issues", "--input", "issues.json", "--dry-run"])

    assert result.exit_code == 0
    assert "处理 Issue 数量: 1" in result.output
    assert "已创建: 1" in result.output
