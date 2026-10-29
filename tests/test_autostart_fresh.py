"""Explicit fresh autostart (``z a``/``z O``/``z A`` / ``pm autostart fresh``).

A reviewed PR is returned to implementation after user feedback: the live
implementation session is adopted, obsolete review/QA/sign-off state is
retired, and auto-start waits for the current implementation turn before
starting exactly one fresh review.

The repo has no pytest-asyncio plugin: async bodies run via ``asyncio.run``.
"""

import asyncio
import json
import time
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from pm_core import autostart_state as st
from pm_core import store
from pm_core.autostart_state import FRESH_KEY, POLICY_WAIT
from pm_core.qa_loop import QALoopState
from pm_core.review_loop import ReviewLoopState
from pm_core.tui import autostart_fresh
from pm_core.tui import auto_start


OLD = "2026-01-01T00:00:00+00:00"


def _pr(pid="pr-a", status="in_review", **extra):
    d = {"id": pid, "title": f"T {pid}", "branch": f"b-{pid}",
         "status": status, "depends_on": [], "notes": [],
         "workdir": f"/tmp/wd-{pid}", "started_at": OLD}
    d.update(extra)
    return d


class FakeApp:
    def __init__(self, prs, root=None):
        self._data = {"project": {"name": "t", "repo": "/r",
                                  "base_branch": "master"}, "prs": prs}
        self._root = root
        self._auto_start = False
        self._auto_start_targets = {}
        self._auto_start_all = False
        self._auto_start_run_id = None
        self._auto_start_launching = set()
        self._review_loops = {}
        self._qa_loops = {}
        self._self_driving_qa = {}
        self._pending_merge_prs = set()
        self._merge_input_required_prs = set()
        self._session_name = None
        self._pane_idle_tracker = None
        self._review_loop_timer = None
        self._watcher_manager = MagicMock()
        self._watcher_manager.find_by_type.return_value = None
        self.logs = []
        self.workers = []

    def log_message(self, msg, **kw):
        self.logs.append(msg)

    def _update_display(self):
        pass

    def _load_state(self):
        pass

    def set_interval(self, *a, **kw):
        return MagicMock()

    def run_worker(self, coro, *a, **kw):
        self.workers.append(coro)
        if asyncio.iscoroutine(coro):
            coro.close()


@pytest.fixture
def project(tmp_path):
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()
    wd = tmp_path / "wd"
    wd.mkdir()
    store.save({"project": {"name": "t", "repo": "/r",
                            "base_branch": "master"},
                "prs": [_pr(workdir=str(wd))]}, pm_dir)
    return pm_dir


# ---------------------------------------------------------------------------
# Atomic reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_rewinds_and_supersedes_old_evidence(self, project):
        pm_dir = project
        data = store.load(pm_dir)
        pr = store.get_pr(data, "pr-a")
        pr["signoff"] = {"verdict": "SIGNOFF_MERGE", "sha": "abc", "ts": OLD}
        pr["signoff_return"] = {"verdict": "SIGNOFF_REVIEW", "hop": "review",
                                "awaiting": "review", "ts": OLD}
        store.save(data, pm_dir)

        out = autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        assert out["ok"] and out["action"] == "fresh_reset"
        assert out["from_status"] == "in_review"

        pr = store.get_pr(store.load(pm_dir), "pr-a")
        assert pr["status"] == "in_progress"
        marker = st.fresh_marker(pr)
        assert marker["from_status"] == "in_review"
        assert marker["attempt"] == 1
        assert marker["awaiting_handoff"] is True
        assert marker["requested_at"]
        # The old approval is preserved but can never be adopted again.
        assert pr["signoff"]["invalidated"].startswith("superseded by fresh")
        assert pr["signoff_history"][0]["verdict"] == "SIGNOFF_MERGE"
        assert pr["signoff_history"][0]["superseded_reason"] == "fresh-autostart"
        # The open return no longer forces a --fresh impl relaunch.
        assert pr["signoff_return"]["resolved_at"]
        assert pr["signoff_return"]["awaiting"] is None
        # Existing implementation history is preserved.
        assert pr["started_at"] == OLD

        from pm_core.signoff import fresh_recorded_verdict, return_awaiting
        assert fresh_recorded_verdict(pr, "abc") is None
        assert return_awaiting(pr) is None

    def test_repeated_reset_while_waiting_is_idempotent(self, project):
        pm_dir = project
        first = autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        assert first["action"] == "fresh_reset"
        marker = st.fresh_marker(store.get_pr(store.load(pm_dir), "pr-a"))

        second = autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        assert second["ok"] and second["action"] == "already_waiting"
        pr = store.get_pr(store.load(pm_dir), "pr-a")
        assert st.fresh_marker(pr) == marker  # untouched

    def test_reset_after_new_review_starts_a_new_attempt(self, project):
        pm_dir = project
        autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        # Simulate the fresh review having started.
        data = store.load(pm_dir)
        pr = store.get_pr(data, "pr-a")
        pr["status"] = "in_review"
        store.save(data, pm_dir)

        out = autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        assert out["ok"] and out["action"] == "fresh_reset"
        marker = st.fresh_marker(store.get_pr(store.load(pm_dir), "pr-a"))
        assert marker["attempt"] == 2
        assert marker["from_status"] == "in_review"

    def test_repeated_reset_records_a_new_explicit_policy(self, project):
        # `z O` then `z A` while still waiting: same attempt (no second
        # reset), but the restart marker must carry the policy just asked
        # for so a TUI restart re-arms the right target.
        pm_dir = project
        autostart_fresh.reset_pr(pm_dir, "pr-a", "test", policy=st.POLICY_WAIT)
        out = autostart_fresh.reset_pr(pm_dir, "pr-a", "test",
                                       policy=st.POLICY_AUTO)
        assert out["ok"] and out["action"] == "already_waiting"
        marker = st.fresh_marker(store.get_pr(store.load(pm_dir), "pr-a"))
        assert marker["policy"] == st.POLICY_AUTO
        assert marker["attempt"] == 1

    def test_second_attempt_does_not_duplicate_signoff_history(self, project):
        pm_dir = project
        data = store.load(pm_dir)
        store.get_pr(data, "pr-a")["signoff"] = {
            "verdict": "SIGNOFF_MERGE", "sha": "abc", "ts": OLD}
        store.save(data, pm_dir)
        autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        # The fresh review started, then more feedback returned it again.
        data = store.load(pm_dir)
        store.get_pr(data, "pr-a")["status"] = "in_review"
        store.save(data, pm_dir)
        autostart_fresh.reset_pr(pm_dir, "pr-a", "test")

        pr = store.get_pr(store.load(pm_dir), "pr-a")
        assert len(pr["signoff_history"]) == 1

    def test_corrupt_marker_attempt_does_not_abort_the_reset(self, project):
        # ``attempt`` is a provenance counter; a hand-edited marker must not
        # make the reset raise (which would escape as an owner-side error and
        # leave the CLI waiting on a reply it never gets).
        pm_dir = project
        data = store.load(pm_dir)
        store.get_pr(data, "pr-a")[FRESH_KEY] = {"attempt": "not-a-number"}
        store.save(data, pm_dir)
        out = autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        assert out["ok"] and out["action"] == "fresh_reset"
        marker = st.fresh_marker(store.get_pr(store.load(pm_dir), "pr-a"))
        assert marker["attempt"] == 1
        assert marker["awaiting_handoff"] is True

    def test_in_progress_without_marker_is_rejected(self, project):
        pm_dir = project
        data = store.load(pm_dir)
        store.get_pr(data, "pr-a")["status"] = "in_progress"
        store.save(data, pm_dir)
        out = autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        assert not out["ok"] and out["error"] == "not_later_stage"

    def test_terminal_is_rejected(self, project):
        pm_dir = project
        data = store.load(pm_dir)
        store.get_pr(data, "pr-a")["status"] = "merged"
        store.save(data, pm_dir)
        out = autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        assert not out["ok"] and out["error"] == "terminal_pr"

    def test_unknown_is_rejected(self, project):
        out = autostart_fresh.reset_pr(project, "nope", "test")
        assert not out["ok"] and out["error"] == "unknown_pr"


# ---------------------------------------------------------------------------
# Handoff detection
# ---------------------------------------------------------------------------

def _transcript(tmp_path, records):
    sid = "12345678-1234-1234-1234-123456789abc"
    path = tmp_path / f"{sid}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def _missing_transcript(tmp_path):
    """A UUID-named path that was never written (transcript unreadable)."""
    return tmp_path / "12345678-1234-1234-1234-123456789abc.jsonl"


def _complete():
    return {"type": "assistant",
            "message": {"role": "assistant",
                        "content": [{"type": "text", "text": "done"}],
                        "stop_reason": "end_turn"}}


def _busy():
    return {"type": "user", "message": {"role": "user", "content": "more"}}


def _interrupted(ts, text="[Request interrupted by user]"):
    """Claude Code's turn-aborted marker (a list-content user record)."""
    return {"type": "user", "timestamp": ts,
            "message": {"role": "user",
                        "content": [{"type": "text", "text": text}]}}


class _Tracker:
    def __init__(self, path=None, idle=True, tracked=True, gone=False):
        self.path = path
        self.idle = idle
        self.tracked = tracked
        self.gone = gone

    def is_tracked(self, key):
        return self.tracked

    def get_transcript_path(self, key):
        return str(self.path) if self.path else None

    def is_idle(self, key):
        return self.idle

    def is_gone(self, key):
        return self.gone


def _marker_pr(requested_at, status="in_progress"):
    # A fresh attempt is by definition back in implementation: the handoff
    # refuses to advance for any other status (see ``handoff_ready``).
    return {"id": "pr-a", "workdir": "/w", "status": status,
            FRESH_KEY: {"requested_at": requested_at,
                        "awaiting_handoff": True}}


