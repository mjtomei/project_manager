"""Notes file management for pm sessions.

Notes are split into sections that target different prompts:

Committed sections (tracked in git, in notes.txt):
  - General: included in all prompts
  - Implementation: included only in implementation prompts
  - Review: included only in review prompts
  - QA: included only in QA prompts
  - Merge: included only in merge prompts
  - Watcher: included only in watcher prompts

Local section (gitignored, in notes-local.txt):
  - Local: included in all prompts, not committed

Architecture document (committed, in architecture.md):
  The project's MIT Axiomatic Design analysis — a living reference that
  plan, implementation and review prompts point sessions at so they reuse the
  existing functional requirements (FRs) and design parameters (DPs) instead
  of re-deriving them.  Free-form markdown; nothing here parses it (pm ships
  zero analyzer code — sessions produce and update it).  Recommended layout,
  top to bottom, so a head+tail prompt excerpt keeps what matters:

    1. Provenance — date, git commit and model the analysis was made with
    2. FRs, and the disjoint DPs that satisfy them (mapped to modules/dirs)
    3. Design Matrix [A] (Level 1, plus key Level-2 matrices), ordered so
       dependencies flow down; a ``*`` above the diagonal is upward coupling
    4. Known coupling debt (cycles, shared state, workarounds + their PRs)
    5. FR/DP change log, newest entry last

  ``ensure_notes_file`` never creates it: whether the file exists is what
  turns the prompt guidance on.
"""

from pathlib import Path
import re

from pm_core import store
from pm_core.prompt_bounds import ARCHITECTURE_BUDGET, bounded_text


NOTES_FILENAME = "notes.txt"
LOCAL_NOTES_FILENAME = "notes-local.txt"

COMMITTED_SECTIONS = ("General", "Implementation", "Review", "QA", "Merge", "Watcher")
ALL_SECTIONS = (*COMMITTED_SECTIONS, "Local")

# Which sections are included in each prompt type.
PROMPT_SECTIONS: dict[str, tuple[str, ...]] = {
    "impl": ("General", "Implementation", "Local"),
    "review": ("General", "Review", "Local"),
    "qa": ("General", "QA", "Local"),
    "merge": ("General", "Merge", "Local"),
    "watcher": ("General", "Watcher", "Local"),
}


