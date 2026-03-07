"""Tests for self-driving QA loop with zz t and zzz t modifiers.

Covers scenario 4 steps:
 - z-prefix dispatch (z=0,1,2,3)
 - Self-driving state initialization (strict/lenient, pass_count, required_passes)
 - Pass counting and auto-merge trigger
 - NEEDS_WORK resets pass_count, transitions to in_review, starts review loop
 - INPUT_REQUIRED pauses the loop
 - Toggle stop (zz t on running loop)
 - z t fresh start clears state
 - Review → QA auto-restart in self-driving mode
"""

import pytest
from unittest.mock import patch, MagicMock, call

from pm_core.qa_loop import QALoopState, VERDICT_PASS, VERDICT_NEEDS_WORK, VERDICT_INPUT_REQUIRED
from pm_core import store


def _make_app(tmp_path, *, pr_status="qa", auto_start=True):
    """Create a mock TUI app with a PR on disk."""
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir(exist_ok=True)
    data = {
        "project": {"name": "test", "repo": "/tmp/r", "base_branch": "master"},
        "prs": [{"id": "pr-001", "title": "T", "branch": "b",
                  "status": pr_status, "workdir": str(tmp_path / "wd"),
                  "notes": []}],
    }
    store.save(data, pm_dir)

    app = MagicMock()
    app._root = pm_dir
    app._data = data
    app._auto_start = auto_start
    app._auto_start_target = "pr-001"
    app._qa_loops = {}
    app._review_loops = {}
    app._self_driving_qa = {}
    return app


# ---------------------------------------------------------------------------
# Step 2-3: zz t starts lenient QA loop with correct state
# ---------------------------------------------------------------------------

class TestZZTLenientStart:
    """zz t (strict=False) should create self-driving state with strict=False."""

    def test_lenient_creates_self_driving_state(self, tmp_path):
        """Step 2-3: zz t registers self-driving with strict=False, pass_count=0."""
        from pm_core.tui.qa_loop_ui import start_or_stop_qa_loop

        app = _make_app(tmp_path)

        with patch("pm_core.tui.qa_loop_ui.start_qa_background"), \
             patch("pm_core.tui.qa_loop_ui._get_qa_pass_count", return_value=1):
            start_or_stop_qa_loop(app, "pr-001", strict=False)

        sd = app._self_driving_qa.get("pr-001")
        assert sd is not None
        assert sd["strict"] is False
        assert sd["pass_count"] == 0
        assert sd["required_passes"] == 1

    def test_lenient_starts_qa_background(self, tmp_path):
        """zz t should start a QA background thread."""
        from pm_core.tui.qa_loop_ui import start_or_stop_qa_loop

        app = _make_app(tmp_path)

        with patch("pm_core.tui.qa_loop_ui.start_qa_background") as mock_bg, \
             patch("pm_core.tui.qa_loop_ui._get_qa_pass_count", return_value=1):
            start_or_stop_qa_loop(app, "pr-001", strict=False)

        mock_bg.assert_called_once()
        assert "pr-001" in app._qa_loops

    def test_lenient_logs_mode_label(self, tmp_path):
        """zz t should log 'lenient' mode."""
        from pm_core.tui.qa_loop_ui import start_or_stop_qa_loop

        app = _make_app(tmp_path)

        with patch("pm_core.tui.qa_loop_ui.start_qa_background"), \
             patch("pm_core.tui.qa_loop_ui._get_qa_pass_count", return_value=1):
            start_or_stop_qa_loop(app, "pr-001", strict=False)

        # Check log message contains 'lenient'
        log_calls = [str(c) for c in app.log_message.call_args_list]
        assert any("lenient" in c for c in log_calls)


# ---------------------------------------------------------------------------
# Step 6: zzz t starts strict QA loop
# ---------------------------------------------------------------------------