class TestHandoff:
    def test_complete_turn_at_reset_time_is_ready(self, tmp_path):
        path = _transcript(tmp_path, [_complete()])
        pr = _marker_pr(st.now_iso())
        assert autostart_fresh.handoff_ready(None, pr, _Tracker(path))

    def test_busy_turn_is_not_ready_even_with_stale_idle(self, tmp_path):
        path = _transcript(tmp_path, [_busy()])
        pr = _marker_pr(st.now_iso())
        assert not autostart_fresh.handoff_ready(None, pr, _Tracker(path))

    def test_complete_turn_is_authoritative_over_a_stale_idle_flag(
            self, tmp_path):
        # The transcript's end-of-turn record is the handoff even when the
        # hook tracker's idle flag is stale/False (e.g. Stop written last).
        path = _transcript(tmp_path, [_complete()])
        pr = _marker_pr(st.now_iso())
        assert autostart_fresh.handoff_ready(
            None, pr, _Tracker(path, idle=False))

    def test_old_hook_event_does_not_advance(self, tmp_path):
        # No transcript to read, so the hook fallback decides: an event from
        # before ``requested_at`` belongs to the old attempt and cannot count.
        pr = _marker_pr(st.now_iso())
        old_event = {"event_type": "idle_prompt",
                     "timestamp": time.time() - 3600}
        with patch("pm_core.hook_events.read_event", return_value=old_event):
            assert not autostart_fresh.handoff_ready(
                None, pr, _Tracker(_missing_transcript(tmp_path)))

    def test_new_hook_event_advances_when_the_transcript_is_unreadable(
            self, tmp_path):
        # No transcript to read: the (post-reset) hook event is the only
        # signal left, so it must count.
        pr = _marker_pr("2020-01-01T00:00:00Z")
        new_event = {"event_type": "idle_prompt",
                     "timestamp": time.time() + 10}
        with patch("pm_core.hook_events.read_event", return_value=new_event):
            assert autostart_fresh.handoff_ready(
                None, pr, _Tracker(_missing_transcript(tmp_path)))

    def test_newer_turn_blocks_a_stale_hook_event(self, tmp_path):
        # The previous turn's idle_prompt is newer than requested_at, but the
        # user has already started another turn (a follow-up prompt): the
        # transcript is authoritative, so the handoff must wait.
        path = _transcript(tmp_path, [_complete(), _busy()])
        pr = _marker_pr("2020-01-01T00:00:00Z")
        new_event = {"event_type": "idle_prompt",
                     "timestamp": time.time() + 10}
        with patch("pm_core.hook_events.read_event", return_value=new_event):
            assert not autostart_fresh.handoff_ready(
                None, pr, _Tracker(path))

    def test_an_interrupt_before_the_request_ends_the_turn(self, tmp_path):
        # The user aborted a turn before asking for the fresh review and has
        # not typed since: the turn is over, so hand off.  Left as
        # in_progress the handoff would stall forever with the pane sitting
        # at the prompt.
        path = _transcript(tmp_path, [
            _complete(), _interrupted("2020-01-01T00:00:00Z")])
        pr = _marker_pr("2020-01-01T00:01:00Z")
        assert autostart_fresh.handoff_ready(None, pr, _Tracker(path))

    def test_an_interrupt_after_the_request_keeps_waiting(self, tmp_path):
        # The user aborted the feedback turn *after* asking for the fresh
        # review; they may be about to retype, so a review must not start
        # over the aborted work.
        path = _transcript(tmp_path, [
            _complete(), _interrupted("2020-01-01T00:02:00Z")])
        pr = _marker_pr("2020-01-01T00:01:00Z")
        assert not autostart_fresh.handoff_ready(None, pr, _Tracker(path))

    def test_spec_pending_blocks_handoff(self, tmp_path):
        path = _transcript(tmp_path, [_complete()])
        pr = _marker_pr(st.now_iso())
        pr["spec_pending"] = "impl"
        assert not autostart_fresh.handoff_ready(None, pr, _Tracker(path))

    def test_gone_pane_blocks_handoff(self, tmp_path):
        path = _transcript(tmp_path, [_complete()])
        pr = _marker_pr(st.now_iso())
        assert not autostart_fresh.handoff_ready(
            None, pr, _Tracker(path, gone=True))

    def test_signoff_return_impl_blocks_handoff(self, tmp_path):
        # A racing sign-off bounce that still expects a fresh impl launch
        # means the rework session has not run yet: a complete (old) turn
        # must not count as the finished handoff.
        path = _transcript(tmp_path, [_complete()])
        pr = _marker_pr(st.now_iso())
        pr["signoff_return"] = {"verdict": "SIGNOFF_IMPL", "hop": "impl",
                                "awaiting": "impl"}
        assert not autostart_fresh.handoff_ready(None, pr, _Tracker(path))

    def test_an_armed_marker_outside_implementation_does_not_hand_off(
            self, tmp_path):
        # The marker is only meaningful while the PR is back in implementation.
        # ``_auto_review_idle_prs`` consumes it when the review starts, but a
        # consume whose locked write failed leaves it armed; a later bounce to
        # in_progress (e.g. a sign-off return whose relaunch has not run yet)
        # must not hand off a second review over the old turn.
        path = _transcript(tmp_path, [_complete()])
        pr = _marker_pr(st.now_iso(), status="in_review")
        assert not autostart_fresh.handoff_ready(None, pr, _Tracker(path))
        pr["status"] = "qa"
        assert not autostart_fresh.handoff_ready(None, pr, _Tracker(path))
        # In implementation (the only legitimate state) it still advances.
        pr["status"] = "in_progress"
        assert autostart_fresh.handoff_ready(None, pr, _Tracker(path))

    def test_consume_handoff_clears_marker(self, project):
        pm_dir = project
        autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        app = FakeApp([], pm_dir)
        autostart_fresh.consume_handoff(app, "pr-a")
        marker = st.fresh_marker(store.get_pr(store.load(pm_dir), "pr-a"))
        assert marker["awaiting_handoff"] is False
        assert marker["handoff_at"] and marker["review_started_at"]

    def test_consume_handoff_also_updates_the_in_memory_row(self, project):
        # ``_auto_review_idle_prs`` reloads ``app._data`` *before* consuming,
        # so without an in-memory update the status row keeps saying "waiting"
        # (and the fresh branch can be re-entered on a later in_progress
        # bounce) until something else reloads the file.
        pm_dir = project
        autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        app = FakeApp(store.load(pm_dir)["prs"], pm_dir)
        assert st.fresh_awaiting(store.get_pr(app._data, "pr-a"))
        autostart_fresh.consume_handoff(app, "pr-a")
        marker = st.fresh_marker(store.get_pr(app._data, "pr-a"))
        assert marker["awaiting_handoff"] is False
        assert marker["handoff_at"] and marker["review_started_at"]

    def test_pane_transcript_wins_over_the_tracker_copy(self, tmp_path):
        # The run-dir ``impl-<pr>.jsonl`` symlink is *finalized* (replaced by
        # a snapshot) when auto-start is disabled, so the copy stops tracking
        # later turns.  The handoff must read the live pane's own transcript
        # from its start command, not that snapshot.
        from types import SimpleNamespace
        stale_dir = tmp_path / "stale"
        stale_dir.mkdir()
        stale = _transcript(stale_dir, [_busy()])
        live_dir = tmp_path / "live"
        live_dir.mkdir()
        live = _transcript(live_dir, [_complete()])
        pr = _marker_pr(st.now_iso())
        app = SimpleNamespace(_session_name="sess")
        with patch("pm_core.tui.review_loop_ui._find_impl_pane",
                   return_value="%1"), \
             patch("pm_core.claude_launcher.pane_transcript_path",
                   return_value=live):
            assert autostart_fresh.handoff_ready(app, pr, _Tracker(stale))

    def test_falls_back_to_the_tracked_transcript_without_a_pane(
            self, tmp_path):
        # A restarted TUI whose impl window cannot be found still has the
        # tracker's registered path; the handoff must keep working from it.
        from types import SimpleNamespace
        path = _transcript(tmp_path, [_complete()])
        pr = _marker_pr(st.now_iso())
        app = SimpleNamespace(_session_name="sess")
        with patch("pm_core.tui.review_loop_ui._find_impl_pane",
                   return_value=None):
            assert autostart_fresh.handoff_ready(app, pr, _Tracker(path))


class _IdleTracker:
    """Tracker stub exposing only what ``reconcile_idle_status`` touches."""

    def __init__(self, path, idle=True, gone=False, tracked=True):
        self.path = path
        self.idle = idle
        self.gone = gone
        self.tracked = tracked
        self.marked: list[str] = []

    def is_gone(self, key):
        return self.gone

    def is_idle(self, key):
        return self.idle

    def is_tracked(self, key):
        return self.tracked

    def get_transcript_path(self, key):
        return str(self.path) if self.path else None

    def mark_active(self, key):
        self.marked.append(key)
        self.idle = False


class TestIdleStatusReconcile:
    """A stale idle flag must not make the status row claim a finished turn."""

    def test_running_turn_clears_the_stale_idle_flag(self, tmp_path):
        # After a restart the pane is registered fresh and its newest hook
        # event is the *previous* turn's idle_prompt, so the tracker reads
        # idle while the user's feedback turn is still running.  R6's status
        # row would then say "turn complete; starting fresh review" for the
        # whole wait.
        path = _transcript(tmp_path, [_complete(), _busy()])
        tracker = _IdleTracker(path)
        autostart_fresh.reconcile_idle_status(None, _marker_pr(st.now_iso()),
                                              tracker)
        assert tracker.marked == ["pr-a"]
        assert tracker.idle is False

    def test_complete_turn_keeps_the_idle_flag(self, tmp_path):
        # The handoff fires on this same tick; the flag is accurate.
        path = _transcript(tmp_path, [_complete()])
        tracker = _IdleTracker(path)
        autostart_fresh.reconcile_idle_status(None, _marker_pr(st.now_iso()),
                                              tracker)
        assert tracker.marked == []
        assert tracker.idle is True

    def test_gone_pane_is_left_alone(self, tmp_path):
        # ``mark_active`` clears ``gone``; a dead pane must keep its own
        # "implementation window missing" status.
        path = _transcript(tmp_path, [_busy()])
        tracker = _IdleTracker(path, gone=True)
        autostart_fresh.reconcile_idle_status(None, _marker_pr(st.now_iso()),
                                              tracker)
        assert tracker.marked == []

    def test_not_waiting_attempt_is_ignored(self, tmp_path):
        path = _transcript(tmp_path, [_busy()])
        tracker = _IdleTracker(path)
        pr = _marker_pr(st.now_iso())
        pr[FRESH_KEY]["awaiting_handoff"] = False
        autostart_fresh.reconcile_idle_status(None, pr, tracker)
        assert tracker.marked == []

    def test_an_interrupt_before_the_request_keeps_the_idle_flag(self, tmp_path):
        # The aborted turn predates the request, so the transcript reads
        # "complete" and the handoff fires on this same tick: the row must not
        # be flipped back to "waiting for the current implementation turn".
        path = _transcript(tmp_path, [_complete(),
                                      _interrupted("2020-01-01T00:00:00Z")])
        tracker = _IdleTracker(path)
        autostart_fresh.reconcile_idle_status(
            None, _marker_pr("2020-01-01T00:01:00Z"), tracker)
        assert tracker.marked == []
        assert tracker.idle is True


