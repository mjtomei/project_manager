"""Durable owed-REQA recovery (pr-db3bf10).

A sign-off ``SIGNOFF_REQA`` bounce leaves ``signoff_return.awaiting == "qa"``
on a PR that is back at ``qa``: an owed **full** QA re-run.  The start used to
live only in one TUI process's memory (or behind the global auto-start
switch), so a restart — or a deferral behind a ``pm qa run`` another process
drives — lost it and the PR sat at ``qa`` with ``awaiting: qa`` on disk until
someone pressed ``t``.

The contract exercised here:

* the obligation is the persisted return record, not a bare ``qa`` status;
* a TUI reconciles it on its poll tick / at mount, **independently of the
  auto-start switch and of auto-start targets**;
* a run another live process drives is waited out (``run_driven_elsewhere``),
  never started over;
* one owner: the on-disk launch claim makes repeated restarts, ticks and
  concurrent TUIs start the owed run exactly once.
"""

import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pm_core import qa_loop, signoff, store
from pm_core.tui import qa_loop_ui

PR = "pr-aaa1111"
OTHER = "pr-bbb2222"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class _Tracker:
    """Minimal stand-in for the TUI pane idle tracker (unused here)."""

    def is_tracked(self, key):
        return False

    def is_gone(self, key):
        return True

    def register(self, *a, **kw):
        pass

    def poll(self, key):
        pass

    def unregister(self, key):
        pass


class App:
    """Plain stand-in for the TUI app: real project.yaml, no Textual."""

    def __init__(self, root, *, autostart=False, targets=()):
        self._root = root
        self._data = store.load(root)
        self._auto_start = autostart
        self._auto_start_targets = {t: {} for t in targets}
        self._auto_start_all = False
        self._auto_start_launching = set()
        self._qa_loops = {}
        self._review_loops = {}
        self._self_driving_qa = {}
        self._pending_merge_prs = set()
        self._session_name = "pm-test"
        self._qa_resume_poll_counter = 0
        self._review_loop_timer = None
        self._pane_idle_tracker = _Tracker()
        self.logs = []
        self.log_kw = []
        self.workers = []
        self.timers = []          # (delay, callback) from app.set_timer

    def set_interval(self, interval, callback):
        """Stand-in for Textual's timer registration (never fires here)."""
        return object()

    def set_timer(self, delay, callback):
        """Stand-in for Textual's one-shot timer (recorded, fired by tests)."""
        self.timers.append((delay, callback))
        return object()

    def fire_timers(self):
        """Run the callbacks ``set_timer`` was given, oldest first."""
        pending, self.timers = self.timers, []
        for _delay, callback in pending:
            callback()

    def log_message(self, msg, **kw):
        self.logs.append(msg)
        self.log_kw.append(kw)

    def run_worker(self, coro):
        self.workers.append(coro)
        close = getattr(coro, "close", None)
        if close:
            close()

    def _load_state(self):
        self._data = store.load(self._root)

    def pr(self, pr_id=PR):
        return store.get_pr(store.load(self._root), pr_id)


def _now(offset_seconds: float = 0) -> str:
    return (datetime.now(timezone.utc)
            + timedelta(seconds=offset_seconds)).isoformat()


def _owed_return(*, awaiting="qa", resolved=False, ts=None) -> dict:
    rec = {"verdict": "SIGNOFF_REQA", "hop": "qa", "reason": "misframed",
           "reviewed_head": "c0ffee", "awaiting": awaiting,
           "ts": ts or _now()}
    if resolved:
        rec["resolved_at"] = ts or _now()
    return rec


def _project(tmp_path, *, status="qa", ret=None, pr_id=PR):
    """Write a one-PR project; *ret* is the sign-off return record (or None)."""
    root = tmp_path / "pm"
    root.mkdir(exist_ok=True)
    pr = {"id": pr_id, "title": "T", "branch": "pm/x", "status": status,
          "workdir": str(tmp_path / "wd"), "depends_on": [], "notes": []}
    if ret is not None:
        pr["signoff_return"] = ret
    store.save({"project": {"name": "t", "repo": "/r",
                            "base_branch": "master", "backend": "local"},
                "prs": [pr]}, root)
    return root


def _qa_workdir(home, *, pr_id=PR, loop_id="loop1", owner_pid=None,
                owner_start=None, ended_at=None):
    """Create a QA workdir carrying a run record, as run_qa_sync writes it."""
    qa_dir = home / ".pm" / "workdirs" / "qa" / f"{pr_id}-{loop_id}"
    qa_dir.mkdir(parents=True, exist_ok=True)
    rec = {"pr_id": pr_id, "loop_id": loop_id, "started_at": 0.0,
           "owner_pid": owner_pid if owner_pid is not None else 0,
           "owner_start": owner_start}
    if ended_at is not None:
        rec["ended_at"] = ended_at
    (qa_dir / qa_loop._RUN_RECORD).write_text(json.dumps(rec))
    return qa_dir


def _driven(value):
    """Patch the live-run probe.

    ``create=True`` because pre-fix code has no probe at all: the tests must
    then fail on the reported symptom (the owed QA never starts), not on a
    missing attribute.
    """
    return patch.object(qa_loop, "run_driven_elsewhere", return_value=value,
                        create=True)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """``Path.home`` inside the temp tree so QA workdir scans are isolated."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def live_owner():
    """A real, live process to name as another run's driver."""
    procs = []

    def make():
        p = subprocess.Popen(["sleep", "30"])
        procs.append(p)
        return p

    yield make
    for p in procs:
        p.kill()
        p.wait()


# ---------------------------------------------------------------------------
# run_driven_elsewhere — the persisted "someone else is running QA" fact
# ---------------------------------------------------------------------------