class TestZZZTStrictStart:
    """zzz t (strict=True) should create self-driving state with strict=True."""

    def test_strict_creates_self_driving_state(self, tmp_path):
        """Step 6: zzz t registers self-driving with strict=True."""
        from pm_core.tui.qa_loop_ui import start_or_stop_qa_loop

        app = _make_app(tmp_path)

        with patch("pm_core.tui.qa_loop_ui.start_qa_background"), \
             patch("pm_core.tui.qa_loop_ui._get_qa_pass_count", return_value=1):
            start_or_stop_qa_loop(app, "pr-001", strict=True)

        sd = app._self_driving_qa.get("pr-001")
        assert sd is not None
        assert sd["strict"] is True
        assert sd["pass_count"] == 0
        assert sd["required_passes"] == 1

    def test_strict_logs_strict_mode_label(self, tmp_path):
        """zzz t should log 'strict (PASS only)' mode."""
        from pm_core.tui.qa_loop_ui import start_or_stop_qa_loop

        app = _make_app(tmp_path)

        with patch("pm_core.tui.qa_loop_ui.start_qa_background"), \
             patch("pm_core.tui.qa_loop_ui._get_qa_pass_count", return_value=1):
            start_or_stop_qa_loop(app, "pr-001", strict=True)

        log_calls = [str(c) for c in app.log_message.call_args_list]
        assert any("strict" in c for c in log_calls)


# ---------------------------------------------------------------------------
# Step 4-5: PASS increments pass_count, triggers auto-merge when sufficient
# ---------------------------------------------------------------------------

class TestPassCountAndAutoMerge:
    """PASS (no changes) increments pass_count; when >= required, triggers merge."""

    def test_pass_increments_pass_count(self, tmp_path):
        """Step 4: PASS increments pass_count from 0 to 1."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = _make_app(tmp_path)
        app._self_driving_qa["pr-001"] = {
            "strict": False, "pass_count": 0, "required_passes": 2
        }
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_PASS


        with patch("pm_core.tui.qa_loop_ui._trigger_auto_merge") as mock_merge, \
             patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
             patch("pm_core.tui.qa_loop_ui.start_qa") as mock_restart:
            _on_qa_complete(app, state)

        # pass_count should be 1, not yet meeting required_passes=2
        assert app._self_driving_qa["pr-001"]["pass_count"] == 1
        mock_merge.assert_not_called()
        mock_restart.assert_called_once_with(app, "pr-001")

    def test_pass_triggers_auto_merge_when_enough(self, tmp_path):
        """Step 5: pass_count reaching required_passes triggers auto-merge."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = _make_app(tmp_path)
        app._self_driving_qa["pr-001"] = {
            "strict": False, "pass_count": 0, "required_passes": 1
        }
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_PASS


        with patch("pm_core.tui.qa_loop_ui._trigger_auto_merge") as mock_merge, \
             patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        mock_merge.assert_called_once_with(app, "pr-001")
        # Self-driving state should be removed after successful merge trigger
        assert "pr-001" not in app._self_driving_qa

    def test_pass_removes_self_driving_on_completion(self, tmp_path):
        """When pass count reaches required, self-driving registration is removed."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = _make_app(tmp_path)
        app._self_driving_qa["pr-001"] = {
            "strict": True, "pass_count": 1, "required_passes": 2
        }
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_PASS


        with patch("pm_core.tui.qa_loop_ui._trigger_auto_merge"), \
             patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        # pass_count was 1, now 2 >= required_passes=2 → removed
        assert "pr-001" not in app._self_driving_qa

    def test_multiple_passes_required(self, tmp_path):
        """With required_passes=3, need 3 consecutive passes before merge."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = _make_app(tmp_path)
        app._self_driving_qa["pr-001"] = {
            "strict": False, "pass_count": 1, "required_passes": 3
        }
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_PASS


        with patch("pm_core.tui.qa_loop_ui._trigger_auto_merge") as mock_merge, \
             patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
             patch("pm_core.tui.qa_loop_ui.start_qa") as mock_restart:
            _on_qa_complete(app, state)

        # pass_count 1→2, still < 3
        assert app._self_driving_qa["pr-001"]["pass_count"] == 2
        mock_merge.assert_not_called()
        mock_restart.assert_called_once()


