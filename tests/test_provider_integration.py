"""Tests for provider integration in claude_launcher functions."""

import os
import urllib.request
import urllib.error
from unittest.mock import patch, MagicMock

import pytest

from pm_core.claude_launcher import build_claude_shell_cmd
from pm_core.providers import ProviderConfig, check_provider


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
    def test_local_provider_anthropic_env(self, mock_gp, mock_sp, mock_log):
        """Local provider uses ANTHROPIC_BASE_URL and model directly."""
        mock_gp.return_value = ProviderConfig(
            name="ollama", type="local",
            api_base="http://localhost:11434",
            model="qwen3.5",
        )
        result = build_claude_shell_cmd(prompt="test", provider="ollama")
        assert "ANTHROPIC_BASE_URL=" in result
        assert "http://localhost:11434" in result
        assert "--model qwen3.5" in result
        # Should NOT have openai prefix
        assert "openai:" not in result

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    @patch("pm_core.providers.get_provider")
    def test_provider_no_model_no_flag(self, mock_gp, mock_sp, mock_log):
        """Provider with no model doesn't add --model flag."""
        mock_gp.return_value = ProviderConfig(
            name="vllm", type="openai",
            api_base="http://localhost:8000/v1",
        )
        result = build_claude_shell_cmd(prompt="test", provider="vllm")
        assert "--model" not in result
        assert "OPENAI_BASE_URL=" in result


# ---------------------------------------------------------------------------
# Real endpoint integration tests (skipped when Ollama is not running)
# ---------------------------------------------------------------------------

def _ollama_available() -> bool:
    """Check if a local Ollama instance is reachable."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=2):
            return True
    except Exception:
        return False


def _ollama_has_model() -> str | None:
    """Return the first available Ollama model name, or None."""
    import json
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=2) as resp:
            body = json.loads(resp.read())
            models = body.get("models", [])
            if models:
                return models[0].get("name")
    except Exception:
        pass
    return None


skip_no_ollama = pytest.mark.skipif(
    not _ollama_available(),
    reason="Ollama not running on localhost:11434",
)


class TestRealOllamaIntegration:
    """Integration tests that exercise a real local Ollama endpoint.

    These tests are skipped in CI or environments without Ollama.
    """

    @skip_no_ollama
    def test_connectivity_check(self):
        """check_provider confirms Ollama is reachable."""
        p = ProviderConfig(
            name="ollama-test", type="local",
            api_base="http://localhost:11434",
        )
        result = check_provider(p, check_tools=False)
        assert result.reachable
        assert "HTTP 200" in result.reachable_detail

    @skip_no_ollama
    def test_tool_use_with_real_model(self):
        """check_provider tests tool use against a real model."""
        model = _ollama_has_model()
        if not model:
            pytest.skip("No models pulled in Ollama")

        p = ProviderConfig(
            name="ollama-test", type="local",
            api_base="http://localhost:11434",
            model=model,
        )
        result = check_provider(p, check_tools=True)
        assert result.reachable
        # Tool use may or may not work depending on the model,
        # but we should get a definitive True/False (not None)
        assert result.tool_use is not None
        assert result.inference_ok is True
