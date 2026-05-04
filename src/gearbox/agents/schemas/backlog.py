"""Backlog Agent — Pydantic schema for issue triage results."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import VersionedSchema


class BacklogItemResult(VersionedSchema):
    labels: list[str] = Field(default_factory=list)
    priority: Literal["P0", "P1", "P2", "P3"] = "P3"
    complexity: Literal["S", "M", "L"] = "M"
    ready_to_implement: bool = False
    issue_number: int | None = None
    failure_reason: str | None = None
