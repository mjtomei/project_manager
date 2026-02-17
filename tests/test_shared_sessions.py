"""Tests for multi-user shared session support.

Covers:
- pm_core/paths.py: shared socket paths, permissions, global settings
- pm_core/tmux.py: _tmux_cmd builder, socket_path propagation
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from pm_core import paths, tmux


# ---------------------------------------------------------------------------
# paths: shared_socket_path
# ---------------------------------------------------------------------------

class TestSharedSocketPath:
    def test_deterministic(self):
        """Same tag always gives the same path."""
        a = paths.shared_socket_path("my-project-abcd1234")
        b = paths.shared_socket_path("my-project-abcd1234")
        assert a == b

    def test_includes_session_tag(self):
        """Path contains the session tag for discoverability."""
        p = paths.shared_socket_path("my-project-abcd1234")
        assert "my-project-abcd1234" in str(p)

    def test_lives_in_shared_dir(self):
        """Socket lives under SHARED_SOCKET_DIR."""
        p = paths.shared_socket_path("tag")
        assert p.parent == paths.SHARED_SOCKET_DIR

    def test_different_tags_different_paths(self):
        """Different tags produce different paths."""
        a = paths.shared_socket_path("project-a")
        b = paths.shared_socket_path("project-b")
        assert a != b

    def test_prefix(self):
        """Socket name starts with pm- prefix."""
        p = paths.shared_socket_path("tag")
        assert p.name == "pm-tag"


# ---------------------------------------------------------------------------
# paths: ensure_shared_socket_dir
# ---------------------------------------------------------------------------

class TestEnsureSharedSocketDir:
    def test_creates_directory(self, tmp_path):
        """Creates the directory if it doesn't exist."""
        fake_dir = tmp_path / "pm-sessions"
        with patch.object(paths, "SHARED_SOCKET_DIR", fake_dir):
            paths.ensure_shared_socket_dir()
        assert fake_dir.is_dir()

    def test_sets_sticky_permissions(self, tmp_path):
        """Directory gets 1777 (sticky + world-writable) permissions."""
        fake_dir = tmp_path / "pm-sessions"
        with patch.object(paths, "SHARED_SOCKET_DIR", fake_dir):
            paths.ensure_shared_socket_dir()
        mode = fake_dir.stat().st_mode & 0o7777
        assert mode == 0o1777

    def test_fixes_permissions_on_existing_dir(self, tmp_path):
        """Corrects permissions if directory already exists with wrong mode."""
        fake_dir = tmp_path / "pm-sessions"
        fake_dir.mkdir(mode=0o755)
        with patch.object(paths, "SHARED_SOCKET_DIR", fake_dir):
            paths.ensure_shared_socket_dir()
        mode = fake_dir.stat().st_mode & 0o7777
        assert mode == 0o1777

    def test_idempotent(self, tmp_path):
        """Calling twice is fine."""
        fake_dir = tmp_path / "pm-sessions"
        with patch.object(paths, "SHARED_SOCKET_DIR", fake_dir):
            paths.ensure_shared_socket_dir()
            paths.ensure_shared_socket_dir()
        assert fake_dir.is_dir()


# ---------------------------------------------------------------------------
# paths: set_shared_socket_permissions
# ---------------------------------------------------------------------------

class TestSetSharedSocketPermissions:
    def test_global_mode_sets_777(self, tmp_path):
        """No group_name → world-accessible (777)."""
        sock = tmp_path / "test-socket"
        sock.touch()
        paths.set_shared_socket_permissions(sock, group_name=None)
        mode = sock.stat().st_mode & 0o777
        assert mode == 0o777

    def test_group_mode_sets_770(self, tmp_path):
        """Group name → group-accessible (770) with chown."""
        sock = tmp_path / "test-socket"
        sock.touch()
        mock_grp = MagicMock()
        mock_grp.gr_gid = 1234
        with patch("pm_core.paths.grp.getgrnam", return_value=mock_grp) as mock_getgrnam:
            with patch("pm_core.paths.os.chown") as mock_chown:
                paths.set_shared_socket_permissions(sock, group_name="devteam")
        mock_getgrnam.assert_called_once_with("devteam")
        mock_chown.assert_called_once_with(str(sock), -1, 1234)
        mode = sock.stat().st_mode & 0o777
        assert mode == 0o770

    def test_invalid_group_raises(self):
        """Non-existent group raises KeyError from grp.getgrnam."""
        sock = Path("/tmp/fake-socket")
        with pytest.raises(KeyError):
            paths.set_shared_socket_permissions(sock, group_name="nonexistent_group_xyz_999")


