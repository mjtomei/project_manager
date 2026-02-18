"""Tests for pm_core.claude_launcher — claude CLI launching and session management."""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

from pm_core.claude_launcher import (
    find_claude,
    find_editor,
    build_claude_shell_cmd,
    load_session,
    save_session,
    clear_session,
    _registry_path,
    _skip_permissions,
    _parse_session_id,
    launch_claude_print_background,
    launch_claude_in_tmux,
)


# ---------------------------------------------------------------------------
# find_claude
# ---------------------------------------------------------------------------

class TestFindClaude:
    @patch("shutil.which", return_value="/usr/local/bin/claude")
    def test_found(self, mock_which):
        assert find_claude() == "/usr/local/bin/claude"

    @patch("shutil.which", return_value=None)
    def test_not_found(self, mock_which):
        assert find_claude() is None


# ---------------------------------------------------------------------------
# find_editor
# ---------------------------------------------------------------------------

class TestFindEditor:
    def test_respects_editor_env(self):
        with patch.dict(os.environ, {"EDITOR": "emacs"}):
            assert find_editor() == "emacs"

    @patch("shutil.which")
    def test_tries_vim_first(self, mock_which):
        env = os.environ.copy()
        env.pop("EDITOR", None)
        mock_which.side_effect = lambda x: f"/usr/bin/{x}" if x == "vim" else None
        with patch.dict(os.environ, env, clear=True):
            assert find_editor() == "vim"

    @patch("shutil.which")
    def test_tries_vi_second(self, mock_which):
        env = os.environ.copy()
        env.pop("EDITOR", None)
        mock_which.side_effect = lambda x: "/usr/bin/vi" if x == "vi" else None
        with patch.dict(os.environ, env, clear=True):
            assert find_editor() == "vi"

    @patch("shutil.which")
    def test_tries_nano_third(self, mock_which):
        env = os.environ.copy()
        env.pop("EDITOR", None)
        mock_which.side_effect = lambda x: "/usr/bin/nano" if x == "nano" else None
        with patch.dict(os.environ, env, clear=True):
            assert find_editor() == "nano"

    @patch("shutil.which", return_value=None)
    def test_defaults_to_vi(self, mock_which):
        env = os.environ.copy()
        env.pop("EDITOR", None)
        with patch.dict(os.environ, env, clear=True):
            assert find_editor() == "vi"


# ---------------------------------------------------------------------------
# build_claude_shell_cmd
# ---------------------------------------------------------------------------

class TestBuildClaudeShellCmd:
    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    def test_basic_prompt(self, mock_sp, mock_log):
        result = build_claude_shell_cmd(prompt="hello world")
        assert result == "claude 'hello world'"

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=True)
    def test_skip_permissions(self, mock_sp, mock_log):
        result = build_claude_shell_cmd(prompt="test")
        assert "--dangerously-skip-permissions" in result

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    def test_session_id(self, mock_sp, mock_log):
        result = build_claude_shell_cmd(prompt="test", session_id="abc-123")
        assert "--session-id abc-123" in result

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    def test_resume(self, mock_sp, mock_log):
        result = build_claude_shell_cmd(session_id="abc-123", resume=True)
        assert "--resume abc-123" in result
        # Prompt should not be included when resuming
        assert "'" not in result

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    def test_escapes_quotes(self, mock_sp, mock_log):
        result = build_claude_shell_cmd(prompt="it's a test")
        assert "it'\\''s a test" in result

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    def test_no_prompt_no_session(self, mock_sp, mock_log):
        result = build_claude_shell_cmd()
        assert result == "claude"

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    def test_resume_with_prompt_ignores_prompt(self, mock_sp, mock_log):
        result = build_claude_shell_cmd(prompt="test", session_id="abc", resume=True)
        assert "--resume abc" in result
        assert "'test'" not in result


# ---------------------------------------------------------------------------
# Session round-trip (load / save / clear)
# ---------------------------------------------------------------------------

