"""Tests for pm_core.providers — LLM provider configuration."""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pm_core.providers import (
    ProviderConfig,
    get_provider,
    list_providers,
    load_providers,
    save_providers,
    set_session_provider,
    get_default_provider,
    set_default_provider,
    _resolve_env_ref,
    BUILTIN_CLAUDE,
)


# ---------------------------------------------------------------------------
# ProviderConfig
# ---------------------------------------------------------------------------

class TestProviderConfig:
    def test_default_is_claude(self):
        p = ProviderConfig(name="claude")
        assert p.type == "claude"
        assert p.env_vars() == {}
        assert p.model_flag() is None

    def test_claude_with_model(self):
        p = ProviderConfig(name="custom-claude", type="claude", model="claude-sonnet-4-20250514")
        assert p.model_flag() == "claude-sonnet-4-20250514"
        assert p.env_vars() == {"ANTHROPIC_MODEL": "claude-sonnet-4-20250514"}

    def test_claude_with_custom_base(self):
        p = ProviderConfig(name="proxy", type="claude",
                          api_base="https://proxy.example.com/v1",
                          api_key="sk-proxy-key")
        env = p.env_vars()
        assert env["ANTHROPIC_BASE_URL"] == "https://proxy.example.com/v1"
        assert env["ANTHROPIC_API_KEY"] == "sk-proxy-key"

    def test_openai_provider(self):
        p = ProviderConfig(name="ollama", type="openai",
                          api_base="http://localhost:11434/v1",
                          api_key="ollama",
                          model="llama3.1:70b")
        env = p.env_vars()
        assert env["OPENAI_BASE_URL"] == "http://localhost:11434/v1"
        assert env["OPENAI_API_KEY"] == "ollama"
        assert p.model_flag() == "openai:llama3.1:70b"

    def test_openai_no_model(self):
        p = ProviderConfig(name="local", type="openai",
                          api_base="http://localhost:8000/v1")
        assert p.model_flag() is None

    def test_capabilities(self):
        p = ProviderConfig(name="test", capabilities=["code", "review"])
        assert p.has_capability("code")
        assert p.has_capability("review")
        assert not p.has_capability("plan")

    def test_no_capabilities_means_all(self):
        p = ProviderConfig(name="test")
        assert p.has_capability("anything")

    def test_env_var_reference(self):
        with patch.dict(os.environ, {"MY_KEY": "secret123"}):
            p = ProviderConfig(name="test", type="openai",
                              api_key="${MY_KEY}")
            env = p.env_vars()
            assert env["OPENAI_API_KEY"] == "secret123"

    def test_env_var_reference_missing(self):
        env_copy = os.environ.copy()
        env_copy.pop("NONEXISTENT_KEY", None)
        with patch.dict(os.environ, env_copy, clear=True):
            p = ProviderConfig(name="test", type="openai",
                              api_key="${NONEXISTENT_KEY}")
            env = p.env_vars()
            assert env["OPENAI_API_KEY"] == ""


# ---------------------------------------------------------------------------
# _resolve_env_ref
# ---------------------------------------------------------------------------

class TestResolveEnvRef:
    def test_plain_string(self):
        assert _resolve_env_ref("hello") == "hello"

    def test_env_ref(self):
        with patch.dict(os.environ, {"FOO": "bar"}):
            assert _resolve_env_ref("${FOO}") == "bar"

    def test_not_env_ref_partial(self):
        assert _resolve_env_ref("${FOO") == "${FOO"
        assert _resolve_env_ref("FOO}") == "FOO}"


# ---------------------------------------------------------------------------
# load_providers / save_providers
# ---------------------------------------------------------------------------

