"""Tests for companion workdir pane feature.

Tests the companion pane functionality for implementation and merge windows,
including CLI flags, global settings, and TUI z-prefix behaviour.
"""

from unittest import mock
from unittest.mock import MagicMock, patch, call

import pytest

from pm_core.cli import pr as pr_mod


# ---------------------------------------------------------------------------
# _add_companion_pane helper
# ---------------------------------------------------------------------------

class TestAddCompanionPane:
    def test_skips_if_already_has_two_panes(self):
        """If the window already has 2+ panes, _add_companion_pane is a no-op."""
        with patch.object(pr_mod, "tmux_mod") as mock_tmux, \
             patch.object(pr_mod, "pane_registry"), \
             patch.object(pr_mod, "pane_layout"):
            mock_tmux.get_pane_indices.return_value = [
                ("%1", 0), ("%2", 1),
            ]
            pr_mod._add_companion_pane("sess", {"id": "@1", "index": "1"},
                                        "/work/dir", "impl")
            mock_tmux.split_pane_at.assert_not_called()

    def test_skips_if_no_panes(self):
        """If the window has no panes, _add_companion_pane is a no-op."""
        with patch.object(pr_mod, "tmux_mod") as mock_tmux, \
             patch.object(pr_mod, "pane_registry"), \
             patch.object(pr_mod, "pane_layout"):
            mock_tmux.get_pane_indices.return_value = []
            pr_mod._add_companion_pane("sess", {"id": "@1", "index": "1"},
                                        "/work/dir", "impl")
            mock_tmux.split_pane_at.assert_not_called()

    def test_splits_and_registers_panes(self):
        """Splits the claude pane horizontally and registers both panes."""
        with patch.object(pr_mod, "tmux_mod") as mock_tmux, \
             patch.object(pr_mod, "pane_registry") as mock_reg, \
             patch.object(pr_mod, "pane_layout") as mock_layout:
            mock_tmux.get_pane_indices.return_value = [("%1", 0)]
            mock_tmux.split_pane_at.return_value = "%2"
            mock_reg.load_registry.return_value = {}
            mock_reg.get_window_data.return_value = {"user_modified": True}

            pr_mod._add_companion_pane("sess", {"id": "@1", "index": "1"},
                                        "/work/dir", "impl")

            mock_tmux.split_pane_at.assert_called_once_with(
                "%1", "h", mock.ANY, background=True,
            )
            # Both panes registered
            assert mock_reg.register_pane.call_count == 2
            roles = [c[0][3] for c in mock_reg.register_pane.call_args_list]
            assert "impl-claude" in roles
            assert "impl-companion" in roles

            # user_modified reset and layout rebalanced
            mock_reg.save_registry.assert_called_once()
            mock_layout.rebalance.assert_called_once_with("sess", "@1")


# ---------------------------------------------------------------------------
# pr start --companion CLI
# ---------------------------------------------------------------------------

