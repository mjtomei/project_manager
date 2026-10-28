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
import subprocess
from datetime import datetime, timedelta, timezone
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
        self._pane_idle_tracker = _Tracker()
        self.logs = []
        self.log_kw = []
        self.workers = []

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
                owner_start=None):
    """Create a QA workdir carrying a run record, as run_qa_sync writes it."""
    qa_dir = home / ".pm" / "workdirs" / "qa" / f"{pr_id}-{loop_id}"
    qa_dir.mkdir(parents=True, exist_ok=True)
    rec = {"pr_id": pr_id, "loop_id": loop_id, "started_at": 0.0,
           "owner_pid": owner_pid if owner_pid is not None else 0,
           "owner_start": owner_start}
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
    import os
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


def test_run_record_absent_means_nothing_drives_it(home):
    assert qa_loop.run_driven_elsewhere(PR) is False


def test_run_qa_sync_writes_the_run_record(home, tmp_path, monkeypatch):
    """A run is visible to other processes from its start, not only once its
    resume snapshot exists (that write lands after scenario launch)."""
    state = qa_loop.QALoopState(pr_id=PR)
    state.qa_workdir = str(home / ".pm" / "workdirs" / "qa" / f"{PR}-x")
    (home / ".pm" / "workdirs" / "qa" / f"{PR}-x").mkdir(parents=True)
    qa_loop.write_run_record(state)
    rec = qa_loop.read_run_record(state.qa_workdir)
    assert rec["pr_id"] == PR and rec["loop_id"] == state.loop_id
    assert rec["owner_pid"] == __import__("os").getpid()


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
    with _driven(False), \
         patch.object(qa_loop_ui, "start_qa") as sq:
        assert qa_loop_ui.start_owed_reqa(app, PR) is True
        sq.assert_called_once_with(app, PR)
    rec = app.pr()["signoff_return"]
    assert rec["awaiting"] == "qa"          # start_qa (faked) would clear it
    assert rec["launch_claim"]["hop"] == "qa"


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
