"""Data models for deterministic Gearbox flows."""

from dataclasses import dataclass


@dataclass
class DispatchItem:
    issue_number: int
    title: str
    labels: list[str]
    priority: str
    complexity: str
    url: str
    reason: str


@dataclass
class DispatchPlan:
    repo: str
    items: list[DispatchItem]
    skipped_count: int
    dry_run: bool
