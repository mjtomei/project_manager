"""``zz d`` waits for an in-flight PR launch instead of racing it.

``z d`` opens its fresh review through an async ``pm pr review --fresh``.
A ``zz d`` pressed before that finished started the loop's own launch in
parallel: both reused review-<pr>'s container and crossed their panes into
one window, so the loop's PASS left a second live review in the container
(QA S62).  ``zz d`` now goes through the same busy guard as the other PR
actions.
"""

from unittest.mock import MagicMock, patch

import pytest

from pm_core.tui import review_loop_ui


@pytest.mark.parametrize("inflight", ["Reviewing pr-001 (fresh)", None])
def test_zz_d_respects_inflight_action(inflight):
    app = MagicMock()
    app._inflight_pr_action = inflight
    app._session_name = "pm-sess"
    loop = MagicMock(running=True, stop_requested=False)
    app._review_loops = {"pr-001": loop}
    with patch.object(review_loop_ui, "_get_selected_pr",
                      return_value=("pr-001", {"id": "pr-001"})), \
         patch.object(review_loop_ui, "_start_loop") as start, \
         patch("pm_core.tmux.kill_window") as kill, \
         patch("pm_core.tmux.find_window_by_name", return_value=None), \
         patch("pm_core.tui.auto_start.get_transcript_dir",
               return_value="/tmp/t"):
        review_loop_ui.start_or_stop_loop(app)
    if inflight:
        start.assert_not_called()
        kill.assert_not_called()
        assert loop.stop_requested is False
        app.log_message.assert_any_call(f"Busy: {inflight}", sticky=1.0)
    else:
        start.assert_called_once()
        assert loop.stop_requested is True