def test_run_record_names_a_live_foreign_driver(home, live_owner):
    owner = live_owner()
    _qa_workdir(home, owner_pid=owner.pid,
                owner_start=qa_loop._proc_start_time(owner.pid))
    assert qa_loop.run_driven_elsewhere(PR) is True
    # Another PR's run says nothing about this one.
    assert qa_loop.run_driven_elsewhere(OTHER) is False


def test_run_record_ignores_own_dead_and_reused_owners(home, live_owner):
    _qa_workdir(home, loop_id="own", owner_pid=os.getpid())
    assert qa_loop.run_driven_elsewhere(PR) is False   # this process's run

    owner = live_owner()
    start = qa_loop._proc_start_time(owner.pid)
    _qa_workdir(home, loop_id="reused", owner_pid=owner.pid,
                owner_start=str(int(start) + 1))       # pid reused
    assert qa_loop.run_driven_elsewhere(PR) is False

    owner.kill()
    owner.wait()
    _qa_workdir(home, loop_id="dead", owner_pid=owner.pid, owner_start=start)
    assert qa_loop.run_driven_elsewhere(PR) is False


def test_an_ended_run_record_is_not_a_driver(home, live_owner):
    """A finished run of a *long-lived* driver (a TUI that went on to other
    work) must not keep reading as in flight: without the end marker every
    other driver — a second TUI, a ``pm pr auto-sequence`` tick — would defer
    to a run that ended hours ago, for as long as that process lives."""
    owner = live_owner()
    _qa_workdir(home, owner_pid=owner.pid,
                owner_start=qa_loop._proc_start_time(owner.pid),
                ended_at=1.0)
    assert qa_loop.run_driven_elsewhere(PR) is False


def test_end_run_record_marks_only_its_own_run(home):
    state = qa_loop.QALoopState(pr_id=PR)
    state.qa_workdir = str(home / ".pm" / "workdirs" / "qa" / f"{PR}-x")
    (home / ".pm" / "workdirs" / "qa" / f"{PR}-x").mkdir(parents=True)
    qa_loop.write_run_record(state)
    qa_loop.end_run_record(state)
    assert qa_loop.read_run_record(state.qa_workdir)["ended_at"]

    # A record written by another driver in the same workdir (a resumed run)
    # is not ours to end.
    other = qa_loop.QALoopState(pr_id=PR)
    other.qa_workdir = state.qa_workdir
    qa_loop.write_run_record(other)
    qa_loop.end_run_record(state)            # stale state, different loop_id
    assert "ended_at" not in qa_loop.read_run_record(state.qa_workdir)


def test_run_record_absent_means_nothing_drives_it(home):
    assert qa_loop.run_driven_elsewhere(PR) is False


def test_write_run_record_names_the_current_process(home):
    state = qa_loop.QALoopState(pr_id=PR)
    state.qa_workdir = str(home / ".pm" / "workdirs" / "qa" / f"{PR}-x")
    (home / ".pm" / "workdirs" / "qa" / f"{PR}-x").mkdir(parents=True)
    qa_loop.write_run_record(state)
    rec = qa_loop.read_run_record(state.qa_workdir)
    assert rec["pr_id"] == PR and rec["loop_id"] == state.loop_id
    assert rec["owner_pid"] == os.getpid()


def _run_data(*, workdir):
    return {"project": {"name": "t", "base_branch": "master",
                        "backend": "local"},
            "prs": [{"id": PR, "title": "T", "branch": "pm/x", "status": "qa",
                     "workdir": str(workdir)}],
            "plans": []}


def test_run_qa_sync_writes_the_run_record_before_planning(home, tmp_path):
    """The wiring, not just the writer: a started run is visible to other
    processes from its first seconds — before planning, i.e. earlier than
    the resume snapshot (first written after scenario launch)."""
    workdir = tmp_path / "wd"
    workdir.mkdir()
    data = _run_data(workdir=workdir)
    state = qa_loop.QALoopState(pr_id=PR)
    with patch("pm_core.qa_loop.get_pm_session", return_value="pm-s"), \
         patch("pm_core.store.load", return_value=data), \
         patch("pm_core.qa_loop._resolve_qa_model",
               return_value=SimpleNamespace(model=None, provider=None,
                                            effort=None)), \
         patch("pm_core.container.is_container_mode_enabled",
               return_value=False), \
         patch("pm_core.prompt_gen.generate_qa_planner_prompt",
               side_effect=RuntimeError("stop the run at the planner")):
        with pytest.raises(RuntimeError):
            qa_loop.run_qa_sync(state, tmp_path / "pm", data["prs"][0])
    rec = qa_loop.read_run_record(state.qa_workdir)
    assert rec is not None and rec["pr_id"] == PR
    assert rec["owner_pid"] == os.getpid()
    # The crash still ends the run: a live driver that raised must not keep
    # other drivers deferring to it for the rest of its life.
    assert rec.get("ended_at")


def test_resume_qa_sync_rewrites_the_run_record(home, tmp_path):
    """A resumed run has a new driver: a stale record naming the dead one
    would leave another TUI thinking the run is up for grabs."""
    workdir = tmp_path / "wd"
    workdir.mkdir()
    data = _run_data(workdir=workdir)
    state = qa_loop.QALoopState(pr_id=PR)
    state.qa_workdir = str(home / ".pm" / "workdirs" / "qa" / f"{PR}-x")
    (home / ".pm" / "workdirs" / "qa" / f"{PR}-x").mkdir(parents=True)
    with patch("pm_core.qa_loop.get_pm_session", return_value="pm-s"), \
         patch("pm_core.store.load", return_value=data), \
         patch("pm_core.qa_loop._load_resume_file", return_value={}), \
         patch("pm_core.qa_loop._execute_and_finalize",
               side_effect=RuntimeError("stop the resume")):
        with pytest.raises(RuntimeError):
            qa_loop.resume_qa_sync(state, tmp_path / "pm", data["prs"][0])
    rec = qa_loop.read_run_record(state.qa_workdir)
    assert rec is not None and rec["owner_pid"] == os.getpid()
    assert rec.get("ended_at")           # the failed resume is over too


