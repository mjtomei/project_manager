"""Acceptance: collectors read the exact native session they launched.

Covers the stories the pm/transcripts indirection got wrong (pr-ec5bc84,
superseding #275):

* #241 — an obsolete review loop's late completion froze the newer loop's
  live ``review-<pr>-i1.jsonl`` and hid its NEEDS_WORK.  No alias exists any
  more: nothing can be frozen or retargeted.
* a fresh review loop after a sign-off return restarts at iteration 1 and
  never reads the earlier loop's iteration 1;
* concurrent PRs on the same run and iteration numbers stay apart;
* TUI restart: a pre-upgrade breadcrumb's in-flight iteration is adopted
  once, read-only, and the new breadcrumb round-trips the run;
* human follow-up in the existing pane reads the same session's later turns;
* a missing/pruned native log is no verdict and is never substituted;
* the CLI auto-sequence, impl tracking and watchers read their own sessions;
  pre-upgrade entries stay untouched.
"""

import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pm_core import session_log
from pm_core.session_log import SessionLaunch

PR = "pr-life"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


def _turn(text, kind="assistant"):
    return json.dumps({"type": kind, "message": {
        "role": kind, "content": [{"type": "text", "text": text}]}}) + "\n"


def _launch_review(tmp_path, pr_id, loop_id, iteration, *, run="run",
                   attempt=1):
    """A real ``build_claude_shell_cmd`` launch of a review attempt, as the
    ``pm pr review --session-id`` child performs it."""
    from pm_core.claude_launcher import build_claude_shell_cmd
    wd = tmp_path / f"wd-{pr_id}"
    wd.mkdir(exist_ok=True)
    sid = str(uuid.uuid4())
    build_claude_shell_cmd(
        prompt="review", session_id=sid, cwd=str(wd), session_type="review",
        launch=SessionLaunch(subject=pr_id, phase="review", run_id=run,
                             loop_id=loop_id, iteration=iteration,
                             attempt=attempt))
    log = Path(session_log.by_session(pr_id, sid).log)
    log.parent.mkdir(parents=True, exist_ok=True)
    return sid, log


def _pr(tmp_path, pr_id=PR):
    return {"id": pr_id, "workdir": str(tmp_path / f"wd-{pr_id}")}


def _discover(state, tmp_path, iteration, pr_id=PR):
    from pm_core import review_loop
    with patch.object(review_loop, "_get_pm_session", return_value=None):
        return review_loop._discover_iteration(
            state, _pr(tmp_path, pr_id), iteration, allow_recovery=True)


# --- #241 stale finalizer ------------------------------------------------------

def test_obsolete_loop_completion_cannot_freeze_or_retarget_newer_log(
        tmp_path):
    from pm_core.review_loop import ReviewLoopState
    from pm_core.tui import review_loop_ui
    root = tmp_path / "pm"
    old = ReviewLoopState(pr_id=PR, iteration=2, run_id="run")
    _, old_log = _launch_review(tmp_path, PR, old.loop_id, 2)
    old_log.write_text(_turn("Old code.\n\nNEEDS_WORK"))
    # Sign-off REVIEW return: a fresh loop restarts at iteration 1 while the
    # obsolete loop's thread is still winding down.
    new = ReviewLoopState(pr_id=PR, iteration=1, run_id="run",
                          iteration_attempted=True)
    sid, log = _launch_review(tmp_path, PR, new.loop_id, 1)
    log.write_text(_turn("go", "user") + _turn("Reviewing the diff..."))
    inode = log.stat().st_ino

    old.latest_verdict = "KILLED"
    review_loop_ui._on_complete_from_thread(None, old)   # late completion

    with log.open("a") as f:
        f.write(_turn("Two issues.\n\nNEEDS_WORK"))
    disc = _discover(new, tmp_path, 1)
    assert (disc.kind, disc.session_id) == ("verdict", sid)
    assert "Two issues" in disc.output
    assert log.stat().st_ino == inode and not log.is_symlink()
    assert not (root / "transcripts").exists()
    assert not list(tmp_path.rglob("review-*.jsonl"))


