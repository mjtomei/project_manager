"""Tests for pm_core.model_config — per-session model targeting."""

import pytest
from unittest.mock import patch

from pm_core.model_config import (
    resolve_model,
    resolve_model_and_provider,
    ModelResolution,
    get_model_config_summary,
    get_pr_model_override,
    QUALITY_TIERS,
    DEFAULT_SESSION_MODELS,
    DEFAULT_SESSION_EFFORT,
    SESSION_TYPES,
)


class TestQualityTiers:
    def test_low_medium_high(self):
        assert "low" in QUALITY_TIERS
        assert "medium" in QUALITY_TIERS
        assert "high" in QUALITY_TIERS

    def test_model_shortcuts(self):
        assert QUALITY_TIERS["opus"] == QUALITY_TIERS["high"]
        assert QUALITY_TIERS["sonnet"] == QUALITY_TIERS["medium"]
        assert QUALITY_TIERS["haiku"] == QUALITY_TIERS["low"]

    def test_passthrough_model_id(self):
        """Non-tier values are passed through as-is."""
        result = resolve_model("review", cli_model="claude-custom-model")
        assert result == "claude-custom-model"


class TestResolveModel:
    def test_defaults(self):
        assert resolve_model("review") == QUALITY_TIERS["high"]
        assert resolve_model("impl") == QUALITY_TIERS["medium"]
        assert resolve_model("qa") == QUALITY_TIERS["medium"]
        assert resolve_model("watcher") == QUALITY_TIERS["low"]
        assert resolve_model("merge") == QUALITY_TIERS["medium"]

    def test_cli_override_takes_precedence(self):
        assert resolve_model("review", cli_model="low") == QUALITY_TIERS["low"]

    def test_cli_with_model_name(self):
        assert resolve_model("review", cli_model="sonnet") == QUALITY_TIERS["sonnet"]
        assert resolve_model("review", cli_model="haiku") == QUALITY_TIERS["haiku"]

    def test_pr_override(self):
        assert resolve_model("impl", pr_model="high") == QUALITY_TIERS["high"]

    def test_cli_beats_pr(self):
        assert resolve_model("impl", cli_model="low", pr_model="high") == QUALITY_TIERS["low"]

    def test_project_config(self):
        data = {"project": {"model_config": {"session_models": {"review": "medium"}}}}
        assert resolve_model("review", project_data=data) == QUALITY_TIERS["medium"]

    def test_pr_beats_project(self):
        data = {"project": {"model_config": {"session_models": {"review": "low"}}}}
        assert resolve_model("review", pr_model="medium", project_data=data) == QUALITY_TIERS["medium"]

    @patch("pm_core.model_config.get_global_setting_value", return_value="high")
    def test_global_setting(self, mock_gsv):
        result = resolve_model("qa")
        assert result == QUALITY_TIERS["high"]

    @patch("pm_core.model_config.get_global_setting_value", return_value="high")
    def test_project_beats_global(self, mock_gsv):
        data = {"project": {"model_config": {"session_models": {"qa": "low"}}}}
        assert resolve_model("qa", project_data=data) == QUALITY_TIERS["low"]

    def test_unknown_session_type(self):
        assert resolve_model("unknown-type") is None


class TestEffortResolution:
    def test_defaults(self):
        result = resolve_model_and_provider("review")
        assert result.effort == "high"
        result = resolve_model_and_provider("watcher")
        assert result.effort == "low"
        result = resolve_model_and_provider("qa")
        assert result.effort == "medium"

    def test_cli_effort_overrides(self):
        result = resolve_model_and_provider("watcher", cli_effort="high")
        assert result.effort == "high"

    def test_project_effort_config(self):
        data = {"project": {"model_config": {"session_effort": {"qa": "low"}}}}
        result = resolve_model_and_provider("qa", project_data=data)
        assert result.effort == "low"

    def test_cli_effort_beats_project(self):
        data = {"project": {"model_config": {"session_effort": {"qa": "low"}}}}
        result = resolve_model_and_provider("qa", cli_effort="high", project_data=data)
        assert result.effort == "high"

    @patch("pm_core.model_config.get_global_setting_value")
    def test_global_effort_setting(self, mock_gsv):
        # First call is for model-qa (returns ""), second for effort-qa
        mock_gsv.side_effect = lambda key: "low" if key == "effort-qa" else ""
        result = resolve_model_and_provider("qa")
        assert result.effort == "low"


class TestGetModelConfigSummary:
    def test_defaults(self):
        summary = get_model_config_summary()
        assert summary["review"] == QUALITY_TIERS["high"]
        assert summary["watcher"] == QUALITY_TIERS["low"]
        assert len(summary) == len(SESSION_TYPES)


class TestGetPrModelOverride:
    def test_present(self):
        assert get_pr_model_override({"model": "high"}) == "high"

    def test_absent(self):
        assert get_pr_model_override({}) is None


class TestBuildClaudeShellCmd:
    def test_model_flag_included(self):
        from pm_core.claude_launcher import build_claude_shell_cmd
        cmd = build_claude_shell_cmd(prompt="test", model="claude-sonnet-4-20250514")
        assert "--model" in cmd
        assert "claude-sonnet-4-20250514" in cmd

    def test_no_model_flag_when_none(self):
        from pm_core.claude_launcher import build_claude_shell_cmd
        cmd = build_claude_shell_cmd(prompt="test")
        assert "--model" not in cmd

    def test_effort_flag_included(self):
        from pm_core.claude_launcher import build_claude_shell_cmd
        cmd = build_claude_shell_cmd(prompt="test", effort="low")
        assert "--effort low" in cmd

    def test_no_effort_flag_when_none(self):
        from pm_core.claude_launcher import build_claude_shell_cmd
        cmd = build_claude_shell_cmd(prompt="test")
        assert "--effort" not in cmd

    def test_model_and_effort_together(self):
        from pm_core.claude_launcher import build_claude_shell_cmd
        cmd = build_claude_shell_cmd(prompt="test", model="claude-sonnet-4-20250514", effort="medium")
        assert "--model" in cmd
        assert "--effort medium" in cmd


class TestProviderResolution:
    def test_provider_prefix_returns_provider(self):
        result = resolve_model_and_provider("watcher", cli_model="provider:ollama")
        assert result.provider == "ollama"
        assert result.model is None

    def test_non_provider_returns_model(self):
        result = resolve_model_and_provider("review")
        assert result.model == QUALITY_TIERS["high"]
        assert result.provider is None

    def test_provider_in_project_config(self):
        data = {"project": {"model_config": {"session_models": {"watcher": "provider:ollama"}}}}
        result = resolve_model_and_provider("watcher", project_data=data)
        assert result.provider == "ollama"
        assert result.model is None

    def test_resolve_model_ignores_provider(self):
        assert resolve_model("watcher", cli_model="provider:ollama") is None

    def test_summary_shows_provider(self):
        data = {"project": {"model_config": {"session_models": {"watcher": "provider:ollama"}}}}
        summary = get_model_config_summary(data)
        assert summary["watcher"] == "provider:ollama"
        assert summary["review"] == QUALITY_TIERS["high"]

    @patch("pm_core.model_config.get_global_setting_value", return_value="provider:vllm")
    def test_global_setting_provider(self, mock_gsv):
        result = resolve_model_and_provider("qa")
        assert result.provider == "vllm"
        assert result.model is None
