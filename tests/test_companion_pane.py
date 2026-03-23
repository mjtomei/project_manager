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
            # First call: pre-split (1 pane); second call: post-split (2 panes)
            mock_tmux.get_pane_indices.side_effect = [
                [("%1", 0)],
                [("%1", 0), ("%2", 1)],
            ]
            mock_tmux.split_pane_at.return_value = "%2"
            mock_reg.load_registry.return_value = {}
            mock_reg.get_window_data.return_value = {"user_modified": True}
            # Registry has no entry yet for this window; fall back to first pane
            mock_reg.find_live_pane_by_role.return_value = None

            pr_mod._add_companion_pane("sess", {"id": "@1", "index": "1"},
                                        "/work/dir", "impl")

            mock_tmux.split_pane_at.assert_called_once_with(
                "%1", "h", mock.ANY, background=True,
            )
            # register_and_rebalance called with both panes (impl-claude + impl-companion)
            mock_layout.register_and_rebalance.assert_called_once()
            call_args = mock_layout.register_and_rebalance.call_args[0]
            pane_list = call_args[2]
            roles = [p[1] for p in pane_list]
            assert "impl-claude" in roles
            assert "impl-companion" in roles

    def test_aborts_if_post_split_pane_count_wrong(self):
        """If pane count after split is not 2, kills companion pane and returns."""
        with patch.object(pr_mod, "tmux_mod") as mock_tmux, \
             patch.object(pr_mod, "pane_registry") as mock_reg, \
             patch.object(pr_mod, "pane_layout") as mock_layout, \
             patch.object(pr_mod, "subprocess") as mock_sub:
            # Pre-split: 1 pane; post-split: still only 1 (unexpected)
            mock_tmux.get_pane_indices.side_effect = [
                [("%1", 0)],
                [("%1", 0)],
            ]
            mock_tmux.split_pane_at.return_value = "%2"
            mock_reg.find_live_pane_by_role.return_value = None

            pr_mod._add_companion_pane("sess", {"id": "@1", "index": "1"},
                                        "/work/dir", "impl")

            # Should kill the companion pane
            mock_tmux._tmux_cmd.assert_called_with("kill-pane", "-t", "%2")
            mock_sub.run.assert_called_once()
            # Should not register anything
            mock_layout.register_and_rebalance.assert_not_called()


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
        # find_windows_by_name is used for stale-window detection
        mock_tmux.find_windows_by_name.return_value = [{"id": "@1", "index": "1", "name": "pr-001"}]
        mock_tmux.find_window_by_name.return_value = {"id": "@1", "index": "1", "name": "pr-001"}
        # Calls: (1) _has_pm_panes liveness check, (2) pre-split check, (3) post-split validation
        mock_tmux.get_pane_indices.side_effect = [
            [("%1", 0)],
            [("%1", 0)],
            [("%1", 0), ("%2", 1)],
        ]
        mock_tmux.split_pane_at.return_value = "%2"
        # Registry must have pm panes so window is treated as valid (not stale)
        _reg.load_registry.return_value = {
            "windows": {"@1": {"panes": [{"id": "%1", "role": "impl-claude"}], "user_modified": False}},
        }
        _reg.get_window_data.return_value = {"user_modified": True}
        _reg.find_live_pane_by_role.return_value = None  # fall back in _add_companion_pane

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
        # find_windows_by_name is used for stale-window detection
        mock_tmux.find_windows_by_name.return_value = [{"id": "@1", "index": "1", "name": "pr-001"}]
        mock_tmux.find_window_by_name.return_value = {"id": "@1", "index": "1", "name": "pr-001"}
        # Calls: (1) _has_pm_panes liveness check, (2) pre-split check, (3) post-split validation
        mock_tmux.get_pane_indices.side_effect = [
            [("%1", 0)],
            [("%1", 0)],
            [("%1", 0), ("%2", 1)],
        ]
        mock_tmux.split_pane_at.return_value = "%2"
        # Registry must have pm panes so window is treated as valid (not stale)
        _reg.load_registry.return_value = {
            "windows": {"@1": {"panes": [{"id": "%1", "role": "impl-claude"}], "user_modified": False}},
        }
        _reg.get_window_data.return_value = {"user_modified": True}
        _reg.find_live_pane_by_role.return_value = None  # fall back in _add_companion_pane

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
        # find_windows_by_name used for stale-window check (no existing window)
        mock_tmux.find_windows_by_name.return_value = []
        mock_tmux.find_window_by_name.return_value = {"id": "@2", "index": "2", "name": "merge-pr-001"}
        mock_tmux.new_window_get_pane.return_value = "%1"
        mock_tmux.pane_window_id.return_value = "@2"
        # Calls: (1) post-creation validation (1 pane OK), (2) pre-split in
        # _add_companion_pane (1 pane, not >=2, continue), (3) post-split (2 panes OK)
        mock_tmux.get_pane_indices.side_effect = [
            [("%1", 0)],
            [("%1", 0)],
            [("%1", 0), ("%2", 1)],
        ]
        mock_tmux.split_pane_at.return_value = "%2"
        _reg.load_registry.return_value = {}
        _reg.get_window_data.return_value = {"user_modified": True}
        _reg.find_live_pane_by_role.return_value = None  # fall back in _add_companion_pane

        data = {"project": {"base_branch": "master"}}
        pr_entry = {"id": "pr-001", "workdir": "/work/dir"}

        with patch.object(pr_mod, "_get_pm_session", return_value="pm-sess"), \
             patch("pm_core.paths.get_global_setting", return_value=False), \
             patch.object(pr_mod, "_ensure_workdir", return_value="/work/dir"):
            pr_mod._launch_merge_window(data, pr_entry, "conflict error",
                                         companion=True)

        mock_tmux.new_window_get_pane.assert_called_once()
        mock_tmux.split_pane_at.assert_called_once()
        # merge-claude must NOT be pre-registered separately; registration
        # happens once via _add_companion_pane's register_and_rebalance.
        _reg.register_pane.assert_not_called()
        _layout.register_and_rebalance.assert_called_once()
        call_args = _layout.register_and_rebalance.call_args[0]
        pane_list = call_args[2]
        roles = [p[1] for p in pane_list]
        assert "merge-claude" in roles
        assert "merge-companion" in roles

    @patch.object(pr_mod, "tmux_mod")
    @patch.object(pr_mod, "pane_registry")
    @patch.object(pr_mod, "prompt_gen")
    @patch.object(pr_mod, "build_claude_shell_cmd", return_value="claude ...")
    def test_no_companion_uses_new_window_get_pane(
        self, _cmd, _prompt, _reg, mock_tmux,
    ):
        """_launch_merge_window without companion uses new_window_get_pane and registers pane."""
        mock_tmux.has_tmux.return_value = True
        mock_tmux.in_tmux.return_value = True
        mock_tmux.session_exists.return_value = True
        # find_windows_by_name used for stale-window check (no existing window)
        mock_tmux.find_windows_by_name.return_value = []
        mock_tmux.find_window_by_name.return_value = {"id": "@2", "index": "2", "name": "merge-pr-001"}
        mock_tmux.new_window_get_pane.return_value = "%1"
        mock_tmux.pane_window_id.return_value = "@2"
        mock_tmux.get_pane_indices.return_value = [("%1", 0)]

        data = {"project": {"base_branch": "master"}}
        pr_entry = {"id": "pr-001", "workdir": "/work/dir"}

        with patch.object(pr_mod, "_get_pm_session", return_value="pm-sess"), \
             patch("pm_core.paths.get_global_setting", return_value=False), \
             patch.object(pr_mod, "_ensure_workdir", return_value="/work/dir"):
            pr_mod._launch_merge_window(data, pr_entry, "conflict error")

        mock_tmux.new_window_get_pane.assert_called_once()
        mock_tmux.new_window.assert_not_called()
        # Pane should be registered with merge-claude role
        _reg.register_pane.assert_called_once()
        call_args = _reg.register_pane.call_args[0]
        assert call_args[3] == "merge-claude"