# Descriptions shown in the edit template header lines.
_SECTION_DESCS: dict[str, str] = {
    "General": "included in all prompts",
    "Implementation": "additional instructions for implementation sessions",
    "Review": "additional instructions for review sessions",
    "QA": "additional instructions for QA sessions",
    "Merge": "additional instructions for merge sessions",
    "Watcher": "additional instructions for watcher sessions",
    "Local": "included in all prompts — gitignored, stays on your machine",
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
~               ## Implementation — additional instructions for implementation sessions
~               ## Review         — additional instructions for review sessions
~               ## QA             — additional instructions for QA sessions
~               ## Merge          — additional instructions for merge sessions
~               ## Watcher        — additional instructions for watcher sessions
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
    # Session notes are user-authored instructions, so they are inlined whole
    # and never truncated; an over-limit prompt is delivered by the launcher's
    # file-backed bootstrap instead (see pm_core.prompt_bounds).
    return f"\n## Session Notes\n{combined}\n"


# Mapping from prompt_type to the specific section name.
_PROMPT_SPECIFIC: dict[str, str] = {
    "impl": "Implementation",
    "review": "Review",
    "qa": "QA",
    "merge": "Merge",
    "watcher": "Watcher",
}


def notes_for_prompt(root: Path, prompt_type: str) -> tuple[str, str]:
    """Return (general_block, specific_block) for a prompt type.

    *general_block* contains General + Local content, formatted as a
    ``## Session Notes`` section.  *specific_block* contains the
    prompt-specific section (e.g. Review for ``"review"``), framed as
    additional user instructions.

    Each block is an empty string when no relevant content exists.
    """
    sections = load_sections(root)

    # General block: General + Local
    general_parts = [
        sections[s].strip()
        for s in ("General", "Local")
        if sections.get(s, "").strip()
    ]
    general_block = ""
    if general_parts:
        combined = "\n\n".join(general_parts)
        general_block = f"\n## Session Notes\n{combined}\n"

    # Specific block: the prompt-type section
    specific_block = ""
    section_name = _PROMPT_SPECIFIC.get(prompt_type, "")
    if section_name:
        content = sections.get(section_name, "").strip()
        if content:
            label = section_name.lower()
            specific_block = (
                f"\n## Additional {section_name} Instructions\n"
                f"The following notes were provided by the user "
                f"for {label} sessions:\n\n{content}\n"
            )

    # Session notes are user-authored instructions, so both blocks are inlined
    # whole and never truncated; an over-limit prompt is delivered by the
    # launcher's file-backed bootstrap instead.
    return general_block, specific_block


# ---------------------------------------------------------------------------
# Architecture document (pm/architecture.md)
# ---------------------------------------------------------------------------

ARCHITECTURE_FILENAME = "architecture.md"


def load_architecture(root: Path) -> str:
    """Return the architecture document's text, stripped.

    Returns ``""`` when the file is missing, empty or cannot be read (e.g. a
    directory sits at the path): the document is optional reference context,
    so a prompt builder treats all of those as "this project has none" rather
    than failing the launch.  Undecodable bytes are replaced, not fatal.
    """
    try:
        text = (root / ARCHITECTURE_FILENAME).read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text.strip()


def architecture_pointer(root: Path) -> str:
    """How a session should name the architecture document.

    An in-repo pm dir is committed with the target repo, so every clone a
    session works in has it at ``pm/architecture.md`` (the same convention
    impl sessions use for ``pm/specs/``).  A standalone pm dir is not part of
    those clones, so the absolute path is the only name that resolves.
    """
    if store.is_internal_pm_dir(root):
        return f"pm/{ARCHITECTURE_FILENAME}"
    return str(root / ARCHITECTURE_FILENAME)


def _architecture_role_guidance(prompt_type: str, pointer: str,
                                pr_id: str | None) -> str:
    this_pr = pr_id or "<pr-id>"
    if prompt_type == "plan":
        return f"""\
While planning:
- Map each proposed PR to the DP(s) it changes, and name them in the PR's
  description when the files don't make it obvious.
- Order PRs so dependencies flow down the matrix. Don't plan work that adds
  upward coupling or a hidden shared-state cycle.
- If the plan legitimately introduces a new FR/DP, or moves a module from one
  DP to another, say so explicitly in the plan file — what it is, where it
  sits in the matrix order, and why — so `{pointer}` can be updated."""
    if prompt_type == "impl":
        return f"""\
While implementing:
- Before designing, find the DP(s) this PR's task touches and keep the
  change inside them.
- If this PR legitimately introduces a new FR/DP, or moves a module from one
  DP to another, record it:
  `pm pr note add {this_pr} 'architecture: <new FR/DP or remap, where it sits in the matrix order, why>'`
  Edit `{pointer}` itself only when this PR's task asks you to — otherwise
  the note is how the change reaches it."""
    return f"""\
While reviewing, treat the document as the baseline and check the diff for:
- New upward `*` coupling — a module in a lower-order DP importing or calling
  into a higher-order one, including a lazy import added inside a function to
  sidestep a cycle.
- New hidden shared state across DPs — module globals, shared files, or
  object attributes used as an undeclared channel between them.
- New modules that map to no DP, or changes that blur two DPs into one.
- A legitimately new FR/DP or module remap the PR doesn't record (in a PR
  note, or in the PR's own edit to `{pointer}`).

New upward coupling, or a workaround that cites no filed improvements PR (see
below), is **NEEDS_WORK**. A contested FR/DP boundary change that needs human
judgment is **INPUT_REQUIRED**."""


_STRUCTURAL_DEBT_LEAD: dict[str, str] = {
    "plan": """
This applies to plans too: when a plan accepts a workaround, or leaves
coupling debt in place as out of scope, file or append the improvements PR as
above and cite its id in the plan instead of leaving the debt as prose.
""",
    "impl": "",
    "review": """
Check the diff for workarounds that skipped this: one whose comment cites no
improvements PR id is **NEEDS_WORK**. In review-loop mode, follow the rule
yourself for any workaround you add while fixing.
""",
}


_STRUCTURAL_DEBT_RULE = """
## File Structural Debt, Don't Just Comment It

Whenever you must add an out-of-scope workaround — a defensive guard, a lazy
import to sidestep an import cycle, a duplicated invariant check, or any
other patch around coupling this work isn't fixing — file the debt instead of
only commenting it:

1. Look for an existing PR on the same structural problem:
   `pm pr list --plan improvements`
2. If one exists, append a note so recurring pain self-prioritizes:
   `pm pr note add <pr-id> '<where you hit it and the workaround you added>'`
3. Otherwise file one:
   `pm pr add '<title>' --plan improvements --description '<the underlying coupling, where it bites, the workaround added, the proper fix>'`
4. Cite that PR id in the code comment beside the workaround — e.g.
   `<why this workaround exists>; tracked in <pr-id>` — instead of an orphan
   historical tag (a bare scenario number, a date, "temporary hack") that no
   one can follow up on.
{lead}"""


def architecture_section(root: Path, prompt_type: str, *,
                         pr_id: str | None = None,
                         max_bytes: int = ARCHITECTURE_BUDGET) -> str:
    """Return the architecture-awareness block for a prompt.

    Mirrors :func:`notes_section`: ``""`` when the project has no
    ``architecture.md`` (or it is empty), so prompts for such projects are
    unchanged.  Otherwise the block holds, in order: role-specific guidance
    for using the FRs/DPs/matrix, an excerpt of the document, and the "File
    Structural Debt, Don't Just Comment It" rule.

    Only the excerpt is bounded (``prompt_bounds.bounded_text``, head + tail,
    marker naming the file): the document is a reference the session can read
    in full.  The guidance and the rule are instructions and are inlined
    whole.

    Args:
        root: The pm root directory.
        prompt_type: ``"plan"``, ``"impl"`` or ``"review"`` (bug-fix PRs use
            the impl/review blocks).
        pr_id: Substituted into the impl guidance's ``pm pr note add``
            command; a placeholder is used when omitted.
        max_bytes: Budget for the document excerpt.
    """
    if prompt_type not in _STRUCTURAL_DEBT_LEAD:
        raise ValueError(
            f"unknown architecture prompt type {prompt_type!r}; expected one "
            f"of {', '.join(_STRUCTURAL_DEBT_LEAD)}")
    content = load_architecture(root)
    if not content:
        return ""

    pointer = architecture_pointer(root)
    excerpt = bounded_text(content, max_bytes=max_bytes,
                           pointer=f"`{pointer}`",
                           label="architecture document")
    guidance = _architecture_role_guidance(prompt_type, pointer, pr_id)
    rule = _STRUCTURAL_DEBT_RULE.format(lead=_STRUCTURAL_DEBT_LEAD[prompt_type])
    return f"""
## Project Architecture (`{pointer}`)

This project keeps its MIT Axiomatic Design analysis in `{pointer}`:
functional requirements (FRs), the disjoint design parameters (DPs) that
satisfy them (mapped to modules and directories), the Design Matrix [A],
known coupling debt, and an FR/DP change log. Use it as the map of the
codebase — work from the FRs/DPs/matrix below instead of re-deriving the
architecture yourself, and read the file for the full text when the copy
below is abbreviated.

The matrix is ordered so dependencies flow down: a DP may depend on DPs at
or below its own order, and a `*` above the diagonal is upward coupling.
- Keep changes inside the DP(s) they belong to.
- Don't add upward `*` coupling: a lower-order DP depending on a higher-order
  one, including through a lazy (function-level) import.
- Don't add hidden shared-state cycles: module globals, shared files, or
  object attributes written by one DP and read by another as an undeclared
  channel.

{guidance}

--- begin {pointer} ---
{excerpt}
--- end {pointer} ---
{rule}"""
