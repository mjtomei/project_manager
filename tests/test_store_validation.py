"""Tests for store module validation functionality."""

import pytest

from pm_core import store
from pm_core.pr_utils import VALID_PR_STATES


@pytest.fixture
def tmp_pm_root(tmp_path):
    """Create a temporary PM root directory."""
    root = tmp_path / "pm"
    root.mkdir()
    return root


class TestValidatePRStatuses:
    """Tests for PR status validation on load."""

    def test_valid_statuses_unchanged(self, tmp_pm_root):
        """Valid PR statuses are not modified on load."""
        (tmp_pm_root / "project.yaml").write_text(
            "project:\n"
            "  name: test\n"
            "  repo: /tmp/repo\n"
            "  base_branch: master\n"
            "prs:\n"
            "  - id: pr-001\n"
            "    status: pending\n"
            "  - id: pr-002\n"
            "    status: in_progress\n"
            "  - id: pr-003\n"
            "    status: in_review\n"
            "  - id: pr-004\n"
            "    status: merged\n"
            "  - id: pr-005\n"
            "    status: closed\n"
        )

        data = store.load(tmp_pm_root)

        statuses = {pr["id"]: pr["status"] for pr in data["prs"]}
        assert statuses["pr-001"] == "pending"
        assert statuses["pr-002"] == "in_progress"
        assert statuses["pr-003"] == "in_review"
        assert statuses["pr-004"] == "merged"
        assert statuses["pr-005"] == "closed"

    def test_invalid_status_normalized_to_pending(self, tmp_pm_root):
        """Invalid PR status is normalized to 'pending' on load."""
        (tmp_pm_root / "project.yaml").write_text(
            "project:\n"
            "  name: test\n"
            "  repo: /tmp/repo\n"
            "  base_branch: master\n"
            "prs:\n"
            "  - id: pr-001\n"
            "    status: invalid_status\n"
            "  - id: pr-002\n"
            "    status: done\n"
            "  - id: pr-003\n"
            "    status: open\n"
        )

        data = store.load(tmp_pm_root)

        for pr in data["prs"]:
            assert pr["status"] == "pending"

    def test_missing_status_normalized_to_pending(self, tmp_pm_root):
        """PR with missing status is normalized to 'pending' on load."""
        (tmp_pm_root / "project.yaml").write_text(
            "project:\n"
            "  name: test\n"
            "  repo: /tmp/repo\n"
            "  base_branch: master\n"
            "prs:\n"
            "  - id: pr-001\n"
            "    title: No status PR\n"
        )

        data = store.load(tmp_pm_root)

        # Missing status should be treated as invalid and normalized
        pr = data["prs"][0]
        assert pr.get("status") == "pending"

    def test_validation_can_be_disabled(self, tmp_pm_root):
        """Validation can be disabled via validate=False parameter."""
        (tmp_pm_root / "project.yaml").write_text(
            "project:\n"
            "  name: test\n"
            "  repo: /tmp/repo\n"
            "  base_branch: master\n"
            "prs:\n"
            "  - id: pr-001\n"
            "    status: invalid_status\n"
        )

        data = store.load(tmp_pm_root, validate=False)

        # Status should remain unchanged when validation disabled
        assert data["prs"][0]["status"] == "invalid_status"

    def test_empty_prs_list_no_error(self, tmp_pm_root):
        """Empty PRs list does not cause validation error."""
        (tmp_pm_root / "project.yaml").write_text(
            "project:\n"
            "  name: test\n"
            "  repo: /tmp/repo\n"
            "  base_branch: master\n"
            "prs: []\n"
        )

        data = store.load(tmp_pm_root)

        assert data["prs"] == []

    def test_null_prs_no_error(self, tmp_pm_root):
        """Null PRs value does not cause validation error."""
        (tmp_pm_root / "project.yaml").write_text(
            "project:\n"
            "  name: test\n"
            "  repo: /tmp/repo\n"
            "  base_branch: master\n"
            "prs: null\n"
        )

        data = store.load(tmp_pm_root)

        assert data["prs"] is None