class TestPrStartCompanion:
    @patch.object(pr_mod, "tmux_mod")
    @patch.object(pr_mod, "pane_registry")
    @patch.object(pr_mod, "pane_layout")
    @patch.object(pr_mod, "prompt_gen")
    @patch.object(pr_mod, "find_claude", return_value="/usr/bin/claude")
    @patch.object(pr_mod, "build_claude_shell_cmd", return_value="claude ...")
    def test_companion_flag_adds_pane_to_existing_window(
        self, _cmd, _claude, _prompt, _layout, _reg, mock_tmux,
        tmp_path,
    ):
        """With --companion and an existing window, a companion pane is added."""
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        workdir = tmp_path / "work"
        workdir.mkdir()

        from pm_core import store
        data = {
            "project": {"name": "test", "repo": str(tmp_path), "base_branch": "master"},
            "prs": [{"id": "pr-001", "title": "Test", "branch": "pm/pr-001",
                      "status": "in_progress", "workdir": str(workdir)}],
        }
        store.save(data, pm_dir)

        mock_tmux.has_tmux.return_value = True
        mock_tmux.in_tmux.return_value = True
        mock_tmux.session_exists.return_value = True
        mock_tmux.find_window_by_name.return_value = {"id": "@1", "index": "1", "name": "pr-001"}
        mock_tmux.get_pane_indices.return_value = [("%1", 0)]  # single pane
        mock_tmux.split_pane_at.return_value = "%2"
        _reg.load_registry.return_value = {}
        _reg.get_window_data.return_value = {"user_modified": True}

        from click.testing import CliRunner
        runner = CliRunner()
        with patch.object(pr_mod, "state_root", return_value=pm_dir), \
             patch.object(pr_mod, "_get_pm_session", return_value="pm-sess"):
            result = runner.invoke(pr_mod.pr, ["start", "--companion", "pr-001"])

        assert result.exit_code == 0
        mock_tmux.split_pane_at.assert_called_once()
        mock_tmux.select_window.assert_called()

    @patch.object(pr_mod, "tmux_mod")
    @patch.object(pr_mod, "pane_registry")
    @patch.object(pr_mod, "pane_layout")
    @patch.object(pr_mod, "prompt_gen")
    @patch.object(pr_mod, "find_claude", return_value="/usr/bin/claude")
    @patch.object(pr_mod, "build_claude_shell_cmd", return_value="claude ...")
    def test_global_setting_enables_companion(
        self, _cmd, _claude, _prompt, _layout, _reg, mock_tmux,
        tmp_path,
    ):
        """The companion-pane global setting should enable companion by default."""
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        workdir = tmp_path / "work"
        workdir.mkdir()

        from pm_core import store
        data = {
            "project": {"name": "test", "repo": str(tmp_path), "base_branch": "master"},
            "prs": [{"id": "pr-001", "title": "Test", "branch": "pm/pr-001",
                      "status": "in_progress", "workdir": str(workdir)}],
        }
        store.save(data, pm_dir)

        mock_tmux.has_tmux.return_value = True
        mock_tmux.in_tmux.return_value = True
        mock_tmux.session_exists.return_value = True
        mock_tmux.find_window_by_name.return_value = {"id": "@1", "index": "1", "name": "pr-001"}
        mock_tmux.get_pane_indices.return_value = [("%1", 0)]
        mock_tmux.split_pane_at.return_value = "%2"
        _reg.load_registry.return_value = {}
        _reg.get_window_data.return_value = {"user_modified": True}

        from click.testing import CliRunner
        runner = CliRunner()
        with patch.object(pr_mod, "state_root", return_value=pm_dir), \
             patch.object(pr_mod, "_get_pm_session", return_value="pm-sess"), \
             patch("pm_core.paths.get_global_setting", return_value=True):
            result = runner.invoke(pr_mod.pr, ["start", "pr-001"])

        # Even without --companion flag, the global setting triggers companion
        assert result.exit_code == 0
        mock_tmux.split_pane_at.assert_called_once()


# ---------------------------------------------------------------------------
# _launch_merge_window companion
# ---------------------------------------------------------------------------

class TestMergeWindowCompanion:
    @patch.object(pr_mod, "tmux_mod")
    @patch.object(pr_mod, "pane_registry")
    @patch.object(pr_mod, "pane_layout")
    @patch.object(pr_mod, "prompt_gen")
    @patch.object(pr_mod, "build_claude_shell_cmd", return_value="claude ...")
    def test_companion_splits_pane(
        self, _cmd, _prompt, _layout, _reg, mock_tmux,
    ):
        """_launch_merge_window with companion=True uses new_window_get_pane and splits."""
        mock_tmux.has_tmux.return_value = True
        mock_tmux.in_tmux.return_value = True
        mock_tmux.session_exists.return_value = True
        mock_tmux.find_window_by_name.side_effect = [
            None,  # first check: no existing
            {"id": "@2", "index": "2", "name": "merge-pr-001"},  # after creation
        ]
        mock_tmux.new_window_get_pane.return_value = "%1"
        mock_tmux.get_pane_indices.return_value = [("%1", 0)]
        mock_tmux.split_pane_at.return_value = "%2"
        _reg.load_registry.return_value = {}
        _reg.get_window_data.return_value = {"user_modified": True}

        data = {"project": {"base_branch": "master"}}
        pr_entry = {"id": "pr-001", "workdir": "/work/dir"}

        with patch.object(pr_mod, "_get_pm_session", return_value="pm-sess"), \
             patch("pm_core.paths.get_global_setting", return_value=False):
            pr_mod._launch_merge_window(data, pr_entry, "conflict error",
                                         companion=True)

        mock_tmux.new_window_get_pane.assert_called_once()
        mock_tmux.split_pane_at.assert_called_once()

    @patch.object(pr_mod, "tmux_mod")
    @patch.object(pr_mod, "prompt_gen")
    @patch.object(pr_mod, "build_claude_shell_cmd", return_value="claude ...")
    def test_no_companion_uses_new_window(
        self, _cmd, _prompt, mock_tmux,
    ):
        """_launch_merge_window without companion uses simple new_window."""
        mock_tmux.has_tmux.return_value = True
        mock_tmux.in_tmux.return_value = True
        mock_tmux.session_exists.return_value = True
        mock_tmux.find_window_by_name.return_value = None

        data = {"project": {"base_branch": "master"}}
        pr_entry = {"id": "pr-001", "workdir": "/work/dir"}

        with patch.object(pr_mod, "_get_pm_session", return_value="pm-sess"), \
             patch("pm_core.paths.get_global_setting", return_value=False):
            pr_mod._launch_merge_window(data, pr_entry, "conflict error")

        mock_tmux.new_window.assert_called_once()
        mock_tmux.new_window_get_pane.assert_not_called()


