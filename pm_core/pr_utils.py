"""Utility functions for PR status validation."""

from typing import Literal

PRStatus = Literal["pending", "in_progress", "in_review", "merged"]

VALID_PR_STATES = {"pending", "in_progress", "in_review", "merged"}


def is_valid_pr_status(status: str) -> bool:
    """
    Check if a PR status string is valid.

    Args:
        status: The status string to validate

    Returns:
        True if the status is one of the valid PR states, False otherwise

    Examples:
        >>> is_valid_pr_status("pending")
        True
        >>> is_valid_pr_status("invalid")
        False
    """
    return status in VALID_PR_STATES


def normalize_pr_status(status: str) -> PRStatus:
    """
    Normalize a PR status string, raising ValueError if invalid.

    Args:
        status: The status string to normalize

    Returns:
        The normalized status

    Raises:
        ValueError: If the status is not valid

    Examples:
        >>> normalize_pr_status("pending")
        'pending'
        >>> normalize_pr_status("invalid")
        Traceback (most recent call last):
        ...
        ValueError: Invalid PR status: 'invalid'. Must be one of: pending, in_progress, in_review, merged
    """
    if status not in VALID_PR_STATES:
        valid_states = ", ".join(sorted(VALID_PR_STATES))
        raise ValueError(f"Invalid PR status: '{status}'. Must be one of: {valid_states}")
    return status  # type: ignore
