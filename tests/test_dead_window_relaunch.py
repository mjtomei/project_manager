"""Starting an impl or review whose window holds only dead panes relaunches.

Stop-on-idle removes a finished session's container and keeps its panes
readable (``remain-on-exit``), so the window stays behind with dead panes.
Plain ``s`` / ``d`` (and ``pm pr start`` / ``pm pr review``) used to switch
to that window, leaving no way back to the session short of ``z s`` (QA S62:
``s`` on an in_review PR whose impl was stopped on idle).
"""

from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from pm_core import store
from pm_core import tmux as tmux_mod
from pm_core.cli import pr as pr_mod
from pm_core.container import ContainerError
from pm_core.tui import pr_view


# ---------------------------------------------------------------------------
# tmux.window_panes_dead
# ---------------------------------------------------------------------------

class TestWindowPanesDead:
    @pytest.mark.parametrize("stdout,expected", [
        ("%1 1\n", True),
        ("%1 1\n%2 1\n", True),
        ("%1 0\n", False),
        ("%1 1\n%2 0\n", False),   # a live companion pane keeps the window
        ("", False),
    ])
    @patch("pm_core.tmux.subprocess.run")
    def test_flags(self, mock_run, stdout, expected):
        mock_run.return_value = MagicMock(returncode=0, stdout=stdout)
        assert tmux_mod.window_panes_dead("sess", "@1") is expected

    @pytest.mark.parametrize("stdout,expected", [
        ("%1 1\n%2 0\n", True),    # only the ignored pane is live
        ("%1 0\n%2 0\n", False),
        ("%2 0\n", False),          # nothing left to judge by
    ])
    @patch("pm_core.tmux.subprocess.run")
    def test_ignored_panes_do_not_count(self, mock_run, stdout, expected):
        mock_run.return_value = MagicMock(returncode=0, stdout=stdout)
        assert tmux_mod.window_panes_dead(
            "sess", "@1", ignore={"%2"}) is expected

    @patch("pm_core.tmux.subprocess.run")
    def test_error_is_not_dead(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert tmux_mod.window_panes_dead("sess", "@1") is False


# ---------------------------------------------------------------------------
# pm pr start / _launch_review_window fast paths
# ---------------------------------------------------------------------------

def _save_project(tmp_path, status="in_review"):
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()
    workdir = tmp_path / "work"
    workdir.mkdir()
    data = {
        "project": {"name": "test", "repo": str(tmp_path),
                    "base_branch": "master"},
        "prs": [{"id": "pr-001", "title": "Test", "branch": "pm/pr-001",
                 "status": status, "workdir": str(workdir)}],
    }
    store.save(data, pm_dir)
    return pm_dir, data


def _mock_tmux(mock_tmux, dead):
    mock_tmux.has_tmux.return_value = True
    mock_tmux.in_tmux.return_value = True
    mock_tmux.session_exists.return_value = True
    mock_tmux.find_window_by_name.return_value = {
        "id": "@1", "index": "1", "name": "pr-001"}
    mock_tmux.window_panes_dead.return_value = dead
    mock_tmux.current_or_base_session.return_value = "pm-sess"


class TestPrStartDeadWindow:
    def _invoke(self, tmp_path, dead, refuse=False):
        pm_dir, data = _save_project(tmp_path)
        git = MagicMock()
        git.is_git_repo.return_value = False
        git.run_git.return_value = MagicMock(returncode=0,
                                             stdout=yaml.safe_dump(data))
        wrap = MagicMock(return_value=("wrapped", "ctr"))
        if refuse:
            wrap.side_effect = ContainerError("Memory governor blocked impl")
        with patch.object(pr_mod, "tmux_mod") as mock_tmux, \
             patch.object(pr_mod, "git_ops", git), \
             patch.object(pr_mod, "prompt_gen"), \
             patch.object(pr_mod, "find_claude", return_value="claude"), \
             patch.object(pr_mod, "build_claude_shell_cmd",
                          return_value="claude ..."), \
             patch.object(pr_mod, "state_root", return_value=pm_dir), \
             patch.object(pr_mod, "_get_pm_session", return_value="pm-sess"), \
             patch("pm_core.container.wrap_claude_cmd", wrap), \
             patch("pm_core.paths.get_global_setting", return_value=False), \
             patch("pm_core.home_window.park_if_on"):
            _mock_tmux(mock_tmux, dead)
            result = CliRunner().invoke(pr_mod.pr, ["start", "pr-001"])
        return result, mock_tmux

    def test_dead_window_is_closed_not_switched_to(self, tmp_path):
        result, mock_tmux = self._invoke(tmp_path, dead=True)
        mock_tmux.kill_window.assert_called_once_with("pm-sess", "@1")
        mock_tmux.select_window.assert_not_called()
        mock_tmux.new_window.assert_called_once()
        assert "Closed window 'pr-001' (its session has ended)" in result.output
        assert "Switched to existing window" not in result.output

    def test_refused_relaunch_keeps_dead_window(self, tmp_path):
        # A governor refusal must leave the stopped session's transcript
        # readable (QA S66): the window is closed only once admitted.
        result, mock_tmux = self._invoke(tmp_path, dead=True, refuse=True)
        assert result.exit_code == 1
        assert "Memory governor blocked impl" in result.output
        mock_tmux.kill_window.assert_not_called()
        mock_tmux.new_window.assert_not_called()
        assert "Closed window" not in result.output

    def test_live_window_is_switched_to(self, tmp_path):
        result, mock_tmux = self._invoke(tmp_path, dead=False)
        mock_tmux.select_window.assert_called_once_with("pm-sess", "@1")
        mock_tmux.kill_window.assert_not_called()


class TestReviewWindowDead:
    def _launch(self, tmp_path, dead, refuse=False):
        _, data = _save_project(tmp_path)
        pr_entry = data["prs"][0]
        wrap = MagicMock(return_value=("wrapped", "ctr"))
        if refuse:
            wrap.side_effect = ContainerError("Memory governor blocked review")
        with patch.object(pr_mod, "tmux_mod") as mock_tmux, \
             patch.object(pr_mod, "_get_pm_session", return_value="pm-sess"), \
             patch.object(pr_mod, "prompt_gen"), \
             patch.object(pr_mod, "build_claude_shell_cmd",
                          return_value="claude ..."), \
             patch("pm_core.container.wrap_claude_cmd", wrap), \
             patch("pm_core.container.is_container_mode_enabled",
                   return_value=False), \
             patch("pm_core.home_window.park_if_on"):
            _mock_tmux(mock_tmux, dead)
            mock_tmux.find_window_by_name.return_value = {
                "id": "@2", "index": "2", "name": "review-pr-001"}
            # Stop once the window would be created.
            mock_tmux.new_window_get_pane.return_value = None
            try:
                pr_mod._launch_review_window(data, pr_entry)
            except SystemExit:
                pass
        return mock_tmux.new_window_get_pane.called, mock_tmux

    def test_dead_review_window_is_closed_and_relaunched(self, tmp_path):
        launched, mock_tmux = self._launch(tmp_path, dead=True)
        assert launched
        mock_tmux.kill_window.assert_called_once_with("pm-sess", "@2")
        mock_tmux.select_window.assert_not_called()

    def test_refused_relaunch_keeps_dead_review_window(self, tmp_path):
        launched, mock_tmux = self._launch(tmp_path, dead=True, refuse=True)
        assert not launched
        mock_tmux.kill_window.assert_not_called()

    def test_live_review_window_is_switched_to(self, tmp_path):
        launched, mock_tmux = self._launch(tmp_path, dead=False)
        assert not launched
        mock_tmux.select_window.assert_called_once_with("pm-sess", "@2")
        mock_tmux.kill_window.assert_not_called()


class TestReviewWindowEnded:
    """The review diff pane is a host shell that outlives the reviewer, so
    it must not keep a stopped review's window alive."""

    @patch("pm_core.tmux.subprocess.run")
    def test_live_diff_shell_is_ignored(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0,
                                          stdout="%5 0\n%6 1\n")
        registry = {"windows": {"@2": {"panes": [
            {"id": "%5", "role": "review-diff"},
            {"id": "%6", "role": "review-claude"}]}}}
        with patch("pm_core.pane_registry.load_registry",
                   return_value=registry):
            assert pr_mod._review_window_ended("pm-sess", "@2") is True

    @patch("pm_core.tmux.subprocess.run")
    def test_live_reviewer_keeps_window(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0,
                                          stdout="%5 0\n%6 0\n")
        registry = {"windows": {"@2": {"panes": [
            {"id": "%5", "role": "review-diff"},
            {"id": "%6", "role": "review-claude"}]}}}
        with patch("pm_core.pane_registry.load_registry",
                   return_value=registry):
            assert pr_mod._review_window_ended("pm-sess", "@2") is False

    @patch("pm_core.tmux.subprocess.run")
    def test_unregistered_window_counts_every_pane(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0,
                                          stdout="%5 0\n%6 1\n")
        with patch("pm_core.pane_registry.load_registry",
                   return_value={"windows": {}}):
            assert pr_mod._review_window_ended("pm-sess", "@2") is False


# ---------------------------------------------------------------------------
# TUI s / d fast paths
# ---------------------------------------------------------------------------

def _app(tmp_path):
    pm_dir, _ = _save_project(tmp_path)
    app = MagicMock()
    app._root = pm_dir
    app._consume_z.return_value = 0
    app.query_one.return_value.selected_pr_id = "pr-001"
    return app


@pytest.mark.parametrize("action,window", [
    (pr_view.start_pr, "pr-001"),
    (pr_view.review_pr, "review-pr-001"),
])
@pytest.mark.parametrize("dead", [True, False])
def test_tui_fast_path_skips_dead_window(tmp_path, action, window, dead):
    app = _app(tmp_path)
    with patch("pm_core.loop_shared.get_pm_session", return_value="pm-sess"), \
         patch("pm_core.tmux.find_window_by_name",
               return_value={"id": "@3", "index": "3", "name": window}), \
         patch("pm_core.tmux.window_panes_dead", return_value=dead), \
         patch("pm_core.tmux.select_window") as select, \
         patch.object(pr_view, "guard_pr_action", return_value=True), \
         patch.object(pr_view, "run_command") as run, \
         patch("pm_core.tui.auto_start.get_transcript_dir", return_value=None):
        action(app)
    if dead:
        select.assert_not_called()
        run.assert_called_once()
    else:
        select.assert_called_once_with("pm-sess", "@3")
        run.assert_not_called()
