"""A sign-off REQA return's ``awaiting: qa`` once its TUI re-run started
(QA S80, 0f4ecbf2).

Live (S80 story 2): the TUI's start_qa gave up clearing ``awaiting`` after
the 2 s lock timeout (a holder kept project.yaml busy right after the hop),
started the run anyway, and nothing cleared it later.  When the run ended
INPUT_REQUIRED, the next auto-start pass read ``awaiting: qa`` as a return
still waiting for its run and re-ran QA.  The pre-fix control (start_qa
waited the lock out and cleared ``awaiting`` on disk) re-ran it too: the
pass read the tree's copy of the PR, loaded before the clear.

start_qa now keeps the give-up as a pending clear that the poll tick retries
without waiting, and both scheduler checks confirm ``awaiting: qa`` on disk.
"""

import threading
import time
from unittest.mock import patch

from pm_core import store
from pm_core import signoff
from pm_core.qa_loop import QALoopState
from tests.test_project_lock_held import _held
from tests.test_qa_completion_unloadable import _make_app, _poll, _pr

TS = "2099-01-01T00:00:00+00:00"


def _return(awaiting="qa", ts=TS):
    return {"verdict": "SIGNOFF_REQA", "hop": "qa", "awaiting": awaiting,
            "ts": ts}


def _seed(app, awaiting="qa", ts=TS):
    data = store.load(app._root)
    p = store.get_pr(data, "pr-001")
    p["workdir"] = "/wd"
    p["signoff_return"] = _return(awaiting, ts)
    store.save(data, app._root)
    return p


def test_clear_gives_up_with_none_and_ts_guards_a_later_return(tmp_path):
    app = _make_app(tmp_path)
    _seed(app)
    with _held(app._root):
        t0 = time.monotonic()
        assert signoff.clear_return_awaiting(
            app._root, "pr-001", "qa", timeout=0.2) is None
        assert time.monotonic() - t0 < 0.6
        assert signoff.clear_return_awaiting(
            app._root, "pr-001", "qa", timeout=store.NO_WAIT) is False
    assert _pr(app._root)["signoff_return"]["awaiting"] == "qa"
    # A retry for an earlier return leaves a later one waiting.
    assert signoff.clear_return_awaiting(
        app._root, "pr-001", "qa", timeout=store.NO_WAIT,
        ts="2000-01-01T00:00:00+00:00") is True
    assert _pr(app._root)["signoff_return"]["awaiting"] == "qa"
    assert signoff.clear_return_awaiting(
        app._root, "pr-001", "qa", timeout=store.NO_WAIT, ts=TS) is True
    assert _pr(app._root)["signoff_return"]["awaiting"] is None


def test_start_qa_give_up_is_cleared_by_the_poll_tick(tmp_path):
    """The run starts after the 2 s give-up; the first poll tick after the
    release clears ``awaiting``, and ticks while it is held never wait."""
    from pm_core.tui import qa_loop_ui
    app = _make_app(tmp_path)
    _seed(app)
    rel = threading.Event()
    held = threading.Event()

    def hold():
        with _held(app._root):
            held.set()
            rel.wait(10)
    t = threading.Thread(target=hold)
    t.start()
    held.wait()
    try:
        with patch.object(qa_loop_ui, "start_qa_background") as bg, \
                patch.object(store, "LOCK_TIMEOUT_SECONDS", 0.2):
            assert qa_loop_ui.start_qa(app, "pr-001", lock_timeout=0.2) is True
        bg.assert_called_once()
        state = app._qa_loops["pr-001"]
        state.running = True
        assert state._ui_return_clear == TS
        for _ in range(3):
            t0 = time.monotonic()
            _poll(app, 1)
            assert time.monotonic() - t0 < 0.5
        assert _pr(app._root)["signoff_return"]["awaiting"] == "qa"
    finally:
        rel.set()
        t.join()
    _poll(app, 1)
    assert _pr(app._root)["signoff_return"]["awaiting"] is None
    assert state._ui_return_clear is None


def test_start_qa_clear_that_took_leaves_nothing_pending(tmp_path):
    from pm_core.tui import qa_loop_ui
    app = _make_app(tmp_path)
    _seed(app)
    with patch.object(qa_loop_ui, "start_qa_background"):
        assert qa_loop_ui.start_qa(app, "pr-001") is True
    assert app._qa_loops["pr-001"]._ui_return_clear is None
    assert _pr(app._root)["signoff_return"]["awaiting"] is None


def _sched_app(tmp_path, tree_awaiting, disk_awaiting):
    from pm_core import autostart_state as st
    from tests.test_autostart_multi_target import FakeApp
    tree = {"id": "pr-001", "title": "T", "branch": "b", "status": "qa",
            "workdir": "/wd", "depends_on": [],
            "signoff_return": _return(tree_awaiting)}
    store.save({"project": {"name": "t", "repo": "/r",
                            "base_branch": "master"},
                "prs": [dict(tree, signoff_return=_return(disk_awaiting))]},
               tmp_path)
    app = FakeApp([tree], root=tmp_path)
    app._auto_start = True
    app._auto_start_targets = {"pr-001": st.make_target_record("t")}
    app._auto_start_run_id = "run"
    return app, tree


def test_stale_tree_awaiting_does_not_rerun_a_finished_run(tmp_path):
    """S80 story 2 on both builds: the re-run ended INPUT_REQUIRED, its start
    had cleared ``awaiting`` on disk, and an auto-start pass re-ran QA on the
    tree's stale ``awaiting: qa``.  A PASS is handed to sign-off."""
    from pm_core.tui import auto_start, signoff_ui
    for verdict in ("INPUT_REQUIRED", "PASS"):
        app, tree = _sched_app(tmp_path, "qa", None)
        with patch.object(auto_start, "recorded_qa_verdict",
                          return_value=verdict), \
                patch.object(signoff_ui, "start_signoff") as ss, \
                patch("pm_core.tui.qa_loop_ui.start_qa") as sq:
            signoff_ui.advance_all(app, [tree])
            auto_start._auto_start_qa_loops(app, [tree])
        sq.assert_not_called()
        assert ss.call_count == (verdict == "PASS")


def test_return_awaiting_on_disk_still_starts_its_run(tmp_path):
    from pm_core.tui import auto_start, signoff_ui
    app, tree = _sched_app(tmp_path, "qa", "qa")
    with patch.object(auto_start, "recorded_qa_verdict",
                      return_value="INPUT_REQUIRED"), \
            patch.object(signoff_ui, "start_signoff") as ss, \
            patch("pm_core.tui.qa_loop_ui.start_qa") as sq:
        signoff_ui.advance_all(app, [tree])
        auto_start._auto_start_qa_loops(app, [tree])
    ss.assert_not_called()
    sq.assert_called_once()
