"""Notes file management for pm sessions."""

from pathlib import Path

NOTES_FILENAME = "notes.txt"
NOTES_HEADER = """\
Notes
=====

Your scratchpad. Jot down anything useful as you work — context,
decisions, things to remember. This file is included in every prompt
pm sends to Claude, so anything you write here becomes shared context.

This file is gitignored and stays local to your machine.
"""

# Vim-style welcome content shown in new notes files.
# The tilde lines mimic vim's empty-buffer display.
NOTES_WELCOME = """\
~
~
~
~           Notes
~
~           Your scratchpad — jot down anything useful as you work.
~           This file is included in every prompt pm sends to Claude,
~           so anything you write here becomes shared context.
~
~               • What you're working on and why
~               • Decisions you've made and their rationale
~               • Things you've tried that didn't work
~               • Details about your setup that Claude forgets between
~                 sessions or loses in long contexts
~               • Anything you'd tell a colleague sitting down at your desk
~
~           Press any key to start editing.
~           This file is gitignored — it stays local to your machine.
~
~
~
"""


def ensure_notes_file(root: Path) -> Path:
    """Create notes.txt if it doesn't exist. Returns the path."""
    path = root / NOTES_FILENAME
    if not path.exists():
        path.write_text("")
    # Ensure gitignored
    gitignore = root / ".gitignore"
    gitignore_content = gitignore.read_text() if gitignore.exists() else ""
    entries_to_ignore = ["notes.txt", ".no-notes-splash"]
    missing = [e for e in entries_to_ignore if e not in gitignore_content]
    if missing:
        with open(gitignore, "a") as f:
            if gitignore_content and not gitignore_content.endswith("\n"):
                f.write("\n")
            for e in missing:
                f.write(f"{e}\n")
    return path


def load_notes(root: Path) -> str:
    """Read notes.txt content, or return empty string if missing."""
    path = root / NOTES_FILENAME
    if path.exists():
        return path.read_text()
    return ""



def notes_section(root: Path) -> str:
    """Return a formatted notes block for inclusion in prompts, or empty string."""
    content = load_notes(root)
    if not content or not content.strip():
        return ""
    return f"\n## Session Notes\n{content}\n"