def _poll_app(tmp_path, pr):
    """A minimal app for ``_poll_impl_idle`` with one tracked impl pane."""
    from types import SimpleNamespace
    from pm_core.pane_idle import PaneIdleTracker
    target = tmp_path / "11111111-2222-3333-4444-555555555555.jsonl"
    target.write_text("")
    tracker = PaneIdleTracker()
    tracker.register("pr-a", "%1", str(target))
    app = SimpleNamespace(
        _session_name="sess", _pane_idle_tracker=tracker,
        _data={"prs": [pr]}, _review_loops={},
        _pending_merge_prs=set(), _merge_input_required_prs=set(),
        log_message=lambda *a, **k: None)
    return app, tracker


class TestPollRouting:
    """`_poll_impl_idle` must route fresh attempts through handoff_ready()."""

    def _run(self, tmp_path, ready):
        from pm_core.tui import review_loop_ui
        pr = _pr(status="in_progress",
                 **{FRESH_KEY: {"requested_at": st.now_iso(),
                                "awaiting_handoff": True}})
        app, tracker = _poll_app(tmp_path, pr)
        calls = []
        with patch.object(tracker, "poll", return_value=False), \
             patch("pm_core.tui.auto_start.is_enabled", return_value=True), \
             patch.object(review_loop_ui, "_auto_review_idle_prs",
                          side_effect=lambda _a, pairs: calls.append(pairs)), \
             patch.object(autostart_fresh, "handoff_ready",
                          return_value=ready):
            review_loop_ui._poll_impl_idle(app)
        return calls

    def test_completed_handoff_starts_the_review_path(self, tmp_path):
        # The generic became_idle() flag is False here (poll returns False):
        # only the explicit handoff check may advance a fresh attempt.
        calls = self._run(tmp_path, ready=True)
        assert len(calls) == 1
        assert [pair[0] for pair in calls[0]] == ["pr-a"]

    def test_incomplete_handoff_waits(self, tmp_path):
        assert self._run(tmp_path, ready=False) == []

    def test_failed_launch_is_rate_limited(self, tmp_path, monkeypatch):
        # A launch that does not move the PR out of in_progress (e.g.
        # ``pr review`` erroring) leaves the transcript complete, so without a
        # backoff every ``_poll_impl_idle`` tick would re-run it forever: a
        # subprocess plus two log lines.  The handoff check stays cheap; only
        # the launch is throttled.
        from pm_core.tui import review_loop_ui
        pr = _pr(status="in_progress",
                 **{FRESH_KEY: {"requested_at": st.now_iso(),
                                "awaiting_handoff": True}})
        app, tracker = _poll_app(tmp_path, pr)
        calls = []
        clock = [1000.0]
        monkeypatch.setattr(autostart_fresh.time, "monotonic",
                            lambda: clock[0])
        with patch.object(tracker, "poll", return_value=False), \
             patch("pm_core.tui.auto_start.is_enabled", return_value=True), \
             patch.object(review_loop_ui, "_auto_review_idle_prs",
                          side_effect=lambda _a, pairs: calls.append(pairs)), \
             patch.object(autostart_fresh, "handoff_ready",
                          return_value=True):
            review_loop_ui._poll_impl_idle(app)
            review_loop_ui._poll_impl_idle(app)  # inside the retry window
            clock[0] += autostart_fresh._HANDOFF_RETRY_SECONDS + 1
            review_loop_ui._poll_impl_idle(app)  # window elapsed → retry
        assert len(calls) == 2

    def test_a_stale_idle_flag_is_cleared_before_the_handoff_check(self, tmp_path):
        # A restarted TUI registers the pane fresh; ``poll`` then reads the
        # *previous* turn's idle_prompt as its newest event and reports idle
        # while the user's feedback turn is still running.  The poll must
        # reconcile that with the transcript (the handoff signal) so the
        # status row does not claim "turn complete; starting fresh review".
        from types import SimpleNamespace
        from pm_core.pane_idle import PaneIdleTracker
        from pm_core.tui import review_loop_ui

        native = tmp_path / "11111111-2222-3333-4444-555555555555.jsonl"
        native.write_text(json.dumps(_busy()) + "\n")
        pr = _pr(status="in_progress",
                 **{FRESH_KEY: {"requested_at": st.now_iso(),
                                "awaiting_handoff": True}})
        tracker = PaneIdleTracker()
        tracker.register("pr-a", "%1", str(native))
        app = SimpleNamespace(
            _session_name="sess", _pane_idle_tracker=tracker,
            _data={"prs": [pr]}, _review_loops={},
            _pending_merge_prs=set(), _merge_input_required_prs=set(),
            log_message=lambda *a, **k: None)
        calls = []
        with patch("pm_core.tmux.pane_exists", return_value=True), \
             patch("pm_core.hook_events.read_event",
                   return_value={"event_type": "idle_prompt",
                                 "timestamp": 1.0, "session_id": "s"}), \
             patch("pm_core.tui.review_loop_ui._find_impl_pane",
                   return_value=None), \
             patch.object(review_loop_ui, "_auto_review_idle_prs",
                          side_effect=lambda _a, pairs: calls.append(pairs)):
            review_loop_ui._poll_impl_idle(app)
        assert calls == []
        assert tracker.is_idle("pr-a") is False

    def test_restart_recovers_the_native_transcript(self, tmp_path):
        # A restarted TUI has a new run dir, so ``impl-<pr>.jsonl`` is
        # missing and the symlink registration raises.  A fresh attempt must
        # still adopt the live pane from its start command (native
        # transcript) rather than only trust-watching it — otherwise the
        # wait never advances and the pane is never polled.
        from types import SimpleNamespace
        from pm_core.pane_idle import PaneIdleTracker
        from pm_core.tui import review_loop_ui

        native = tmp_path / "11111111-2222-3333-4444-555555555555.jsonl"
        native.write_text("")
        pr = _pr(status="in_progress",
                 **{FRESH_KEY: {"requested_at": st.now_iso(),
                                "awaiting_handoff": True}})
        tracker = PaneIdleTracker()
        watched = []
        app = SimpleNamespace(
            _session_name="sess", _pane_idle_tracker=tracker,
            _data={"prs": [pr]}, _review_loops={},
            _pending_merge_prs=set(), _merge_input_required_prs=set(),
            log_message=lambda *a, **k: None)
        with patch.object(review_loop_ui, "_find_impl_pane",
                          return_value="%1"), \
             patch("pm_core.tui.auto_start.get_transcript_dir",
                   return_value=tmp_path), \
             patch("pm_core.claude_launcher.pane_transcript_path",
                   return_value=native), \
             patch.object(review_loop_ui, "_watch_untracked_trust",
                          side_effect=lambda *a, **k: watched.append(a)), \
             patch("pm_core.tmux.pane_exists", return_value=True), \
             patch("pm_core.hook_events.read_event", return_value=None), \
             patch("pm_core.tui.auto_start.is_enabled", return_value=True), \
             patch.object(review_loop_ui, "_auto_review_idle_prs"), \
             patch.object(autostart_fresh, "handoff_ready",
                          return_value=False):
            review_loop_ui._poll_impl_idle(app)
        assert tracker.is_tracked("pr-a")
        assert watched == []


class TestHandoffConsumption:
    """R3: the fresh handoff is consumed where the review actually starts.

    ``consume_handoff`` was only covered directly; nothing pinned its call
    site in ``_auto_review_idle_prs``.  That is what makes the status row
    stop saying "waiting" and what keeps a later in_progress bounce from
    being mistaken for this attempt.
    """

    def _app(self, project, awaiting=True):
        data = store.load(project)
        pr = store.get_pr(data, "pr-a")
        pr["status"] = "in_progress"
        if awaiting:
            pr[FRESH_KEY] = {"requested_at": st.now_iso(),
                             "from_status": "in_review", "source": "test",
                             "attempt": 1, "policy": POLICY_WAIT,
                             "awaiting_handoff": True}
        store.save(data, project)
        app = FakeApp(store.load(project)["prs"], project)
        app._auto_start = True
        app._auto_start_targets = {"pr-a": st.make_target_record("test")}
        return app

    def _start_review(self, project, app):
        """Drive _auto_review_idle_prs with the real helper, mocked subprocess."""
        from pm_core.tui import review_loop_ui
        pr = store.get_pr(store.load(project), "pr-a")

        def fake_run_command(_app, cmd, *a, **k):
            # The real helper runs ``pr review --no-window``, which moves the
            # PR to in_review on disk.
            data = store.load(project)
            store.get_pr(data, "pr-a")["status"] = "in_review"
            store.save(data, project)

        with patch("pm_core.tui.pr_view.run_command",
                   side_effect=fake_run_command), \
             patch.object(review_loop_ui, "_start_loop") as start_loop:
            review_loop_ui._auto_review_idle_prs(app, [("pr-a", pr)])
        start_loop.assert_called_once()
        return store.get_pr(store.load(project), "pr-a")

    def test_starting_the_review_consumes_the_marker(self, project):
        app = self._app(project)
        pr = self._start_review(project, app)
        marker = st.fresh_marker(pr)
        assert marker["awaiting_handoff"] is False
        assert marker["handoff_at"]
        assert marker["review_started_at"]
        # The attempt's provenance survives consumption.
        assert marker["attempt"] == 1
        assert marker["requested_at"]

    def test_an_ordinary_review_start_writes_no_marker(self, project):
        # The consume is only for a real fresh attempt: an ordinary idle
        # implementation must not gain a marker (the i1 no-spurious-write
        # contract).
        app = self._app(project, awaiting=False)
        pr = self._start_review(project, app)
        assert st.fresh_marker(pr) == {}


# ---------------------------------------------------------------------------
# fresh_start orchestration
# ---------------------------------------------------------------------------

