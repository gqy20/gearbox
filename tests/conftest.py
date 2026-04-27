"""测试配置和共享 fixtures"""

import os
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """临时配置目录，隔离真实配置"""
    config_dir = tmp_path / ".config" / "gearbox"
    config_dir.mkdir(parents=True)
    old_config = os.environ.get("GEARBOX_CONFIG_DIR")

    original_xdg = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)

    yield config_dir

    if original_xdg is not None:
        os.environ["XDG_CONFIG_HOME"] = original_xdg
    elif "XDG_CONFIG_HOME" in os.environ:
        del os.environ["XDG_CONFIG_HOME"]

    if old_config is not None:
        os.environ["GEARBOX_CONFIG_DIR"] = old_config


@pytest.fixture
def temp_home(tmp_path: Path) -> Generator[Path, None, None]:
    """临时 HOME 目录，隔离真实 home"""
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(tmp_path)

    yield tmp_path

    if old_home is not None:
        os.environ["HOME"] = old_home
    else:
        del os.environ["HOME"]


@pytest.fixture
def sample_issues_json() -> dict:
    """示例 issues.json 数据"""
    return {
        "repo": "owner/repo",
        "profile": {"language": "python", "stars": 100},
        "benchmarks": ["pallets/click"],
        "issues": [
            {
                "title": "缺少类型注解",
                "body": "## 问题\n代码缺少类型注解\n\n## 解决方案\n1. 添加 py.typed\n2. 运行 mypy",
                "labels": "high,enhancement",
            },
            {
                "title": "测试覆盖不足",
                "body": "## 问题\n测试覆盖率低于 80%\n\n## 解决方案\n1. 添加 pytest-cov\n2. 补充单元测试",
                "labels": "medium,testing",
            },
        ],
    }
