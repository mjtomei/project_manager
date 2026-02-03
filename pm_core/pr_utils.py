"""Utility functions for PR status validation."""

from typing import Literal

PRStatus = Literal["pending", "in_progress", "in_review", "merged", "closed"]

VALID_PR_STATES = {"pending", "in_progress", "in_review", "merged", "closed"}


def is_valid_pr_status(status: str) -> bool:
    """Check if a PR status string is valid."""
    return status in VALID_PR_STATES


def normalize_pr_status(status: str) -> PRStatus:
    """Normalize a PR status string, raising ValueError if invalid."""
    if status not in VALID_PR_STATES:
        valid_states = ", ".join(sorted(VALID_PR_STATES))
        raise ValueError(f"Invalid PR status: '{status}'. Must be one of: {valid_states}")
    return status  # type: ignore