class TestFreshStart:
    def _app(self, project):
        # Build the in-memory rows from disk so ``_validate`` sees the status
        # a test wrote: a stale in-memory row would let ``reset_pr``'s own
        # disk re-read mask a broken validation (and the all-or-nothing
        # contract of R1.1 would go unpinned).
        app = FakeApp(store.load(project)["prs"], project)
        app._pane_idle_tracker = MagicMock()
        app._pane_idle_tracker.is_tracked.return_value = False
        return app

    def test_waits_when_turn_in_progress(self, project):
        app = self._app(project)
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs") as rev:
            out = autostart_fresh.fresh_start(app, ["pr-a"])
        assert out["ok"] and out["handoff"]["pr-a"] == "waiting"
        rev.assert_not_called()
        assert "pr-a" in auto_start.get_targets(app)
        assert st.fresh_awaiting(store.get_pr(store.load(project), "pr-a"))
        assert any("waiting for the current implementation turn"
                   in line for line in app.logs)

    def test_complete_turn_starts_one_review(self, project):
        app = self._app(project)
        calls = []

        def fake_review(_app, pairs):
            calls.append(pairs)
            # The real helper transitions the PR before starting the loop.
            data = store.load(project)
            store.get_pr(data, "pr-a")["status"] = "in_review"
            store.save(data, project)

        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=True), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs",
                   side_effect=fake_review):
            out = autostart_fresh.fresh_start(app, ["pr-a"])
        assert out["ok"] and out["handoff"]["pr-a"] == "review_started"
        assert len(calls) == 1
        assert calls[0][0][0] == "pr-a"

    def test_dead_pane_does_not_hand_off_immediately(self, project, tmp_path):
        # A pane that died since the last poll leaves a stale "live" tracker
        # entry whose transcript still ends in a completed turn.  The
        # immediate handoff must poll first (as ``_poll_impl_idle`` does) and
        # wait for the scheduler's relaunch instead of starting a review over
        # the old, unreworked code.
        from pm_core.pane_idle import PaneIdleTracker

        native = tmp_path / "11111111-2222-3333-4444-555555555555.jsonl"
        native.write_text(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": "done"}]},
        }) + "\n")
        app = self._app(project)
        tracker = PaneIdleTracker()
        tracker.register("pr-a", "%1", str(native))
        app._pane_idle_tracker = tracker
        with patch("pm_core.pane_idle.tmux_mod.pane_exists",
                   return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs") as rev:
            out = autostart_fresh.fresh_start(app, ["pr-a"])
        rev.assert_not_called()
        assert out["ok"] and out["handoff"]["pr-a"] == "waiting"
        assert tracker.is_gone("pr-a")

    def test_repeated_call_does_not_duplicate(self, project):
        app = self._app(project)
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs") as rev:
            first = autostart_fresh.fresh_start(app, ["pr-a"])
            second = autostart_fresh.fresh_start(app, ["pr-a"])
        assert first["changes"][0]["action"] == "fresh_reset"
        assert second["changes"][0]["action"] == "already_waiting"
        rev.assert_not_called()

    def test_two_already_waiting_prs_read_as_a_plural(self, project):
        # The all-already-waiting confirmation is the only message built from
        # the whole call ("Auto-start: pr-a, pr-b already waiting for their
        # implementation turn"), so it must agree in number.
        data = store.load(project)
        data["prs"].append(_pr("pr-b", workdir=str(project.parent / "wd-b")))
        store.save(data, project)
        app = FakeApp(store.load(project)["prs"], project)
        app._pane_idle_tracker = MagicMock()
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            autostart_fresh.fresh_start(app, ["pr-a", "pr-b"])
            app.logs.clear()
            out = autostart_fresh.fresh_start(app, ["pr-a", "pr-b"])
        assert [c["action"] for c in out["changes"]] == ["already_waiting"] * 2
        assert any("already waiting for their implementation turn" in line
                   for line in app.logs)

    def test_mixed_call_names_each_pr_by_what_happened(self, project):
        # A call can reset one PR and leave another already waiting.  The
        # confirmation must not claim the waiting PR was returned to
        # implementation.
        data = store.load(project)
        data["prs"].append(_pr("pr-b", status="in_progress",
                               workdir=str(project.parent / "wd-b"),
                               **{FRESH_KEY: {"requested_at": st.now_iso(),
                                              "awaiting_handoff": True}}))
        store.save(data, project)
        app = FakeApp(store.load(project)["prs"], project)
        app._pane_idle_tracker = MagicMock()
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            out = autostart_fresh.fresh_start(app, ["pr-a", "pr-b"])
        assert [c["action"] for c in out["changes"]] == [
            "fresh_reset", "already_waiting"]
        line = next(line for line in app.logs
                    if line.startswith("Auto-start: fresh run"))
        assert "fresh run for pr-a — returned to implementation" in line
        assert "pr-b already waiting for its implementation turn" in line
        assert "fresh run for pr-a, pr-b" not in line

    def test_merge_in_progress_is_refused(self, project):
        app = self._app(project)
        app._pending_merge_prs.add("pr-a")
        out = autostart_fresh.fresh_start(app, ["pr-a"])
        assert not out["ok"] and out["error"] == "merge_in_progress"
        # Nothing changed.
        pr = store.get_pr(store.load(project), "pr-a")
        assert pr["status"] == "in_review"
        assert not auto_start.get_targets(app)

    def test_merge_input_required_is_refused(self, project):
        # R8's third in-flight condition: the merge window is blocked on an
        # INPUT_REQUIRED answer.  The in-memory set alone must refuse.
        app = self._app(project)
        app._merge_input_required_prs.add("pr-a")
        out = autostart_fresh.fresh_start(app, ["pr-a"])
        assert not out["ok"] and out["error"] == "merge_in_progress"
        assert store.get_pr(store.load(project), "pr-a")["status"] == "in_review"
        assert not auto_start.get_targets(app)

    def test_merge_window_alone_is_refused(self, project):
        # R8 also covers a merge whose window is live but whose in-memory
        # sets were lost (e.g. a restarted TUI): the window check alone must
        # refuse the reset rather than tear state out from under it.
        app = self._app(project)
        with patch("pm_core.tui.review_loop_ui._merge_window_exists",
                   return_value=True):
            out = autostart_fresh.fresh_start(app, ["pr-a"])
        assert not out["ok"] and out["error"] == "merge_in_progress"
        assert store.get_pr(store.load(project), "pr-a")["status"] == "in_review"
        assert not auto_start.get_targets(app)

    def test_pending_pr_is_refused(self, project):
        # Save first, then build the app from disk: the refusal must come
        # from ``_validate`` (the all-or-nothing pass), not from
        # ``reset_pr``'s own stage re-check.
        data = store.load(project)
        store.get_pr(data, "pr-a")["status"] = "pending"
        store.save(data, project)
        app = self._app(project)
        out = autostart_fresh.fresh_start(app, ["pr-a"])
        assert not out["ok"] and out["error"] == "not_later_stage"
        # ``invalid`` is only set by the up-front pass; ``reset_pr``'s own
        # stage re-check reports the failure without it.
        assert out["invalid"] == ["pr-a"]
        assert store.get_pr(store.load(project), "pr-a")["status"] == "pending"
        assert not auto_start.get_targets(app)

    def test_pr_without_a_workdir_is_refused(self, project):
        # R1.1: no workdir means no implementation session to adopt, so the
        # whole call must be rejected before anything changes.
        data = store.load(project)
        store.get_pr(data, "pr-a")["workdir"] = ""
        store.save(data, project)
        app = self._app(project)
        out = autostart_fresh.fresh_start(app, ["pr-a"])
        assert not out["ok"] and out["error"] == "no_workdir"
        assert store.get_pr(store.load(project), "pr-a")["status"] == "in_review"
        assert not auto_start.get_targets(app)

    def test_validation_is_all_or_nothing_for_a_wrong_status_pr(self, project):
        # A non-terminal PR in the wrong stage alongside a valid one must
        # reject the whole call (R1.1) — the valid PR is not reset and no
        # target is added.  ``reset_pr`` would have rejected it too, but by
        # then the other PRs in the call are already on disk (the i4
        # partial-failure contract), so the up-front pass is what keeps
        # "nothing changed" true for an invalid set.
        data = store.load(project)
        data["prs"].append(_pr("pr-b", status="pending",
                               workdir=str(project.parent / "wd-b")))
        store.save(data, project)
        app = self._app(project)
        out = autostart_fresh.fresh_start(app, ["pr-a", "pr-b"])
        assert not out["ok"] and out["error"] == "not_later_stage"
        assert out["invalid"] == ["pr-b"]
        assert store.get_pr(store.load(project), "pr-a")["status"] == "in_review"
        assert not auto_start.get_targets(app)

    @pytest.mark.parametrize("stage", ["qa", "sign_off"])
    def test_rewinds_from_every_later_stage(self, project, stage):
        # R1: a fresh request from qa / sign_off starts a new attempt, not
        # only from in_review (the reported #250 state).
        data = store.load(project)
        store.get_pr(data, "pr-a")["status"] = stage
        store.save(data, project)
        app = self._app(project)
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs") as rev:
            out = autostart_fresh.fresh_start(app, ["pr-a"])
        assert out["ok"]
        assert out["changes"][0]["action"] == "fresh_reset"
        assert out["changes"][0]["from_status"] == stage
        rev.assert_not_called()
        pr = store.get_pr(store.load(project), "pr-a")
        assert pr["status"] == "in_progress"
        assert st.fresh_marker(pr)["from_status"] == stage
        assert st.fresh_awaiting(pr)

    def test_one_invalid_id_changes_nothing(self, project):
        # Validation is all-or-nothing: a bad id in the set must not reset
        # (or add a target for) the valid one.
        data = store.load(project)
        data["prs"].append(_pr("pr-b", status="merged",
                               workdir=str(project.parent / "wd-b")))
        store.save(data, project)
        app = FakeApp(store.load(project)["prs"], project)
        app._pane_idle_tracker = MagicMock()

        out = autostart_fresh.fresh_start(app, ["pr-a", "pr-b"])
        assert not out["ok"] and out["error"] == "terminal_pr"
        assert store.get_pr(store.load(project), "pr-a")["status"] == "in_review"
        assert not auto_start.get_targets(app)

    def test_partial_reset_failure_is_reported(self, project):
        # Validation reads the TUI's in-memory rows; the reset re-reads disk
        # under the lock.  A PR that changed underneath (merged meanwhile)
        # fails its reset — the others must still be reset and the failure
        # must be reported so the CLI can print it.
        data = store.load(project)
        data["prs"].append(_pr("pr-b", workdir=str(project.parent / "wd-b")))
        store.save(data, project)
        app = FakeApp(store.load(project)["prs"], project)
        app._pane_idle_tracker = MagicMock()
        app._pane_idle_tracker.is_tracked.return_value = False
        # On disk pr-b has already merged; app._data still says in_review.
        on_disk = store.load(project)
        store.get_pr(on_disk, "pr-b")["status"] = "merged"
        store.save(on_disk, project)

        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            out = autostart_fresh.fresh_start(app, ["pr-a", "pr-b"])
        assert out["ok"]
        assert [c["pr_id"] for c in out["changes"]] == ["pr-a"]
        assert out["failed"][0]["pr_id"] == "pr-b"
        assert out["failed"][0]["error"] == "terminal_pr"
        assert store.get_pr(store.load(project), "pr-a")["status"] == "in_progress"
        assert auto_start.get_targets(app) == ["pr-a"]
        # The TUI key path only shows the log line: the failure must be in it
        # (the CLI additionally prints ``failed:`` lines from the payload).
        assert any("failed: pr-b (terminal_pr)" in line for line in app.logs)

    def test_a_raising_reset_is_a_per_pr_failure(self, project):
        # ``reset_pr`` handles the expected store errors itself; anything
        # else must not abort the loop *after* another PR was already reset
        # on disk (that PR's reset would be lost from the reply, its old
        # state unretired and its target never added).
        data = store.load(project)
        data["prs"].append(_pr("pr-b", workdir=str(project.parent / "wd-b")))
        store.save(data, project)
        app = FakeApp(store.load(project)["prs"], project)
        app._pane_idle_tracker = MagicMock()
        app._pane_idle_tracker.is_tracked.return_value = False

        real_reset = autostart_fresh.reset_pr

        def flaky(root, pr_id, source, policy=None):
            if pr_id == "pr-b":
                raise RuntimeError("boom")
            return real_reset(root, pr_id, source, policy=policy)

        with patch.object(autostart_fresh, "reset_pr", side_effect=flaky), \
             patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            out = autostart_fresh.fresh_start(app, ["pr-a", "pr-b"])
        assert out["ok"]
        assert [c["pr_id"] for c in out["changes"]] == ["pr-a"]
        assert out["failed"][0]["pr_id"] == "pr-b"
        assert out["failed"][0]["error"] == "internal"
        assert store.get_pr(store.load(project), "pr-a")["status"] == "in_progress"
        assert auto_start.get_targets(app) == ["pr-a"]
        assert any("failed: pr-b (internal)" in line for line in app.logs)

    def test_new_target_policies_match_the_z_keys(self, project):
        app = self._app(project)
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            autostart_fresh.fresh_start(
                app, ["pr-a"], policy=st.POLICY_AUTO, source="key:zA")
        assert auto_start.target_policy(app, "pr-a") == st.POLICY_AUTO
        assert not st.is_wait_target(
            app._auto_start_targets["pr-a"])

    def test_z_o_forces_wait_for_merge(self, project):
        app = self._app(project)
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            autostart_fresh.fresh_start(
                app, ["pr-a"], policy=st.POLICY_WAIT, source="key:zO")
        assert auto_start.target_policy(app, "pr-a") == POLICY_WAIT
        assert st.is_wait_target(app._auto_start_targets["pr-a"])

    def test_explicit_policy_overrides_an_existing_target(self, project):
        app = self._app(project)
        app._auto_start_targets["pr-a"] = st.make_target_record("cli")
        app._auto_start = True
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            autostart_fresh.fresh_start(
                app, ["pr-a"], policy=st.POLICY_AUTO)
        assert auto_start.target_policy(app, "pr-a") == st.POLICY_AUTO

    def test_z_a_defaults_a_new_target_to_wait_for_merge(self, project):
        # `z a` passes no explicit policy: a new target gets the manual-merge
        # default (and the marker records it for a restart re-arm).
        app = self._app(project)
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            autostart_fresh.fresh_start(
                app, ["pr-a"], policy=None, source="key:za")
        assert auto_start.target_policy(app, "pr-a") == POLICY_WAIT
        marker = st.fresh_marker(store.get_pr(store.load(project), "pr-a"))
        assert marker["policy"] == POLICY_WAIT

    def test_z_a_preserves_an_existing_wait_for_merge_target(self, project):
        # `z a` must not silently downgrade a wait-for-merge target (whose
        # hold covers its whole dependency chain) to a single stop mark.
        app = self._app(project)
        auto_start.add_targets(app, ["pr-a"], policy=st.POLICY_WAIT,
                               source="test")
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            autostart_fresh.fresh_start(
                app, ["pr-a"], policy=None, source="key:za")
        assert auto_start.target_policy(app, "pr-a") == st.POLICY_WAIT
        marker = st.fresh_marker(store.get_pr(store.load(project), "pr-a"))
        assert marker["policy"] == st.POLICY_WAIT

    def test_z_a_preserves_an_existing_auto_merge_target(self, project):
        app = self._app(project)
        auto_start.add_targets(app, ["pr-a"], policy=st.POLICY_AUTO,
                               source="test")
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            autostart_fresh.fresh_start(
                app, ["pr-a"], policy=None, source="key:za")
        assert auto_start.target_policy(app, "pr-a") == st.POLICY_AUTO
        # The marker must record the preserved policy too: ``resume_pending``
        # re-arms the target from it after a TUI restart, so a marker left at
        # the wait-for-merge default would silently downgrade the target.
        marker = st.fresh_marker(store.get_pr(store.load(project), "pr-a"))
        assert marker["policy"] == st.POLICY_AUTO

    def test_fresh_leaves_unrelated_targets_alone(self, project):
        # A fresh reset must not disturb another target's policy or status.
        data = store.load(project)
        data["prs"].append(_pr("pr-b", workdir=str(project.parent / "wd-b")))
        store.save(data, project)
        app = FakeApp(store.load(project)["prs"], project)
        app._pane_idle_tracker = MagicMock()
        auto_start.add_targets(app, ["pr-b"], policy=st.POLICY_AUTO,
                               source="test")
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            autostart_fresh.fresh_start(app, ["pr-a"])
        assert auto_start.target_policy(app, "pr-b") == st.POLICY_AUTO
        assert store.get_pr(store.load(project), "pr-b")["status"] == "in_review"
        assert "pr-a" in auto_start.get_targets(app)
        assert "pr-b" in auto_start.get_targets(app)


# ---------------------------------------------------------------------------
# z O / z A key wiring
# ---------------------------------------------------------------------------

class _KeyApp:
    """Minimal app for calling the TUI's bound action methods directly."""

    def __init__(self, z, pr_id):
        self._z = z
        self._pr_id = pr_id
        self.logs = []
        self.workers = []

    def _consume_z(self):
        return self._z

    def _fresh_autostart_from_key(self, *args, **kwargs):
        # The bound action methods call this helper on ``self``; bind the real
        # implementation to this duck-typed app.
        from pm_core.tui.app import ProjectManagerApp
        return ProjectManagerApp._fresh_autostart_from_key(
            self, *args, **kwargs)

    def query_one(self, *_a, **_k):
        from types import SimpleNamespace
        return SimpleNamespace(selected_pr_id=self._pr_id)

    def log_message(self, msg, **kw):
        self.logs.append(msg)

    def run_worker(self, coro, *a, **kw):
        self.workers.append(coro)
        if asyncio.iscoroutine(coro):
            coro.close()


class TestKeyBindings:
    """`z a`/`z O`/`z A` are the fresh variants; plain `a`/`O`/`A` keep their
    meaning."""

    def _fresh_calls(self, monkeypatch):
        calls = []

        def fake(app, ids, policy=None, source=None):
            calls.append((ids, policy, source))
            return {"ok": True}

        monkeypatch.setattr(autostart_fresh, "fresh_start", fake)
        return calls

    def test_z_lower_a_requests_fresh_keeping_the_policy(self, monkeypatch):
        # `z a` is the generic fresh autostart: policy=None preserves an
        # existing target's policy (wait_for_merge included) and defaults a
        # new target to wait_for_merge.
        from pm_core.tui.app import ProjectManagerApp
        calls = self._fresh_calls(monkeypatch)
        ProjectManagerApp.action_show_auto_runs(_KeyApp(z=1, pr_id="pr-a"))
        assert calls == [(["pr-a"], None, "key:za")]

    def test_z_upper_a_requests_auto_merge_fresh(self, monkeypatch):
        from pm_core.tui.app import ProjectManagerApp
        calls = self._fresh_calls(monkeypatch)
        ProjectManagerApp.action_toggle_auto_start(_KeyApp(z=1, pr_id="pr-a"))
        assert calls == [(["pr-a"], st.POLICY_AUTO, "key:zA")]

    def test_z_upper_o_requests_wait_for_merge_fresh(self, monkeypatch):
        from pm_core.tui.app import ProjectManagerApp
        calls = self._fresh_calls(monkeypatch)
        ProjectManagerApp.action_auto_sequence_pr(_KeyApp(z=1, pr_id="pr-a"))
        assert calls == [(["pr-a"], st.POLICY_WAIT, "key:zO")]

    def test_plain_a_opens_the_runs_popup(self, monkeypatch):
        from pm_core.tui.app import ProjectManagerApp
        opened = []
        monkeypatch.setattr(auto_start, "open_runs_popup",
                            lambda app: opened.append(app))
        app = _KeyApp(z=0, pr_id="pr-a")
        ProjectManagerApp.action_show_auto_runs(app)
        assert opened == [app]

    def test_plain_upper_a_still_toggles(self, monkeypatch):
        # Plain ``A`` keeps its continuation semantics (toggle auto-merge);
        # only ``z A`` is the fresh reset.
        from pm_core.tui.app import ProjectManagerApp
        sentinel = object()
        monkeypatch.setattr(auto_start, "toggle",
                            lambda app, selected_pr_id=None: sentinel)
        app = _KeyApp(z=0, pr_id="pr-a")
        ProjectManagerApp.action_toggle_auto_start(app)
        assert app.workers == [sentinel]

    def test_plain_upper_o_still_arms_the_sequence(self, monkeypatch):
        # Plain ``O`` keeps its continuation semantics (arm a wait-for-merge
        # auto-sequence target); only ``z O`` is the fresh reset.
        from pm_core.tui.app import ProjectManagerApp
        sentinel = object()
        monkeypatch.setattr(auto_start, "auto_sequence_for_pr",
                            lambda app, pr_id: sentinel)
        app = _KeyApp(z=0, pr_id="pr-a")
        ProjectManagerApp.action_auto_sequence_pr(app)
        assert app.workers == [sentinel]

    def test_z_lower_a_without_a_selection_does_nothing(self, monkeypatch):
        from pm_core.tui.app import ProjectManagerApp
        calls = self._fresh_calls(monkeypatch)
        app = _KeyApp(z=1, pr_id=None)
        ProjectManagerApp.action_show_auto_runs(app)
        assert calls == []
        assert any("No PR selected" in line for line in app.logs)

    def test_z_upper_a_without_a_selection_does_nothing(self, monkeypatch):
        from pm_core.tui.app import ProjectManagerApp
        calls = self._fresh_calls(monkeypatch)
        app = _KeyApp(z=1, pr_id=None)
        ProjectManagerApp.action_toggle_auto_start(app)
        assert calls == []
        assert any("No PR selected" in line for line in app.logs)

    def test_a_raising_fresh_start_is_logged_not_raised(self, monkeypatch):
        # The key path must never traceback into Textual: a destructive
        # action that fails has to say so on the log line and leave the app
        # usable.
        from pm_core.tui.app import ProjectManagerApp

        def boom(*_a, **_k):
            raise RuntimeError("store exploded")

        monkeypatch.setattr(autostart_fresh, "fresh_start", boom)
        app = _KeyApp(z=1, pr_id="pr-a")
        ProjectManagerApp.action_show_auto_runs(app)  # must not raise
        assert any("Auto-start fresh failed: store exploded" in line
                   for line in app.logs)

    def test_a_refused_fresh_start_names_the_reason(self, monkeypatch):
        # A rejection (wrong stage, merge in flight, ...) must reach the log
        # line with its stage-specific message, not fail silently.
        from pm_core.tui.app import ProjectManagerApp
        monkeypatch.setattr(
            autostart_fresh, "fresh_start",
            lambda *_a, **_k: {"ok": False, "error": "not_later_stage",
                               "message": "pr-a is pending; fresh autostart "
                                          "applies to in_review / qa / "
                                          "sign_off PRs"})
        app = _KeyApp(z=1, pr_id="pr-a")
        ProjectManagerApp.action_show_auto_runs(app)
        assert any("pr-a is pending" in line for line in app.logs)


class _PrefixApp:
    """Minimal app for the App-level ``on_key`` prefix handler."""

    def __init__(self, z):
        self._z_count = z
        self._z_cancel_timer = None
        self._w_mode = False
        self._y_mode = False
        self._command_pending = False
        self.screen_stack = [object()]
        self.cleared = 0
        self.timers = []

    def query_one(self, *_a, **_k):
        from types import SimpleNamespace
        return SimpleNamespace(has_focus=False)

    def _clear_prefix_hint(self):
        self.cleared += 1

    # Bind the real timer methods rather than re-stating them: the prefix
    # tests then exercise the production bodies.  (Only the ``_z_count`` /
    # ``_clear_prefix_hint`` bookkeeping is observable through the duck type,
    # so a copy here would let the real bodies regress unnoticed.)
    def _stop_z_timer(self):
        from pm_core.tui.app import ProjectManagerApp
        return ProjectManagerApp._stop_z_timer(self)

    def _cancel_z_mode(self):
        from pm_core.tui.app import ProjectManagerApp
        return ProjectManagerApp._cancel_z_mode(self)

    def log_message(self, *_a, **_k):
        return 0

    def set_timer(self, delay, callback, *_a, **_k):
        self.timers.append((delay, callback))
        return MagicMock()


class _KeyEvent:
    def __init__(self, key, character=None):
        self.key = key
        self.character = character

    def prevent_default(self):
        pass

    def stop(self):
        pass


class TestPrefixCancellation:
    """A stale ``z`` prefix must not arm the destructive fresh variant."""

    def test_unrelated_key_cancels_the_prefix(self):
        from pm_core.tui.app import ProjectManagerApp
        app = _PrefixApp(z=1)
        ProjectManagerApp.on_key(app, _KeyEvent("j", "j"))
        assert app._z_count == 0
        assert app.cleared == 1

    def test_z_action_key_keeps_the_prefix(self):
        from pm_core.tui.app import ProjectManagerApp
        app = _PrefixApp(z=1)
        ProjectManagerApp.on_key(app, _KeyEvent("A", "A"))
        assert app._z_count == 1
        assert app.cleared == 0

    def test_every_z_consuming_key_keeps_the_prefix(self):
        # Every binding whose action calls ``_consume_z()`` must keep the
        # prefix.  Otherwise ``z e``/``z v``/``z c`` ... silently lose their
        # "kill existing before next" behaviour.
        from pm_core.tui.app import ProjectManagerApp
        for key in ("s", "S", "d", "e", "v", "n", "L", "m", "H", "c",
                    "t", "a", "A", "O"):
            app = _PrefixApp(z=1)
            ProjectManagerApp.on_key(app, _KeyEvent(key, key))
            assert app._z_count == 1, key
            assert app.cleared == 0, key

    def test_the_z_key_set_matches_the_consume_z_callers(self):
        # The hand-maintained list above has drifted before (i2's set omitted
        # keys whose handlers consume z; ``q``/``t`` were nearly confused).
        # Derive the set from the source instead: for every single-key binding
        # whose action — directly or through a ``pane_ops``/``pr_view``/
        # ``qa_loop_ui`` helper — calls ``_consume_z()``, the key must be in
        # ``_Z_PREFIX_KEYS``, and every key in the set must be such a binding.
        import inspect
        from pm_core.tui import pane_ops, pr_view, qa_loop_ui
        from pm_core.tui.app import ProjectManagerApp, _Z_PREFIX_KEYS

        helpers = (pane_ops, pr_view, qa_loop_ui)

        def consumes(fn) -> bool:
            try:
                return "_consume_z(" in inspect.getsource(fn)
            except (OSError, TypeError):
                return False

        def action_consumes(action: str) -> bool:
            fn = getattr(ProjectManagerApp, f"action_{action}", None)
            if fn is None:
                return False
            if consumes(fn):
                return True
            src = inspect.getsource(fn)
            for mod in helpers:
                short = mod.__name__.rsplit(".", 1)[-1]
                for name, obj in vars(mod).items():
                    if (inspect.isfunction(obj) and consumes(obj)
                            and f"{short}.{name}" in src):
                        return True
            return False

        derived = {b.key for b in ProjectManagerApp.BINDINGS
                   if len(b.key) == 1 and action_consumes(b.action)}
        assert derived == set(_Z_PREFIX_KEYS)

    def test_non_z_action_key_cancels_the_prefix(self):
        # ``i`` (sign-off), ``Y`` (cleanup), ``g`` (merge) and ``p`` (plans)
        # never consume z; they must not leave a stale prefix armed for a
        # later destructive fresh-autostart key.
        from pm_core.tui.app import ProjectManagerApp
        for key in ("i", "Y", "g", "p"):
            app = _PrefixApp(z=1)
            ProjectManagerApp.on_key(app, _KeyEvent(key, key))
            assert app._z_count == 0, key

    def test_prefix_expires_after_the_chord_window(self):
        # Navigation keys (j/k/arrows) are stopped by the focused widget
        # before ``on_key`` sees them, so the key-set cancellation above
        # cannot fire for them.  The prefix must expire on its own.
        from pm_core.tui.app import ProjectManagerApp
        app = _PrefixApp(z=1)
        ProjectManagerApp._cancel_z_mode(app)
        assert app._z_count == 0
        assert app.cleared == 1

    def test_pressing_z_arms_and_consuming_stops_the_timer(self):
        from pm_core.tui.app import ProjectManagerApp, _Z_PREFIX_TIMEOUT
        app = _PrefixApp(z=0)
        ProjectManagerApp.on_key(app, _KeyEvent("z", "z"))
        assert app._z_count == 1
        assert app._z_cancel_timer is not None
        # The timer must be armed with the chord window and the real cancel
        # callback — a wrong delay or a no-op callback would leave a forgotten
        # ``z`` armed for a later destructive key, which the direct
        # ``_cancel_z_mode`` test above cannot detect.
        assert app.timers == [(_Z_PREFIX_TIMEOUT, app._cancel_z_mode)]
        assert ProjectManagerApp._consume_z(app) == 1
        assert app._z_cancel_timer is None


# ---------------------------------------------------------------------------
# Restart recovery
# ---------------------------------------------------------------------------

class TestResume:
    def test_resume_pending_readds_target_with_recorded_policy(self, project):
        # First attempt, then simulate a plain TUI restart (targets are
        # in-memory and lost).
        app = FakeApp(store.load(project)["prs"], project)
        app._pane_idle_tracker = MagicMock()
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            autostart_fresh.fresh_start(
                app, ["pr-a"], policy=st.POLICY_AUTO, source="key:zA")

        restarted = FakeApp(store.load(project)["prs"], project)
        restarted._pane_idle_tracker = MagicMock()
        assert auto_start.get_targets(restarted) == []
        resumed = autostart_fresh.resume_pending(restarted)
        assert resumed == ["pr-a"]
        assert auto_start.target_policy(restarted, "pr-a") == st.POLICY_AUTO
        assert st.fresh_awaiting(
            store.get_pr(store.load(project), "pr-a"))

    def test_resume_pending_is_idempotent(self, project):
        # The restart hook runs once per mount, but a repeated scan must not
        # duplicate the target or report the PR again.
        autostart_fresh.reset_pr(project, "pr-a", "test")
        app = FakeApp(store.load(project)["prs"], project)
        assert autostart_fresh.resume_pending(app) == ["pr-a"]
        assert autostart_fresh.resume_pending(app) == []
        assert auto_start.get_targets(app) == ["pr-a"]

    def test_resume_skips_consumed_attempts(self, project):
        app = FakeApp(store.load(project)["prs"], project)
        autostart_fresh.reset_pr(project, "pr-a", "test")
        autostart_fresh.consume_handoff(app, "pr-a")
        restarted = FakeApp(store.load(project)["prs"], project)
        assert autostart_fresh.resume_pending(restarted) == []
        assert auto_start.get_targets(restarted) == []

    def test_resume_skips_advanced_prs(self, project):
        autostart_fresh.reset_pr(project, "pr-a", "test")
        data = store.load(project)
        store.get_pr(data, "pr-a")["status"] = "in_review"
        store.save(data, project)
        restarted = FakeApp(store.load(project)["prs"], project)
        assert autostart_fresh.resume_pending(restarted) == []

    def test_resume_falls_back_to_wait_for_an_unknown_marker_policy(
            self, project):
        # A hand-edited / future marker value must not arm a target with an
        # unknown policy; the resume uses the manual-merge default.
        autostart_fresh.reset_pr(project, "pr-a", "test",
                                 policy=st.POLICY_AUTO)
        data = store.load(project)
        store.get_pr(data, "pr-a")[FRESH_KEY]["policy"] = "bogus"
        store.save(data, project)
        restarted = FakeApp(store.load(project)["prs"], project)
        assert autostart_fresh.resume_pending(restarted) == ["pr-a"]
        assert auto_start.target_policy(restarted, "pr-a") == st.POLICY_WAIT


# ---------------------------------------------------------------------------
# Retiring old in-memory state
# ---------------------------------------------------------------------------

class TestRetirement:
    def test_stale_loop_and_qa_are_dropped(self):
        app = FakeApp([_pr()])
        app._review_loops["pr-a"] = ReviewLoopState(
            pr_id="pr-a", running=False, latest_verdict="NEEDS_WORK")
        app._qa_loops["pr-a"] = QALoopState(pr_id="pr-a")
        app._self_driving_qa["pr-a"] = {"pass_count": 1}
        app._pending_merge_prs.add("pr-a")
        app._merge_input_required_prs.add("pr-a")

        written = {}
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={}), \
             patch("pm_core.runtime_state.set_action_state",
                   side_effect=lambda pid, action, state, **kw:
                   written.__setitem__(action, (state, kw))):
            autostart_fresh.retire_in_memory(app, _pr())

        assert "pr-a" not in app._review_loops
        assert "pr-a" not in app._qa_loops
        assert "pr-a" not in app._self_driving_qa
        assert "pr-a" not in app._pending_merge_prs
        assert "pr-a" not in app._merge_input_required_prs
        assert written["review-loop"][0] == "done"
        assert written["review-loop"][1]["verdict"] == "SUPERSEDED"
        assert written["review-loop"][1]["previous_verdict"] == "NEEDS_WORK"
        assert written["qa"][1]["verdict"] == "SUPERSEDED"

    def test_signoff_driver_bookkeeping_is_cleared(self):
        # ``signoff_ui`` skips a terminal outcome it has already acted on for
        # the same (verdict, sha, policy).  A stale key from the old attempt
        # would make the new attempt's verdict a no-op (no merge) when the
        # rework did not move HEAD, so the reset must drop it.
        app = FakeApp([_pr()])
        app._signoff_acted = {"pr-a": ("SIGNOFF_MERGE", "abc123", "auto_merge"),
                              "pr-b": ("SIGNOFF_MERGE", "def456", "auto_merge")}
        app._signoff_launched_at = {"pr-a": 1234.0}
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={}), \
             patch("pm_core.runtime_state.set_action_state"):
            autostart_fresh.retire_in_memory(app, _pr())
        assert "pr-a" not in app._signoff_acted
        assert "pr-a" not in app._signoff_launched_at
        # Another PR's bookkeeping is untouched.
        assert "pr-b" in app._signoff_acted

    def test_a_held_qa_run_is_discarded_not_just_stopped(self):
        # A run that finalized with INPUT_REQUIRED is *held* with ``running``
        # False while it keeps polling its worker panes (the hold has no
        # timeout of its own), so checking ``running`` alone left it alive.
        # Every discard must go through ``discard_qa_state``: it stops the
        # run, marks it superseded (a winding-down thread must not rewrite
        # the resume snapshot) and clears that snapshot.
        app = FakeApp([_pr()])
        qa = QALoopState(pr_id="pr-a")
        qa.held = True
        qa.waiting_for_input = {1}
        app._qa_loops["pr-a"] = qa
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={}), \
             patch("pm_core.runtime_state.set_action_state"):
            autostart_fresh.retire_in_memory(app, _pr())
        assert "pr-a" not in app._qa_loops
        assert qa.stop_requested
        assert qa.superseded

    def test_qa_scenario_tracker_keys_are_dropped_before_the_sentinel(self):
        # ``poll_qa_state`` unregisters a finished run's scenario keys; a
        # popped loop never reaches that path, so the retirement must drop
        # them itself — and *before* the SUPERSEDED sentinel, because
        # unregistering a ``qa:`` key clears the qa runtime mirror, which
        # would wipe a sentinel written first.  Both sides are recorded into
        # one event list so the ordering is actually observable.
        from pm_core.qa_loop import QAScenario

        events: list[tuple[str, str]] = []

        class _Tracker:
            def is_idle(self, key):
                return False

            def mark_active(self, key):
                pass

            def unregister(self, key):
                events.append(("unregister", key))

        app = FakeApp([_pr()])
        app._pane_idle_tracker = _Tracker()
        qa = QALoopState(pr_id="pr-a")
        qa.scenarios = [QAScenario(index=1, title="a", focus="f"),
                        QAScenario(index=2, title="b", focus="f")]
        app._qa_loops["pr-a"] = qa
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={}), \
             patch("pm_core.runtime_state.set_action_state",
                   side_effect=lambda pid, action, state, **kw:
                   events.append(("sentinel", action))):
            autostart_fresh.retire_in_memory(app, _pr())
        assert [e for e in events if e[0] == "unregister"] == [
            ("unregister", "qa:pr-a:s1"), ("unregister", "qa:pr-a:s2")]
        qa_sentinel = events.index(("sentinel", "qa"))
        assert all(i < qa_sentinel for i, e in enumerate(events)
                   if e[0] == "unregister")

    def test_live_loop_is_stopped(self):
        app = FakeApp([_pr()])
        loop = ReviewLoopState(pr_id="pr-a", running=True)
        app._review_loops["pr-a"] = loop
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={}), \
             patch("pm_core.runtime_state.set_action_state"), \
             patch("pm_core.review_loop._release_lease"):
            autostart_fresh.retire_in_memory(app, _pr())
        assert loop.stop_requested

    def test_the_old_loops_launch_lease_is_released(self):
        # The successor review this attempt starts claims the cross-driver
        # launch lease *before* it discovers/launches, so the old loop must
        # give its lease up now — exactly what the z d / zz d supersede paths
        # do.  Otherwise the successor sits in ``_wait_for_claim`` until the
        # old thread reaches its completion callback (or, if that is slower
        # than REVIEW_LAUNCH_CLAIM_WAIT, stands down as "superseded" and
        # leaves the fresh attempt in in_review with no review).
        app = FakeApp([_pr()])
        loop = ReviewLoopState(pr_id="pr-a", running=True)
        app._review_loops["pr-a"] = loop
        released = []
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={}), \
             patch("pm_core.runtime_state.set_action_state"), \
             patch("pm_core.review_loop._release_lease",
                   side_effect=lambda st: released.append(st)):
            autostart_fresh.retire_in_memory(app, _pr())
        assert released == [loop]

    def test_a_finished_loop_has_no_lease_to_release(self):
        # A loop that already finished released its lease at completion; the
        # retirement must not do a second (harmless but pointless) release.
        app = FakeApp([_pr()])
        app._review_loops["pr-a"] = ReviewLoopState(pr_id="pr-a",
                                                    running=False)
        released = []
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={}), \
             patch("pm_core.runtime_state.set_action_state"), \
             patch("pm_core.review_loop._release_lease",
                   side_effect=lambda st: released.append(st)):
            autostart_fresh.retire_in_memory(app, _pr())
        assert released == []

    def test_review_loop_sentinel_fences_late_callbacks(self):
        # ``_is_active_loop`` compares the recorded loop_id: the retirement
        # must write a *different* one so a late callback from the old
        # thread cannot record its verdict into the new attempt.
        app = FakeApp([_pr()])
        loop = ReviewLoopState(pr_id="pr-a", running=True)
        app._review_loops["pr-a"] = loop
        written = {}
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={}), \
             patch("pm_core.runtime_state.set_action_state",
                   side_effect=lambda pid, action, state, **kw:
                   written.__setitem__(action, (state, kw))), \
             patch("pm_core.review_loop._release_lease"):
            autostart_fresh.retire_in_memory(app, _pr())
        new_id = written["review-loop"][1]["loop_id"]
        assert new_id and new_id != loop.loop_id

    def test_retirement_clears_the_previous_turns_idle_flag(self):
        # A resumed turn fires no hook at its start, so the tracker keeps
        # the old turn's idle flag; the wait status would then wrongly say
        # "turn complete".  Retiring the attempt must reset it.
        class _Tracker:
            def __init__(self):
                self.idle = True
                self.marked = []

            def is_idle(self, key):
                return self.idle

            def mark_active(self, key):
                self.marked.append(key)
                self.idle = False

        app = FakeApp([_pr()])
        tracker = _Tracker()
        app._pane_idle_tracker = tracker
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={}), \
             patch("pm_core.runtime_state.set_action_state"):
            autostart_fresh.retire_in_memory(app, _pr())
        assert tracker.marked == ["pr-a"]
        assert tracker.idle is False

    def test_retirement_keeps_a_live_permission_prompt(self):
        class _Tracker:
            def __init__(self):
                self.marked = []

            def is_idle(self, key):
                return False

            def mark_active(self, key):
                self.marked.append(key)

        app = FakeApp([_pr()])
        tracker = _Tracker()
        app._pane_idle_tracker = tracker
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={}), \
             patch("pm_core.runtime_state.set_action_state"):
            autostart_fresh.retire_in_memory(app, _pr())
        assert tracker.marked == []

    def test_retirement_kills_the_review_window(self):
        # A live/stopped loop's review window must be parked and killed so a
        # running iteration's verdict poll exits (matching the z d supersede
        # path), not left to finish against the reset attempt.
        app = FakeApp([_pr()])
        app._session_name = "sess"
        app._review_loops["pr-a"] = ReviewLoopState(pr_id="pr-a",
                                                    running=False)
        killed = []
        with patch("pm_core.tmux.find_window_by_name",
                   return_value={"id": "@1"}), \
             patch("pm_core.tmux.kill_window",
                   side_effect=lambda s, w: killed.append((s, w))), \
             patch("pm_core.home_window.park_if_on") as park, \
             patch("pm_core.runtime_state.get_action_state", return_value={}), \
             patch("pm_core.runtime_state.set_action_state"):
            autostart_fresh.retire_in_memory(app, _pr())
        park.assert_called_once_with("sess", "@1")
        assert killed == [("sess", "review-pr-a")]

    def test_retire_downstream_retires_the_signoff_run(self, tmp_path):
        # The router window/transcript/launch stamp are driver-side state the
        # bounce path also retires; historical captures are left alone.
        app = FakeApp([_pr()])
        app._session_name = "sess"
        called = []
        with patch("pm_core.tui.auto_start.get_transcript_dir",
                   return_value=str(tmp_path)), \
             patch("pm_core.signoff.retire_signoff_run",
                   side_effect=lambda s, p, t: called.append(
                       (s, p["id"], t))):
            autostart_fresh.retire_downstream(app, _pr())
        assert called == [("sess", "pr-a", tmp_path)]


