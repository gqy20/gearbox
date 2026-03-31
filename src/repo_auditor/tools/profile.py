"""Profile 生成工具 - 分析仓库并生成统一的 Profile JSON"""

from pathlib import Path
from typing import Any

import tomllib
from claude_agent_sdk import tool


def _load_pyproject(repo_path: Path) -> dict[str, Any]:
    pyproject_path = repo_path / "pyproject.toml"
    if not pyproject_path.exists():
        return {}

    with pyproject_path.open("rb") as file:
        return tomllib.load(file)


def _detect_project_type(project_data: dict[str, Any], repo_path: Path) -> str:
    scripts = project_data.get("scripts", {})
    if scripts:
        return "cli"

    if (repo_path / "src").exists():
        return "library"

    return "application"


def _detect_linters(tool_data: dict[str, Any], root_data: dict[str, Any]) -> list[str]:
    linters: list[str] = []

    if "ruff" in tool_data:
        linters.append("ruff")

    dev_dependencies = root_data.get("dependency-groups", {}).get("dev", [])
    if any("ruff" in dependency for dependency in dev_dependencies) and "ruff" not in linters:
        linters.append("ruff")

    return linters


def _detect_test_framework(
    project_data: dict[str, Any], root_data: dict[str, Any], repo_path: Path
) -> str | None:
    dependencies = list(project_data.get("dependencies", []))
    optional_deps = project_data.get("optional-dependencies", {})
    for group in optional_deps.values():
        dependencies.extend(group)
    dependencies.extend(root_data.get("dependency-groups", {}).get("dev", []))

    if any("pytest" in dependency for dependency in dependencies):
        return "pytest"

    if (repo_path / "tests").exists():
        return "pytest"

    return None


def _detect_type_checker(tool_data: dict[str, Any], root_data: dict[str, Any]) -> str | None:
    if "mypy" in tool_data:
        return "mypy"

    dev_dependencies = root_data.get("dependency-groups", {}).get("dev", [])
    if any("mypy" in dependency for dependency in dev_dependencies):
        return "mypy"

    return None


def _detect_ci_file(repo_path: Path) -> str | None:
    workflows_dir = repo_path / ".github" / "workflows"
    if not workflows_dir.exists():
        return None

    workflow_files = sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml"))
    if not workflow_files:
        return None

    return workflow_files[0].relative_to(repo_path).as_posix()


def _detect_install_command(repo_path: Path) -> str:
    if (repo_path / "uv.lock").exists() or (repo_path / "pyproject.toml").exists():
        return "uv sync"
    return ""


def _detect_test_command(test_framework: str | None) -> str:
    if test_framework == "pytest":
        return "uv run pytest -v"
    return ""


def build_profile(repo_path: Path) -> dict[str, Any]:
    pyproject = _load_pyproject(repo_path)
    project_data = pyproject.get("project", {})
    tool_data = pyproject.get("tool", {})

    test_framework = _detect_test_framework(project_data, pyproject, repo_path)
    type_checker = _detect_type_checker(tool_data, pyproject)

    return {
        "project": {
            "type": _detect_project_type(project_data, repo_path),
            "language": "python" if pyproject else "unknown",
            "entry_points": sorted(project_data.get("scripts", {}).keys()),
            "modules": [path.name for path in sorted((repo_path / "src").iterdir())]
            if (repo_path / "src").exists()
            else [],
        },
        "build": {
            "install_command": _detect_install_command(repo_path),
            "test_command": _detect_test_command(test_framework),
            "ci_file": _detect_ci_file(repo_path),
        },
        "quality": {
            "linters": _detect_linters(tool_data, pyproject),
            "test_framework": test_framework,
            "type_checker": type_checker,
            "coverage": (repo_path / ".coveragerc").exists()
            or (repo_path / "coverage.xml").exists(),
        },
        "extensibility": {
            "plugins": False,
            "hooks": (repo_path / ".pre-commit-config.yaml").exists(),
            "config_schema": "pyproject.toml" if pyproject else None,
        },
        "security": {
            "dependabot": (repo_path / ".github" / "dependabot.yml").exists(),
            "secrets_scan": False,
        },
    }


@tool("generate_profile", "生成仓库Profile", {"repo_path": str})
async def generate_profile(args: dict[str, Any]) -> dict[str, Any]:
    """分析目标仓库结构并生成基础 Profile。"""
    repo_path = Path(args["repo_path"]).resolve()
    profile = build_profile(repo_path)

    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Profile 分析完成: {repo_path}\n"
                    f"- 类型: {profile['project']['type']}\n"
                    f"- 语言: {profile['project']['language']}\n"
                    f"- CI: {profile['build']['ci_file'] or 'none'}"
                ),
            }
        ],
        "structured_output": profile,
    }