class TestTimestampBackfill:
    """Tests for created_at/updated_at backfill on load."""

    def test_backfill_from_started_at(self, tmp_pm_root):
        """PRs without created_at/updated_at get backfilled from started_at."""
        (tmp_pm_root / "project.yaml").write_text(
            "project:\n"
            "  name: test\n"
            "  repo: /tmp/repo\n"
            "  base_branch: master\n"
            "prs:\n"
            "  - id: pr-001\n"
            "    status: in_progress\n"
            "    started_at: '2024-03-01T00:00:00+00:00'\n"
        )

        data = store.load(tmp_pm_root)
        pr = data["prs"][0]

        assert pr["created_at"] == "2024-03-01T00:00:00+00:00"
        assert pr["updated_at"] == "2024-03-01T00:00:00+00:00"

    def test_backfill_updated_at_prefers_merged(self, tmp_pm_root):
        """updated_at backfill picks merged_at (most recent lifecycle event)."""
        (tmp_pm_root / "project.yaml").write_text(
            "project:\n"
            "  name: test\n"
            "  repo: /tmp/repo\n"
            "  base_branch: master\n"
            "prs:\n"
            "  - id: pr-001\n"
            "    status: merged\n"
            "    started_at: '2024-01-01T00:00:00+00:00'\n"
            "    reviewed_at: '2024-02-01T00:00:00+00:00'\n"
            "    merged_at: '2024-03-01T00:00:00+00:00'\n"
        )

        data = store.load(tmp_pm_root)
        pr = data["prs"][0]

        assert pr["updated_at"] == "2024-03-01T00:00:00+00:00"

    def test_backfill_created_at_prefers_started(self, tmp_pm_root):
        """created_at backfill picks started_at (earliest lifecycle event)."""
        (tmp_pm_root / "project.yaml").write_text(
            "project:\n"
            "  name: test\n"
            "  repo: /tmp/repo\n"
            "  base_branch: master\n"
            "prs:\n"
            "  - id: pr-001\n"
            "    status: merged\n"
            "    started_at: '2024-01-01T00:00:00+00:00'\n"
            "    reviewed_at: '2024-02-01T00:00:00+00:00'\n"
            "    merged_at: '2024-03-01T00:00:00+00:00'\n"
        )

        data = store.load(tmp_pm_root)
        pr = data["prs"][0]

        assert pr["created_at"] == "2024-01-01T00:00:00+00:00"

    def test_no_backfill_when_fields_exist(self, tmp_pm_root):
        """Existing created_at/updated_at are not overwritten."""
        (tmp_pm_root / "project.yaml").write_text(
            "project:\n"
            "  name: test\n"
            "  repo: /tmp/repo\n"
            "  base_branch: master\n"
            "prs:\n"
            "  - id: pr-001\n"
            "    status: in_progress\n"
            "    created_at: '2024-01-01T00:00:00+00:00'\n"
            "    updated_at: '2024-06-01T00:00:00+00:00'\n"
            "    started_at: '2024-03-01T00:00:00+00:00'\n"
        )

        data = store.load(tmp_pm_root)
        pr = data["prs"][0]

        assert pr["created_at"] == "2024-01-01T00:00:00+00:00"
        assert pr["updated_at"] == "2024-06-01T00:00:00+00:00"

    def test_no_timestamps_stays_none(self, tmp_pm_root):
        """PRs with no timestamps at all get None (not crash)."""
        (tmp_pm_root / "project.yaml").write_text(
            "project:\n"
            "  name: test\n"
            "  repo: /tmp/repo\n"
            "  base_branch: master\n"
            "prs:\n"
            "  - id: pr-001\n"
            "    status: pending\n"
        )

        data = store.load(tmp_pm_root)
        pr = data["prs"][0]

        assert pr["created_at"] is None
        assert pr["updated_at"] is None