def test_fresh_loop_restarts_at_iteration_one_without_the_old_verdict(
        tmp_path):
    from pm_core.cli import pr as pr_mod
    from pm_core.review_loop import ReviewLoopState
    first = ReviewLoopState(pr_id=PR, run_id="run")
    a_sid, a_log = _launch_review(tmp_path, PR, first.loop_id, 1)
    a_log.write_text(_turn("Ship it.\n\nPASS"))
    fresh = ReviewLoopState(pr_id=PR, run_id="run", iteration_attempted=True)
    b_sid, b_log = _launch_review(tmp_path, PR, fresh.loop_id, 1)
    b_log.write_text(_turn("Reviewing the rework..."))

    disc = _discover(fresh, tmp_path, 1)
    assert disc.kind == "launch" and disc.output is None   # no PASS inherited
    b_log.write_text(b_log.read_text() + _turn("Regression.\n\nNEEDS_WORK"))
    disc = _discover(fresh, tmp_path, 1)
    assert (disc.kind, disc.session_id) == ("verdict", b_sid)

    # Both loops' iteration 1 stay discoverable with their own logs.
    with patch.object(pr_mod, "state_root", return_value=tmp_path), \
            patch.object(pr_mod.store, "load", return_value={"prs": []}):
        from click.testing import CliRunner
        out = CliRunner().invoke(pr_mod.pr_sessions, [PR]).output
    assert f"loop={first.loop_id} i1" in out and a_sid in out
    assert f"loop={fresh.loop_id} i1" in out and b_sid in out
    assert out.count("log[present]") == 2


def test_concurrent_prs_with_the_same_run_and_iterations_stay_apart(tmp_path):
    from pm_core.review_loop import ReviewLoopState
    x = ReviewLoopState(pr_id="pr-x", run_id="run", iteration_attempted=True)
    y = ReviewLoopState(pr_id="pr-y", run_id="run", iteration_attempted=True)
    y.loop_id = x.loop_id   # even a shared loop id cannot cross PRs
    x_sid, x_log = _launch_review(tmp_path, "pr-x", x.loop_id, 1)
    y_sid, y_log = _launch_review(tmp_path, "pr-y", y.loop_id, 1)
    x_log.write_text(_turn("PASS"))
    y_log.write_text(_turn("NEEDS_WORK"))
    dx = _discover(x, tmp_path, 1, "pr-x")
    dy = _discover(y, tmp_path, 1, "pr-y")
    assert (dx.session_id, "PASS" in dx.output) == (x_sid, True)
    assert (dy.session_id, "NEEDS_WORK" in dy.output) == (y_sid, True)


def test_missing_native_log_is_no_verdict_and_never_substituted(
        tmp_path, home):
    from pm_core.review_loop import ReviewLoopState
    state = ReviewLoopState(pr_id=PR, run_id="run", iteration_attempted=True)
    sid, log = _launch_review(tmp_path, PR, state.loop_id, 1)
    # Another session's log with a verdict sits in the same project dir.
    (log.parent / f"{uuid.uuid4()}.jsonl").write_text(_turn("PASS"))
    assert not log.exists()           # never written, or pruned by Claude
    disc = _discover(state, tmp_path, 1)
    assert disc.kind == "launch" and disc.output is None
    rec = session_log.by_session(PR, sid)
    assert session_log.log_state(rec) == "missing"
    assert sid in session_log.missing_message(rec)


# --- human follow-up -------------------------------------------------------------

def test_follow_up_reads_the_same_sessions_later_answer(tmp_path):
    from pm_core import hook_events, loop_shared, review_loop
    from pm_core.review_loop import ReviewLoopState
    state = ReviewLoopState(pr_id=PR, iteration=1, run_id="run")
    sid, log = _launch_review(tmp_path, PR, state.loop_id, 1)
    log.write_text(_turn("Which branch?\n\nINPUT_REQUIRED"))
    state.last_session_id = sid

    def human_answers(session_id, **kw):
        assert session_id == sid      # the exact session, nothing else
        with log.open("a") as f:
            f.write(_turn("main", "user") + _turn("Thanks.\n\nPASS"))
        return {"event_type": "idle_prompt", "timestamp": 9e9}

    with patch.object(review_loop, "_get_pm_session", return_value="pm-s"), \
            patch.object(loop_shared, "find_claude_pane", return_value="%1"), \
            patch.object(hook_events, "wait_for_event",
                         side_effect=human_answers), \
            patch.object(review_loop, "_LEASE_REFRESH_SECONDS", 1e9):
        out = review_loop._wait_for_follow_up_verdict(_pr(tmp_path), state)
    assert out and "PASS" in out


# --- TUI restart -------------------------------------------------------------------

def test_new_breadcrumb_round_trips_the_loop_run(tmp_path):
    from pm_core.tui import auto_start
    fields = auto_start._loop_record_fields(
        {"iteration": 2, "loop_id": "abcd1234", "run_id": "autostart-x"})
    assert (fields["run_id"], fields["legacy_transcript_dir"]) == \
        ("autostart-x", "")
    # A record without a loop id gets a full-width one (ledger key).
    assert len(auto_start._loop_record_fields({})["loop_id"]) == 8


