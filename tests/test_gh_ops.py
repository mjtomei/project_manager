"""Tests for gh_ops GitHub CLI wrapper functions."""

import subprocess
from unittest import mock

import pytest

from pm_core import gh_ops


@pytest.fixture
def mock_gh_check():
    """Mock the _check_gh function to avoid actual gh CLI checks."""
    with mock.patch.object(gh_ops, "_check_gh"):
        yield


class TestCreateDraftPr:
    """Tests for create_draft_pr function."""

    def test_creates_draft_pr_successfully(self, mock_gh_check):
        """Should create a draft PR and return url and number."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout="https://github.com/owner/repo/pull/42\n",
                stderr="",
            )

            result = gh_ops.create_draft_pr(
                workdir="/tmp/repo",
                title="Test PR",
                base="main",
                body="Test body",
            )

            assert result is not None
            assert result["url"] == "https://github.com/owner/repo/pull/42"
            assert result["number"] == 42

            # Verify the command was called correctly
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args[0][0] == [
                "gh", "pr", "create",
                "--draft",
                "--title", "Test PR",
                "--base", "main",
                "--body", "Test body",
            ]

    def test_returns_none_on_failure(self, mock_gh_check):
        """Should return None if PR creation fails."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=1,
                stdout="",
                stderr="Error: failed to create PR",
            )

            result = gh_ops.create_draft_pr(
                workdir="/tmp/repo",
                title="Test PR",
                base="main",
            )

            assert result is None

    def test_extracts_pr_number_from_url(self, mock_gh_check):
        """Should extract PR number from various URL formats."""
        with mock.patch("subprocess.run") as mock_run:
            # URL without trailing slash
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout="https://github.com/owner/repo/pull/123",
                stderr="",
            )
            result = gh_ops.create_draft_pr("/tmp/repo", "Test", "main")
            assert result["number"] == 123

            # URL with trailing slash
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout="https://github.com/owner/repo/pull/456/",
                stderr="",
            )
            result = gh_ops.create_draft_pr("/tmp/repo", "Test", "main")
            assert result["number"] == 456

    def test_handles_empty_body(self, mock_gh_check):
        """Should work with empty body parameter."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout="https://github.com/owner/repo/pull/1\n",
                stderr="",
            )

            result = gh_ops.create_draft_pr("/tmp/repo", "Test", "main")

            assert result is not None
            call_args = mock_run.call_args[0][0]
            assert "--body" in call_args
            # Body should be empty string
            body_idx = call_args.index("--body")
            assert call_args[body_idx + 1] == ""


class TestMarkPrReady:
    """Tests for mark_pr_ready function."""

    def test_marks_pr_ready_by_number(self, mock_gh_check):
        """Should mark PR ready using PR number."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout="",
                stderr="",
            )

            result = gh_ops.mark_pr_ready("/tmp/repo", 42)

            assert result is True
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args == ["gh", "pr", "ready", "42"]

    def test_marks_pr_ready_by_branch(self, mock_gh_check):
        """Should mark PR ready using branch name."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout="",
                stderr="",
            )

            result = gh_ops.mark_pr_ready("/tmp/repo", "feature-branch")

            assert result is True
            call_args = mock_run.call_args[0][0]
            assert call_args == ["gh", "pr", "ready", "feature-branch"]

    def test_returns_false_on_failure(self, mock_gh_check):
        """Should return False if marking ready fails."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=1,
                stdout="",
                stderr="Error: PR is not a draft",
            )

            result = gh_ops.mark_pr_ready("/tmp/repo", 42)

            assert result is False


class TestGetPrStatus:
    """Tests for get_pr_status function."""

    def test_returns_pr_info(self, mock_gh_check):
        """Should return PR info dict."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout='{"state":"OPEN","url":"https://github.com/o/r/pull/1","number":1,"title":"Test","mergedAt":null}',
                stderr="",
            )

            result = gh_ops.get_pr_status("/tmp/repo", "feature")

            assert result is not None
            assert result["state"] == "OPEN"
            assert result["number"] == 1

    def test_returns_none_for_missing_pr(self, mock_gh_check):
        """Should return None if no PR exists for branch."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=1,
                stdout="",
                stderr="no pull requests found",
            )

            result = gh_ops.get_pr_status("/tmp/repo", "nonexistent-branch")

            assert result is None


class TestIsPrMerged:
    """Tests for is_pr_merged function."""

    def test_returns_true_for_merged_pr(self, mock_gh_check):
        """Should return True when PR state is MERGED."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout='{"state":"MERGED","url":"https://github.com/o/r/pull/1","number":1,"title":"Test","mergedAt":"2024-01-01T00:00:00Z"}',
                stderr="",
            )

            result = gh_ops.is_pr_merged("/tmp/repo", "merged-branch")

            assert result is True

    def test_returns_false_for_open_pr(self, mock_gh_check):
        """Should return False when PR is still open."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout='{"state":"OPEN","url":"https://github.com/o/r/pull/1","number":1,"title":"Test","mergedAt":null}',
                stderr="",
            )

            result = gh_ops.is_pr_merged("/tmp/repo", "open-branch")

            assert result is False

    def test_returns_false_for_no_pr(self, mock_gh_check):
        """Should return False when no PR exists."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=1,
                stdout="",
                stderr="no pull requests found",
            )

            result = gh_ops.is_pr_merged("/tmp/repo", "no-pr-branch")

            assert result is False
