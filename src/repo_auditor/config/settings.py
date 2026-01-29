"""配置管理 - 读写用户配置"""

import os
from pathlib import Path
from typing import Any

import tomli_w

# 配置文件路径
CONFIG_DIR = Path.home() / ".config" / "repo-auditor"
CONFIG_FILE = CONFIG_DIR / "config.toml"


def ensure_config_dir() -> None:
    """确保配置目录存在"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def get_config_path() -> Path:
    """获取配置文件路径"""
    return CONFIG_FILE


def load_config() -> dict[str, Any]:
    """加载配置文件"""
    if not CONFIG_FILE.exists():
        return {}

    try:
        import tomli

        with open(CONFIG_FILE, "rb") as f:
            return tomli.load(f)
    except ImportError:
        return {}
    except Exception:
        return {}


def save_config(config: dict[str, Any]) -> None:
    """保存配置文件"""
    ensure_config_dir()

    with open(CONFIG_FILE, "w") as f:
        tomli_w.dump(config, f)


def get_github_token() -> str | None:
    """获取 GitHub Token（优先级：配置文件 > 环境变量）"""
    config = load_config()
    if "github_token" in config:
        return config["github_token"]
    return os.environ.get("GITHUB_TOKEN")


def get_anthropic_api_key() -> str | None:
    """获取 Anthropic API Key（优先级：配置文件 > 环境变量）

    支持的环境变量（按优先级）:
    1. ANTHROPIC_AUTH_TOKEN (官方推荐)
    2. ANTHROPIC_API_KEY (兼容旧版)
    """
    config = load_config()
    if "anthropic_api_key" in config:
        return config["anthropic_api_key"]

    # 优先使用官方推荐的环境变量名
    return os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")


def get_anthropic_base_url() -> str | None:
    """获取 Anthropic Base URL（用于代理等）

    支持的环境变量: ANTHROPIC_BASE_URL
    """
    config = load_config()
    if "anthropic_base_url" in config:
        return config["anthropic_base_url"]

    return os.environ.get("ANTHROPIC_BASE_URL")


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