# ---------------------------------------------------------------------------
# paths: global settings
# ---------------------------------------------------------------------------

class TestGlobalSettings:
    def test_get_nonexistent_returns_false(self, tmp_path):
        """Missing setting file returns False."""
        with patch.object(paths, "pm_home", return_value=tmp_path):
            assert paths.get_global_setting("no-such-setting") is False

    def test_set_and_get(self, tmp_path):
        """set_global_setting(True) → get_global_setting returns True."""
        with patch.object(paths, "pm_home", return_value=tmp_path):
            paths.set_global_setting("test-setting", True)
            assert paths.get_global_setting("test-setting") is True

    def test_set_false_removes_file(self, tmp_path):
        """set_global_setting(False) removes the file."""
        with patch.object(paths, "pm_home", return_value=tmp_path):
            paths.set_global_setting("test-setting", True)
            assert paths.get_global_setting("test-setting") is True
            paths.set_global_setting("test-setting", False)
            assert paths.get_global_setting("test-setting") is False

    def test_set_false_when_not_exists(self, tmp_path):
        """set_global_setting(False) when file doesn't exist is a no-op."""
        with patch.object(paths, "pm_home", return_value=tmp_path):
            paths.set_global_setting("never-set", False)  # should not raise
            assert paths.get_global_setting("never-set") is False

    def test_file_with_wrong_content(self, tmp_path):
        """Setting file that doesn't contain 'true' returns False."""
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        (settings_dir / "bad-setting").write_text("false\n")
        with patch.object(paths, "pm_home", return_value=tmp_path):
            assert paths.get_global_setting("bad-setting") is False

    def test_multiple_settings_independent(self, tmp_path):
        """Different settings don't interfere with each other."""
        with patch.object(paths, "pm_home", return_value=tmp_path):
            paths.set_global_setting("setting-a", True)
            paths.set_global_setting("setting-b", False)
            assert paths.get_global_setting("setting-a") is True
            assert paths.get_global_setting("setting-b") is False


# ---------------------------------------------------------------------------
# paths: run_shell_logged
# ---------------------------------------------------------------------------

class TestRunShellLogged:
    def test_runs_command_and_returns_result(self):
        """Runs subprocess and returns CompletedProcess."""
        result = paths.run_shell_logged(["echo", "hello"], capture_output=True, text=True)
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_logs_command(self, tmp_path):
        """Logs the command to the command log file."""
        log_file = tmp_path / "test.log"
        with patch.object(paths, "command_log_file", return_value=log_file):
            paths.run_shell_logged(["echo", "test"], capture_output=True)
        log_content = log_file.read_text()
        assert "echo" in log_content

    def test_logs_failure(self, tmp_path):
        """Logs non-zero return codes."""
        log_file = tmp_path / "test.log"
        with patch.object(paths, "command_log_file", return_value=log_file):
            result = paths.run_shell_logged(["false"], prefix="test")
        assert result.returncode != 0
        log_content = log_file.read_text()
        assert "WARN" in log_content or "failed" in log_content


# ---------------------------------------------------------------------------
# tmux: _tmux_cmd builder
# ---------------------------------------------------------------------------

