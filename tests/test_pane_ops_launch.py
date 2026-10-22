"""pane_ops.launch_pane: a pane whose command finishes before it is focused."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from pm_core.tui import pane_ops


def _launch(select_error, pane_alive):
    app = MagicMock()
    with patch.object(pane_ops, "get_session_and_window",
                      return_value=("s", "@1")), \
         patch.object(pane_ops.pane_registry, "find_live_pane_by_role",
                      return_value=None), \
         patch.object(pane_ops.pane_registry, "load_registry",
                      return_value={}), \
         patch.object(pane_ops.pane_layout, "preferred_split_direction",
                      return_value="h"), \
         patch.object(pane_ops.pane_layout, "register_and_rebalance"), \
         patch.object(pane_ops.tmux_mod, "split_pane", return_value="%9"), \
         patch.object(pane_ops.tmux_mod, "select_pane_smart",
                      side_effect=select_error), \
         patch.object(pane_ops.tmux_mod, "pane_exists",
                      return_value=pane_alive):
        pane_ops.launch_pane(app, "pm pr spec-approve x", "spec-review")
    return [c.args[0] for c in app.log_message.call_args_list]


def test_pane_that_already_exited_is_not_an_error():
    """E.g. the V pane of a losing concurrent approver prints "No pending
    spec review" and exits before launch_pane focuses it."""
    err = subprocess.CalledProcessError(1, ["tmux", "select-pane"])
    with patch.object(pane_ops._log, "exception") as logged:
        logs = _launch(err, pane_alive=False)
    logged.assert_not_called()
    assert not any(m.startswith("Error") for m in logs)


@pytest.mark.parametrize("err,alive", [
    (subprocess.CalledProcessError(1, ["tmux", "select-pane"]), True),
    (RuntimeError("boom"), False)])
def test_other_focus_failures_still_reported(err, alive):
    logs = _launch(err, pane_alive=alive)
    assert any(m.startswith("Error") for m in logs)


def test_focused_pane_logs_launch():
    assert _launch(None, pane_alive=True) == ["Launched spec-review pane"]
