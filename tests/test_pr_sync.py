"""Tests for PR sync functionality."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pm_core import pr_sync, store


@pytest.fixture
def tmp_pm_root(tmp_path):
    """Create a temporary PM root directory with minimal project.yaml."""
    root = tmp_path / "pm"
    root.mkdir()
    (root / "project.yaml").write_text(
        "project:\n"
        "  name: test-project\n"
        "  repo: /tmp/test-repo\n"
        "  base_branch: main\n"
        "  backend: vanilla\n"
        "prs: []\n"
    )
    return root


@pytest.fixture
def tmp_pm_root_with_prs(tmp_path):
    """Create a temporary PM root with some PRs."""
    root = tmp_path / "pm"
    root.mkdir()
    (root / "project.yaml").write_text(
        "project:\n"
        "  name: test-project\n"
        "  repo: /tmp/test-repo\n"
        "  base_branch: main\n"
        "  backend: vanilla\n"
        "prs:\n"
        "  - id: pr-001\n"
        "    title: First PR\n"
        "    status: in_progress\n"
        "    branch: pm/pr-001-first\n"
        "  - id: pr-002\n"
        "    title: Second PR\n"
        "    status: in_review\n"
        "    branch: pm/pr-002-second\n"
        "  - id: pr-003\n"
        "    title: Third PR\n"
        "    status: pending\n"
        "    branch: pm/pr-003-third\n"
        "    depends_on:\n"
        "      - pr-001\n"
    )
    return root


@pytest.fixture
def tmp_pm_root_github(tmp_path):
    """Create a temporary PM root with GitHub backend and gh_pr_number fields."""
    root = tmp_path / "pm"
    root.mkdir()
    (root / "project.yaml").write_text(
        "project:\n"
        "  name: test-project\n"
        "  repo: https://github.com/test/repo.git\n"
        "  base_branch: main\n"
        "  backend: github\n"
        "prs:\n"
        "  - id: pr-001\n"
        "    title: First PR\n"
        "    status: in_progress\n"
        "    branch: pm/pr-001-first\n"
        "    gh_pr_number: 101\n"
        "  - id: pr-002\n"
        "    title: Second PR\n"
        "    status: in_review\n"
        "    branch: pm/pr-002-second\n"
        "    gh_pr_number: 102\n"
        "  - id: pr-003\n"
        "    title: Third PR\n"
        "    status: pending\n"
        "    branch: pm/pr-003-third\n"
    )
    return root


class TestLastSyncTimestamp:
    """Tests for timestamp tracking."""

    def test_get_last_sync_timestamp_none_when_missing(self, tmp_pm_root):
        """get_last_sync_timestamp returns None when no timestamp stored."""
        data = store.load(tmp_pm_root)
        assert pr_sync.get_last_sync_timestamp(data) is None

    def test_get_last_sync_timestamp_parses_iso_format(self, tmp_pm_root):
        """get_last_sync_timestamp parses ISO format timestamp."""
        data = store.load(tmp_pm_root)
        expected = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        data["project"]["last_pr_sync"] = expected.isoformat()

        result = pr_sync.get_last_sync_timestamp(data)
        assert result == expected

    def test_get_last_sync_timestamp_handles_invalid_format(self, tmp_pm_root):
        """get_last_sync_timestamp returns None for invalid timestamp."""
        data = store.load(tmp_pm_root)
        data["project"]["last_pr_sync"] = "not-a-timestamp"

        result = pr_sync.get_last_sync_timestamp(data)
        assert result is None

    def test_set_last_sync_timestamp(self, tmp_pm_root):
        """set_last_sync_timestamp stores ISO format timestamp."""
        data = store.load(tmp_pm_root)
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

        pr_sync.set_last_sync_timestamp(data, timestamp)

        assert data["project"]["last_pr_sync"] == timestamp.isoformat()

    def test_set_last_sync_timestamp_creates_project_section(self):
        """set_last_sync_timestamp creates project section if missing."""
        data = {}
        timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

        pr_sync.set_last_sync_timestamp(data, timestamp)

        assert "project" in data
        assert data["project"]["last_pr_sync"] == timestamp.isoformat()


class TestShouldSync:
    """Tests for sync interval checking."""

    def test_should_sync_true_when_no_previous_sync(self, tmp_pm_root):
        """should_sync returns True when no previous sync recorded."""
        data = store.load(tmp_pm_root)

        should, reason = pr_sync.should_sync(data)

        assert should is True
        assert reason is None

    def test_should_sync_false_when_too_recent(self, tmp_pm_root):
        """should_sync returns False when last sync was too recent."""
        data = store.load(tmp_pm_root)
        recent = datetime.now(timezone.utc) - timedelta(seconds=30)
        data["project"]["last_pr_sync"] = recent.isoformat()

        should, reason = pr_sync.should_sync(data, min_interval_seconds=60)

        assert should is False
        assert "synced" in reason
        assert "min interval: 60s" in reason

    def test_should_sync_true_when_interval_exceeded(self, tmp_pm_root):
        """should_sync returns True when enough time has passed."""
        data = store.load(tmp_pm_root)
        old = datetime.now(timezone.utc) - timedelta(seconds=120)
        data["project"]["last_pr_sync"] = old.isoformat()

        should, reason = pr_sync.should_sync(data, min_interval_seconds=60)

        assert should is True
        assert reason is None

    def test_should_sync_true_when_forced(self, tmp_pm_root):
        """should_sync returns True when force=True regardless of timestamp."""
        data = store.load(tmp_pm_root)
        recent = datetime.now(timezone.utc) - timedelta(seconds=5)
        data["project"]["last_pr_sync"] = recent.isoformat()

        should, reason = pr_sync.should_sync(data, min_interval_seconds=60, force=True)

        assert should is True
        assert reason is None

    def test_should_sync_handles_naive_datetime(self, tmp_pm_root):
        """should_sync handles naive datetime (no timezone) in stored timestamp."""
        data = store.load(tmp_pm_root)
        # Intentionally use naive datetime (no timezone) to test that the code
        # handles timestamps stored without timezone info gracefully
        old = datetime.now() - timedelta(seconds=120)
        data["project"]["last_pr_sync"] = old.isoformat()

        # Should not crash and should allow sync
        should, reason = pr_sync.should_sync(data, min_interval_seconds=60)

        assert should is True


class TestFindWorkdir:
    """Tests for workdir discovery."""

    def test_find_workdir_returns_none_when_no_workdirs(self, tmp_pm_root):
        """find_workdir returns None when no workdirs exist."""
        data = store.load(tmp_pm_root)

        result = pr_sync.find_workdir(data)

        assert result is None

    def test_find_workdir_returns_pr_workdir(self, tmp_pm_root_with_prs, tmp_path):
        """find_workdir returns a PR's workdir if it exists."""
        data = store.load(tmp_pm_root_with_prs)

        # Create a fake workdir for pr-001
        workdir = tmp_path / "workdir-001"
        workdir.mkdir()
        (workdir / ".git").mkdir()

        data["prs"][0]["workdir"] = str(workdir)

        with patch("pm_core.git_ops.is_git_repo", return_value=True):
            result = pr_sync.find_workdir(data)

        assert result == str(workdir)


