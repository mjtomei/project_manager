"""Review-id → directory and per-review file path resolution.

Everything lives under ``<root>/docs/adversarial-review/`` where ``root`` is
the pm directory (the dir returned by :func:`pm_core.store.find_project_root`,
i.e. ``pm/``).  Per-review cycle files live in a per-id subdirectory under
``reviews/`` so filenames need no artifact suffix — the directory disambiguates.
The three methodology docs sit at the top level, shared across all reviews.
"""

from pathlib import Path

# Relative to the pm root.
ADVERSARIAL_ROOT = "docs/adversarial-review"
REVIEWS_SUBDIR = f"{ADVERSARIAL_ROOT}/reviews"

# Shared, top-level methodology files (concatenated into the session context).
METHODOLOGY_FILE = f"{ADVERSARIAL_ROOT}/METHODOLOGY.md"
CITATION_USE_AUDIT_FILE = f"{ADVERSARIAL_ROOT}/CITATION_USE_AUDIT.md"
CITATION_CRAWL_FILE = f"{ADVERSARIAL_ROOT}/CITATION_CRAWL.md"


def reviews_root(root: Path) -> Path:
    """Return the directory holding all per-review subdirectories."""
    return root / REVIEWS_SUBDIR


def dir_for(root: Path, review_id: str, *, create: bool = True) -> Path:
    """Return the per-review directory, creating it on first access."""
    d = reviews_root(root) / review_id
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def state_path(root: Path, review_id: str, *, create: bool = True) -> Path:
    """Path to the review's ``STATE.md``."""
    return dir_for(root, review_id, create=create) / "STATE.md"


def focus_path(root: Path, review_id: str, *, create: bool = True) -> Path:
    """Path to the review's ``UI_FOCUS.md``."""
    return dir_for(root, review_id, create=create) / "UI_FOCUS.md"


def notes_path(root: Path, review_id: str, *, create: bool = True) -> Path:
    """Path to the review's ``NOTES.md``."""
    return dir_for(root, review_id, create=create) / "NOTES.md"


def cycle_paths(root: Path, review_id: str, n: int, *, create: bool = True) -> dict[str, Path]:
    """Return the three per-cycle file paths for cycle ``n``.

    Keys: ``review`` / ``audit`` / ``response`` → the cycle's review,
    citation-audit, and review-response markdown files.
    """
    d = dir_for(root, review_id, create=create)
    return {
        "review": d / f"REVIEW_CYCLE_{n}.md",
        "audit": d / f"CITATION_AUDIT_CYCLE_{n}.md",
        "response": d / f"REVIEW_RESPONSE_CYCLE_{n}.md",
    }


def methodology_paths(root: Path) -> list[Path]:
    """Return the shared methodology files, in context order.

    Files that don't exist yet are still returned — the context loader skips
    missing ones with a note.
    """
    return [
        root / METHODOLOGY_FILE,
        root / CITATION_USE_AUDIT_FILE,
        root / CITATION_CRAWL_FILE,
    ]
