"""Tests for pm_core.model_config — per-session model targeting."""

import pytest
from unittest.mock import patch

from pm_core.model_config import (
    resolve_model,
    resolve_model_and_provider,
    ModelResolution,
    _expand_tier,
    get_model_config_summary,
    get_pr_model_override,
    QUALITY_TIERS,
    DEFAULT_SESSION_MODELS,
    SESSION_TYPES,
)


class TestExpandTier:
    def test_known_tiers(self):
        assert _expand_tier("high") == "claude-opus-4-20250514"
        assert _expand_tier("standard") == "claude-sonnet-4-20250514"
        assert _expand_tier("economy") == "claude-haiku-4-5-20251001"

    def test_passthrough_model_id(self):
        assert _expand_tier("claude-custom-model") == "claude-custom-model"
        assert _expand_tier("my-local-model") == "my-local-model"


class TestResolveModel:
    def test_defaults(self):
        assert resolve_model("review") == QUALITY_TIERS["high"]
        assert resolve_model("impl") == QUALITY_TIERS["standard"]
        assert resolve_model("qa") == QUALITY_TIERS["standard"]
        assert resolve_model("watcher") == QUALITY_TIERS["economy"]
        assert resolve_model("merge") == QUALITY_TIERS["standard"]

    def test_cli_override_takes_precedence(self):
        result = resolve_model("review", cli_model="economy")
        assert result == QUALITY_TIERS["economy"]

    def test_cli_override_with_model_id(self):
        result = resolve_model("review", cli_model="claude-custom")
        assert result == "claude-custom"

    def test_pr_override(self):
        result = resolve_model("impl", pr_model="high")
        assert result == QUALITY_TIERS["high"]

    def test_cli_beats_pr(self):
        result = resolve_model("impl", cli_model="economy", pr_model="high")
        assert result == QUALITY_TIERS["economy"]

    def test_project_config(self):
        data = {
            "project": {
                "model_config": {
                    "session_models": {
                        "review": "standard",
                    }
                }
            }
        }
        result = resolve_model("review", project_data=data)
        assert result == QUALITY_TIERS["standard"]

    def test_pr_beats_project(self):
        data = {
            "project": {
                "model_config": {
                    "session_models": {
                        "review": "economy",
                    }
                }
            }
        }
        result = resolve_model("review", pr_model="standard", project_data=data)
        assert result == QUALITY_TIERS["standard"]

    @patch("pm_core.model_config.get_global_setting_value", return_value="high")
    def test_global_setting(self, mock_gsv):
        result = resolve_model("qa")
        assert result == QUALITY_TIERS["high"]
        mock_gsv.assert_called_with("model-qa")

    @patch("pm_core.model_config.get_global_setting_value", return_value="high")
    def test_project_beats_global(self, mock_gsv):
        data = {
            "project": {
                "model_config": {
                    "session_models": {
                        "qa": "economy",
                    }
                }
            }
        }
        result = resolve_model("qa", project_data=data)
        assert result == QUALITY_TIERS["economy"]

    def test_unknown_session_type(self):
        result = resolve_model("unknown-type")
        assert result is None


class TestGetModelConfigSummary:
    def test_defaults(self):
        summary = get_model_config_summary()
        assert summary["review"] == QUALITY_TIERS["high"]
        assert summary["watcher"] == QUALITY_TIERS["economy"]
        assert len(summary) == len(SESSION_TYPES)


class TestGetPrModelOverride:
    def test_present(self):
        assert get_pr_model_override({"model": "high"}) == "high"

    def test_absent(self):
        assert get_pr_model_override({}) is None
        assert get_pr_model_override({"title": "foo"}) is None


class TestBuildClaudeShellCmdModel:
    def test_model_flag_included(self):
        from pm_core.claude_launcher import build_claude_shell_cmd
        cmd = build_claude_shell_cmd(prompt="test", model="claude-sonnet-4-20250514")
        assert "--model claude-sonnet-4-20250514" in cmd

    def test_no_model_flag_when_none(self):
        from pm_core.claude_launcher import build_claude_shell_cmd
        cmd = build_claude_shell_cmd(prompt="test")
        assert "--model" not in cmd


class TestProviderResolution:
    """Test provider: prefix resolution via resolve_model_and_provider."""

    def test_provider_prefix_returns_provider(self):
        result = resolve_model_and_provider("watcher", cli_model="provider:ollama")
        assert result.provider == "ollama"
        assert result.model is None

    def test_non_provider_returns_model(self):
        result = resolve_model_and_provider("review")
        assert result.model == QUALITY_TIERS["high"]
        assert result.provider is None

    def test_provider_in_project_config(self):
        data = {
            "project": {
                "model_config": {
                    "session_models": {
                        "watcher": "provider:ollama",
                    }
                }
            }
        }
        result = resolve_model_and_provider("watcher", project_data=data)
        assert result.provider == "ollama"
        assert result.model is None

    def test_resolve_model_ignores_provider(self):
        """resolve_model returns None for provider: values (no model)."""
        result = resolve_model("watcher", cli_model="provider:ollama")
        assert result is None

    def test_summary_shows_provider(self):
        data = {
            "project": {
                "model_config": {
                    "session_models": {
                        "watcher": "provider:ollama",
                    }
                }
            }
        }
        summary = get_model_config_summary(data)
        assert summary["watcher"] == "provider:ollama"
        assert summary["review"] == QUALITY_TIERS["high"]

    @patch("pm_core.model_config.get_global_setting_value", return_value="provider:vllm")
    def test_global_setting_provider(self, mock_gsv):
        result = resolve_model_and_provider("qa")
        assert result.provider == "vllm"
        assert result.model is None