def test_resume_qa_background_publishes_running_immediately():
    """The owed-REQA reconciler runs in the same poll tick as the resume
    scan: an adopted run must already look owned, or the reconciler starts a
    second full run over it."""
    import threading
    state = qa_loop.QALoopState(pr_id=PR)
    release = threading.Event()

    def hold(*_a, **_kw):
        release.wait(10)

    with patch("pm_core.qa_loop.resume_qa_sync", side_effect=hold):
        t = qa_loop.resume_qa_background(state, "/x", {})
        try:
            assert state.running is True
        finally:
            release.set()
            t.join(10)


# ---------------------------------------------------------------------------
# Reconciliation — durable, and independent of the auto-start switch
# ---------------------------------------------------------------------------

def test_restart_with_autostart_off_starts_the_owed_qa_once(tmp_path):
    """The repro: a tick wrote ``awaiting: qa``, the TUI restarted with
    auto-start off and no targets.  The owed full QA must still run — once.

    Fails on pre-fix code with the reported symptom: nothing starts QA
    (``start_qa`` is never called), so the PR sits at ``qa`` with
    ``awaiting: qa`` on disk until someone presses ``t``.
    """
    root = _project(tmp_path, ret=_owed_return())
    app = App(root)                       # autostart off, no targets

    with _driven(False), \
         patch.object(qa_loop_ui, "_resume_incomplete_qa"), \
         patch.object(qa_loop_ui, "start_qa") as sq:
        for _ in range(6):                # several ~1 s poll ticks
            qa_loop_ui.poll_qa_state(app)

    sq.assert_called_once_with(app, PR)


def test_owed_qa_waits_for_a_live_run_then_starts_once(tmp_path, home,
                                                       live_owner):
    """Deferred behind a ``pm qa run``: nothing starts while that process is
    alive; once it ends the owed full QA starts exactly once."""
    root = _project(tmp_path, ret=_owed_return())
    owner = live_owner()
    _qa_workdir(home, owner_pid=owner.pid,
                owner_start=qa_loop._proc_start_time(owner.pid))
    app = App(root)

    with patch.object(qa_loop_ui, "start_qa") as sq:
        qa_loop_ui.reconcile_owed_reqa(app)
        qa_loop_ui.reconcile_owed_reqa(app)
        sq.assert_not_called()
        # Still owed on disk, and the deferral is reported once, not per tick.
        assert app.pr()["signoff_return"]["awaiting"] == "qa"
        assert sum("QA starts once" in m for m in app.logs) == 1

        owner.kill()
        owner.wait()
        qa_loop_ui.reconcile_owed_reqa(app)      # the live owner finished
        qa_loop_ui.reconcile_owed_reqa(app)
    sq.assert_called_once_with(app, PR)


def test_deferral_is_reported_for_a_return_without_a_ts(tmp_path, home,
                                                        live_owner):
    """A hand-edited return record need not carry ``ts``.  Keying the
    once-per-episode dedupe on it must not compare equal to "never reported"
    (None), which would swallow the deferral line on every tick."""
    rec = _owed_return()
    rec.pop("ts")
    root = _project(tmp_path, ret=rec)
    owner = live_owner()
    _qa_workdir(home, owner_pid=owner.pid,
                owner_start=qa_loop._proc_start_time(owner.pid))
    app = App(root)
    with patch.object(qa_loop_ui, "start_qa") as sq:
        qa_loop_ui.reconcile_owed_reqa(app)
        qa_loop_ui.reconcile_owed_reqa(app)
    sq.assert_not_called()
    assert sum("QA starts once" in m for m in app.logs) == 1


def test_a_bare_qa_status_is_not_authorization(tmp_path):
    root = _project(tmp_path, ret=None)
    app = App(root)
    with patch.object(qa_loop_ui, "start_qa") as sq:
        qa_loop_ui.reconcile_owed_reqa(app)
    sq.assert_not_called()


@pytest.mark.parametrize("ret,status", [
    (_owed_return(resolved=True), "qa"),          # episode closed
    (_owed_return(awaiting=None), "qa"),          # already launched/cleared
    (_owed_return(awaiting="review"), "qa"),      # a different hop is owed
    (_owed_return(), "sign_off"),                 # superseded by a new pass
    (_owed_return(), "in_review"),                # superseded by rework
    (_owed_return(), "merged"),                   # done
], ids=["resolved", "cleared", "other-hop", "back-in-signoff", "in-review",
        "merged"])
def test_only_an_open_qa_return_at_qa_is_owed(tmp_path, ret, status):
    root = _project(tmp_path, status=status, ret=ret)
    app = App(root)
    with _driven(False), \
         patch.object(qa_loop_ui, "start_qa") as sq:
        qa_loop_ui.reconcile_owed_reqa(app)
    sq.assert_not_called()


def test_running_local_loop_is_left_alone(tmp_path):
    """The user's own ``t``/``zz t`` owns the PR: no second start."""
    root = _project(tmp_path, ret=_owed_return())
    app = App(root)
    state = qa_loop.QALoopState(pr_id=PR)
    state.running = True
    app._qa_loops[PR] = state
    with _driven(False), \
         patch.object(qa_loop_ui, "start_qa") as sq:
        qa_loop_ui.reconcile_owed_reqa(app)
    sq.assert_not_called()


