"""Tests for MERGED verdict detection from merge resolution windows.

Tests the verdict detection logic added to _poll_impl_idle in
review_loop_ui.py, which detects when Claude outputs MERGED in a merge
resolution window and triggers finalization.
"""

from unittest.mock import MagicMock, patch

import pytest

from pm_core.loop_shared import (
    extract_verdict_from_content,
    match_verdict,
    VerdictStabilityTracker,
    STABILITY_POLLS,
)


# ---------------------------------------------------------------------------
# Unit tests: VerdictStabilityTracker (shared helper)
# ---------------------------------------------------------------------------

class TestVerdictStabilityTracker:
    """Tests for the non-blocking stability tracker from loop_shared."""

    def test_returns_false_on_first_detection(self):
        t = VerdictStabilityTracker()
        assert t.update("k", "MERGED") is False

    def test_returns_true_after_stability_polls(self):
        t = VerdictStabilityTracker()
        for _ in range(STABILITY_POLLS - 1):
            assert t.update("k", "MERGED") is False
        assert t.update("k", "MERGED") is True

    def test_resets_on_none(self):
        t = VerdictStabilityTracker()
        t.update("k", "MERGED")
        t.update("k", None)
        # Needs full STABILITY_POLLS again
        for _ in range(STABILITY_POLLS - 1):
            assert t.update("k", "MERGED") is False
        assert t.update("k", "MERGED") is True

    def test_resets_on_different_verdict(self):
        t = VerdictStabilityTracker()
        t.update("k", "MERGED")
        t.update("k", "PASS")  # different verdict resets count
        assert t.update("k", "PASS") is True  # 2nd consecutive PASS

    def test_independent_keys(self):
        t = VerdictStabilityTracker()
        t.update("a", "MERGED")
        t.update("b", "MERGED")
        # Each key tracks independently
        assert t.update("a", "MERGED") is True
        assert t.update("b", "MERGED") is True

    def test_reset_clears_single_key(self):
        t = VerdictStabilityTracker()
        t.update("a", "MERGED")
        t.update("b", "MERGED")
        t.reset("a")
        assert t.update("a", "MERGED") is False  # reset
        assert t.update("b", "MERGED") is True   # unaffected

    def test_clear_clears_all(self):
        t = VerdictStabilityTracker()
        t.update("a", "MERGED")
        t.update("b", "MERGED")
        t.clear()
        assert t.update("a", "MERGED") is False
        assert t.update("b", "MERGED") is False


# ---------------------------------------------------------------------------
# Unit tests: MERGED verdict detection via shared helpers
# ---------------------------------------------------------------------------

class TestMatchVerdictMerged:
    """match_verdict correctly identifies MERGED on its own line."""

    def test_bare_merged(self):
        assert match_verdict("MERGED", ("MERGED",)) == "MERGED"

    def test_bold_merged(self):
        assert match_verdict("**MERGED**", ("MERGED",)) == "MERGED"

    def test_merged_with_whitespace(self):
        assert match_verdict("  MERGED  ", ("MERGED",)) == "MERGED"

    def test_merged_in_sentence_rejected(self):
        assert match_verdict("PR was MERGED successfully", ("MERGED",)) is None

    def test_merged_in_prompt_instruction_rejected(self):
        assert match_verdict("When done, output MERGED on its own line", ("MERGED",)) is None

    def test_merged_with_trailing_punctuation_rejected(self):
        assert match_verdict("MERGED.", ("MERGED",)) is None
        assert match_verdict("MERGED!", ("MERGED",)) is None

    def test_merged_with_backticks(self):
        assert match_verdict("`MERGED`", ("MERGED",)) == "MERGED"


