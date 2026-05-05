"""Tests for the find-or-create-window helper used by CLI commands."""

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from pm_core.cli._window_launch import launch_claude_in_window


def _setup(stack: ExitStack, *, pm_session: str | None = "pm-test",
           existing_win=None, session_exists: bool = True):
    """Patch dependencies and return a dict of mocks."""
    mocks = {
        "_get_pm_session": stack.enter_context(patch(
            "pm_core.cli._window_launch._get_pm_session",
            return_value=pm_session)),
        "load_session": stack.enter_context(patch(
            "pm_core.cli._window_launch.load_session", return_value=None)),
        "save_session": stack.enter_context(patch(
            "pm_core.cli._window_launch.save_session")),
        "clear_session": stack.enter_context(patch(
            "pm_core.cli._window_launch.clear_session")),
        "build_cmd": stack.enter_context(patch(
            "pm_core.cli._window_launch.build_claude_shell_cmd",
            return_value="claude --session-id xx 'p'")),
        "launch_claude": stack.enter_context(patch(
            "pm_core.cli._window_launch.launch_claude")),
        "session_exists": stack.enter_context(patch(
            "pm_core.tmux.session_exists", return_value=session_exists)),
        "find_window": stack.enter_context(patch(
            "pm_core.tmux.find_window_by_name", return_value=existing_win)),
        "kill_window": stack.enter_context(patch("pm_core.tmux.kill_window")),
        "new_window": stack.enter_context(patch("pm_core.tmux.new_window")),
        "select_window": stack.enter_context(patch(
            "pm_core.tmux.select_window")),
        "set_size": stack.enter_context(patch(
            "pm_core.tmux.set_shared_window_size")),
    }
    return mocks


def test_switches_to_existing_window():
    existing = {"id": "@7", "index": 2, "name": "plan-deps"}
    with ExitStack() as stack:
        m = _setup(stack, existing_win=existing)
        launch_claude_in_window(
            "plan-deps", "prompt", cwd="/repo",
            session_key="plan:deps", pm_root=Path("/fake"),
        )
        m["select_window"].assert_called_once_with("pm-test", "@7")
        m["new_window"].assert_not_called()
        m["launch_claude"].assert_not_called()


def test_kills_existing_window_when_fresh():
    existing = {"id": "@7", "index": 2, "name": "plan-deps"}
    with ExitStack() as stack:
        m = _setup(stack, existing_win=existing)
        launch_claude_in_window(
            "plan-deps", "prompt", cwd="/repo",
            session_key="plan:deps", pm_root=Path("/fake"), fresh=True,
        )
        m["kill_window"].assert_called_once_with("pm-test", "@7")
        m["new_window"].assert_called_once()
        assert m["new_window"].call_args[0][1] == "plan-deps"


def test_creates_new_window_when_missing():
    with ExitStack() as stack:
        m = _setup(stack, existing_win=None)
        launch_claude_in_window(
            "plan-deps", "prompt", cwd="/repo",
            session_key="plan:deps", pm_root=Path("/fake"),
        )
        m["new_window"].assert_called_once()
        args = m["new_window"].call_args[0]
        assert args[0] == "pm-test"
        assert args[1] == "plan-deps"
        assert args[3] == "/repo"
        m["launch_claude"].assert_not_called()


def test_falls_back_inline_when_not_in_pm_session():
    with ExitStack() as stack:
        m = _setup(stack, pm_session=None)
        launch_claude_in_window(
            "plan-deps", "prompt", cwd="/repo",
            session_key="plan:deps", pm_root=Path("/fake"),
        )
        m["launch_claude"].assert_called_once()
        assert m["launch_claude"].call_args[1]["session_key"] == "plan:deps"
        m["new_window"].assert_not_called()
        m["select_window"].assert_not_called()


def test_falls_back_inline_when_session_missing():
    with ExitStack() as stack:
        m = _setup(stack, pm_session="pm-test", session_exists=False)
        launch_claude_in_window(
            "plan-deps", "prompt", cwd="/repo",
            session_key="plan:deps", pm_root=Path("/fake"),
        )
        m["launch_claude"].assert_called_once()


def test_fresh_clears_session_on_inline_fallback():
    with ExitStack() as stack:
        m = _setup(stack, pm_session=None)
        launch_claude_in_window(
            "plan-deps", "prompt", cwd="/repo",
            session_key="plan:deps", pm_root=Path("/fake"), fresh=True,
        )
        m["clear_session"].assert_called_once_with(Path("/fake"), "plan:deps")
        m["launch_claude"].assert_called_once()
        assert m["launch_claude"].call_args[1]["resume"] is False


def test_new_window_failure_falls_back_inline():
    with ExitStack() as stack:
        m = _setup(stack, existing_win=None)
        m["new_window"].side_effect = RuntimeError("boom")
        launch_claude_in_window(
            "plan-deps", "prompt", cwd="/repo",
            session_key="plan:deps", pm_root=Path("/fake"),
        )
        m["launch_claude"].assert_called_once()
