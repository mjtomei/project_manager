"""Utility functions for PR entries: status validation and snapshot hygiene."""

from typing import Literal

PRStatus = Literal["pending", "in_progress", "in_review", "qa", "sign_off", "merged", "closed"]

VALID_PR_STATES = {"pending", "in_progress", "in_review", "qa", "sign_off", "merged", "closed"}

# Statuses that end a PR's lifecycle.  A ``merged``/``closed`` record is
# history: it is never moved back to an active status by a GitHub sync (a
# merge *discovered* on GitHub still finalizes), never auto-started, and it
# never satisfies a dependent's ``depends_on`` (only ``merged`` does).
# ``pm pr close`` retains the entry (pr-62ad13d), so the distinction between
# "closed on GitHub" and "closed locally" no longer exists.
TERMINAL_PR_STATES = ("merged", "closed")


def usable_prs(prs) -> list[dict]:
    """Return the PR entries that carry a usable, non-empty string ``id``.

    A partial or externally written project.yaml can hold a PR mapping with
    a status but no ``id`` (or a non-string one).  Everything that indexes
    PRs by id — the dependency graph, the TUI tree, and the sync loops —
    must skip those entries rather than raise ``KeyError: 'id'``; the popup
    picker rejects such a snapshot outright with a readable reason.
    """
    return [pr for pr in (prs or [])
            if isinstance(pr, dict)
            and isinstance(pr.get("id"), str)
            and pr["id"]]


def is_valid_pr_status(status: str) -> bool:
    """Check if a PR status string is valid."""
    return status in VALID_PR_STATES


def normalize_pr_status(status: str) -> PRStatus:
    """Normalize a PR status string, raising ValueError if invalid."""
    if status not in VALID_PR_STATES:
        valid_states = ", ".join(sorted(VALID_PR_STATES))
        raise ValueError(f"Invalid PR status: '{status}'. Must be one of: {valid_states}")
    return status  # type: ignore