class TestMatchVerdictInputRequired:
    """match_verdict correctly identifies INPUT_REQUIRED for merge windows."""

    def test_bare_input_required(self):
        assert match_verdict("INPUT_REQUIRED", ("MERGED", "INPUT_REQUIRED")) == "INPUT_REQUIRED"

    def test_bold_input_required(self):
        assert match_verdict("**INPUT_REQUIRED**", ("MERGED", "INPUT_REQUIRED")) == "INPUT_REQUIRED"

    def test_input_required_with_whitespace(self):
        assert match_verdict("  INPUT_REQUIRED  ", ("MERGED", "INPUT_REQUIRED")) == "INPUT_REQUIRED"

    def test_input_required_in_sentence_rejected(self):
        assert match_verdict("Output INPUT_REQUIRED if stuck", ("MERGED", "INPUT_REQUIRED")) is None


class TestExtractVerdictMerged:
    """extract_verdict_from_content detects MERGED in pane content."""

    def test_merged_in_tail(self):
        content = "\n".join(["working..."] * 40 + ["**MERGED**"])
        result = extract_verdict_from_content(
            content, verdicts=("MERGED",), keywords=("MERGED",),
        )
        assert result == "MERGED"

    def test_merged_not_in_tail_not_detected(self):
        """MERGED buried far above the tail is not detected."""
        content = "\n".join(["**MERGED**"] + ["more output..."] * 50)
        result = extract_verdict_from_content(
            content, verdicts=("MERGED",), keywords=("MERGED",),
        )
        assert result is None

    def test_no_merged_returns_none(self):
        content = "\n".join(["resolving conflicts..."] * 20)
        result = extract_verdict_from_content(
            content, verdicts=("MERGED",), keywords=("MERGED",),
        )
        assert result is None

    def test_merged_with_prompt_text_filtering(self):
        """MERGED in Claude's output is detected even with prompt text filtering."""
        prompt = "When done, output **MERGED** on its own line"
        content = prompt + "\n" + "\n".join(["fixing..."] * 40) + "\n\nMERGED"
        result = extract_verdict_from_content(
            content, verdicts=("MERGED",), keywords=("MERGED",),
            prompt_text=prompt,
        )
        assert result == "MERGED"

    def test_prompt_instruction_not_detected(self):
        """The prompt instruction itself should not match as a verdict."""
        prompt = "When done, output **MERGED** on its own line"
        # Only the prompt, no Claude output — MERGED appears in the instruction
        # but not as a standalone line
        content = prompt
        result = extract_verdict_from_content(
            content, verdicts=("MERGED",), keywords=("MERGED",),
            prompt_text=prompt,
        )
        assert result is None

    def test_terminal_wrapped_prompt_not_detected(self):
        """Terminal wrapping the prompt should not produce a false MERGED verdict."""
        from tests.conftest import simulate_terminal_wrap
        prompt = "4. When done, output **MERGED** on its own line"
        wrapped = simulate_terminal_wrap(prompt, width=30)
        # Wrapped at width 30 might produce: "4. When done, output **MERGED*" / "*..."
        # But match_verdict requires exact "MERGED" after stripping markdown
        result = extract_verdict_from_content(
            wrapped, verdicts=("MERGED",), keywords=("MERGED",),
        )
        assert result is None


# ---------------------------------------------------------------------------
# Integration tests: _poll_impl_idle merge verdict detection
# ---------------------------------------------------------------------------

def _make_app(prs=None, pending_merges=None, session_name="test-session"):
    """Create a mock TUI app with the required attributes."""
    app = MagicMock()
    app._data = {"prs": prs or []}
    app._root = "/tmp/test-root"
    app._session_name = session_name
    app._pending_merge_prs = pending_merges or set()
    app._review_loops = {}
    app._impl_poll_counter = 4  # Will be 5 on next increment → triggers poll
    app._review_loop_timer = MagicMock()
    app._watcher_state = None

    # PaneIdleTracker mock
    tracker = MagicMock()
    tracker.tracked_keys.return_value = []
    app._pane_idle_tracker = tracker

    return app


def _make_pr(pr_id="pr-001", status="in_review", workdir="/tmp/wd"):
    return {
        "id": pr_id,
        "title": "Test PR",
        "branch": f"pm/{pr_id}",
        "status": status,
        "workdir": workdir,
    }


