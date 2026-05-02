"""测试 config 模块"""

import logging
import os
import time
from pathlib import Path

import pytest

from gearbox.config import (
    AGENT_DEFAULTS,
    PROVIDERS,
    get_anthropic_api_key,
    get_anthropic_base_url,
    get_anthropic_model,
    get_config_path,
    get_github_token,
    load_config,
    reload_config,
    save_config,
)


class TestGetConfigPath:
    """测试 get_config_path"""

    def test_returns_path_object(self) -> None:
        path = get_config_path()
        assert isinstance(path, Path)

    def test_path_exists_or_creatable(self) -> None:
        path = get_config_path()
        assert ".toml" in str(path)


class TestLoadConfig:
    """测试 load_config"""

    def test_returns_dict(self) -> None:
        result = load_config()
        assert isinstance(result, dict)


class TestSaveConfig:
    """测试 save_config"""

    def test_saves_toml_file(self, temp_home: Path) -> None:
        config_dir = temp_home / ".config" / "gearbox"
        config_dir.mkdir(parents=True)
        os.environ["XDG_CONFIG_HOME"] = str(temp_home)

        save_config({"test_key": "test_value"})

        path = get_config_path()
        assert path.exists()
        with open(path, "r") as f:
            content = f.read()
            assert "test_key" in content


class TestGithubToken:
    """测试 GitHub Token 相关函数"""

    def test_get_github_token_env(self) -> None:
        os.environ["GITHUB_TOKEN"] = "ghp_test_token"
        try:
            token = get_github_token()
            assert token == "ghp_test_token"
        finally:
            del os.environ["GITHUB_TOKEN"]

    def test_get_github_token_empty_when_not_set(self) -> None:
        if "GITHUB_TOKEN" in os.environ:
            del os.environ["GITHUB_TOKEN"]
        token = get_github_token()
        assert token is None or token == ""


class TestAnthropicApiKey:
    """测试 Anthropic API Key 相关函数"""

    def test_get_api_key_auth_token_env(self) -> None:
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "sk-test-auth"
        try:
            key = get_anthropic_api_key()
            assert key == "sk-test-auth"
        finally:
            del os.environ["ANTHROPIC_AUTH_TOKEN"]

    def test_get_api_key_api_key_env_fallback(self) -> None:
        if "ANTHROPIC_AUTH_TOKEN" in os.environ:
            del os.environ["ANTHROPIC_AUTH_TOKEN"]
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-api"
        try:
            key = get_anthropic_api_key()
            assert key == "sk-test-api"
        finally:
            del os.environ["ANTHROPIC_API_KEY"]


class TestAnthropicModel:
    """测试 get_anthropic_model"""

    def test_returns_string(self) -> None:
        model = get_anthropic_model()
        assert isinstance(model, str)
        assert len(model) > 0

    def test_env_override(self) -> None:
        os.environ["ANTHROPIC_MODEL"] = "test-model"
        try:
            model = get_anthropic_model()
            assert model == "test-model"
        finally:
            del os.environ["ANTHROPIC_MODEL"]

    def test_env_wins_over_provider(self, temp_home: Path) -> None:
        os.environ["XDG_CONFIG_HOME"] = str(temp_home)
        os.environ["ANTHROPIC_MODEL"] = "env-model"
        try:
            config_dir = temp_home / ".config" / "gearbox"
            config_dir.mkdir(parents=True)
            save_config({"provider": "glm"})
            model = get_anthropic_model()
            assert model == "env-model"
        finally:
            del os.environ["ANTHROPIC_MODEL"]


class TestAnthropicBaseUrl:
    """测试 get_anthropic_base_url"""

    def test_env_override(self) -> None:
        os.environ["ANTHROPIC_BASE_URL"] = "https://proxy.example.com/anthropic"
        try:
            base_url = get_anthropic_base_url()
            assert base_url == "https://proxy.example.com/anthropic"
        finally:
            del os.environ["ANTHROPIC_BASE_URL"]

    def test_provider_used_when_env_missing(self, temp_home: Path) -> None:
        os.environ["XDG_CONFIG_HOME"] = str(temp_home)
        config_dir = temp_home / ".config" / "gearbox"
        config_dir.mkdir(parents=True)
        save_config({"provider": "glm"})

        base_url = get_anthropic_base_url()
        assert base_url == PROVIDERS["glm"]["base_url"]


