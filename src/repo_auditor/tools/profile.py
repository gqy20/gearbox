"""Profile 生成工具 - 分析仓库并生成统一的 Profile JSON"""

import json
import subprocess
from pathlib import Path
from typing import Any

import tomllib
from claude_agent_sdk import tool


def _load_pyproject_from_text(content: str) -> dict[str, Any]:
    if not content:
        return {}
    return tomllib.loads(content)


def _load_pyproject(repo_path: Path) -> dict[str, Any]:
    pyproject_path = repo_path / "pyproject.toml"
    if not pyproject_path.exists():
        return {}

    with pyproject_path.open("rb") as file:
        return tomllib.load(file)


def _gh_api(path: str) -> Any:
    result = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True)
    return json.loads(result.stdout or "null")


def _is_remote_repo(repo_path: str) -> bool:
    return "/" in repo_path and not Path(repo_path).exists()


def _load_remote_pyproject(repo_name: str) -> dict[str, Any]:
    try:
        payload = _gh_api(f"/repos/{repo_name}/contents/pyproject.toml")
    except subprocess.CalledProcessError:
        return {}

    if payload.get("encoding") == "utf-8":
        return _load_pyproject_from_text(payload.get("content", ""))

    return {}


def _detect_project_type(project_data: dict[str, Any], has_src: bool) -> str:
    scripts = project_data.get("scripts", {})
    if scripts:
        return "cli"

    if has_src:
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
    project_data: dict[str, Any], root_data: dict[str, Any], has_tests_dir: bool
) -> str | None:
    dependencies = list(project_data.get("dependencies", []))
    optional_deps = project_data.get("optional-dependencies", {})
    for group in optional_deps.values():
        dependencies.extend(group)
    dependencies.extend(root_data.get("dependency-groups", {}).get("dev", []))

    if any("pytest" in dependency for dependency in dependencies):
        return "pytest"

    if has_tests_dir:
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


def _detect_remote_ci_file(repo_name: str) -> str | None:
    try:
        payload = _gh_api(f"/repos/{repo_name}/contents/.github/workflows")
    except subprocess.CalledProcessError:
        return None

    for item in payload:
        if item.get("type") == "file" and item.get("path", "").endswith((".yml", ".yaml")):
            return item["path"]
    return None


def _has_remote_dependabot(repo_name: str) -> bool:
    try:
        _gh_api(f"/repos/{repo_name}/contents/.github/dependabot.yml")
        return True
    except subprocess.CalledProcessError:
        return False


def _remote_path_exists(repo_name: str, path: str) -> bool:
    try:
        _gh_api(f"/repos/{repo_name}/contents/{path}")
        return True
    except subprocess.CalledProcessError:
        return False


def _remote_docs_path(repo_name: str) -> str | None:
    if _remote_path_exists(repo_name, "docs"):
        return "docs/"
    if _remote_path_exists(repo_name, "README.md"):
        return "README.md"
    return None


def _detect_install_command(has_pyproject: bool) -> str:
    if has_pyproject:
        return "uv sync"
    return ""


def _detect_test_command(test_framework: str | None) -> str:
    if test_framework == "pytest":
        return "uv run pytest -v"
    return ""


