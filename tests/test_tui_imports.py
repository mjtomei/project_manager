"""Import smoke tests for the tui module split.

Verifies that all screen, widget, and pane_ops classes/functions are
importable from their new modules, and that existing import paths
(e.g., from pm_core.tui.app import ProjectManagerApp) still work.
"""

import inspect


# ---------------------------------------------------------------------------
# Screen classes importable from tui.screens
# ---------------------------------------------------------------------------

class TestScreenImports:
    def test_welcome_screen(self):
        from pm_core.tui.screens import WelcomeScreen
        assert WelcomeScreen is not None

    def test_connect_screen(self):
        from pm_core.tui.screens import ConnectScreen
        assert ConnectScreen is not None

    def test_help_screen(self):
        from pm_core.tui.screens import HelpScreen
        assert HelpScreen is not None

    def test_plan_picker_screen(self):
        from pm_core.tui.screens import PlanPickerScreen
        assert PlanPickerScreen is not None

    def test_plan_add_screen(self):
        from pm_core.tui.screens import PlanAddScreen
        assert PlanAddScreen is not None

    def test_all_screens_are_modal(self):
        from textual.screen import ModalScreen
        from pm_core.tui.screens import (
            WelcomeScreen, ConnectScreen, HelpScreen,
            PlanPickerScreen, PlanAddScreen,
        )
        for cls in (WelcomeScreen, ConnectScreen, HelpScreen,
                    PlanPickerScreen, PlanAddScreen):
            assert issubclass(cls, ModalScreen), f"{cls.__name__} is not a ModalScreen"


# ---------------------------------------------------------------------------
# Widget classes importable from tui.widgets
# ---------------------------------------------------------------------------

class TestWidgetImports:
    def test_tree_scroll(self):
        from pm_core.tui.widgets import TreeScroll
        assert TreeScroll is not None

    def test_status_bar(self):
        from pm_core.tui.widgets import StatusBar
        assert StatusBar is not None

    def test_status_bar_has_update_status(self):
        from pm_core.tui.widgets import StatusBar
        assert hasattr(StatusBar, "update_status")
        sig = inspect.signature(StatusBar.update_status)
        params = list(sig.parameters.keys())
        assert "project_name" in params
        assert "repo" in params
        assert "sync_state" in params

    def test_log_line(self):
        from pm_core.tui.widgets import LogLine
        assert LogLine is not None


# ---------------------------------------------------------------------------
# pane_ops functions importable and have expected signatures
# ---------------------------------------------------------------------------

class TestPaneOpsImports:
    def test_launch_pane(self):
        from pm_core.tui.pane_ops import launch_pane
        sig = inspect.signature(launch_pane)
        params = list(sig.parameters.keys())
        assert params == ["app", "cmd", "role", "fresh"]

    def test_rebalance(self):
        from pm_core.tui.pane_ops import rebalance
        sig = inspect.signature(rebalance)
        assert "app" in sig.parameters

    def test_get_session_and_window(self):
        from pm_core.tui.pane_ops import get_session_and_window
        sig = inspect.signature(get_session_and_window)
        assert "app" in sig.parameters

    def test_find_editor(self):
        from pm_core.tui.pane_ops import find_editor
        assert callable(find_editor)

    def test_launch_claude(self):
        from pm_core.tui.pane_ops import launch_claude
        sig = inspect.signature(launch_claude)
        assert "app" in sig.parameters

    def test_launch_help_claude(self):
        from pm_core.tui.pane_ops import launch_help_claude
        sig = inspect.signature(launch_help_claude)
        assert "app" in sig.parameters

    def test_edit_plan(self):
        from pm_core.tui.pane_ops import edit_plan
        sig = inspect.signature(edit_plan)
        assert "app" in sig.parameters

    def test_view_plan(self):
        from pm_core.tui.pane_ops import view_plan
        sig = inspect.signature(view_plan)
        assert "app" in sig.parameters

    def test_launch_notes(self):
        from pm_core.tui.pane_ops import launch_notes
        assert callable(launch_notes)

    def test_view_log(self):
        from pm_core.tui.pane_ops import view_log
        assert callable(view_log)

    def test_launch_meta(self):
        from pm_core.tui.pane_ops import launch_meta
        assert callable(launch_meta)

    def test_launch_test(self):
        from pm_core.tui.pane_ops import launch_test
        sig = inspect.signature(launch_test)
        params = list(sig.parameters.keys())
        assert params == ["app", "test_id"]

    def test_handle_plan_action(self):
        from pm_core.tui.pane_ops import handle_plan_action
        sig = inspect.signature(handle_plan_action)
        params = list(sig.parameters.keys())
        assert params == ["app", "action", "plan_id"]

    def test_handle_plan_add(self):
        from pm_core.tui.pane_ops import handle_plan_add
        assert callable(handle_plan_add)

    def test_quit_app(self):
        from pm_core.tui.pane_ops import quit_app
        assert callable(quit_app)

    def test_restart_app(self):
        from pm_core.tui.pane_ops import restart_app
        assert callable(restart_app)

    def test_show_connect(self):
        from pm_core.tui.pane_ops import show_connect
        assert callable(show_connect)

    def test_toggle_guide(self):
        from pm_core.tui.pane_ops import toggle_guide
        assert callable(toggle_guide)

    def test_auto_launch_guide(self):
        from pm_core.tui.pane_ops import auto_launch_guide
        assert callable(auto_launch_guide)

    def test_guide_setup_steps_constant(self):
        from pm_core.tui.pane_ops import GUIDE_SETUP_STEPS
        assert isinstance(GUIDE_SETUP_STEPS, set)
        assert "no_project" in GUIDE_SETUP_STEPS


