"""Tests for pm_core.model_config — per-session model targeting."""

import pytest
from unittest.mock import patch

from pm_core.model_config import (
    resolve_model,
    resolve_model_and_provider,
    ModelResolution,
    get_model_config_summary,
    get_pr_model_override,
    SESSION_TYPES,
)


class TestPassthrough:
    def test_bare_names_passed_through(self):
        """Bare model names like sonnet, opus are passed through as-is."""
        with patch.dict("os.environ", {"PM_MODEL": "sonnet"}):
            assert resolve_model("review") == "sonnet"
        with patch.dict("os.environ", {"PM_MODEL": "opus"}):
            assert resolve_model("review") == "opus"

    def test_full_model_id_passed_through(self):
        """Full model IDs are passed through as-is."""
        with patch.dict("os.environ", {"PM_MODEL": "claude-custom-model"}):
            result = resolve_model("review")
            assert result == "claude-custom-model"


class TestResolveModel:
    def test_defaults_are_none(self):
        """With no config, all session types return None (use CLI default)."""
        assert resolve_model("review") is None
        assert resolve_model("impl") is None
        assert resolve_model("qa") is None
        assert resolve_model("watcher") is None
        assert resolve_model("merge") is None

    def test_pr_override(self):
        assert resolve_model("impl", pr_model="opus") == "opus"

    def test_project_config(self):
        data = {"project": {"model_config": {"session_models": {"review": "sonnet"}}}}
        assert resolve_model("review", project_data=data) == "sonnet"

    def test_pr_beats_project(self):
        data = {"project": {"model_config": {"session_models": {"review": "haiku"}}}}
        assert resolve_model("review", pr_model="sonnet", project_data=data) == "sonnet"

    @patch("pm_core.model_config.get_global_setting_value", return_value="opus")
    def test_global_setting(self, mock_gsv):
        result = resolve_model("qa")
        assert result == "opus"

    @patch("pm_core.model_config.get_global_setting_value", return_value="opus")
    def test_project_beats_global(self, mock_gsv):
        data = {"project": {"model_config": {"session_models": {"qa": "haiku"}}}}
        assert resolve_model("qa", project_data=data) == "haiku"

    def test_unknown_session_type(self):
        assert resolve_model("unknown-type") is None


class TestEffortResolution:
    def test_defaults_are_none(self):
        """With no config, effort is None (use CLI default)."""
        result = resolve_model_and_provider("review")
        assert result.effort is None
        result = resolve_model_and_provider("qa")
        assert result.effort is None
        result = resolve_model_and_provider("impl")
        assert result.effort is None

    def test_watcher_no_effort_by_default(self):
        """Watcher has no default effort."""
        result = resolve_model_and_provider("watcher")
        assert result.effort is None

    def test_haiku_suppresses_effort(self):
        """Even if effort is configured, it's suppressed for haiku."""
        with patch.dict("os.environ", {"PM_MODEL": "haiku", "PM_EFFORT": "high"}):
            result = resolve_model_and_provider("watcher")
            assert result.effort is None

    def test_haiku_explicit_suppresses_effort(self):
        """Setting model to haiku via env var suppresses effort."""
        with patch.dict("os.environ", {"PM_MODEL": "haiku", "PM_EFFORT": "high"}):
            result = resolve_model_and_provider("qa")
            assert result.effort is None

    def test_sonnet_keeps_effort(self):
        """Sonnet supports effort levels."""
        with patch.dict("os.environ", {"PM_MODEL": "sonnet", "PM_EFFORT": "low"}):
            result = resolve_model_and_provider("qa")
            assert result.effort == "low"

    def test_opus_keeps_effort(self):
        """Opus supports effort levels."""
        with patch.dict("os.environ", {"PM_EFFORT": "medium"}):
            result = resolve_model_and_provider("review")
            assert result.effort == "medium"

    def test_project_effort_config(self):
        data = {"project": {"model_config": {"session_effort": {"qa": "low"}}}}
        result = resolve_model_and_provider("qa", project_data=data)
        assert result.effort == "low"

    @patch("pm_core.model_config.get_global_setting_value")
    def test_global_effort_setting(self, mock_gsv):
        mock_gsv.side_effect = lambda key: "low" if key == "effort-qa" else ""
        result = resolve_model_and_provider("qa")
        assert result.effort == "low"


