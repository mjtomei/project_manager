"""Tests for deferred PR re-sort until TUI is idle."""

import time
from unittest.mock import MagicMock, patch


SAMPLE_PRS = [
    {"id": "pr-001", "title": "First PR", "status": "in_progress", "depends_on": []},
    {"id": "pr-002", "title": "Second PR", "status": "pending", "depends_on": []},
    {"id": "pr-003", "title": "Third PR", "status": "merged", "depends_on": ["pr-001"]},
]


# ---------------------------------------------------------------------------
# TechTree.update_prs with recompute parameter
# ---------------------------------------------------------------------------

class TestTechTreeDeferredResort:
    """Tests for TechTree.update_prs(recompute=...) and apply_pending_resort."""

    def _make_tree(self):
        """Create a TechTree instance with mocked Textual internals."""
        from pm_core.tui.tech_tree import TechTree
        # Use a MagicMock that has the real methods but mocked Textual plumbing.
        tree = MagicMock(spec=TechTree)
        tree._prs = []
        tree._resort_pending = False
        # Bind real methods so we test actual logic
        tree.update_prs = TechTree.update_prs.__get__(tree, TechTree)
        tree.apply_pending_resort = TechTree.apply_pending_resort.__get__(tree, TechTree)
        return tree

    def test_update_prs_recompute_true_clears_pending(self):
        """update_prs(recompute=True) recomputes layout and clears pending flag."""
        tree = self._make_tree()
        tree._resort_pending = True  # simulate pending state
        with patch.object(tree, '_recompute'):
            tree.update_prs(SAMPLE_PRS, recompute=True)

        assert tree._prs == SAMPLE_PRS
        assert tree._resort_pending is False
        tree.refresh.assert_called_with(layout=True)

    def test_update_prs_recompute_false_sets_pending(self):
        """update_prs(recompute=False) updates data but sets pending flag."""
        tree = self._make_tree()
        with patch.object(tree, '_recompute') as mock_recompute:
            tree.update_prs(SAMPLE_PRS, recompute=False)

        assert tree._prs == SAMPLE_PRS
        assert tree._resort_pending is True
        mock_recompute.assert_not_called()
        # refresh() called without layout=True
        tree.refresh.assert_called_once_with()

    def test_update_prs_default_recompute_true(self):
        """update_prs() defaults to recompute=True."""
        tree = self._make_tree()
        with patch.object(tree, '_recompute'):
            tree.update_prs(SAMPLE_PRS)

        assert tree._resort_pending is False
        tree.refresh.assert_called_with(layout=True)

    def test_apply_pending_resort_when_pending(self):
        """apply_pending_resort() recomputes and clears flag when pending."""
        tree = self._make_tree()
        tree._resort_pending = True
        with patch.object(tree, '_recompute') as mock_recompute:
            tree.apply_pending_resort()

        mock_recompute.assert_called_once()
        assert tree._resort_pending is False
        tree.refresh.assert_called_with(layout=True)

    def test_apply_pending_resort_noop_when_not_pending(self):
        """apply_pending_resort() does nothing when no resort is pending."""
        tree = self._make_tree()
        tree._resort_pending = False
        with patch.object(tree, '_recompute') as mock_recompute:
            tree.apply_pending_resort()

        mock_recompute.assert_not_called()
        tree.refresh.assert_not_called()


# ---------------------------------------------------------------------------
# App idle detection
# ---------------------------------------------------------------------------