# ---------------------------------------------------------------------------
# Backward-compatible imports from tui.app
# ---------------------------------------------------------------------------

class TestBackwardCompatImports:
    def test_project_manager_app(self):
        """ProjectManagerApp is still importable from tui.app."""
        from pm_core.tui.app import ProjectManagerApp
        assert ProjectManagerApp is not None

    def test_connect_screen_from_app(self):
        """ConnectScreen is re-exported from tui.app for backward compatibility."""
        from pm_core.tui.app import ConnectScreen
        assert ConnectScreen is not None

    def test_welcome_screen_from_app(self):
        """WelcomeScreen is re-exported from tui.app."""
        from pm_core.tui.app import WelcomeScreen
        assert WelcomeScreen is not None

    def test_help_screen_from_app(self):
        """HelpScreen is re-exported from tui.app."""
        from pm_core.tui.app import HelpScreen
        assert HelpScreen is not None

    def test_plan_picker_screen_from_app(self):
        """PlanPickerScreen is re-exported from tui.app."""
        from pm_core.tui.app import PlanPickerScreen
        assert PlanPickerScreen is not None

    def test_plan_add_screen_from_app(self):
        """PlanAddScreen is re-exported from tui.app."""
        from pm_core.tui.app import PlanAddScreen
        assert PlanAddScreen is not None

    def test_tree_scroll_from_app(self):
        """TreeScroll is re-exported from tui.app."""
        from pm_core.tui.app import TreeScroll
        assert TreeScroll is not None

    def test_status_bar_from_app(self):
        """StatusBar is re-exported from tui.app."""
        from pm_core.tui.app import StatusBar
        assert StatusBar is not None

    def test_log_line_from_app(self):
        """LogLine is re-exported from tui.app."""
        from pm_core.tui.app import LogLine
        assert LogLine is not None

    def test_same_class_identity(self):
        """Classes imported from tui.app and tui.screens are the same objects."""
        from pm_core.tui.app import ConnectScreen as CS1
        from pm_core.tui.screens import ConnectScreen as CS2
        assert CS1 is CS2

        from pm_core.tui.app import StatusBar as SB1
        from pm_core.tui.widgets import StatusBar as SB2
        assert SB1 is SB2


# ---------------------------------------------------------------------------
# Shared shell helpers importable from tui._shell
# ---------------------------------------------------------------------------

class TestShellImports:
    def test_run_shell(self):
        from pm_core.tui._shell import _run_shell
        assert callable(_run_shell)

    def test_run_shell_async(self):
        from pm_core.tui._shell import _run_shell_async
        assert callable(_run_shell_async)

    def test_app_reexports_run_shell(self):
        """app.py imports _run_shell from _shell (no duplicate definition)."""
        from pm_core.tui._shell import _run_shell as shell_ver
        from pm_core.tui.app import _run_shell as app_ver
        assert shell_ver is app_ver