# ---------------------------------------------------------------------------
# Stale QA evidence
# ---------------------------------------------------------------------------

class TestStaleQa:
    def test_pre_fresh_qa_pass_is_ignored(self):
        pr = {"id": "pr-a", FRESH_KEY: {"requested_at": st.now_iso(),
                                        "awaiting_handoff": False}}
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={"state": "done", "verdict": "PASS",
                                 "updated_at": OLD}):
            assert auto_start.recorded_qa_verdict("pr-a", pr) is None

    def test_qa_pass_after_fresh_is_kept(self):
        pr = {"id": "pr-a", FRESH_KEY: {"requested_at": OLD,
                                        "awaiting_handoff": False}}
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={"state": "done", "verdict": "PASS",
                                 "updated_at": st.now_iso()}):
            assert auto_start.recorded_qa_verdict("pr-a", pr) == "PASS"

    def test_retirement_sentinel_is_not_a_verdict(self):
        # The fresh reset replaces the old run's verdict with SUPERSEDED
        # (keeping the old one under previous_verdict).  That is not a
        # usable QA result: it must neither hold nor advance the flow.
        pr = {"id": "pr-a", FRESH_KEY: {"requested_at": st.now_iso(),
                                        "awaiting_handoff": False}}
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={"state": "done", "verdict": "SUPERSEDED",
                                 "previous_verdict": "PASS",
                                 "updated_at": st.now_iso()}):
            assert auto_start.recorded_qa_verdict("pr-a", pr) is None


