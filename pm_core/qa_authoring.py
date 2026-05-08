"""Guided authoring helpers for QA library files.

Loads the packaged qa_library.md doc and wraps it into a Claude prompt
that interviews the user to draft a new instruction or artifact recipe.
"""

from pathlib import Path


_DOC_PATH = Path(__file__).parent / "docs" / "qa_library.md"


def qa_library_doc() -> str:
    """Return the packaged QA library reference doc as a string."""
    return _DOC_PATH.read_text()


_CATEGORY_BLURB = {
    "instructions": (
        "A QA instruction is a reusable procedure referenced by QA "
        "scenarios or implementation sessions."
    ),
    "artifacts": (
        "An artifact recipe is a procedure for capturing concrete "
        "evidence of behavior — recordings, logs, screenshots — "
        "consumable by humans (replay/read) and downstream agents "
        "(parse/diff)."
    ),
}


def build_authoring_prompt(name: str, category: str, target_path: Path) -> str:
    """Build a Claude prompt that interviews the user to draft a new file.

    *category* is "instructions" or "artifacts". *target_path* is the
    file the session should ultimately write.
    """
    if category not in ("instructions", "artifacts"):
        raise ValueError(f"unsupported category: {category}")

    label = "QA instruction" if category == "instructions" else "artifact recipe"
    blurb = _CATEGORY_BLURB[category]
    doc = qa_library_doc()

    return f"""Work with the user to author a new {label} for the pm QA
library at:

    {target_path}

{blurb}

The reference document below is the ground truth for the schema and
conventions. Existing files in the same directory are good style
references. Use your judgment on how to interview the user, what to
draft, and when to write the file.

## Reference: pm QA library

{doc}
"""
