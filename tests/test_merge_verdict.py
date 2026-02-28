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
    STABILITY_POLLS,
)


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
        review_loop_ui._merge_verdict_stable.clear()

    @patch("pm_core.tui.review_loop_ui._find_impl_pane", return_value="%42")
    @patch("pm_core.tui.review_loop_ui._refresh_tech_tree")
    @patch("pm_core.tui.review_loop_ui._finalize_detected_merge")
    def test_merged_detected_after_stability(self, mock_finalize, mock_refresh,
                                              mock_find_pane):
        """MERGED verdict triggers finalization after STABILITY_POLLS consecutive detections."""
        from pm_core.tui.review_loop_ui import _poll_impl_idle, _merge_verdict_stable

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
            merge_key = "merge:pr-001"
            if i < STABILITY_POLLS - 1:
                assert mock_finalize.call_count == 0
                assert _merge_verdict_stable.get(merge_key, 0) == i + 1

        # On the final poll, finalize should be called
        assert mock_finalize.call_count == 1
        call_args = mock_finalize.call_args
        assert call_args[0][1] == "pr-001"  # pr_id
        assert call_args[0][2] == "merge:pr-001"  # merge_key

    @patch("pm_core.tui.review_loop_ui._find_impl_pane", return_value="%42")
    @patch("pm_core.tui.review_loop_ui._refresh_tech_tree")
    def test_no_merged_no_finalization(self, mock_refresh, mock_find_pane):
        """Without MERGED verdict, no finalization happens."""
        from pm_core.tui.review_loop_ui import _poll_impl_idle, _merge_verdict_stable

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

        assert "merge:pr-001" not in _merge_verdict_stable

    @patch("pm_core.tui.review_loop_ui._find_impl_pane", return_value="%42")
    @patch("pm_core.tui.review_loop_ui._refresh_tech_tree")
    def test_stability_resets_when_merged_disappears(self, mock_refresh, mock_find_pane):
        """If MERGED disappears from pane content, stability counter resets."""
        from pm_core.tui.review_loop_ui import _poll_impl_idle, _merge_verdict_stable

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
        assert _merge_verdict_stable.get("merge:pr-001") == 1

        # Second poll: MERGED gone (Claude doing more work)
        tracker.get_content.return_value = "still working..."
        _poll_impl_idle(app)
        assert "merge:pr-001" not in _merge_verdict_stable

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
    """Tests for _finalize_detected_merge helper."""

    def setup_method(self):
        from pm_core.tui import review_loop_ui
        review_loop_ui._merge_verdict_stable.clear()

    @patch("pm_core.tui.review_loop_ui.store")
    @patch("pm_core.tui.auto_start.check_and_start")
    @patch("pm_core.tui.auto_start.get_transcript_dir", return_value=None)
    @patch("pm_core.tui.pr_view.run_command")
    def test_successful_finalization(self, mock_run_cmd, mock_tdir,
                                      mock_check_start, mock_store):
        """When merge succeeds, cleans up tracking state and kicks off dependents."""
        from pm_core.tui.review_loop_ui import _finalize_detected_merge, _merge_verdict_stable

        app = _make_app()
        tracker = MagicMock()
        pending = {"pr-001"}
        active_keys = {"merge:pr-001"}
        _merge_verdict_stable["merge:pr-001"] = 2

        # After run_command, reload shows PR as merged
        merged_pr = _make_pr("pr-001", status="merged")
        mock_store.load.return_value = {"prs": [merged_pr]}
        mock_store.get_pr.return_value = merged_pr

        _finalize_detected_merge(app, "pr-001", "merge:pr-001",
                                  tracker, pending, active_keys)

        # Verify merge command was run
        mock_run_cmd.assert_called_once()
        cmd_arg = mock_run_cmd.call_args[0][1]
        assert "pr merge" in cmd_arg
        assert "pr-001" in cmd_arg

        # Tracking state cleaned up
        assert "pr-001" not in pending
        assert "merge:pr-001" not in active_keys
        assert "merge:pr-001" not in _merge_verdict_stable
        tracker.unregister.assert_called_once_with("merge:pr-001")

        # Dependents kicked off
        app.run_worker.assert_called_once()

    @patch("pm_core.tui.review_loop_ui.store")
    @patch("pm_core.tui.auto_start.get_transcript_dir", return_value=None)
    @patch("pm_core.tui.pr_view.run_command")
    def test_merge_not_finalized_adds_to_pending(self, mock_run_cmd, mock_tdir,
                                                   mock_store):
        """When merge command doesn't finalize, PR is added to pending_merges for idle fallback."""
        from pm_core.tui.review_loop_ui import _finalize_detected_merge, _merge_verdict_stable

        app = _make_app()
        tracker = MagicMock()
        pending = set()
        active_keys = {"merge:pr-001"}
        _merge_verdict_stable["merge:pr-001"] = 2

        # After run_command, PR is still in_review (merge didn't complete)
        still_reviewing = _make_pr("pr-001", status="in_review")
        mock_store.load.return_value = {"prs": [still_reviewing]}
        mock_store.get_pr.return_value = still_reviewing

        _finalize_detected_merge(app, "pr-001", "merge:pr-001",
                                  tracker, pending, active_keys)

        # PR added to pending for idle fallback
        assert "pr-001" in pending
        # Stability state cleared so detection can restart
        assert "merge:pr-001" not in _merge_verdict_stable
        # Tracker not unregistered (keep watching)
        tracker.unregister.assert_not_called()
        # No worker started
        app.run_worker.assert_not_called()


class TestMergeVerdictCleanup:
    """Tests that stale merge verdict state is cleaned up."""

    def setup_method(self):
        from pm_core.tui import review_loop_ui
        review_loop_ui._merge_verdict_stable.clear()

    @patch("pm_core.tui.review_loop_ui._find_impl_pane", return_value="%42")
    @patch("pm_core.tui.review_loop_ui._refresh_tech_tree")
    def test_already_merged_pr_cleans_up(self, mock_refresh, mock_find_pane):
        """PRs that are already merged get cleaned up from verdict state."""
        from pm_core.tui.review_loop_ui import _poll_impl_idle, _merge_verdict_stable

        # Pre-seed verdict state as if we were tracking
        _merge_verdict_stable["merge:pr-001"] = 1

        pr = _make_pr("pr-001", status="merged")
        app = _make_app(prs=[pr], pending_merges={"pr-001"})

        tracker = app._pane_idle_tracker
        tracker.tracked_keys.return_value = []

        _poll_impl_idle(app)

        assert "merge:pr-001" not in _merge_verdict_stable
        tracker.unregister.assert_called_with("merge:pr-001")