def test_pre_upgrade_breadcrumb_adopts_its_in_flight_session_once(
        tmp_path, home):
    """A loop restored from a breadcrumb written by the old pm names its
    in-flight iteration only by its run-dir symlink: adopted once, read
    only; the legacy tree is left exactly as it was."""
    from pm_core import review_loop
    from pm_core.review_loop import ReviewLoopState
    from pm_core.tui import auto_start
    tdir = tmp_path / "pm" / "transcripts" / "autostart-old-1"
    tdir.mkdir(parents=True)
    sid = str(uuid.uuid4())
    native = home / ".claude" / "projects" / "-wd" / f"{sid}.jsonl"
    native.parent.mkdir(parents=True)
    native.write_text(_turn("Found it.\n\nNEEDS_WORK"))
    link = tdir / f"review-{PR}-i2.jsonl"
    link.symlink_to(native)
    before = (os.readlink(link), native.read_bytes())
    fields = auto_start._loop_record_fields({
        "iteration": 2, "loop_id": "ab12", "_transcript_dir": str(tdir),
        "iteration_attempted": True})
    assert fields["run_id"] == "autostart-old-1"
    state = ReviewLoopState(pr_id=PR, **fields)

    with patch.object(review_loop, "_get_pm_session", return_value=None):
        out = review_loop._adopt_in_flight_review(state, _pr(tmp_path))
        again = review_loop._adopt_in_flight_review(state, _pr(tmp_path))
    assert "NEEDS_WORK" in out and again == out
    (rec,) = session_log.find(PR, loop_id="ab12", iteration=2)
    assert (rec.session_id, rec.log, rec.legacy) == (sid, str(native),
                                                     str(link))
    assert (os.readlink(link), native.read_bytes()) == before


def test_pre_upgrade_link_of_an_earlier_run_is_not_adopted(tmp_path, home):
    """The saved ``stale_session_id`` names the link's session from before
    the loop attempted the iteration (an earlier run's): never adopted."""
    from pm_core import review_loop
    from pm_core.review_loop import ReviewLoopState
    tdir = tmp_path / "pm" / "transcripts" / "manual-1"
    tdir.mkdir(parents=True)
    sid = str(uuid.uuid4())
    (tmp_path / f"{sid}.jsonl").write_text(_turn("PASS"))
    (tdir / f"review-{PR}-i1.jsonl").symlink_to(tmp_path / f"{sid}.jsonl")
    state = ReviewLoopState(pr_id=PR, iteration=1, loop_id="cd34",
                            legacy_transcript_dir=str(tdir),
                            stale_session_id=sid, iteration_attempted=True)
    with patch.object(review_loop, "_get_pm_session", return_value=None):
        assert review_loop._adopt_in_flight_review(state, _pr(tmp_path)) \
            is None
    assert session_log.records(PR) == []


# --- CLI auto-sequence ---------------------------------------------------------------

def test_auto_sequence_reads_its_iteration_and_continues_legacy_numbering(
        tmp_path, home):
    from pm_core.cli import pr as pr_mod
    root = tmp_path / "pm"
    adir = root / "transcripts" / "auto-sequence" / PR
    adir.mkdir(parents=True)
    sid = str(uuid.uuid4())
    native = home / ".claude" / "projects" / "-wd" / f"{sid}.jsonl"
    native.parent.mkdir(parents=True)
    native.write_text(_turn("NEEDS_WORK"))
    (adir / f"review-{PR}-i3.jsonl").symlink_to(native)
    (adir / f"review-{PR}-i2.jsonl").write_text("")
    before = sorted(p.name for p in adir.iterdir())
    with patch.object(pr_mod, "state_root", return_value=root):
        assert pr_mod._check_review_verdict(PR) == ("NEEDS_WORK", 3)
        # The next tick launches iteration 4, which records itself.
        _, log4 = _launch_review(tmp_path, PR, "", 4, run="auto-sequence")
        log4.write_text(_turn("PASS"))
        assert pr_mod._check_review_verdict(PR) == ("PASS", 4)
    assert sorted(p.name for p in adir.iterdir()) == before
    assert os.readlink(adir / f"review-{PR}-i3.jsonl") == str(native)


# --- TUI impl tracking -----------------------------------------------------------------

