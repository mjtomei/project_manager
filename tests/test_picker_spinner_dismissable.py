"""Regression tests for pr-23d97f8: the popup spinner must exit cleanly
when input handling is unavailable (cbreak setup failed on a real tty)
and when per-tick tmux/runtime_state calls block consistently.

Without these guards the spinner used to keep ticking after q/Esc became
unreadable per-character, leaving the popup stuck on top of the affected
tmux window with no dismissal path."""

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
def real_tty_stdin(monkeypatch):
    """sys.stdin reports isatty()==True but tcgetattr raises.  Mirrors
    the production failure mode: we're in a real terminal popup but
    something in the parent shell's termios state breaks our cbreak
    setup, so per-character q/Esc reads silently won't work."""
    fake = MagicMock()
    fake.fileno.return_value = 0
    fake.read.return_value = ""
    fake.isatty.return_value = True
    monkeypatch.setattr(sys, "stdin", fake)
    monkeypatch.setattr(termios, "tcgetattr",
                        MagicMock(side_effect=termios.error("eio")))


def test_spinner_exits_when_cbreak_fails_on_real_tty(real_tty_stdin):
    """If cbreak setup fails *and* stdin is a real tty, the spinner
    cannot honor q/Esc — it must exit immediately rather than spin
    unresponsively until the queued command finishes."""
    fake_tmux = MagicMock(list_windows=MagicMock(return_value=[]),
                          select_window=MagicMock())
    fake_rs = MagicMock()
    fake_rs.get_action_state.return_value = {"state": "running"}
    fake_rs.request_suppress_switch = MagicMock()
    with patch.object(session_mod, "tmux_mod", fake_tmux), \
         patch.object(session_mod.store, "load", return_value={"prs": []}), \
         patch.object(session_mod, "state_root", return_value="/tmp"), \
         patch("pm_core.runtime_state.get_action_state",
               return_value={"state": "running"}), \
         patch("pm_core.runtime_state.request_suppress_switch") as mock_supp, \
         patch("click.echo"):
        # No SystemExit, no infinite loop — early return.
        session_mod._wait_for_tui_command("sess", "review-loop pr-001",
                                          tick_s=0.001)
    # The early-exit path requests suppress_switch so the eventual
    # completion doesn't yank focus from under the user.
    assert mock_supp.called


def test_spinner_watchdog_exits_on_persistently_slow_ticks(monkeypatch):
    """If tmux + runtime_state calls block past the threshold for N
    consecutive ticks, the spinner exits with a backend-unresponsive
    message rather than continuing to block keypress handling."""
    # Use the cbreak-failing-but-not-tty fixture so we stay in the loop.
    fake = MagicMock()
    fake.fileno.return_value = 0
    fake.read.return_value = ""
    fake.isatty.return_value = False  # tests aren't a tty → loop continues
    monkeypatch.setattr(sys, "stdin", fake)
    monkeypatch.setattr(termios, "tcgetattr",
                        MagicMock(side_effect=termios.error("not a tty")))

    fake_tmux = MagicMock(list_windows=MagicMock(return_value=[]),
                          select_window=MagicMock())

    # Drive monotonic() so each tick appears to take >1.0s.  The
    # spinner samples it twice per tick (start, then after the blocking
    # calls).  After WATCHDOG_LIMIT (=5) consecutive slow ticks, exit.
    times = iter([float(i) * 2.0 for i in range(200)])

    with patch("time.monotonic", side_effect=lambda: next(times)), \
         patch.object(session_mod, "tmux_mod", fake_tmux), \
         patch.object(session_mod.store, "load", return_value={"prs": []}), \
         patch.object(session_mod, "state_root", return_value="/tmp"), \
         patch("pm_core.runtime_state.get_action_state",
               return_value={"state": "running"}), \
         patch("pm_core.runtime_state.request_suppress_switch") as mock_supp, \
         patch("select.select", return_value=([], [], [])), \
         patch("click.echo"):
        # Watchdog must trip and return without raising.
        session_mod._wait_for_tui_command("sess", "review-loop pr-001",
                                          tick_s=0.001)
    assert mock_supp.called