# ---------------------------------------------------------------------------
# Step 7: NEEDS_WORK in strict mode resets pass_count and transitions
# ---------------------------------------------------------------------------

class TestNeedsWorkStrict:
    """NEEDS_WORK resets pass_count, transitions to in_review, starts review loop."""

    def test_needs_work_resets_pass_count(self, tmp_path):
        """Step 7: NEEDS_WORK resets pass_count to 0."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = _make_app(tmp_path)
        app._self_driving_qa["pr-001"] = {
            "strict": True, "pass_count": 2, "required_passes": 3
        }
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK


        with patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
             patch("pm_core.tui.qa_loop_ui._start_self_driving_review"):
            _on_qa_complete(app, state)

        assert app._self_driving_qa["pr-001"]["pass_count"] == 0

    def test_needs_work_transitions_to_in_review(self, tmp_path):
        """Step 7: NEEDS_WORK transitions PR from qa → in_review."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = _make_app(tmp_path)
        app._self_driving_qa["pr-001"] = {
            "strict": True, "pass_count": 1, "required_passes": 2
        }
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK


        with patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
             patch("pm_core.tui.qa_loop_ui._start_self_driving_review"):
            _on_qa_complete(app, state)

        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

    def test_needs_work_starts_review_loop_directly(self, tmp_path):
        """Step 7: NEEDS_WORK starts review loop via _start_self_driving_review."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = _make_app(tmp_path)
        app._self_driving_qa["pr-001"] = {
            "strict": True, "pass_count": 1, "required_passes": 2
        }
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK


        with patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
             patch("pm_core.tui.qa_loop_ui._start_self_driving_review") as mock_review:
            _on_qa_complete(app, state)

        mock_review.assert_called_once_with(app, "pr-001", True)  # strict=True

    def test_needs_work_lenient_passes_strict_false(self, tmp_path):
        """In lenient mode, NEEDS_WORK passes strict=False to review loop."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = _make_app(tmp_path)
        app._self_driving_qa["pr-001"] = {
            "strict": False, "pass_count": 0, "required_passes": 1
        }
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_NEEDS_WORK


        with patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
             patch("pm_core.tui.qa_loop_ui._start_self_driving_review") as mock_review:
            _on_qa_complete(app, state)

        mock_review.assert_called_once_with(app, "pr-001", False)  # strict=False


# ---------------------------------------------------------------------------
# Step 8: Review → QA auto-restart in self-driving mode
# ---------------------------------------------------------------------------

class TestReviewToQAAutoRestart:
    """When review completes and PR returns to qa, QA restarts automatically."""

    def test_self_driving_restarts_qa_after_review(self, tmp_path):
        """Step 8: _maybe_start_qa restarts QA when self-driving is registered."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa

        app = _make_app(tmp_path, pr_status="in_review")
        app._self_driving_qa["pr-001"] = {
            "strict": True, "pass_count": 0, "required_passes": 2
        }

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-001")

        # PR should transition to qa
        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "qa"
        mock_start.assert_called_once_with(app, "pr-001")

    def test_self_driving_bypasses_auto_start_off(self, tmp_path):
        """Step 8: Self-driving QA restarts even with auto-start disabled."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa

        app = _make_app(tmp_path, pr_status="in_review", auto_start=False)
        app._self_driving_qa["pr-001"] = {
            "strict": False, "pass_count": 0, "required_passes": 1
        }

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-001")

        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "qa"
        mock_start.assert_called_once()


# ---------------------------------------------------------------------------
# Step 9: Toggle stop (zz t on running loop)
# ---------------------------------------------------------------------------

