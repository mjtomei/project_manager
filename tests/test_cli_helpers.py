"""Tests for pm_core.cli.helpers — shared CLI utility functions."""

from unittest.mock import patch

import pytest

from pm_core.cli.helpers import (
    _infer_pr_id,
    _pr_display_id,
    _pr_id_sort_key,
    _resolve_pr_id,
)


# ---------------------------------------------------------------------------
# _resolve_pr_id
# ---------------------------------------------------------------------------


class TestResolvePrId:
    """Tests for _resolve_pr_id (resolve by pm ID or GitHub PR number)."""

    @pytest.fixture()
    def data(self):
        return {
            "prs": [
                {"id": "pr-001", "title": "First", "gh_pr_number": 42},
                {"id": "pr-002", "title": "Second"},
                {"id": "pr-a3f2b1c", "title": "Hash ID", "gh_pr_number": 99},
            ]
        }

    def test_resolve_by_exact_pm_id(self, data):
        pr = _resolve_pr_id(data, "pr-001")
        assert pr is not None
        assert pr["id"] == "pr-001"

    def test_resolve_by_pm_id_not_found(self, data):
        assert _resolve_pr_id(data, "pr-999") is None

    def test_resolve_by_github_number(self, data):
        pr = _resolve_pr_id(data, "42")
        assert pr is not None
        assert pr["id"] == "pr-001"

    def test_resolve_by_github_number_not_found(self, data):
        assert _resolve_pr_id(data, "123") is None

    def test_resolve_hash_id(self, data):
        pr = _resolve_pr_id(data, "pr-a3f2b1c")
        assert pr is not None
        assert pr["title"] == "Hash ID"

    def test_resolve_invalid_string(self, data):
        assert _resolve_pr_id(data, "not-a-pr") is None

    def test_resolve_empty_prs(self):
        assert _resolve_pr_id({"prs": []}, "pr-001") is None

    def test_resolve_no_prs_key(self):
        assert _resolve_pr_id({}, "42") is None

    def test_resolve_pr_without_gh_number(self, data):
        """PR pr-002 has no gh_pr_number; resolving by number skips it."""
        pr = _resolve_pr_id(data, "99")
        assert pr is not None
        assert pr["id"] == "pr-a3f2b1c"


# ---------------------------------------------------------------------------
# _infer_pr_id
# ---------------------------------------------------------------------------


class TestInferPrId:
    """Tests for _infer_pr_id (infer PR from context)."""

    @pytest.fixture()
    def data(self):
        return {
            "project": {"active_pr": "pr-002"},
            "prs": [
                {"id": "pr-001", "status": "merged", "workdir": "/tmp/wd1"},
                {"id": "pr-002", "status": "in_progress", "workdir": "/tmp/wd2"},
                {"id": "pr-003", "status": "pending"},
            ],
        }

    def test_infer_from_active_pr(self, data):
        """If there's an active PR it should be returned (no status filter)."""
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = "/some/other/dir"
            result = _infer_pr_id(data)
        assert result == "pr-002"

    def test_infer_from_active_pr_with_matching_filter(self, data):
        """Active PR returned when it matches the status filter."""
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = "/some/other/dir"
            result = _infer_pr_id(data, status_filter=("in_progress",))
        assert result == "pr-002"

    def test_infer_from_active_pr_with_nonmatching_filter(self, data):
        """Active PR skipped when it doesn't match the status filter."""
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = "/some/other/dir"
            result = _infer_pr_id(data, status_filter=("pending",))
        # Falls through to single-match: only pr-003 is pending
        assert result == "pr-003"

    def test_infer_from_workdir(self, data, tmp_path):
        """If cwd is inside a PR's workdir, that PR is returned."""
        wd = tmp_path / "wd"
        wd.mkdir()
        data["prs"][0]["workdir"] = str(wd)
        subdir = wd / "src"
        subdir.mkdir()
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = str(subdir)
            mock_path.return_value.resolve.return_value = wd.resolve()
            result = _infer_pr_id(data)
        assert result == "pr-001"

    def test_infer_no_active_no_filter(self, data):
        """No active PR and no status filter returns None when multiple PRs exist."""
        data["project"]["active_pr"] = None
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = "/some/other/dir"
            result = _infer_pr_id(data)
        assert result is None

    def test_infer_single_match_on_filter(self, data):
        """When exactly one PR matches the status filter, return it."""
        data["project"]["active_pr"] = None
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = "/some/other/dir"
            result = _infer_pr_id(data, status_filter=("merged",))
        assert result == "pr-001"

    def test_infer_multiple_matches_returns_none(self, data):
        """When multiple PRs match the filter, return None."""
        data["prs"][2]["status"] = "in_progress"
        data["project"]["active_pr"] = None
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = "/some/other/dir"
            result = _infer_pr_id(data, status_filter=("in_progress",))
        assert result is None

    def test_infer_empty_prs(self):
        """With no PRs, returns None."""
        with patch("pm_core.cli.helpers.Path") as mock_path:
            mock_path.cwd.return_value.resolve.return_value = "/some/other/dir"
            result = _infer_pr_id({"prs": [], "project": {}})
        assert result is None


# ---------------------------------------------------------------------------
# _pr_id_sort_key
# ---------------------------------------------------------------------------


class TestPrIdSortKey:
    """Tests for _pr_id_sort_key (sort PR IDs numerically)."""

    def test_numeric_id(self):
        assert _pr_id_sort_key("pr-001") == (1, "")
        assert _pr_id_sort_key("pr-42") == (42, "")

    def test_hash_id(self):
        assert _pr_id_sort_key("pr-a3f2b1c") == (0, "a3f2b1c")

    def test_sorting_order(self):
        ids = ["pr-003", "pr-a3f2b1c", "pr-001", "pr-010"]
        sorted_ids = sorted(ids, key=_pr_id_sort_key)
        assert sorted_ids == ["pr-a3f2b1c", "pr-001", "pr-003", "pr-010"]

    def test_bare_id(self):
        assert _pr_id_sort_key("something") == (0, "something")


# ---------------------------------------------------------------------------
# _pr_display_id
# ---------------------------------------------------------------------------


class TestPrDisplayId:
    """Tests for _pr_display_id (prefer GitHub #N, fall back to local ID)."""

    def test_with_gh_number(self):
        assert _pr_display_id({"id": "pr-001", "gh_pr_number": 42}) == "#42"

    def test_without_gh_number(self):
        assert _pr_display_id({"id": "pr-001"}) == "pr-001"

    def test_with_none_gh_number(self):
        assert _pr_display_id({"id": "pr-002", "gh_pr_number": None}) == "pr-002"