class TestProviders:
    """测试 PROVIDERS 配置"""

    def test_providers_is_dict(self) -> None:
        assert isinstance(PROVIDERS, dict)

    def test_providers_has_expected_keys(self) -> None:
        assert "minimax" in PROVIDERS
        assert "glm" in PROVIDERS
        assert "anthropic" in PROVIDERS

    def test_provider_has_base_url_and_model(self) -> None:
        for name, config in PROVIDERS.items():
            assert "base_url" in config
            assert "model" in config
            assert isinstance(config["base_url"], str)
            assert isinstance(config["model"], str)


class TestAgentDefaults:
    """测试 AGENT_DEFAULTS"""

    def test_is_dict(self) -> None:
        assert isinstance(AGENT_DEFAULTS, dict)

    def test_has_max_turns(self) -> None:
        assert "max_turns" in AGENT_DEFAULTS
        assert isinstance(AGENT_DEFAULTS["max_turns"], dict)
        assert "backlog" in AGENT_DEFAULTS["max_turns"]
        assert "review" in AGENT_DEFAULTS["max_turns"]
        assert "implement" in AGENT_DEFAULTS["max_turns"]
        assert "audit" in AGENT_DEFAULTS["max_turns"]
        assert AGENT_DEFAULTS["max_turns"]["implement"] == 80


class TestConfigCache:
    """测试配置缓存行为 (Issue #60)"""

    def test_multiple_loads_return_cached_object(self, temp_home: Path, caplog: pytest.LogCaptureFixture) -> None:
        """连续多次 load_config 应返回缓存对象（同一 identity），避免重复 I/O"""
        config_dir = temp_home / ".config" / "gearbox"
        config_dir.mkdir(parents=True)
        save_config({"anthropic_model": "cached-model-v1"})

        with caplog.at_level(logging.DEBUG, logger="gearbox.config.settings"):
            first = load_config()
            second = load_config()
            third = load_config()

        # 后续调用应返回同一对象（缓存命中）
        assert first is second is third
        # 应有 cache hit 日志
        assert any("cache hit" in r.message.lower() for r in caplog.records)

    def test_cache_invalidated_on_file_change(self, temp_home: Path) -> None:
        """文件修改后，下次 load_config 应重新读取"""
        config_dir = temp_home / ".config" / "gearbox"
        config_dir.mkdir(parents=True)
        save_config({"anthropic_model": "model-v1"})

        first = load_config()
        assert first["anthropic_model"] == "model-v1"

        # 修改文件
        time.sleep(0.05)  # 确保 mtime 变化
        save_config({"anthropic_model": "model-v2"})

        second = load_config()
        assert second["anthropic_model"] == "model-v2"
        # 对象 identity 不同（缓存失效后重新加载）
        assert first is not second

    def test_reload_config_forces_refresh(self, temp_home: Path) -> None:
        """reload_config() 应强制刷新缓存，即使文件未变"""
        config_dir = temp_home / ".config" / "gearbox"
        config_dir.mkdir(parents=True)
        save_config({"key": "original"})

        first = load_config()

        # 不改文件，强制 reload
        reloaded = reload_config()
        assert reloaded["key"] == "original"
        # reload 返回新对象
        assert first is not reloaded

    def test_getters_use_cache_consistently(self, temp_home: Path) -> None:
        """getter 函数在单次事务内应读到一致的配置快照（无 TOCTOU）"""
        config_dir = temp_home / ".config" / "gearbox"
        config_dir.mkdir(parents=True)
        save_config({
            "anthropic_api_key": "key-for-model-x",
            "anthropic_model": "model-x",
        })

        # 连续调用多个 getter，应全部命中缓存并返回一致数据
        key1 = get_anthropic_api_key()
        model1 = get_anthropic_model()
        key2 = get_anthropic_api_key()
        model2 = get_anthropic_model()

        assert key1 == "key-for-model-x"
        assert model1 == "model-x"
        assert key1 == key2
        assert model1 == model2