# ---------------------------------------------------------------------------
# Stale sign-off evidence
# ---------------------------------------------------------------------------

class TestStaleSignoff:
    def test_pre_fresh_verdict_is_ignored_even_when_not_invalidated(self):
        # The reset invalidates the current record; this timestamp fence also
        # covers a racing/legacy write that never got the invalidated flag.
        from pm_core.signoff import fresh_recorded_verdict
        pr = {"id": "pr-a",
              "signoff": {"verdict": "SIGNOFF_REQA", "sha": "abc",
                          "ts": OLD},
              FRESH_KEY: {"requested_at": st.now_iso(),
                          "awaiting_handoff": True}}
        assert fresh_recorded_verdict(pr, "abc") is None

    def test_post_fresh_verdict_is_kept(self):
        from pm_core.signoff import fresh_recorded_verdict
        pr = {"id": "pr-a",
              "signoff": {"verdict": "SIGNOFF_REQA", "sha": "abc",
                          "ts": st.now_iso()},
              FRESH_KEY: {"requested_at": OLD, "awaiting_handoff": False}}
        assert fresh_recorded_verdict(pr, "abc") == "SIGNOFF_REQA"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

class TestStatus:
    def _status(self, pr, idle, windows=None):
        return st.build_status({
            "prs": [pr], "targets": {"pr-a": st.make_target_record("test")},
            "enabled": True,
            "windows": {"#1": "%1"} if windows is None else windows,
            "impl_idle": {"pr-a": idle} if idle else {},
        })

    def test_waiting_reason_names_the_implementation_turn(self):
        pr = _pr(status="in_progress", gh_pr_number=1,
                 **{FRESH_KEY: {"requested_at": st.now_iso(),
                                "awaiting_handoff": True}})
        run = self._status(pr, "active")["runs"][0]
        assert run["state"] == "waiting"
        assert "waiting for the current implementation turn" in run["reason"]

    def test_missing_implementation_window_reason(self):
        pr = _pr(status="in_progress", gh_pr_number=1,
                 **{FRESH_KEY: {"requested_at": st.now_iso(),
                                "awaiting_handoff": True}})
        run = self._status(pr, "active", windows={})["runs"][0]
        assert run["state"] == "waiting"
        assert "implementation window missing" in run["reason"]

    def test_permission_prompt_reason_is_distinct(self):
        # A live permission prompt keeps its own reason: the turn is not
        # complete, it is blocked on the user answering the dialog.
        pr = _pr(status="in_progress", gh_pr_number=1,
                 **{FRESH_KEY: {"requested_at": st.now_iso(),
                                "awaiting_handoff": True}})
        run = self._status(pr, "waiting")["runs"][0]
        assert run["state"] == "waiting"
        assert "permission prompt in implementation window" in run["reason"]

    def test_idle_reason_says_review_is_starting(self):
        pr = _pr(status="in_progress", gh_pr_number=1,
                 **{FRESH_KEY: {"requested_at": st.now_iso(),
                                "awaiting_handoff": True}})
        run = self._status(pr, "idle")["runs"][0]
        assert "implementation turn complete" in run["reason"]

    def test_consumed_marker_shows_normal_implementation(self):
        pr = _pr(status="in_progress", gh_pr_number=1,
                 **{FRESH_KEY: {"requested_at": st.now_iso(),
                                "awaiting_handoff": False}})
        run = self._status(pr, "active")["runs"][0]
        assert run["reason"] == "implementing"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@pytest.fixture
