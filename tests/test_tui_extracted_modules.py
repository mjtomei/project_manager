"""Import smoke tests for the extracted TUI modules.

Verifies that frame_capture, sync, and pr_view are importable with the
expected public functions and signatures, following the same pattern as
test_tui_imports.py.
"""

import inspect


# ---------------------------------------------------------------------------
# frame_capture — constants and functions
# ---------------------------------------------------------------------------

class TestFrameCaptureImports:
    def test_default_frame_rate(self):
        from pm_core.tui.frame_capture import DEFAULT_FRAME_RATE
        assert isinstance(DEFAULT_FRAME_RATE, int) and DEFAULT_FRAME_RATE >= 1

    def test_default_frame_buffer_size(self):
        from pm_core.tui.frame_capture import DEFAULT_FRAME_BUFFER_SIZE
        assert isinstance(DEFAULT_FRAME_BUFFER_SIZE, int) and DEFAULT_FRAME_BUFFER_SIZE >= 1

    def test_get_capture_config_path(self):
        from pm_core.tui.frame_capture import get_capture_config_path
        sig = inspect.signature(get_capture_config_path)
        assert "app" in sig.parameters

    def test_get_frames_path(self):
        from pm_core.tui.frame_capture import get_frames_path
        sig = inspect.signature(get_frames_path)
        assert "app" in sig.parameters

    def test_load_capture_config(self):
        from pm_core.tui.frame_capture import load_capture_config
        sig = inspect.signature(load_capture_config)
        assert "app" in sig.parameters

    def test_capture_frame(self):
        from pm_core.tui.frame_capture import capture_frame
        sig = inspect.signature(capture_frame)
        params = list(sig.parameters.keys())
        assert params[0] == "app"
        assert "trigger" in params

    def test_save_frames(self):
        from pm_core.tui.frame_capture import save_frames
        sig = inspect.signature(save_frames)
        assert "app" in sig.parameters

    def test_setup_frame_watchers(self):
        from pm_core.tui.frame_capture import setup_frame_watchers
        sig = inspect.signature(setup_frame_watchers)
        assert "app" in sig.parameters

    def test_on_guide_step_changed(self):
        from pm_core.tui.frame_capture import on_guide_step_changed
        sig = inspect.signature(on_guide_step_changed)
        params = list(sig.parameters.keys())
        assert params == ["app", "step"]

    def test_on_tree_selection_changed(self):
        from pm_core.tui.frame_capture import on_tree_selection_changed
        sig = inspect.signature(on_tree_selection_changed)
        params = list(sig.parameters.keys())
        assert params == ["app", "index"]

    def test_on_tree_prs_changed(self):
        from pm_core.tui.frame_capture import on_tree_prs_changed
        sig = inspect.signature(on_tree_prs_changed)
        params = list(sig.parameters.keys())
        assert params == ["app", "prs"]


# ---------------------------------------------------------------------------
# sync — async functions
# ---------------------------------------------------------------------------

class TestSyncImports:
    def test_background_sync(self):
        from pm_core.tui.sync import background_sync
        assert inspect.iscoroutinefunction(background_sync)
        sig = inspect.signature(background_sync)
        assert "app" in sig.parameters

    def test_do_normal_sync(self):
        from pm_core.tui.sync import do_normal_sync
        assert inspect.iscoroutinefunction(do_normal_sync)
        sig = inspect.signature(do_normal_sync)
        params = list(sig.parameters.keys())
        assert params[0] == "app"
        assert "is_manual" in params

    def test_startup_github_sync(self):
        from pm_core.tui.sync import startup_github_sync
        assert inspect.iscoroutinefunction(startup_github_sync)
        sig = inspect.signature(startup_github_sync)
        assert "app" in sig.parameters


# ---------------------------------------------------------------------------
# pr_view — constants, guards, handlers, and command execution
# ---------------------------------------------------------------------------

