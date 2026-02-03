"""Tests for PR utility functions."""

import pytest

from pm_core.pr_utils import is_valid_pr_status, normalize_pr_status, VALID_PR_STATES


class TestIsValidPRStatus:
    """Tests for is_valid_pr_status function."""

    def test_valid_pending(self):
        """Test that 'pending' is a valid status."""
        assert is_valid_pr_status("pending") is True

    def test_valid_in_progress(self):
        """Test that 'in_progress' is a valid status."""
        assert is_valid_pr_status("in_progress") is True

    def test_valid_in_review(self):
        """Test that 'in_review' is a valid status."""
        assert is_valid_pr_status("in_review") is True

    def test_valid_merged(self):
        """Test that 'merged' is a valid status."""
        assert is_valid_pr_status("merged") is True

    def test_invalid_status(self):
        """Test that invalid statuses return False."""
        assert is_valid_pr_status("invalid") is False

    def test_empty_string(self):
        """Test that empty string returns False."""
        assert is_valid_pr_status("") is False

    def test_case_sensitive(self):
        """Test that status validation is case-sensitive."""
        assert is_valid_pr_status("Pending") is False
        assert is_valid_pr_status("PENDING") is False
        assert is_valid_pr_status("In_Progress") is False

    def test_whitespace_variations(self):
        """Test that whitespace is not trimmed."""
        assert is_valid_pr_status(" pending") is False
        assert is_valid_pr_status("pending ") is False
        assert is_valid_pr_status(" pending ") is False

    def test_all_valid_states_covered(self):
        """Test that all states in VALID_PR_STATES are actually valid."""
        for state in VALID_PR_STATES:
            assert is_valid_pr_status(state) is True


class TestNormalizePRStatus:
    """Tests for normalize_pr_status function."""

    def test_normalize_valid_pending(self):
        """Test normalizing 'pending' status."""
        assert normalize_pr_status("pending") == "pending"

    def test_normalize_valid_in_progress(self):
        """Test normalizing 'in_progress' status."""
        assert normalize_pr_status("in_progress") == "in_progress"

    def test_normalize_valid_in_review(self):
        """Test normalizing 'in_review' status."""
        assert normalize_pr_status("in_review") == "in_review"

    def test_normalize_valid_merged(self):
        """Test normalizing 'merged' status."""
        assert normalize_pr_status("merged") == "merged"

    def test_normalize_invalid_status_raises_error(self):
        """Test that invalid status raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            normalize_pr_status("invalid")
        assert "Invalid PR status: 'invalid'" in str(exc_info.value)
        assert "Must be one of:" in str(exc_info.value)

    def test_normalize_empty_string_raises_error(self):
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            normalize_pr_status("")
        assert "Invalid PR status: ''" in str(exc_info.value)

    def test_normalize_case_sensitive(self):
        """Test that normalize is case-sensitive and rejects wrong case."""
        with pytest.raises(ValueError):
            normalize_pr_status("Pending")
        with pytest.raises(ValueError):
            normalize_pr_status("MERGED")

    def test_normalize_error_message_includes_all_valid_states(self):
        """Test that error message lists all valid states."""
        with pytest.raises(ValueError) as exc_info:
            normalize_pr_status("invalid")
        error_msg = str(exc_info.value)
        for state in VALID_PR_STATES:
            assert state in error_msg

    def test_normalize_whitespace_raises_error(self):
        """Test that whitespace variations are rejected."""
        with pytest.raises(ValueError):
            normalize_pr_status(" pending")
        with pytest.raises(ValueError):
            normalize_pr_status("pending ")

    def test_normalize_all_valid_states(self):
        """Test that all valid states can be normalized."""
        for state in VALID_PR_STATES:
            result = normalize_pr_status(state)
            assert result == state


class TestValidPRStates:
    """Tests for the VALID_PR_STATES constant."""

    def test_contains_expected_states(self):
        """Test that VALID_PR_STATES contains all expected states."""
        expected = {"pending", "in_progress", "in_review", "merged"}
        assert VALID_PR_STATES == expected

    def test_is_set(self):
        """Test that VALID_PR_STATES is a set for O(1) lookup."""
        assert isinstance(VALID_PR_STATES, set)

    def test_no_duplicate_values(self):
        """Test that there are no duplicates (sets prevent this, but verify)."""
        assert len(VALID_PR_STATES) == 4
