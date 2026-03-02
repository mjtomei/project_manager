"""Tests for pm_core.tui.watchdog — TUI watchdog for dead threads and stale state."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from pm_core.review_loop import ReviewLoopState
from pm_core.watcher_loop import WatcherLoopState
from pm_core.tui.watchdog import (
    _check_review_loops,
    _check_watcher_loop,
    _check_poll_timer,
    _check_stale_merge_tracking,
    _poll_timer_needed,
    _watchdog_tick,
    WATCHDOG_INTERVAL,
    _POLL_STALE_THRESHOLD,
)


def _make_app(**overrides):
    """Create a mock app with the state fields the watchdog expects."""
    app = MagicMock()
    app._review_loops = overrides.get("review_loops", {})
    app._watcher_state = overrides.get("watcher_state", None)
    app._review_loop_timer = overrides.get("review_loop_timer", None)
    app._poll_last_tick = overrides.get("poll_last_tick", 0.0)
    app._pending_merge_prs = overrides.get("pending_merge_prs", set())
    app._merge_input_required_prs = overrides.get("merge_input_required_prs", set())
    app._merge_propagation_phase = overrides.get("merge_propagation_phase", set())
    app._session_name = overrides.get("session_name", "test-session")
    app._data = overrides.get("data", {"prs": []})
    app._watchdog_timer = overrides.get("watchdog_timer", None)
    return app


# ---------------------------------------------------------------------------
# 1. Review loop thread health
# ---------------------------------------------------------------------------

class TestCheckReviewLoops:
    def test_noop_when_no_loops(self):
        app = _make_app()
        _check_review_loops(app)
        app.log_message.assert_not_called()

    def test_noop_when_loop_not_running(self):
        state = ReviewLoopState(pr_id="abc123")
        state.running = False
        app = _make_app(review_loops={"abc123": state})
        _check_review_loops(app)
        app.log_message.assert_not_called()

    def test_noop_when_thread_alive(self):
        state = ReviewLoopState(pr_id="abc123")
        state.running = True
        thread = MagicMock(spec=threading.Thread)
        thread.is_alive.return_value = True
        state._thread = thread
        app = _make_app(review_loops={"abc123": state})
        _check_review_loops(app)
        app.log_message.assert_not_called()
        assert state.running is True

    def test_detects_dead_thread(self):
        state = ReviewLoopState(pr_id="abc123")
        state.running = True
        thread = MagicMock(spec=threading.Thread)
        thread.is_alive.return_value = False
        state._thread = thread
        app = _make_app(review_loops={"abc123": state})
        _check_review_loops(app)
        assert state.running is False
        assert state.latest_verdict == "ERROR"
        app.log_message.assert_called_once()
        assert "abc123" in app.log_message.call_args[0][0]

    def test_preserves_existing_verdict_on_dead_thread(self):
        state = ReviewLoopState(pr_id="abc123")
        state.running = True
        state.latest_verdict = "NEEDS_WORK"
        thread = MagicMock(spec=threading.Thread)
        thread.is_alive.return_value = False
        state._thread = thread
        app = _make_app(review_loops={"abc123": state})
        _check_review_loops(app)
        assert state.running is False
        assert state.latest_verdict == "NEEDS_WORK"  # preserved, not overwritten

    def test_skips_no_thread_reference(self):
        """Loops without a _thread reference should be skipped, not crash."""
        state = ReviewLoopState(pr_id="abc123")
        state.running = True
        state._thread = None
        app = _make_app(review_loops={"abc123": state})
        _check_review_loops(app)
        assert state.running is True  # unchanged
        app.log_message.assert_not_called()

    def test_multiple_loops(self):
        dead_state = ReviewLoopState(pr_id="dead1")
        dead_state.running = True
        dead_thread = MagicMock(spec=threading.Thread)
        dead_thread.is_alive.return_value = False
        dead_state._thread = dead_thread

        alive_state = ReviewLoopState(pr_id="alive1")
        alive_state.running = True
        alive_thread = MagicMock(spec=threading.Thread)
        alive_thread.is_alive.return_value = True
        alive_state._thread = alive_thread

        app = _make_app(review_loops={"dead1": dead_state, "alive1": alive_state})
        _check_review_loops(app)
        assert dead_state.running is False
        assert alive_state.running is True


# ---------------------------------------------------------------------------
# 2. Watcher loop thread health
# ---------------------------------------------------------------------------

class TestCheckWatcherLoop:
    def test_noop_when_no_watcher(self):
        app = _make_app()
        _check_watcher_loop(app)
        app.log_message.assert_not_called()

    def test_noop_when_watcher_not_running(self):
        state = WatcherLoopState()
        state.running = False
        app = _make_app(watcher_state=state)
        _check_watcher_loop(app)
        app.log_message.assert_not_called()

    def test_noop_when_thread_alive(self):
        state = WatcherLoopState()
        state.running = True
        thread = MagicMock(spec=threading.Thread)
        thread.is_alive.return_value = True
        state._thread = thread
        app = _make_app(watcher_state=state)
        _check_watcher_loop(app)
        assert state.running is True
        app.log_message.assert_not_called()

    def test_detects_dead_thread(self):
        state = WatcherLoopState()
        state.running = True
        thread = MagicMock(spec=threading.Thread)
        thread.is_alive.return_value = False
        state._thread = thread
        app = _make_app(watcher_state=state)
        _check_watcher_loop(app)
        assert state.running is False
        assert state.latest_verdict == "ERROR"
        app.log_message.assert_called_once()

    def test_preserves_existing_verdict(self):
        state = WatcherLoopState()
        state.running = True
        state.latest_verdict = "KILLED"
        thread = MagicMock(spec=threading.Thread)
        thread.is_alive.return_value = False
        state._thread = thread
        app = _make_app(watcher_state=state)
        _check_watcher_loop(app)
        assert state.latest_verdict == "KILLED"


# ---------------------------------------------------------------------------
# 3. Poll timer health
# ---------------------------------------------------------------------------

class TestCheckPollTimer:
    def test_noop_when_poll_timer_not_needed(self):
        app = _make_app(poll_last_tick=time.monotonic() - 100)
        # No active loops or PRs
        _check_poll_timer(app)
        app.log_message.assert_not_called()

    def test_noop_when_tick_is_fresh(self):
        state = ReviewLoopState(pr_id="abc123")
        state.running = True
        app = _make_app(
            review_loops={"abc123": state},
            poll_last_tick=time.monotonic(),
        )
        _check_poll_timer(app)
        app.log_message.assert_not_called()

    def test_noop_when_tick_is_zero(self):
        """Zero tick means timer just started — should not flag as stale."""
        state = ReviewLoopState(pr_id="abc123")
        state.running = True
        app = _make_app(review_loops={"abc123": state}, poll_last_tick=0.0)
        _check_poll_timer(app)
        app.log_message.assert_not_called()

    @patch("pm_core.tui.review_loop_ui._ensure_poll_timer")
    def test_restarts_stale_timer(self, mock_ensure):
        state = ReviewLoopState(pr_id="abc123")
        state.running = True
        old_timer = MagicMock()
        app = _make_app(
            review_loops={"abc123": state},
            poll_last_tick=time.monotonic() - 10,  # 10s stale
            review_loop_timer=old_timer,
        )
        _check_poll_timer(app)
        old_timer.stop.assert_called_once()
        assert app._review_loop_timer is None
        assert app._poll_last_tick == 0.0
        mock_ensure.assert_called_once_with(app)
        app.log_message.assert_called_once()

    def test_poll_timer_needed_review_loop(self):
        state = ReviewLoopState(pr_id="abc123")
        state.running = True
        app = _make_app(review_loops={"abc123": state})
        assert _poll_timer_needed(app) is True

    def test_poll_timer_needed_watcher(self):
        state = WatcherLoopState()
        state.running = True
        app = _make_app(watcher_state=state)
        assert _poll_timer_needed(app) is True

    def test_poll_timer_needed_active_prs(self):
        app = _make_app(data={"prs": [
            {"id": "x", "status": "in_progress", "workdir": "/tmp/x"}
        ]})
        assert _poll_timer_needed(app) is True

    def test_poll_timer_not_needed(self):
        app = _make_app()
        assert _poll_timer_needed(app) is False


# ---------------------------------------------------------------------------
# 4. Stale merge tracking
# ---------------------------------------------------------------------------

class TestCheckStaleMergeTracking:
    def test_noop_when_no_merges(self):
        app = _make_app()
        _check_stale_merge_tracking(app)
        app.log_message.assert_not_called()

    def test_noop_when_no_session(self):
        app = _make_app(
            session_name=None,
            pending_merge_prs={"abc123"},
        )
        _check_stale_merge_tracking(app)
        # Should return early, not crash
        app.log_message.assert_not_called()

    @patch("pm_core.tmux.find_window_by_name", return_value=None)
    @patch("pm_core.store.get_pr")
    def test_cleans_stale_pending_merge(self, mock_get_pr, mock_find_win):
        pr = {"id": "abc123", "status": "in_review", "gh_pr_number": 42}
        mock_get_pr.return_value = pr

        app = _make_app(
            pending_merge_prs={"abc123"},
            data={"prs": [pr]},
        )
        _check_stale_merge_tracking(app)
        assert "abc123" not in app._pending_merge_prs
        app.log_message.assert_called_once()

    @patch("pm_core.tmux.find_window_by_name")
    @patch("pm_core.store.get_pr")
    def test_keeps_active_pending_merge(self, mock_get_pr, mock_find_win):
        pr = {"id": "abc123", "status": "in_review", "gh_pr_number": 42}
        mock_get_pr.return_value = pr
        mock_find_win.return_value = {"id": "@1", "index": "1", "name": "merge-#42"}

        app = _make_app(
            pending_merge_prs={"abc123"},
            data={"prs": [pr]},
        )
        _check_stale_merge_tracking(app)
        assert "abc123" in app._pending_merge_prs
        app.log_message.assert_not_called()

    @patch("pm_core.tmux.find_window_by_name")
    @patch("pm_core.store.get_pr")
    def test_cleans_merged_pr_from_pending(self, mock_get_pr, mock_find_win):
        pr = {"id": "abc123", "status": "merged", "gh_pr_number": 42}
        mock_get_pr.return_value = pr

        app = _make_app(
            pending_merge_prs={"abc123"},
            data={"prs": [pr]},
        )
        _check_stale_merge_tracking(app)
        assert "abc123" not in app._pending_merge_prs

    @patch("pm_core.tmux.find_window_by_name", return_value=None)
    @patch("pm_core.store.get_pr")
    def test_cleans_stale_propagation_phase(self, mock_get_pr, mock_find_win):
        pr = {"id": "abc123", "status": "in_review", "gh_pr_number": 42}
        mock_get_pr.return_value = pr

        app = _make_app(
            merge_propagation_phase={"abc123"},
            data={"prs": [pr]},
        )
        _check_stale_merge_tracking(app)
        assert "abc123" not in app._merge_propagation_phase

    @patch("pm_core.tmux.find_window_by_name")
    @patch("pm_core.store.get_pr", return_value=None)
    def test_cleans_unknown_pr_from_tracking(self, mock_get_pr, mock_find_win):
        """PR no longer in project data should be cleaned up."""
        app = _make_app(
            pending_merge_prs={"gone_pr"},
            merge_propagation_phase={"gone_pr"},
        )
        _check_stale_merge_tracking(app)
        assert "gone_pr" not in app._pending_merge_prs
        assert "gone_pr" not in app._merge_propagation_phase


# ---------------------------------------------------------------------------
# Integration: _watchdog_tick
# ---------------------------------------------------------------------------

class TestWatchdogTick:
    @patch("pm_core.tui.watchdog._check_stale_merge_tracking")
    @patch("pm_core.tui.watchdog._check_poll_timer")
    @patch("pm_core.tui.watchdog._check_watcher_loop")
    @patch("pm_core.tui.watchdog._check_review_loops")
    def test_calls_all_checks(self, mock_rl, mock_wl, mock_pt, mock_mt):
        app = _make_app()
        _watchdog_tick(app)
        mock_rl.assert_called_once_with(app)
        mock_wl.assert_called_once_with(app)
        mock_pt.assert_called_once_with(app)
        mock_mt.assert_called_once_with(app)

    def test_survives_exception_in_check(self):
        """The tick should not crash even if a check raises."""
        app = _make_app()
        with patch("pm_core.tui.watchdog._check_review_loops", side_effect=RuntimeError("boom")):
            # Should not raise
            _watchdog_tick(app)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_watchdog_interval(self):
        assert WATCHDOG_INTERVAL == 30

    def test_poll_stale_threshold(self):
        assert _POLL_STALE_THRESHOLD == 5.0
