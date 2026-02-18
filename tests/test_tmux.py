"""Tests for pm_core.tmux — tmux helper functions."""

import os
from unittest.mock import patch, MagicMock

from pm_core.tmux import (
    has_tmux,
    in_tmux,
    session_exists,
    create_session,
    new_window,
    split_pane,
    split_pane_background,
    split_pane_at,
    send_keys_literal,
    kill_window,
    get_pane_geometries,
    get_window_id,
    get_window_size,
    swap_pane,
    list_windows,
    find_window_by_name,
    select_window,
    is_zoomed,
    unzoom_pane,
    get_session_name,
    current_or_base_session,
)


# ---------------------------------------------------------------------------
# has_tmux / in_tmux
# ---------------------------------------------------------------------------

class TestHasTmux:
    @patch("shutil.which", return_value="/usr/bin/tmux")
    def test_installed(self, mock_which):
        assert has_tmux() is True

    @patch("shutil.which", return_value=None)
    def test_not_installed(self, mock_which):
        assert has_tmux() is False


class TestInTmux:
    def test_in_tmux(self):
        with patch.dict(os.environ, {"TMUX": "/tmp/tmux-1000/default,123,0"}):
            assert in_tmux() is True

    def test_not_in_tmux(self):
        env = os.environ.copy()
        env.pop("TMUX", None)
        with patch.dict(os.environ, env, clear=True):
            assert in_tmux() is False


# ---------------------------------------------------------------------------
# session_exists
# ---------------------------------------------------------------------------

