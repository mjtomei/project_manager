"""Tests for pm_core.claude_launcher — claude CLI launching helpers.

Note: load_session, save_session, clear_session, _parse_session_id are
      tested in test_session_registry.py.
"""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

from pm_core.claude_launcher import (
    find_claude,
    find_editor,
    build_claude_shell_cmd,
    load_session,
    save_session,
    launch_claude,
    launch_claude_print,
    launch_claude_print_background,
    launch_claude_in_tmux,
    launch_bridge_in_tmux,
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


# ---------------------------------------------------------------------------
# launch_claude
# ---------------------------------------------------------------------------

class TestLaunchClaude:
    @patch("pm_core.claude_launcher.find_claude", return_value=None)
    def test_raises_when_no_claude(self, mock_fc, tmp_path):
        import pytest
        with pytest.raises(FileNotFoundError, match="claude CLI not found"):
            launch_claude("hello", "key", tmp_path)

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.claude_launcher.subprocess.run")
    @patch("pm_core.claude_launcher._skip_permissions", return_value=False)
    @patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude")
    def test_new_session(self, mock_fc, mock_sp, mock_run, mock_log, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        rc = launch_claude("hello", "key1", tmp_path, resume=True)
        assert rc == 0
        # Session should be saved
        assert load_session(tmp_path, "key1") is not None
        cmd = mock_run.call_args[0][0]
        assert "--session-id" in cmd

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.claude_launcher.subprocess.run")
    @patch("pm_core.claude_launcher._skip_permissions", return_value=False)
    @patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude")
    def test_resume_existing_session(self, mock_fc, mock_sp, mock_run, mock_log, tmp_path):
        save_session(tmp_path, "key1", "existing-session-id")
        mock_run.return_value = MagicMock(returncode=0)
        rc = launch_claude("hello", "key1", tmp_path, resume=True)
        assert rc == 0
        cmd = mock_run.call_args[0][0]
        assert "--resume" in cmd
        assert "existing-session-id" in cmd

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.claude_launcher.subprocess.run")
    @patch("pm_core.claude_launcher._skip_permissions", return_value=False)
    @patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude")
    def test_retry_on_failure(self, mock_fc, mock_sp, mock_run, mock_log, tmp_path):
        """When first run fails with resume, retries with fresh session."""
        save_session(tmp_path, "key1", "old-session")
        mock_run.side_effect = [
            MagicMock(returncode=1),  # First attempt fails
            MagicMock(returncode=0),  # Retry succeeds
        ]
        rc = launch_claude("hello", "key1", tmp_path, resume=True)
        assert rc == 0
        assert mock_run.call_count == 2
        # Second call should use --session-id (not --resume)
        retry_cmd = mock_run.call_args_list[1][0][0]
        assert "--session-id" in retry_cmd

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.claude_launcher.subprocess.run")
    @patch("pm_core.claude_launcher._skip_permissions", return_value=True)
    @patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude")
    def test_skip_permissions_flag(self, mock_fc, mock_sp, mock_run, mock_log, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        launch_claude("hello", "key1", tmp_path, resume=False)
        cmd = mock_run.call_args[0][0]
        assert "--dangerously-skip-permissions" in cmd

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.claude_launcher.subprocess.run")
    @patch("pm_core.claude_launcher._skip_permissions", return_value=False)
    @patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude")
    def test_no_resume(self, mock_fc, mock_sp, mock_run, mock_log, tmp_path):
        """resume=False skips retry logic on failure."""
        mock_run.return_value = MagicMock(returncode=1)
        rc = launch_claude("hello", "key1", tmp_path, resume=False)
        assert rc == 1
        # Should only run once (no retry)
        assert mock_run.call_count == 1


# ---------------------------------------------------------------------------
# launch_claude_print
# ---------------------------------------------------------------------------

class TestLaunchClaudePrint:
    @patch("pm_core.claude_launcher.find_claude", return_value=None)
    def test_raises_when_no_claude(self, mock_fc):
        import pytest
        with pytest.raises(FileNotFoundError, match="claude CLI not found"):
            launch_claude_print("hello")

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.claude_launcher.subprocess.run")
    @patch("pm_core.claude_launcher._skip_permissions", return_value=False)
    @patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude")
    def test_returns_stdout(self, mock_fc, mock_sp, mock_run, mock_log):
        mock_run.return_value = MagicMock(returncode=0, stdout="result text")
        result = launch_claude_print("hello")
        assert result == "result text"

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.claude_launcher.subprocess.run")
    @patch("pm_core.claude_launcher._skip_permissions", return_value=True)
    @patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude")
    def test_skip_permissions(self, mock_fc, mock_sp, mock_run, mock_log):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok")
        launch_claude_print("hello")
        cmd = mock_run.call_args[0][0]
        assert "--dangerously-skip-permissions" in cmd

    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.claude_launcher.subprocess.run")
    @patch("pm_core.claude_launcher._skip_permissions", return_value=False)
    @patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude")
    def test_nonzero_returncode_logged(self, mock_fc, mock_sp, mock_run, mock_log):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        launch_claude_print("hello")
        # log_shell_command called twice: once for the command, once for the failure
        assert mock_log.call_count == 2


# ---------------------------------------------------------------------------
# launch_bridge_in_tmux
# ---------------------------------------------------------------------------

class TestLaunchBridgeInTmux:
    @patch("pm_core.tmux.split_pane_background")
    def test_returns_socket_path(self, mock_split):
        result = launch_bridge_in_tmux(None, "/tmp/proj", "main-session")
        assert result.startswith("/tmp/pm-bridge-")
        assert result.endswith(".sock")
        mock_split.assert_called_once()

    @patch("pm_core.tmux.split_pane_background")
    def test_includes_prompt(self, mock_split):
        launch_bridge_in_tmux("my prompt", "/tmp/proj", "sess")
        cmd = mock_split.call_args[0][2]
        assert "--prompt" in cmd
        assert "my prompt" in cmd

    @patch("pm_core.tmux.split_pane_background")
    def test_escapes_quotes_in_prompt(self, mock_split):
        launch_bridge_in_tmux("it's a test", "/tmp/proj", "sess")
        cmd = mock_split.call_args[0][2]
        assert "it'\\''s a test" in cmd

    @patch("pm_core.tmux.split_pane_background")
    def test_no_prompt(self, mock_split):
        launch_bridge_in_tmux(None, "/tmp/proj", "sess")
        cmd = mock_split.call_args[0][2]
        assert "--prompt" not in cmd


# ---------------------------------------------------------------------------
# launch_claude_print_background — additional coverage
# ---------------------------------------------------------------------------

class TestLaunchClaudePrintBackgroundExtra:
    @patch("pm_core.claude_launcher._skip_permissions", return_value=True)
    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.claude_launcher.subprocess.run")
    @patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude")
    def test_skip_permissions_flag(self, mock_fc, mock_run, mock_log, mock_sp):
        """Line 301: _skip_permissions adds --dangerously-skip-permissions."""
        import threading
        mock_run.return_value = MagicMock(stdout="out", stderr="", returncode=0)
        event = threading.Event()
        results = {}

        def cb(stdout, stderr, rc):
            results["cmd"] = mock_run.call_args[0][0]
            results["rc"] = rc
            event.set()

        launch_claude_print_background("test", callback=cb)
        event.wait(timeout=2)
        assert "--dangerously-skip-permissions" in results["cmd"]

    @patch("pm_core.claude_launcher._skip_permissions", return_value=False)
    @patch("pm_core.claude_launcher.log_shell_command")
    @patch("pm_core.claude_launcher.subprocess.run")
    @patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude")
    def test_nonzero_returncode(self, mock_fc, mock_run, mock_log, mock_sp):
        """Line 311: non-zero returncode is logged."""
        import threading
        mock_run.return_value = MagicMock(stdout="", stderr="err", returncode=1)
        event = threading.Event()
        results = {}

        def cb(stdout, stderr, rc):
            results["rc"] = rc
            event.set()

        launch_claude_print_background("test", callback=cb)
        event.wait(timeout=2)
        assert results["rc"] == 1
        # log_shell_command called twice (once for cmd, once for failure)
        assert mock_log.call_count == 2
