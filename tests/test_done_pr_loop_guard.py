"""Regression test for pr-fc6db6a: plain `d` (done_pr) must not spawn a
duplicate review subprocess when a review loop is already running for the
selected PR.
"""

from unittest.mock import MagicMock, patch


def _make_app(pr_id="pr-001"):
    app = MagicMock()
    tree = MagicMock()
    tree.selected_pr_id = pr_id
    app.query_one.return_value = tree
    app._root = None  # disables the fast-path window check
    app._review_loops = {}
    return app


def test_done_pr_blocks_when_review_loop_running():
    from pm_core.tui import pr_view

    app = _make_app("pr-001")
    app._review_loops["pr-001"] = MagicMock(running=True)

    with patch.object(pr_view, "run_command") as run_cmd, \
         patch.object(pr_view, "guard_pr_action", return_value=True):
        pr_view.done_pr(app)

    run_cmd.assert_not_called()
    assert any(
        "Review loop running" in str(c.args[0])
        for c in app.log_message.call_args_list
    )


def test_done_pr_blocks_even_with_fresh_flag():
    from pm_core.tui import pr_view

    app = _make_app("pr-001")
    app._review_loops["pr-001"] = MagicMock(running=True)

    with patch.object(pr_view, "run_command") as run_cmd, \
         patch.object(pr_view, "guard_pr_action", return_value=True):
        pr_view.done_pr(app, fresh=True)

    run_cmd.assert_not_called()


def test_done_pr_proceeds_when_loop_not_running():
    from pm_core.tui import pr_view

    app = _make_app("pr-001")
    # Stale entry with running=False should not block.
    app._review_loops["pr-001"] = MagicMock(running=False)

    with patch.object(pr_view, "run_command") as run_cmd, \
         patch.object(pr_view, "guard_pr_action", return_value=True):
        pr_view.done_pr(app)

    run_cmd.assert_called_once()


def test_done_pr_proceeds_when_loop_for_different_pr():
    from pm_core.tui import pr_view

    app = _make_app("pr-001")
    app._review_loops["pr-002"] = MagicMock(running=True)

    with patch.object(pr_view, "run_command") as run_cmd, \
         patch.object(pr_view, "guard_pr_action", return_value=True):
        pr_view.done_pr(app)

    run_cmd.assert_called_once()
