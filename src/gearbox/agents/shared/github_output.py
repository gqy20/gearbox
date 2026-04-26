"""GitHub Actions 输出公共能力。"""

from __future__ import annotations

import json
from dataclasses import is_dataclass

from gearbox.agents.shared.artifacts import to_jsonable
from gearbox.core.gh import write_outputs


def result_to_github_output(result: object, output_file: str = "/tmp/github_output") -> None:
    """将 dataclass/对象结果写入 GitHub Actions output 文件。"""
    data: dict[str, str] = {}
    for key, value in vars(result).items():
        if isinstance(value, (list, dict)) or is_dataclass(value):
            data[key] = json.dumps(to_jsonable(value), ensure_ascii=False)
        elif isinstance(value, bool):
            data[key] = str(value).lower()
        elif value is None:
            data[key] = ""
        else:
            data[key] = str(value)
    data["status"] = "success"
    write_outputs(data, output_file)


def format_currency(amount: float | None) -> str:
    return f"${amount:.4f}" if amount is not None else "n/a"
