"""TUI command bar: shared history recall and Tab completion."""

from __future__ import annotations

import asyncio

import pytest

from pm_core import command_history as ch

TAG = "demo-c5a1006b"

PROJECT_YAML = """\
project: {name: demo, repo: /tmp/demo, base_branch: master, backend: local}
plans:
- {id: plan-001, name: Alpha, status: active}
prs:
- {id: pr-0000001, title: one, branch: b1, status: in_progress, gh_pr_number: 193}
- {id: pr-0000002, title: two, branch: b2, status: pending, gh_pr_number: 195}
- {id: pr-abc1234, title: three, branch: b3, status: pending}
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "pm"
    root.mkdir()
    (root / "project.yaml").write_text(PROJECT_YAML)
    return root


def _host(root, session_name=f"pm-{TAG}"):
    from textual.app import App
    from pm_core.tui.command_bar import CommandBar, CommandSubmitted
    from pm_core.tui.tech_tree import TechTree

    class Host(App):
        _command_pending = False
        _command_buffer: list = []
        _session_name = session_name
        _root = root

        def __init__(self):
            super().__init__()
            self.submitted: list[str] = []
            self.logged: list[str] = []

        def compose(self):
            yield TechTree(id="tech-tree")
            yield CommandBar(id="command-bar")

        def on_command_submitted(self, message: CommandSubmitted) -> None:
            self.submitted.append(message.command)

        def log_message(self, msg, **kwargs):
            self.logged.append(msg)

    return Host()


def _run(root, script, session_name=f"pm-{TAG}"):
    """Run ``script(app, bar, pilot)`` against a focused command bar."""
    async def body():
        from pm_core.tui.command_bar import CommandBar
        app = _host(root, session_name)
        async with app.run_test(size=(100, 12)) as pilot:
            bar = app.query_one("#command-bar", CommandBar)
            bar.focus()
            await pilot.pause()
            return await script(app, bar, pilot)
    return asyncio.run(body())


def test_submit_appends_to_shared_history(env):
    async def script(app, bar, pilot):
        await pilot.press(*"pr list", "enter")
        await pilot.pause()
        return app.submitted
    assert _run(env, script) == ["pr list"]
    assert ch.read_history(TAG) == ["pr list"]


def test_up_down_walk_history_and_restore_draft(env):
    ch.append_history("pr list", TAG)
    ch.append_history("plan list", TAG)

    async def script(app, bar, pilot):
        seen = []
        await pilot.press(*"pr sh")
        for key in ("up", "up", "up", "down", "down"):
            await pilot.press(key)
            seen.append((bar.value, bar.cursor_position))
        return seen, app.focused is bar
    seen, focused = _run(env, script)
    assert [v for v, _ in seen] == ["plan list", "pr list", "pr list", "plan list", "pr sh"]
    assert all(c == len(v) for v, c in seen)  # cursor at end of the line
    assert focused


def test_recall_sees_commands_written_by_the_popup_after_focus(env):
    async def script(app, bar, pilot):
        ch.append_history("pr show pr-abc1234", TAG)  # the popup just ran this
        await pilot.press("up")
        return bar.value
    assert _run(env, script) == "pr show pr-abc1234"


def test_history_is_per_session(env):
    ch.append_history("other session cmd", "other-11111111")

    async def script(app, bar, pilot):
        await pilot.press("up")
        return bar.value
    assert _run(env, script) == ""


def test_without_pm_session_history_stays_in_memory(env, tmp_path):
    async def script(app, bar, pilot):
        await pilot.press(*"pr list", "enter")
        await pilot.pause()
        bar.focus()
        await pilot.press("up")
        return bar.value
    assert _run(env, script, session_name=None) == "pr list"
    assert not list((tmp_path / "home").rglob("command_history"))


def test_tab_completes_unique_pr_id(env):
    async def script(app, bar, pilot):
        await pilot.press(*"pr show pr-a", "tab")
        return bar.value, app.focused is bar
    value, focused = _run(env, script)
    assert value == "pr show pr-abc1234 "
    assert focused  # Tab did not move focus out of the bar


def test_tab_lists_then_cycles(env):
    async def script(app, bar, pilot):
        await pilot.press(*"pr edit #19", "tab")
        first = bar.value
        await pilot.press("tab")
        second = bar.value
        await pilot.press("tab")
        third = bar.value
        await pilot.press("shift+tab")
        back = bar.value
        return first, second, third, back, list(app.logged)
    first, second, third, back, logged = _run(env, script)
    assert first == "pr edit #19"
    assert (second, third, back) == ("pr edit #193", "pr edit #195", "pr edit #193")
    assert logged and "#193" in logged[-1] and "#195" in logged[-1]


def test_tab_completes_mid_line_and_subcommands(env):
    async def script(app, bar, pilot):
        await pilot.press(*"pr sta")
        await pilot.press("tab")
        sub = bar.value
        bar.value = "plan review  --help"
        bar.cursor_position = len("plan review ")
        await pilot.press("tab")
        return sub, bar.value, bar.cursor_position
    sub, value, cursor = _run(env, script)
    assert sub == "pr start "
    assert value == "plan review plan-001  --help"
    assert cursor == len("plan review plan-001 ")


def test_tab_without_matches_keeps_text(env):
    async def script(app, bar, pilot):
        await pilot.press(*"bogus ", "tab")
        return bar.value
    assert _run(env, script) == "bogus "