class TestAppIdleDetection:
    """Tests for ProjectManagerApp idle detection and resort scheduling."""

    def _make_app(self):
        """Create a minimal app mock with the idle detection attributes."""
        from pm_core.tui.app import ProjectManagerApp
        app = ProjectManagerApp.__new__(ProjectManagerApp)
        app._last_interaction = 0.0
        app._resort_check_timer = None
        return app

    def test_is_tui_idle_no_interaction(self):
        """TUI is idle when no interaction has occurred (startup)."""
        app = self._make_app()
        assert app._is_tui_idle() is True

    def test_is_tui_idle_recent_interaction(self):
        """TUI is not idle right after an interaction."""
        app = self._make_app()
        app._last_interaction = time.monotonic()
        assert app._is_tui_idle() is False

    def test_is_tui_idle_after_timeout(self):
        """TUI is idle when interaction was longer ago than the timeout."""
        app = self._make_app()
        timeout = app._get_resort_idle_timeout()
        app._last_interaction = time.monotonic() - timeout - 1.0
        assert app._is_tui_idle() is True

    def test_default_timeout_is_10(self):
        """Default re-sort idle timeout is 10 seconds."""
        app = self._make_app()
        assert app._get_resort_idle_timeout() == 10.0

    def test_configurable_timeout(self):
        """Re-sort idle timeout is configurable via global setting."""
        app = self._make_app()
        with patch("pm_core.paths.get_global_setting_value", return_value="5"):
            assert app._get_resort_idle_timeout() == 5.0

    def test_invalid_timeout_falls_back_to_default(self):
        """Invalid setting value falls back to default timeout."""
        app = self._make_app()
        with patch("pm_core.paths.get_global_setting_value", return_value="not-a-number"):
            assert app._get_resort_idle_timeout() == 10.0


# ---------------------------------------------------------------------------
# Integration: _update_display with defer_resort
# ---------------------------------------------------------------------------

class TestUpdateDisplayDeferred:
    """Tests for _update_display(defer_resort=True) behavior."""

    def test_update_display_default_is_immediate(self):
        """_update_display() with default args does immediate recompute."""
        from pm_core.tui.app import ProjectManagerApp
        app = ProjectManagerApp.__new__(ProjectManagerApp)
        app._data = {"project": {"name": "test"}, "prs": SAMPLE_PRS}

        mock_tree = MagicMock()
        mock_tree._resort_pending = False
        mock_status_bar = MagicMock()

        with patch.object(app, 'query_one', side_effect=lambda sel, cls=None: mock_tree if "tech-tree" in sel else mock_status_bar), \
             patch.object(app, '_update_status_bar'), \
             patch.object(app, '_update_filter_status'), \
             patch('pm_core.tui.review_loop_ui.ensure_animation_timer'):
            app._update_display()

        # update_prs called with default (recompute=True)
        mock_tree.update_prs.assert_called_once_with(SAMPLE_PRS)

    def test_update_display_defer_when_active(self):
        """_update_display(defer_resort=True) defers recompute when TUI is active."""
        from pm_core.tui.app import ProjectManagerApp
        app = ProjectManagerApp.__new__(ProjectManagerApp)
        app._data = {"project": {"name": "test"}, "prs": SAMPLE_PRS}
        app._last_interaction = time.monotonic()  # just interacted
        app._resort_check_timer = None

        mock_tree = MagicMock()
        mock_tree._resort_pending = False
        mock_status_bar = MagicMock()

        with patch.object(app, 'query_one', side_effect=lambda sel, cls=None: mock_tree if "tech-tree" in sel else mock_status_bar), \
             patch.object(app, '_update_status_bar'), \
             patch.object(app, '_update_filter_status'), \
             patch.object(app, '_schedule_resort_check') as mock_schedule, \
             patch('pm_core.tui.review_loop_ui.ensure_animation_timer'):
            app._update_display(defer_resort=True)

        # update_prs called with recompute=False
        mock_tree.update_prs.assert_called_once_with(SAMPLE_PRS, recompute=False)
        mock_schedule.assert_called_once()

    def test_update_display_defer_but_idle(self):
        """_update_display(defer_resort=True) does immediate recompute when TUI is idle."""
        from pm_core.tui.app import ProjectManagerApp
        app = ProjectManagerApp.__new__(ProjectManagerApp)
        app._data = {"project": {"name": "test"}, "prs": SAMPLE_PRS}
        app._last_interaction = 0.0  # no interaction (startup)
        app._resort_check_timer = None

        mock_tree = MagicMock()
        mock_tree._resort_pending = False
        mock_status_bar = MagicMock()

        with patch.object(app, 'query_one', side_effect=lambda sel, cls=None: mock_tree if "tech-tree" in sel else mock_status_bar), \
             patch.object(app, '_update_status_bar'), \
             patch.object(app, '_update_filter_status'), \
             patch('pm_core.tui.review_loop_ui.ensure_animation_timer'):
            app._update_display(defer_resort=True)

        # update_prs called with default (recompute=True) since idle
        mock_tree.update_prs.assert_called_once_with(SAMPLE_PRS)
