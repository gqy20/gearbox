"""Extended tests for config settings — set_* functions and edge cases."""

import os
from pathlib import Path

import pytest

from gearbox.config import (
    PROVIDERS,
    get_anthropic_api_key,
    get_anthropic_base_url,
    get_anthropic_model,
    get_config_path,
    get_github_token,
    load_config,
    save_config,
    set_anthropic_api_key,
    set_anthropic_base_url,
    set_anthropic_model,
    set_github_token,
    set_provider,
)


class TestEnsureConfigDir:
    """测试 ensure_config_dir (通过 save_config 间接验证)"""

    def test_save_config_creates_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))

        save_config({"test": True})

        assert get_config_path().parent.exists()


class TestSetGithubToken:
    """测试 set_github_token"""

    def test_saves_and_retrieves_token(self, temp_home: Path) -> None:
        set_github_token("ghp_new_token")
        assert get_github_token() == "ghp_new_token"

    def test_overwrites_existing_token(self, temp_home: Path) -> None:
        set_github_token("first")
        set_github_token("second")
        assert get_github_token() == "second"


class TestSetAnthropicApiKey:
    """测试 set_anthropic_api_key"""

    def test_saves_and_retrieves_key(self, temp_home: Path) -> None:
        # Clear env to test file-based storage
        for key in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
            os.environ.pop(key, None)

        set_anthropic_api_key("sk-new-key")
        assert get_anthropic_api_key() == "sk-new-key"

    def test_config_file_overrides_env(self, temp_home: Path) -> None:
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "env-key"
        set_anthropic_api_key("file-key")
        # File should take priority
        assert get_anthropic_api_key() == "file-key"


class TestSetAnthropicBaseUrl:
    """测试 set_anthropic_base_url"""

    def test_saves_and_retrieves_url(self, temp_home: Path) -> None:
        os.environ.pop("ANTHROPIC_BASE_URL", None)
        set_anthropic_base_url("https://custom.proxy.com/v1")
        assert get_anthropic_base_url() == "https://custom.proxy.com/v1"


class TestSetAnthropicModel:
    """测试 set_anthropic_model"""

    def test_saves_and_retrieves_model(self, temp_home: Path) -> None:
        os.environ.pop("ANTHROPIC_MODEL", None)
        set_anthropic_model("custom-model-v2")
        assert get_anthropic_model() == "custom-model-v2"

    def test_config_wins_over_env(self, temp_home: Path) -> None:
        os.environ["ANTHROPIC_MODEL"] = "env-model"
        set_anthropic_model("config-model")
        assert get_anthropic_model() == "config-model"


class TestSetProvider:
    """测试 set_provider"""

    def test_sets_glm_provider(self, temp_home: Path) -> None:
        set_provider("glm")

        config = load_config()
        assert config["provider"] == "glm"
        assert get_anthropic_base_url() == PROVIDERS["glm"]["base_url"]
        assert get_anthropic_model() == PROVIDERS["glm"]["model"]

    def test_sets_anthropic_provider(self, temp_home: Path) -> None:
        set_provider("anthropic")

        config = load_config()
        assert config["provider"] == "anthropic"
        assert get_anthropic_base_url() == PROVIDERS["anthropic"]["base_url"]
        assert get_anthropic_model() == PROVIDERS["anthropic"]["model"]

    def test_sets_minimax_provider(self, temp_home: Path) -> None:
        set_provider("minimax")

        config = load_config()
        assert config["provider"] == "minimax"
        assert get_anthropic_base_url() == PROVIDERS["minimax"]["base_url"]
        assert get_anthropic_model() == PROVIDERS["minimax"]["model"]

    def test_raises_for_unknown_provider(self, temp_home: Path) -> None:
        with pytest.raises(ValueError, match="未知的 Provider"):
            set_provider("nonexistent")


class TestLoadConfigEdgeCases:
    """测试 load_config 边界情况"""

    def test_returns_empty_dict_when_file_missing(self, temp_home: Path) -> None:
        result = load_config()
        assert result == {}

    def test_returns_empty_on_tomli_import_error(
        self, temp_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force tomli import to fail by making it unimportable
        import importlib.util

        original_find = importlib.util.find_spec

        def failing_find(name, *args, **kwargs):
            if name == "tomli":
                return None
            return original_find(name, *args, **kwargs)

        monkeypatch.setattr(importlib.util, "find_spec", failing_find)
        result = load_config()
        assert isinstance(result, dict)


class TestSaveConfigRoundTrip:
    """测试 save_config / load_config 往返一致性"""

    def test_round_trip_preserves_data(self, temp_home: Path) -> None:
        original = {
            "github_token": "token123",
            "anthropic_api_key": "key456",
            "provider": "glm",
            "custom_field": [1, 2, 3],
        }
        save_config(original)
        loaded = load_config()

        assert loaded["github_token"] == "token123"
        assert loaded["anthropic_api_key"] == "key456"
        assert loaded["provider"] == "glm"
        assert loaded["custom_field"] == [1, 2, 3]
