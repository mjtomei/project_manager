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