class TestTmuxCmd:
    def test_basic_command(self):
        """Without socket, builds plain tmux command."""
        cmd = tmux._tmux_cmd("has-session", "-t", "mysess")
        assert cmd == ["tmux", "has-session", "-t", "mysess"]

    def test_with_socket_path(self):
        """socket_path kwarg adds -S flag."""
        cmd = tmux._tmux_cmd("has-session", "-t", "mysess",
                             socket_path="/tmp/pm-sessions/pm-test")
        assert cmd == ["tmux", "-S", "/tmp/pm-sessions/pm-test",
                        "has-session", "-t", "mysess"]

    def test_env_var_fallback(self):
        """Falls back to PM_TMUX_SOCKET env var."""
        with patch.dict(os.environ, {"PM_TMUX_SOCKET": "/tmp/env-socket"}):
            cmd = tmux._tmux_cmd("list-sessions")
        assert cmd == ["tmux", "-S", "/tmp/env-socket", "list-sessions"]

    def test_explicit_socket_overrides_env(self):
        """Explicit socket_path takes precedence over env var."""
        with patch.dict(os.environ, {"PM_TMUX_SOCKET": "/tmp/env-socket"}):
            cmd = tmux._tmux_cmd("list-sessions",
                                 socket_path="/tmp/explicit-socket")
        assert cmd == ["tmux", "-S", "/tmp/explicit-socket", "list-sessions"]

    def test_no_socket_no_env(self):
        """Without socket_path or env var, no -S flag."""
        with patch.dict(os.environ, {}, clear=True):
            # Clear PM_TMUX_SOCKET specifically
            env = os.environ.copy()
            env.pop("PM_TMUX_SOCKET", None)
            with patch.dict(os.environ, env, clear=True):
                cmd = tmux._tmux_cmd("list-sessions")
        assert "-S" not in cmd
        assert cmd == ["tmux", "list-sessions"]

    def test_multiple_args(self):
        """Handles multiple arguments correctly."""
        cmd = tmux._tmux_cmd("new-session", "-d", "-s", "test", "-n", "main",
                             socket_path="/tmp/sock")
        assert cmd == ["tmux", "-S", "/tmp/sock",
                        "new-session", "-d", "-s", "test", "-n", "main"]


# ---------------------------------------------------------------------------
# tmux: socket_path propagation through wrapper functions
# ---------------------------------------------------------------------------

class TestSocketPathPropagation:
    """Verify that socket_path is forwarded to _tmux_cmd in key functions."""

    @patch("pm_core.tmux.subprocess.run")
    def test_session_exists_passes_socket(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        tmux.session_exists("test", socket_path="/tmp/sock")
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_create_session_passes_socket(self, mock_run):
        tmux.create_session("test", "/tmp", "bash", socket_path="/tmp/sock")
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_attach_passes_socket(self, mock_run):
        tmux.attach("test", socket_path="/tmp/sock")
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_kill_session_passes_socket(self, mock_run):
        tmux.kill_session("test", socket_path="/tmp/sock")
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_set_session_option_passes_socket(self, mock_run):
        tmux.set_session_option("test", "status", "off", socket_path="/tmp/sock")
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_set_environment_passes_socket(self, mock_run):
        tmux.set_environment("test", "KEY", "value", socket_path="/tmp/sock")
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_create_grouped_session_passes_socket(self, mock_run):
        tmux.create_grouped_session("base", "base~1", socket_path="/tmp/sock")
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_list_grouped_sessions_passes_socket(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="base~1\n")
        tmux.list_grouped_sessions("base", socket_path="/tmp/sock")
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_find_unattached_passes_socket(self, mock_run):
        """find_unattached_grouped_session forwards socket to both list and display calls."""
        # First call: list_grouped_sessions returns one session
        # Second call: display-message checks if attached
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="base~1\n"),  # list-sessions
            MagicMock(returncode=0, stdout="0\n"),  # display-message (not attached)
        ]
        result = tmux.find_unattached_grouped_session("base", socket_path="/tmp/sock")
        assert result == "base~1"
        # Both calls should use the socket
        for c in mock_run.call_args_list:
            cmd = c[0][0]
            assert "-S" in cmd
            assert "/tmp/sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_next_grouped_session_name_passes_socket(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="base~1\nbase~2\n")
        name = tmux.next_grouped_session_name("base", socket_path="/tmp/sock")
        assert name == "base~3"
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/sock" in cmd