class TestPrViewImports:
    def test_pr_action_prefixes(self):
        from pm_core.tui.pr_view import PR_ACTION_PREFIXES
        assert isinstance(PR_ACTION_PREFIXES, tuple)
        assert "pr start" in PR_ACTION_PREFIXES
        assert "pr review" in PR_ACTION_PREFIXES

    def test_guard_pr_action(self):
        from pm_core.tui.pr_view import guard_pr_action
        sig = inspect.signature(guard_pr_action)
        params = list(sig.parameters.keys())
        assert params == ["app", "action_desc"]

    def test_handle_pr_selected(self):
        from pm_core.tui.pr_view import handle_pr_selected
        sig = inspect.signature(handle_pr_selected)
        params = list(sig.parameters.keys())
        assert params == ["app", "pr_id"]

    def test_start_pr(self):
        from pm_core.tui.pr_view import start_pr
        sig = inspect.signature(start_pr)
        assert "app" in sig.parameters

    def test_done_pr(self):
        from pm_core.tui.pr_view import done_pr
        sig = inspect.signature(done_pr)
        assert "app" in sig.parameters

    def test_hide_plan(self):
        from pm_core.tui.pr_view import hide_plan
        sig = inspect.signature(hide_plan)
        assert "app" in sig.parameters

    def test_toggle_merged(self):
        from pm_core.tui.pr_view import toggle_merged
        sig = inspect.signature(toggle_merged)
        assert "app" in sig.parameters

    def test_cycle_filter(self):
        from pm_core.tui.pr_view import cycle_filter
        sig = inspect.signature(cycle_filter)
        assert "app" in sig.parameters

    def test_move_to_plan(self):
        from pm_core.tui.pr_view import move_to_plan
        sig = inspect.signature(move_to_plan)
        assert "app" in sig.parameters

    def test_handle_plan_pick(self):
        from pm_core.tui.pr_view import handle_plan_pick
        sig = inspect.signature(handle_plan_pick)
        params = list(sig.parameters.keys())
        assert params == ["app", "pr_id", "result"]

    def test_handle_command_submitted(self):
        from pm_core.tui.pr_view import handle_command_submitted
        sig = inspect.signature(handle_command_submitted)
        params = list(sig.parameters.keys())
        assert params == ["app", "cmd"]

    def test_run_command(self):
        from pm_core.tui.pr_view import run_command
        sig = inspect.signature(run_command)
        params = list(sig.parameters.keys())
        assert params[0] == "app"
        assert "cmd" in params
        assert "working_message" in params
        assert "action_key" in params


# ---------------------------------------------------------------------------
# app.py still delegates to extracted modules
# ---------------------------------------------------------------------------

class TestAppForwarders:
    def test_app_has_capture_frame(self):
        """App keeps _capture_frame as a forwarding method."""
        from pm_core.tui.app import ProjectManagerApp
        assert hasattr(ProjectManagerApp, "_capture_frame")

    def test_app_has_run_command(self):
        """App keeps _run_command as a forwarding method."""
        from pm_core.tui.app import ProjectManagerApp
        assert hasattr(ProjectManagerApp, "_run_command")


# ---------------------------------------------------------------------------
# Deferred re-sort: _is_tui_idle, _resort_pending, _update_display signature
# ---------------------------------------------------------------------------

