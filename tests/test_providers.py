"""Tests for pm_core.providers — LLM provider configuration."""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pm_core.providers import (
    ProviderConfig,
    ProviderTestResult,
    get_provider,
    list_providers,
    load_providers,
    save_providers,
    set_session_provider,
    get_default_provider,
    set_default_provider,
    check_provider,
    get_recommended_models,
    format_model_recommendations,
    _resolve_env_ref,
    _get_system_memory_gb,
    BUILTIN_CLAUDE,
    RECOMMENDED_MODELS,
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

    def test_local_provider(self):
        p = ProviderConfig(name="ollama", type="local",
                          api_base="http://localhost:11434",
                          model="qwen3.5")
        env = p.env_vars()
        assert env["ANTHROPIC_BASE_URL"] == "http://localhost:11434"
        assert env["ANTHROPIC_API_KEY"] == ""
        assert env["ANTHROPIC_AUTH_TOKEN"] == "ollama"
        assert p.model_flag() == "qwen3.5"

    def test_local_provider_custom_key(self):
        p = ProviderConfig(name="custom", type="local",
                          api_base="http://localhost:8001",
                          api_key="my-key",
                          model="glm-4.7-flash")
        env = p.env_vars()
        assert env["ANTHROPIC_API_KEY"] == "my-key"
        assert "ANTHROPIC_AUTH_TOKEN" not in env

    def test_openai_provider(self):
        p = ProviderConfig(name="vllm", type="openai",
                          api_base="http://localhost:8000/v1",
                          api_key="vllm-key",
                          model="codellama")
        env = p.env_vars()
        assert env["OPENAI_BASE_URL"] == "http://localhost:8000/v1"
        assert env["OPENAI_API_KEY"] == "vllm-key"
        assert p.model_flag() == "openai:codellama"

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


# ---------------------------------------------------------------------------
# ProviderTestResult
# ---------------------------------------------------------------------------

class TestProviderTestResult:
    def test_ok_when_reachable_and_tools_ok(self):
        r = ProviderTestResult(reachable=True, tool_use=True)
        assert r.ok
        assert r.warnings == []

    def test_ok_when_reachable_and_tools_not_tested(self):
        r = ProviderTestResult(reachable=True, tool_use=None)
        assert r.ok

    def test_not_ok_when_unreachable(self):
        r = ProviderTestResult(reachable=False, reachable_detail="connection refused")
        assert not r.ok
        assert len(r.warnings) == 1
        assert "not reachable" in r.warnings[0]

    def test_not_ok_when_tool_use_fails(self):
        r = ProviderTestResult(reachable=True, tool_use=False,
                               tool_use_detail="model did not use tool")
        assert not r.ok
        assert len(r.warnings) == 1
        assert "function calling" in r.warnings[0]

    def test_tool_use_warning_includes_recommendations(self):
        r = ProviderTestResult(reachable=True, tool_use=False,
                               tool_use_detail="did not call tool")
        warning = r.warnings[0]
        assert "Recommended models" in warning
        assert "qwen3.5" in warning


# ---------------------------------------------------------------------------
# check_provider
# ---------------------------------------------------------------------------

class TestCheckProvider:
    def test_no_api_base(self):
        p = ProviderConfig(name="empty", type="openai")
        result = check_provider(p)
        assert not result.reachable
        assert "no API base URL" in result.reachable_detail

    @patch("urllib.request.urlopen")
    def test_reachable(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        p = ProviderConfig(name="test", type="openai",
                          api_base="http://localhost:11434/v1")
        result = check_provider(p, check_tools=False)
        assert result.reachable
        assert "HTTP 200" in result.reachable_detail

    @patch("urllib.request.urlopen")
    def test_unreachable(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        p = ProviderConfig(name="test", type="openai",
                          api_base="http://localhost:99999/v1")
        result = check_provider(p)
        assert not result.reachable
        assert "connection failed" in result.reachable_detail

    @patch("urllib.request.urlopen")
    def test_tool_use_success(self, mock_urlopen):
        import json
        # First call: /models (connectivity)
        models_resp = MagicMock()
        models_resp.status = 200
        models_resp.__enter__ = MagicMock(return_value=models_resp)
        models_resp.__exit__ = MagicMock(return_value=False)

        # Second call: /chat/completions (tool use)
        chat_body = json.dumps({
            "choices": [{
                "message": {"tool_calls": [{"function": {"name": "calculator"}}]},
                "finish_reason": "tool_calls",
            }]
        }).encode()
        chat_resp = MagicMock()
        chat_resp.read.return_value = chat_body
        chat_resp.__enter__ = MagicMock(return_value=chat_resp)
        chat_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [models_resp, chat_resp]

        p = ProviderConfig(name="test", type="openai",
                          api_base="http://localhost:11434/v1",
                          model="llama3.1")
        result = check_provider(p)
        assert result.reachable
        assert result.tool_use is True

    @patch("urllib.request.urlopen")
    def test_tool_use_failure(self, mock_urlopen):
        import json
        models_resp = MagicMock()
        models_resp.status = 200
        models_resp.__enter__ = MagicMock(return_value=models_resp)
        models_resp.__exit__ = MagicMock(return_value=False)

        chat_body = json.dumps({
            "choices": [{
                "message": {"content": "The answer is 4"},
                "finish_reason": "stop",
            }]
        }).encode()
        chat_resp = MagicMock()
        chat_resp.read.return_value = chat_body
        chat_resp.__enter__ = MagicMock(return_value=chat_resp)
        chat_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [models_resp, chat_resp]

        p = ProviderConfig(name="test", type="openai",
                          api_base="http://localhost:11434/v1",
                          model="tiny-model")
        result = check_provider(p)
        assert result.reachable
        assert result.tool_use is False
        assert "did not use the tool" in result.tool_use_detail


# ---------------------------------------------------------------------------
# Recommended models
# ---------------------------------------------------------------------------

class TestRecommendedModels:
    def test_models_list_not_empty(self):
        assert len(RECOMMENDED_MODELS) > 0

    def test_models_ordered_by_size(self):
        sizes = [m.param_billions for m in RECOMMENDED_MODELS]
        assert sizes == sorted(sizes)

    def test_get_recommended_with_plenty_of_ram(self):
        with patch("pm_core.providers._get_system_memory_gb", return_value=128.0), \
             patch("pm_core.providers._get_gpu_memory_gb", return_value=None):
            models = get_recommended_models()
            assert all(fits for _, fits in models)

    def test_get_recommended_with_limited_ram(self):
        with patch("pm_core.providers._get_system_memory_gb", return_value=8.0), \
             patch("pm_core.providers._get_gpu_memory_gb", return_value=None):
            models = get_recommended_models()
            # Some should fit (7GB model), some shouldn't (24GB+ models)
            fits_list = [fits for _, fits in models]
            assert True in fits_list
            assert False in fits_list

    def test_get_recommended_uses_gpu_if_larger(self):
        with patch("pm_core.providers._get_system_memory_gb", return_value=8.0), \
             patch("pm_core.providers._get_gpu_memory_gb", return_value=24.0):
            models = get_recommended_models()
            # 24GB VRAM should fit 32B model (20GB required)
            for model, fits in models:
                if model.ram_gb_required <= 24:
                    assert fits

    def test_format_includes_model_tags(self):
        with patch("pm_core.providers._get_system_memory_gb", return_value=16.0), \
             patch("pm_core.providers._get_gpu_memory_gb", return_value=None):
            text = format_model_recommendations()
            assert "glm-4.7-flash" in text
            assert "Recommended models" in text
            assert "16 GB" in text

    def test_format_marks_unfitting_models(self):
        with patch("pm_core.providers._get_system_memory_gb", return_value=6.0), \
             patch("pm_core.providers._get_gpu_memory_gb", return_value=None):
            text = format_model_recommendations()
            assert "needs" in text  # "needs X GB" for models that don't fit
