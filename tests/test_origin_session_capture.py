"""Regression tests for pr-c41f029: capture the originating tmux session at
PR-actions-pane open, not at action-execution time.

The bug: window-following re-detected the originating session *late* via
``tmux.sessions_on_window`` (querying each grouped session's current active
window). Between popup-open and action-execution the active window/session
can change, so the wrong session — or none — got switched to the new window.

The fix: capture the invoking session once when the picker opens
(``runtime_state.capture_origin_session``), thread it through the action
context, and have the window-following call sites prefer it
(``tmux.followers_for_window``), using ``sessions_on_window`` only as a
fallback when no session was captured.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from pm_core import runtime_state
from pm_core import tmux as tmux_mod


@pytest.fixture(autouse=True)
def _isolate_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_state, "_runtime_dir", lambda: tmp_path)


# ---------------------------------------------------------------------------
# runtime_state.capture_origin_session / consume_origin_session
# ---------------------------------------------------------------------------

class TestCaptureConsume:
    def test_roundtrip(self):
        runtime_state.capture_origin_session("pr-x", "qa", "pm-proj~2")
        assert runtime_state.consume_origin_session("pr-x", "qa") == "pm-proj~2"

    def test_consume_clears(self):
        runtime_state.capture_origin_session("pr-x", "qa", "pm-proj~2")
        assert runtime_state.consume_origin_session("pr-x", "qa") == "pm-proj~2"
        # Second consume sees nothing — no stale leak into the next run.
        assert runtime_state.consume_origin_session("pr-x", "qa") is None

    def test_consume_missing_returns_none(self):
        assert runtime_state.consume_origin_session("pr-none", "qa") is None
        # No empty stub entry left behind.
        assert runtime_state.get_action_state("pr-none", "qa") == {}

    def test_empty_session_not_captured(self):
        runtime_state.capture_origin_session("pr-x", "qa", "")
        assert runtime_state.consume_origin_session("pr-x", "qa") is None

    def test_survives_launching_running_transitions(self):
        """The captured session must persist across the action's own
        state writes between capture (popup-open) and consume (execution)."""
        runtime_state.capture_origin_session("pr-x", "review-loop", "pm-proj~3")
        runtime_state.set_action_state("pr-x", "review-loop", "launching")
        runtime_state.set_action_state("pr-x", "review-loop", "running",
                                       iteration=1)
        entry = runtime_state.get_action_state("pr-x", "review-loop")
        assert entry.get("state") == "running"
        assert entry.get("origin_session") == "pm-proj~3"
        assert runtime_state.consume_origin_session(
            "pr-x", "review-loop") == "pm-proj~3"

    def test_capture_preserves_existing_state(self):
        runtime_state.set_action_state("pr-x", "qa", "running")
        runtime_state.capture_origin_session("pr-x", "qa", "pm-proj~1")
        assert runtime_state.get_action_state("pr-x", "qa").get("state") \
            == "running"


# ---------------------------------------------------------------------------
# tmux.followers_for_window — prefer captured, fall back to detection
# ---------------------------------------------------------------------------

class TestFollowersForWindow:
    def test_prefers_captured_without_detecting(self):
        """When a captured session is present, sessions_on_window must NOT be
        called — the whole point of capturing is to skip late detection."""
        with patch.object(tmux_mod, "sessions_on_window",
                          side_effect=AssertionError(
                              "sessions_on_window must not be called")):
            assert tmux_mod.followers_for_window(
                "base", "@1", "pm-proj~2") == ["pm-proj~2"]

    def test_captured_list_passed_through(self):
        with patch.object(tmux_mod, "sessions_on_window",
                          side_effect=AssertionError("must not detect")):
            assert tmux_mod.followers_for_window(
                "base", "@1", ["pm-proj~2", "pm-proj~3"]) \
                == ["pm-proj~2", "pm-proj~3"]

    def test_falls_back_when_no_capture(self):
        with patch.object(tmux_mod, "sessions_on_window",
                          return_value=["pm-proj~9"]) as m:
            assert tmux_mod.followers_for_window("base", "@1", None) \
                == ["pm-proj~9"]
            m.assert_called_once_with("base", "@1")

    def test_empty_capture_falls_back(self):
        with patch.object(tmux_mod, "sessions_on_window",
                          return_value=["pm-proj~9"]) as m:
            assert tmux_mod.followers_for_window("base", "@1", []) \
                == ["pm-proj~9"]
            m.assert_called_once()


# ---------------------------------------------------------------------------
# Race simulation: active window changes between open and execution
# ---------------------------------------------------------------------------

class TestRaceResolution:
    def test_captured_session_wins_over_late_detection(self):
        """Capture session A at popup-open. By execution time the active
        window has moved, so late detection (sessions_on_window) would report
        a *different* session B (or nobody). The captured A must be the one
        switched — and detection must be skipped entirely."""
        runtime_state.capture_origin_session("pr-x", "qa", "pm-proj~A")

        # Late detection would return the wrong answer due to the race.
        with patch.object(tmux_mod, "sessions_on_window",
                          return_value=["pm-proj~B"]) as detect:
            captured = runtime_state.consume_origin_session("pr-x", "qa")
            followers = tmux_mod.followers_for_window("base", "@old", captured)

        assert followers == ["pm-proj~A"]
        detect.assert_not_called()

    def test_no_capture_uses_detection(self):
        """Legacy/CLI path: nothing captured → fall back to live detection."""
        with patch.object(tmux_mod, "sessions_on_window",
                          return_value=["pm-proj~B"]):
            captured = runtime_state.consume_origin_session("pr-none", "qa")
            followers = tmux_mod.followers_for_window("base", "@old", captured)
        assert followers == ["pm-proj~B"]


# ---------------------------------------------------------------------------
# tmux.active_client_session — unambiguous single client only
# ---------------------------------------------------------------------------

class TestActiveClientSession:
    @patch("pm_core.tmux.list_grouped_sessions", return_value=["base~1"])
    @patch("pm_core.tmux.subprocess.run")
    def test_single_client(self, mock_run, _lg):
        mock_run.return_value = MagicMock(returncode=0, stdout="base~1\n")
        assert tmux_mod.active_client_session("base") == "base~1"

    @patch("pm_core.tmux.list_grouped_sessions", return_value=["base~1"])
    @patch("pm_core.tmux.subprocess.run")
    def test_multiple_clients_ambiguous(self, mock_run, _lg):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="base\nbase~1\n")
        assert tmux_mod.active_client_session("base") is None

    @patch("pm_core.tmux.list_grouped_sessions", return_value=[])
    @patch("pm_core.tmux.subprocess.run")
    def test_no_clients(self, mock_run, _lg):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        assert tmux_mod.active_client_session("base") is None

    @patch("pm_core.tmux.list_grouped_sessions", return_value=[])
    @patch("pm_core.tmux.subprocess.run")
    def test_error_returns_none(self, mock_run, _lg):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert tmux_mod.active_client_session("base") is None


# ---------------------------------------------------------------------------
# Picker dispatch records the popup session under the right (pr_id, action)
# ---------------------------------------------------------------------------

class TestPickerCapture:
    @pytest.mark.parametrize("cmd,pr_id,action", [
        ("tui:review-loop start pr-abc", "pr-abc", "review-loop"),
        ("tui:pr qa loop pr-abc", "pr-abc", "qa"),
        ("tui:pr qa fresh pr-abc", "pr-abc", "qa"),
        ("tui:pr qa pr-abc", "pr-abc", "qa"),
        ("pr review --fresh pr-abc", "pr-abc", "review"),
        ("pr start pr-abc", "pr-abc", "start"),
        ("pr merge --resolve-window pr-abc", "pr-abc", "merge"),
    ])
    def test_origin_action_parser(self, cmd, pr_id, action):
        from pm_core.cli.session import _origin_action_for_cmd
        assert _origin_action_for_cmd(cmd) == (pr_id, action)

    @pytest.mark.parametrize("cmd,expected", [
        ("", (None, None)),                  # empty
        ("garbage", (None, None)),           # not a recognized form
        ("pr foo pr-x", (None, None)),       # unknown pr subcommand
        ("tui:garbage", (None, None)),       # tui: route, unparseable
        ("pr start", (None, "start")),       # direct route, no pr id token
    ])
    def test_origin_action_parser_no_match(self, cmd, expected):
        """Malformed / no-pr-id commands return without a usable
        (pr_id, action) so the caller's `if o_pr and o_action` guard skips
        capture — the spec's "capture skipped; no crash" edge case."""
        from pm_core.cli.session import _origin_action_for_cmd
        result = _origin_action_for_cmd(cmd)
        assert result == expected
        # The capture guard only fires when BOTH are truthy; verify these
        # all fail it so no spurious entry is recorded.
        o_pr, o_action = result
        assert not (o_pr and o_action)

    def test_run_picker_command_captures_session(self):
        """_run_picker_command must pin the popup session at dispatch time
        for the (pr_id, action) the action will later consume."""
        from pm_core.cli import session as session_mod
        # Stop after capture: short-circuit the actual dispatch.
        with patch("pm_core.cli.helpers.trigger_tui_command",
                   return_value=False), \
             patch.object(session_mod, "_wait_dismiss"), \
             patch.object(session_mod.pane_registry, "base_session_name",
                          return_value="pm-proj"):
            session_mod._run_picker_command(
                "tui:pr qa loop pr-abc", "pm-proj~2")
        assert runtime_state.get_action_state("pr-abc", "qa").get(
            "origin_session") == "pm-proj~2"
