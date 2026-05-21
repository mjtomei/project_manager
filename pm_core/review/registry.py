"""Read/write the ``reviews:`` list in ``project.yaml``.

Reviews are first-class entities alongside plans and PRs.  Each entry registers
a review against a target; the dynamic cycle state lives in the review's
``STATE.md`` (see :mod:`pm_core.review.paths`), not here.

All writes go through :func:`pm_core.store.locked_update`, which load-modifies-
saves the whole document, so other top-level keys (``project``, ``plans``,
``prs``) are preserved untouched.
"""

from pathlib import Path

from pm_core import store

VALID_TARGET_TYPES = {"plan", "file", "topic"}
VALID_STATUSES = {"active", "archived"}


def make_review_entry(review_id: str, target: str, target_type: str,
                      *, status: str = "active") -> dict:
    """Create a standard review entry dict with all required keys."""
    return {
        "id": review_id,
        "target": target,
        "target-type": target_type,
        "status": status,
    }


def get_review(data: dict, review_id: str) -> dict | None:
    """Return the review entry with ``review_id`` from loaded data, or None."""
    for review in data.get("reviews") or []:
        if review.get("id") == review_id:
            return review
    return None


def create_review(root: Path, review_id: str, target: str,
                  target_type: str) -> dict:
    """Append a new active review entry to ``project.yaml`` and return it.

    Idempotent on id: if an entry with ``review_id`` already exists it is
    returned unchanged rather than duplicated.
    """
    entry = make_review_entry(review_id, target, target_type)

    def apply(data):
        if data.get("reviews") is None:
            data["reviews"] = []
        if any(r.get("id") == review_id for r in data["reviews"]):
            return
        data["reviews"].append(entry)

    data = store.locked_update(root, apply)
    return get_review(data, review_id) or entry


def set_status(root: Path, review_id: str, status: str) -> None:
    """Set a review entry's ``status`` (``active`` | ``archived``)."""
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid review status: {status!r}")

    def apply(data):
        for review in data.get("reviews") or []:
            if review.get("id") == review_id:
                review["status"] = status
                return

    store.locked_update(root, apply)


def list_active(root: Path) -> list[dict]:
    """Return all reviews with ``status == 'active'``."""
    data = store.load(root)
    return [r for r in (data.get("reviews") or []) if r.get("status") == "active"]
