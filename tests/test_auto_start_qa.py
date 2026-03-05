"""Tests for review-to-QA auto-transition via auto-start.

Covers scenario 8 steps:
 - _auto_start_qa_loops detects PRs in "qa" status and starts QA
 - Target PR scoping (only starts QA for transitive deps of target)
 - Skips PRs already running QA or with existing verdicts
 - _maybe_start_qa transitions PR from in_review → qa when review passes
 - Race guard between poll_qa_state completion handler and auto-start
 - Auto-start disabled → no QA loops started
"""

import pytest
from unittest.mock import patch, MagicMock, call

from pm_core.qa_loop import QALoopState, VERDICT_PASS, VERDICT_NEEDS_WORK
from pm_core import store


def _make_app(tmp_path, *, prs=None, auto_start=True, target=None):
    """Create a mock TUI app with PRs on disk."""
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir(exist_ok=True)
    if prs is None:
        prs = [{"id": "pr-001", "title": "T", "branch": "b",
                "status": "qa", "workdir": str(tmp_path / "wd"),
                "notes": []}]
    data = {
        "project": {"name": "test", "repo": "/tmp/r", "base_branch": "master"},
        "prs": prs,
    }
    store.save(data, pm_dir)

    app = MagicMock()
    app._root = pm_dir
    app._data = data
    app._auto_start = auto_start
    app._auto_start_target = target
    app._auto_start_run_id = None
    app._qa_loops = {}
    app._review_loops = {}
    app._self_driving_qa = {}
    return app


# ---------------------------------------------------------------------------
# _auto_start_qa_loops: basic detection
# ---------------------------------------------------------------------------

class TestAutoStartQALoopsDetection:
    """_auto_start_qa_loops detects PRs in 'qa' status and starts QA."""

    def test_starts_qa_for_qa_status_pr(self, tmp_path):
        """When auto-start is enabled and PR is in 'qa' status, starts QA."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        app = _make_app(tmp_path, auto_start=True)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_called_once_with(app, "pr-001")

    def test_skips_non_qa_status_prs(self, tmp_path):
        """PRs not in 'qa' status are not started."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        prs = [
            {"id": "pr-001", "title": "T", "branch": "b",
             "status": "in_review", "workdir": str(tmp_path / "wd"), "notes": []},
            {"id": "pr-002", "title": "T2", "branch": "b2",
             "status": "in_progress", "workdir": str(tmp_path / "wd2"), "notes": []},
            {"id": "pr-003", "title": "T3", "branch": "b3",
             "status": "merged", "workdir": str(tmp_path / "wd3"), "notes": []},
        ]
        app = _make_app(tmp_path, prs=prs, auto_start=True)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_not_called()

    def test_disabled_auto_start_skips_all(self, tmp_path):
        """When auto-start is disabled, no QA loops are started."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        app = _make_app(tmp_path, auto_start=False)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_not_called()

    def test_skips_pr_without_workdir(self, tmp_path):
        """PRs in 'qa' status but without a workdir are skipped."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        prs = [{"id": "pr-001", "title": "T", "branch": "b",
                "status": "qa", "workdir": "", "notes": []}]
        app = _make_app(tmp_path, prs=prs, auto_start=True)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_not_called()

    def test_starts_multiple_qa_prs(self, tmp_path):
        """Multiple PRs in 'qa' status all get started."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        prs = [
            {"id": "pr-001", "title": "T1", "branch": "b1",
             "status": "qa", "workdir": str(tmp_path / "wd1"), "notes": []},
            {"id": "pr-002", "title": "T2", "branch": "b2",
             "status": "qa", "workdir": str(tmp_path / "wd2"), "notes": []},
        ]
        app = _make_app(tmp_path, prs=prs, auto_start=True)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        assert mock_start.call_count == 2
        mock_start.assert_any_call(app, "pr-001")
        mock_start.assert_any_call(app, "pr-002")


# ---------------------------------------------------------------------------
# Target PR scoping
# ---------------------------------------------------------------------------

class TestAutoStartQATargetScoping:
    """_auto_start_qa_loops respects target PR scoping."""

    def test_with_target_only_starts_deps(self, tmp_path):
        """When target is set, only starts QA for PRs in its dep tree."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        prs = [
            {"id": "pr-001", "title": "Dep", "branch": "b1",
             "status": "qa", "workdir": str(tmp_path / "wd1"),
             "depends_on": [], "notes": []},
            {"id": "pr-002", "title": "Target", "branch": "b2",
             "status": "qa", "workdir": str(tmp_path / "wd2"),
             "depends_on": ["pr-001"], "notes": []},
            {"id": "pr-003", "title": "Unrelated", "branch": "b3",
             "status": "qa", "workdir": str(tmp_path / "wd3"),
             "depends_on": [], "notes": []},
        ]
        app = _make_app(tmp_path, prs=prs, auto_start=True, target="pr-002")

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app, target="pr-002", prs=prs)

        # pr-001 (dep of target) and pr-002 (target itself) should start
        # pr-003 (unrelated) should be skipped
        assert mock_start.call_count == 2
        started_ids = {c.args[1] for c in mock_start.call_args_list}
        assert started_ids == {"pr-001", "pr-002"}

    def test_without_target_starts_all_qa_prs(self, tmp_path):
        """Without a target, all qa-status PRs are started."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        prs = [
            {"id": "pr-001", "title": "T1", "branch": "b1",
             "status": "qa", "workdir": str(tmp_path / "wd1"), "notes": []},
            {"id": "pr-002", "title": "T2", "branch": "b2",
             "status": "qa", "workdir": str(tmp_path / "wd2"), "notes": []},
        ]
        app = _make_app(tmp_path, prs=prs, auto_start=True)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app, target=None, prs=prs)

        assert mock_start.call_count == 2

    def test_transitive_deps_included(self, tmp_path):
        """Transitive deps (not just direct) of target are included."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        prs = [
            {"id": "pr-a", "title": "Root dep", "branch": "ba",
             "status": "qa", "workdir": str(tmp_path / "wda"),
             "depends_on": [], "notes": []},
            {"id": "pr-b", "title": "Mid dep", "branch": "bb",
             "status": "qa", "workdir": str(tmp_path / "wdb"),
             "depends_on": ["pr-a"], "notes": []},
            {"id": "pr-c", "title": "Target", "branch": "bc",
             "status": "qa", "workdir": str(tmp_path / "wdc"),
             "depends_on": ["pr-b"], "notes": []},
        ]
        app = _make_app(tmp_path, prs=prs, auto_start=True, target="pr-c")

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app, target="pr-c", prs=prs)

        # All three: pr-a (transitive), pr-b (direct dep), pr-c (target)
        assert mock_start.call_count == 3
        started_ids = {c.args[1] for c in mock_start.call_args_list}
        assert started_ids == {"pr-a", "pr-b", "pr-c"}


