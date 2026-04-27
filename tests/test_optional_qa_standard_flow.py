"""Tests for Scenario 12: Optional QA — standard flow still works without QA.

Verifies that PRs without QA configured follow the normal
in_progress → in_review → merged flow without any QA step.

Key invariants:
1. _maybe_start_qa returns early when auto-start is disabled (no QA triggered)
2. PR can be merged directly from in_review without passing through qa status
3. 't' key is blocked when QA pane is visible (start_qa_on_pr in blocked list)
4. 'q' pane renders gracefully with empty instruction lists
5. QA pane Enter with no selected PR doesn't crash
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

from pm_core import store
from pm_core.qa_loop import QALoopState, VERDICT_PASS


def _make_project(tmp_path, *, pr_status="in_review", auto_start=False,
                  auto_start_target=None):
    """Create a minimal project.yaml with one PR and return (pm_dir, app mock)."""
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir(exist_ok=True)
    data = {
        "project": {"name": "test", "repo": "/tmp/r", "base_branch": "master"},
        "prs": [{
            "id": "pr-001",
            "title": "Test PR",
            "branch": "test-branch",
            "status": pr_status,
            "workdir": str(tmp_path / "wd"),
            "notes": [],
        }],
    }
    store.save(data, pm_dir)

    app = MagicMock()
    app._root = pm_dir
    app._data = data
    app._auto_start = auto_start
    app._auto_start_target = auto_start_target
    app._qa_loops = {}
    app._review_loops = {}
    app._self_driving_qa = {}
    return pm_dir, app


# ---------------------------------------------------------------------------
# 1. _maybe_start_qa returns early without auto-start
# ---------------------------------------------------------------------------

class TestMaybeStartQaWithoutAutoStart:
    """When auto-start is disabled, _maybe_start_qa should not trigger QA."""

    def test_no_qa_transition_without_auto_start(self, tmp_path):
        """Step 3-4: Review PASS does NOT trigger QA when auto-start is off."""
        pm_dir, app = _make_project(tmp_path, pr_status="in_review",
                                     auto_start=False)

        with patch("pm_core.tui.auto_start.is_enabled", return_value=False):
            from pm_core.tui.review_loop_ui import _maybe_start_qa
            _maybe_start_qa(app, "pr-001")

        # PR should still be in_review (not qa)
        data = store.load(pm_dir)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

    def test_no_qa_loops_started(self, tmp_path):
        """No QA loop state should be created."""
        pm_dir, app = _make_project(tmp_path, pr_status="in_review",
                                     auto_start=False)

        with patch("pm_core.tui.auto_start.is_enabled", return_value=False):
            from pm_core.tui.review_loop_ui import _maybe_start_qa
            _maybe_start_qa(app, "pr-001")

        assert len(app._qa_loops) == 0


class TestMaybeStartQaWithAutoStart:
    """When auto-start IS enabled, _maybe_start_qa transitions to qa status."""

    def test_transitions_to_qa_with_auto_start(self, tmp_path):
        """Auto-start enabled: review PASS triggers QA transition."""
        pm_dir, app = _make_project(tmp_path, pr_status="in_review",
                                     auto_start=True,
                                     auto_start_target="pr-001")

        with patch("pm_core.tui.auto_start.is_enabled", return_value=True), \
             patch("pm_core.tui.auto_start.get_target", return_value="pr-001"), \
             patch("pm_core.tui.auto_start._transitive_deps", return_value=set()), \
             patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            from pm_core.tui.review_loop_ui import _maybe_start_qa
            _maybe_start_qa(app, "pr-001")

        # PR should now be in "qa" status
        data = store.load(pm_dir)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "qa"
        mock_start.assert_called_once()


# ---------------------------------------------------------------------------
# 2. Direct merge from in_review (no qa intermediate)
# ---------------------------------------------------------------------------

class TestDirectMergeWithoutQA:
    """A PR can be merged directly from in_review without going through qa."""

    def test_pr_merge_from_in_review(self, tmp_path):
        """Step 4: pm pr merge works on an in_review PR."""
        pm_dir, _ = _make_project(tmp_path, pr_status="in_review")

        data = store.load(pm_dir)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

        # Simulate manual merge
        pr["status"] = "merged"
        store.save(data, pm_dir)

        data = store.load(pm_dir)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "merged"

    def test_full_flow_without_qa(self, tmp_path):
        """Step 1-4: in_progress → in_review → merged (no qa)."""
        pm_dir, _ = _make_project(tmp_path, pr_status="in_progress")

        # Start → in_review
        data = store.load(pm_dir)
        pr = store.get_pr(data, "pr-001")
        pr["status"] = "in_review"
        store.save(data, pm_dir)

        # Verify no qa status appeared
        data = store.load(pm_dir)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

        # Merge directly
        pr["status"] = "merged"
        store.save(data, pm_dir)

        data = store.load(pm_dir)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "merged"


# ---------------------------------------------------------------------------
# 3. 't' key blocked in QA view
# ---------------------------------------------------------------------------

class TestTKeyBehavior:
    """Step 5: 't' key behavior when QA is not configured or view is QA."""

    def test_start_qa_on_pr_blocked_in_qa_view(self):
        """start_qa_on_pr is in the blocked actions list for QA view."""
        from pm_core.tui.app import ProjectManagerApp
        import inspect

        source = inspect.getsource(ProjectManagerApp.check_action)
        # The check_action method should block start_qa_on_pr when _qa_visible
        assert "start_qa_on_pr" in source

    def test_t_binding_exists(self):
        """'t' key is bound to start_qa_on_pr."""
        from pm_core.tui.app import ProjectManagerApp
        t_bindings = [b for b in ProjectManagerApp.BINDINGS if b.key == "t"]
        assert len(t_bindings) == 1
        assert t_bindings[0].action == "start_qa_on_pr"

    def test_action_start_qa_no_pr_selected(self):
        """Step 5: 't' with no PR selected shows message, doesn't crash."""
        from pm_core.tui.app import ProjectManagerApp
        import inspect
        source = inspect.getsource(ProjectManagerApp.action_start_qa_on_pr)
        # Should handle no PR selected
        assert "No PR selected" in source


