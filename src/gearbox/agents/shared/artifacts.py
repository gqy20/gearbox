"""Agent 结果 artifact 公共能力。"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path


def to_jsonable(value: object) -> object:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    return value


def write_json_artifact(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def read_json_artifact(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