# ---------------------------------------------------------------------------
# Skip already running QA or existing verdicts
# ---------------------------------------------------------------------------

class TestAutoStartQASkipRunning:
    """_auto_start_qa_loops skips PRs already running QA or with verdicts."""

    def test_skips_running_qa(self, tmp_path):
        """PRs with a running QA loop are skipped."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        app = _make_app(tmp_path, auto_start=True)

        # Simulate running QA loop
        state = QALoopState(pr_id="pr-001")
        state.running = True
        app._qa_loops["pr-001"] = state

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_not_called()

    def test_skips_completed_with_verdict(self, tmp_path):
        """PRs with a verdict (awaiting poll_qa_state processing) are skipped."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        app = _make_app(tmp_path, auto_start=True)

        # Simulate completed QA loop (not running, but has verdict)
        state = QALoopState(pr_id="pr-001")
        state.running = False
        state.latest_verdict = VERDICT_PASS
        app._qa_loops["pr-001"] = state

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_not_called()

    def test_starts_qa_when_loop_entry_absent(self, tmp_path):
        """PR in 'qa' status with no loop entry gets started."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        app = _make_app(tmp_path, auto_start=True)
        # No entry in _qa_loops at all
        assert "pr-001" not in app._qa_loops

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_called_once_with(app, "pr-001")

    def test_starts_qa_when_old_loop_cleaned_up(self, tmp_path):
        """After poll_qa_state removes a completed loop, auto-start restarts."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        app = _make_app(tmp_path, auto_start=True)
        # Simulate that poll_qa_state already cleaned up the entry
        # (no entry in _qa_loops)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_called_once_with(app, "pr-001")


# ---------------------------------------------------------------------------
# Race guard: poll_qa_state vs auto-start
# ---------------------------------------------------------------------------

