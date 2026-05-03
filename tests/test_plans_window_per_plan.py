"""Regression: plan actions must each get their own per-plan tmux window.

Bug pr-98b2a95: PLANS_WINDOW_NAME was a hardcoded string "plans" so every
plan action collided in one shared window, defeating multi-plan parallelism.
"""
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


def _patch_tmux(target_windows: dict):
    """Returns context-manager dict of patches that record window creation.

    target_windows is mutated as windows are 'created'.
    """
    def _find(session, name):
        return target_windows.get(name)

    def _new(session, name, cmd, cwd, switch=False):
        target_windows[name] = {"id": f"@{name}", "index": str(len(target_windows)), "name": name}
        return None

    return _find, _new


def test_per_plan_review_actions_use_distinct_windows():
    app = _make_app()
    windows: dict = {}
    find, new = _patch_tmux(windows)
    launches = []

    with patch.object(pane_ops.tmux_mod, "in_tmux", return_value=True), \
         patch.object(pane_ops.tmux_mod, "get_session_name", return_value="sess"), \
         patch.object(pane_ops.tmux_mod, "find_window_by_name", side_effect=find), \
         patch.object(pane_ops.tmux_mod, "new_window_get_pane", side_effect=new), \
         patch.object(pane_ops.tmux_mod, "select_window"), \
         patch.object(pane_ops, "launch_pane",
                      side_effect=lambda app, cmd, role, fresh=False, target_window=None:
                      launches.append((cmd, role, target_window))):
        pane_ops.handle_plan_action(app, "review", "plan-AAA")
        pane_ops.handle_plan_action(app, "review", "plan-BBB")
        pane_ops.handle_plan_action(app, "review", "plan-AAA")  # reuse

    assert "plans-AAA" in windows
    assert "plans-BBB" in windows
    # only two distinct per-plan windows created (third call reuses AAA's)
    plan_windows = [k for k in windows if k.startswith("plans-") and k != "plans-deps"]
    assert sorted(plan_windows) == ["plans-AAA", "plans-BBB"]
    # All three launches targeted some window id
    assert len(launches) == 3
    a1, b, a2 = launches
    assert a1[2] == "@plans-AAA"
    assert b[2] == "@plans-BBB"
    assert a2[2] == "@plans-AAA"


def test_different_actions_same_plan_share_one_window():
    """edit/breakdown/review on the same plan all land in one window
    (as separate panes by role) — they're steps of one workflow."""
    app = _make_app()
    # Make the plan file exist so 'edit' actually launches.
    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "a.md").write_text("# plan")
    app._root = tmp
    app._data = {"plans": [{"id": "plan-AAA", "file": "a.md"}]}

    windows: dict = {}
    find, new = _patch_tmux(windows)
    launches = []

    with patch.object(pane_ops.tmux_mod, "in_tmux", return_value=True), \
         patch.object(pane_ops.tmux_mod, "get_session_name", return_value="sess"), \
         patch.object(pane_ops.tmux_mod, "find_window_by_name", side_effect=find), \
         patch.object(pane_ops.tmux_mod, "new_window_get_pane", side_effect=new), \
         patch.object(pane_ops.tmux_mod, "select_window"), \
         patch.object(pane_ops, "find_editor", return_value="vi"), \
         patch.object(pane_ops, "launch_pane",
                      side_effect=lambda app, cmd, role, fresh=False, target_window=None:
                      launches.append((cmd, role, target_window))):
        pane_ops.handle_plan_action(app, "edit", "plan-AAA")
        pane_ops.handle_plan_action(app, "breakdown", "plan-AAA")
        pane_ops.handle_plan_action(app, "review", "plan-AAA")

    assert list(windows.keys()) == ["plans-AAA"]
    assert all(target == "@plans-AAA" for _, _, target in launches)
    roles = sorted(role for _, role, _ in launches)
    assert roles == ["plan-breakdown", "plan-edit", "plan-review"]


def test_deps_action_uses_cross_plan_window():
    app = _make_app()
    windows: dict = {}
    find, new = _patch_tmux(windows)
    launches = []

    with patch.object(pane_ops.tmux_mod, "in_tmux", return_value=True), \
         patch.object(pane_ops.tmux_mod, "get_session_name", return_value="sess"), \
         patch.object(pane_ops.tmux_mod, "find_window_by_name", side_effect=find), \
         patch.object(pane_ops.tmux_mod, "new_window_get_pane", side_effect=new), \
         patch.object(pane_ops.tmux_mod, "select_window"), \
         patch.object(pane_ops, "launch_pane",
                      side_effect=lambda app, cmd, role, fresh=False, target_window=None:
                      launches.append((cmd, role, target_window))):
        pane_ops.handle_plan_action(app, "deps", None)

    # deps is cross-plan; must not pollute a per-plan window namespace
    assert "plans-deps" in windows
    assert not any(k.startswith("plans-plan-") for k in windows)


def test_none_plan_id_falls_back_to_plain_plans_window():
    """Defensive: any future caller passing plan_id=None still gets a window."""
    app = _make_app()
    windows: dict = {}
    find, new = _patch_tmux(windows)

    with patch.object(pane_ops.tmux_mod, "in_tmux", return_value=True), \
         patch.object(pane_ops.tmux_mod, "get_session_name", return_value="sess"), \
         patch.object(pane_ops.tmux_mod, "find_window_by_name", side_effect=find), \
         patch.object(pane_ops.tmux_mod, "new_window_get_pane", side_effect=new), \
         patch.object(pane_ops.tmux_mod, "select_window"), \
         patch.object(pane_ops, "launch_pane"):
        win_id = pane_ops._ensure_plans_window(app, None)

    assert "plans" in windows
    assert win_id == "@plans"
