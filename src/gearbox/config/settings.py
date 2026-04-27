"""配置管理 - 读写用户配置"""

import os
from pathlib import Path
from typing import Any, cast

import tomli_w

# Agent 默认参数（CLI 和 Action 均引用此处的值）
AGENT_DEFAULTS: dict[str, Any] = {
    "max_turns": {
        "backlog": 5,
        "review": 10,
        "implement": 80,
        "audit": 20,
    },
}


def _config_dir() -> Path:
    return Path.home() / ".config" / "gearbox"


def _config_file() -> Path:
    return _config_dir() / "config.toml"


def ensure_config_dir() -> None:
    """确保配置目录存在"""
    _config_dir().mkdir(parents=True, exist_ok=True)


def get_config_path() -> Path:
    """获取配置文件路径"""
    return _config_file()


def load_config() -> dict[str, Any]:
    """加载配置文件"""
    config_file = get_config_path()
    if not config_file.exists():
        return {}

    try:
        import tomli

        with open(config_file, "rb") as f:
            return tomli.load(f)
    except ImportError:
        return {}
    except Exception:
        return {}


def save_config(config: dict[str, Any]) -> None:
    """保存配置文件"""
    ensure_config_dir()

    with open(get_config_path(), "wb") as f:
        tomli_w.dump(config, f)


def get_github_token() -> str | None:
    """获取 GitHub Token（优先级：配置文件 > 环境变量）"""
    config = load_config()
    if "github_token" in config:
        return cast(str, config["github_token"])
    return os.environ.get("GITHUB_TOKEN")


def get_anthropic_api_key() -> str | None:
    """获取 Anthropic API Key（优先级：配置文件 > 环境变量）

    支持的环境变量（按优先级）:
    1. ANTHROPIC_AUTH_TOKEN (官方推荐)
    2. ANTHROPIC_API_KEY (兼容旧版)
    """
    config = load_config()
    if "anthropic_api_key" in config:
        return cast(str, config["anthropic_api_key"])

    # 优先使用官方推荐的环境变量名
    return os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")


def get_anthropic_base_url() -> str | None:
    """获取 Anthropic Base URL（用于代理等）

    优先级：配置文件 > 环境变量 > Provider 默认值。
    """
    config = load_config()
    if "anthropic_base_url" in config:
        return cast(str, config["anthropic_base_url"])

    env_base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if env_base_url:
        return env_base_url

    # 如果配置了 provider，使用其默认值
    if "provider" in config:
        provider = PROVIDERS.get(config["provider"])
        if provider:
            return provider["base_url"]

    return None


# Provider 预设配置
PROVIDERS: dict[str, dict[str, str]] = {
    "minimax": {
        "base_url": "https://api.minimaxi.com/anthropic",
        "model": "MiniMax-M2.7-highspeed",
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/anthropic",
        "model": "glm-5v-turbo",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-6",
    },
}


def get_anthropic_model() -> str:
    """获取 Anthropic/Agent 模型名。

    优先级：配置文件 > 环境变量 > Provider 默认值。
    """
    config = load_config()
    if "anthropic_model" in config:
        return cast(str, config["anthropic_model"])

    env_model = os.environ.get("ANTHROPIC_MODEL")
    if env_model:
        return env_model

    # 如果配置了 provider，使用其默认值
    if "provider" in config:
        provider = PROVIDERS.get(config["provider"])
        if provider:
            return provider["model"]

    return "glm-5-turbo"


def set_github_token(token: str) -> None:
    """设置 GitHub Token"""
    config = load_config()
    config["github_token"] = token
    save_config(config)


def set_anthropic_api_key(api_key: str) -> None:
    """设置 Anthropic API Key"""
    config = load_config()
    config["anthropic_api_key"] = api_key
    save_config(config)


def set_anthropic_base_url(base_url: str) -> None:
    """设置 Anthropic Base URL"""
    config = load_config()
    config["anthropic_base_url"] = base_url
    save_config(config)


def set_anthropic_model(model: str) -> None:
    """设置 Agent 模型名"""
    config = load_config()
    config["anthropic_model"] = model
    save_config(config)


def set_provider(provider: str) -> None:
    """设置 Provider 预设（会同时设置 base_url 和 model）"""
    if provider not in PROVIDERS:
        raise ValueError(f"未知的 Provider: {provider}，可用: {', '.join(PROVIDERS.keys())}")

    config = load_config()
    config["provider"] = provider
    config["anthropic_base_url"] = PROVIDERS[provider]["base_url"]
    config["anthropic_model"] = PROVIDERS[provider]["model"]
    save_config(config)
