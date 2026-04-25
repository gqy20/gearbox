"""测试 MCP 工具"""

import json

import pytest

from gearbox.tools import benchmark as benchmark_tool
from gearbox.tools.benchmark import discover_benchmarks
from gearbox.tools.compare import CAPABILITY_DIMENSIONS, create_comparison
from gearbox.tools.issue import create_issue
from gearbox.tools import profile as profile_tool
from gearbox.tools.profile import generate_profile


@pytest.mark.asyncio
async def test_generate_profile() -> None:
    """测试 Profile 生成工具"""
    result = await generate_profile.handler({"repo_path": "."})
    profile = result["structured_output"]

    assert "content" in result
    assert "structured_output" in result
    assert profile["project"]["type"] == "cli"
    assert profile["project"]["language"] == "python"
    assert "gearbox" in profile["project"]["entry_points"]
    assert profile["build"]["ci_file"] == ".github/workflows/audit.yml"
    assert profile["build"]["install_command"] == "uv sync"
    assert profile["build"]["test_command"] == "uv run pytest -v"
    assert "ruff" in profile["quality"]["linters"]
    assert profile["quality"]["test_framework"] == "pytest"
    assert profile["quality"]["type_checker"] == "mypy"
    assert profile["quality"]["coverage"] is False
    assert profile["extensibility"]["config_schema"] == "pyproject.toml"
    assert profile["security"]["dependabot"] is False
    assert profile["docs"]["has_documentation"] is True
    assert profile["community"]["has_license"] is False
    assert profile["platform"]["has_docker"] is False


@pytest.mark.asyncio
async def test_generate_profile_remote_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试远程 GitHub 仓库 Profile 生成"""
    captured_commands: list[list[str]] = []

    pyproject_text = """
[project]
name = "example-cli"
dependencies = ["click>=8.0.0"]

[project.scripts]
example = "example.cli:main"

[dependency-groups]
dev = ["pytest>=8.0.0", "mypy>=1.0.0"]

[tool.ruff]
line-length = 100

[tool.mypy]
python_version = "3.10"
""".strip()

    workflow_payload = [{"name": "ci.yml", "path": ".github/workflows/ci.yml", "type": "file"}]
    docs_payload = [{"name": "index.md", "path": "docs/index.md", "type": "file"}]

    def fake_run(command: list[str], check: bool, capture_output: bool, text: bool) -> object:
        assert check is True
        assert capture_output is True
        assert text is True
        captured_commands.append(command)

        class CompletedProcess:
            stdout = ""

        result = CompletedProcess()
        joined = " ".join(command)
        if "/contents/pyproject.toml" in joined:
            result.stdout = json.dumps({"content": pyproject_text, "encoding": "utf-8"})
            return result
        if "/contents/.github/workflows" in joined:
            result.stdout = json.dumps(workflow_payload)
            return result
        if "/contents/docs" in joined:
            result.stdout = json.dumps(docs_payload)
            return result
        if "/contents/README.md" in joined:
            result.stdout = json.dumps({"name": "README.md", "path": "README.md", "type": "file"})
            return result
        if "/contents/CONTRIBUTING.md" in joined:
            result.stdout = json.dumps(
                {"name": "CONTRIBUTING.md", "path": "CONTRIBUTING.md", "type": "file"}
            )
            return result
        if "/contents/LICENSE" in joined:
            result.stdout = json.dumps({"name": "LICENSE", "path": "LICENSE", "type": "file"})
            return result
        if "/contents/.github/dependabot.yml" in joined:
            result.stdout = json.dumps(
                {"name": "dependabot.yml", "path": ".github/dependabot.yml", "type": "file"}
            )
            return result
        if "/contents/CODE_OF_CONDUCT.md" in joined or "/contents/Dockerfile" in joined:
            raise profile_tool.subprocess.CalledProcessError(returncode=1, cmd=command)

        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(profile_tool.subprocess, "run", fake_run)

    result = await generate_profile.handler({"repo_path": "owner/example-cli"})
    profile = result["structured_output"]

    assert profile["project"]["type"] == "cli"
    assert profile["project"]["language"] == "python"
    assert profile["project"]["entry_points"] == ["example"]
    assert profile["build"]["ci_file"] == ".github/workflows/ci.yml"
    assert profile["quality"]["test_framework"] == "pytest"
    assert profile["quality"]["type_checker"] == "mypy"
    assert "ruff" in profile["quality"]["linters"]
    assert profile["docs"]["has_documentation"] is True
    assert profile["community"]["has_contributing_guide"] is True
    assert profile["community"]["has_license"] is True
    assert profile["security"]["dependabot"] is True
    assert captured_commands


@pytest.mark.asyncio
async def test_discover_benchmarks(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试对标发现工具"""
    captured_commands: list[list[str]] = []

    def fake_run(command: list[str], check: bool, capture_output: bool, text: bool) -> object:
        assert check is True
        assert capture_output is True
        assert text is True
        captured_commands.append(command)

        payload = [
            {
                "fullName": "python-poetry/poetry",
                "language": "Python",
                "description": "Python packaging and dependency management",
                "stargazersCount": 33000,
                "isArchived": False,
                "isFork": False,
                "url": "https://github.com/python-poetry/poetry",
            },
            {
                "fullName": "pallets/click",
                "language": "Python",
                "description": "Composable command line interface toolkit",
                "stargazersCount": 17000,
                "isArchived": False,
                "isFork": False,
                "url": "https://github.com/pallets/click",
            },
            {
                "fullName": "fastapi/typer",
                "language": "Python",
                "description": "Typer, build great CLIs. Easy to code. Based on Python type hints.",
                "stargazersCount": 14000,
                "isArchived": False,
                "isFork": False,
                "url": "https://github.com/fastapi/typer",
            },
        ]

        class CompletedProcess:
            stdout = json.dumps(payload)

        return CompletedProcess()

    monkeypatch.setattr(benchmark_tool.subprocess, "run", fake_run)

    target_profile = {
        "project": {
            "type": "cli",
            "language": "python",
            "entry_points": ["gearbox"],
        },
        "quality": {
            "linters": ["ruff"],
            "test_framework": "pytest",
            "type_checker": "mypy",
        },
    }

    result = await discover_benchmarks.handler(
        {
            "target_profile": target_profile,
            "top": 3,
            "min_stars": 100,
        }
    )

    assert "content" in result
    assert "structured_output" in result
    benchmarks = result["structured_output"]
    assert len(benchmarks) == 3
    assert benchmarks[0]["stars"] >= 100
    assert benchmarks[0]["language"] == "Python"
    assert "same language" in benchmarks[0]["reasons"]
    assert "score" in benchmarks[0]
    assert benchmarks[0]["score"] >= benchmarks[1]["score"]
    assert captured_commands
    assert captured_commands[0][:3] == ["gh", "search", "repos"]