class TestEnvVarOverrides:
    def test_pm_model_env_var(self):
        with patch.dict("os.environ", {"PM_MODEL": "haiku"}):
            result = resolve_model("qa")
            assert result == "haiku"

    def test_pm_model_with_shortcut(self):
        with patch.dict("os.environ", {"PM_MODEL": "sonnet"}):
            result = resolve_model("review")
            assert result == "sonnet"

    def test_pm_model_beats_project(self):
        data = {"project": {"model_config": {"session_models": {"qa": "opus"}}}}
        with patch.dict("os.environ", {"PM_MODEL": "haiku"}):
            result = resolve_model("qa", project_data=data)
            assert result == "haiku"

    def test_pm_effort_env_var(self):
        with patch.dict("os.environ", {"PM_EFFORT": "low"}):
            result = resolve_model_and_provider("review")
            assert result.effort == "low"

    def test_pm_effort_beats_project(self):
        data = {"project": {"model_config": {"session_effort": {"qa": "low"}}}}
        with patch.dict("os.environ", {"PM_EFFORT": "high"}):
            result = resolve_model_and_provider("qa", project_data=data)
            assert result.effort == "high"

    def test_pm_model_provider_prefix(self):
        with patch.dict("os.environ", {"PM_MODEL": "provider:ollama"}):
            result = resolve_model_and_provider("qa")
            assert result.provider == "ollama"
            assert result.model is None


class TestGetModelConfigSummary:
    def test_no_config_shows_default(self):
        summary = get_model_config_summary()
        assert summary["review"] == "(default)"
        assert summary["watcher"] == "(default)"
        assert len(summary) == len(SESSION_TYPES)


class TestGetPrModelOverride:
    def test_present(self):
        assert get_pr_model_override({"model": "opus"}) == "opus"

    def test_absent(self):
        assert get_pr_model_override({}) is None


class TestBuildClaudeShellCmd:
    def test_model_flag_included(self):
        from pm_core.claude_launcher import build_claude_shell_cmd
        cmd = build_claude_shell_cmd(prompt="test", model="sonnet")
        assert "--model" in cmd
        assert "sonnet" in cmd

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
        cmd = build_claude_shell_cmd(prompt="test", model="sonnet", effort="medium")
        assert "--model" in cmd
        assert "--effort medium" in cmd


class TestProviderResolution:
    def test_provider_prefix_via_env(self):
        with patch.dict("os.environ", {"PM_MODEL": "provider:ollama"}):
            result = resolve_model_and_provider("watcher")
            assert result.provider == "ollama"
            assert result.model is None

    def test_non_provider_returns_model(self):
        """With explicit config, non-provider values resolve to model string."""
        result = resolve_model_and_provider("review", pr_model="opus")
        assert result.model == "opus"
        assert result.provider is None

    def test_provider_in_project_config(self):
        data = {"project": {"model_config": {"session_models": {"watcher": "provider:ollama"}}}}
        result = resolve_model_and_provider("watcher", project_data=data)
        assert result.provider == "ollama"
        assert result.model is None

    def test_resolve_model_ignores_provider(self):
        with patch.dict("os.environ", {"PM_MODEL": "provider:ollama"}):
            assert resolve_model("watcher") is None

    def test_summary_shows_provider(self):
        data = {"project": {"model_config": {"session_models": {"watcher": "provider:ollama"}}}}
        summary = get_model_config_summary(data)
        assert summary["watcher"] == "provider:ollama"
        assert summary["review"] == "(default)"

    @patch("pm_core.model_config.get_global_setting_value", return_value="provider:vllm")
    def test_global_setting_provider(self, mock_gsv):
        result = resolve_model_and_provider("qa")
        assert result.provider == "vllm"
        assert result.model is None


class TestQaSubtypeFallback:
    def test_qa_planning_falls_back_to_qa(self):
        data = {"project": {"model_config": {"session_models": {"qa": "sonnet"}}}}
        result = resolve_model("qa_planning", project_data=data)
        assert result == "sonnet"

    def test_qa_scenario_falls_back_to_qa(self):
        data = {"project": {"model_config": {"session_models": {"qa": "haiku"}}}}
        result = resolve_model("qa_scenario", project_data=data)
        assert result == "haiku"

    def test_specific_beats_fallback(self):
        data = {"project": {"model_config": {"session_models": {
            "qa": "haiku",
            "qa_planning": "opus",
        }}}}
        assert resolve_model("qa_planning", project_data=data) == "opus"
        assert resolve_model("qa_scenario", project_data=data) == "haiku"

    def test_effort_fallback(self):
        data = {"project": {"model_config": {"session_effort": {"qa": "low"}}}}
        result = resolve_model_and_provider("qa_planning", project_data=data)
        assert result.effort == "low"

    def test_effort_specific_beats_fallback(self):
        data = {"project": {"model_config": {"session_effort": {
            "qa": "low",
            "qa_planning": "high",
        }}}}
        result = resolve_model_and_provider("qa_planning", project_data=data)
        assert result.effort == "high"
        result = resolve_model_and_provider("qa_scenario", project_data=data)
        assert result.effort == "low"
