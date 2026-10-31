"""Regression tests for pr-b423bfd: the popup spinner must exit when the
action reaches a terminal state (done/failed) — even if no tmux window
is created. Previously it spun forever showing 'review-loop: done…'."""

import sys
import termios
from unittest.mock import MagicMock, patch

import pytest

from pm_core.cli import session as session_mod


@pytest.fixture(autouse=True)
def _no_real_state(monkeypatch, tmp_path):
    from pm_core import runtime_state
    monkeypatch.setattr(runtime_state, "_runtime_dir", lambda: tmp_path)


@pytest.fixture
def fake_stdin(monkeypatch):
    """Replace sys.stdin with something whose fileno() works but tcgetattr fails,
    forcing the cbreak path to no-op cleanly."""
    fake = MagicMock()
    fake.fileno.return_value = 0
    fake.read.return_value = ""
    monkeypatch.setattr(sys, "stdin", fake)
    monkeypatch.setattr(termios, "tcgetattr",
                        MagicMock(side_effect=termios.error("not a tty")))


def _run_spinner(entry, fake_stdin_marker):
    # Simulate a launcher transition: the popup-start snapshot reads an
    # empty entry (no prior run) and subsequent polls observe the new
    # terminal state.  This trips the fresh-mode 'saw_state_change'
    # guard so the terminal-state short-circuit can fire.
    fake_tmux = MagicMock(list_windows=MagicMock(return_value=[]),
                          select_window=MagicMock())
    entries = [{}, entry]
    def _get(*_a, **_kw):
        return entries.pop(0) if len(entries) > 1 else entries[0]
    with patch.object(session_mod, "tmux_mod", fake_tmux), \
         patch.object(session_mod.store, "load", return_value={"prs": []}), \
         patch.object(session_mod, "state_root", return_value="/tmp"), \
         patch("pm_core.runtime_state.get_action_state", side_effect=_get), \
         patch.object(session_mod, "_wait_dismiss") as mock_dismiss, \
         patch("select.select", return_value=([], [], [])), \
         patch("click.echo"):
        session_mod._wait_for_tui_command("sess", "review-loop pr-001",
                                          tick_s=0.001)
        return mock_dismiss


def test_spinner_exits_on_failed_state_and_waits_for_dismiss(fake_stdin):
    entry = {"state": "failed", "verdict": "ERROR"}
    mock_dismiss = _run_spinner(entry, fake_stdin)
    assert mock_dismiss.called, "_wait_dismiss should be called on failure"


def test_spinner_exits_on_done_state_without_dismiss(fake_stdin):
    """Clean done state with no window should auto-dismiss (no key wait)."""
    entry = {"state": "done", "verdict": "PASS"}
    mock_dismiss = _run_spinner(entry, fake_stdin)
    assert not mock_dismiss.called, (
        "_wait_dismiss should NOT be called on clean done"
    )


def test_spinner_treats_done_with_error_verdict_as_failure(fake_stdin):
    """If state somehow ends as 'done' but verdict is ERROR, surface it."""
    entry = {"state": "done", "verdict": "ERROR"}
    mock_dismiss = _run_spinner(entry, fake_stdin)
    assert mock_dismiss.called


