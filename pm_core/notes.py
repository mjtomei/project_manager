"""Notes file management for pm sessions.

Notes are split into sections that target different prompts:

Committed sections (tracked in git, in notes.txt):
  - General: included in all prompts
  - Implementation: included only in implementation prompts
  - Review: included only in review prompts
  - Merge: included only in merge prompts
  - Watcher: included only in watcher prompts

Local section (gitignored, in notes-local.txt):
  - Local: included in all prompts, not committed
"""

from pathlib import Path
import re

NOTES_FILENAME = "notes.txt"
LOCAL_NOTES_FILENAME = "notes-local.txt"

COMMITTED_SECTIONS = ("General", "Implementation", "Review", "Merge", "Watcher")
ALL_SECTIONS = (*COMMITTED_SECTIONS, "Local")

# Which sections are included in each prompt type.
PROMPT_SECTIONS: dict[str, tuple[str, ...]] = {
    "impl": ("General", "Implementation", "Local"),
    "review": ("General", "Review", "Local"),
    "merge": ("General", "Merge", "Local"),
    "watcher": ("General", "Watcher", "Local"),
}

# Descriptions shown in the edit template header lines.
_SECTION_DESCS: dict[str, str] = {
    "General": "included in all prompts",
    "Implementation": "implementation prompts only",
    "Review": "review prompts only",
    "Merge": "merge prompts only",
    "Watcher": "watcher prompts only",
    "Local": "all prompts — gitignored, stays on your machine",
}

# Regex matching a section header line (e.g. "## General" or "## General — desc").
_SECTION_RE = re.compile(
    r"^##\s+(" + "|".join(ALL_SECTIONS) + r")\b",
    re.IGNORECASE,
)

NOTES_HEADER = """\
Notes
=====

Your scratchpad. Jot down anything useful as you work — context,
decisions, things to remember. Notes are included in prompts
pm sends to Claude, so anything you write here becomes shared context.

Committed notes are shared with the team; local notes stay on your machine.
"""

# Vim-style welcome content shown before opening the editor.
NOTES_WELCOME = """\
~
~
~
~           Notes
~
~           Your scratchpad — jot down anything useful as you work.
~           Notes are organized into sections that target different prompts.
~
~               ## General        — included in all prompts (committed)
~               ## Implementation — implementation prompts only
~               ## Review         — review prompts only
~               ## Merge          — merge prompts only
~               ## Watcher        — watcher prompts only
~               ## Local          — all prompts (gitignored)
~
~           Press any key to start editing.
~
~
~
"""


# ---------------------------------------------------------------------------
# File management
# ---------------------------------------------------------------------------

def ensure_notes_file(root: Path) -> Path:
    """Create notes files if they don't exist and fix gitignore.

    Returns the committed notes path.
    """
    _migrate_old_format(root)

    path = root / NOTES_FILENAME
    if not path.exists():
        path.write_text("")

    local_path = root / LOCAL_NOTES_FILENAME
    if not local_path.exists():
        local_path.write_text("")

    _update_gitignore(root)
    return path


def _update_gitignore(root: Path) -> None:
    """Ensure gitignore has the right entries.

    notes-local.txt and .no-notes-splash should be ignored.
    notes.txt should NOT be ignored (it's committed now).
    """
    gitignore = root / ".gitignore"
    content = gitignore.read_text() if gitignore.exists() else ""
    lines = content.splitlines()

    # Remove notes.txt from gitignore (was gitignored in old format)
    new_lines = [l for l in lines if l.strip() != NOTES_FILENAME]

    # Add entries that should be gitignored
    entries_to_ignore = [LOCAL_NOTES_FILENAME, ".no-notes-splash"]
    existing = "\n".join(new_lines)
    for entry in entries_to_ignore:
        if entry not in existing:
            new_lines.append(entry)

    new_content = "\n".join(new_lines)
    if new_content and not new_content.endswith("\n"):
        new_content += "\n"
    if not new_content:
        new_content = ""

    if new_content != content:
        gitignore.write_text(new_content)


