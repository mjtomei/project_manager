"""Tests for session cleanup and session-closed CLI commands."""

from unittest.mock import patch, MagicMock, call

import pytest
from click.testing import CliRunner

from pm_core.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestSessionCleanup:
    """Tests for ``pm session cleanup``."""

    @patch("pm_core.push_proxy.restart_dead_proxies", return_value=0)
    @patch("pm_core.push_proxy.cleanup_stale_proxy_dirs", return_value=0)
    @patch("pm_core.container.cleanup_stale_containers", return_value=2)
    @patch("pm_core.cli.session._get_session_name_for_cwd",
           return_value="pm-repo-abc123")
    def test_reports_removed_containers(
        self, mock_session, mock_containers, mock_proxies, mock_restart,
        runner,
    ):
        result = runner.invoke(cli, ["session", "cleanup"])
        assert result.exit_code == 0
        assert "2 stale container(s) removed" in result.output
        mock_containers.assert_called_once_with(
            "pm-repo-abc123", "repo-abc123")

    @patch("pm_core.push_proxy.restart_dead_proxies", return_value=3)
    @patch("pm_core.push_proxy.cleanup_stale_proxy_dirs", return_value=1)
    @patch("pm_core.container.cleanup_stale_containers", return_value=0)
    @patch("pm_core.cli.session._get_session_name_for_cwd",
           return_value="pm-repo-abc123")
    def test_reports_proxies_and_restarts(
        self, mock_session, mock_containers, mock_proxies, mock_restart,
        runner,
    ):
        result = runner.invoke(cli, ["session", "cleanup"])
        assert result.exit_code == 0
        assert "1 dead proxy dir(s) cleaned" in result.output
        assert "3 proxy(ies) restarted" in result.output

    @patch("pm_core.push_proxy.restart_dead_proxies", return_value=0)
    @patch("pm_core.push_proxy.cleanup_stale_proxy_dirs", return_value=0)
    @patch("pm_core.container.cleanup_stale_containers", return_value=0)
    @patch("pm_core.cli.session._get_session_name_for_cwd",
           return_value="pm-repo-abc123")
    def test_reports_nothing_found(
        self, mock_session, mock_containers, mock_proxies, mock_restart,
        runner,
    ):
        result = runner.invoke(cli, ["session", "cleanup"])
        assert result.exit_code == 0
        assert "No stale containers or proxies found." in result.output

    @patch("pm_core.push_proxy.restart_dead_proxies", return_value=0)
    @patch("pm_core.push_proxy.cleanup_stale_proxy_dirs", return_value=0)
    @patch("pm_core.container.cleanup_stale_containers", return_value=0)
    @patch("pm_core.cli.session._get_session_name_for_cwd",
           return_value="pm-repo-abc123")
    def test_works_without_tmux_session(
        self, mock_session, mock_containers, mock_proxies, mock_restart,
        runner,
    ):
        """EC5: cleanup should work even when tmux session is not running."""
        # No mock for tmux_mod.session_exists — it should not be called
        result = runner.invoke(cli, ["session", "cleanup"])
        assert result.exit_code == 0


class TestSessionClosedHook:
    """Tests for ``pm _session-closed``."""

    @patch("pm_core.push_proxy.cleanup_stale_proxy_dirs", return_value=0)
    @patch("pm_core.push_proxy.stop_session_proxies", return_value=0)
    @patch("pm_core.container.cleanup_session_containers", return_value=0)
    @patch("pm_core.tmux.session_exists", return_value=False)
    def test_cleans_up_when_base_session_gone(
        self, mock_exists, mock_containers, mock_proxies, mock_dirs, runner,
    ):
        result = runner.invoke(cli, ["_session-closed", "pm-repo-abc123"])
        assert result.exit_code == 0
        mock_containers.assert_called_once_with("repo-abc123")
        mock_proxies.assert_called_once_with("repo-abc123")
        mock_dirs.assert_called_once_with("repo-abc123")

    @patch("pm_core.container.cleanup_session_containers")
    @patch("pm_core.tmux.session_exists", return_value=True)
    def test_noop_when_base_session_still_exists(
        self, mock_exists, mock_containers, runner,
    ):
        """Grouped session closing (pm-tag~2) should not trigger cleanup."""
        result = runner.invoke(cli, ["_session-closed", "pm-repo-abc~2"])
        assert result.exit_code == 0
        mock_containers.assert_not_called()

    @patch("pm_core.container.cleanup_session_containers")
    def test_noop_for_non_pm_session(self, mock_containers, runner):
        """IR5: non-pm sessions should be ignored."""
        result = runner.invoke(cli, ["_session-closed", "my-session"])
        assert result.exit_code == 0
        mock_containers.assert_not_called()

    @patch("pm_core.container.cleanup_session_containers")
    def test_noop_for_empty_session_tag(self, mock_containers, runner):
        """session_tag would be empty string for just 'pm-'."""
        result = runner.invoke(cli, ["_session-closed", "pm-"])
        assert result.exit_code == 0
        mock_containers.assert_not_called()
