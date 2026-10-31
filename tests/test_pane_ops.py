"""Tests for pane_ops cleanup functions."""

from unittest.mock import patch, MagicMock


class TestCleanupMergedPrResources:
    """Test cleanup_merged_pr_resources."""

    @patch("pm_core.cli.helpers.kill_pr_windows", return_value=[])
    @patch("pm_core.tui.pane_ops.store.load")
    def test_kills_windows_for_merged_prs(self, mock_load, mock_kpw):
        from pm_core.tui.pane_ops import cleanup_merged_pr_resources

        mock_load.return_value = {
            "prs": [
                {"id": "pr-aaa", "status": "merged", "title": "A"},
                {"id": "pr-bbb", "status": "in_progress", "title": "B"},
                {"id": "pr-ccc", "status": "merged", "title": "C"},
            ]
        }
        cleanup_merged_pr_resources("pm-test-session")
        assert mock_kpw.call_count == 2
        call_pr_ids = [c.args[1]["id"] for c in mock_kpw.call_args_list]
        assert "pr-aaa" in call_pr_ids
        assert "pr-ccc" in call_pr_ids

    @patch("pm_core.tui.pane_ops.store.load")
    def test_no_merged_prs_is_noop(self, mock_load):
        from pm_core.tui.pane_ops import cleanup_merged_pr_resources

        mock_load.return_value = {
            "prs": [
                {"id": "pr-aaa", "status": "in_progress"},
            ]
        }
        cleanup_merged_pr_resources("pm-test-session")

    @patch("pm_core.tui.pane_ops.store.load", side_effect=FileNotFoundError)
    def test_handles_load_failure(self, mock_load):
        from pm_core.tui.pane_ops import cleanup_merged_pr_resources

        cleanup_merged_pr_resources("pm-test-session")

    @patch("pm_core.container.cleanup_pr_containers")
    @patch("pm_core.container.is_container_mode_enabled", return_value=True)
    @patch("pm_core.cli.helpers.kill_pr_windows", return_value=[])
    @patch("pm_core.tui.pane_ops.store.load")
    def test_cleans_containers_when_enabled(self, mock_load, mock_kpw,
                                            mock_enabled, mock_cleanup):
        from pm_core.tui.pane_ops import cleanup_merged_pr_resources

        mock_load.return_value = {
            "prs": [{"id": "pr-aaa", "status": "merged"}]
        }
        cleanup_merged_pr_resources("pm-test-session")
        mock_cleanup.assert_called_once_with("pr-aaa")

    @patch("pm_core.container.cleanup_pr_containers")
    @patch("pm_core.container.is_container_mode_enabled", return_value=False)
    @patch("pm_core.cli.helpers.kill_pr_windows", return_value=[])
    @patch("pm_core.tui.pane_ops.store.load")
    def test_skips_containers_when_disabled(self, mock_load, mock_kpw,
                                            mock_enabled, mock_cleanup):
        from pm_core.tui.pane_ops import cleanup_merged_pr_resources

        mock_load.return_value = {
            "prs": [{"id": "pr-aaa", "status": "merged"}]
        }
        cleanup_merged_pr_resources("pm-test-session")
        mock_cleanup.assert_not_called()