class TestLoadSaveProviders:
    def test_no_file_returns_empty(self, tmp_path):
        with patch("pm_core.providers.pm_home", return_value=tmp_path):
            assert load_providers() == {}

    def test_roundtrip(self, tmp_path):
        with patch("pm_core.providers.pm_home", return_value=tmp_path):
            data = {
                "providers": {
                    "ollama": {
                        "type": "openai",
                        "api_base": "http://localhost:11434/v1",
                        "model": "llama3.1",
                    }
                },
                "default": "ollama",
            }
            save_providers(data)
            loaded = load_providers()
            assert loaded["default"] == "ollama"
            assert loaded["providers"]["ollama"]["model"] == "llama3.1"


# ---------------------------------------------------------------------------
# get_provider
# ---------------------------------------------------------------------------

class TestGetProvider:
    def test_default_is_claude(self):
        with patch("pm_core.providers.load_providers", return_value={}), \
             patch("pm_core.providers.session_dir", return_value=None):
            p = get_provider()
            assert p.name == BUILTIN_CLAUDE
            assert p.type == "claude"

    def test_explicit_name(self):
        config = {
            "providers": {
                "ollama": {
                    "type": "openai",
                    "api_base": "http://localhost:11434/v1",
                    "model": "llama3.1",
                }
            }
        }
        with patch("pm_core.providers.load_providers", return_value=config), \
             patch("pm_core.providers.session_dir", return_value=None):
            p = get_provider("ollama")
            assert p.name == "ollama"
            assert p.type == "openai"
            assert p.api_base == "http://localhost:11434/v1"

    def test_env_var_override(self):
        config = {
            "providers": {
                "vllm": {
                    "type": "openai",
                    "api_base": "http://localhost:8000/v1",
                }
            }
        }
        with patch("pm_core.providers.load_providers", return_value=config), \
             patch("pm_core.providers.session_dir", return_value=None), \
             patch.dict(os.environ, {"PM_PROVIDER": "vllm"}):
            p = get_provider()
            assert p.name == "vllm"

    def test_unknown_provider_falls_back(self):
        with patch("pm_core.providers.load_providers", return_value={}), \
             patch("pm_core.providers.session_dir", return_value=None):
            p = get_provider("nonexistent")
            assert p.name == BUILTIN_CLAUDE

    def test_session_provider(self, tmp_path):
        sd = tmp_path / "session"
        sd.mkdir()
        (sd / "provider").write_text("ollama\n")
        config = {
            "providers": {
                "ollama": {
                    "type": "openai",
                    "api_base": "http://localhost:11434/v1",
                }
            }
        }
        with patch("pm_core.providers.load_providers", return_value=config), \
             patch("pm_core.providers.session_dir", return_value=sd):
            p = get_provider()
            assert p.name == "ollama"

    def test_config_default(self):
        config = {
            "providers": {
                "ollama": {
                    "type": "openai",
                    "api_base": "http://localhost:11434/v1",
                }
            },
            "default": "ollama",
        }
        with patch("pm_core.providers.load_providers", return_value=config), \
             patch("pm_core.providers.session_dir", return_value=None):
            p = get_provider()
            assert p.name == "ollama"


# ---------------------------------------------------------------------------
# list_providers
# ---------------------------------------------------------------------------

class TestListProviders:
    def test_includes_builtin(self):
        with patch("pm_core.providers.load_providers", return_value={}):
            providers = list_providers()
            assert any(p.name == BUILTIN_CLAUDE for p in providers)

    def test_includes_configured(self):
        config = {
            "providers": {
                "ollama": {
                    "type": "openai",
                    "api_base": "http://localhost:11434/v1",
                }
            }
        }
        with patch("pm_core.providers.load_providers", return_value=config):
            providers = list_providers()
            names = [p.name for p in providers]
            assert "claude" in names
            assert "ollama" in names


# ---------------------------------------------------------------------------
# set_session_provider
# ---------------------------------------------------------------------------

class TestSetSessionProvider:
    def test_writes_provider_file(self, tmp_path):
        sd = tmp_path / "session"
        sd.mkdir()
        with patch("pm_core.providers.session_dir", return_value=sd):
            set_session_provider("ollama")
            assert (sd / "provider").read_text().strip() == "ollama"