class TestSyncPrs:
    """Tests for the main sync function."""

    def test_sync_prs_skipped_when_too_recent(self, tmp_pm_root_with_prs):
        """sync_prs skips when last sync was too recent."""
        data = store.load(tmp_pm_root_with_prs)
        recent = datetime.now(timezone.utc) - timedelta(seconds=30)
        data["project"]["last_pr_sync"] = recent.isoformat()
        store.save(data, tmp_pm_root_with_prs)

        result = pr_sync.sync_prs(tmp_pm_root_with_prs, min_interval_seconds=60)

        assert result.synced is False
        assert result.was_skipped is True
        assert "synced" in result.skipped_reason

    def test_sync_prs_error_when_no_workdir(self, tmp_pm_root_with_prs):
        """sync_prs returns error when no workdir available."""
        result = pr_sync.sync_prs(tmp_pm_root_with_prs, force=True)

        assert result.synced is False
        assert result.error is not None
        assert "No workdirs found" in result.error

    def test_sync_prs_detects_merged_prs(self, tmp_pm_root_with_prs, tmp_path):
        """sync_prs detects and updates merged PRs."""
        data = store.load(tmp_pm_root_with_prs)

        # Create a fake workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir()
        (workdir / ".git").mkdir()
        data["prs"][0]["workdir"] = str(workdir)
        store.save(data, tmp_pm_root_with_prs)

        # Mock the backend to say pr-001 is merged
        mock_backend = MagicMock()
        mock_backend.is_merged.side_effect = lambda wd, branch, base: branch == "pm/pr-001-first"

        with patch("pm_core.pr_sync.get_backend", return_value=mock_backend), \
             patch("pm_core.git_ops.is_git_repo", return_value=True):
            result = pr_sync.sync_prs(tmp_pm_root_with_prs, force=True)

        assert result.synced is True
        assert result.updated_count == 1
        assert "pr-001" in result.merged_prs

        # Verify the PR status was updated
        updated_data = store.load(tmp_pm_root_with_prs)
        pr_001 = next(p for p in updated_data["prs"] if p["id"] == "pr-001")
        assert pr_001["status"] == "merged"

    def test_sync_prs_updates_timestamp(self, tmp_pm_root_with_prs, tmp_path):
        """sync_prs updates the last_pr_sync timestamp."""
        data = store.load(tmp_pm_root_with_prs)

        # Create a fake workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir()
        (workdir / ".git").mkdir()
        data["prs"][0]["workdir"] = str(workdir)
        store.save(data, tmp_pm_root_with_prs)

        mock_backend = MagicMock()
        mock_backend.is_merged.return_value = False

        with patch("pm_core.pr_sync.get_backend", return_value=mock_backend), \
             patch("pm_core.git_ops.is_git_repo", return_value=True):
            pr_sync.sync_prs(tmp_pm_root_with_prs, force=True)

        updated_data = store.load(tmp_pm_root_with_prs)
        assert "last_pr_sync" in updated_data["project"]

    def test_sync_prs_skips_pending_prs(self, tmp_pm_root_with_prs, tmp_path):
        """sync_prs does not check pending PRs for merge status."""
        data = store.load(tmp_pm_root_with_prs)

        # Create a fake workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir()
        (workdir / ".git").mkdir()
        data["prs"][0]["workdir"] = str(workdir)
        store.save(data, tmp_pm_root_with_prs)

        mock_backend = MagicMock()
        mock_backend.is_merged.return_value = True

        with patch("pm_core.pr_sync.get_backend", return_value=mock_backend), \
             patch("pm_core.git_ops.is_git_repo", return_value=True):
            result = pr_sync.sync_prs(tmp_pm_root_with_prs, force=True)

        # Only in_progress and in_review should be checked
        # pr-003 is pending, so should not be in merged_prs
        assert "pr-003" not in result.merged_prs

    def test_sync_prs_quiet_does_not_save(self, tmp_pm_root_with_prs, tmp_path):
        """sync_prs_quiet does not save changes to disk."""
        data = store.load(tmp_pm_root_with_prs)

        # Create a fake workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir()
        (workdir / ".git").mkdir()
        data["prs"][0]["workdir"] = str(workdir)
        store.save(data, tmp_pm_root_with_prs)

        mock_backend = MagicMock()
        mock_backend.is_merged.side_effect = lambda wd, branch, base: branch == "pm/pr-001-first"

        with patch("pm_core.pr_sync.get_backend", return_value=mock_backend), \
             patch("pm_core.git_ops.is_git_repo", return_value=True):
            updated_data, result = pr_sync.sync_prs_quiet(tmp_pm_root_with_prs, force=True)

        # The returned data should have the merged status
        pr_001 = next(p for p in updated_data["prs"] if p["id"] == "pr-001")
        assert pr_001["status"] == "merged"

        # But the file should not have been updated
        disk_data = store.load(tmp_pm_root_with_prs)
        disk_pr_001 = next(p for p in disk_data["prs"] if p["id"] == "pr-001")
        assert disk_pr_001["status"] == "in_progress"


