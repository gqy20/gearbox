"""Evaluator Agent — Pydantic schema for multi-result evaluation."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field


def _coerce_score_keys(data: dict[str, Any]) -> dict[int, Any]:
    """Convert string keys to int, dropping non-numeric keys."""
    out: dict[int, Any] = {}
    for k, v in data.items():
        try:
            out[int(k)] = v
        except (ValueError, TypeError):
            continue
    return out


class ScoreItem(BaseModel):
    score: float = Field(ge=0, le=1)
    justification: str = ""


ScoreDict = Annotated[
    dict[int, ScoreItem],
    BeforeValidator(_coerce_score_keys),
]


class EvaluationResult(BaseModel):
    winner: int = Field(ge=0, description="最佳结果索引 (0-based)")
    scores: ScoreDict = Field(default_factory=dict)
    reasoning: str = ""
    consensus: list[str] = Field(default_factory=list)