# ---------------------------------------------------------------------------
# TUI companion parameter for start_pr
# ---------------------------------------------------------------------------

class TestTuiStartPrCompanion:
    """Test that companion parameter controls --companion flag."""

    def _make_app(self, z_count=0):
        """Create a mock app with z-prefix state."""
        app = MagicMock()
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
    def test_no_companion(self, _setting, _guard, mock_run):
        """Default: no --companion, no --fresh."""
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
    def test_companion_true(self, _setting, _guard, mock_run):
        """companion=True adds --companion flag."""
        from pm_core.tui import pr_view
        app = self._make_app(z_count=0)
        app.query_one.return_value = self._make_tree()

        pr_view.start_pr(app, companion=True)

        cmd = mock_run.call_args[0][1]
        assert "--companion" in cmd
        assert "--fresh" not in cmd

    @patch("pm_core.tui.pr_view.run_command")
    @patch("pm_core.tui.pr_view.guard_pr_action", return_value=True)
    @patch("pm_core.paths.get_global_setting", return_value=False)
    def test_z_fresh_preserved(self, _setting, _guard, mock_run):
        """z prefix still means fresh (backward compat)."""
        from pm_core.tui import pr_view
        app = self._make_app(z_count=1)
        app.query_one.return_value = self._make_tree()

        pr_view.start_pr(app)

        cmd = mock_run.call_args[0][1]
        assert "--fresh" in cmd
        assert "--companion" not in cmd

    @patch("pm_core.tui.pr_view.run_command")
    @patch("pm_core.tui.pr_view.guard_pr_action", return_value=True)
    @patch("pm_core.paths.get_global_setting", return_value=False)
    def test_z_fresh_with_companion(self, _setting, _guard, mock_run):
        """z prefix (fresh) combined with companion=True."""
        from pm_core.tui import pr_view
        app = self._make_app(z_count=1)
        app.query_one.return_value = self._make_tree()

        pr_view.start_pr(app, companion=True)

        cmd = mock_run.call_args[0][1]
        assert "--fresh" in cmd
        assert "--companion" in cmd


