"""Regression test for pr-177dec0: select_pr must trigger scroll-into-view
robustly, including when called programmatically (e.g. from the command bar)
where focus changes can clobber the deferred scroll_to_region call."""

from unittest.mock import MagicMock, patch

from pm_core.tui.tech_tree import TechTree


def _make_tree_with_prs(n: int = 50) -> TechTree:
    prs = [
        {"id": f"pr-{i:03d}", "title": f"PR {i}", "status": "pending",
         "deps": [], "plan": None}
        for i in range(n)
    ]
    tree = TechTree(prs=prs)
    # Bypass on_mount so we don't need a running app
    tree._prs = prs
    tree._recompute()
    return tree


def test_select_pr_schedules_scroll_via_call_after_refresh():
    """select_pr should defer scroll via call_after_refresh."""
    tree = _make_tree_with_prs()
    target_id = "pr-040"

    with patch.object(tree, "call_after_refresh") as car, \
         patch.object(tree, "set_timer") as st, \
         patch.object(tree, "refresh"):
        tree.select_pr(target_id)

    # Both the immediate after-refresh hook and a small fallback timer
    # should be scheduled for _scroll_selected_into_view.
    car.assert_any_call(tree._scroll_selected_into_view)
    # Fallback timer protects against focus-induced scroll clobber when
    # called from the command bar — see pr-177dec0.
    st.assert_any_call(0.05, tree._scroll_selected_into_view)


def test_select_pr_updates_selected_index():
    tree = _make_tree_with_prs()
    target_id = "pr-040"
    target_idx = tree._ordered_ids.index(target_id)
    assert tree.selected_index != target_idx  # precondition

    with patch.object(tree, "call_after_refresh"), \
         patch.object(tree, "set_timer"), \
         patch.object(tree, "refresh"):
        tree.select_pr(target_id)

    assert tree.selected_index == target_idx


def test_select_pr_unknown_id_is_noop():
    tree = _make_tree_with_prs()
    with patch.object(tree, "call_after_refresh") as car, \
         patch.object(tree, "set_timer") as st, \
         patch.object(tree, "refresh"):
        tree.select_pr("pr-does-not-exist")

    car.assert_not_called()
    st.assert_not_called()