def test_nothing_owed_reads_no_project_yaml(tmp_path):
    """The tick runs every ~5 s forever: an idle project must not pay for a
    project.yaml load (the claim is the authority when something is owed)."""
    root = _project(tmp_path, ret=None)
    app = App(root)
    with patch.object(store, "load", side_effect=AssertionError("loaded")), \
         patch.object(qa_loop_ui, "start_qa") as sq:
        qa_loop_ui.reconcile_owed_reqa(app)
    sq.assert_not_called()


# ---------------------------------------------------------------------------
# One owner across restarts, ticks and clients
# ---------------------------------------------------------------------------

def test_a_fresh_foreign_claim_blocks_until_it_expires(tmp_path):
    """Another driver claimed the launch (it may be starting right now): wait
    it out.  A claim whose launcher died expires, and the reconciler takes
    over — the obligation is never stranded."""
    root = _project(tmp_path, ret=_owed_return())
    app = App(root)

    def claim(offset):
        def apply(d):
            store.get_pr(d, PR)["signoff_return"]["launch_claim"] = {
                "hop": "qa", "at": _now(offset)}
        store.locked_update(root, apply)

    claim(-1)
    with _driven(False), \
         patch.object(qa_loop_ui, "start_qa") as sq:
        qa_loop_ui.reconcile_owed_reqa(app)
        sq.assert_not_called()

    claim(-(signoff.RETURN_LAUNCH_CLAIM_SECONDS + 5))
    with _driven(False), \
         patch.object(qa_loop_ui, "start_qa") as sq:
        qa_loop_ui.reconcile_owed_reqa(app)
    sq.assert_called_once_with(app, PR)


def test_a_held_claim_is_declined_without_a_project_rewrite(tmp_path):
    """Waiting out another driver's claim must not cost a full project.yaml
    rewrite every ~5 s tick: ``locked_update`` saves even when its callback
    declines, and the claim can be held for RETURN_LAUNCH_CLAIM_SECONDS."""
    root = _project(tmp_path, ret=_owed_return())
    app = App(root)

    def apply(d):
        store.get_pr(d, PR)["signoff_return"]["launch_claim"] = {
            "hop": "qa", "at": _now(-1)}
    store.locked_update(root, apply)

    with _driven(False), \
         patch.object(store, "save") as save, \
         patch.object(qa_loop_ui, "start_qa") as sq:
        qa_loop_ui.reconcile_owed_reqa(app)
    sq.assert_not_called()
    save.assert_not_called()


def test_two_tuis_start_the_owed_qa_only_once(tmp_path):
    """Grouped/concurrent clients: the claim is the cross-process gate."""
    root = _project(tmp_path, ret=_owed_return())
    a, b = App(root), App(root)
    starts = []

    def fake_start(app, pr_id, **kw):
        starts.append((app, pr_id))
        # What the real start_qa does first: consume the obligation.
        from pm_core.signoff import clear_return_awaiting
        clear_return_awaiting(root, pr_id, "qa")

    with _driven(False), \
         patch.object(qa_loop_ui, "start_qa", side_effect=fake_start):
        qa_loop_ui.reconcile_owed_reqa(a)
        qa_loop_ui.reconcile_owed_reqa(b)
        qa_loop_ui.reconcile_owed_reqa(a)
    assert starts == [(a, PR)]


def test_start_owed_reqa_claims_the_launch_before_starting(tmp_path):
    root = _project(tmp_path, ret=_owed_return())
    app = App(root)

    def fake_start(app_, pr_id, **kw):
        # What the real start_qa does: register the loop (running) first.
        state = qa_loop.QALoopState(pr_id=pr_id)
        state.running = True
        app_._qa_loops[pr_id] = state

    with _driven(False), \
         patch.object(qa_loop_ui, "start_qa", side_effect=fake_start) as sq:
        assert qa_loop_ui.start_owed_reqa(app, PR) is True
        sq.assert_called_once_with(app, PR)
    rec = app.pr()["signoff_return"]
    assert rec["awaiting"] == "qa"          # start_qa (faked) would clear it
    assert rec["launch_claim"]["hop"] == "qa"


def test_start_owed_reqa_reports_a_bailed_start(tmp_path):
    """``start_qa`` can refuse (no project root, PR gone, parse error).  The
    caller must not be told a run started — auto-start would announce one
    that does not exist — and the obligation must stay on disk."""
    root = _project(tmp_path, ret=_owed_return())
    app = App(root)
    with _driven(False), \
         patch.object(qa_loop_ui, "start_qa") as sq:   # registers nothing
        assert qa_loop_ui.start_owed_reqa(app, PR) is False
        sq.assert_called_once_with(app, PR)
    assert app.pr()["signoff_return"]["awaiting"] == "qa"
    assert qa_loop_ui.owed_reqa_prs(app) != []


def test_a_finished_or_stopped_loop_does_not_block_the_owed_start(tmp_path):
    """``_qa_loops`` keeps a finished run for one poll tick and a stopped one
    indefinitely.  Only a *running* loop owns the PR; a stale entry must not
    strand the obligation."""
    root = _project(tmp_path, ret=_owed_return())
    app = App(root)
    stale = qa_loop.QALoopState(pr_id=PR)
    stale.running = False
    app._qa_loops[PR] = stale
    with _driven(False), \
         patch.object(qa_loop_ui, "start_qa") as sq:
        qa_loop_ui.reconcile_owed_reqa(app)
    sq.assert_called_once_with(app, PR)


