"""TUI wiring for the pre-review / pre-QA base integration gate.

The gate itself is covered with real git in ``test_base_check.py``; these
tests pin the TUI's handoff behaviour: no review/QA writer while a return is
open, an idle notification is not completion, and the review loop resumes
after a genuine rework.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pm_core import base_check, store
from pm_core.qa_loop import QALoopState


def _return(**over):
    rec = {
        "verdict": "BASE_CONFLICT", "stage": "review", "head": "abc",
        "base_sha": "base", "base_branch": "master", "target_repo": "/repo",
        "conflicts": ["shared.txt"], "conflicts_total": 1,
        "reason": "CONFLICTS with master@base: shared.txt",
        "attempt": 1, "ts": "2026-01-01T00:00:00+00:00",
        "awaiting": None, "resolved_at": None,
    }
    rec.update(over)
    return rec


def _app(tmp_path, prs):
    pm = tmp_path / "pm"
    pm.mkdir(exist_ok=True)
    data = {"project": {"name": "t", "repo": "/tmp/r",
                        "base_branch": "master"},
            "prs": prs}
    store.save(data, pm)
    app = MagicMock()
    app._root = pm
    app._data = data
    app._review_loops = {}
    app._qa_loops = {}
    app._auto_start = False
    app._auto_start_targets = {}
    app._auto_start_all = False
    app._auto_start_run_id = None
    app._self_driving_qa = {}
    app._pane_idle_tracker = MagicMock()
    app._base_completion_checks = {}
    return app


def _pr(status="in_progress", **extra):
    pr = {"id": "pr-001", "title": "T", "branch": "pm/pr-001",
          "status": status, "workdir": "/wd", "notes": []}
    pr.update(extra)
    return pr


def _tracker(idle_since):
    t = MagicMock()
    t.idle_since.return_value = idle_since
    return t


# --- no writer while a return is open -------------------------------------

def test_start_loop_refuses_with_open_base_return(tmp_path):
    from pm_core.tui import review_loop_ui

    app = _app(tmp_path, [_pr(base_return=_return())])
    with patch("pm_core.tmux.in_tmux", return_value=True):
        review_loop_ui._start_loop(app, "pr-001", app._data["prs"][0],
                                   transcript_dir=str(tmp_path / "tdir"))
    assert app._review_loops == {}
    assert any("rework pending" in str(c.args[0])
               for c in app.log_message.call_args_list)


def test_auto_start_review_loops_skips_open_base_return(tmp_path):
    from pm_core.tui import auto_start

    app = _app(tmp_path, [_pr(status="in_review", base_return=_return())])
    app._auto_start = True
    app._auto_start_all = True
    with patch("pm_core.tui.review_loop_ui._start_loop") as start:
        auto_start._auto_start_review_loops(app)
    start.assert_not_called()


def test_auto_start_qa_loops_skips_open_base_return(tmp_path):
    from pm_core.tui import auto_start

    app = _app(tmp_path, [_pr(status="qa", base_return=_return())])
    app._auto_start = True
    app._auto_start_all = True
    with patch("pm_core.tui.qa_loop_ui.start_qa") as start:
        auto_start._auto_start_qa_loops(app)
    start.assert_not_called()


def test_start_qa_refuses_with_open_base_return(tmp_path):
    from pm_core.tui import qa_loop_ui

    app = _app(tmp_path, [_pr(status="in_review", base_return=_return())])
    qa_loop_ui.start_qa(app, "pr-001")
    assert app._qa_loops == {}
    assert any("rework pending" in str(c.args[0])
               for c in app.log_message.call_args_list)


def test_start_loop_repairs_a_raced_in_review_status(tmp_path):
    """A refused loop must leave the PR in_progress, not stranded in_review.

    The TUI's base-return handoff only watches ``in_progress`` PRs, so a
    raced ``in_review`` status (a stale callback wrote it before the return
    landed) would otherwise strand the rework: no reviewer runs, and the
    completion check never sees the PR.
    """
    from pm_core.tui import review_loop_ui

    pr = _pr(status="in_review", base_return=_return())
    app = _app(tmp_path, [pr])
    with patch("pm_core.tmux.in_tmux", return_value=True):
        review_loop_ui._start_loop(app, "pr-001", pr,
                                   transcript_dir=str(tmp_path / "tdir"))
    assert app._review_loops == {}
    stored = store.get_pr(store.load(app._root), "pr-001")
    assert stored["status"] == "in_progress"


# --- idle is not completion ------------------------------------------------

def test_completion_tick_waits_for_settle(tmp_path):
    from pm_core.tui import review_loop_ui

    app = _app(tmp_path, [_pr(base_return=_return())])
    ok, why, _resume = review_loop_ui._base_completion_tick(
        app, "pr-001", app._data["prs"][0], _tracker(time.time()))
    assert not ok
    assert "settle" in why


def test_completion_tick_blocks_on_dirty_workdir(tmp_path):
    from pm_core.tui import review_loop_ui

    pr = _pr(base_return=_return())
    app = _app(tmp_path, [pr])
    old = time.time() - base_check.IDLE_SETTLE_SECONDS - 1
    with patch("pm_core.base_check.git_op_in_progress", return_value=None), \
         patch("pm_core.base_check.tracked_dirty", return_value=True):
        ok, why, _resume = review_loop_ui._base_completion_tick(
            app, "pr-001", pr, _tracker(old))
    assert not ok
    assert "uncommitted edits" in why


def test_completion_tick_runs_the_check_once_and_reports(tmp_path):
    from pm_core.tui import review_loop_ui

    pr = _pr(base_return=_return())
    app = _app(tmp_path, [pr])
    # Execute the worker synchronously.
    app.run_worker.side_effect = lambda fn, **kw: fn()
    old = time.time() - base_check.IDLE_SETTLE_SECONDS - 1
    done = base_check.CompletionResult(True, "clean", resume_loop=True)
    with patch("pm_core.base_check.git_op_in_progress", return_value=None), \
         patch("pm_core.base_check.tracked_dirty", return_value=False), \
         patch("pm_core.base_check.impl_completion",
               return_value=done) as check:
        first = review_loop_ui._base_completion_tick(
            app, "pr-001", pr, _tracker(old))
        second = review_loop_ui._base_completion_tick(
            app, "pr-001", pr, _tracker(old))
    assert not first[0] and "checking" in first[1]
    assert second == (True, "clean", True)
    check.assert_called_once()


def test_completion_tick_rechecks_after_a_new_idle_event(tmp_path):
    """A cached verdict belongs to the idle turn it was computed for.

    A later hook event means the implementation did more work, so a cached
    clean verdict must not start a reviewer beside that fresh turn.
    """
    from pm_core.tui import review_loop_ui

    pr = _pr(base_return=_return())
    app = _app(tmp_path, [pr])
    app.run_worker.side_effect = lambda fn, **kw: fn()
    old = time.time() - base_check.IDLE_SETTLE_SECONDS - 2
    done = base_check.CompletionResult(True, "clean", resume_loop=False)
    with patch("pm_core.base_check.git_op_in_progress", return_value=None), \
         patch("pm_core.base_check.tracked_dirty", return_value=False), \
         patch("pm_core.base_check.impl_completion",
               return_value=done) as check:
        review_loop_ui._base_completion_tick(app, "pr-001", pr, _tracker(old))
        cached = review_loop_ui._base_completion_tick(
            app, "pr-001", pr, _tracker(old))
        assert cached[0] is True
        # A newer idle event (still settled) must be checked afresh.
        fresh = review_loop_ui._base_completion_tick(
            app, "pr-001", pr, _tracker(old + 1))
    assert not fresh[0] and "checking" in fresh[1]
    assert check.call_count == 2


def test_completion_tick_background_test_is_not_completion(tmp_path):
    """An idle turn whose rework did not change the pair stays pending."""
    from pm_core.tui import review_loop_ui

    pr = _pr(base_return=_return())
    app = _app(tmp_path, [pr])
    app.run_worker.side_effect = lambda fn, **kw: fn()
    old = time.time() - base_check.IDLE_SETTLE_SECONDS - 1
    pending = base_check.CompletionResult(
        False, "HEAD and base unchanged since the return")
    with patch("pm_core.base_check.git_op_in_progress", return_value=None), \
         patch("pm_core.base_check.tracked_dirty", return_value=False), \
         patch("pm_core.base_check.impl_completion", return_value=pending):
        review_loop_ui._base_completion_tick(app, "pr-001", pr, _tracker(old))
        ok, why, _resume = review_loop_ui._base_completion_tick(
            app, "pr-001", pr, _tracker(old))
    assert not ok
    assert "unchanged" in why


# --- QA poll cleanup -------------------------------------------------------

def test_poll_qa_state_drops_a_base_returned_run(tmp_path):
    from pm_core.tui import qa_loop_ui

    app = _app(tmp_path, [_pr(status="qa")])
    state = QALoopState(pr_id="pr-001")
    state.running = False
    state.base_returned = True
    state.base_return_reason = "CONFLICTS with master@base: shared.txt"
    app._qa_loops["pr-001"] = state
    with patch("pm_core.tui.qa_loop_ui._resume_incomplete_qa"):
        qa_loop_ui.poll_qa_state(app)
    assert "pr-001" not in app._qa_loops
    assert any("QA not started" in str(c.args[0])
               for c in app.log_message.call_args_list)


# --- resume after a genuine rework ----------------------------------------

def test_resume_returned_loop_starts_a_review_loop(tmp_path):
    from pm_core.tui import review_loop_ui

    pr = _pr(status="in_progress")
    app = _app(tmp_path, [pr])

    def _review_no_window(app_, cmd):
        # ``pm pr review --no-window`` transitions the status only.
        def _apply(d):
            store.get_pr(d, "pr-001")["status"] = "in_review"
        store.locked_update(app_._root, _apply)
        app_._data = store.load(app_._root)

    with patch("pm_core.tui.pr_view.run_command",
               side_effect=_review_no_window), \
         patch.object(review_loop_ui, "_start_loop") as start:
        review_loop_ui._resume_returned_loop(app, "pr-001")
    start.assert_called_once()
    assert start.call_args.args[1] == "pr-001"


def test_resume_returned_loop_does_not_double_start(tmp_path):
    """A loop that already owns the PR must not be started twice.

    ``_start_loop`` has no running-loop guard of its own (its other callers
    check first), so a user ``d`` that won the race in the same tick would
    leave two reviewer writers on one PR.
    """
    from pm_core.tui import review_loop_ui

    pr = _pr(status="in_progress")
    app = _app(tmp_path, [pr])
    app._review_loops["pr-001"] = SimpleNamespace(running=True)
    with patch("pm_core.tui.pr_view.run_command") as run_cmd, \
         patch.object(review_loop_ui, "_start_loop") as start:
        review_loop_ui._resume_returned_loop(app, "pr-001")
    start.assert_not_called()
    run_cmd.assert_not_called()


def test_completion_tick_handles_a_missing_workdir(tmp_path):
    """No workdir must not reach the git helpers with an empty cwd.

    ``subprocess.run(cwd="")`` raises, and this tick runs inside the shared
    poll timer: an exception there would break QA/sign-off polling too.
    """
    from pm_core.tui import review_loop_ui

    pr = _pr(base_return=_return())
    pr.pop("workdir")
    app = _app(tmp_path, [pr])
    old = time.time() - base_check.IDLE_SETTLE_SECONDS - 1
    ok, why, _resume = review_loop_ui._base_completion_tick(
        app, "pr-001", pr, _tracker(old))
    assert not ok
    assert "workdir" in why


def test_poll_impl_idle_catches_up_base_rework_with_auto_start(tmp_path):
    """A manual loop's rework still relaunches when auto-start is enabled.

    ``check_and_start`` only drives PRs inside the auto-start scope, so a
    manual loop on a non-target PR would otherwise strand its ``awaiting``
    base return: nothing relaunches the implementation and every gate refuses
    the review.  The launch claim keeps this one owner even when both
    drivers try.
    """
    from pm_core.tui import review_loop_ui

    pr = _pr("in_progress", base_return=_return(awaiting="impl"))
    app = _app(tmp_path, [pr])
    app._session_name = "pm-test"
    app._pending_merge_prs = set()
    # Auto-start is enabled but this PR is not one of its targets.
    app._auto_start = True
    app._auto_start_all = False
    app._auto_start_targets = {"pr-other": {}}
    tracker = app._pane_idle_tracker
    tracker.is_tracked.return_value = True
    tracker.is_gone.return_value = False
    tracker.is_idle.return_value = True

    with patch("pm_core.tui.review_loop_ui._find_impl_pane",
               return_value="%1"), \
         patch("pm_core.tui.auto_start.get_transcript_dir",
               return_value=str(tmp_path)), \
         patch("pm_core.tui.review_loop_ui._catch_up_base_impl") as catch_up:
        review_loop_ui._poll_impl_idle(app)

    catch_up.assert_called_once_with(app, "pr-001")
    tracker.mark_active.assert_called_with("pr-001")


# --- raced status repair in the schedulers --------------------------------

def test_auto_start_review_loops_repairs_a_raced_in_review_status(tmp_path):
    """Skipping must not leave the rework stranded in in_review.

    The base-return completion handoff only polls in_progress PRs, so an
    in_review PR whose return is open would otherwise get neither a reviewer
    nor a completion check.
    """
    from pm_core.tui import auto_start

    app = _app(tmp_path, [_pr(status="in_review", base_return=_return())])
    app._auto_start = True
    app._auto_start_all = True
    with patch("pm_core.tui.review_loop_ui._start_loop") as start:
        auto_start._auto_start_review_loops(app)
    start.assert_not_called()
    stored = store.get_pr(store.load(app._root), "pr-001")
    assert stored["status"] == "in_progress"


def test_auto_start_qa_loops_repairs_a_raced_qa_status(tmp_path):
    from pm_core.tui import auto_start

    app = _app(tmp_path, [_pr(status="qa", base_return=_return())])
    app._auto_start = True
    app._auto_start_all = True
    with patch("pm_core.tui.qa_loop_ui.start_qa") as start:
        auto_start._auto_start_qa_loops(app)
    start.assert_not_called()
    stored = store.get_pr(store.load(app._root), "pr-001")
    assert stored["status"] == "in_progress"


def test_start_loop_continues_iteration_numbering(tmp_path):
    """A re-review preserves earlier iteration transcripts (evidence)."""
    from pm_core.tui import review_loop_ui

    pr = _pr(status="in_review")
    app = _app(tmp_path, [pr])
    tdir = tmp_path / "tdir"
    tdir.mkdir()
    (tdir / "review-pr-001-i1.jsonl").write_text("{}")
    (tdir / "review-pr-001-i2.jsonl").write_text("{}")
    with patch("pm_core.tmux.in_tmux", return_value=True), \
         patch.object(review_loop_ui, "start_review_loop_background"), \
         patch.object(review_loop_ui, "_ensure_poll_timer"), \
         patch("pm_core.store.find_project_root", return_value=tmp_path), \
         patch("pm_core.runtime_state.set_action_state"):
        review_loop_ui._start_loop(app, "pr-001", pr,
                                   transcript_dir=str(tdir))
    state = app._review_loops["pr-001"]
    assert state.iteration == 2
    assert state.adopt_in_flight is False
