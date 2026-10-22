"""Regression tests for pr-8409c64: the popup spinner must recognise the
action's window — and, for review-loop, switch focus to it — even when the
popup process's cwd points at a *different* pm project than the one that owns
the PR (e.g. another PR's workdir clone, whose project.yaml is a stale branch
copy).

Root cause: ``_wait_for_tui_command`` resolved the PR's ``display_id`` via
``state_root()`` (cwd-/``_project_override``-based). When the popup runs from
a window whose cwd isn't the PR's project, ``state_root()`` loads the wrong
``project.yaml``, the ``pr_id`` isn't found, ``display_id`` stays ``None`` and
``target_window`` becomes ``None`` — so ``_find_target_window_ids()`` returns
``[]`` forever, ``window_open`` is never ``True`` and the spinner never fires
``select_window`` (it spins on the "starting" frame).

For QA (``t`` in the picker) the same miss shows up differently: the TUI's QA
launch performs the focus switch itself, so the client *does* move to the QA
window, but the spinner never recognises that window and holds the popup open
over it until the QA run reaches a terminal state.

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


_MAX_TICKS = 500


def _load(root):
    return _OWNER_DATA if str(root) == _OWNER_ROOT else _FOREIGN_DATA


def _run_spinner(window_seq, state_seq,
                 tui_cmd="review-loop start pr-001",
                 client_session=None, client_attached=True, tmux=None,
                 launch_probe=lambda _session, _pr: False):
    """Drive _wait_for_tui_command with simulated tmux + runtime_state.

    Simulates the bug condition: state_root() resolves to a FOREIGN project
    (no PR), while the session resolves to the OWNER project (has PR).
    Returns (select_window mock, echoed lines, consume_suppress_switch mock).
    """
    wq = list(window_seq)
    sq = list(state_seq)

    def list_windows(_sess):
        v = wq.pop(0) if len(wq) > 1 else wq[0]
        return [{"name": n, "id": i} for (n, i) in v]

    ticks = {"n": 0}

    def get_state(_pr, _action):
        # The spinner reads the runtime state once per tick, whether or not
        # it resolved a target window.  Cap the ticks so a regression (e.g.
        # target_window back to None with a 'running' state) fails instead
        # of spinning forever.
        ticks["n"] += 1
        if ticks["n"] > _MAX_TICKS:
            raise AssertionError(
                f"spinner still polling after {_MAX_TICKS} ticks")
        return sq.pop(0) if len(sq) > 1 else sq[0]

    fake_tmux = tmux if tmux is not None else MagicMock()
    fake_tmux.list_windows.side_effect = list_windows
    fake_tmux.select_window = MagicMock(return_value=True)
    fake_tmux.select_window_in_session = MagicMock(return_value=True)
    fake_tmux.session_has_clients = MagicMock(return_value=client_attached)
    echoed: list[str] = []

    with patch.object(session_mod, "tmux_mod", fake_tmux), \
         patch.object(session_mod, "state_root", return_value=_FOREIGN_ROOT), \
         patch.object(session_mod, "_resolve_root_from_session",
                      return_value=_OWNER_ROOT), \
         patch.object(session_mod.store, "load", side_effect=_load), \
         patch("pm_core.runtime_state.get_action_state", side_effect=get_state), \
         patch("pm_core.runtime_state.consume_suppress_switch",
               return_value=True) as consume, \
         patch.object(session_mod, "_review_launch_in_progress",
                      side_effect=launch_probe), \
         patch.object(session_mod, "_wait_dismiss"), \
         patch("select.select", return_value=([], [], [])), \
         patch("click.echo",
               side_effect=lambda msg="", **_kw: echoed.append(str(msg))):
        try:
            session_mod._wait_for_tui_command(
                "pm-sess", tui_cmd, tick_s=0.0001,
                client_session=client_session)
        except SystemExit:
            pass
    return fake_tmux.select_window, echoed, consume


def test_switch_fires_for_new_window(fake_stdin):
    """No review window open → window appears → spinner switches to it.

    On pre-fix code display_id resolves to None (foreign state_root()), so
    target_window is None, window_open never True and select_window is never
    called; the runtime_state reaching 'done' makes the spinner exit via the
    terminal short-circuit *without switching*. This assertion then fails.
    """
    W = "review-pr-001"
    select_window, _, _ = _run_spinner(
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
    select_window, _, _ = _run_spinner(
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


def test_stale_suppress_flag_does_not_swallow_switch(fake_stdin):
    """A q/Esc on an earlier review-loop popup used to leave
    ``suppress_switch`` on the runtime entry, and a running→running restart
    keeps it.  The next, non-dismissed ``zz d`` must still switch — reaching
    window_open means this popup was not dismissed (QA s18 story 3).
    """
    W = "review-pr-001"
    select_window, echoed, consume = _run_spinner(
        window_seq=[[(W, "@5")], [], [(W, "@9")], [(W, "@9")]],
        state_seq=[{"state": "running", "suppress_switch": True,
                    "updated_at": "t0"},
                   {"state": "running", "updated_at": "t1"}],
    )
    assert select_window.called, "stale suppress flag swallowed the switch"
    assert select_window.call_args.args == ("pm-sess", W)
    assert _exited_on_window(echoed, W), echoed
    # The flag belongs to the TUI's QA launch; the spinner never reads it
    # for review-loop (the patched consume would report it set).
    assert not consume.called


def _exited_on_window(echoed, window):
    return any(f"window {window} is open" in line for line in echoed)


def test_qa_spinner_dismisses_when_new_qa_window_opens(fake_stdin):
    """``t`` from another window, no QA window yet → QA window appears →
    the spinner exits (popup closes) while the run is still going.

    Pre-fix the spinner never matched ``qa-pr-001`` and only exited once the
    run reached 'done' — i.e. the popup stayed over the QA window for the
    whole run.
    """
    W = "qa-pr-001"
    select_window, echoed, _ = _run_spinner(
        window_seq=[[], [(W, "@9")], [(W, "@9")]],
        state_seq=[{"state": "launching", "updated_at": "t0"},
                   {"state": "running", "updated_at": "t1"},
                   {"state": "done", "verdict": "PASS", "updated_at": "t2"}],
        tui_cmd="pr qa pr-001",
    )
    assert _exited_on_window(echoed, W), echoed
    assert not any("qa: done" in line for line in echoed), echoed
    # The TUI's QA launch owns the focus switch for qa; the spinner must
    # not issue a second one.
    assert not select_window.called


def test_qa_spinner_dismisses_for_existing_qa_window(fake_stdin):
    """``t`` with a QA run already open (main + scenario windows) → the
    spinner exits immediately instead of waiting for the run to finish."""
    select_window, echoed, _ = _run_spinner(
        window_seq=[[("qa-pr-001", "@5"), ("qa-pr-001-s1", "@6")]],
        state_seq=[{"state": "running", "updated_at": "t0"},
                   {"state": "done", "verdict": "PASS", "updated_at": "t1"}],
        tui_cmd="pr qa pr-001",
    )
    assert _exited_on_window(echoed, "qa-pr-001"), echoed
    assert not any("qa: done" in line for line in echoed), echoed
    assert not select_window.called


def test_switch_targets_the_popup_client_session(fake_stdin):
    """Two clients attached (pm-sess~1, pm-sess~2): the spinner in ~2's popup
    must switch ~2, not whichever client typed last.

    A popup has no $TMUX_PANE, so ``select_window``'s current-session lookup
    resolves to the most recently active client; with both users typing the
    chord, both popups switched the same client and the other was left on
    its old window (QA scenario 19).
    """
    W = "review-pr-001"
    fake_tmux = MagicMock()
    select_window, _, _ = _run_spinner(
        window_seq=[[], [(W, "@9")], [(W, "@9")]],
        state_seq=[{"state": "running", "updated_at": "t0"},
                   {"state": "running", "updated_at": "t1"},
                   {"state": "done", "verdict": "PASS", "updated_at": "t2"}],
        client_session="pm-sess~2", tmux=fake_tmux,
    )
    assert not select_window.called
    assert fake_tmux.select_window_in_session.call_args.args == (
        "pm-sess~2", W)


def test_switch_falls_back_when_popup_session_unattached(fake_stdin):
    """A picker run in an unattached session (e.g. headless in the base
    session) keeps the old attached-session lookup."""
    W = "review-pr-001"
    fake_tmux = MagicMock()
    select_window, _, _ = _run_spinner(
        window_seq=[[], [(W, "@9")], [(W, "@9")]],
        state_seq=[{"state": "running", "updated_at": "t0"},
                   {"state": "running", "updated_at": "t1"},
                   {"state": "done", "verdict": "PASS", "updated_at": "t2"}],
        client_session="pm-sess", client_attached=False, tmux=fake_tmux,
    )
    assert select_window.call_args.args == ("pm-sess", W)
    assert not fake_tmux.select_window_in_session.called


def test_review_loop_switch_waits_for_inflight_launch(fake_stdin):
    """A review window that appears while another launch still holds the
    PR's launch lock is about to be superseded (killed + recreated by the
    queued launch); the spinner must not switch to it until the lock clears.

    QA scenario 19 story 4: switching early selected the doomed window after
    the second launch had snapshotted its sessions, so the client was bounced
    back to its old window when the doomed window was killed.
    """
    W = "review-pr-001"
    busy = [True, True, True, False]
    fake_tmux = MagicMock()

    def probe(_session, _pr):
        return busy.pop(0) if len(busy) > 1 else busy[0]

    _run_spinner(
        window_seq=[[(W, "@5")], [(W, "@5")], [], [(W, "@6")],
                    [(W, "@6")]],
        state_seq=[{"state": "running", "updated_at": "t0"}],
        client_session="pm-sess~1", tmux=fake_tmux, launch_probe=probe,
    )
    # Every busy probe was consumed before the single switch fired.
    assert busy == [False]
    assert fake_tmux.select_window_in_session.call_count == 1


def _dismiss_with_q(tui_cmd):
    """Run the spinner until a 'q' keypress; return request_suppress mock."""
    sys.stdin.read.return_value = "q"
    fake_tmux = MagicMock()
    fake_tmux.list_windows.return_value = []
    with patch.object(session_mod, "tmux_mod", fake_tmux), \
         patch.object(session_mod, "_session_project_root",
                      return_value=_OWNER_ROOT), \
         patch.object(session_mod.store, "load", side_effect=_load), \
         patch("pm_core.runtime_state.get_action_state",
               return_value={"state": "running"}), \
         patch("pm_core.runtime_state.request_suppress_switch") as req, \
         patch("select.select", return_value=([sys.stdin], [], [])), \
         patch("click.echo"):
        with pytest.raises(SystemExit):
            session_mod._wait_for_tui_command("pm-sess", tui_cmd,
                                              tick_s=0.0001)
    return req


def test_dismissed_review_loop_leaves_no_suppress_flag(fake_stdin):
    """review-loop is switched only by the spinner, so q/Esc just exits; a
    flag would have no consumer and would linger on the entry."""
    assert not _dismiss_with_q("review-loop start pr-001").called


def test_dismissed_qa_requests_suppress_switch(fake_stdin):
    """The TUI's QA launch switches focus itself, so q/Esc must tell it not
    to."""
    req = _dismiss_with_q("pr qa pr-001")
    assert req.call_args.args == ("pr-001", "qa")