def _migrate_old_format(root: Path) -> None:
    """Migrate old single-file gitignored notes to the new section format.

    If notes.txt exists with content but no section headers, it's the old
    format.  Move its content to notes-local.txt (preserving the local,
    gitignored nature of the old file) and clear notes.txt.
    """
    path = root / NOTES_FILENAME
    if not path.exists():
        return

    content = path.read_text()
    if not content.strip():
        return

    # Already has section headers → new format, no migration needed
    if _SECTION_RE.search(content):
        return

    # Old format — move content to local notes
    local_path = root / LOCAL_NOTES_FILENAME
    if not local_path.exists() or not local_path.read_text().strip():
        local_path.write_text(content)

    # Clear committed file for new section format
    path.write_text("")


# ---------------------------------------------------------------------------
# Section loading / saving
# ---------------------------------------------------------------------------

def load_sections(root: Path) -> dict[str, str]:
    """Load all note sections from their backing files.

    Returns a dict mapping section name → content string (may be empty).
    """
    sections: dict[str, str] = {s: "" for s in ALL_SECTIONS}

    # Parse committed file for section content
    path = root / NOTES_FILENAME
    if path.exists():
        parsed = _parse_sections(path.read_text())
        for s in COMMITTED_SECTIONS:
            if s in parsed:
                sections[s] = parsed[s]

    # Local section comes from its own file
    local_path = root / LOCAL_NOTES_FILENAME
    if local_path.exists():
        sections["Local"] = local_path.read_text().strip()

    return sections


def save_sections(root: Path, sections: dict[str, str]) -> None:
    """Write sections back to their respective backing files."""
    # Build committed file with all section headers
    parts = []
    for s in COMMITTED_SECTIONS:
        content = sections.get(s, "").strip()
        if content:
            parts.append(f"## {s}\n\n{content}")
        else:
            parts.append(f"## {s}")

    (root / NOTES_FILENAME).write_text("\n\n".join(parts) + "\n")

    # Local section
    local_content = sections.get("Local", "").strip()
    (root / LOCAL_NOTES_FILENAME).write_text(
        local_content + "\n" if local_content else ""
    )


# ---------------------------------------------------------------------------
# Edit template (composite view for the editor)
# ---------------------------------------------------------------------------

def build_edit_template(root: Path) -> str:
    """Build a composite template for editing all sections at once."""
    sections = load_sections(root)
    parts = []
    for s in ALL_SECTIONS:
        desc = _SECTION_DESCS[s]
        content = sections.get(s, "").strip()
        header = f"## {s} — {desc}"
        if content:
            parts.append(f"{header}\n\n{content}")
        else:
            parts.append(header)
    return "\n\n".join(parts) + "\n"


def parse_edit_template(text: str) -> dict[str, str]:
    """Parse an edited template back into a section dict."""
    sections: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []

    for line in text.splitlines():
        m = _SECTION_RE.match(line)
        if m:
            if current is not None:
                sections[current] = "\n".join(lines).strip()
            # Normalize to canonical case
            raw = m.group(1)
            current = next(
                (s for s in ALL_SECTIONS if s.lower() == raw.lower()), raw
            )
            lines = []
        elif current is not None:
            lines.append(line)

    if current is not None:
        sections[current] = "\n".join(lines).strip()

    return sections


def _parse_sections(text: str) -> dict[str, str]:
    """Parse section-formatted text into a dict."""
    return parse_edit_template(text)


# ---------------------------------------------------------------------------
# Prompt integration
# ---------------------------------------------------------------------------

def load_notes(root: Path) -> str:
    """Read combined notes content (all sections).  Backwards-compatible."""
    sections = load_sections(root)
    parts = [
        sections[s].strip()
        for s in ALL_SECTIONS
        if sections.get(s, "").strip()
    ]
    return "\n\n".join(parts)


def notes_section(root: Path, prompt_type: str | None = None) -> str:
    """Return a formatted notes block for inclusion in a prompt.

    Args:
        root: The pm root directory.
        prompt_type: One of ``"impl"``, ``"review"``, ``"merge"``,
            ``"watcher"``.  If *None*, all sections are included.

    Returns empty string if no relevant notes exist.
    """
    sections = load_sections(root)

    if prompt_type and prompt_type in PROMPT_SECTIONS:
        included = PROMPT_SECTIONS[prompt_type]
    else:
        included = ALL_SECTIONS

    parts = [
        sections[s].strip()
        for s in included
        if sections.get(s, "").strip()
    ]
    if not parts:
        return ""

    combined = "\n\n".join(parts)
    return f"\n## Session Notes\n{combined}\n"