# ---------------------------------------------------------------------------
# TUI z-prefix for start_pr
# ---------------------------------------------------------------------------

class TestTuiStartPrZPrefix:
    """Test that z-prefix is correctly mapped to companion/fresh flags."""

    def _make_app(self, z_count=0):
        """Create a mock app with z-prefix state."""
        app = MagicMock()
        app._z_count = z_count
        app._consume_z = MagicMock(return_value=z_count)
        app._data = {
            "prs": [{"id": "pr-001", "title": "Test", "status": "pending"}],
        }
        app._root = None
        app._inflight_pr_action = None
        return app

    def _make_tree(self, pr_id="pr-001"):
        tree = MagicMock()
        tree.selected_pr_id = pr_id
        return tree

    @patch("pm_core.tui.pr_view.run_command")
    @patch("pm_core.tui.pr_view.guard_pr_action", return_value=True)
    @patch("pm_core.paths.get_global_setting", return_value=False)
    def test_no_z_no_companion(self, _setting, _guard, mock_run):
        """z=0: normal start, no --companion, no --fresh."""
        from pm_core.tui import pr_view
        app = self._make_app(z_count=0)
        app.query_one.return_value = self._make_tree()

        pr_view.start_pr(app)

        cmd = mock_run.call_args[0][1]
        assert "--companion" not in cmd
        assert "--fresh" not in cmd
        assert "pr-001" in cmd

    @patch("pm_core.tui.pr_view.run_command")
    @patch("pm_core.tui.pr_view.guard_pr_action", return_value=True)
    @patch("pm_core.paths.get_global_setting", return_value=False)
    def test_z1_companion_only(self, _setting, _guard, mock_run):
        """z=1: companion pane, not fresh."""
        from pm_core.tui import pr_view
        app = self._make_app(z_count=1)
        app.query_one.return_value = self._make_tree()

        pr_view.start_pr(app)

        cmd = mock_run.call_args[0][1]
        assert "--companion" in cmd
        assert "--fresh" not in cmd

    @patch("pm_core.tui.pr_view.run_command")
    @patch("pm_core.tui.pr_view.guard_pr_action", return_value=True)
    @patch("pm_core.paths.get_global_setting", return_value=False)
    def test_zz_fresh_no_companion(self, _setting, _guard, mock_run):
        """z=2 (zz): fresh start, no companion."""
        from pm_core.tui import pr_view
        app = self._make_app(z_count=2)
        app.query_one.return_value = self._make_tree()

        pr_view.start_pr(app)

        cmd = mock_run.call_args[0][1]
        assert "--fresh" in cmd
        assert "--companion" not in cmd

    @patch("pm_core.tui.pr_view.run_command")
    @patch("pm_core.tui.pr_view.guard_pr_action", return_value=True)
    @patch("pm_core.paths.get_global_setting", return_value=False)
    def test_zzz_fresh_and_companion(self, _setting, _guard, mock_run):
        """z=3 (zzz): fresh start with companion."""
        from pm_core.tui import pr_view
        app = self._make_app(z_count=3)
        app.query_one.return_value = self._make_tree()

        pr_view.start_pr(app)

        cmd = mock_run.call_args[0][1]
        assert "--fresh" in cmd
        assert "--companion" in cmd


# ---------------------------------------------------------------------------
# TUI z-prefix for merge_pr
# ---------------------------------------------------------------------------

class TestTuiMergePrZPrefix:
    """Test that z-prefix enables companion flag for merge."""

    def _make_app(self, z_count=0):
        app = MagicMock()
        app._consume_z = MagicMock(return_value=z_count)
        app._inflight_pr_action = None
        return app

    def _make_tree(self, pr_id="pr-001"):
        tree = MagicMock()
        tree.selected_pr_id = pr_id
        return tree

    @patch("pm_core.tui.pr_view.run_command")
    @patch("pm_core.tui.pr_view.guard_pr_action", return_value=True)
    def test_no_z_no_companion(self, _guard, mock_run):
        """z=0: normal merge, no --companion."""
        from pm_core.tui import pr_view
        app = self._make_app(z_count=0)
        app.query_one.return_value = self._make_tree()

        pr_view.merge_pr(app)

        cmd = mock_run.call_args[0][1]
        assert "--companion" not in cmd
        assert "--resolve-window" in cmd

    @patch("pm_core.tui.pr_view.run_command")
    @patch("pm_core.tui.pr_view.guard_pr_action", return_value=True)
    def test_z1_companion(self, _guard, mock_run):
        """z=1: merge with --companion."""
        from pm_core.tui import pr_view
        app = self._make_app(z_count=1)
        app.query_one.return_value = self._make_tree()

        pr_view.merge_pr(app)

        cmd = mock_run.call_args[0][1]
        assert "--companion" in cmd
        assert "--resolve-window" in cmd
