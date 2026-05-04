"""Regression tests for pr-6553192: suppress_switch must not leak across
action invocations. Setting the flag (on popup dismiss) then re-launching
the action via any path (TUI keybinding, fresh picker, auto-start) must
clear the flag so the new invocation's window-switch is not skipped."""

from __future__ import annotations

import pytest

from pm_core import runtime_state


@pytest.fixture(autouse=True)
def _isolate_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_state, "_runtime_dir", lambda: tmp_path)


def test_dismiss_then_fresh_launch_clears_flag():
    pr, act = "pr-abc", "review"
    runtime_state.request_suppress_switch(pr, act)
    assert runtime_state.get_action_state(pr, act).get("suppress_switch") is True

    # Fresh invocation transitions to launching (e.g. via TUI keybinding).
    runtime_state.set_action_state(pr, act, "launching")

    entry = runtime_state.get_action_state(pr, act)
    assert entry.get("state") == "launching"
    assert "suppress_switch" not in entry
    # Subsequent consume sees no flag — caller proceeds with focus switch.
    assert runtime_state.consume_suppress_switch(pr, act) is False


def test_transition_to_running_from_absent_clears_flag():
    pr, act = "pr-abc", "qa"
    runtime_state.request_suppress_switch(pr, act)
    runtime_state.set_action_state(pr, act, "running")
    assert "suppress_switch" not in runtime_state.get_action_state(pr, act)


def test_picker_spinner_lifecycle_preserved():
    """Inside a single picker invocation: state goes launching -> running,
    user dismisses (flag set with state=None), then window appears and
    spinner consumes the flag. The transition from launching to running
    must not pre-clear the flag, and re-writes of running must not either."""
    pr, act = "pr-abc", "review-loop"
    runtime_state.set_action_state(pr, act, "launching")
    runtime_state.set_action_state(pr, act, "running")
    # User dismisses popup.
    runtime_state.request_suppress_switch(pr, act)
    assert runtime_state.get_action_state(pr, act).get("suppress_switch") is True
    # Background updates in the same invocation (state stays running).
    runtime_state.set_action_state(pr, act, "running", iteration=2)
    assert runtime_state.get_action_state(pr, act).get("suppress_switch") is True
    # Spinner consumes when window appears.
    assert runtime_state.consume_suppress_switch(pr, act) is True
    assert "suppress_switch" not in runtime_state.get_action_state(pr, act)


def test_terminal_transition_does_not_clear_flag():
    """done/failed transitions leave the flag alone; next launching clears."""
    pr, act = "pr-abc", "review"
    runtime_state.set_action_state(pr, act, "running")
    runtime_state.request_suppress_switch(pr, act)
    runtime_state.set_action_state(pr, act, "done")
    assert runtime_state.get_action_state(pr, act).get("suppress_switch") is True
    # The next fresh launch clears it.
    runtime_state.set_action_state(pr, act, "launching")
    assert "suppress_switch" not in runtime_state.get_action_state(pr, act)


def test_idempotent_launching_does_not_clear_flag_set_during_invocation():
    """If something writes launching twice in a row, and a flag was set in
    between, the second launching write should not clear (prior state was
    already launching — not a fresh invocation)."""
    pr, act = "pr-abc", "review"
    runtime_state.set_action_state(pr, act, "launching")
    runtime_state.request_suppress_switch(pr, act)
    runtime_state.set_action_state(pr, act, "launching", pane_id="%9")
    assert runtime_state.get_action_state(pr, act).get("suppress_switch") is True


def test_request_suppress_switch_does_not_clear_itself():
    pr, act = "pr-abc", "review"
    runtime_state.set_action_state(pr, act, "running")
    runtime_state.request_suppress_switch(pr, act)
    assert runtime_state.get_action_state(pr, act).get("suppress_switch") is True
