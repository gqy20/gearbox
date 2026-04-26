"""向后兼容的运行时导出。"""

from . import runtime

SdkEventLogger = runtime.SdkEventLogger
prepare_sdk_options = runtime.prepare_agent_options

__all__ = ["SdkEventLogger", "prepare_sdk_options"]
