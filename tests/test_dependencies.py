"""测试项目依赖声明——确保未使用的依赖不被包含。"""

from pathlib import Path

import tomli


def _load_pyproject_deps() -> list[str]:
    """从 pyproject.toml 读取 [project.dependencies] 列表。"""
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomli.load(f)
    return data.get("project", {}).get("dependencies", [])


class TestPydanticNotInDependencies:
    """Issue #18: pydantic 不应出现在依赖声明中，因为代码库未使用。"""

    def test_pydantic_absent_from_project_dependencies(self) -> None:
        deps = _load_pyproject_deps()
        dep_names = [d.split(">=")[0].split("==")[0].split("<")[0].strip() for d in deps]
        assert "pydantic" not in dep_names, (
            "pydantic 出现在 [project.dependencies] 中，"
            "但代码库中未使用该依赖（Issue #18）。"
        )