class TestSessionRoundTrip:
    def test_save_load_clear(self, tmp_path):
        save_session(tmp_path, "key1", "session-abc")
        assert load_session(tmp_path, "key1") == "session-abc"
        clear_session(tmp_path, "key1")
        assert load_session(tmp_path, "key1") is None

    def test_multiple_keys(self, tmp_path):
        save_session(tmp_path, "a", "s1")
        save_session(tmp_path, "b", "s2")
        assert load_session(tmp_path, "a") == "s1"
        assert load_session(tmp_path, "b") == "s2"

    def test_overwrite(self, tmp_path):
        save_session(tmp_path, "k", "old")
        save_session(tmp_path, "k", "new")
        assert load_session(tmp_path, "k") == "new"

    def test_load_missing_file(self, tmp_path):
        assert load_session(tmp_path, "x") is None

    def test_clear_missing_key(self, tmp_path):
        save_session(tmp_path, "a", "s1")
        clear_session(tmp_path, "nonexistent")
        assert load_session(tmp_path, "a") == "s1"


# ---------------------------------------------------------------------------
# _registry_path
# ---------------------------------------------------------------------------

class TestRegistryPath:
    def test_returns_path(self, tmp_path):
        result = _registry_path(tmp_path)
        assert result == tmp_path / ".pm-sessions.json"


# ---------------------------------------------------------------------------
# _skip_permissions
# ---------------------------------------------------------------------------

class TestSkipPermissions:
    @patch("pm_core.paths.skip_permissions_enabled", return_value=True)
    def test_enabled(self, mock_sp):
        assert _skip_permissions() is True

    @patch("pm_core.paths.skip_permissions_enabled", return_value=False)
    def test_disabled(self, mock_sp):
        assert _skip_permissions() is False


# ---------------------------------------------------------------------------
# launch_claude_print_background
# ---------------------------------------------------------------------------

class TestLaunchClaudePrintBackground:
    @patch("pm_core.claude_launcher.find_claude", return_value=None)
    def test_no_claude_calls_callback(self, mock_fc):
        import threading
        results = {}
        event = threading.Event()

        def cb(stdout, stderr, rc):
            results["stdout"] = stdout
            results["stderr"] = stderr
            results["rc"] = rc
            event.set()

        launch_claude_print_background("test", callback=cb)
        event.wait(timeout=2)
        assert results["rc"] == 1
        assert "not found" in results["stderr"]

    @patch("pm_core.claude_launcher._skip_permissions", return_value=False)
    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.claude_launcher.subprocess.run")
    @patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude")
    def test_runs_claude(self, mock_fc, mock_run, mock_log, mock_sp):
        import threading
        mock_run.return_value = MagicMock(
            stdout="output", stderr="", returncode=0
        )
        results = {}
        event = threading.Event()

        def cb(stdout, stderr, rc):
            results["stdout"] = stdout
            results["rc"] = rc
            event.set()

        launch_claude_print_background("test", callback=cb)
        event.wait(timeout=2)
        assert results["stdout"] == "output"
        assert results["rc"] == 0


# ---------------------------------------------------------------------------
# launch_claude_in_tmux
# ---------------------------------------------------------------------------

class TestLaunchClaudeInTmux:
    @patch("pm_core.claude_launcher.build_claude_shell_cmd", return_value="claude 'hello'")
    @patch("pm_core.tmux.send_keys")
    def test_sends_command(self, mock_sk, mock_build):
        launch_claude_in_tmux("%1", "hello")
        mock_sk.assert_called_once_with("%1", "claude 'hello'")

    @patch("pm_core.claude_launcher.build_claude_shell_cmd", return_value="claude 'hello'")
    @patch("pm_core.tmux.send_keys")
    def test_with_cwd(self, mock_sk, mock_build):
        launch_claude_in_tmux("%1", "hello", cwd="/tmp/proj")
        cmd = mock_sk.call_args[0][1]
        assert cmd.startswith("cd '/tmp/proj' && ")
