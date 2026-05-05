"""Audit Agent — Pydantic schema for audit results."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Issue(BaseModel):
    title: str
    body: str
    labels: list[str] = Field(default_factory=list)


class AuditResult(BaseModel):
    repo: str
    profile: dict[str, Any] = Field(default_factory=dict)
    comparison_markdown: str = ""
    benchmarks: list[str] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    cost: float | None = None
    failure_reason: str | None = None
