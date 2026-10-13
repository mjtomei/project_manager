"""Background reloads must not pull focus out of the command bar.

QA repro (pr-0b87a97 s7): while auto-start was launching windows, auto-review's
sync ``pr review`` ran ``_load_state`` → ``_show_normal_view`` → tree.focus()
between the user's ``/`` and their typing, so "autostart add X" went to the
tree as hotkeys (``t`` started QA on the selected PR) and was never submitted.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pm_core.tui.app import ProjectManagerApp


def _stub_app(cmd_bar_focused=False, pending=False):
    cmd_bar = SimpleNamespace(has_focus=cmd_bar_focused)
    app = SimpleNamespace(
        _command_pending=pending,
        query_one=lambda *a, **k: cmd_bar,
    )
    app._command_bar_in_use = (
        lambda: ProjectManagerApp._command_bar_in_use(app))
    return app


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


def _queue_host(tmp_path):
    """Minimal app with the real command bar, tree and queue drain."""
    from textual.app import App
    from pm_core.tui.command_bar import CommandBar
    from pm_core.tui.tech_tree import TechTree

    queue = tmp_path / "tui-pm-test.cmd-queue"

    class Host(App):
        _command_pending = False
        _cmd_queue_ready = True
        _plans_visible = False
        _drain_command_queue = ProjectManagerApp._drain_command_queue
        _command_bar_in_use = ProjectManagerApp._command_bar_in_use

        def compose(self):
            yield TechTree(id="tech-tree")
            yield CommandBar(id="command-bar")

        def _command_queue_file(self):
            return queue

    return Host(), queue


def _drain_while(tmp_path, *, typing: bool):
    async def body():
        app, queue = _queue_host(tmp_path)
        async with app.run_test(size=(80, 20)) as pilot:
            from pm_core.tui.command_bar import CommandBar
            from pm_core.tui.tech_tree import TechTree
            cmd_bar = app.query_one("#command-bar", CommandBar)
            tree = app.query_one("#tech-tree", TechTree)
            (cmd_bar if typing else tree).focus()
            await pilot.pause()
            queue.write_text("autostart status --reply r1\n")
            with patch("pm_core.tui.auto_start.handle_command"):
                app._drain_command_queue()
            await pilot.pause()
            return app.focused
    return asyncio.run(body())


def test_cli_command_from_queue_keeps_command_bar_focus(tmp_path):
    """A ``pm autostart`` call (SIGUSR2 queue) arriving while the user is
    typing must not move focus to the tree — the autostart branch focuses
    the tree for commands typed in the bar itself."""
    from pm_core.tui.command_bar import CommandBar
    assert isinstance(_drain_while(tmp_path, typing=True), CommandBar)


def test_cli_command_from_queue_leaves_tree_focus(tmp_path):
    from pm_core.tui.tech_tree import TechTree
    assert isinstance(_drain_while(tmp_path, typing=False), TechTree)


def test_cli_command_from_queue_keeps_half_typed_text(tmp_path):
    """QA repro (pr-0b87a97 s12): the refocus after a queued ``pm autostart
    status`` went through Input's select-on-focus, selecting the whole
    half-typed command, so the next keystroke replaced it and the bar
    submitted only the suffix ("No such command '33987'")."""
    async def body():
        app, queue = _queue_host(tmp_path)
        async with app.run_test(size=(80, 20)) as pilot:
            from pm_core.tui.command_bar import CommandBar
            cmd_bar = app.query_one("#command-bar", CommandBar)
            cmd_bar.focus()
            await pilot.pause()
            await pilot.press(*"add pr-75")
            queue.write_text("autostart status --reply r1\n")
            with patch("pm_core.tui.auto_start.handle_command"):
                app._drain_command_queue()
            await pilot.pause()
            await pilot.press(*"33")
            await pilot.pause()
            return cmd_bar.value
    assert asyncio.run(body()) == "add pr-7533"


def test_unfocused_hint_advertises_runs_popup():
    """QA s31 (pr-0b87a97): R18 promises a visible "Runs" hint for ``a``
    but the TUI has no Footer widget; the unfocused command-bar hint is the
    bottom row, so it carries it.  Focusing the bar still shows the typing
    placeholder, and blurring restores the hint."""
    async def body():
        from textual.app import App
        from pm_core.tui.command_bar import CommandBar
        from pm_core.tui.tech_tree import TechTree

        class Host(App):
            _command_pending = False
            _command_buffer: list = []

            def compose(self):
                yield TechTree(id="tech-tree")
                yield CommandBar(id="command-bar")

        app = Host()
        async with app.run_test(size=(80, 12)) as pilot:
            cmd_bar = app.query_one("#command-bar", CommandBar)
            app.query_one("#tech-tree", TechTree).focus()
            await pilot.pause()
            seen = [cmd_bar.placeholder]
            cmd_bar.focus()
            await pilot.pause()
            seen.append(cmd_bar.placeholder)
            app.query_one("#tech-tree", TechTree).focus()
            await pilot.pause()
            seen.append(cmd_bar.placeholder)
            return seen
    unfocused, focused, again = asyncio.run(body())
    assert "a Runs" in unfocused and "press / to type a command" in unfocused
    assert focused == "Type command (e.g. pr start pr-001)..."
    assert again == unfocused
