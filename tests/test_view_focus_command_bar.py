"""Background reloads must not pull focus out of the command bar.

QA repro (pr-0b87a97 s7): while auto-start was launching windows, auto-review's
sync ``pr review`` ran ``_load_state`` → ``_show_normal_view`` → tree.focus()
between the user's ``/`` and their typing, so "autostart add X" went to the
tree as hotkeys (``t`` started QA on the selected PR) and was never submitted.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from pm_core.tui.app import ProjectManagerApp


def _stub_app(cmd_bar_focused=False, pending=False):
    cmd_bar = SimpleNamespace(has_focus=cmd_bar_focused)
    return SimpleNamespace(
        _command_pending=pending,
        query_one=lambda *a, **k: cmd_bar,
    )


def test_focuses_view_when_command_bar_idle():
    widget = MagicMock()
    ProjectManagerApp._focus_view_widget(_stub_app(), widget)
    widget.focus.assert_called_once()


def test_keeps_command_bar_focus_while_typing():
    widget = MagicMock()
    ProjectManagerApp._focus_view_widget(_stub_app(cmd_bar_focused=True), widget)
    widget.focus.assert_not_called()


def test_keeps_pending_slash_between_keypress_and_focus():
    widget = MagicMock()
    ProjectManagerApp._focus_view_widget(_stub_app(pending=True), widget)
    widget.focus.assert_not_called()
