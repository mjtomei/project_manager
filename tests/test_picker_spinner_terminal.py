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
    fake_tmux = MagicMock(list_windows=MagicMock(return_value=[]),
                          select_window=MagicMock())
    with patch.object(session_mod, "tmux_mod", fake_tmux), \
         patch.object(session_mod.store, "load", return_value={"prs": []}), \
         patch.object(session_mod, "state_root", return_value="/tmp"), \
         patch("pm_core.runtime_state.get_action_state", return_value=entry), \
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
