"""Guided authoring helpers for QA library files.

Loads the packaged qa_library.md doc and wraps it into a Claude prompt
that interviews the user to draft a new instruction or artifact recipe.
"""

from pathlib import Path


_DOC_PATH = Path(__file__).parent / "docs" / "qa_library.md"


def qa_library_doc() -> str:
    """Return the packaged QA library reference doc as a string."""
    return _DOC_PATH.read_text()


def build_authoring_prompt(name: str, category: str, target_path: Path) -> str:
    """Build a Claude prompt that interviews the user to draft a new file.

    *category* is "instructions" or "artifacts". *target_path* is the
    file the session should ultimately write.
    """
    if category not in ("instructions", "artifacts"):
        raise ValueError(f"unsupported category: {category}")

    label = "QA instruction" if category == "instructions" else "artifact recipe"
    doc = qa_library_doc()

    return f"""You are helping the user author a new {label} for the pm QA
library. The file should be written to:

    {target_path}

Use the reference document below as ground truth for the schema, where
each field surfaces, and the conventions for {category}/. Look at
existing files in the same directory (or close ones) for style.

## Your job

1. Ask the user a few short, targeted questions to learn what this
   {label} is for. At minimum:
   - One-line `description` (≤ 80 chars).
   - The shape of the body (Setup / Test Steps / etc. for instructions;
     When to use / What this recipe produces / Capture / Manifest format
     for artifacts).
   - Any tags worth setting.
2. Draft the file content with frontmatter + body. Show it to the user
   and let them iterate.
3. When the user confirms, write the file at the target path.
4. Mention that they can re-open it later with
   `pm qa edit {name.lower().replace(" ", "-")}`.

Keep questions short. One at a time. Don't lecture; do show working
drafts.

## Reference: pm QA library

{doc}
"""
