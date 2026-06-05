"""测试 config 模块"""

import os
from pathlib import Path
from unittest.mock import patch

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


class TestConfigConsistency:
    """测试配置读取一致性：多次 getter 调用应返回同一快照的值 (Issue #119)"""

    @staticmethod
    def _clear_anthropic_env() -> dict[str, str | None]:
        """移除可能干扰测试的 Anthropic 环境变量"""
        saved: dict[str, str | None] = {}
        for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            saved[key] = os.environ.pop(key, None)
        return saved

    @staticmethod
    def _restore_env(saved: dict[str, str | None]) -> None:
        for key, val in saved.items():
            if val is not None:
                os.environ[key] = val
            elif key in os.environ:
                del os.environ[key]

    def test_single_file_read_for_multiple_getters(self, tmp_path: Path) -> None:
        """连续调用多个 getter 只触发一次文件 I/O（缓存生效）"""
        import gearbox.config.settings as settings_mod

        saved = self._clear_anthropic_env()
        try:
            cfg_dir = tmp_path / ".config" / "gearbox"
            cfg_dir.mkdir(parents=True)
            cfg_file = cfg_dir / "config.toml"

            with open(cfg_file, "wb") as f:
                import tomli_w

                tomli_w.dump({"provider": "glm"}, f)

            # Patch get_config_path so load_config reads our temp file
            with patch.object(settings_mod, "get_config_path", return_value=cfg_file):
                # 清除可能存在的旧缓存
                settings_mod.load_config.cache_clear()  # type: ignore[attr-defined]

                read_count = 0
                _original_open = open

                def counting_open(path, *args, **kwargs):
                    nonlocal read_count
                    if str(path) == str(cfg_file) and "rb" in args and len(args) > 0:
                        read_count += 1
                    return _original_open(path, *args, **kwargs)

                with patch("builtins.open", side_effect=counting_open):
                    get_anthropic_base_url()
                    get_anthropic_model()
                    get_anthropic_api_key()

            # 缓存生效：三次 getter 只产生一次文件读取
            assert read_count == 1, f"Expected 1 file read, got {read_count}"
        finally:
            self._restore_env(saved)

    def test_getters_return_consistent_provider_pair(self, tmp_path: Path) -> None:
        """base_url 和 model 必须来自同一 provider 快照"""
        import gearbox.config.settings as settings_mod

        saved = self._clear_anthropic_env()
        try:
            cfg_dir = tmp_path / ".config" / "gearbox"
            cfg_dir.mkdir(parents=True)
            cfg_file = cfg_dir / "config.toml"

            with open(cfg_file, "wb") as f:
                import tomli_w

                tomli_w.dump({"provider": "minimax"}, f)

            with patch.object(settings_mod, "get_config_path", return_value=cfg_file):
                settings_mod.load_config.cache_clear()  # type: ignore[attr-defined]

                base_url = get_anthropic_base_url()
                model = get_anthropic_model()

            # 两者必须来自同一 provider 的预设
            assert (base_url, model) == (
                PROVIDERS["minimax"]["base_url"],
                PROVIDERS["minimax"]["model"],
            ), f"base_url/model 不匹配: ({base_url}, {model})"
        finally:
            self._restore_env(saved)

    def test_cache_invalidated_after_save(self, tmp_path: Path) -> None:
        """save_config 后缓存应失效，下次读取获取新值"""
        import gearbox.config.settings as settings_mod

        saved = self._clear_anthropic_env()
        try:
            cfg_dir = tmp_path / ".config" / "gearbox"
            cfg_dir.mkdir(parents=True)
            cfg_file = cfg_dir / "config.toml"

            with patch.object(settings_mod, "get_config_path", return_value=cfg_file):
                settings_mod.load_config.cache_clear()  # type: ignore[attr-defined]

                # 初始：minimax
                save_config({"provider": "minimax"})
                assert get_anthropic_base_url() == PROVIDERS["minimax"]["base_url"]
                assert get_anthropic_model() == PROVIDERS["minimax"]["model"]

                # 保存新值后缓存自动清除
                save_config({"provider": "anthropic"})
                assert get_anthropic_base_url() == PROVIDERS["anthropic"]["base_url"]
                assert get_anthropic_model() == PROVIDERS["anthropic"]["model"]
        finally:
            self._restore_env(saved)