def test_a_started_owed_reqa_is_dropped_from_memory(tmp_path):
    """Once the start consumed the obligation on disk, this process's copy
    must stop offering it: otherwise every ~5 s tick re-attempts the claim —
    a full project.yaml read plus an fsynced rewrite — until a reload.

    Exercises the real ``start_qa`` (only the background thread is stubbed),
    so the consumption and its in-memory mirror are the shipped ones.
    """
    root = _project(tmp_path, ret=_owed_return())
    app = App(root)

    def fake_background(state, *_a, **_kw):
        # What the real start_qa_background does before starting its thread.
        state.running = True

    with _driven(False), \
         patch.object(qa_loop_ui, "start_qa_background",
                      side_effect=fake_background) as bg:
        assert qa_loop_ui.start_owed_reqa(app, PR) is True
    bg.assert_called_once()
    assert app.pr()["signoff_return"]["awaiting"] is None   # on disk
    assert qa_loop_ui.owed_reqa_prs(app) == []              # and in memory

    app._qa_loops.clear()                 # the run has ended
    with patch.object(signoff, "claim_return_launch") as claim:
        qa_loop_ui.reconcile_owed_reqa(app)
    claim.assert_not_called()


def test_in_memory_consumption_leaves_another_hop_alone(tmp_path):
    """The mirror of ``start_qa``'s consumption must only clear the ``qa``
    hop: clearing a return awaiting impl/review would hide it from the
    scheduler until the next reload."""
    root = _project(tmp_path, ret=_owed_return(awaiting="review"))
    app = App(root)
    qa_loop_ui._consume_owed_reqa_in_memory(app, PR)
    assert app._data["prs"][0]["signoff_return"]["awaiting"] == "review"
    assert app.pr()["signoff_return"]["awaiting"] == "review"


def test_an_obligation_consumed_elsewhere_is_dropped_from_memory(tmp_path):
    """Another process (a second TUI, an auto-sequence tick) started the run,
    so the obligation is gone on disk while this process's copy still shows
    it.  Re-attempting the claim every ~5 s would rewrite project.yaml for
    nothing until some other path reloads the state."""
    root = _project(tmp_path, ret=_owed_return())
    app = App(root)                      # app._data still says owed

    def consumed_elsewhere(d):
        store.get_pr(d, PR)["signoff_return"]["awaiting"] = None
    store.locked_update(root, consumed_elsewhere)

    with _driven(False), patch.object(qa_loop_ui, "start_qa") as sq:
        qa_loop_ui.reconcile_owed_reqa(app)
    sq.assert_not_called()
    assert qa_loop_ui.owed_reqa_prs(app) == []

    with _driven(False), patch.object(signoff, "claim_return_launch") as claim:
        qa_loop_ui.reconcile_owed_reqa(app)
    claim.assert_not_called()            # no further locked rewrite


def test_arm_owed_reqa_arms_the_tick_and_starts_the_run(tmp_path):
    """The mount hook: a restarted TUI must not wait for some other loop to
    keep the poll tick alive (auto-start off, nothing running)."""
    root = _project(tmp_path, ret=_owed_return())
    app = App(root)
    with _driven(False), \
         patch.object(qa_loop_ui, "start_qa") as sq, \
         patch("pm_core.tui.review_loop_ui._ensure_poll_timer") as timer:
        qa_loop_ui.arm_owed_reqa(app)
        timer.assert_called_once_with(app)
        app.fire_timers()
        sq.assert_called_once_with(app, PR)


def test_arm_owed_reqa_defers_the_reconcile_past_the_first_frame(tmp_path):
    """``on_mount`` runs before the first frame, and actually starting the
    owed run costs two locked project.yaml rewrites (the claim, then the
    ``awaiting`` clear) — ~1 s each on a large project.  The mount hook must
    hand that to a timer, or a restarted TUI with an owed REQA looks hung."""
    root = _project(tmp_path, ret=_owed_return())
    app = App(root)
    with _driven(False), \
         patch.object(qa_loop_ui, "start_qa") as sq, \
         patch("pm_core.tui.review_loop_ui._ensure_poll_timer"):
        qa_loop_ui.arm_owed_reqa(app)
        sq.assert_not_called()            # nothing blocking in on_mount
        assert len(app.timers) == 1
        delay, _callback = app.timers[0]
        assert 0 < delay <= 1.0
        app.fire_timers()
    sq.assert_called_once_with(app, PR)


def test_arm_owed_reqa_contains_a_failing_reconcile(tmp_path):
    """The mount hook's guard wraps the arm, not the deferred call: a failure
    inside the timer must not escape into Textual's timer machinery (and a
    silent loss there is the bug the hook exists to prevent)."""
    root = _project(tmp_path, ret=_owed_return())
    app = App(root)
    with patch.object(qa_loop_ui, "reconcile_owed_reqa",
                      side_effect=RuntimeError("boom")):
        qa_loop_ui.arm_owed_reqa(app)
        app.fire_timers()                  # must not raise


def test_arm_owed_reqa_is_quiet_when_nothing_is_owed(tmp_path):
    """Runs on every mount: the in-memory state (just loaded) is enough, so
    an idle project pays no second project.yaml read."""
    root = _project(tmp_path, ret=None)
    app = App(root)
    with patch.object(store, "load", side_effect=AssertionError("loaded")), \
         patch.object(qa_loop_ui, "start_qa") as sq, \
         patch("pm_core.tui.review_loop_ui._ensure_poll_timer") as timer:
        qa_loop_ui.arm_owed_reqa(app)
    sq.assert_not_called()
    timer.assert_not_called()