# ---------------------------------------------------------------------------
# TUI companion parameter for merge_pr
# ---------------------------------------------------------------------------

class TestTuiMergePrCompanion:
    """Test that companion parameter controls --companion flag for merge."""

    def _make_app(self):
        app = MagicMock()
        app._inflight_pr_action = None
        return app

    def _make_tree(self, pr_id="pr-001"):
        tree = MagicMock()
        tree.selected_pr_id = pr_id
        return tree

    @patch("pm_core.tui.pr_view.run_command")
    @patch("pm_core.tui.pr_view.guard_pr_action", return_value=True)
    def test_no_companion(self, _guard, mock_run):
        """Default: no --companion."""
        from pm_core.tui import pr_view
        app = self._make_app()
        app.query_one.return_value = self._make_tree()

        pr_view.merge_pr(app)

        cmd = mock_run.call_args[0][1]
        assert "--companion" not in cmd
        assert "--resolve-window" in cmd

    @patch("pm_core.tui.pr_view.run_command")
    @patch("pm_core.tui.pr_view.guard_pr_action", return_value=True)
    def test_companion_true(self, _guard, mock_run):
        """companion=True adds --companion flag."""
        from pm_core.tui import pr_view
        app = self._make_app()
        app.query_one.return_value = self._make_tree()

        pr_view.merge_pr(app, companion=True)

        cmd = mock_run.call_args[0][1]
        assert "--companion" in cmd
        assert "--resolve-window" in cmd


# ---------------------------------------------------------------------------
# _has_pm_panes and _find_or_rename_stale_window helpers
# ---------------------------------------------------------------------------

class TestHasPmPanes:
    def test_returns_false_when_no_registry_entry(self):
        with patch.object(pr_mod, "pane_registry") as mock_reg, \
             patch.object(pr_mod, "tmux_mod"):
            mock_reg.load_registry.return_value = {"windows": {}}
            assert pr_mod._has_pm_panes("sess", "@1") is False

    def test_returns_false_when_registered_pane_is_dead(self):
        with patch.object(pr_mod, "pane_registry") as mock_reg, \
             patch.object(pr_mod, "tmux_mod") as mock_tmux:
            mock_reg.load_registry.return_value = {
                "windows": {"@1": {"panes": [{"id": "%99", "role": "impl-claude"}]}}
            }
            mock_tmux.get_pane_indices.return_value = []  # no live panes
            assert pr_mod._has_pm_panes("sess", "@1") is False

    def test_returns_true_when_registered_pane_is_live(self):
        with patch.object(pr_mod, "pane_registry") as mock_reg, \
             patch.object(pr_mod, "tmux_mod") as mock_tmux:
            mock_reg.load_registry.return_value = {
                "windows": {"@1": {"panes": [{"id": "%1", "role": "impl-claude"}]}}
            }
            mock_tmux.get_pane_indices.return_value = [("%1", 0)]
            assert pr_mod._has_pm_panes("sess", "@1") is True


