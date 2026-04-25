"""Gearbox - AI 驱动的仓库自动化飞轮系统"""

__version__ = "0.1.0"

from .agents.audit import run_audit
from .cli import cli

__all__ = ["run_audit", "cli"]