def test_reconcile_is_wired_into_the_poll_tick(tmp_path):
    """Restart recovery must not depend on any loop being in memory: the
    shared poll tick reconciles (auto-start off, nothing running)."""
    root = _project(tmp_path, ret=_owed_return())
    app = App(root)
    with _driven(False), \
         patch.object(qa_loop_ui, "_resume_incomplete_qa"), \
         patch.object(qa_loop_ui, "start_qa") as sq:
        for _ in range(6):                   # the reconciler's 5 s cadence
            qa_loop_ui.poll_qa_state(app)
    sq.assert_called_once_with(app, PR)


# ---------------------------------------------------------------------------
# A re-run the restart killed before its first snapshot (S131)
# ---------------------------------------------------------------------------

def _own_run(home, *, loop_id="lost", started_at=None, **kw):
    """A run record naming this process, as the old TUI image wrote it."""
    qa_dir = _qa_workdir(home, loop_id=loop_id, owner_pid=os.getpid(),
                         owner_start=qa_loop._proc_start_time(os.getpid()),
                         **kw)
    rec = qa_loop.read_run_record(qa_dir)
    rec["started_at"] = started_at if started_at is not None else 0.0
    (qa_dir / qa_loop._RUN_RECORD).write_text(json.dumps(rec))
    return qa_dir


def _as_another_process():
    """Ask the driver probes from a ``pm pr auto-sequence`` tick's side."""
    return patch.object(qa_loop.os, "getpid", return_value=1)


def test_restart_ends_only_this_images_snapshotless_runs(home):
    """``pm tui restart`` execs in place: the pid and start time a run
    record names survive while the run's thread is gone."""
    lost = _own_run(home, loop_id="lost")
    snap = _own_run(home, loop_id="snap")
    (snap / "qa_resume.json").write_text("{}")      # the resume scan's
    live = _own_run(home, loop_id="live")           # a loop it drives
    other = _qa_workdir(home, loop_id="reused", owner_pid=os.getpid(),
                        owner_start="1")            # pid reused
    done = _own_run(home, loop_id="done", ended_at=5.0)
    launch = _own_run(home, loop_id="launch")
    rec = qa_loop.read_run_record(launch)
    rec["launch"] = True
    (launch / qa_loop._RUN_RECORD).write_text(json.dumps(rec))

    ended = qa_loop.end_runs_orphaned_by_restart([str(live)])

    assert [(wd, r["loop_id"]) for wd, r in ended] == [(lost, "lost")]
    assert qa_loop.read_run_record(lost)["ended_at"]
    for wd in (snap, live, other, launch):
        assert "ended_at" not in qa_loop.read_run_record(wd)
    assert qa_loop.read_run_record(done)["ended_at"] == 5.0


def test_a_reqa_rerun_killed_by_a_plain_restart_starts_again_once(tmp_path,
                                                                    home):
    """The S131 repro: the TUI routed the REQA and started the owed re-run
    (consuming ``awaiting``), then a plain ``pm tui restart`` killed it
    during planning.  Its record names the restarted TUI's own live pid, so
    ticks deferred to it forever and nothing started QA again.  The mount
    hooks must end that record and start the owed run once."""
    ts = _now(-10)
    root = _project(tmp_path, ret=_owed_return(awaiting=None, ts=ts))
    started = signoff.parse_ts(ts).timestamp() + 1
    lost = _own_run(home, started_at=started)
    with _as_another_process():
        assert qa_loop.run_driven_elsewhere(PR) is True     # the symptom
    app = App(root)                    # a plain restart: auto-start off

    with patch.object(qa_loop_ui, "start_qa") as sq, \
         patch("pm_core.tui.review_loop_ui._ensure_poll_timer"):
        qa_loop_ui.recover_restart_killed_runs(app)
        qa_loop_ui.arm_owed_reqa(app)
        app.fire_timers()
        qa_loop_ui.report_restart_lost_runs(app)
        for _ in range(6):
            qa_loop_ui.reconcile_owed_reqa(app)
        # A second restart's mount finds nothing more to recover.
        qa_loop_ui.recover_restart_killed_runs(app)
        qa_loop_ui.report_restart_lost_runs(app)
    sq.assert_called_once_with(app, PR)
    assert qa_loop.read_run_record(lost)["ended_at"]
    with _as_another_process():
        assert qa_loop.run_driven_elsewhere(PR) is False
    # Reopened on disk, behind the claim the start took.
    ret = app.pr()["signoff_return"]
    assert ret["awaiting"] == "qa" and ret["launch_claim"]["hop"] == "qa"
    # It starts again by itself: no "press z t" line for it.
    assert not [m for m in app.logs if "cut off by the TUI restart" in m]


@pytest.mark.parametrize("case", ["verdict", "successor", "before-return",
                                  "not-qa"])
def test_a_restart_killed_run_reopens_only_the_reqa_it_consumed(tmp_path,
                                                                 home, case):
    """Only the owed re-run itself reopens the obligation: not a run that
    reached a verdict, one a newer run replaced, one started before the
    return (the judged run), or a PR that has left ``qa``."""
    ts = _now(-10)
    t = signoff.parse_ts(ts).timestamp()
    root = _project(tmp_path, ret=_owed_return(awaiting=None, ts=ts),
                    status="sign_off" if case == "not-qa" else "qa")
    lost = _own_run(home, started_at=t - 5 if case == "before-return"
                    else t + 1)
    if case == "verdict":
        (lost / "qa_status.json").write_text(json.dumps({"overall": "PASS"}))
    if case == "successor":
        _qa_workdir(home, loop_id="newer")
        rec = qa_loop.read_run_record(lost.parent / f"{PR}-newer")
        rec["started_at"] = t + 2
        (lost.parent / f"{PR}-newer" / qa_loop._RUN_RECORD).write_text(
            json.dumps(rec))
    app = App(root)
    with patch.object(store, "locked_update",
                      wraps=store.locked_update) as lu:
        qa_loop_ui.recover_restart_killed_runs(app)
    qa_loop_ui.report_restart_lost_runs(app)
    assert qa_loop.read_run_record(lost)["ended_at"]
    assert app.pr()["signoff_return"]["awaiting"] is None
    lu.assert_not_called()              # no project.yaml rewrite
    # A run that reached a verdict or was replaced lost nothing, and a PR
    # that left qa has nothing to run again; one still at qa is told how.
    cut = [m for m in app.logs if "cut off by the TUI restart" in m]
    assert len(cut) == (1 if case == "before-return" else 0)


