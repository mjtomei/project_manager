"""Tests for provider integration in claude_launcher functions."""

from unittest.mock import patch

from pm_core.claude_launcher import build_claude_shell_cmd
from pm_core.providers import ProviderConfig


CANARY = "canary-84ebabf-do-not-use"


def _build(provider, **kwargs):
    """Build a command and return (cmd, env) with env_out wired up."""
    env: dict[str, str] = {}
    cmd = build_claude_shell_cmd(provider=provider, env_out=env, **kwargs)
    return cmd, env


class TestBuildClaudeShellCmdProvider:
    """Test provider parameter in build_claude_shell_cmd."""

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    @patch("pm_core.providers.get_provider")
    def test_default_provider_no_change(self, mock_gp, mock_sp, mock_log):
        """Default claude provider produces the same command as before."""
        mock_gp.return_value = ProviderConfig(name="claude")
        env: dict[str, str] = {}
        result = build_claude_shell_cmd(prompt="hello", env_out=env)
        # Only inherited classifier and subagent pins are dropped (main
        # account, no model selected): names only, no values.
        assert result == ("env -u ANTHROPIC_DEFAULT_OPUS_MODEL "
                          "-u ANTHROPIC_DEFAULT_SONNET_MODEL "
                          "-u ANTHROPIC_DEFAULT_HAIKU_MODEL "
                          "-u ANTHROPIC_DEFAULT_FABLE_MODEL "
                          "-u ANTHROPIC_SMALL_FAST_MODEL -u CLAUDE_CODE_SUBAGENT_MODEL "
                          "-u CLAUDE_CODE_SUBAGENT_MODEL_FORCE "
                          "-u CLAUDE_CODE_AUTO_MODE_MODEL -u PM_ROUTE_BASE_URL claude 'hello'")
        assert env == {}

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    @patch("pm_core.providers.get_provider")
    def test_openai_provider_env_not_in_command(self, mock_gp, mock_sp, mock_log):
        """OpenAI provider values travel via env_out, never in the command."""
        mock_gp.return_value = ProviderConfig(
            name="ollama", type="openai",
            api_base="http://localhost:11434/v1",
            api_key=CANARY,
            model="llama3.1:70b",
        )
        result, env = _build("ollama", prompt="hello")
        assert CANARY not in result
        assert "OPENAI_API_KEY=" not in result
        assert "OPENAI_BASE_URL=" not in result
        assert env["OPENAI_API_KEY"] == CANARY
        assert env["OPENAI_BASE_URL"] == "http://localhost:11434/v1"
        assert "--model openai:llama3.1:70b" in result
        assert "'hello'" in result

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=True)
    @patch("pm_core.providers.get_provider")
    def test_provider_with_skip_permissions(self, mock_gp, mock_sp, mock_log):
        """Provider env stays out of the command with skip-permissions."""
        mock_gp.return_value = ProviderConfig(
            name="ollama", type="openai",
            api_base="http://localhost:11434/v1",
            model="llama3.1",
        )
        result, env = _build("ollama", prompt="test")
        assert "--dangerously-skip-permissions" in result
        assert "--model openai:llama3.1" in result
        assert env["OPENAI_BASE_URL"] == "http://localhost:11434/v1"

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
        result, env = _build("vllm", prompt="test", session_id="abc-123")
        assert "--session-id abc-123" in result
        assert "--model openai:codellama" in result
        assert env["OPENAI_BASE_URL"] == "http://localhost:8000/v1"

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    @patch("pm_core.providers.get_provider")
    def test_claude_provider_with_model(self, mock_gp, mock_sp, mock_log):
        """Claude provider with explicit model sets --model and env."""
        mock_gp.return_value = ProviderConfig(
            name="fast", type="claude", model="claude-haiku-4-5-20251001"
        )
        result, env = _build("fast", prompt="test")
        assert "--model claude-haiku-4-5-20251001" in result
        assert "ANTHROPIC_MODEL=" not in result
        assert env["ANTHROPIC_MODEL"] == "claude-haiku-4-5-20251001"

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
        result, env = _build("ollama", prompt="test")
        assert "ANTHROPIC_BASE_URL=" not in result
        assert "http://localhost:11434" not in result
        assert "--model qwen3.5" in result
        # Should NOT have openai prefix
        assert "openai:" not in result
        assert env["ANTHROPIC_BASE_URL"] == "http://localhost:11434"
        assert env["ANTHROPIC_API_KEY"] == ""
        assert env["ANTHROPIC_AUTH_TOKEN"] == "ollama"

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    @patch("pm_core.providers.get_provider")
    def test_provider_no_model_no_flag(self, mock_gp, mock_sp, mock_log):
        """Provider with no model doesn't add --model flag."""
        mock_gp.return_value = ProviderConfig(
            name="vllm", type="openai",
            api_base="http://localhost:8000/v1",
        )
        result, env = _build("vllm", prompt="test")
        assert "--model" not in result
        assert "OPENAI_BASE_URL=" not in result
        assert env["OPENAI_BASE_URL"] == "http://localhost:8000/v1"

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    @patch("pm_core.providers.get_provider")
    def test_claude_api_key_canary_not_in_command(self, mock_gp, mock_sp, mock_log):
        """The reported bug: a claude-type api_key never enters the command."""
        mock_gp.return_value = ProviderConfig(
            name="mainstub", type="claude", api_key=CANARY,
        )
        result, env = _build("mainstub", prompt="test")
        assert CANARY not in result
        assert "ANTHROPIC_API_KEY=" not in result
        assert env["ANTHROPIC_API_KEY"] == CANARY

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    @patch("pm_core.providers.get_provider")
    def test_env_ref_api_key_resolved_into_env_not_command(
            self, mock_gp, mock_sp, mock_log, monkeypatch):
        """A ${VAR} api_key is resolved for the env but not for the command."""
        monkeypatch.setenv("CANARY_PROVIDER_KEY", CANARY)
        mock_gp.return_value = ProviderConfig(
            name="mainstub", type="claude", api_key="${CANARY_PROVIDER_KEY}",
        )
        result, env = _build("mainstub", prompt="test")
        assert CANARY not in result
        assert "${CANARY_PROVIDER_KEY}" not in result
        assert env["ANTHROPIC_API_KEY"] == CANARY

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    @patch("pm_core.providers.get_provider")
    def test_logged_command_has_no_provider_secret(
            self, mock_gp, mock_sp, mock_log):
        """log_shell_command must never receive the provider secret."""
        mock_gp.return_value = ProviderConfig(
            name="mainstub", type="claude", api_key=CANARY,
        )
        _build("mainstub", prompt="test")
        logged = " ".join(str(c) for c in mock_log.call_args_list)
        assert CANARY not in logged
        assert "ANTHROPIC_API_KEY=" not in logged

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    @patch("pm_core.providers.get_provider")
    def test_warns_when_provider_env_is_not_forwarded(
            self, mock_gp, mock_sp, mock_log):
        """A caller that forgets env_out is loud, not silently unauthenticated."""
        mock_gp.return_value = ProviderConfig(
            name="mainstub", type="claude", api_key=CANARY,
        )
        with patch("pm_core.claude_launcher._log.warning") as warn:
            build_claude_shell_cmd(prompt="test", provider="mainstub")
        assert warn.called
        msg = " ".join(str(a) for c in warn.call_args_list for a in c.args)
        assert "env_out" in msg
        assert CANARY not in msg