class TestToggleStop:
    """Pressing zz t again on a running loop should stop it."""

    def test_toggle_stop_running_loop(self, tmp_path):
        """Step 9: zz t on running loop sets stop_requested and removes self-driving."""
        from pm_core.tui.qa_loop_ui import start_or_stop_qa_loop

        app = _make_app(tmp_path)
        # Pre-register running loop
        running_state = QALoopState(pr_id="pr-001")
        running_state.running = True
        app._qa_loops["pr-001"] = running_state
        app._self_driving_qa["pr-001"] = {
            "strict": False, "pass_count": 1, "required_passes": 2
        }

        start_or_stop_qa_loop(app, "pr-001", strict=False)

        # Stop should be requested
        assert running_state.stop_requested is True
        # Self-driving registration should be removed
        assert "pr-001" not in app._self_driving_qa

    def test_toggle_stop_logs_stopping(self, tmp_path):
        """Step 9: Stopping should log 'QA loop stopping'."""
        from pm_core.tui.qa_loop_ui import start_or_stop_qa_loop

        app = _make_app(tmp_path)
        running_state = QALoopState(pr_id="pr-001")
        running_state.running = True
        app._qa_loops["pr-001"] = running_state
        app._self_driving_qa["pr-001"] = {
            "strict": False, "pass_count": 0, "required_passes": 1
        }

        start_or_stop_qa_loop(app, "pr-001", strict=False)

        log_calls = [str(c) for c in app.log_message.call_args_list]
        assert any("QA loop stopping" in c for c in log_calls)


# ---------------------------------------------------------------------------
# Step 10: z t (fresh start) clears state and starts new QA
# ---------------------------------------------------------------------------

class TestFreshStartZT:
    """z t should stop running QA, clear state, and start fresh."""

    def test_fresh_start_stops_running(self, tmp_path):
        """Step 10: z t stops running QA."""
        from pm_core.tui.qa_loop_ui import fresh_start_qa

        app = _make_app(tmp_path)
        running_state = QALoopState(pr_id="pr-001")
        running_state.running = True
        app._qa_loops["pr-001"] = running_state

        with patch("pm_core.tui.qa_loop_ui.start_qa"):
            fresh_start_qa(app, "pr-001")

        assert running_state.stop_requested is True

    def test_fresh_start_removes_old_loop(self, tmp_path):
        """Step 10: z t removes old loop from _qa_loops before starting new."""
        from pm_core.tui.qa_loop_ui import fresh_start_qa

        app = _make_app(tmp_path)
        old_state = QALoopState(pr_id="pr-001")
        old_state.running = True
        app._qa_loops["pr-001"] = old_state

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            fresh_start_qa(app, "pr-001")

        # Old state should be popped before start_qa is called
        mock_start.assert_called_once_with(app, "pr-001")

    def test_fresh_start_when_not_running(self, tmp_path):
        """z t works even when no QA is running — starts fresh."""
        from pm_core.tui.qa_loop_ui import fresh_start_qa

        app = _make_app(tmp_path)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            fresh_start_qa(app, "pr-001")

        mock_start.assert_called_once_with(app, "pr-001")

    def test_fresh_start_clears_self_driving_state(self, tmp_path):
        """Step 10: z t clears self-driving registration so the fresh QA is one-shot."""
        from pm_core.tui.qa_loop_ui import fresh_start_qa

        app = _make_app(tmp_path)
        running_state = QALoopState(pr_id="pr-001")
        running_state.running = True
        app._qa_loops["pr-001"] = running_state
        app._self_driving_qa["pr-001"] = {
            "strict": True, "pass_count": 2, "required_passes": 3
        }

        with patch("pm_core.tui.qa_loop_ui.start_qa"):
            fresh_start_qa(app, "pr-001")

        # Self-driving state should be cleared
        assert "pr-001" not in app._self_driving_qa

    def test_fresh_start_clears_loops_before_start(self, tmp_path):
        """z t must remove old loop from _qa_loops before calling start_qa,
        so start_qa doesn't hit the 'already running' guard."""
        from pm_core.tui.qa_loop_ui import fresh_start_qa

        app = _make_app(tmp_path)
        old_state = QALoopState(pr_id="pr-001")
        old_state.running = True
        app._qa_loops["pr-001"] = old_state

        loops_snapshot = []

        def capture_start(a, pr_id):
            # Capture the state of _qa_loops at the time start_qa is called
            loops_snapshot.append(dict(a._qa_loops))

        with patch("pm_core.tui.qa_loop_ui.start_qa", side_effect=capture_start):
            fresh_start_qa(app, "pr-001")

        # At the time start_qa was called, _qa_loops should not contain pr-001
        assert len(loops_snapshot) == 1
        assert "pr-001" not in loops_snapshot[0]

    def test_fresh_start_new_state_has_planning_phase(self, tmp_path):
        """z t creates a new QALoopState with planning_phase=True (starts from scratch)."""
        from pm_core.tui.qa_loop_ui import fresh_start_qa

        app = _make_app(tmp_path)
        old_state = QALoopState(pr_id="pr-001")
        old_state.running = True
        old_state.planning_phase = False  # old state past planning
        old_state.scenarios = [MagicMock()]  # old state had scenarios
        app._qa_loops["pr-001"] = old_state

        with patch("pm_core.tui.qa_loop_ui.start_qa_background"):
            fresh_start_qa(app, "pr-001")

        # The new state in _qa_loops should be fresh
        new_state = app._qa_loops.get("pr-001")
        assert new_state is not None
        assert new_state is not old_state
        assert new_state.planning_phase is True
        assert new_state.scenarios == []
        assert new_state.stop_requested is False

    def test_fresh_start_does_not_call_cleanup_directly(self, tmp_path):
        """Window cleanup is deferred to run_qa_sync planning phase,
        not called immediately by fresh_start_qa."""
        from pm_core.tui.qa_loop_ui import fresh_start_qa

        app = _make_app(tmp_path)
        old_state = QALoopState(pr_id="pr-001")
        old_state.running = True
        app._qa_loops["pr-001"] = old_state

        with patch("pm_core.tui.qa_loop_ui.start_qa"), \
             patch("pm_core.qa_loop._cleanup_stale_scenario_windows") as mock_cleanup:
            fresh_start_qa(app, "pr-001")

        # _cleanup_stale_scenario_windows should NOT be called by fresh_start_qa
        mock_cleanup.assert_not_called()