# ---------------------------------------------------------------------------
# tmux: functions without socket use env var via _tmux_cmd
# ---------------------------------------------------------------------------

class TestEnvVarSocket:
    """Verify that functions without explicit socket_path still pick up PM_TMUX_SOCKET."""

    @patch("pm_core.tmux.subprocess.run")
    def test_split_pane_uses_env_socket(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="%1\n")
        with patch.dict(os.environ, {"PM_TMUX_SOCKET": "/tmp/env-sock"}):
            tmux.split_pane("sess", "h", "bash")
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/env-sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_send_keys_uses_env_socket(self, mock_run):
        with patch.dict(os.environ, {"PM_TMUX_SOCKET": "/tmp/env-sock"}):
            tmux.send_keys("sess:0", "ls")
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/env-sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_new_window_uses_env_socket(self, mock_run):
        # new_window calls list_windows and select_window internally
        mock_run.return_value = MagicMock(returncode=0, stdout="@1 0 main\n")
        with patch.dict(os.environ, {"PM_TMUX_SOCKET": "/tmp/env-sock"}):
            with patch.object(tmux, "find_window_by_name", return_value={"index": "1"}):
                with patch.object(tmux, "current_or_base_session", return_value="sess"):
                    tmux.new_window("sess", "editor", "vim", "/tmp")
        # First call should be new-window
        cmd = mock_run.call_args_list[0][0][0]
        assert "-S" in cmd
        assert "/tmp/env-sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_set_hook_uses_env_socket(self, mock_run):
        with patch.dict(os.environ, {"PM_TMUX_SOCKET": "/tmp/env-sock"}):
            tmux.set_hook("sess", "after-resize-pane", "run-shell 'echo hi'")
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/env-sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_get_window_size_uses_env_socket(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="200 50\n")
        with patch.dict(os.environ, {"PM_TMUX_SOCKET": "/tmp/env-sock"}):
            tmux.get_window_size("sess")
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/env-sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_select_pane_uses_env_socket(self, mock_run):
        with patch.dict(os.environ, {"PM_TMUX_SOCKET": "/tmp/env-sock"}):
            tmux.select_pane("%1")
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/env-sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_resize_pane_uses_env_socket(self, mock_run):
        with patch.dict(os.environ, {"PM_TMUX_SOCKET": "/tmp/env-sock"}):
            tmux.resize_pane("%1", "x", 100)
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/env-sock" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_zoom_pane_uses_env_socket(self, mock_run):
        with patch.dict(os.environ, {"PM_TMUX_SOCKET": "/tmp/env-sock"}):
            tmux.zoom_pane("%1")
        cmd = mock_run.call_args[0][0]
        assert "-S" in cmd
        assert "/tmp/env-sock" in cmd


# ---------------------------------------------------------------------------
# tmux: next_grouped_session_name logic
# ---------------------------------------------------------------------------

class TestNextGroupedSessionName:
    """Unit tests for next_grouped_session_name naming logic."""

    @patch("pm_core.tmux.list_grouped_sessions", return_value=[])
    def test_first_grouped_session(self, _):
        assert tmux.next_grouped_session_name("base") == "base~1"

    @patch("pm_core.tmux.list_grouped_sessions", return_value=["base~1"])
    def test_increments_from_one(self, _):
        assert tmux.next_grouped_session_name("base") == "base~2"

    @patch("pm_core.tmux.list_grouped_sessions", return_value=["base~1", "base~3"])
    def test_uses_max_not_count(self, _):
        """Uses max suffix, not count, to avoid collisions."""
        assert tmux.next_grouped_session_name("base") == "base~4"

    @patch("pm_core.tmux.list_grouped_sessions", return_value=["base~5", "base~2", "base~8"])
    def test_handles_out_of_order(self, _):
        assert tmux.next_grouped_session_name("base") == "base~9"
