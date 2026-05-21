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


def test_active_review_plan_ids_matches_target_and_stem():
    """The badge-source builder matches active plan reviews by target or id.

    Only active ``target-type: plan`` reviews count; archived reviews and
    topic/file reviews are ignored. Matches either by the stored target file
    path or by the review id == the plan-file stem.
    """
    from types import SimpleNamespace
    from pm_core.tui.app import ProjectManagerApp

    stub = SimpleNamespace(_data={
        "reviews": [
            # active plan review, matches p1 by target (and by stem)
            {"id": "plan-1", "target": "plans/plan-1.md",
             "target-type": "plan", "status": "active"},
            # archived → excluded even though it points at p2
            {"id": "plan-2", "target": "plans/plan-2.md",
             "target-type": "plan", "status": "archived"},
            # active but a topic review → excluded
            {"id": "topic-x", "target": "some topic",
             "target-type": "topic", "status": "active"},
            # active plan review matched only by stem (target uses a bare id)
            {"id": "plan-4", "target": "plan-4",
             "target-type": "plan", "status": "active"},
        ],
        "plans": [
            {"id": "p1", "file": "plans/plan-1.md"},
            {"id": "p2", "file": "plans/plan-2.md"},
            {"id": "p3", "file": "plans/plan-3.md"},
            {"id": "p4", "file": "plans/plan-4.md"},
        ],
    })
    assert ProjectManagerApp._active_review_plan_ids(stub) == {"p1", "p4"}