def test_a_restart_killed_plain_run_is_reported_not_left_silent(tmp_path,
                                                                 home):
    """A run the user started with ``t`` (no sign-off return) that the
    restart killed before its first snapshot has nothing to resume and
    nothing starts it again with auto-start off, so the TUI says why and how
    to run it again, once.  ``z t``: its main qa window can outlive it, and
    plain ``t`` only focuses that window."""
    root = _project(tmp_path, ret=None)
    lost = _own_run(home, started_at=time.time() - 5)
    app = App(root)
    with patch.object(store, "locked_update",
                      wraps=store.locked_update) as lu:
        for _ in range(2):                             # a second mount
            qa_loop_ui.recover_restart_killed_runs(app)
            qa_loop_ui.report_restart_lost_runs(app)
    assert qa_loop.read_run_record(lost)["ended_at"]
    lu.assert_not_called()
    assert app.logs == [f"QA for {PR} was cut off by the TUI restart before "
                        "its first snapshot — press z t to run it again"]
    assert app.log_kw == [{"sticky": 10}]


@pytest.mark.parametrize("case", ["autostart", "left-qa"])
def test_a_lost_run_running_again_or_out_of_qa_is_not_reported(
        tmp_path, home, case):
    """Auto-start is off at mount and comes back with the breadcrumb, whose
    pass starts a lost target's QA again: no "press z t" line for a run
    already running again (z t would kill it), nor for a PR that left qa
    before the report."""
    root = _project(tmp_path, ret=None)
    _own_run(home, started_at=time.time() - 5)
    app = App(root)
    qa_loop_ui.recover_restart_killed_runs(app)
    if case == "autostart":
        from pm_core.tui import auto_start
        app._auto_start, app._auto_start_targets = True, {PR: {}}
        with patch.object(qa_loop_ui, "start_qa", side_effect=lambda a, p:
                          a._qa_loops.__setitem__(p, object())) as sq:
            auto_start._auto_start_qa_loops(app)
        sq.assert_called_once_with(app, PR)
    else:
        store.get_pr(app._data, PR)["status"] = "sign_off"
    qa_loop_ui.report_restart_lost_runs(app)
    assert not [m for m in app.logs if "cut off by the TUI restart" in m]


def test_restart_recovery_retires_the_dead_runs_windows(tmp_path, home):
    """The dead run opened scenario 0's window before its main ``qa-<pr>``
    window; the next run's cleanup is keyed on the main window, so without
    this a second ``qa-<pr>-s0`` sat beside the new run's."""
    ts = _now(-10)
    root = _project(tmp_path, ret=_owed_return(awaiting=None, ts=ts))
    lost = _own_run(home, started_at=signoff.parse_ts(ts).timestamp() + 1)
    app = App(root)
    with patch.object(qa_loop_ui, "get_pm_session", return_value="pm-test"), \
         patch.object(qa_loop, "kill_windows_of_run") as kw:
        qa_loop_ui.recover_restart_killed_runs(app)
    kw.assert_called_once_with("pm-test", lost)


def test_kill_windows_of_run_matches_only_that_runs_qa_windows(tmp_path):
    from pm_core import tmux as tmux_mod
    wd = tmp_path / "qa" / f"{PR}-lost"
    panes = "\n".join([
        f"@1\tqa-{PR}-s0\t{wd}/s-0/repo",            # the dead run's
        f"@2\tqa-{PR}-s0\t{wd}-other/s-0/repo",      # a sibling run's
        f"@3\tnotes\t{wd}/s-0/repo",                 # not a QA window
        f"@4\tqa-{PR}-s1\t{wd}",
    ])
    with patch.object(tmux_mod, "_run", return_value=SimpleNamespace(
            returncode=0, stdout=panes)), \
         patch.object(tmux_mod, "kill_window") as kill, \
         patch("pm_core.home_window.park_if_on"):
        assert qa_loop.kill_windows_of_run("pm-test", wd) == 2
    assert [c.args for c in kill.call_args_list] == [("pm-test", "@1"),
                                                     ("pm-test", "@4")]


