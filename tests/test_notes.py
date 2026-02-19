"""Tests for pm_core.notes — notes file management."""

from pm_core.notes import (
    ensure_notes_file,
    load_notes,
    notes_section,
    NOTES_FILENAME,
)


# ---------------------------------------------------------------------------
# ensure_notes_file
# ---------------------------------------------------------------------------

class TestEnsureNotesFile:
    def test_creates_file(self, tmp_path):
        path = ensure_notes_file(tmp_path)
        assert path.exists()
        assert path.name == NOTES_FILENAME

    def test_idempotent(self, tmp_path):
        ensure_notes_file(tmp_path)
        ensure_notes_file(tmp_path)
        assert (tmp_path / NOTES_FILENAME).exists()

    def test_does_not_overwrite_existing(self, tmp_path):
        notes = tmp_path / NOTES_FILENAME
        notes.write_text("my notes")
        ensure_notes_file(tmp_path)
        assert notes.read_text() == "my notes"

    def test_creates_gitignore(self, tmp_path):
        ensure_notes_file(tmp_path)
        gi = tmp_path / ".gitignore"
        assert gi.exists()
        content = gi.read_text()
        assert "notes.txt" in content
        assert ".no-notes-splash" in content

    def test_appends_to_existing_gitignore(self, tmp_path):
        gi = tmp_path / ".gitignore"
        gi.write_text("*.pyc\n")
        ensure_notes_file(tmp_path)
        content = gi.read_text()
        assert "*.pyc" in content
        assert "notes.txt" in content

    def test_appends_newline_if_missing(self, tmp_path):
        gi = tmp_path / ".gitignore"
        gi.write_text("*.pyc")  # no trailing newline
        ensure_notes_file(tmp_path)
        content = gi.read_text()
        # Should have a newline between existing content and new entries
        assert "*.pyc\n" in content

    def test_does_not_duplicate_entries(self, tmp_path):
        gi = tmp_path / ".gitignore"
        gi.write_text("notes.txt\n.no-notes-splash\n")
        ensure_notes_file(tmp_path)
        content = gi.read_text()
        assert content.count("notes.txt") == 1


# ---------------------------------------------------------------------------
# load_notes
# ---------------------------------------------------------------------------

class TestLoadNotes:
    def test_missing_file(self, tmp_path):
        assert load_notes(tmp_path) == ""

    def test_reads_content(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("hello world")
        assert load_notes(tmp_path) == "hello world"

    def test_empty_file(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("")
        assert load_notes(tmp_path) == ""


# ---------------------------------------------------------------------------
# notes_section
# ---------------------------------------------------------------------------

class TestNotesSection:
    def test_empty_notes(self, tmp_path):
        assert notes_section(tmp_path) == ""

    def test_whitespace_only_notes(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("   \n  \n")
        assert notes_section(tmp_path) == ""

    def test_returns_formatted_section(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("important note")
        result = notes_section(tmp_path)
        assert "## Session Notes" in result
        assert "important note" in result

    def test_missing_file_returns_empty(self, tmp_path):
        assert notes_section(tmp_path) == ""
