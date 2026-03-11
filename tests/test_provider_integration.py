"""Tests for provider integration in claude_launcher functions."""

import os
from unittest.mock import patch, MagicMock

from pm_core.claude_launcher import build_claude_shell_cmd
from pm_core.providers import ProviderConfig


class TestBuildClaudeShellCmdProvider:
    """Test provider parameter in build_claude_shell_cmd."""

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    @patch("pm_core.providers.get_provider")
    def test_default_provider_no_change(self, mock_gp, mock_sp, mock_log):
        """Default claude provider produces the same command as before."""
        mock_gp.return_value = ProviderConfig(name="claude")
        result = build_claude_shell_cmd(prompt="hello")
        assert result == "claude 'hello'"

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    @patch("pm_core.providers.get_provider")
    def test_openai_provider_adds_env_and_model(self, mock_gp, mock_sp, mock_log):
        """OpenAI provider adds env vars prefix and --model flag."""
        mock_gp.return_value = ProviderConfig(
            name="ollama", type="openai",
            api_base="http://localhost:11434/v1",
            api_key="ollama",
            model="llama3.1:70b",
        )
        result = build_claude_shell_cmd(prompt="hello", provider="ollama")
        assert "OPENAI_BASE_URL=" in result
        assert "http://localhost:11434/v1" in result
        assert "OPENAI_API_KEY=" in result
        assert "--model openai:llama3.1:70b" in result
        assert "'hello'" in result

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=True)
    @patch("pm_core.providers.get_provider")
    def test_provider_with_skip_permissions(self, mock_gp, mock_sp, mock_log):
        """Provider env vars come before claude command with skip-permissions."""
        mock_gp.return_value = ProviderConfig(
            name="ollama", type="openai",
            api_base="http://localhost:11434/v1",
            model="llama3.1",
        )
        result = build_claude_shell_cmd(prompt="test", provider="ollama")
        assert "--dangerously-skip-permissions" in result
        assert "--model openai:llama3.1" in result
        # Env prefix should come before claude
        claude_pos = result.index("claude")
        openai_pos = result.index("OPENAI_BASE_URL")
        assert openai_pos < claude_pos

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    @patch("pm_core.providers.get_provider")
    def test_provider_with_session_id(self, mock_gp, mock_sp, mock_log):
        """Provider works with session_id."""
        mock_gp.return_value = ProviderConfig(
            name="vllm", type="openai",
            api_base="http://localhost:8000/v1",
            model="codellama",
        )
        result = build_claude_shell_cmd(
            prompt="test", session_id="abc-123", provider="vllm"
        )
        assert "--session-id abc-123" in result
        assert "--model openai:codellama" in result

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    @patch("pm_core.providers.get_provider")
    def test_claude_provider_with_model(self, mock_gp, mock_sp, mock_log):
        """Claude provider with explicit model sets --model without prefix."""
        mock_gp.return_value = ProviderConfig(
            name="fast", type="claude", model="claude-haiku-4-5-20251001"
        )
        result = build_claude_shell_cmd(prompt="test", provider="fast")
        assert "--model claude-haiku-4-5-20251001" in result
        # ANTHROPIC_MODEL env var is also set for claude-type providers
        assert "ANTHROPIC_MODEL=claude-haiku-4-5-20251001" in result

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    @patch("pm_core.providers.get_provider")
    def test_provider_no_model_no_flag(self, mock_gp, mock_sp, mock_log):
        """Provider with no model doesn't add --model flag."""
        mock_gp.return_value = ProviderConfig(
            name="local", type="openai",
            api_base="http://localhost:8000/v1",
        )
        result = build_claude_shell_cmd(prompt="test", provider="local")
        assert "--model" not in result
        assert "OPENAI_BASE_URL=" in result