def _build_profile(
    pyproject: dict[str, Any],
    *,
    has_src: bool,
    has_tests_dir: bool,
    ci_file: str | None,
    has_pre_commit: bool,
    has_dependabot: bool,
    has_coverage: bool,
    modules: list[str],
    has_documentation: bool,
    has_contributing_guide: bool,
    has_code_of_conduct: bool,
    has_license: bool,
    has_docker: bool,
) -> dict[str, Any]:
    project_data = pyproject.get("project", {})
    tool_data = pyproject.get("tool", {})

    test_framework = _detect_test_framework(project_data, pyproject, has_tests_dir)
    type_checker = _detect_type_checker(tool_data, pyproject)

    return {
        "project": {
            "type": _detect_project_type(project_data, has_src),
            "language": "python" if pyproject else "unknown",
            "entry_points": sorted(project_data.get("scripts", {}).keys()),
            "modules": modules,
        },
        "build": {
            "install_command": _detect_install_command(bool(pyproject)),
            "test_command": _detect_test_command(test_framework),
            "ci_file": ci_file,
        },
        "quality": {
            "linters": _detect_linters(tool_data, pyproject),
            "test_framework": test_framework,
            "type_checker": type_checker,
            "coverage": has_coverage,
        },
        "extensibility": {
            "plugins": False,
            "hooks": has_pre_commit,
            "config_schema": "pyproject.toml" if pyproject else None,
        },
        "security": {
            "dependabot": has_dependabot,
            "secrets_scan": False,
        },
        "docs": {
            "has_documentation": has_documentation,
            "has_changelog": False,
        },
        "community": {
            "has_contributing_guide": has_contributing_guide,
            "has_code_of_conduct": has_code_of_conduct,
            "has_license": has_license,
        },
        "platform": {
            "has_docker": has_docker,
        },
    }


def build_profile(repo_path: Path) -> dict[str, Any]:
    pyproject = _load_pyproject(repo_path)
    return _build_profile(
        pyproject,
        has_src=(repo_path / "src").exists(),
        has_tests_dir=(repo_path / "tests").exists(),
        ci_file=_detect_ci_file(repo_path),
        has_pre_commit=(repo_path / ".pre-commit-config.yaml").exists(),
        has_dependabot=(repo_path / ".github" / "dependabot.yml").exists(),
        has_coverage=(repo_path / ".coveragerc").exists() or (repo_path / "coverage.xml").exists(),
        modules=[path.name for path in sorted((repo_path / "src").iterdir())]
        if (repo_path / "src").exists()
        else [],
        has_documentation=(repo_path / "docs").exists() or (repo_path / "README.md").exists(),
        has_contributing_guide=(repo_path / "CONTRIBUTING.md").exists(),
        has_code_of_conduct=(repo_path / "CODE_OF_CONDUCT.md").exists(),
        has_license=(repo_path / "LICENSE").exists() or (repo_path / "LICENSE.md").exists(),
        has_docker=(repo_path / "Dockerfile").exists(),
    )


def build_remote_profile(repo_name: str) -> dict[str, Any]:
    pyproject = _load_remote_pyproject(repo_name)
    return _build_profile(
        pyproject,
        has_src=False,
        has_tests_dir=False,
        ci_file=_detect_remote_ci_file(repo_name),
        has_pre_commit=False,
        has_dependabot=_has_remote_dependabot(repo_name),
        has_coverage=False,
        modules=[],
        has_documentation=_remote_docs_path(repo_name) is not None,
        has_contributing_guide=_remote_path_exists(repo_name, "CONTRIBUTING.md"),
        has_code_of_conduct=_remote_path_exists(repo_name, "CODE_OF_CONDUCT.md"),
        has_license=_remote_path_exists(repo_name, "LICENSE")
        or _remote_path_exists(repo_name, "LICENSE.md"),
        has_docker=_remote_path_exists(repo_name, "Dockerfile"),
    )


@tool("generate_profile", "生成仓库Profile", {"repo_path": str})
async def generate_profile(args: dict[str, Any]) -> dict[str, Any]:
    """分析目标仓库结构并生成基础 Profile。"""
    repo_path_arg = args["repo_path"]
    if _is_remote_repo(repo_path_arg):
        profile = build_remote_profile(repo_path_arg)
        display_path = repo_path_arg
    else:
        repo_path = Path(repo_path_arg).resolve()
        profile = build_profile(repo_path)
        display_path = str(repo_path)

    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Profile 分析完成: {display_path}\n"
                    f"- 类型: {profile['project']['type']}\n"
                    f"- 语言: {profile['project']['language']}\n"
                    f"- CI: {profile['build']['ci_file'] or 'none'}"
                ),
            }
        ],
        "structured_output": profile,
    }
