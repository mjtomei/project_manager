"""pr-28bda5d: the home window must be kicked in lockstep with state
mutations, via the two central hooks the PR added:

- ``runtime_state.set_action_state`` — kicks on a *real* transition or
  entry/exit, but not on no-op heartbeat / clear-of-absent writes.
- ``cli.helpers.trigger_tui_reload`` — kicks whenever the TUI is
  reloaded (which every mutating CLI command already triggers).

These guard the hand-written kick condition in ``set_action_state`` and
the lockstep hook in ``trigger_tui_reload``; ``refresh_home`` itself is
covered in ``test_home_window.py``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pm_core import runtime_state


@pytest.fixture(autouse=True)
def _isolate_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_state, "_runtime_dir", lambda: tmp_path)


class TestSetActionStateKick:
    def test_real_transition_kicks(self):
        with patch("pm_core.home_window.refresh_home") as kick:
            runtime_state.set_action_state("pr-1", "review", "running")
        kick.assert_called_once()

    def test_repeat_heartbeat_does_not_kick(self):
        runtime_state.set_action_state("pr-1", "review", "running")
        with patch("pm_core.home_window.refresh_home") as kick:
            # Same state again — a no-op heartbeat, no rendered change.
            runtime_state.set_action_state("pr-1", "review", "running")
        kick.assert_not_called()

    def test_clear_of_existing_action_kicks(self):
        runtime_state.set_action_state("pr-1", "review", "running")
        with patch("pm_core.home_window.refresh_home") as kick:
            runtime_state.set_action_state("pr-1", "review", None)
        kick.assert_called_once()

    def test_clear_of_absent_action_does_not_kick(self):
        with patch("pm_core.home_window.refresh_home") as kick:
            runtime_state.set_action_state("pr-1", "never-recorded", None)
        kick.assert_not_called()

    def test_kick_failure_is_swallowed(self):
        # A broken home window must never break a state write.
        with patch("pm_core.home_window.refresh_home",
                   side_effect=RuntimeError("boom")):
            runtime_state.set_action_state("pr-1", "review", "running")
        assert runtime_state.get_action_state("pr-1", "review")["state"] == "running"


class TestTriggerTuiReloadKick:
    def test_reload_kicks_home_with_resolved_session(self):
        from pm_core.cli import helpers

        with patch("pm_core.cli.helpers._find_tui_pane",
                   return_value=(None, "pm-x")), \
             patch("pm_core.home_window.refresh_home") as kick:
            helpers.trigger_tui_reload()
        kick.assert_called_once_with("pm-x")