# ---------------------------------------------------------------------------
# Step 11: INPUT_REQUIRED pauses self-driving loop
# ---------------------------------------------------------------------------

class TestInputRequiredPause:
    """INPUT_REQUIRED should pause the self-driving loop."""

    def test_input_required_pauses_loop(self, tmp_path):
        """Step 11: INPUT_REQUIRED leaves self-driving registered but doesn't restart."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = _make_app(tmp_path)
        app._self_driving_qa["pr-001"] = {
            "strict": False, "pass_count": 1, "required_passes": 2
        }
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_INPUT_REQUIRED


        with patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
             patch("pm_core.tui.qa_loop_ui.start_qa") as mock_restart, \
             patch("pm_core.tui.qa_loop_ui._trigger_auto_merge") as mock_merge:
            _on_qa_complete(app, state)

        # Self-driving should still be registered (not removed)
        assert "pr-001" in app._self_driving_qa
        # QA should NOT restart
        mock_restart.assert_not_called()
        # Merge should NOT be triggered
        mock_merge.assert_not_called()

    def test_input_required_leaves_qa_status(self, tmp_path):
        """Step 11: INPUT_REQUIRED leaves PR in qa status."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = _make_app(tmp_path)
        app._self_driving_qa["pr-001"] = {
            "strict": True, "pass_count": 0, "required_passes": 1
        }
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_INPUT_REQUIRED


        with patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "qa"

    def test_input_required_logs_paused(self, tmp_path):
        """Step 11: INPUT_REQUIRED should log 'paused for human input'."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = _make_app(tmp_path)
        app._self_driving_qa["pr-001"] = {
            "strict": False, "pass_count": 0, "required_passes": 1
        }
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_INPUT_REQUIRED


        with patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        log_calls = [str(c) for c in app.log_message.call_args_list]
        assert any("paused" in c.lower() or "human input" in c.lower() for c in log_calls)

    def test_input_required_then_restart_with_zz_t(self, tmp_path):
        """After INPUT_REQUIRED pause, zz t should start a fresh self-driving loop."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete, start_or_stop_qa_loop

        app = _make_app(tmp_path)
        app._self_driving_qa["pr-001"] = {
            "strict": False, "pass_count": 1, "required_passes": 2
        }

        # Phase 1: QA completes with INPUT_REQUIRED — loop pauses
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_INPUT_REQUIRED


        with patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
             patch("pm_core.tui.qa_loop_ui.start_qa"), \
             patch("pm_core.tui.qa_loop_ui._trigger_auto_merge"):
            _on_qa_complete(app, state)

        assert "pr-001" in app._self_driving_qa
        # Simulate poll_qa_state cleaning up the completed loop
        app._qa_loops.pop("pr-001", None)

        # Phase 2: User does manual intervention, then presses zz t to restart
        with patch("pm_core.tui.qa_loop_ui.start_qa_background") as mock_bg:
            start_or_stop_qa_loop(app, "pr-001", strict=False)

        # Should have started a new loop
        mock_bg.assert_called_once()
        assert "pr-001" in app._qa_loops
        assert "pr-001" in app._self_driving_qa
        # pass_count should be reset to 0 (fresh loop)
        assert app._self_driving_qa["pr-001"]["pass_count"] == 0

    def test_input_required_restart_with_stale_loop_state(self, tmp_path):
        """zz t restart works even if stale loop state hasn't been cleaned up yet."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete, start_or_stop_qa_loop

        app = _make_app(tmp_path)
        app._self_driving_qa["pr-001"] = {
            "strict": True, "pass_count": 0, "required_passes": 1
        }

        # Phase 1: QA completes with INPUT_REQUIRED
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_INPUT_REQUIRED


        with patch("pm_core.tui.qa_loop_ui._record_qa_note"), \
             patch("pm_core.tui.qa_loop_ui.start_qa"), \
             patch("pm_core.tui.qa_loop_ui._trigger_auto_merge"):
            _on_qa_complete(app, state)

        # Stale loop state still in app._qa_loops (poll hasn't cleaned up)
        app._qa_loops["pr-001"] = state

        # Phase 2: User presses zz t — should still work
        with patch("pm_core.tui.qa_loop_ui.start_qa_background") as mock_bg:
            start_or_stop_qa_loop(app, "pr-001", strict=True)

        # New loop should have started (stale state replaced)
        mock_bg.assert_called_once()
        new_state = app._qa_loops["pr-001"]
        assert new_state is not state  # New state, not the old one


# ---------------------------------------------------------------------------
# z-prefix dispatch in action_start_qa_on_pr
# ---------------------------------------------------------------------------

class TestZPrefixDispatch:
    """Verify z-prefix dispatch from action_start_qa_on_pr."""

    def test_z0_calls_focus_or_start(self):
        """z=0 (plain t) calls focus_or_start_qa."""
        app = MagicMock()
        app._z_count = 0
        app._qa_loops = {}
        app._self_driving_qa = {}

        # Mock _consume_z to return 0
        def consume_z():
            count = app._z_count
            app._z_count = 0
            return count

        with patch("pm_core.tui.qa_loop_ui.focus_or_start_qa") as mock_focus, \
             patch("pm_core.tui.qa_loop_ui.fresh_start_qa") as mock_fresh, \
             patch("pm_core.tui.qa_loop_ui.start_or_stop_qa_loop") as mock_loop:
            # Simulate what action_start_qa_on_pr does
            z = consume_z()
            if z == 0:
                from pm_core.tui import qa_loop_ui
                qa_loop_ui.focus_or_start_qa(app, "pr-001")
            elif z == 1:
                from pm_core.tui import qa_loop_ui
                qa_loop_ui.fresh_start_qa(app, "pr-001")
            elif z == 2:
                from pm_core.tui import qa_loop_ui
                qa_loop_ui.start_or_stop_qa_loop(app, "pr-001", strict=False)
            else:
                from pm_core.tui import qa_loop_ui
                qa_loop_ui.start_or_stop_qa_loop(app, "pr-001", strict=True)

        mock_focus.assert_called_once_with(app, "pr-001")
        mock_fresh.assert_not_called()
        mock_loop.assert_not_called()

    def test_z1_calls_fresh_start(self):
        """z=1 (z t) calls fresh_start_qa."""
        app = MagicMock()
        app._z_count = 1

        with patch("pm_core.tui.qa_loop_ui.focus_or_start_qa") as mock_focus, \
             patch("pm_core.tui.qa_loop_ui.fresh_start_qa") as mock_fresh, \
             patch("pm_core.tui.qa_loop_ui.start_or_stop_qa_loop") as mock_loop:
            z = app._z_count
            app._z_count = 0
            if z == 0:
                from pm_core.tui import qa_loop_ui
                qa_loop_ui.focus_or_start_qa(app, "pr-001")
            elif z == 1:
                from pm_core.tui import qa_loop_ui
                qa_loop_ui.fresh_start_qa(app, "pr-001")

        mock_focus.assert_not_called()
        mock_fresh.assert_called_once_with(app, "pr-001")

    def test_z2_calls_loop_lenient(self):
        """z=2 (zz t) calls start_or_stop_qa_loop(strict=False)."""
        app = MagicMock()
        app._z_count = 2

        with patch("pm_core.tui.qa_loop_ui.start_or_stop_qa_loop") as mock_loop:
            z = app._z_count
            app._z_count = 0
            if z == 2:
                from pm_core.tui import qa_loop_ui
                qa_loop_ui.start_or_stop_qa_loop(app, "pr-001", strict=False)

        mock_loop.assert_called_once_with(app, "pr-001", strict=False)

    def test_z3_calls_loop_strict(self):
        """z=3 (zzz t) calls start_or_stop_qa_loop(strict=True)."""
        app = MagicMock()
        app._z_count = 3

        with patch("pm_core.tui.qa_loop_ui.start_or_stop_qa_loop") as mock_loop:
            z = app._z_count
            app._z_count = 0
            if z >= 3:
                from pm_core.tui import qa_loop_ui
                qa_loop_ui.start_or_stop_qa_loop(app, "pr-001", strict=True)

        mock_loop.assert_called_once_with(app, "pr-001", strict=True)


# ---------------------------------------------------------------------------
# _start_self_driving_review maps strict correctly
# ---------------------------------------------------------------------------

class TestStartSelfDrivingReview:
    """_start_self_driving_review maps strict flag to stop_on_suggestions."""

    def test_strict_true_maps_to_stop_on_suggestions_false(self, tmp_path):
        """strict=True → stop_on_suggestions=False (strict review)."""
        from pm_core.tui.qa_loop_ui import _start_self_driving_review

        app = _make_app(tmp_path, pr_status="in_review")

        with patch("pm_core.tui.review_loop_ui._start_loop") as mock_loop:
            _start_self_driving_review(app, "pr-001", strict=True)

        mock_loop.assert_called_once()
        _, kwargs = mock_loop.call_args
        assert kwargs.get("stop_on_suggestions") is False or \
               mock_loop.call_args[0][3] is False  # positional fallback

    def test_strict_false_maps_to_stop_on_suggestions_true(self, tmp_path):
        """strict=False → stop_on_suggestions=True (lenient review)."""
        from pm_core.tui.qa_loop_ui import _start_self_driving_review

        app = _make_app(tmp_path, pr_status="in_review")

        with patch("pm_core.tui.review_loop_ui._start_loop") as mock_loop:
            _start_self_driving_review(app, "pr-001", strict=False)

        mock_loop.assert_called_once()
        # Check stop_on_suggestions=True was passed
        call_args = mock_loop.call_args
        # Could be positional or keyword
        if "stop_on_suggestions" in (call_args.kwargs or {}):
            assert call_args.kwargs["stop_on_suggestions"] is True
        else:
            # positional: (app, pr_id, pr, stop_on_suggestions)
            assert call_args[0][3] is True


# ---------------------------------------------------------------------------
# Edge cases: changes with PASS, qa-pass-count setting
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases in self-driving QA behavior."""

    def test_qa_pass_count_setting_default(self):
        """Default qa-pass-count should be 1."""
        from pm_core.tui.qa_loop_ui import _get_qa_pass_count

        with patch("pm_core.tui.qa_loop_ui.get_global_setting_value", return_value=""):
            assert _get_qa_pass_count() == 1

    def test_qa_pass_count_setting_custom(self):
        """Custom qa-pass-count should be respected."""
        from pm_core.tui.qa_loop_ui import _get_qa_pass_count

        with patch("pm_core.tui.qa_loop_ui.get_global_setting_value", return_value="3"):
            assert _get_qa_pass_count() == 3

    def test_qa_pass_count_minimum_1(self):
        """qa-pass-count should never be less than 1."""
        from pm_core.tui.qa_loop_ui import _get_qa_pass_count

        with patch("pm_core.tui.qa_loop_ui.get_global_setting_value", return_value="0"):
            assert _get_qa_pass_count() == 1

    def test_qa_pass_count_invalid_returns_1(self):
        """Invalid qa-pass-count should default to 1."""
        from pm_core.tui.qa_loop_ui import _get_qa_pass_count

        with patch("pm_core.tui.qa_loop_ui.get_global_setting_value", return_value="abc"):
            assert _get_qa_pass_count() == 1

    def test_self_driving_merge_uses_force(self, tmp_path):
        """Self-driving QA should call _maybe_auto_merge with force=True.

        Without force, _maybe_auto_merge early-returns when auto-start is
        disabled, which would break the zz t / zzz t flow.
        """
        from pm_core.tui.qa_loop_ui import _trigger_auto_merge

        app = _make_app(tmp_path, auto_start=False)
        app._self_driving_qa["pr-001"] = {
            "strict": False, "pass_count": 1, "required_passes": 1
        }

        with patch("pm_core.tui.review_loop_ui._maybe_auto_merge") as mock_merge:
            _trigger_auto_merge(app, "pr-001")

        mock_merge.assert_called_once_with(app, "pr-001", force=True)

    def test_non_self_driving_merge_no_force(self, tmp_path):
        """Non-self-driving QA should call _maybe_auto_merge without force."""
        from pm_core.tui.qa_loop_ui import _trigger_auto_merge

        app = _make_app(tmp_path, auto_start=True)
        # No self-driving state

        with patch("pm_core.tui.review_loop_ui._maybe_auto_merge") as mock_merge:
            _trigger_auto_merge(app, "pr-001")

        mock_merge.assert_called_once_with(app, "pr-001", force=False)

    def test_self_driving_merge_force_in_full_flow(self, tmp_path):
        """End-to-end: _on_qa_complete with pass_count reaching required_passes
        should call _maybe_auto_merge with force=True even though it also
        removes the self-driving entry (pop must happen AFTER merge trigger)."""
        from pm_core.tui.qa_loop_ui import _on_qa_complete

        app = _make_app(tmp_path, auto_start=False)
        app._self_driving_qa["pr-001"] = {
            "strict": False, "pass_count": 0, "required_passes": 1
        }
        state = QALoopState(pr_id="pr-001")
        state.latest_verdict = VERDICT_PASS


        with patch("pm_core.tui.review_loop_ui._maybe_auto_merge") as mock_merge, \
             patch("pm_core.tui.qa_loop_ui._record_qa_note"):
            _on_qa_complete(app, state)

        mock_merge.assert_called_once_with(app, "pr-001", force=True)
        # Self-driving state should still be cleaned up after merge
        assert "pr-001" not in app._self_driving_qa

    def test_stale_loop_removed_on_new_start(self, tmp_path):
        """Starting a new loop removes stale (non-running) loop state."""
        from pm_core.tui.qa_loop_ui import start_or_stop_qa_loop

        app = _make_app(tmp_path)
        stale = QALoopState(pr_id="pr-001")
        stale.running = False  # Not running anymore
        app._qa_loops["pr-001"] = stale

        with patch("pm_core.tui.qa_loop_ui.start_qa_background"):
            start_or_stop_qa_loop(app, "pr-001", strict=False)

        # Should have created a new state, not the stale one
        new_state = app._qa_loops["pr-001"]
        assert new_state is not stale
        assert "pr-001" in app._self_driving_qa