class TestSyncResult:
    """Tests for SyncResult class."""

    def test_sync_result_was_skipped_true_when_reason_set(self):
        """was_skipped is True when skipped_reason is set."""
        result = pr_sync.SyncResult(synced=False, skipped_reason="too recent")
        assert result.was_skipped is True

    def test_sync_result_was_skipped_false_when_no_reason(self):
        """was_skipped is False when skipped_reason is None."""
        result = pr_sync.SyncResult(synced=True)
        assert result.was_skipped is False

    def test_sync_result_defaults(self):
        """SyncResult has correct defaults."""
        result = pr_sync.SyncResult(synced=True)
        assert result.updated_count == 0
        assert result.merged_prs == []
        assert result.closed_prs == []
        assert result.ready_prs == []
        assert result.error is None
        assert result.skipped_reason is None

    def test_sync_result_closed_prs(self):
        """SyncResult tracks closed PRs."""
        result = pr_sync.SyncResult(
            synced=True,
            updated_count=2,
            closed_prs=["pr-001", "pr-002"]
        )
        assert result.closed_prs == ["pr-001", "pr-002"]


class TestMinIntervalConstants:
    """Tests for interval constants."""

    def test_background_interval_is_5_minutes(self):
        """Background sync interval should be 5 minutes."""
        assert pr_sync.MIN_BACKGROUND_SYNC_INTERVAL_SECONDS == 300

    def test_manual_interval_is_1_minute(self):
        """Manual sync interval should be 1 minute."""
        assert pr_sync.MIN_SYNC_INTERVAL_SECONDS == 60


