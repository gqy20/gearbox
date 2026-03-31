"""测试 MCP 工具"""

import pytest

from repo_auditor.tools.benchmark import discover_benchmarks
from repo_auditor.tools.compare import CAPABILITY_DIMENSIONS, create_comparison
from repo_auditor.tools.issue import create_issue
from repo_auditor.tools.profile import generate_profile


@pytest.mark.asyncio
async def test_generate_profile() -> None:
    """测试 Profile 生成工具"""
    result = await generate_profile.handler({"repo_path": "."})
    profile = result["structured_output"]

    assert "content" in result
    assert "structured_output" in result
    assert profile["project"]["type"] == "cli"
    assert profile["project"]["language"] == "python"
    assert "repo-auditor" in profile["project"]["entry_points"]
    assert profile["build"]["ci_file"] == ".github/workflows/audit.yml"
    assert profile["build"]["install_command"] == "uv sync"
    assert profile["build"]["test_command"] == "uv run pytest -v"
    assert "ruff" in profile["quality"]["linters"]
    assert profile["quality"]["test_framework"] == "pytest"
    assert profile["quality"]["type_checker"] == "mypy"
    assert profile["quality"]["coverage"] is False
    assert profile["extensibility"]["config_schema"] == "pyproject.toml"
    assert profile["security"]["dependabot"] is False


@pytest.mark.asyncio
async def test_discover_benchmarks() -> None:
    """测试对标发现工具"""
    target_profile = {
        "project": {
            "type": "cli",
            "language": "python",
            "entry_points": ["repo-auditor"],
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


@pytest.mark.asyncio
async def test_create_comparison() -> None:
    """测试对比矩阵工具"""
    target_profile = {
        "project": {"type": "cli", "language": "python", "entry_points": ["repo-auditor"]},
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
