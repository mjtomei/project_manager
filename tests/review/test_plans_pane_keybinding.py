from unittest.mock import patch, MagicMock

from pm_core.tui.plans_pane import PlansPane
from pm_core.tui import pane_ops


def test_r_key_maps_to_literature_review():
    assert PlansPane._KEY_ACTIONS.get("r") == "literature-review"


def test_handle_plan_action_dispatches_literature_review():
    app = MagicMock()
    with patch.object(pane_ops, "_launch_in_plans_window") as launch:
        pane_ops.handle_plan_action(app, "literature-review", "plan-1")
    launch.assert_called_once()
    args = launch.call_args.args
    # _launch_in_plans_window(app, plan_id, cmd, role)
    assert args[1] == "plan-1"
    assert args[2] == "pm plan literature-review plan-1"
    assert args[3] == "literature-review"


def test_handle_plan_action_no_plan_does_nothing():
    app = MagicMock()
    with patch.object(pane_ops, "_launch_in_plans_window") as launch:
        pane_ops.handle_plan_action(app, "literature-review", None)
    launch.assert_not_called()


def test_active_review_badge_renders():
    pane = PlansPane()
    pane._plans = [
        {"id": "plan-1", "name": "One", "status": "draft", "pr_count": 0,
         "intro": "", "active_review": True},
    ]
    # render() returns a rich Text; its plain string should carry the badge
    out = pane.render()
    assert "review" in out.plain