class TestPollMergeVerdictDetection:
    """Tests that _poll_impl_idle detects MERGED verdict from merge windows."""

    def setup_method(self):
        """Reset module-level state between tests."""
        from pm_core.tui import review_loop_ui
        review_loop_ui._merge_verdict_tracker.clear()

    @patch("pm_core.tui.review_loop_ui._find_impl_pane", return_value="%42")
    @patch("pm_core.tui.review_loop_ui._refresh_tech_tree")
    @patch("pm_core.tui.review_loop_ui._finalize_detected_merge")
    def test_merged_detected_after_stability(self, mock_finalize, mock_refresh,
                                              mock_find_pane):
        """MERGED verdict triggers finalization after STABILITY_POLLS consecutive detections."""
        from pm_core.tui.review_loop_ui import _poll_impl_idle

        pr = _make_pr("pr-001", status="in_review")
        app = _make_app(prs=[pr])

        tracker = app._pane_idle_tracker
        tracker.is_tracked.return_value = False
        tracker.is_gone.return_value = False
        tracker.get_content.return_value = "\n".join(["work..."] * 40 + ["MERGED"])
        tracker.tracked_keys.return_value = []
        tracker.became_idle.return_value = False

        # Poll multiple times to reach stability
        for i in range(STABILITY_POLLS):
            _poll_impl_idle(app)
            if i < STABILITY_POLLS - 1:
                assert mock_finalize.call_count == 0

        # On the final poll, finalize should be called
        assert mock_finalize.call_count == 1
        call_args = mock_finalize.call_args
        assert call_args[0][1] == "pr-001"  # pr_id
        assert call_args[0][2] == "merge:pr-001"  # merge_key

    @patch("pm_core.tui.review_loop_ui._find_impl_pane", return_value="%42")
    @patch("pm_core.tui.review_loop_ui._refresh_tech_tree")
    @patch("pm_core.tui.review_loop_ui._finalize_detected_merge")
    def test_no_merged_no_finalization(self, mock_finalize, mock_refresh, mock_find_pane):
        """Without MERGED verdict, no finalization happens."""
        from pm_core.tui.review_loop_ui import _poll_impl_idle

        pr = _make_pr("pr-001", status="in_review")
        app = _make_app(prs=[pr])

        tracker = app._pane_idle_tracker
        tracker.is_tracked.return_value = False
        tracker.is_gone.return_value = False
        # Content without MERGED
        tracker.get_content.return_value = "still working on conflicts..."
        tracker.tracked_keys.return_value = []
        tracker.became_idle.return_value = False

        for _ in range(5):
            _poll_impl_idle(app)

        mock_finalize.assert_not_called()

    @patch("pm_core.tui.review_loop_ui._find_impl_pane", return_value="%42")
    @patch("pm_core.tui.review_loop_ui._refresh_tech_tree")
    @patch("pm_core.tui.review_loop_ui._finalize_detected_merge")
    def test_stability_resets_when_merged_disappears(self, mock_finalize,
                                                      mock_refresh, mock_find_pane):
        """If MERGED disappears from pane content, stability counter resets
        and finalization is not triggered even after enough total detections."""
        from pm_core.tui.review_loop_ui import _poll_impl_idle

        pr = _make_pr("pr-001", status="in_review")
        app = _make_app(prs=[pr])

        tracker = app._pane_idle_tracker
        tracker.is_tracked.return_value = False
        tracker.is_gone.return_value = False
        tracker.tracked_keys.return_value = []
        tracker.became_idle.return_value = False

        # First poll: MERGED detected
        tracker.get_content.return_value = "\n".join(["work..."] * 40 + ["MERGED"])
        _poll_impl_idle(app)
        assert mock_finalize.call_count == 0

        # Second poll: MERGED gone (Claude doing more work) — resets stability
        tracker.get_content.return_value = "still working..."
        _poll_impl_idle(app)

        # Third poll: MERGED back — needs STABILITY_POLLS consecutive again
        tracker.get_content.return_value = "\n".join(["work..."] * 40 + ["MERGED"])
        _poll_impl_idle(app)
        assert mock_finalize.call_count == 0  # only 1 consecutive, not stable yet

    @patch("pm_core.tui.review_loop_ui._find_impl_pane", return_value=None)
    @patch("pm_core.tui.review_loop_ui._refresh_tech_tree")
    def test_no_merge_window_no_tracking(self, mock_refresh, mock_find_pane):
        """If no merge window exists for an in_review PR, nothing is tracked."""
        from pm_core.tui.review_loop_ui import _poll_impl_idle

        pr = _make_pr("pr-001", status="in_review")
        app = _make_app(prs=[pr])

        tracker = app._pane_idle_tracker
        tracker.is_tracked.return_value = False
        tracker.is_gone.return_value = False
        tracker.tracked_keys.return_value = []

        _poll_impl_idle(app)
        # register should not be called since _find_impl_pane returned None
        tracker.register.assert_not_called()

    @patch("pm_core.tui.review_loop_ui._find_impl_pane", return_value="%42")
    @patch("pm_core.tui.review_loop_ui._refresh_tech_tree")
    @patch("pm_core.tui.review_loop_ui._finalize_detected_merge")
    def test_works_without_auto_start(self, mock_finalize, mock_refresh, mock_find_pane):
        """MERGED detection works for PRs NOT in _pending_merge_prs (no auto-start)."""
        from pm_core.tui.review_loop_ui import _poll_impl_idle

        pr = _make_pr("pr-001", status="in_review")
        # Empty pending_merges — auto-start didn't register this PR
        app = _make_app(prs=[pr], pending_merges=set())

        tracker = app._pane_idle_tracker
        tracker.is_tracked.return_value = False
        tracker.is_gone.return_value = False
        tracker.get_content.return_value = "\n".join(["work..."] * 40 + ["MERGED"])
        tracker.tracked_keys.return_value = []
        tracker.became_idle.return_value = False

        for _ in range(STABILITY_POLLS):
            _poll_impl_idle(app)

        assert mock_finalize.call_count == 1

    @patch("pm_core.tui.review_loop_ui._find_impl_pane", return_value="%42")
    @patch("pm_core.tui.review_loop_ui._refresh_tech_tree")
    def test_idle_fallback_only_for_pending_merges(self, mock_refresh, mock_find_pane):
        """Idle fallback only fires for PRs in _pending_merge_prs, not discovered ones."""
        from pm_core.tui.review_loop_ui import _poll_impl_idle

        pr = _make_pr("pr-001", status="in_review")
        # PR not in pending_merges
        app = _make_app(prs=[pr], pending_merges=set())

        tracker = app._pane_idle_tracker
        tracker.is_tracked.return_value = False
        tracker.is_gone.return_value = False
        tracker.get_content.return_value = "idle content..."
        tracker.tracked_keys.return_value = []
        # Pane went idle
        tracker.became_idle.return_value = True

        _poll_impl_idle(app)

        # No merge command should be run via idle fallback since PR isn't in pending_merges
        app.log_message.assert_not_called()


