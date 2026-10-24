"""Writers retried on the TUI poll timer never wait for a project.yaml lock
another pm process holds for a long time (RQ38, S48).

Live (S48 story 1, 3ebe4d7a): with ``pm edit`` open (lock held until the
editor quits) a finished NEEDS_WORK run retried ``_transition_pr_status``
on every poll tick.  Each try waited the full 2 s lock timeout on the TUI's
event loop and logged a StoreLockTimeout warning, so arrow keys took ~2 s
and the log got one warning every ~4 s for as long as the editor stayed open.

Those writes now make a single non-blocking attempt (``store.NO_WAIT``): a
held lock keeps the result / follow-up / hand-off pending, says so once, and
the write lands on the first tick after the lock is released.  There is no
separate "is it locked?" probe, so a holder that takes the lock just before
the write cannot make the TUI wait either.  Other callers (CLI, user keys)
keep the default 2 s wait.
"""

import fcntl
import threading
import time
from contextlib import contextmanager
from unittest.mock import patch

from pm_core import store
from pm_core.qa_loop import VERDICT_NEEDS_WORK, VERDICT_PASS
from tests.test_qa_completion_unloadable import (
    _finished_run, _logged, _make_app, _poll, _pr)


@contextmanager
def _held(root):
    """Hold project.yaml.lock the way ``pm edit`` does (own open file)."""
    with open(root / "project.yaml.lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _release_later(root, after):
    """Hold the lock now, release it from a thread *after* seconds."""
    f = open(root / "project.yaml.lock", "a")
    fcntl.flock(f, fcntl.LOCK_EX)

    def rel():
        time.sleep(after)
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()
    t = threading.Thread(target=rel)
    t.start()
    return t


def test_no_wait_tries_once_and_default_still_waits(tmp_path):
    store.save({"project": {"name": "t"}, "plans": [], "prs": []}, tmp_path)
    with _held(tmp_path):
        t0 = time.monotonic()
        try:
            store.locked_update(tmp_path, lambda d: None, timeout=store.NO_WAIT)
        except store.StoreLockTimeout:
            pass
        else:
            raise AssertionError("NO_WAIT write succeeded under a held lock")
        assert time.monotonic() - t0 < 0.2
    # The default (CLI) wait is unchanged: a holder that lets go within 2 s
    # does not fail the write.
    t = _release_later(tmp_path, 0.3)
    store.locked_update(tmp_path, lambda d: d.setdefault("x", 1))
    t.join()
    assert store.load(tmp_path).get("x") == 1


def test_completion_waits_for_a_held_lock_without_blocking(tmp_path):
    from pm_core.tui import qa_loop_ui
    app = _make_app(tmp_path)
    _state, snap = _finished_run(app, tmp_path, VERDICT_NEEDS_WORK)

    with _held(app._root), patch.object(qa_loop_ui, "_log") as log:
        t0 = time.monotonic()
        mirror = _poll(app, 5)
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0, elapsed  # was 2 s per tick (lock timeout)
        warned = [c.args[0] % c.args[1:] for c in log.warning.call_args_list]
        assert not any("StoreLockTimeout" in m for m in warned), warned
        assert len(warned) == 1 and "lock is released" in warned[0], warned
        assert "pr-001" in app._qa_loops
        assert snap.exists()
        assert not _logged(app, "returning to review")
        assert len(_logged(app, "waiting for project.yaml to be unlocked")) == 1
        assert not mirror.called
        assert _pr(app._root)["status"] == "qa"

    _poll(app, 3)
    pr = _pr(app._root)
    assert pr["status"] == "in_review"
    assert len([n for n in pr["notes"] if n["text"].startswith("QA ")]) == 1
    assert len(_logged(app, "returning to review")) == 1
    assert len(_logged(app, "waiting for project.yaml")) == 1
    assert not snap.exists()
    assert "pr-001" not in app._qa_loops


def test_lock_taken_between_the_writes_keeps_the_rest_pending(tmp_path):
    """The lock is free for the transition and taken just before the note
    (the acquisition race a separate probe could not see): the note waits
    without blocking, and is written once, after the release."""
    from pm_core.tui import qa_loop_ui
    app = _make_app(tmp_path)
    _state, snap = _finished_run(app, tmp_path, VERDICT_NEEDS_WORK)
    real = qa_loop_ui._transition_pr_status
    holder = {}

    def transition_then_lock(*a, **k):
        ok = real(*a, **k)
        f = open(app._root / "project.yaml.lock", "a")
        fcntl.flock(f, fcntl.LOCK_EX)
        holder["f"] = f
        return ok

    t0 = time.monotonic()
    with patch.object(qa_loop_ui, "_transition_pr_status",
                      side_effect=transition_then_lock):
        _poll(app, 1)
    _poll(app, 3)
    assert time.monotonic() - t0 < 1.0
    assert _pr(app._root)["status"] == "in_review"
    assert not _pr(app._root)["notes"]
    assert snap.exists() and "pr-001" in app._qa_loops
    assert not _logged(app, "returning to review")
    assert len(_logged(app, "waiting for project.yaml to be unlocked")) == 1

    fcntl.flock(holder["f"], fcntl.LOCK_UN)
    holder["f"].close()
    _poll(app, 3)
    pr = _pr(app._root)
    assert len([n for n in pr["notes"] if n["text"].startswith("QA ")]) == 1
    assert len(_logged(app, "returning to review")) == 1
    assert not snap.exists()


def test_pending_sign_off_follow_up_waits_for_a_held_lock(tmp_path):
    """Note written, sign-off hand-off pending: retried without a lock wait
    and without an "Error:" line per tick, then exactly one hand-off."""
    from pm_core.tui import qa_loop_ui, signoff_ui
    app = _make_app(tmp_path)
    state, snap = _finished_run(app, tmp_path, VERDICT_PASS)
    state._ui_writes_done.add("note")
    state._ui_complete_notified = True
    state._ui_pending.append(lambda: qa_loop_ui._trigger_signoff(app, "pr-001"))

    with patch.object(signoff_ui, "_driven", return_value=True), \
            patch.object(signoff_ui, "step") as step:
        with _held(app._root):
            t0 = time.monotonic()
            for _ in range(4):
                assert qa_loop_ui._completion_waits_for_project(app, state)
            assert time.monotonic() - t0 < 1.0
            assert not _logged(app, "Error:")
            assert len(_logged(app, "waits for project.yaml to be unlocked")) == 1
            step.assert_not_called()
        assert not qa_loop_ui._completion_waits_for_project(app, state)
    assert _pr(app._root)["status"] == "sign_off"
    step.assert_called_once()
    assert not _logged(app, "Error:")


def test_start_signoff_waits_for_a_held_lock(tmp_path):
    from pm_core.tui import signoff_ui
    app = _make_app(tmp_path)
    with patch.object(signoff_ui, "_driven", return_value=True), \
            patch.object(signoff_ui, "step") as step:
        with _held(app._root):
            t0 = time.monotonic()
            for _ in range(3):  # scheduler passes
                assert signoff_ui.start_signoff(
                    app, "pr-001", lock_timeout=store.NO_WAIT) is False
            assert time.monotonic() - t0 < 1.0
            assert not _logged(app, "Error:")
            assert len(_logged(app, "waits for project.yaml to be unlocked")) == 1
            step.assert_not_called()
        signoff_ui.start_signoff(app, "pr-001", lock_timeout=store.NO_WAIT)
    assert _pr(app._root)["status"] == "sign_off"
    step.assert_called_once()


def test_later_sign_off_wait_of_the_same_pr_is_said_again(tmp_path):
    """The "waits" line is said once per wait, not once per PR: a hand-off
    that went through forgets it, so the PR's next hand-off (a later QA
    PASS, e.g. after a sign-off REQA round) that meets a held lock says so
    again instead of waiting silently."""
    from pm_core.tui import signoff_ui
    app = _make_app(tmp_path)

    def _back_to_qa(d):
        store.get_pr(d, "pr-001")["status"] = "qa"
    with patch.object(signoff_ui, "_driven", return_value=True), \
            patch.object(signoff_ui, "step") as step:
        for _ in range(2):
            with _held(app._root):
                assert signoff_ui.start_signoff(
                    app, "pr-001", lock_timeout=store.NO_WAIT) is False
            signoff_ui.start_signoff(app, "pr-001", lock_timeout=store.NO_WAIT)
            assert _pr(app._root)["status"] == "sign_off"
            store.locked_update(app._root, _back_to_qa)
    assert step.call_count == 2
    assert len(_logged(app, "waits for project.yaml to be unlocked")) == 2


def test_one_shot_sign_off_hand_off_rides_out_a_brief_holder(tmp_path):
    """The skip_qa review PASS hands off through ``_maybe_auto_merge`` once;
    nothing retries it.  It keeps the default lock wait, so a pm process
    holding the lock for a moment (a `pm pr note add` from a pane) does not
    lose the hand-off, and a lock held past the wait is an "Error:" line,
    not a "waits" line that promises a retry."""
    from pm_core.tui import signoff_ui
    app = _make_app(tmp_path)
    with patch.object(signoff_ui, "_driven", return_value=True), \
            patch.object(signoff_ui, "step") as step:
        t = _release_later(app._root, 0.3)
        signoff_ui.start_signoff(app, "pr-001")
        t.join()
        step.assert_called_once()
    assert _pr(app._root)["status"] == "sign_off"
    assert not _logged(app, "waits for project.yaml")

    (tmp_path / "held").mkdir()
    app = _make_app(tmp_path / "held")
    with patch.object(signoff_ui, "_driven", return_value=True), \
            patch.object(signoff_ui, "step") as step, _held(app._root):
        assert signoff_ui.start_signoff(app, "pr-001") is False
        step.assert_not_called()
    assert len(_logged(app, "Error:")) == 1
    assert not _logged(app, "waits for project.yaml")


def test_scheduler_pass_hands_off_without_waiting(tmp_path):
    """advance_all retries a QA-passed PR on every pass: one non-blocking
    attempt each, said once."""
    from pm_core.tui import auto_start, signoff_ui
    app = _make_app(tmp_path)
    app._data = store.load(app._root)
    with patch.object(auto_start, "is_enabled", return_value=True), \
            patch.object(auto_start, "in_scope", return_value=True), \
            patch.object(auto_start, "recorded_qa_verdict",
                         return_value="PASS"), \
            patch.object(signoff_ui, "_driven", return_value=True), \
            patch.object(signoff_ui, "step") as step:
        with _held(app._root):
            t0 = time.monotonic()
            for _ in range(3):
                signoff_ui.advance_all(app)
            assert time.monotonic() - t0 < 1.0
            step.assert_not_called()
        signoff_ui.advance_all(app)
    step.assert_called_once()
    assert _pr(app._root)["status"] == "sign_off"
    assert len(_logged(app, "waits for project.yaml to be unlocked")) == 1
    assert not _logged(app, "Error:")


def test_review_hand_off_transition_waits_for_a_held_lock(tmp_path):
    from tests.test_review_qa_handoff_unloadable import (
        _self_driving_app, _status)
    from pm_core.tui import review_loop_ui
    app = _self_driving_app(tmp_path)
    with patch("pm_core.tui.qa_loop_ui.start_qa") as start:
        with _held(app._root), patch.object(review_loop_ui, "_log") as log:
            t0 = time.monotonic()
            for _ in range(4):  # poll ticks while the editor is open
                review_loop_ui._start_qa_after_review(app, "pr-001")
            assert time.monotonic() - t0 < 1.0
            start.assert_not_called()
            assert _status(app) == "in_review"
            assert app._pending_auto_qa["pr-001"] == (
                "transition", store.LOCK_BUSY_REASON)
            waits = [c.args[0] for c in app.log_message.call_args_list
                     if "waiting for project.yaml to be unlocked" in c.args[0]]
            assert len(waits) == 1
            assert log.warning.call_count == 1  # once, not per tick
        review_loop_ui._start_qa_after_review(app, "pr-001")
    start.assert_called_once_with(app, "pr-001", lock_timeout=store.NO_WAIT)
    assert _status(app) == "qa"
    assert app._pending_auto_qa == {}


def test_review_hand_off_launch_waits_for_a_held_lock(tmp_path):
    """Launch phase: the status is already qa, and the QA start must clear a
    sign-off REQA return marker (a locked write).  It neither waits nor
    shows "Error:" per tick; QA starts once after the release."""
    from tests.test_review_qa_handoff_unloadable import _self_driving_app
    from pm_core.tui import qa_loop_ui, review_loop_ui

    def mark(d):
        p = store.get_pr(d, "pr-001")
        p["status"] = "qa"
        p["signoff_return"] = {"awaiting": "qa"}
    app = _self_driving_app(tmp_path)
    store.locked_update(app._root, mark)
    app._pending_auto_qa = {"pr-001": ("launch", "earlier reason")}
    with patch("pm_core.signoff.return_awaiting",
               side_effect=lambda pr: ((pr or {}).get("signoff_return")
                                       or {}).get("awaiting")), \
            patch.object(qa_loop_ui, "start_qa_background") as bg:
        with _held(app._root):
            t0 = time.monotonic()
            for _ in range(4):
                review_loop_ui._start_qa_after_review(app, "pr-001")
            assert time.monotonic() - t0 < 1.0
            bg.assert_not_called()
            assert app._pending_auto_qa["pr-001"] == (
                "launch", store.LOCK_BUSY_REASON)
            assert not _logged(app, "Error:")
            assert len(_logged(app, "waiting for project.yaml to be unlocked")) == 1
        review_loop_ui._start_qa_after_review(app, "pr-001")
    bg.assert_called_once()
    assert app._pending_auto_qa == {}
    rec = store.get_pr(store.load(app._root), "pr-001")["signoff_return"]
    assert rec["awaiting"] is None


def test_recovered_completion_waits_for_a_held_lock(tmp_path):
    """A run that completed while the TUI was down, found by the resume scan
    while the lock is held, is handed to the poll timer at once (no 2 s wait
    in the scan) and keeps its snapshot."""
    from pm_core import qa_loop
    from pm_core.tui import qa_loop_ui
    from tests.test_qa_resume import _make_app as _resume_app, _seed_run
    app = _resume_app(tmp_path)
    app._self_driving_qa = {}
    app._review_loops = {}
    qa_dir = _seed_run(tmp_path, overall=VERDICT_NEEDS_WORK)
    with patch("pathlib.Path.home", return_value=tmp_path), \
            patch.object(qa_loop, "resume_qa_background") as resume_bg, \
            _held(app._root):
        t0 = time.monotonic()
        qa_loop_ui._resume_incomplete_qa(app)
        assert time.monotonic() - t0 < 1.0
    resume_bg.assert_not_called()
    state = app._qa_loops["pr-001"]
    assert state.latest_verdict == VERDICT_NEEDS_WORK
    assert not state._ui_complete_notified  # the poll timer records it
    assert (qa_dir / "qa_resume.json").exists()
    assert _pr(app._root)["status"] == "qa"


def test_shared_enter_qa_status_does_not_wait_for_the_hand_off(tmp_path):
    """start_qa's in_review -> qa write (the helper S47 shares with zz t):
    the hand-off launch (NO_WAIT) fails at once and quietly under a held
    lock; a user key (default wait) still reports the error."""
    from tests.test_review_qa_handoff_unloadable import _self_driving_app
    from pm_core.tui import qa_loop_ui
    app = _self_driving_app(tmp_path)  # pr-001 in_review
    with patch.object(qa_loop_ui, "start_qa_background") as bg:
        with _held(app._root):
            t0 = time.monotonic()
            assert qa_loop_ui.start_qa(
                app, "pr-001", lock_timeout=store.NO_WAIT) is False
            assert time.monotonic() - t0 < 0.5
            assert not _logged(app, "Error:")
            assert qa_loop_ui.start_qa(app, "pr-001") is False  # 2 s wait
            assert len(_logged(app, "Error:")) == 1
        bg.assert_not_called()
        assert qa_loop_ui.start_qa(app, "pr-001", lock_timeout=store.NO_WAIT)
        bg.assert_called_once()
    assert store.get_pr(store.load(app._root), "pr-001")["status"] == "qa"


def test_review_hand_off_wait_line_is_not_hidden_by_the_done_line(tmp_path):
    """The "Review loop done … PASS" line is sticky; the waiting line logged
    right after it must not be dropped by it (S48 story 2: the pm log had it
    only as "(hidden by sticky message)")."""
    from tests.test_review_qa_handoff_unloadable import _self_driving_app
    from pm_core.tui import review_loop_ui
    app = _self_driving_app(tmp_path)
    with patch("pm_core.tui.qa_loop_ui.start_qa"), _held(app._root):
        review_loop_ui._start_qa_after_review(app, "pr-001")
    calls = [c for c in app.log_message.call_args_list
             if "waiting for project.yaml to be unlocked" in c.args[0]]
    assert len(calls) == 1
    assert calls[0].kwargs.get("sticky", 0) > 0 or calls[0].kwargs.get("force")
