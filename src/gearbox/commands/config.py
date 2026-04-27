"""Configuration CLI commands."""

import click

from gearbox.config import (
    get_config_path,
    get_github_token,
    load_config,
    set_anthropic_api_key,
    set_anthropic_base_url,
    set_anthropic_model,
    set_github_token,
    set_provider,
)


@click.group()
def config() -> None:
    """配置管理 - 设置密钥和选项"""
    pass


@config.command("list")
def config_list() -> None:
    """查看当前配置"""
    cfg = load_config()

    click.echo(f"配置文件: {get_config_path()}")
    click.echo()

    if not cfg:
        click.echo("（空配置）")
        return

    for key, value in cfg.items():
        if "token" in key.lower() or "key" in key.lower():
            masked = value[:8] + "..." if len(value) > 8 else "***"
            click.echo(f"{key}: {masked}")
        else:
            click.echo(f"{key}: {value}")

    click.echo()
    click.echo("环境变量:")
    click.echo(f"  GITHUB_TOKEN: {'***已设置***' if get_github_token() else '(未设置)'}")


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """设置配置项

    \b
    可用的 KEY:
      github-token           GitHub Token (用于 gh 命令)
      anthropic-api-key      API Key (必需)
      provider               预设 Provider (minimax/glm/anthropic)
      anthropic-base-url     Base URL (provider 预设时会自动设置)
      anthropic-model        模型名 (默认: glm-5-turbo)

    \b
    Provider 预设 (一键配置 base_url + model):
      minimax                MiniMax API (base_url + MiniMax-M2.7-highspeed)
      glm                    智谱 GLM API (base_url + glm-5v-turbo)
      anthropic              Anthropic API (base_url + claude-sonnet-4-6)

    \b
    示例:
        gearbox config set provider minimax
        gearbox config set anthropic-api-key sk-xxxxx
    """
    key_map = {
        "github-token": set_github_token,
        "anthropic-api-key": set_anthropic_api_key,
        "anthropic-base-url": set_anthropic_base_url,
        "anthropic-model": set_anthropic_model,
        "provider": set_provider,
    }

    if key not in key_map:
        click.echo(f"❌ 未知的配置项: {key}")
        click.echo("\n可用的配置项:")
        for k in key_map:
            click.echo(f"  - {k}")
        raise click.Abort()

    key_map[key](value)
    click.echo(f"✅ 已设置 {key}")

    click.echo("\n当前配置:")
    config_list()


@config.command("path")
def config_path() -> None:
    """显示配置文件路径"""
    click.echo(f"{get_config_path()}")