class TestFinalizeDetectedMerge:
    """Tests for _finalize_detected_merge helper.

    _finalize_detected_merge directly marks the PR as merged in project.yaml
    without re-running ``pm pr merge`` (which would cause an infinite loop).
    """

    def setup_method(self):
        from pm_core.tui import review_loop_ui
        review_loop_ui._merge_verdict_tracker.clear()

    @patch("pm_core.cli.helpers.kill_pr_windows")
    @patch("pm_core.cli.helpers.save_and_push")
    @patch("pm_core.cli.helpers._record_status_timestamp")
    @patch("pm_core.tui.auto_start.check_and_start")
    def test_directly_marks_pr_merged(self, mock_check_start,
                                       mock_timestamp, mock_save, mock_kill):
        """MERGED verdict directly marks PR as merged without re-running merge command."""
        from pm_core.tui.review_loop_ui import _finalize_detected_merge

        pr = _make_pr("pr-001", status="in_review")
        app = _make_app(prs=[pr])
        tracker = MagicMock()
        pending = {"pr-001"}
        active_keys = {"merge:pr-001"}

        _finalize_detected_merge(app, "pr-001", "merge:pr-001",
                                  tracker, pending, active_keys)

        # PR status directly updated (no pm pr merge subprocess)
        assert pr["status"] == "merged"
        mock_timestamp.assert_called_once_with(pr, "merged")
        mock_save.assert_called_once()

        # Tracking state cleaned up
        assert "pr-001" not in pending
        assert "merge:pr-001" not in active_keys
        tracker.unregister.assert_called_once_with("merge:pr-001")

        # Dependents kicked off
        app.run_worker.assert_called_once()

    @patch("pm_core.cli.helpers.kill_pr_windows")
    @patch("pm_core.cli.helpers.save_and_push")
    @patch("pm_core.cli.helpers._record_status_timestamp")
    @patch("pm_core.tui.auto_start.check_and_start")
    def test_does_not_call_attempt_merge(self, mock_check_start,
                                          mock_timestamp, mock_save, mock_kill):
        """_finalize_detected_merge does NOT call _attempt_merge_and_check (no infinite loop)."""
        from pm_core.tui.review_loop_ui import _finalize_detected_merge

        pr = _make_pr("pr-001", status="in_review")
        app = _make_app(prs=[pr])
        tracker = MagicMock()

        with patch("pm_core.tui.review_loop_ui._attempt_merge_and_check") as mock_attempt:
            _finalize_detected_merge(app, "pr-001", "merge:pr-001",
                                      tracker, set(), set())
            mock_attempt.assert_not_called()

    def test_pr_not_found_logs_warning(self):
        """If PR is not found in data, finalization is skipped gracefully."""
        from pm_core.tui.review_loop_ui import _finalize_detected_merge

        app = _make_app(prs=[])  # no PRs
        tracker = MagicMock()

        _finalize_detected_merge(app, "pr-999", "merge:pr-999",
                                  tracker, set(), set())

        # No worker started (PR not found)
        app.run_worker.assert_not_called()

    @patch("pm_core.cli.helpers.kill_pr_windows")
    @patch("pm_core.cli.helpers.save_and_push")
    @patch("pm_core.cli.helpers._record_status_timestamp")
    @patch("pm_core.tui.auto_start.check_and_start")
    def test_clears_merge_input_required(self, mock_check_start,
                                          mock_timestamp, mock_save, mock_kill):
        """MERGED verdict clears merge INPUT_REQUIRED state if it was set."""
        from pm_core.tui.review_loop_ui import _finalize_detected_merge

        pr = _make_pr("pr-001", status="in_review")
        app = _make_app(prs=[pr])
        app._merge_input_required_prs = {"pr-001"}
        tracker = MagicMock()

        _finalize_detected_merge(app, "pr-001", "merge:pr-001",
                                  tracker, set(), set())

        assert "pr-001" not in app._merge_input_required_prs