class TestFindOrRenameStaleWindow:
    def test_returns_none_when_no_window(self):
        with patch.object(pr_mod, "tmux_mod") as mock_tmux:
            mock_tmux.find_windows_by_name.return_value = []
            assert pr_mod._find_or_rename_stale_window("sess", "pr-001") is None
            mock_tmux.rename_window.assert_not_called()

    def test_returns_window_when_pm_managed(self):
        window = {"id": "@1", "index": "1", "name": "pr-001"}
        with patch.object(pr_mod, "tmux_mod") as mock_tmux, \
             patch.object(pr_mod, "pane_registry") as mock_reg:
            mock_tmux.find_windows_by_name.return_value = [window]
            mock_reg.load_registry.return_value = {
                "windows": {"@1": {"panes": [{"id": "%1", "role": "impl-claude"}]}}
            }
            mock_tmux.get_pane_indices.return_value = [("%1", 0)]
            result = pr_mod._find_or_rename_stale_window("sess", "pr-001")
            assert result == window
            mock_tmux.rename_window.assert_not_called()

    def test_renames_stale_window_and_returns_none(self):
        window = {"id": "@1", "index": "1", "name": "pr-001"}
        with patch.object(pr_mod, "tmux_mod") as mock_tmux, \
             patch.object(pr_mod, "pane_registry") as mock_reg:
            mock_tmux.find_windows_by_name.return_value = [window]
            mock_reg.load_registry.return_value = {"windows": {}}  # no registry entry
            result = pr_mod._find_or_rename_stale_window("sess", "pr-001")
            assert result is None
            mock_tmux.rename_window.assert_called_once()
            new_name = mock_tmux.rename_window.call_args[0][2]
            assert new_name.startswith("pr-001-stale-")

    def test_disambiguates_duplicates_preferring_pm_managed(self):
        managed_win = {"id": "@1", "index": "1", "name": "pr-001"}
        stale_win = {"id": "@2", "index": "2", "name": "pr-001"}
        with patch.object(pr_mod, "tmux_mod") as mock_tmux, \
             patch.object(pr_mod, "pane_registry") as mock_reg:
            mock_tmux.find_windows_by_name.return_value = [managed_win, stale_win]
            # @1 has live pane, @2 does not
            mock_reg.load_registry.return_value = {
                "windows": {
                    "@1": {"panes": [{"id": "%1", "role": "impl-claude"}]},
                    "@2": {"panes": []},
                }
            }
            mock_tmux.get_pane_indices.side_effect = lambda sess, win: (
                [("%1", 0)] if win == "@1" else []
            )
            result = pr_mod._find_or_rename_stale_window("sess", "pr-001")
            assert result == managed_win
            # Only the stale window should be renamed
            mock_tmux.rename_window.assert_called_once()
            assert mock_tmux.rename_window.call_args[0][1] == "@2"

    def test_all_duplicates_unmanaged_renames_all_uniquely(self):
        windows = [
            {"id": "@1", "index": "1", "name": "pr-001"},
            {"id": "@2", "index": "2", "name": "pr-001"},
        ]
        with patch.object(pr_mod, "tmux_mod") as mock_tmux, \
             patch.object(pr_mod, "pane_registry") as mock_reg:
            mock_tmux.find_windows_by_name.return_value = windows
            mock_reg.load_registry.return_value = {"windows": {}}
            mock_tmux.get_pane_indices.return_value = []
            result = pr_mod._find_or_rename_stale_window("sess", "pr-001")
            assert result is None
            assert mock_tmux.rename_window.call_count == 2
            # Both renamed names must be unique
            names = [c[0][2] for c in mock_tmux.rename_window.call_args_list]
            assert len(set(names)) == 2, f"Expected unique stale names, got: {names}"