def test_spinner_waits_through_stale_terminal_state(fake_stdin):
    """Regression for pr-f27b882: fresh-mode actions must NOT short-circuit
    on a stale 'done'/'failed' entry left over from a prior run.  The popup
    must keep spinning until the launcher overwrites the state, otherwise
    the auto-switch in the window-appearance branch is skipped and the
    user is stranded on the wrong tmux window."""
    fake_tmux = MagicMock(list_windows=MagicMock(return_value=[]),
                          select_window=MagicMock())
    stale = {"state": "done", "verdict": "PASS",
             "updated_at": "2026-05-04T00:00:00Z"}
    # get_action_state returns the stale entry on every call; nothing
    # transitions.  The spinner must not exit on its own — we'll cancel
    # via a simulated keypress instead.
    select_calls = {"n": 0}
    def _select(*_a, **_kw):
        # First few ticks: no input.  Then deliver a 'q' keypress so the
        # spinner exits via the dismiss path; if it had short-circuited
        # on stale terminal state, we'd never reach this branch.
        select_calls["n"] += 1
        if select_calls["n"] < 3:
            return ([], [], [])
        return ([sys.stdin], [], [])
    fake_stdin_obj = sys.stdin
    fake_stdin_obj.read = MagicMock(return_value="q")
    with patch.object(session_mod, "tmux_mod", fake_tmux), \
         patch.object(session_mod.store, "load", return_value={"prs": []}), \
         patch.object(session_mod, "state_root", return_value="/tmp"), \
         patch("pm_core.runtime_state.get_action_state", return_value=stale), \
         patch.object(session_mod, "_wait_dismiss") as mock_dismiss, \
         patch("select.select", side_effect=_select), \
         patch("click.echo"):
        # q-keypress exits via SystemExit(0); short-circuit would
        # return normally without raising.
        with pytest.raises(SystemExit):
            session_mod._wait_for_tui_command("sess", "review-loop pr-001",
                                              tick_s=0.001)
    # If the short-circuit had fired we'd have called _wait_dismiss for
    # a 'failed' verdict or returned immediately for 'done'.  We expect
    # neither — the spinner kept polling and was cancelled by the user.
    assert not mock_dismiss.called
    assert select_calls["n"] >= 3


def test_plain_qa_start_after_finished_run_waits_and_honours_q(fake_stdin, tmp_path):
    """S92: a plain (non-fresh) ``qa`` start from the picker after a finished
    run.  The entry still reads the prior run's ``done PASS`` until the new
    run's windows exist, so the spinner must not exit on it: that printed
    the old verdict, closed the popup before q/Esc could be read, and the
    new run then took the focus the user asked to keep."""
    from pm_core import runtime_state
    runtime_state.set_action_state("pr-001", "qa", "done", verdict="PASS")
    fake_tmux = MagicMock(list_windows=MagicMock(return_value=[]),
                          select_window=MagicMock())
    select_calls = {"n": 0}

    def _select(*_a, **_kw):
        select_calls["n"] += 1
        if select_calls["n"] < 3:
            return ([], [], [])
        return ([sys.stdin], [], [])
    sys.stdin.read = MagicMock(return_value="q")
    with patch.object(session_mod, "tmux_mod", fake_tmux), \
         patch.object(session_mod.store, "load", return_value={"prs": []}), \
         patch.object(session_mod, "state_root", return_value="/tmp"), \
         patch.object(session_mod, "_wait_dismiss") as mock_dismiss, \
         patch("select.select", side_effect=_select), \
         patch("click.echo") as mock_echo:
        with pytest.raises(SystemExit):
            session_mod._wait_for_tui_command("sess", "pr qa pr-001",
                                              tick_s=0.001)
    assert not mock_dismiss.called
    assert select_calls["n"] >= 3
    shown = " ".join(str(c.args[0]) for c in mock_echo.call_args_list if c.args)
    assert "done" not in shown, shown
    # The q left the flag for the new run's window creation to consume.
    assert runtime_state.consume_suppress_switch("pr-001", "qa") is True


def test_plain_qa_start_exits_on_this_runs_terminal_state(fake_stdin):
    """The guard only skips the entry that was already terminal at popup
    start: once this invocation writes a new terminal state (no window),
    the spinner still exits on it."""
    fake_tmux = MagicMock(list_windows=MagicMock(return_value=[]),
                          select_window=MagicMock())
    stale = {"state": "done", "verdict": "PASS", "updated_at": "2026-05-04T00:00:00Z"}
    new = {"state": "failed", "verdict": "ERROR", "updated_at": "2026-05-04T00:01:00Z"}
    entries = [stale, stale, new]

    def _get(*_a, **_kw):
        return entries.pop(0) if len(entries) > 1 else entries[0]
    with patch.object(session_mod, "tmux_mod", fake_tmux), \
         patch.object(session_mod.store, "load", return_value={"prs": []}), \
         patch.object(session_mod, "state_root", return_value="/tmp"), \
         patch("pm_core.runtime_state.get_action_state", side_effect=_get), \
         patch.object(session_mod, "_wait_dismiss") as mock_dismiss, \
         patch("select.select", return_value=([], [], [])), \
         patch("click.echo"):
        session_mod._wait_for_tui_command("sess", "pr qa pr-001", tick_s=0.001)
    assert mock_dismiss.called
