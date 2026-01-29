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

    assert "content" in result
    assert "structured_output" in result
    assert result["structured_output"]["project"]["type"] == "unknown"


@pytest.mark.asyncio
async def test_discover_benchmarks() -> None:
    """测试对标发现工具"""
    result = await discover_benchmarks.handler(
        {
            "repo_name": "test/repo",
            "top": 3,
            "min_stars": 100,
        }
    )

    assert "content" in result
    assert "structured_output" in result
    benchmarks = result["structured_output"]
    assert len(benchmarks) == 3
    assert benchmarks[0]["stars"] >= 100


@pytest.mark.asyncio
async def test_create_comparison() -> None:
    """测试对比矩阵工具"""
    result = await create_comparison.handler(
        {
            "target_profile": {},
            "benchmarks": [{"name": "test/repo"}],
        }
    )

    assert "content" in result
    assert "structured_output" in result
    matrix = result["structured_output"]
    assert "target" in matrix
    assert "benchmarks" in matrix
    assert len(CAPABILITY_DIMENSIONS) == 15


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