def test_tui_tracks_an_impl_pane_launched_before_the_upgrade(tmp_path, home,
                                                             monkeypatch):
    """The TUI's run dir names the in-flight impl session (old pm); after the
    upgrade restart the pane is tracked by that exact session, read-only."""
    from pm_core.tui import review_loop_ui
    root = tmp_path / "pm"
    tdir = root / "transcripts" / "autostart-r"
    tdir.mkdir(parents=True)
    sid = str(uuid.uuid4())
    wd = tmp_path / "wd"
    native = home / ".claude" / "projects" / "-wd" / f"{sid}.jsonl"
    (tdir / f"impl-{PR}.jsonl").symlink_to(native)
    monkeypatch.setattr("pm_core.tmux.pane_start_command",
                        lambda p: f"claude --session-id {sid}")
    monkeypatch.setattr(review_loop_ui, "_find_impl_pane",
                        lambda session, name: "%5")
    tracker = MagicMock()
    tracker.is_tracked.return_value = False
    tracker.became_idle.return_value = False
    pr = {"id": PR, "status": "in_progress", "workdir": str(wd)}
    app = SimpleNamespace(
        _session_name="sess", _pane_idle_tracker=tracker,
        _data={"prs": [pr]}, _review_loops={}, _pending_merge_prs=set(),
        _root=root, _auto_start_run_id="autostart-r",
        log_message=lambda *a, **k: None)
    with patch("pm_core.tui.auto_start.is_enabled", return_value=False):
        review_loop_ui._poll_impl_idle(app)
    tracker.register.assert_called_once_with(PR, "%5", str(native))
    (rec,) = session_log.records(PR)
    assert (rec.phase, rec.run_id, rec.session_id) == ("impl", "autostart-r",
                                                       sid)
    assert os.readlink(tdir / f"impl-{PR}.jsonl") == str(native)


# --- watchers --------------------------------------------------------------------------

def test_watcher_iteration_polls_its_own_session(tmp_path):
    from pm_core.watchers.auto_start_watcher import AutoStartWatcher
    w = AutoStartWatcher(str(tmp_path))
    w.state.run_id = "watcher-1"
    seen = {}

    def child(cmd, **kw):
        # ``pm watcher --iteration`` records the session it was handed.
        sid = cmd[cmd.index("--session-id") + 1]
        session_log.register(
            SessionLaunch(subject=w.ledger_subject, phase="watcher",
                          run_id=cmd[cmd.index("--run-id") + 1],
                          iteration=int(cmd[cmd.index("--iteration") + 1])),
            sid, str(tmp_path))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def poll(pane_id, transcript, **kw):
        seen["transcript"] = transcript
        return "READY"

    with patch("pm_core.watcher_base.get_pm_session", return_value="pm-s"), \
            patch("pm_core.tmux.session_exists", return_value=True), \
            patch("pm_core.watcher_base.subprocess.run", side_effect=child), \
            patch("pm_core.watcher_base.time.sleep"), \
            patch("pm_core.watcher_base.find_claude_pane", return_value="%3"), \
            patch.object(w, "_poll_for_verdict", side_effect=poll):
        assert w._run_iteration(1) == "READY"
    rec = session_log.by_session(w.ledger_subject, w.state.session_id)
    assert (rec.run_id, rec.iteration) == ("watcher-1", 1)
    assert seen["transcript"] == str(session_log.log_path(rec))


# --- QA scenario worker ------------------------------------------------------------------

def test_qa_scenario_worker_records_its_session(tmp_path):
    from pm_core import qa_loop
    sc = qa_loop.QAScenario(index=3, title="t", focus="f", steps="s")
    sc.worktree_path = str(tmp_path / "clone")
    state = qa_loop.QALoopState(pr_id=PR, qa_workdir=str(tmp_path),
                                loop_id="qa-loop-1")
    sid = str(uuid.uuid4())
    with patch("pm_core.paths.fake_claude_config_for_type", return_value=None), \
            patch("pm_core.claude_launcher.prepare_workspace"), \
            patch("pm_core.qa_loop._write_scenario_capture_file"), \
            patch("pm_core.prompt_gen.generate_qa_child_prompt",
                  return_value="p"):
        qa_loop._build_scenario_run_cmd(
            sc, state, {"project": {}}, sid,
            qa_loop._resolve_qa_model({}, {"project": {}}, "qa_scenario"),
            session="sess", workdir_path=str(tmp_path))
    rec = session_log.by_session(PR, sid)
    assert (rec.phase, rec.loop_id, rec.iteration) == ("qa", "qa-loop-1", 3)
    assert rec.log == qa_loop._scenario_log_path(sc, str(tmp_path), sid)
    assert not list(tmp_path.glob("transcript-s*.jsonl"))
