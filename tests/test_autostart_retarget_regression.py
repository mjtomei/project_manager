"""Regression: a second ``O`` must not retarget away from the first PR.

Pre-fix, the TUI kept one ``_auto_start_target``; pressing ``O`` on PR B
after PR A repointed it to B, so when A's implementation went idle the
impl→review transition was filtered out of scope and A stalled in
``in_progress`` (captured under impl/pre-fix).  Uses only entry points that
exist before and after the fix so it fails on pre-fix code for that reason.
"""

import asyncio
from unittest.mock import MagicMock, patch

from pm_core.tui import auto_start
from pm_core.tui import review_loop_ui


class _App:
    def __init__(self, prs, root):
        self._data = {"project": {}, "prs": prs}
        self._root = root
        self._auto_start = False
        self._auto_start_targets = {}
        self._auto_start_all = False
        self._auto_start_run_id = None
        self._stop_before_merge = set()
        self._review_loops = {}
        self._qa_loops = {}
        self._watcher_manager = MagicMock()
        self._watcher_manager.find_by_type.return_value = None

    def log_message(self, *a, **kw):
        pass

    def _update_display(self):
        pass

    def _load_state(self):
        pass

    def run_worker(self, coro, *a, **kw):
        if asyncio.iscoroutine(coro):
            coro.close()


def test_second_O_keeps_first_pr_advancing(tmp_path):
    prs = [{"id": "pr-a", "status": "in_progress", "depends_on": [],
            "workdir": "/w/a"},
           {"id": "pr-b", "status": "in_progress", "depends_on": [],
            "workdir": "/w/b"}]
    app = _App(prs, tmp_path)

    async def no_start(*a, **kw):
        return None

    with patch.object(auto_start, "_start_pr_quiet", no_start), \
         patch("pm_core.tui.watcher_ui.is_running", return_value=False):
        asyncio.run(auto_start.auto_sequence_for_pr(app, "pr-a"))
        asyncio.run(auto_start.auto_sequence_for_pr(app, "pr-b"))

    reviewed = []

    def fake_run_command(_app, cmd, **kw):
        # Status-only transition: the review loop opens iteration 1's
        # window itself, so a windowed `pr review` here would be a
        # throwaway Claude session.
        assert "--no-window" in cmd.split()
        reviewed.append(cmd.split()[-1])

    # Both implementations go idle on the same poll tick.
    with patch("pm_core.tui.pr_view.run_command", fake_run_command), \
         patch("pm_core.tui.review_loop_ui.store.load",
               return_value=app._data), \
         patch.object(review_loop_ui, "_start_loop"):
        review_loop_ui._auto_review_idle_prs(
            app, [("pr-a", prs[0]), ("pr-b", prs[1])])

    assert reviewed == ["pr-a", "pr-b"]
    assert app._stop_before_merge == {"pr-a", "pr-b"}
