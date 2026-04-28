"""Review Agent — Pydantic schema for PR review results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReviewComment(BaseModel):
    file: str
    line: int | None = None
    body: str
    severity: Literal["blocker", "warning", "info"] = "info"


class ReviewResult(BaseModel):
    verdict: Literal["LGTM", "Request Changes", "Comment Only"]
    score: int = Field(ge=0, le=10)
    summary: str
    comments: list[ReviewComment] = Field(default_factory=list)
    failure_reason: str | None = None
