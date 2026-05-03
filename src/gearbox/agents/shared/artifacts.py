"""Agent 结果 artifact 公共能力。"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

from pydantic import BaseModel


def to_jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if hasattr(value, "__dict__"):
        return {k: to_jsonable(v) for k, v in value.__dict__.items() if not k.startswith("_")}
    return value


def write_json_artifact(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_json_artifact(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"Expected dict from {path}, got {type(data).__name__}")
    return data
