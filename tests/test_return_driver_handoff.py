"""TUI and ``pm pr auto-sequence`` ticks hand a sign-off return's session to
each other instead of replacing it (QA S79, pr-592e4bd).

* A tick launched the REVIEW return's review; the TUI restarted right after
  and, having no loop for the PR, started one whose ``--fresh`` launch
  killed that review 0.6 s later.  The TUI now adopts the live window.
* The TUI relaunched an IMPL return; the next tick judged the new impl pane
  by its own ``impl-<pr>.jsonl`` symlink — an earlier, idle session — and
  moved the PR to review 1.2 s into the rework.  Both drivers now judge a
  pane only by the session it runs.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pm_core import store
from pm_core.claude_launcher import pane_runs_transcript, transcript_path_for

PR = "pr-s79"
SID_OLD = "11111111-2222-4333-8444-555555555555"
SID_NEW = "66666666-7777-4888-9999-aaaaaaaaaaaa"


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-cfg"))
    return h


def _pane_cmds(monkeypatch, cmds: dict):
    monkeypatch.setattr("pm_core.tmux.pane_start_command",
                        lambda pane: cmds.get(pane, ""))


def _launch_cmd(wd, sid):
    return f'"cd {wd} && claude --session-id {sid} \\"x\\""'


def _link(path: Path, wd, sid) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(transcript_path_for(str(wd), sid))
    return path


def test_pane_runs_transcript(home, tmp_path, monkeypatch):
    wd = tmp_path / "wd"
    _pane_cmds(monkeypatch, {"%1": _launch_cmd(wd, SID_NEW), "%2": "bash"})
    link = _link(tmp_path / "run" / f"impl-{PR}.jsonl", wd, SID_OLD)
    assert pane_runs_transcript("%1", str(wd), link) is False
    link.unlink()
    _link(link, wd, SID_NEW)
    assert pane_runs_transcript("%1", str(wd), link) is True
    # No session id in the pane's command: nothing to check against.
    assert pane_runs_transcript("%2", str(wd), link) is True


# --- tick: impl idle -------------------------------------------------------

@pytest.mark.parametrize("pane_sid,judged", [(SID_OLD, True), (SID_NEW, False)])
def test_tick_judges_impl_pane_only_by_its_own_session(
        home, tmp_path, monkeypatch, pane_sid, judged):
    """The tick's symlink names an earlier (idle) session; a pane another
    driver launched since must not be judged idle from it."""
    from pm_core.cli import pr as pr_mod
    wd = tmp_path / "wd"
    tdir = tmp_path / "auto-sequence"
    _link(tdir / f"impl-{PR}.jsonl", wd, SID_OLD)
    old = transcript_path_for(str(wd), SID_OLD)
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("{}\n")
    _pane_cmds(monkeypatch, {"%5": _launch_cmd(wd, pane_sid)})
    tracker = MagicMock()
    tracker.is_idle.return_value = True
    tracker.is_gone.return_value = False
    with patch.object(pr_mod, "_impl_window_pane", return_value="%5"), \
            patch("pm_core.pane_idle.PaneIdleTracker", return_value=tracker):
        idle, gone = pr_mod._check_impl_idle(
            "sess", {"id": PR, "workdir": str(wd)}, tdir)
    assert (idle, gone) == (judged, False)
    assert tracker.register.called is judged


# --- TUI: impl idle --------------------------------------------------------

@pytest.mark.parametrize("pane_sid,registered", [(SID_OLD, True),
                                                 (SID_NEW, False)])
def test_tui_tracks_impl_pane_only_by_its_own_session(
        home, tmp_path, monkeypatch, pane_sid, registered):
    """The TUI's run-dir symlink names its earlier session; a pane a tick
    relaunched since is left untracked (trust-watched only) instead of
    being judged idle from that session."""
    from types import SimpleNamespace
    from pm_core.tui import review_loop_ui
    wd = tmp_path / "wd"
    run = tmp_path / "run"
    _link(run / f"impl-{PR}.jsonl", wd, SID_OLD)
    _pane_cmds(monkeypatch, {"%5": _launch_cmd(wd, pane_sid)})
    monkeypatch.setattr(review_loop_ui, "_find_impl_pane",
                        lambda session, name: "%5" if name == PR else None)
    watched = []
    monkeypatch.setattr(review_loop_ui, "_watch_untracked_trust",
                        lambda app, pane, wdir, seen: watched.append(pane))
    tracker = MagicMock()
    tracker.is_tracked.return_value = False
    tracker.became_idle.return_value = False
    pr = {"id": PR, "status": "in_progress", "workdir": str(wd)}
    app = SimpleNamespace(
        _session_name="sess", _pane_idle_tracker=tracker,
        _data={"prs": [pr]}, _review_loops={}, _pending_merge_prs=set(),
        _root=tmp_path / "pm", _auto_start_run_id=None,
        log_message=lambda *a, **k: None)
    with patch("pm_core.tui.auto_start.get_transcript_dir", return_value=run), \
            patch("pm_core.tui.auto_start.is_enabled", return_value=False):
        review_loop_ui._poll_impl_idle(app)
    assert tracker.register.called is registered
    assert watched == ([] if registered else ["%5"])


# --- TUI: adopt a launched REVIEW return ------------------------------------

def _review_return(wd, *, awaiting=None, age_s=10):
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_s)).isoformat()
    return {"id": PR, "title": "T", "branch": "b", "status": "in_review",
            "workdir": str(wd), "depends_on": [],
            "signoff_return": {"verdict": "SIGNOFF_REVIEW", "hop": "review",
                               "awaiting": awaiting, "ts": ts}}


def _review_app(tmp_path, pr):
    from pm_core import autostart_state as st
    from tests.test_autostart_multi_target import FakeApp
    app = FakeApp([pr], root=tmp_path)
    app._auto_start = True
    app._auto_start_targets = {PR: st.make_target_record("t")}
    app._auto_start_run_id = "run"
    app._session_name = "sess"
    store.save(app._data, tmp_path)
    return app


def _run_review_pass(app, pr, run, pane="%7"):
    from pm_core.tui import auto_start
    with patch("pm_core.tui.review_loop_ui._start_loop") as start, \
            patch("pm_core.review_loop._find_claude_pane",
                  return_value=pane), \
            patch.object(auto_start, "get_transcript_dir", return_value=run):
        auto_start._auto_start_review_loops(app, [pr])
    return start


def test_tui_adopts_the_review_a_tick_launched_for_the_return(
        home, tmp_path, monkeypatch):
    """awaiting cleared by the tick's launch moments ago (its session has
    not written a transcript yet): the restarted TUI polls that window as
    iteration 1 of a resumed loop, with no --fresh launch."""
    wd = tmp_path / "wd"
    run = tmp_path / "run"
    pr = _review_return(wd)
    app = _review_app(tmp_path, pr)
    _pane_cmds(monkeypatch, {"%7": _launch_cmd(wd, SID_NEW)})
    start = _run_review_pass(app, pr, run)
    start.assert_called_once()
    state = start.call_args.kwargs["resume_state"]
    assert (state.iteration, state.history) == (1, [])
    link = run / f"review-{PR}-i1.jsonl"
    assert Path(os.readlink(link)) == transcript_path_for(str(wd), SID_NEW)


def test_tui_adopts_a_review_active_since_the_return(
        home, tmp_path, monkeypatch):
    """The 185 s re-check after a skipped claim: the tick's review has been
    running (and writing) since the return."""
    wd = tmp_path / "wd"
    pr = _review_return(wd, age_s=200)
    app = _review_app(tmp_path, pr)
    t = transcript_path_for(str(wd), SID_NEW)
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text("{}\n")
    _pane_cmds(monkeypatch, {"%7": _launch_cmd(wd, SID_NEW)})
    start = _run_review_pass(app, pr, tmp_path / "run")
    assert start.call_args.kwargs["resume_state"].iteration == 1


def test_tui_does_not_adopt_a_review_older_than_the_return(
        home, tmp_path, monkeypatch):
    """A window idle since before the return reviewed the code sign-off
    sent back: start a fresh loop as before."""
    wd = tmp_path / "wd"
    pr = _review_return(wd, age_s=10)
    app = _review_app(tmp_path, pr)
    t = transcript_path_for(str(wd), SID_OLD)
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text("{}\n")
    past = time.time() - 60
    os.utime(t, (past, past))
    _pane_cmds(monkeypatch, {"%7": _launch_cmd(wd, SID_OLD)})
    start = _run_review_pass(app, pr, tmp_path / "run")
    start.assert_called_once()
    assert start.call_args.kwargs.get("resume_state") is None
    assert not (tmp_path / "run" / f"review-{PR}-i1.jsonl").exists()


@pytest.mark.parametrize("case", ["no-window", "no-return", "awaiting"])
def test_tui_starts_a_fresh_loop_when_nothing_to_adopt(
        home, tmp_path, monkeypatch, case):
    wd = tmp_path / "wd"
    pr = _review_return(wd)
    if case == "no-return":
        pr.pop("signoff_return")
    app = _review_app(tmp_path, pr)
    if case == "awaiting":
        # Unclaimed and still awaiting: the TUI takes the claim and
        # launches (test_signoff_integration covers the claim itself).
        pr["signoff_return"]["awaiting"] = "review"
        store.save(app._data, tmp_path)
    _pane_cmds(monkeypatch, {"%7": _launch_cmd(wd, SID_NEW)})
    start = _run_review_pass(app, pr, tmp_path / "run",
                             pane=None if case == "no-window" else "%7")
    start.assert_called_once()
    assert start.call_args.kwargs.get("resume_state") is None
