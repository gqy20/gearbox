"""Fix Agent — Pydantic schema for review-fix results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FixResult(BaseModel):
    """Fix Agent 执行结果：根据 Review 反馈修补 PR。"""

    verdict: Literal["fixed", "partial", "skipped"] = Field(
        description="修复结论: fixed=全部解决, partial=部分解决, skipped=跳过"
    )
    commits_pushed: int = Field(
        ge=0,
        description="推送到 PR 分支的 commit 数量",
    )
    files_modified: list[str] = Field(
        default_factory=list,
        description="本次修改的文件列表",
    )
    still_has_issues: bool = Field(
        default=True,
        description="是否仍有未解决的 review 问题",
    )
    failure_reason: str | None = Field(
        default=None,
        description="无法完成修复时的原因",
    )