def cli_project(tmp_path, monkeypatch):
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()
    wd = tmp_path / "wd"
    wd.mkdir()
    store.save({"project": {"name": "t", "repo": "/r",
                            "base_branch": "master"},
                "prs": [_pr(workdir=str(wd)),
                        _pr("pr-b", workdir=str(wd)),
                        _pr("pr-m", status="merged")]}, pm_dir)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pm_core.cli.autostart.state_root", lambda: pm_dir)
    monkeypatch.setattr("pm_core.cli.autostart.pm_home", lambda: home)
    return pm_dir, home


def _cli(args):
    from pm_core.cli import cli
    return CliRunner().invoke(cli, ["autostart", *args])


class TestCli:
    def test_help_mentions_fresh(self):
        res = _cli(["--help"])
        assert res.exit_code == 0
        assert "fresh" in res.output

    def test_tui_keys_lists_the_fresh_chords(self):
        # ``pm tui keys`` is the CLI twin of the in-TUI help screen; both
        # must name the fresh-autostart chords (plain ``a`` still opens the
        # runs popup) and the new command-bar verb.
        from pm_core.cli import cli
        res = CliRunner().invoke(cli, ["tui", "keys"])
        assert res.exit_code == 0, res.output
        assert "z a" in res.output
        assert "z O / z A" in res.output
        assert "add|remove ID...   Command bar (also: fresh" in res.output

    def test_fresh_sends_the_verb(self, cli_project):
        sent = []

        def fake_request(session, args, timeout):
            sent.append((session, args))
            return {"ok": True, "changes": [
                        {"pr_id": "pr-a", "action": "fresh_reset",
                         "from_status": "in_review"}],
                    "message": "Auto-start fresh: pr-a: waiting",
                    "status": {"mode": "targets", "targets": []}}

        with patch("pm_core.cli.autostart._request",
                   side_effect=fake_request):
            res = _cli(["fresh", "pr-a", "--auto-merge", "-s", "pm-x"])
        assert res.exit_code == 0, res.output
        assert sent == [("pm-x", ["fresh", "pr-a", "--auto-merge"])]
        assert "fresh: pr-a (in_review → in_progress)" in res.output
        assert "Auto-start fresh: pr-a: waiting" in res.output

    def test_fresh_rejects_conflicting_flags_before_sending(self, cli_project):
        # ``fresh`` shares ``add``'s flag resolution; two distinct policies
        # must reject the command locally (nothing sent to the owner).
        with patch("pm_core.cli.autostart.submit_tui_command") as sub:
            res = _cli(["fresh", "pr-a", "--stop-before-merge",
                        "--auto-merge", "--json", "-s", "pm-x"])
        assert res.exit_code == 1, res.output
        out = json.loads(res.output)
        assert out["error"] == "conflicting_flags"
        assert "--wait-for-merge" in out["message"]
        sub.assert_not_called()

    def test_fresh_accepts_the_deprecated_alias(self, cli_project):
        # ``--stop-before-merge`` and ``--wait-for-merge`` are one choice,
        # not a conflict, and both map to the manual policy.
        sent = []

        def fake_request(session, args, timeout):
            sent.append(args)
            return {"ok": True, "changes": [], "status": {}}

        with patch("pm_core.cli.autostart._request",
                   side_effect=fake_request):
            res = _cli(["fresh", "pr-a", "--stop-before-merge",
                        "--wait-for-merge", "-s", "pm-x"])
        assert res.exit_code == 0, res.output
        assert sent == [["fresh", "pr-a", "--wait-for-merge"]]

    def test_failed_reply_prints_the_error_once(self, cli_project):
        # The owner's failure message is reported by `_finish`'s Error line;
        # echoing it from `_print_changes` too would duplicate it.
        with patch("pm_core.cli.autostart._request",
                   return_value={"ok": False, "error": "not_later_stage",
                                 "message": "pr-a is already in implementation",
                                 "changes": []}):
            res = _cli(["fresh", "pr-a", "-s", "pm-x"])
        assert res.exit_code == 1
        assert res.output.count("already in implementation") == 1

    def test_partial_failure_prints_a_failed_line(self, cli_project):
        # A reply can be ok (one PR reset) *and* carry per-PR failures (a PR
        # that changed underneath the all-or-nothing validation).  Those are
        # not part of the owner's message, so the CLI must print them itself —
        # to stderr, without failing the whole command.
        with patch("pm_core.cli.autostart._request",
                   return_value={
                       "ok": True,
                       "changes": [{"pr_id": "pr-a", "action": "fresh_reset",
                                    "from_status": "in_review"}],
                       "handoff": {"pr-a": "waiting"},
                       "failed": [{"pr_id": "pr-b", "ok": False,
                                   "error": "terminal_pr",
                                   "message": "pr-b is already merged"}],
                       "message": "Auto-start fresh: pr-a: waiting",
                       "status": {"mode": "targets", "targets": []}}):
            res = _cli(["fresh", "pr-a", "pr-b", "-s", "pm-x"])
        assert res.exit_code == 0, res.output
        assert "fresh: pr-a (in_review → in_progress)" in res.output
        assert ("failed: pr-b (terminal_pr): pr-b is already merged"
                in res.output)

    def test_already_waiting_line_names_the_wait(self, cli_project):
        with patch("pm_core.cli.autostart._request",
                   return_value={"ok": True,
                                 "changes": [{"pr_id": "pr-a",
                                              "action": "already_waiting"}],
                                 "status": {"mode": "targets",
                                            "targets": []}}):
            res = _cli(["fresh", "pr-a", "-s", "pm-x"])
        assert res.exit_code == 0, res.output
        assert ("already waiting: pr-a (waiting for its implementation turn)"
                in res.output)

    def test_merged_rejected_before_sending(self, cli_project):
        with patch("pm_core.cli.autostart.submit_tui_command") as sub:
            res = _cli(["fresh", "pr-m", "-s", "pm-x"])
        assert res.exit_code == 1 and "merged" in res.output
        sub.assert_not_called()

    def test_round_trip_through_tui_handler(self, cli_project):
        import os
        import shlex
        pm_dir, home = cli_project
        pidfile = pm_dir.parent / "tui.pid"
        pidfile.write_text(str(os.getpid()))
        app = FakeApp(store.load(pm_dir)["prs"], pm_dir)
        app._pane_idle_tracker = MagicMock()
        app._pane_idle_tracker.is_tracked.return_value = False
        seen = {}

        class _Ok:
            ok = True
            reason = ""
            message = ""

        def fake_submit(session, cmd):
            seen["cmd"] = cmd
            with patch("pm_core.tui.auto_start.pm_home",
                       return_value=home):
                seen["result"] = auto_start.handle_command(
                    app, shlex.split(cmd)[1:])
            return _Ok()

        with patch("pm_core.cli.autostart._tui_pidfile_for_session",
                   return_value=pidfile), \
             patch("pm_core.cli.autostart.submit_tui_command",
                   side_effect=fake_submit), \
             patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            res = _cli(["fresh", "pr-a", "-s", "pm-x", "--json"])
        assert res.exit_code == 0, res.output
        assert seen["cmd"].startswith("autostart fresh pr-a --reply ")
        assert seen["result"]["ok"]
        assert seen["result"]["changes"][0]["action"] == "fresh_reset"
        out = json.loads(res.output)
        assert out["ok"] and out["handoff"]["pr-a"] == "waiting"