class TestRaceGuard:
    """Race guard prevents auto-start from restarting QA before poll_qa_state runs."""

    def test_race_window_protected_by_latest_verdict(self, tmp_path):
        """In the race window (running=False, verdict set, poll not yet run),
        auto-start must NOT restart QA."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        app = _make_app(tmp_path, auto_start=True)

        # This is the race window: QA thread finished (running=False),
        # verdict is set, but poll_qa_state hasn't processed it yet
        state = QALoopState(pr_id="pr-001")
        state.running = False
        state.latest_verdict = VERDICT_NEEDS_WORK
        state._ui_complete_notified = False  # poll hasn't run yet
        app._qa_loops["pr-001"] = state

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_not_called()

    def test_after_poll_cleanup_auto_start_can_restart(self, tmp_path):
        """After poll_qa_state removes the loop entry, auto-start can restart."""
        from pm_core.tui.auto_start import _auto_start_qa_loops
        from pm_core.tui.qa_loop_ui import poll_qa_state

        app = _make_app(tmp_path, auto_start=True)

        # Set up a completed loop
        state = QALoopState(pr_id="pr-001")
        state.running = False
        state.latest_verdict = VERDICT_PASS
        state._ui_complete_notified = False
        app._qa_loops["pr-001"] = state

        # First poll: marks _ui_complete_notified, calls _on_qa_complete
        with patch("pm_core.tui.qa_loop_ui._on_qa_complete"):
            poll_qa_state(app)
        assert state._ui_complete_notified is True
        assert "pr-001" in app._qa_loops  # still present for one cycle

        # Second poll: removes the entry
        with patch("pm_core.tui.qa_loop_ui._on_qa_complete"):
            poll_qa_state(app)
        assert "pr-001" not in app._qa_loops

        # Now auto-start can restart QA
        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_called_once_with(app, "pr-001")


# ---------------------------------------------------------------------------
# _maybe_start_qa: review-to-QA transition
# ---------------------------------------------------------------------------

class TestMaybeStartQA:
    """_maybe_start_qa transitions PR from in_review → qa on review pass."""

    def test_transitions_pr_to_qa_status(self, tmp_path):
        """When review passes, PR status transitions from in_review to qa."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa

        prs = [{"id": "pr-001", "title": "T", "branch": "b",
                "status": "in_review", "workdir": str(tmp_path / "wd"),
                "notes": []}]
        app = _make_app(tmp_path, prs=prs, auto_start=True, target="pr-001")

        with patch("pm_core.tui.qa_loop_ui.start_qa"):
            _maybe_start_qa(app, "pr-001")

        # Verify the PR status changed on disk
        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "qa"

    def test_starts_qa_loop_after_transition(self, tmp_path):
        """After transitioning to qa, a QA loop is started."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa

        prs = [{"id": "pr-001", "title": "T", "branch": "b",
                "status": "in_review", "workdir": str(tmp_path / "wd"),
                "notes": []}]
        app = _make_app(tmp_path, prs=prs, auto_start=True, target="pr-001")

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-001")

        mock_start.assert_called_once_with(app, "pr-001")

    def test_no_transition_when_auto_start_disabled(self, tmp_path):
        """Without auto-start (and no self-driving), no transition occurs."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa

        prs = [{"id": "pr-001", "title": "T", "branch": "b",
                "status": "in_review", "workdir": str(tmp_path / "wd"),
                "notes": []}]
        app = _make_app(tmp_path, prs=prs, auto_start=False)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-001")

        mock_start.assert_not_called()
        # PR should remain in_review
        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

    def test_scoped_to_target_deps(self, tmp_path):
        """PR outside the target's dep tree is not transitioned."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa

        prs = [
            {"id": "pr-001", "title": "Unrelated", "branch": "b1",
             "status": "in_review", "workdir": str(tmp_path / "wd1"),
             "depends_on": [], "notes": []},
            {"id": "pr-002", "title": "Target", "branch": "b2",
             "status": "in_progress", "workdir": str(tmp_path / "wd2"),
             "depends_on": [], "notes": []},
        ]
        app = _make_app(tmp_path, prs=prs, auto_start=True, target="pr-002")

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-001")

        # pr-001 is not in pr-002's dep tree, so no transition
        mock_start.assert_not_called()
        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

    def test_self_driving_bypasses_auto_start_check(self, tmp_path):
        """In self-driving mode, _maybe_start_qa works even without auto-start."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa

        prs = [{"id": "pr-001", "title": "T", "branch": "b",
                "status": "in_review", "workdir": str(tmp_path / "wd"),
                "notes": []}]
        app = _make_app(tmp_path, prs=prs, auto_start=False)
        # Set up self-driving state
        app._self_driving_qa = {"pr-001": {"strict": False, "pass_count": 0,
                                            "required_passes": 1}}

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-001")

        mock_start.assert_called_once_with(app, "pr-001")
        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "qa"


# ---------------------------------------------------------------------------
# check_and_start integration: calls _auto_start_qa_loops
# ---------------------------------------------------------------------------

class TestCheckAndStartCallsQALoops:
    """check_and_start calls _auto_start_qa_loops after processing ready PRs."""

    def test_check_and_start_triggers_qa_loops(self, tmp_path):
        """check_and_start calls _auto_start_qa_loops at the end."""
        import asyncio
        from pm_core.tui.auto_start import check_and_start

        app = _make_app(tmp_path, auto_start=True)

        with patch("pm_core.tui.auto_start._auto_start_qa_loops") as mock_qa, \
             patch("pm_core.tui.auto_start._auto_start_review_loops"):
            asyncio.run(check_and_start(app))

        mock_qa.assert_called_once()