class TestCLIIntegration:
    """Tests for CLI integration with pr_sync."""

    def test_pr_sync_quiet_returns_updated_data(self, tmp_pm_root_with_prs, tmp_path):
        """sync_prs_quiet returns updated data that CLI can use."""
        data = store.load(tmp_pm_root_with_prs)

        # Create a fake workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir()
        (workdir / ".git").mkdir()
        data["prs"][0]["workdir"] = str(workdir)
        store.save(data, tmp_pm_root_with_prs)

        mock_backend = MagicMock()
        mock_backend.is_merged.side_effect = lambda wd, branch, base: branch == "pm/pr-001-first"

        with patch("pm_core.pr_sync.get_backend", return_value=mock_backend), \
             patch("pm_core.git_ops.is_git_repo", return_value=True):
            updated_data, result = pr_sync.sync_prs_quiet(tmp_pm_root_with_prs, force=True)

        # The result should indicate successful sync
        assert result.synced is True
        assert result.updated_count == 1

        # The updated_data should have the new status
        pr_001 = next(p for p in updated_data["prs"] if p["id"] == "pr-001")
        assert pr_001["status"] == "merged"

        # CLI can now save this data
        store.save(updated_data, tmp_pm_root_with_prs)

        # Verify saved data
        final_data = store.load(tmp_pm_root_with_prs)
        pr_001_final = next(p for p in final_data["prs"] if p["id"] == "pr-001")
        assert pr_001_final["status"] == "merged"


class TestSyncFromGitHub:
    """Tests for sync_from_github function."""

    def test_sync_from_github_requires_github_backend(self, tmp_pm_root):
        """sync_from_github returns error for non-GitHub backends."""
        result = pr_sync.sync_from_github(tmp_pm_root)

        assert result.synced is False
        assert "GitHub" in result.error

    def test_sync_from_github_detects_merged(self, tmp_pm_root_github):
        """sync_from_github detects merged PRs from GitHub API."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "state": "MERGED",
            "isDraft": False,
            "mergedAt": "2024-01-15T10:00:00Z"
        })

        with patch("subprocess.run", return_value=mock_result), \
             patch("subprocess.Popen"):  # Don't actually spawn background process
            result = pr_sync.sync_from_github(tmp_pm_root_github, save_state=False)

        assert result.synced is True
        assert "pr-001" in result.merged_prs

    def test_sync_from_github_detects_closed(self, tmp_pm_root_github):
        """sync_from_github detects closed PRs from GitHub API."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "state": "CLOSED",
            "isDraft": False,
            "mergedAt": None
        })

        with patch("subprocess.run", return_value=mock_result), \
             patch("subprocess.Popen"):  # Don't actually spawn background process
            result = pr_sync.sync_from_github(tmp_pm_root_github, save_state=False)

        assert result.synced is True
        assert "pr-001" in result.closed_prs

    def test_sync_from_github_detects_draft_as_in_progress(self, tmp_pm_root_github):
        """sync_from_github sets draft PRs to in_progress."""
        data = store.load(tmp_pm_root_github)
        # Set pr-001 to in_review first
        data["prs"][0]["status"] = "in_review"
        store.save(data, tmp_pm_root_github)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "state": "OPEN",
            "isDraft": True,
            "mergedAt": None
        })

        with patch("subprocess.run", return_value=mock_result), \
             patch("subprocess.Popen"):
            result = pr_sync.sync_from_github(tmp_pm_root_github, save_state=False)

        assert result.synced is True
        assert result.updated_count >= 1

    def test_sync_from_github_detects_ready_as_in_review(self, tmp_pm_root_github):
        """sync_from_github sets ready PRs to in_review."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "state": "OPEN",
            "isDraft": False,
            "mergedAt": None
        })

        with patch("subprocess.run", return_value=mock_result), \
             patch("subprocess.Popen"):
            result = pr_sync.sync_from_github(tmp_pm_root_github, save_state=False)

        assert result.synced is True
        # pr-001 was in_progress, should change to in_review
        assert result.updated_count >= 1

    def test_sync_from_github_skips_prs_without_gh_pr_number(self, tmp_pm_root_github):
        """sync_from_github skips PRs without gh_pr_number."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "state": "MERGED",
            "isDraft": False,
            "mergedAt": "2024-01-15T10:00:00Z"
        })

        with patch("subprocess.run", return_value=mock_result), \
             patch("subprocess.Popen"):
            result = pr_sync.sync_from_github(tmp_pm_root_github, save_state=False)

        # pr-003 has no gh_pr_number, should not appear in results
        assert "pr-003" not in result.merged_prs
        assert "pr-003" not in result.closed_prs

    def test_sync_from_github_handles_api_errors(self, tmp_pm_root_github):
        """sync_from_github handles GitHub API errors gracefully."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            result = pr_sync.sync_from_github(tmp_pm_root_github, save_state=False)

        # Should still return synced=True but with no updates
        assert result.synced is True
        assert result.updated_count == 0
