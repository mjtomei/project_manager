"""Regression: plan actions must each get their own per-plan tmux window.

Bug pr-98b2a95: PLANS_WINDOW_NAME was a hardcoded string "plans" so every
plan action collided in one shared window, defeating multi-plan parallelism.
Also verifies the per-plan window opens with the action command as its sole
pane (no leftover bash placeholder).
"""
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from pm_core.tui import pane_ops


def _make_app():
    app = MagicMock()
    app._root = None
    app._data = {"plans": [
        {"id": "plan-AAA", "file": "a.md"},
        {"id": "plan-BBB", "file": "b.md"},
    ]}
    return app


class TmuxFake:
    """Minimal tmux stand-in that records window/pane creation."""

    def __init__(self):
        self.windows: dict = {}        # name -> {id, index, name}
        self.new_window_calls = []     # (name, cmd)
        self.split_calls = []          # (window_id, role, cmd) via launch_pane

    def find(self, session, name):
        return self.windows.get(name)

    def new_window(self, session, name, cmd, cwd, switch=False):
        idx = len(self.windows)
        self.windows[name] = {"id": f"@{name}", "index": str(idx), "name": name}
        self.new_window_calls.append((name, cmd))
        return f"%{name}-pane0"


def _install(stack: ExitStack, fake: TmuxFake):
    """Install patches that drive _launch_in_plans_window through TmuxFake."""
    stack.enter_context(patch.object(pane_ops.tmux_mod, "in_tmux", return_value=True))
    stack.enter_context(patch.object(pane_ops.tmux_mod, "get_session_name", return_value="sess"))
    stack.enter_context(patch.object(pane_ops.tmux_mod, "find_window_by_name", side_effect=fake.find))
    stack.enter_context(patch.object(pane_ops.tmux_mod, "new_window_get_pane", side_effect=fake.new_window))
    stack.enter_context(patch.object(pane_ops.tmux_mod, "select_window"))
    stack.enter_context(patch.object(pane_ops.pane_registry, "load_registry", return_value={"generation": "0"}))
    stack.enter_context(patch.object(pane_ops.pane_layout, "register_and_rebalance"))

    def _launch_pane(app, cmd, role, fresh=False, target_window=None):
        fake.split_calls.append((target_window, role, cmd))
    stack.enter_context(patch.object(pane_ops, "launch_pane", side_effect=_launch_pane))


def test_per_plan_review_actions_use_distinct_windows():
    app = _make_app()
    fake = TmuxFake()
    with ExitStack() as stack:
        _install(stack, fake)
        pane_ops.handle_plan_action(app, "review", "plan-AAA")
        pane_ops.handle_plan_action(app, "review", "plan-BBB")
        pane_ops.handle_plan_action(app, "review", "plan-AAA")  # reuse

    assert sorted(fake.windows.keys()) == ["plan-AAA", "plan-BBB"]
    # First two calls each created a window with the real command — no placeholder.
    assert len(fake.new_window_calls) == 2
    for name, cmd in fake.new_window_calls:
        assert "pm plan review" in cmd, (
            f"window {name} was opened with placeholder '{cmd}', not the action")
    # Third call reused plan-AAA via split.
    assert len(fake.split_calls) == 1
    assert fake.split_calls[0][0] == "@plan-AAA"


def test_different_actions_same_plan_share_one_window():
    """edit/breakdown/review on the same plan all land in one window
    (as separate panes by role) — they're steps of one workflow."""
    import tempfile, pathlib
    app = _make_app()
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "a.md").write_text("# plan")
    app._root = tmp
    app._data = {"plans": [{"id": "plan-AAA", "file": "a.md"}]}

    fake = TmuxFake()
    with ExitStack() as stack:
        _install(stack, fake)
        stack.enter_context(patch.object(pane_ops, "find_editor", return_value="vi"))
        pane_ops.handle_plan_action(app, "edit", "plan-AAA")
        pane_ops.handle_plan_action(app, "breakdown", "plan-AAA")
        pane_ops.handle_plan_action(app, "review", "plan-AAA")

    assert list(fake.windows.keys()) == ["plan-AAA"]
    # First action created the window (so its command was the inaugural one).
    assert len(fake.new_window_calls) == 1
    # Subsequent two actions split into the existing window.
    assert len(fake.split_calls) == 2
    assert all(target == "@plan-AAA" for target, _, _ in fake.split_calls)


def test_deps_action_uses_cross_plan_window():
    app = _make_app()
    fake = TmuxFake()
    with ExitStack() as stack:
        _install(stack, fake)
        pane_ops.handle_plan_action(app, "deps", None)

    # deps is cross-plan; uses synthetic id 'plan-deps' so it's distinct from
    # any real plan but still namespaced in the per-plan window scheme.
    assert list(fake.windows.keys()) == ["plan-deps"]


def test_window_opens_with_action_command_no_placeholder_pane():
    """The new window's first pane must run the action, not 'bash -l'."""
    app = _make_app()
    fake = TmuxFake()
    with ExitStack() as stack:
        _install(stack, fake)
        pane_ops.handle_plan_action(app, "review", "plan-AAA")

    assert len(fake.new_window_calls) == 1
    name, cmd = fake.new_window_calls[0]
    assert name == "plan-AAA"
    assert "pm plan review plan-AAA" in cmd
    assert cmd != "bash -l"
