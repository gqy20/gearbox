"""Implement Agent — Pydantic schema for implementation results."""

from __future__ import annotations

from pydantic import Field

from .base import VersionedSchema


class ImplementResult(VersionedSchema):
    branch_name: str
    summary: str
    files_changed: list[str] = Field(default_factory=list)
    pr_url: str | None = None
    ready_for_review: bool = False
    failure_reason: str | None = None
    blocked_reason: str | None = None
