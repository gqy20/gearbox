"""测试 config 模块"""

import os
import stat
import warnings
from pathlib import Path

from gearbox.config import (
    AGENT_DEFAULTS,
    PROVIDERS,
    get_anthropic_api_key,
    get_anthropic_base_url,
    get_anthropic_model,
    get_config_path,
    get_github_token,
    load_config,
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


class TestConfigFilePermissions:
    """测试配置文件权限限制 (Issue #40)"""

    def test_save_config_sets_file_permissions_0o600(self, temp_home: Path) -> None:
        """save_config 写入后应将配置文件权限设为 0o600（仅 owner 可读写）"""
        os.environ["XDG_CONFIG_HOME"] = str(temp_home)

        save_config({"anthropic_api_key": "sk-test-key", "github_token": "ghp_test"})

        config_file = get_config_path()
        mode = stat.S_IMODE(config_file.stat().st_mode)
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_save_config_restricts_directory_permissions(self, temp_home: Path) -> None:
        """save_config 应限制配置目录权限为 0o700"""
        os.environ["XDG_CONFIG_HOME"] = str(temp_home)

        save_config({"test_key": "test_value"})

        config_dir = get_config_path().parent
        dir_mode = stat.S_IMODE(config_dir.stat().st_mode)
        # 目录应仅允许 owner 访问
        assert dir_mode == 0o700, f"Expected directory 0o700, got {oct(dir_mode)}"

    def test_save_config_with_sensitive_data_is_not_world_readable(
        self,
        temp_home: Path,
    ) -> None:
        """包含敏感数据的配置文件不应被其他用户读取"""
        os.environ["XDG_CONFIG_HOME"] = str(temp_home)

        save_config(
            {
                "anthropic_api_key": "sk-secret-12345",
                "github_token": "ghp_secret_token",
            }
        )

        config_file = get_config_path()
        mode = stat.S_IMODE(config_file.stat().st_mode)
        # 确保组和其他用户无任何权限
        assert mode & stat.S_IRGRP == 0, "Group should not have read permission"
        assert mode & stat.S_IWGRP == 0, "Group should not have write permission"
        assert mode & stat.S_IROTH == 0, "Others should not have read permission"
        assert mode & stat.S_IWOTH == 0, "Others should not have write permission"

    def test_load_config_warns_on_insecure_permissions(self, temp_home: Path) -> None:
        """load_config 在文件权限过宽时应发出警告"""
        os.environ["XDG_CONFIG_HOME"] = str(temp_home)
        config_dir = temp_home / ".config" / "gearbox"
        config_dir.mkdir(parents=True)

        # 手动创建一个权限过宽的配置文件
        config_file = config_dir / "config.toml"
        config_file.write_text('key = "value"', encoding="utf-8")
        config_file.chmod(0o644)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            load_config()
            warning_messages = [str(x.message) for x in w]
            assert any("permission" in msg.lower() or "权限" in msg for msg in warning_messages), (
                f"Expected a permission warning but got: {[str(x.message) for x in w]}"
            )
