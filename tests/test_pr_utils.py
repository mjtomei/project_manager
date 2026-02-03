"""Tests for PR utilities module."""

import pytest

from pm_core.pr_utils import (
    PRStatus,
    VALID_PR_STATES,
    is_valid_pr_status,
    normalize_pr_status,
)


class TestValidPRStates:
    """Tests for VALID_PR_STATES constant."""

    def test_contains_pending(self):
        """VALID_PR_STATES includes pending."""
        assert "pending" in VALID_PR_STATES

    def test_contains_in_progress(self):
        """VALID_PR_STATES includes in_progress."""
        assert "in_progress" in VALID_PR_STATES

    def test_contains_in_review(self):
        """VALID_PR_STATES includes in_review."""
        assert "in_review" in VALID_PR_STATES

    def test_contains_merged(self):
        """VALID_PR_STATES includes merged."""
        assert "merged" in VALID_PR_STATES

    def test_contains_closed(self):
        """VALID_PR_STATES includes closed."""
        assert "closed" in VALID_PR_STATES

    def test_has_exactly_five_states(self):
        """VALID_PR_STATES has exactly 5 states."""
        assert len(VALID_PR_STATES) == 5


class TestIsValidPRStatus:
    """Tests for is_valid_pr_status function."""

    def test_valid_statuses(self):
        """is_valid_pr_status returns True for valid statuses."""
        for status in VALID_PR_STATES:
            assert is_valid_pr_status(status) is True

    def test_invalid_status(self):
        """is_valid_pr_status returns False for invalid statuses."""
        assert is_valid_pr_status("invalid") is False
        assert is_valid_pr_status("done") is False
        assert is_valid_pr_status("open") is False
        assert is_valid_pr_status("") is False

    def test_case_sensitive(self):
        """is_valid_pr_status is case sensitive."""
        assert is_valid_pr_status("PENDING") is False
        assert is_valid_pr_status("Merged") is False
        assert is_valid_pr_status("IN_PROGRESS") is False


class TestNormalizePRStatus:
    """Tests for normalize_pr_status function."""

    def test_valid_statuses_returned_unchanged(self):
        """normalize_pr_status returns valid statuses unchanged."""
        for status in VALID_PR_STATES:
            assert normalize_pr_status(status) == status

    def test_invalid_status_raises_valueerror(self):
        """normalize_pr_status raises ValueError for invalid status."""
        with pytest.raises(ValueError) as exc_info:
            normalize_pr_status("invalid")

        assert "Invalid PR status" in str(exc_info.value)
        assert "invalid" in str(exc_info.value)

    def test_error_message_includes_valid_states(self):
        """normalize_pr_status error message includes valid states."""
        with pytest.raises(ValueError) as exc_info:
            normalize_pr_status("bad_status")

        error_msg = str(exc_info.value)
        assert "pending" in error_msg or "merged" in error_msg