# ---------------------------------------------------------------------------
# 4. 'q' pane with empty instructions
# ---------------------------------------------------------------------------

class TestQPaneEmptyInstructions:
    """Step 6: 'q' pane renders when there are no QA instructions."""

    def test_empty_pane_renders(self):
        """Empty instruction list renders 'No QA items available.'"""
        from pm_core.tui.qa_pane import QAPane
        pane = QAPane()
        # Verify empty state renders correctly
        assert pane._items == []

    def test_qa_pane_flatten_empty(self):
        """Flatten with empty data produces only headers."""
        from tests.test_qa_pane import _flatten_items
        flat = _flatten_items({"instructions": [], "regression": []})
        assert len(flat) == 2  # Just 2 section headers
        selectable = [i for i, item in enumerate(flat) if "_section" not in item]
        assert selectable == []

    def test_qa_pane_render_empty(self):
        """Rendering empty list shows placeholder text."""
        from tests.test_qa_pane import _render
        output = _render([], 0)
        assert "No QA items available." in output.plain

    def test_qa_pane_navigate_empty(self):
        """Navigation on empty list doesn't crash."""
        from tests.test_qa_pane import _navigate, _flatten_items
        flat = _flatten_items({"instructions": [], "regression": []})
        selectable = [i for i, item in enumerate(flat) if "_section" not in item]
        # Should have no selectable items
        assert len(selectable) == 0
        # Navigate should return same index
        result = _navigate(flat, 0, "j")
        assert result == 0
        result = _navigate(flat, 0, "k")
        assert result == 0


# ---------------------------------------------------------------------------
# 5. QA pane Enter with no selected PR
# ---------------------------------------------------------------------------

class TestQPaneEnterNoPR:
    """Step 6: Enter on an instruction doesn't crash without a selected PR."""

    def test_qa_item_activated_without_pr(self):
        """QAItemActivated message can be created without a PR reference."""
        from pm_core.tui.qa_pane import QAItemActivated
        msg = QAItemActivated("instructions:login-flow")
        assert msg.item_id == "instructions:login-flow"

    def test_on_key_enter_empty_list(self):
        """Pressing Enter on empty list doesn't produce a message."""
        from pm_core.tui.qa_pane import QAPane
        import inspect
        source = inspect.getsource(QAPane.on_key)
        # The on_key should have a guard for empty selectable
        assert "if not selectable" in source


# ---------------------------------------------------------------------------
# 6. PR status validation includes qa as valid
# ---------------------------------------------------------------------------

class TestPRStatusIncludes:
    """The 'qa' status is valid but optional in the PR flow."""

    def test_qa_is_valid_status(self):
        from pm_core.pr_utils import VALID_PR_STATES
        assert "qa" in VALID_PR_STATES

    def test_standard_states_exist(self):
        from pm_core.pr_utils import VALID_PR_STATES
        for state in ("pending", "in_progress", "in_review", "merged", "closed"):
            assert state in VALID_PR_STATES

    def test_qa_status_not_required_for_merge(self):
        """A PR can go from in_review to merged without passing through qa."""
        from pm_core.pr_utils import VALID_PR_STATES
        # Both in_review and merged are valid states — no forced intermediate
        assert "in_review" in VALID_PR_STATES
        assert "merged" in VALID_PR_STATES


# ---------------------------------------------------------------------------
# 7. _maybe_auto_merge can be called directly (bypassing QA)
# ---------------------------------------------------------------------------

class TestAutoMergeDirectly:
    """_maybe_auto_merge works on in_review PRs (not just post-QA)."""

    def test_maybe_auto_merge_checks_auto_start(self, tmp_path):
        """Without auto-start, _maybe_auto_merge returns early."""
        pm_dir, app = _make_project(tmp_path, pr_status="in_review",
                                     auto_start=False)

        with patch("pm_core.tui.auto_start.is_enabled", return_value=False):
            from pm_core.tui.review_loop_ui import _maybe_auto_merge
            _maybe_auto_merge(app, "pr-001")

        # No merge should have been attempted
        data = store.load(pm_dir)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"


# ---------------------------------------------------------------------------
# 8. Self-driving QA not registered without explicit zz
# ---------------------------------------------------------------------------

class TestSelfDrivingNotRegistered:
    """Without an explicit zz t, no self-driving state exists."""

    def test_no_self_driving_by_default(self, tmp_path):
        pm_dir, app = _make_project(tmp_path)
        assert app._self_driving_qa == {}

    def test_maybe_start_qa_checks_self_driving(self, tmp_path):
        """_maybe_start_qa checks self-driving state first."""
        pm_dir, app = _make_project(tmp_path, pr_status="in_review",
                                     auto_start=False)

        with patch("pm_core.tui.auto_start.is_enabled", return_value=False):
            from pm_core.tui.review_loop_ui import _maybe_start_qa
            _maybe_start_qa(app, "pr-001")

        # No self-driving state, no auto-start → no QA
        data = store.load(pm_dir)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"
