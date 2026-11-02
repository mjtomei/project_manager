"""QA R3: execution-only runs and recreated windows keep their main pane.

``pm qa run`` (and any run restarted after its qa-<id> window was killed)
has no planner pane, so ``run_qa_sync`` creates the QA window itself.  It
used to be created with ``echo 'QA execution'``: the pane exited at once,
there is no remain-on-exit, so the window vanished before pm could look up
its pane — no status pane, no qa-planner registration, and the window was
gone again by the time the run finished.
"""

import subprocess
import time
from unittest.mock import patch


from pm_core import qa_loop


class TestExecutionOnlyMainPane:
    def test_placeholder_command_outlives_the_lookup(self):
        """The window's command must not exit on its own."""
        proc = subprocess.Popen(
            ["sh", "-c", qa_loop._QA_MAIN_PANE_CMD],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            time.sleep(0.5)
            assert proc.poll() is None, "placeholder pane command exited"
        finally:
            proc.kill()
            proc.wait(timeout=5)

    @patch("pm_core.tmux.new_window_get_pane", return_value="%9")
    @patch("pm_core.tmux.find_window_by_name", return_value=None)
    def test_missing_window_is_created_with_a_live_pane(
            self, mock_find, mock_new):
        pane = qa_loop._ensure_qa_main_pane("pm-test", "qa-pr-001", "/wd")

        assert pane == "%9"
        mock_new.assert_called_once()
        cmd = mock_new.call_args.args[2]
        assert cmd == qa_loop._QA_MAIN_PANE_CMD
        assert "sleep infinity" in cmd
        assert mock_new.call_args.kwargs["switch"] is False

    @patch("pm_core.tmux.new_window_get_pane")
    @patch("pm_core.tmux.get_pane_indices", return_value=[("%7", 0), ("%8", 1)])
    @patch("pm_core.tmux.find_window_by_name",
           return_value={"id": "@5", "index": "3", "name": "qa-pr-001"})
    def test_existing_window_reuses_its_main_pane(
            self, mock_find, mock_panes, mock_new):
        """A recreated/second run must not open a second window."""
        pane = qa_loop._ensure_qa_main_pane("pm-test", "qa-pr-001", "/wd")

        assert pane == "%7"
        mock_new.assert_not_called()

    def test_status_setup_registers_planner_and_status(self):
        """Both panes of the created window land in the registry once."""
        session = "pm-test"
        with patch("pm_core.tmux.split_pane_at", return_value="%10"), \
                patch("pm_core.tmux.pane_window_id", return_value="@5"), \
                patch("pm_core.pane_registry.prune_dead_windows",
                      return_value=[]) as prune, \
                patch("pm_core.pane_registry.load_registry", return_value={}), \
                patch("pm_core.pane_layout.register_and_rebalance") as register:
            qa_loop._add_status_pane(session, "%9", "/qa/status.json")

        prune.assert_called_once_with(session)
        registered = [
            (pane, role)
            for call in register.call_args_list
            for pane, role, _cmd in call.args[2]
        ]
        assert registered == [("%9", "qa-planner"), ("%10", "qa-status")]
