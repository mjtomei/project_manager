"""Tests for pm_core.tmux — tmux helper functions."""

import os
from unittest.mock import patch, MagicMock

from pm_core.tmux import (
    has_tmux,
    in_tmux,
    session_exists,
    create_session,
    new_window_get_pane,
    split_pane,
    split_pane_background,
    split_pane_at,
    send_keys_literal,
    kill_window,
    apply_layout,
    get_pane_indices,
    get_pane_geometries,
    get_window_id,
    get_window_size,
    swap_pane,
    list_windows,
    find_window_by_name,
    select_window,
    select_pane_smart,
    is_zoomed,
    unzoom_pane,
    get_session_name,
    current_or_base_session,
    list_grouped_sessions,
    find_unattached_grouped_session,
    sessions_on_window,
    attached_group_active_windows,
)


# ---------------------------------------------------------------------------
# has_tmux / in_tmux
# ---------------------------------------------------------------------------

class TestAttachedGroupActiveWindows:
    @patch("pm_core.tmux._run")
    def test_single_query_filters_group_and_attachment(self, run):
        run.return_value = MagicMock(returncode=0, stdout=(
            "1|@1|base\n2|@2|base~1\n0|@3|base~2\n"
            "1|@4|other\n1|@5|base-extra\n"
            "|@6|base~3\n1||base~4\nmalformed\n"
            "1|@7|base~5|with|pipes\n"))
        assert attached_group_active_windows("base", socket_path="/socket") == {
            "base": "@1", "base~1": "@2", "base~5|with|pipes": "@7"}
        run.assert_called_once()
        cmd = run.call_args.args[0]
        assert "list-sessions" in cmd
        assert "#{session_attached}|#{window_id}|#{session_name}" in cmd
        assert cmd[cmd.index("-S") + 1] == "/socket"

    @patch("pm_core.tmux._run")
    def test_separator_is_printable_so_c_locale_cannot_break_it(self, run):
        # tmux rewrites control characters (e.g. a tab) in format output to
        # "_" when the server runs under LC_ALL=C, so a tab-separated query
        # silently parsed as zero fields.  The separator must be printable.
        run.return_value = MagicMock(returncode=0, stdout="1|@1|base\n")
        assert attached_group_active_windows("base") == {"base": "@1"}
        fmt = next(a for a in run.call_args.args[0] if "session_name" in a)
        assert "\t" not in fmt
        assert "|" in fmt

    @patch("pm_core.tmux._run")
    def test_error_returns_empty_map(self, run):
        run.return_value = MagicMock(returncode=1, stdout="")
        assert attached_group_active_windows("base") == {}
        run.assert_called_once()


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
        env.pop("PM_POPUP_SESSION", None)
        with patch.dict(os.environ, env, clear=True):
            result = get_session_name()
        cmd = mock_run.call_args[0][0]
        assert "-t" not in cmd
        assert result == "sess"

    @patch("pm_core.tmux.subprocess.run")
    def test_popup_session_env_without_tmux_pane(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        env = os.environ.copy()
        env.pop("TMUX_PANE", None)
        env["PM_POPUP_SESSION"] = "proj~7"
        with patch.dict(os.environ, env, clear=True):
            result = get_session_name()
        assert result == "proj~7"
        cmd = mock_run.call_args[0][0]
        assert "has-session" in cmd and "=proj~7" in cmd

    @patch("pm_core.tmux.subprocess.run")
    def test_popup_session_env_ignored_once_session_is_gone(self, mock_run):
        """An inherited PM_POPUP_SESSION naming a dead session falls back
        to the current client instead of returning a stale name."""
        mock_run.side_effect = [MagicMock(returncode=1, stdout=""),
                                MagicMock(returncode=0, stdout="proj~2\n")]
        env = os.environ.copy()
        env.pop("TMUX_PANE", None)
        env["PM_POPUP_SESSION"] = "proj~7"
        with patch.dict(os.environ, env, clear=True):
            result = get_session_name()
        assert result == "proj~2"

    @patch("pm_core.tmux.subprocess.run")
    def test_tmux_pane_beats_popup_session_env(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="myproj\n")
        with patch.dict(os.environ, {"TMUX_PANE": "%5",
                                     "PM_POPUP_SESSION": "proj~7"}):
            result = get_session_name()
        assert result == "myproj"


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

    @patch("pm_core.tmux.subprocess.run")
    @patch("pm_core.tmux.get_session_name", return_value="proj~2")
    @patch("pm_core.tmux.in_tmux", return_value=True)
    def test_in_grouped_session(self, mock_in, mock_gsn, mock_run):
        """When current session is a grouped session and it's attached, return it."""
        mock_run.return_value = MagicMock(returncode=0, stdout="1\n")
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


# ---------------------------------------------------------------------------
# new_window_get_pane
# ---------------------------------------------------------------------------

class TestNewWindowGetPane:
    @patch("pm_core.tmux.get_pane_indices", return_value=[("%5", 0)])
    @patch("pm_core.tmux.current_or_base_session", return_value="sess")
    @patch("pm_core.tmux.find_window_by_name", return_value={"id": "@1", "index": "1", "name": "review"})
    @patch("pm_core.tmux.subprocess.run")
    def test_returns_pane_id(self, mock_run, mock_fwbn, mock_cobs, mock_gpi):
        mock_run.return_value = MagicMock(returncode=0)
        result = new_window_get_pane("sess", "review", "bash", "/tmp")
        assert result == "%5"

    @patch("pm_core.tmux.find_window_by_name", return_value=None)
    @patch("pm_core.tmux.subprocess.run")
    def test_returns_none_when_window_not_found(self, mock_run, mock_fwbn):
        mock_run.return_value = MagicMock(returncode=0)
        result = new_window_get_pane("sess", "review", "bash", "/tmp")
        assert result is None

    @patch("pm_core.tmux.get_pane_indices", return_value=[])
    @patch("pm_core.tmux.current_or_base_session", return_value="sess")
    @patch("pm_core.tmux.find_window_by_name", return_value={"id": "@1", "index": "1", "name": "review"})
    @patch("pm_core.tmux.subprocess.run")
    def test_returns_none_when_no_panes(self, mock_run, mock_fwbn, mock_cobs, mock_gpi):
        mock_run.return_value = MagicMock(returncode=0)
        result = new_window_get_pane("sess", "review", "bash", "/tmp")
        assert result is None

    @patch("pm_core.tmux.get_pane_indices", return_value=[("%5", 0)])
    @patch("pm_core.tmux.current_or_base_session", return_value="sess")
    @patch("pm_core.tmux.find_window_by_name", return_value={"id": "@1", "index": "1", "name": "review"})
    @patch("pm_core.tmux.subprocess.run")
    def test_switch_false_skips_select_window(self, mock_run, mock_fwbn, mock_cobs, mock_gpi):
        mock_run.return_value = MagicMock(returncode=0)
        result = new_window_get_pane("sess", "review", "bash", "/tmp", switch=False)
        assert result == "%5"
        # select-window should NOT have been called — only new-window
        calls = mock_run.call_args_list
        cmds = [c[0][0] for c in calls]
        assert any("new-window" in cmd for cmd in cmds)
        assert not any("select-window" in cmd for cmd in cmds)
        mock_cobs.assert_not_called()


# ---------------------------------------------------------------------------
# apply_layout
# ---------------------------------------------------------------------------

class TestApplyLayout:
    @patch("pm_core.tmux.subprocess.run")
    def test_failure_logs_warning(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="layout error")
        result = apply_layout("sess", "0", "bad-layout")
        assert result is False


# ---------------------------------------------------------------------------
# get_pane_indices
# ---------------------------------------------------------------------------

class TestGetPaneIndices:
    @patch("pm_core.tmux.subprocess.run")
    def test_error_returns_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert get_pane_indices("sess") == []

    @patch("pm_core.tmux.subprocess.run")
    def test_parses_output(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="%0 0\n%1 1\n")
        result = get_pane_indices("sess")
        assert result == [("%0", 0), ("%1", 1)]


# ---------------------------------------------------------------------------
# select_pane_smart
# ---------------------------------------------------------------------------

class TestSelectPaneSmart:
    @patch("pm_core.tmux.zoom_pane")
    @patch("pm_core.tmux.select_pane")
    @patch("pm_core.pane_layout.is_mobile", return_value=True)
    def test_zooms_in_mobile(self, mock_mobile, mock_select, mock_zoom):
        select_pane_smart("%1", "sess", "0")
        mock_select.assert_called_once_with("%1")
        mock_zoom.assert_called_once_with("%1")

    @patch("pm_core.tmux.zoom_pane")
    @patch("pm_core.tmux.select_pane")
    @patch("pm_core.pane_layout.is_mobile", return_value=False)
    def test_no_zoom_in_desktop(self, mock_mobile, mock_select, mock_zoom):
        select_pane_smart("%1", "sess", "0")
        mock_select.assert_called_once_with("%1")
        mock_zoom.assert_not_called()


# ---------------------------------------------------------------------------
# list_grouped_sessions / find_unattached_grouped_session
# ---------------------------------------------------------------------------

class TestListGroupedSessions:
    @patch("pm_core.tmux.subprocess.run")
    def test_error_returns_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert list_grouped_sessions("proj") == []

    @patch("pm_core.tmux.subprocess.run")
    def test_filters_and_sorts(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="proj\nproj~2\nproj~1\nother~1\n"
        )
        result = list_grouped_sessions("proj")
        assert result == ["proj~1", "proj~2"]


class TestFindUnattachedGroupedSession:
    @patch("pm_core.tmux.list_grouped_sessions", return_value=[])
    def test_no_grouped_returns_none(self, mock_lg):
        assert find_unattached_grouped_session("proj") is None

    @patch("pm_core.tmux.subprocess.run")
    @patch("pm_core.tmux.list_grouped_sessions", return_value=["proj~1", "proj~2"])
    def test_all_attached_returns_none(self, mock_lg, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="1\n"),  # proj~1 attached
            MagicMock(returncode=0, stdout="1\n"),  # proj~2 attached
        ]
        assert find_unattached_grouped_session("proj") is None

    @patch("pm_core.tmux.subprocess.run")
    @patch("pm_core.tmux.list_grouped_sessions", return_value=["proj~1", "proj~2"])
    def test_finds_first_unattached(self, mock_lg, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="1\n"),  # proj~1 attached
            MagicMock(returncode=0, stdout="0\n"),  # proj~2 unattached
        ]
        assert find_unattached_grouped_session("proj") == "proj~2"


class TestSessionsOnWindow:
    @patch("pm_core.tmux.subprocess.run")
    @patch("pm_core.tmux.list_grouped_sessions", return_value=[])
    def test_no_match(self, mock_lg, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="@2\n")
        assert sessions_on_window("proj", "@1") == []

    @patch("pm_core.tmux.subprocess.run")
    @patch("pm_core.tmux.list_grouped_sessions", return_value=["proj~1", "proj~2"])
    def test_returns_matching_sessions(self, mock_lg, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="@5\n"),   # base on @5
            MagicMock(returncode=0, stdout="@5\n"),   # proj~1 on @5
            MagicMock(returncode=0, stdout="@3\n"),   # proj~2 on @3
        ]
        assert sessions_on_window("proj", "@5") == ["proj", "proj~1"]

    @patch("pm_core.tmux.subprocess.run")
    @patch("pm_core.tmux.list_grouped_sessions", return_value=[])
    def test_display_error_skipped(self, mock_lg, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert sessions_on_window("proj", "@1") == []