@pytest.mark.asyncio
async def test_create_comparison() -> None:
    """测试对比矩阵工具"""
    target_profile = {
        "project": {"type": "cli", "language": "python", "entry_points": ["gearbox"]},
        "build": {"ci_file": ".github/workflows/audit.yml"},
        "quality": {
            "linters": ["ruff"],
            "test_framework": "pytest",
            "type_checker": "mypy",
            "coverage": False,
        },
        "extensibility": {"plugins": False, "config_schema": "pyproject.toml"},
        "security": {"dependabot": False},
        "docs": {"has_documentation": True, "has_changelog": False},
        "community": {"has_contributing_guide": False, "has_code_of_conduct": False},
        "platform": {"has_docker": False},
    }
    benchmark_profile = {
        "repo": "example/benchmark",
        "project": {"type": "cli", "language": "python", "entry_points": ["bench"]},
        "build": {"ci_file": ".github/workflows/test.yml"},
        "quality": {
            "linters": ["ruff"],
            "test_framework": "pytest",
            "type_checker": "mypy",
            "coverage": True,
        },
        "extensibility": {"plugins": True, "config_schema": "pyproject.toml"},
        "security": {"dependabot": True},
        "docs": {"has_documentation": True, "has_changelog": True},
        "community": {"has_contributing_guide": True, "has_code_of_conduct": True},
        "platform": {"has_docker": True},
    }

    result = await create_comparison.handler(
        {
            "target_profile": target_profile,
            "benchmark_profiles": [benchmark_profile],
        }
    )

    assert "content" in result
    assert "structured_output" in result
    matrix = result["structured_output"]
    assert "dimensions" in matrix
    assert "top_gaps" in matrix
    assert len(CAPABILITY_DIMENSIONS) == 15
    coverage_dimension = next(
        item for item in matrix["dimensions"] if item["name"] == "has_coverage"
    )
    dependabot_dimension = next(
        item for item in matrix["dimensions"] if item["name"] == "has_dependabot"
    )
    assert coverage_dimension["target"]["value"] is False
    assert coverage_dimension["benchmarks"][0]["value"] is True
    assert coverage_dimension["gap_level"] == "high"
    assert dependabot_dimension["gap_level"] == "high"
    assert "has_coverage" in matrix["top_gaps"]


@pytest.mark.asyncio
async def test_create_issue() -> None:
    """测试 Issue 生成工具"""
    result = await create_issue.handler(
        {
            "comparison": {},
            "gap_count": 2,
        }
    )

    assert "content" in result
    assert "structured_output" in result
    issues = result["structured_output"]
    assert len(issues) == 2
    assert "title" in issues[0]
    assert "body" in issues[0]
