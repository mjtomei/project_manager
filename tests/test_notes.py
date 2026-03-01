"""Tests for pm_core.notes — section-based notes management."""

from pm_core.notes import (
    ALL_SECTIONS,
    COMMITTED_SECTIONS,
    LOCAL_NOTES_FILENAME,
    NOTES_FILENAME,
    PROMPT_SECTIONS,
    build_edit_template,
    ensure_notes_file,
    load_notes,
    load_sections,
    notes_for_prompt,
    notes_section,
    parse_edit_template,
    save_sections,
)


# ---------------------------------------------------------------------------
# ensure_notes_file
# ---------------------------------------------------------------------------

class TestEnsureNotesFile:
    def test_creates_both_files(self, tmp_path):
        path = ensure_notes_file(tmp_path)
        assert path.exists()
        assert path.name == NOTES_FILENAME
        assert (tmp_path / LOCAL_NOTES_FILENAME).exists()

    def test_idempotent(self, tmp_path):
        ensure_notes_file(tmp_path)
        ensure_notes_file(tmp_path)
        assert (tmp_path / NOTES_FILENAME).exists()
        assert (tmp_path / LOCAL_NOTES_FILENAME).exists()

    def test_does_not_overwrite_existing(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("## General\n\nmy notes")
        ensure_notes_file(tmp_path)
        assert "my notes" in (tmp_path / NOTES_FILENAME).read_text()

    def test_gitignore_includes_local_not_committed(self, tmp_path):
        ensure_notes_file(tmp_path)
        gi = tmp_path / ".gitignore"
        assert gi.exists()
        content = gi.read_text()
        assert LOCAL_NOTES_FILENAME in content
        assert ".no-notes-splash" in content
        # notes.txt should NOT be gitignored (it's committed now)
        lines = [l.strip() for l in content.splitlines()]
        assert NOTES_FILENAME not in lines

    def test_removes_notes_txt_from_gitignore(self, tmp_path):
        """Old gitignore had notes.txt — ensure it's removed."""
        gi = tmp_path / ".gitignore"
        gi.write_text("notes.txt\n.no-notes-splash\n")
        ensure_notes_file(tmp_path)
        content = gi.read_text()
        lines = [l.strip() for l in content.splitlines()]
        assert NOTES_FILENAME not in lines
        assert LOCAL_NOTES_FILENAME in lines

    def test_appends_to_existing_gitignore(self, tmp_path):
        gi = tmp_path / ".gitignore"
        gi.write_text("*.pyc\n")
        ensure_notes_file(tmp_path)
        content = gi.read_text()
        assert "*.pyc" in content
        assert LOCAL_NOTES_FILENAME in content

    def test_appends_newline_if_missing(self, tmp_path):
        gi = tmp_path / ".gitignore"
        gi.write_text("*.pyc")  # no trailing newline
        ensure_notes_file(tmp_path)
        content = gi.read_text()
        assert content.endswith("\n")

    def test_does_not_duplicate_entries(self, tmp_path):
        gi = tmp_path / ".gitignore"
        gi.write_text(f"{LOCAL_NOTES_FILENAME}\n.no-notes-splash\n")
        ensure_notes_file(tmp_path)
        content = gi.read_text()
        assert content.count(LOCAL_NOTES_FILENAME) == 1


# ---------------------------------------------------------------------------
# Migration from old format
# ---------------------------------------------------------------------------

class TestMigration:
    def test_old_format_migrates_to_local(self, tmp_path):
        """Old notes.txt without section headers is moved to notes-local.txt."""
        (tmp_path / NOTES_FILENAME).write_text("my old notes\nsome context\n")
        ensure_notes_file(tmp_path)
        # Old content should be in local file
        local = (tmp_path / LOCAL_NOTES_FILENAME).read_text()
        assert "my old notes" in local
        # Committed file should be cleared
        assert (tmp_path / NOTES_FILENAME).read_text() == ""

    def test_new_format_not_migrated(self, tmp_path):
        """notes.txt with section headers is left alone."""
        content = "## General\n\nsome notes\n"
        (tmp_path / NOTES_FILENAME).write_text(content)
        ensure_notes_file(tmp_path)
        assert (tmp_path / NOTES_FILENAME).read_text() == content

    def test_empty_file_not_migrated(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("")
        ensure_notes_file(tmp_path)
        assert (tmp_path / NOTES_FILENAME).read_text() == ""

    def test_does_not_overwrite_existing_local(self, tmp_path):
        """If notes-local.txt already has content, don't overwrite it."""
        (tmp_path / NOTES_FILENAME).write_text("old notes")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("existing local\n")
        ensure_notes_file(tmp_path)
        assert "existing local" in (tmp_path / LOCAL_NOTES_FILENAME).read_text()


# ---------------------------------------------------------------------------
# load_sections / save_sections
# ---------------------------------------------------------------------------

class TestLoadSections:
    def test_empty_files(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("")
        sections = load_sections(tmp_path)
        assert all(sections[s] == "" for s in ALL_SECTIONS)

    def test_missing_files(self, tmp_path):
        sections = load_sections(tmp_path)
        assert all(sections[s] == "" for s in ALL_SECTIONS)

    def test_loads_committed_sections(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text(
            "## General\n\ngeneral notes\n\n## Implementation\n\nimpl notes\n"
        )
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("")
        sections = load_sections(tmp_path)
        assert sections["General"] == "general notes"
        assert sections["Implementation"] == "impl notes"
        assert sections["Review"] == ""
        assert sections["Local"] == ""

    def test_loads_local_section(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("local stuff\n")
        sections = load_sections(tmp_path)
        assert sections["Local"] == "local stuff"

    def test_loads_all_sections(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text(
            "## General\n\nG\n\n## Implementation\n\nI\n\n"
            "## Review\n\nR\n\n## Merge\n\nM\n\n## Watcher\n\nW\n"
        )
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("L\n")
        sections = load_sections(tmp_path)
        assert sections["General"] == "G"
        assert sections["Implementation"] == "I"
        assert sections["Review"] == "R"
        assert sections["Merge"] == "M"
        assert sections["Watcher"] == "W"
        assert sections["Local"] == "L"


class TestSaveSections:
    def test_roundtrip(self, tmp_path):
        original = {
            "General": "general notes",
            "Implementation": "impl stuff",
            "Review": "",
            "Merge": "merge notes",
            "Watcher": "",
            "Local": "local only",
        }
        save_sections(tmp_path, original)
        loaded = load_sections(tmp_path)
        for s in ALL_SECTIONS:
            assert loaded[s] == original[s].strip()

    def test_committed_file_has_all_headers(self, tmp_path):
        save_sections(tmp_path, {"General": "stuff"})
        content = (tmp_path / NOTES_FILENAME).read_text()
        for s in COMMITTED_SECTIONS:
            assert f"## {s}" in content

    def test_empty_local_writes_empty_file(self, tmp_path):
        save_sections(tmp_path, {"Local": ""})
        assert (tmp_path / LOCAL_NOTES_FILENAME).read_text() == ""

    def test_local_content_preserved(self, tmp_path):
        save_sections(tmp_path, {"Local": "my local notes"})
        assert (tmp_path / LOCAL_NOTES_FILENAME).read_text() == "my local notes\n"


# ---------------------------------------------------------------------------
# build_edit_template / parse_edit_template
# ---------------------------------------------------------------------------

class TestEditTemplate:
    def test_template_has_all_sections(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("")
        template = build_edit_template(tmp_path)
        for s in ALL_SECTIONS:
            assert f"## {s}" in template

    def test_template_includes_content(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("## General\n\nhello world\n")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("local stuff\n")
        template = build_edit_template(tmp_path)
        assert "hello world" in template
        assert "local stuff" in template

    def test_template_includes_descriptions(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("")
        template = build_edit_template(tmp_path)
        assert "included in all prompts" in template
        assert "gitignored" in template

    def test_parse_roundtrip(self, tmp_path):
        sections = {
            "General": "general notes here",
            "Implementation": "impl notes",
            "Review": "review notes",
            "Merge": "",
            "Watcher": "watcher notes",
            "Local": "local only stuff",
        }
        save_sections(tmp_path, sections)
        template = build_edit_template(tmp_path)
        parsed = parse_edit_template(template)
        for s in ALL_SECTIONS:
            assert parsed.get(s, "") == sections[s].strip()

    def test_parse_empty_template(self):
        parsed = parse_edit_template("")
        assert parsed == {}

    def test_parse_unknown_headers_become_content(self):
        """Unknown section headers are treated as content of the previous section."""
        text = "## General\n\nhello\n\n## Unknown\n\nstuff\n"
        parsed = parse_edit_template(text)
        assert "hello" in parsed["General"]
        assert "## Unknown" in parsed["General"]

    def test_parse_case_insensitive(self):
        text = "## general\n\nhello\n"
        parsed = parse_edit_template(text)
        assert parsed["General"] == "hello"


# ---------------------------------------------------------------------------
# load_notes (backwards-compatible combined view)
# ---------------------------------------------------------------------------

class TestLoadNotes:
    def test_missing_files(self, tmp_path):
        assert load_notes(tmp_path) == ""

    def test_reads_all_sections(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("## General\n\nhello\n")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("local\n")
        result = load_notes(tmp_path)
        assert "hello" in result
        assert "local" in result

    def test_empty_files(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("")
        assert load_notes(tmp_path) == ""


# ---------------------------------------------------------------------------
# notes_section (prompt integration)
# ---------------------------------------------------------------------------

class TestNotesSection:
    def test_empty_notes(self, tmp_path):
        assert notes_section(tmp_path) == ""

    def test_whitespace_only_notes(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("## General\n\n   \n")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("  \n")
        assert notes_section(tmp_path) == ""

    def test_returns_formatted_section(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("## General\n\nimportant note\n")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("")
        result = notes_section(tmp_path)
        assert "## Session Notes" in result
        assert "important note" in result

    def test_missing_files_returns_empty(self, tmp_path):
        assert notes_section(tmp_path) == ""

    def test_impl_includes_general_impl_local(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text(
            "## General\n\nG\n\n## Implementation\n\nI\n\n## Review\n\nR\n"
        )
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("L\n")
        result = notes_section(tmp_path, "impl")
        assert "G" in result
        assert "I" in result
        assert "L" in result
        assert "R" not in result

    def test_review_includes_general_review_local(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text(
            "## General\n\nG\n\n## Implementation\n\nI\n\n## Review\n\nR\n"
        )
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("L\n")
        result = notes_section(tmp_path, "review")
        assert "G" in result
        assert "R" in result
        assert "L" in result
        assert "I" not in result

    def test_merge_includes_general_merge_local(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text(
            "## General\n\nG\n\n## Merge\n\nM\n\n## Watcher\n\nW\n"
        )
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("L\n")
        result = notes_section(tmp_path, "merge")
        assert "G" in result
        assert "M" in result
        assert "L" in result
        assert "W" not in result

    def test_watcher_includes_general_watcher_local(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text(
            "## General\n\nG\n\n## Watcher\n\nW\n\n## Merge\n\nM\n"
        )
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("L\n")
        result = notes_section(tmp_path, "watcher")
        assert "G" in result
        assert "W" in result
        assert "L" in result
        assert "M" not in result

    def test_none_prompt_type_includes_all(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text(
            "## General\n\nG\n\n## Implementation\n\nI\n\n"
            "## Review\n\nR\n\n## Merge\n\nM\n\n## Watcher\n\nW\n"
        )
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("L\n")
        result = notes_section(tmp_path, None)
        for letter in ["G", "I", "R", "M", "W", "L"]:
            assert letter in result

    def test_unknown_prompt_type_includes_all(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("## General\n\nG\n")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("")
        result = notes_section(tmp_path, "unknown")
        assert "G" in result


# ---------------------------------------------------------------------------
# notes_for_prompt (two-block prompt integration)
# ---------------------------------------------------------------------------

class TestNotesForPrompt:
    def test_empty_notes_returns_empty_tuple(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("")
        general, specific = notes_for_prompt(tmp_path, "impl")
        assert general == ""
        assert specific == ""

    def test_general_block_includes_general_and_local(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("## General\n\nG notes\n")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("L notes\n")
        general, _ = notes_for_prompt(tmp_path, "impl")
        assert "## Session Notes" in general
        assert "G notes" in general
        assert "L notes" in general

    def test_general_block_excludes_specific_sections(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text(
            "## General\n\nG\n\n## Implementation\n\nI\n\n## Review\n\nR\n"
        )
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("")
        general, _ = notes_for_prompt(tmp_path, "impl")
        assert "I" not in general
        assert "R" not in general

    def test_specific_block_for_impl(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("## Implementation\n\nimpl instructions\n")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("")
        _, specific = notes_for_prompt(tmp_path, "impl")
        assert "## Additional Implementation Instructions" in specific
        assert "for implementation sessions" in specific
        assert "impl instructions" in specific

    def test_specific_block_for_review(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("## Review\n\nreview instructions\n")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("")
        _, specific = notes_for_prompt(tmp_path, "review")
        assert "## Additional Review Instructions" in specific
        assert "for review sessions" in specific
        assert "review instructions" in specific

    def test_specific_block_for_merge(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("## Merge\n\nmerge instructions\n")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("")
        _, specific = notes_for_prompt(tmp_path, "merge")
        assert "## Additional Merge Instructions" in specific
        assert "merge instructions" in specific

    def test_specific_block_for_watcher(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("## Watcher\n\nwatcher instructions\n")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("")
        _, specific = notes_for_prompt(tmp_path, "watcher")
        assert "## Additional Watcher Instructions" in specific
        assert "watcher instructions" in specific

    def test_specific_block_empty_when_no_content(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text("## General\n\nG\n")
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("")
        _, specific = notes_for_prompt(tmp_path, "impl")
        assert specific == ""

    def test_specific_block_excludes_other_types(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text(
            "## Review\n\nreview stuff\n\n## Implementation\n\nimpl stuff\n"
        )
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("")
        _, specific = notes_for_prompt(tmp_path, "review")
        assert "review stuff" in specific
        assert "impl stuff" not in specific

    def test_both_blocks_populated(self, tmp_path):
        (tmp_path / NOTES_FILENAME).write_text(
            "## General\n\nG\n\n## Implementation\n\nI\n"
        )
        (tmp_path / LOCAL_NOTES_FILENAME).write_text("L\n")
        general, specific = notes_for_prompt(tmp_path, "impl")
        assert "G" in general
        assert "L" in general
        assert "I" in specific
        assert "## Session Notes" in general
        assert "## Additional Implementation Instructions" in specific

    def test_missing_files(self, tmp_path):
        general, specific = notes_for_prompt(tmp_path, "impl")
        assert general == ""
        assert specific == ""