class TestSessionExists:
    @patch("pm_core.tmux.subprocess.run")
    def test_exists(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert session_exists("myproj") is True

    @patch("pm_core.tmux.subprocess.run")
    def test_not_exists(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert session_exists("myproj") is False


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------

class TestCreateSession:
    @patch("pm_core.tmux.subprocess.run")
    def test_creates_detached(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        create_session("proj", "/home/user", "bash")
        cmd = mock_run.call_args[0][0]
        assert "new-session" in cmd
        assert "-d" in cmd
        assert "-s" in cmd


# ---------------------------------------------------------------------------
# split_pane / split_pane_background / split_pane_at
# ---------------------------------------------------------------------------

class TestSplitPane:
    @patch("pm_core.tmux.subprocess.run")
    def test_horizontal(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="%5\n")
        result = split_pane("sess", "h", "echo hi")
        cmd = mock_run.call_args[0][0]
        assert "-h" in cmd
        assert result == "%5"

    @patch("pm_core.tmux.subprocess.run")
    def test_vertical(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="%6\n")
        result = split_pane("sess", "v", "echo hi")
        cmd = mock_run.call_args[0][0]
        assert "-v" in cmd


class TestSplitPaneBackground:
    @patch("pm_core.tmux.subprocess.run")
    def test_includes_dash_d(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="%7\n")
        split_pane_background("sess", "v", "cmd")
        cmd = mock_run.call_args[0][0]
        assert "-d" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_horizontal(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="%8\n")
        split_pane_background("sess", "h", "cmd")
        cmd = mock_run.call_args[0][0]
        assert "-h" in cmd


class TestSplitPaneAt:
    @patch("pm_core.tmux.subprocess.run")
    def test_basic(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="%9\n")
        result = split_pane_at("%1", "v", "cmd")
        cmd = mock_run.call_args[0][0]
        assert "-t" in cmd
        assert "%1" in cmd
        assert result == "%9"

    @patch("pm_core.tmux.subprocess.run")
    def test_background(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="%10\n")
        split_pane_at("%1", "h", "cmd", background=True)
        cmd = mock_run.call_args[0][0]
        assert "-d" in cmd


# ---------------------------------------------------------------------------
# send_keys_literal
# ---------------------------------------------------------------------------

class TestSendKeysLiteral:
    @patch("pm_core.tmux.subprocess.run")
    def test_no_enter(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        send_keys_literal("%1", "C-c")
        cmd = mock_run.call_args[0][0]
        assert "Enter" not in cmd
        assert "C-c" in cmd


# ---------------------------------------------------------------------------
# kill_window
# ---------------------------------------------------------------------------

class TestKillWindow:
    @patch("pm_core.tmux.subprocess.run")
    def test_kill(self, mock_run):
        kill_window("sess", "1")
        cmd = mock_run.call_args[0][0]
        assert "kill-window" in cmd
        assert "sess:1" in cmd


# ---------------------------------------------------------------------------
# get_pane_geometries
# ---------------------------------------------------------------------------

class TestGetPaneGeometries:
    @patch("pm_core.tmux.subprocess.run")
    def test_parses_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="%0 0 0 80 24\n%1 80 0 40 24\n",
        )
        result = get_pane_geometries("sess")
        assert len(result) == 2
        assert result[0] == ("%0", 0, 0, 80, 24)
        assert result[1] == ("%1", 80, 0, 40, 24)

    @patch("pm_core.tmux.subprocess.run")
    def test_empty_on_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert get_pane_geometries("sess") == []


# ---------------------------------------------------------------------------
# get_window_size
# ---------------------------------------------------------------------------

class TestGetWindowSize:
    @patch("pm_core.tmux.subprocess.run")
    def test_parses(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="200 50\n")
        assert get_window_size("sess") == (200, 50)

    @patch("pm_core.tmux.subprocess.run")
    def test_error_returns_zero(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert get_window_size("sess") == (0, 0)

    @patch("pm_core.tmux.subprocess.run")
    def test_unexpected_output(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="bad\n")
        assert get_window_size("sess") == (0, 0)


# ---------------------------------------------------------------------------
# get_window_id
# ---------------------------------------------------------------------------

class TestGetWindowId:
    @patch("pm_core.tmux.current_or_base_session", return_value="sess")
    @patch("pm_core.tmux.subprocess.run")
    def test_returns_id(self, mock_run, mock_cobs):
        mock_run.return_value = MagicMock(returncode=0, stdout="@1\n")
        assert get_window_id("sess") == "@1"


# ---------------------------------------------------------------------------
# swap_pane
# ---------------------------------------------------------------------------

class TestSwapPane:
    @patch("pm_core.tmux.subprocess.run")
    def test_swap(self, mock_run):
        swap_pane("%0", "%1")
        cmd = mock_run.call_args[0][0]
        assert "swap-pane" in cmd
        assert "%0" in cmd
        assert "%1" in cmd


# ---------------------------------------------------------------------------
# list_windows / find_window_by_name
# ---------------------------------------------------------------------------

class TestListWindows:
    @patch("pm_core.tmux.subprocess.run")
    def test_parses(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="@0 0 main\n@1 1 editor\n",
        )
        result = list_windows("sess")
        assert len(result) == 2
        assert result[0] == {"id": "@0", "index": "0", "name": "main"}
        assert result[1] == {"id": "@1", "index": "1", "name": "editor"}

    @patch("pm_core.tmux.subprocess.run")
    def test_empty_on_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert list_windows("sess") == []


class TestFindWindowByName:
    @patch("pm_core.tmux.list_windows")
    def test_found(self, mock_lw):
        mock_lw.return_value = [
            {"id": "@0", "index": "0", "name": "main"},
            {"id": "@1", "index": "1", "name": "editor"},
        ]
        result = find_window_by_name("sess", "editor")
        assert result is not None
        assert result["name"] == "editor"

    @patch("pm_core.tmux.list_windows")
    def test_not_found(self, mock_lw):
        mock_lw.return_value = [{"id": "@0", "index": "0", "name": "main"}]
        assert find_window_by_name("sess", "missing") is None


# ---------------------------------------------------------------------------
# select_window
# ---------------------------------------------------------------------------

class TestSelectWindow:
    @patch("pm_core.tmux.current_or_base_session", return_value="sess")
    @patch("pm_core.tmux.subprocess.run")
    def test_success(self, mock_run, mock_cobs):
        mock_run.return_value = MagicMock(returncode=0)
        assert select_window("sess", "1") is True

    @patch("pm_core.tmux.current_or_base_session", return_value="sess")
    @patch("pm_core.tmux.subprocess.run")
    def test_failure(self, mock_run, mock_cobs):
        mock_run.return_value = MagicMock(returncode=1)
        assert select_window("sess", "99") is False


# ---------------------------------------------------------------------------
# is_zoomed / unzoom_pane
# ---------------------------------------------------------------------------

class TestIsZoomed:
    @patch("pm_core.tmux.subprocess.run")
    def test_zoomed(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="1\n")
        assert is_zoomed("sess") is True

    @patch("pm_core.tmux.subprocess.run")
    def test_not_zoomed(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="0\n")
        assert is_zoomed("sess") is False


class TestUnzoomPane:
    @patch("pm_core.tmux.subprocess.run")
    def test_unzooms_when_zoomed(self, mock_run):
        # First call: is_zoomed check (returns "1")
        # Second call: the actual resize-pane -Z
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="1\n"),  # is_zoomed
            MagicMock(returncode=0),  # resize-pane -Z
        ]
        unzoom_pane("sess")
        assert mock_run.call_count == 2

    @patch("pm_core.tmux.subprocess.run")
    def test_noop_when_not_zoomed(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="0\n")
        unzoom_pane("sess")
        assert mock_run.call_count == 1  # only the is_zoomed check


# ---------------------------------------------------------------------------
# get_session_name
# ---------------------------------------------------------------------------

class TestGetSessionName:
    @patch("pm_core.tmux.subprocess.run")
    def test_uses_tmux_pane_env(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="myproj\n")
        with patch.dict(os.environ, {"TMUX_PANE": "%5"}):
            result = get_session_name()
        cmd = mock_run.call_args[0][0]
        assert "-t" in cmd
        assert "%5" in cmd
        assert result == "myproj"

    @patch("pm_core.tmux.subprocess.run")
    def test_fallback_without_tmux_pane(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="sess\n")
        env = os.environ.copy()
        env.pop("TMUX_PANE", None)
        with patch.dict(os.environ, env, clear=True):
            result = get_session_name()
        cmd = mock_run.call_args[0][0]
        assert "-t" not in cmd
        assert result == "sess"


# ---------------------------------------------------------------------------
# current_or_base_session
# ---------------------------------------------------------------------------

class TestCurrentOrBaseSession:
    @patch("pm_core.tmux.list_grouped_sessions", return_value=[])
    @patch("pm_core.tmux.in_tmux", return_value=False)
    def test_not_in_tmux_returns_base(self, mock_in, mock_lg):
        assert current_or_base_session("proj") == "proj"

    @patch("pm_core.tmux.get_session_name", return_value="proj")
    @patch("pm_core.tmux.in_tmux", return_value=True)
    def test_in_same_session(self, mock_in, mock_gsn):
        assert current_or_base_session("proj") == "proj"

    @patch("pm_core.tmux.get_session_name", return_value="proj~2")
    @patch("pm_core.tmux.in_tmux", return_value=True)
    def test_in_grouped_session(self, mock_in, mock_gsn):
        assert current_or_base_session("proj") == "proj~2"

    @patch("pm_core.tmux.subprocess.run")
    @patch("pm_core.tmux.list_grouped_sessions", return_value=["proj~1", "proj~2"])
    @patch("pm_core.tmux.get_session_name", return_value="other")
    @patch("pm_core.tmux.in_tmux", return_value=True)
    def test_finds_attached_grouped(self, mock_in, mock_gsn, mock_lg, mock_run):
        """When current session is different, finds an attached grouped session."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="0\n"),  # proj~1 not attached
            MagicMock(returncode=0, stdout="1\n"),  # proj~2 attached
        ]
        assert current_or_base_session("proj") == "proj~2"