def test_kill_windows_of_run_matches_that_runs_container_windows(tmp_path):
    """Container scenario windows are opened in the PR workdir, not the QA
    workdir; they are the dead run's by the container they exec into (S136:
    a plain restart left ``qa-<pr>-s1``/``-s2`` and their refiners alive)."""
    from pm_core import tmux as tmux_mod
    wd = tmp_path / "qa" / f"{PR}-0684f96ec911541c"
    wd.mkdir(parents=True)
    (wd / "qa_run.json").write_text(json.dumps(
        {"pr_id": PR, "loop_id": "0684f96ec911541c"}))
    prwd = tmp_path / "workdirs" / f"pm-{PR}"
    run = f"sh -c 'podman exec -it -e X pm-tag-qa-{PR}-0684f96ec911541c-s%d bash -c claude'"
    other = f"sh -c 'podman exec -it pm-tag-qa-{PR}-1111111111111111-s1 bash -c claude'"
    panes = "\n".join([
        f"@1\tqa-{PR}-s0\t{wd}/s-0/repo\tsh -c 'claude'",   # host s0
        f"@2\tqa-{PR}-s1\t{prwd}\t" + run % 1,               # the dead run's
        f"@3\tqa-{PR}-s2\t{prwd}\t" + run % 2,
        f"@4\tqa-{PR}-s1\t{prwd}\t" + other,                 # another run's
        f"@5\tqa-{PR}\t{prwd}\tsh -c 'echo QA execution'",   # main window
        f"@6\t{PR}\t{prwd}\t" + run % 1,                     # not a QA window
    ])
    with patch.object(tmux_mod, "_run", return_value=SimpleNamespace(
            returncode=0, stdout=panes)), \
         patch.object(tmux_mod, "kill_window") as kill, \
         patch("pm_core.home_window.park_if_on"):
        assert qa_loop.kill_windows_of_run("pm-test", wd) == 3
    assert [c.args[1] for c in kill.call_args_list] == ["@1", "@2", "@3"]


def test_restart_recovery_is_wired_into_mount_before_the_owed_arm():
    """The recovery must run before ``arm_owed_reqa`` reads the obligation."""
    import inspect
    from pm_core.tui import app as app_mod
    src = inspect.getsource(app_mod)
    assert 0 < src.index("recover_restart_killed_runs(self)") \
        < src.index("qa_loop_ui.arm_owed_reqa(self)")


def test_restart_lost_report_is_wired_after_the_breadcrumb():
    """The report waits for the breadcrumb's auto-start pass."""
    import inspect
    from pm_core.tui import app as app_mod
    src = inspect.getsource(app_mod)
    assert 0 < src.index("auto_start.consume_breadcrumb(self)") \
        < src.index("qa_loop_ui.report_restart_lost_runs(self)")


# ---------------------------------------------------------------------------
# Other drivers of the same obligation
# ---------------------------------------------------------------------------

def test_autostart_qa_loop_skips_a_run_driven_elsewhere(tmp_path):
    """Auto-start must not start a second loop over a live ``pm qa run``."""
    root = _project(tmp_path, ret=_owed_return())
    app = App(root, autostart=True, targets=(PR,))
    with _driven(True), \
         patch.object(qa_loop_ui, "start_qa") as sq:
        from pm_core.tui import auto_start
        auto_start._auto_start_qa_loops(app, app._data["prs"])
    sq.assert_not_called()


def test_autostart_qa_loop_starts_an_owed_reqa_through_the_claim(tmp_path):
    root = _project(tmp_path, ret=_owed_return())
    app = App(root, autostart=True, targets=(PR,))
    with _driven(False), \
         patch.object(qa_loop_ui, "start_qa") as sq:
        from pm_core.tui import auto_start
        auto_start._auto_start_qa_loops(app, app._data["prs"])
        auto_start._auto_start_qa_loops(app, app._data["prs"])
    sq.assert_called_once_with(app, PR)
    assert app.pr()["signoff_return"]["launch_claim"]["hop"] == "qa"


def test_zz_t_loop_start_consumes_the_owed_reqa(tmp_path):
    """``zz t`` starts a full QA loop without going through ``start_qa``: it
    must still consume the obligation, or the reconciler starts a *second*
    full run once that loop ends."""
    root = _project(tmp_path, ret=_owed_return())
    app = App(root)
    with patch.object(qa_loop_ui, "start_qa_background") as bg:
        qa_loop_ui.start_or_stop_qa_loop(app, PR)
    bg.assert_called_once()
    assert app.pr()["signoff_return"]["awaiting"] is None
    assert qa_loop_ui.owed_reqa_prs(app) == []


def test_a_pre_return_qa_pass_does_not_supersede_the_owed_reqa(tmp_path):
    """A run that finished after the bounce but verified the code sign-off
    already judged must not hand the PR back to sign-off: the owed full QA
    still has to run."""
    root = _project(tmp_path, ret=_owed_return())
    app = App(root, autostart=True, targets=(PR,))
    state = qa_loop.QALoopState(pr_id=PR)
    state.latest_verdict = qa_loop.VERDICT_PASS
    with patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
         patch("pm_core.tui.signoff_ui.start_signoff") as start_signoff:
        qa_loop_ui._on_qa_complete(app, state)
    start_signoff.assert_not_called()
    assert app.pr()["status"] == "qa"
    assert any("sign-off" in m and "owed" in m.lower() for m in app.logs), \
        app.logs


def test_a_pre_return_self_driving_pass_does_not_supersede_the_owed_reqa(
        tmp_path):
    """The ``zz t`` branch of the same PASS handler hands off too.  A loop
    whose last run began before the bounce (a restart would have consumed
    the obligation) must not hand the PR to sign-off on its PASS: that moves
    the PR off ``qa`` and the reconciler stops seeing the obligation."""
    root = _project(tmp_path, ret=_owed_return())
    app = App(root, autostart=True, targets=(PR,))
    app._self_driving_qa[PR] = {"pass_count": 0, "required_passes": 1}
    state = qa_loop.QALoopState(pr_id=PR)
    state.latest_verdict = qa_loop.VERDICT_PASS
    with patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
         patch("pm_core.tui.signoff_ui.start_signoff") as start_signoff:
        qa_loop_ui._on_qa_complete(app, state)
    start_signoff.assert_not_called()
    assert app.pr()["status"] == "qa"
    assert app._self_driving_qa == {}       # the loop ends, no restart
    assert any("owed sign-off re-run" in m for m in app.logs), app.logs
    # The obligation is still owed, so the reconciler runs it next tick.
    assert qa_loop_ui.owed_reqa_prs(app) != []
