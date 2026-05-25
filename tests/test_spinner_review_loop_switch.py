"""Regression tests for pr-8409c64: the review-loop popup spinner must switch
focus to the review window even when the popup process's cwd points at a
*different* pm project than the one that owns the PR.

Root cause: ``_wait_for_tui_command`` resolved the PR's ``display_id`` via
``state_root()`` (cwd-/``_project_override``-based). When the popup runs from
a window whose cwd isn't the PR's project, ``state_root()`` loads the wrong
``project.yaml``, the ``pr_id`` isn't found, ``display_id`` stays ``None`` and
``target_window`` becomes ``None`` — so ``_find_target_window_ids()`` returns
``[]`` forever, ``window_open`` is never ``True`` and the spinner never fires
``select_window`` (it spins on the "starting" frame).

The fix resolves the root from the session (``_resolve_root_from_session``,
matching the popup picker's own listing) before falling back to
``state_root()``.
"""

import sys
import termios
from unittest.mock import MagicMock, patch

import pytest

from pm_core.cli import session as session_mod


@pytest.fixture
def fake_stdin(monkeypatch):
    """stdin whose fileno() works but tcgetattr fails → cbreak path no-ops."""
    fake = MagicMock()
    fake.fileno.return_value = 0
    fake.read.return_value = ""
    monkeypatch.setattr(sys, "stdin", fake)
    monkeypatch.setattr(termios, "tcgetattr",
                        MagicMock(side_effect=termios.error("not a tty")))


# Project that OWNS the PR (the session-resolved root).
_OWNER_ROOT = "/owner/pm"
_OWNER_DATA = {"prs": [{"id": "pr-001", "title": "x"}]}  # no gh → display_id pr-001
# Foreign project the popup's cwd happens to point at (state_root()).
_FOREIGN_ROOT = "/foreign/pm"
_FOREIGN_DATA = {"prs": []}  # pr-001 absent → display_id would be None


def _load(root):
    return _OWNER_DATA if str(root) == _OWNER_ROOT else _FOREIGN_DATA


def _run_spinner(window_seq, state_seq):
    """Drive _wait_for_tui_command with simulated tmux + runtime_state.

    Simulates the bug condition: state_root() resolves to a FOREIGN project
    (no PR), while the session resolves to the OWNER project (has PR).
    Returns the fake select_window mock.
    """
    wq = list(window_seq)
    sq = list(state_seq)

    def list_windows(_sess):
        v = wq.pop(0) if len(wq) > 1 else wq[0]
        return [{"name": n, "id": i} for (n, i) in v]

    def get_state(_pr, _action):
        return sq.pop(0) if len(sq) > 1 else sq[0]

    fake_tmux = MagicMock()
    fake_tmux.list_windows.side_effect = list_windows
    fake_tmux.select_window = MagicMock(return_value=True)

    with patch.object(session_mod, "tmux_mod", fake_tmux), \
         patch.object(session_mod, "state_root", return_value=_FOREIGN_ROOT), \
         patch.object(session_mod, "_resolve_root_from_session",
                      return_value=_OWNER_ROOT), \
         patch.object(session_mod.store, "load", side_effect=_load), \
         patch("pm_core.runtime_state.get_action_state", side_effect=get_state), \
         patch("pm_core.runtime_state.consume_suppress_switch",
               return_value=False), \
         patch.object(session_mod, "_wait_dismiss"), \
         patch("select.select", return_value=([], [], [])), \
         patch("click.echo"):
        try:
            session_mod._wait_for_tui_command(
                "pm-sess", "review-loop start pr-001", tick_s=0.0001)
        except SystemExit:
            pass
    return fake_tmux.select_window


def test_switch_fires_for_new_window(fake_stdin):
    """No review window open → window appears → spinner switches to it.

    On pre-fix code display_id resolves to None (foreign state_root()), so
    target_window is None, window_open never True and select_window is never
    called; the runtime_state reaching 'done' makes the spinner exit via the
    terminal short-circuit *without switching*. This assertion then fails.
    """
    W = "review-pr-001"
    select_window = _run_spinner(
        # snapshot: no window; then the freshly launched window appears and
        # stays (post-fix switches here). A trailing 'done' bounds the
        # pre-fix loop (which never matches the window) via the
        # terminal-state short-circuit.
        window_seq=[[], [(W, "@9")], [(W, "@9")]],
        state_seq=[{"state": "running", "updated_at": "t0"},
                   {"state": "running", "updated_at": "t1"},
                   {"state": "done", "verdict": "PASS", "updated_at": "t2"}],
    )
    assert select_window.called, "spinner should switch to the new review window"
    assert select_window.call_args.args == ("pm-sess", W)


def test_switch_fires_for_existing_window_fresh(fake_stdin):
    """Review window already open → killed + recreated → spinner switches.

    Mirrors the running/terminal-loop supersede case: an existing
    ``review-pr-001`` (@5) is replaced by a new id (@9). The fresh-mode
    logic waits for the old id to go and a new id to appear, then switches.
    """
    W = "review-pr-001"
    select_window = _run_spinner(
        # snapshot sees @5; then it's killed; then @9 appears and stays
        # (post-fix switches here). State stays 'running' until after @9 is
        # up, then 'done' bounds the pre-fix loop.
        window_seq=[[(W, "@5")], [(W, "@5")], [], [(W, "@9")], [(W, "@9")]],
        state_seq=[{"state": "running", "updated_at": "t0"},
                   {"state": "running", "updated_at": "t1"},
                   {"state": "running", "updated_at": "t2"},
                   {"state": "running", "updated_at": "t3"},
                   {"state": "done", "verdict": "PASS", "updated_at": "t4"}],
    )
    assert select_window.called, "spinner should switch to the rebuilt window"
    assert select_window.call_args.args == ("pm-sess", W)