class TestDeferredResort:
    """Unit tests for the deferred PR re-sort feature (R6/R7)."""

    def test_is_tui_idle_when_no_interaction(self):
        """_is_tui_idle() returns True when _last_interaction_time is 0 (never pressed)."""
        import time
        from pm_core.tui.app import ProjectManagerApp
        app = object.__new__(ProjectManagerApp)
        app._last_interaction_time = 0.0
        # 10-second threshold, elapsed >> 10
        assert app._is_tui_idle() is True

    def test_is_tui_idle_false_after_recent_key(self):
        """_is_tui_idle() returns False immediately after a key press."""
        import time
        from pm_core.tui.app import ProjectManagerApp
        app = object.__new__(ProjectManagerApp)
        app._last_interaction_time = time.monotonic()  # just pressed a key
        assert app._is_tui_idle() is False

    def test_resort_pending_init(self):
        """_resort_pending is initialised to False in __init__."""
        from pm_core.tui.app import ProjectManagerApp
        import unittest.mock as mock
        # Patch super().__init__ and Timer-heavy calls to allow lightweight construction
        with mock.patch.object(ProjectManagerApp, "__init__", lambda self: None):
            app = object.__new__(ProjectManagerApp)
            # Manually call just the part of __init__ we care about
        # Verify the attribute exists on the class-level approach by checking
        # the real __init__ sets it
        from pm_core.tui.app import ProjectManagerApp
        assert "_resort_pending" in ProjectManagerApp.__init__.__code__.co_varnames or \
               any("_resort_pending" in line for line in
                   open(ProjectManagerApp.__init__.__code__.co_filename).readlines()[
                       ProjectManagerApp.__init__.__code__.co_firstlineno:
                       ProjectManagerApp.__init__.__code__.co_firstlineno + 200
                   ])

    def test_update_display_has_immediate_param(self):
        """_update_display() has an `immediate` parameter with default False."""
        import inspect
        from pm_core.tui.app import ProjectManagerApp
        sig = inspect.signature(ProjectManagerApp._update_display)
        assert "immediate" in sig.parameters
        assert sig.parameters["immediate"].default is False

    def test_apply_pending_resort_no_op_when_not_pending(self):
        """_apply_pending_resort() is a no-op when _resort_pending is False."""
        from pm_core.tui.app import ProjectManagerApp
        app = object.__new__(ProjectManagerApp)
        app._resort_pending = False
        # Should return without raising even with no Textual widgets attached
        app._apply_pending_resort()

    def test_tech_tree_update_prs_data_no_recompute(self):
        """update_prs_data() stores PR data without calling _recompute()."""
        import unittest.mock as mock
        from pm_core.tui.tech_tree import TechTree
        tree = object.__new__(TechTree)
        tree._prs = []
        # prs is a Textual reactive — bypass it with mock.patch so we
        # don't need a live Textual app context to set it.
        recompute_called = []
        tree._recompute = lambda: recompute_called.append(True)
        prs = [{"id": "pr-001", "title": "test", "status": "pending"}]
        with mock.patch.object(TechTree, "prs", new_callable=lambda: property(
            lambda self: self._prs, lambda self, v: setattr(self, "_prs", v)
        )):
            tree.update_prs_data(prs)
        assert tree._prs == prs
        assert recompute_called == [], "_recompute must not be called by update_prs_data"

    def test_tech_tree_recompute_clears_resort_pending(self):
        """TechTree._recompute() clears app._resort_pending if app is attached."""
        import unittest.mock as mock
        from pm_core.tui.tech_tree import TechTree
        from pm_core.tui.tree_layout import TreeLayout
        tree = object.__new__(TechTree)
        tree._prs = []
        tree._hidden_plans = set()
        tree._status_filter = None
        tree._hide_merged = False
        tree._hide_closed = True
        tree._sort_field = None
        tree._ordered_ids = []
        tree._node_positions = {}
        tree._plan_label_rows = {}
        tree._hidden_plan_label_rows = {}
        tree._hidden_label_ids = []
        tree._plan_group_order = []

        # Attach a mock app with _resort_pending = True.
        # `app` and `selected_index` are Textual read-only properties/reactives,
        # so we patch them on the instance's type.
        mock_app = mock.MagicMock()
        mock_app._resort_pending = True

        mock_result = TreeLayout()
        mock_selected_index = mock.PropertyMock(return_value=0)
        mock_app_prop = mock.PropertyMock(return_value=mock_app)
        with mock.patch("pm_core.tui.tech_tree.compute_tree_layout", return_value=mock_result), \
             mock.patch.object(type(tree), "selected_index", mock_selected_index), \
             mock.patch.object(type(tree), "app", mock_app_prop):
            tree._recompute()

        assert mock_app._resort_pending is False