class TestMergeInputRequired:
    """Tests for INPUT_REQUIRED verdict detection in merge windows."""

    def setup_method(self):
        from pm_core.tui import review_loop_ui
        review_loop_ui._merge_verdict_tracker.clear()

    def test_handle_merge_input_required_sets_state(self):
        """_handle_merge_input_required marks the PR in app state."""
        from pm_core.tui.review_loop_ui import _handle_merge_input_required

        app = _make_app()
        app._merge_input_required_prs = set()

        _handle_merge_input_required(app, "pr-001", "merge:pr-001")

        assert "pr-001" in app._merge_input_required_prs
        app.log_message.assert_called_once()
        # Should contain INPUT_REQUIRED in the message
        msg = app.log_message.call_args[0][0]
        assert "INPUT_REQUIRED" in msg

    def test_handle_merge_input_required_resets_tracker(self):
        """After INPUT_REQUIRED, verdict tracker is reset so MERGED can be detected later."""
        from pm_core.tui.review_loop_ui import (
            _handle_merge_input_required,
            _merge_verdict_tracker,
        )

        app = _make_app()
        app._merge_input_required_prs = set()

        # Simulate prior verdict detection
        _merge_verdict_tracker.update("merge:pr-001", "INPUT_REQUIRED")

        _handle_merge_input_required(app, "pr-001", "merge:pr-001")

        # Tracker should be reset — MERGED needs fresh stability count
        assert _merge_verdict_tracker.update("merge:pr-001", "MERGED") is False  # 1st poll

    @patch("pm_core.tui.review_loop_ui._find_impl_pane", return_value="%42")
    @patch("pm_core.tui.review_loop_ui._refresh_tech_tree")
    @patch("pm_core.tui.review_loop_ui._handle_merge_input_required")
    def test_input_required_detected_from_poll(self, mock_handle, mock_refresh,
                                                mock_find_pane):
        """INPUT_REQUIRED verdict in merge window triggers handler after stability."""
        from pm_core.tui.review_loop_ui import _poll_impl_idle

        pr = _make_pr("pr-001", status="in_review")
        app = _make_app(prs=[pr])
        app._merge_input_required_prs = set()

        tracker = app._pane_idle_tracker
        tracker.is_tracked.return_value = False
        tracker.is_gone.return_value = False
        tracker.get_content.return_value = "\n".join(
            ["resolving..."] * 40 + ["INPUT_REQUIRED"]
        )
        tracker.tracked_keys.return_value = []
        tracker.became_idle.return_value = False

        for _ in range(STABILITY_POLLS):
            _poll_impl_idle(app)

        mock_handle.assert_called_once()
        assert mock_handle.call_args[0][1] == "pr-001"

    @patch("pm_core.tui.review_loop_ui._find_impl_pane", return_value="%42")
    @patch("pm_core.tui.review_loop_ui._refresh_tech_tree")
    @patch("pm_core.tui.review_loop_ui._finalize_detected_merge")
    @patch("pm_core.tui.review_loop_ui._handle_merge_input_required")
    def test_merged_after_input_required(self, mock_handle_ir, mock_finalize,
                                          mock_refresh, mock_find_pane):
        """After INPUT_REQUIRED, MERGED can still be detected and triggers finalization."""
        from pm_core.tui.review_loop_ui import _poll_impl_idle, _merge_verdict_tracker

        pr = _make_pr("pr-001", status="in_review")
        app = _make_app(prs=[pr])
        app._merge_input_required_prs = set()

        tracker = app._pane_idle_tracker
        tracker.is_tracked.return_value = False
        tracker.is_gone.return_value = False
        tracker.tracked_keys.return_value = []
        tracker.became_idle.return_value = False

        # Phase 1: INPUT_REQUIRED
        tracker.get_content.return_value = "\n".join(
            ["resolving..."] * 40 + ["INPUT_REQUIRED"]
        )
        for _ in range(STABILITY_POLLS):
            _poll_impl_idle(app)
        assert mock_handle_ir.call_count == 1

        # Reset tracker as the handler would
        _merge_verdict_tracker.reset("merge:pr-001")

        # Phase 2: MERGED (after user helped)
        tracker.get_content.return_value = "\n".join(
            ["resolved with help..."] * 40 + ["MERGED"]
        )
        for _ in range(STABILITY_POLLS):
            _poll_impl_idle(app)
        assert mock_finalize.call_count == 1


class TestMergeVerdictCleanup:
    """Tests that stale merge verdict state is cleaned up."""

    def setup_method(self):
        from pm_core.tui import review_loop_ui
        review_loop_ui._merge_verdict_tracker.clear()

    @patch("pm_core.tui.review_loop_ui._find_impl_pane", return_value="%42")
    @patch("pm_core.tui.review_loop_ui._refresh_tech_tree")
    def test_already_merged_pr_cleans_up(self, mock_refresh, mock_find_pane):
        """PRs that are already merged get cleaned up from tracking."""
        from pm_core.tui.review_loop_ui import _poll_impl_idle

        pr = _make_pr("pr-001", status="merged")
        app = _make_app(prs=[pr], pending_merges={"pr-001"})

        tracker = app._pane_idle_tracker
        tracker.tracked_keys.return_value = []

        _poll_impl_idle(app)

        tracker.unregister.assert_called_with("merge:pr-001")
