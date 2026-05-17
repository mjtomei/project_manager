"""Tests for PR notes feature — hash-based note IDs, CLI commands, prompt gen."""

import re
from unittest.mock import patch

from click.testing import CliRunner

from pm_core import store
from pm_core.cli import cli
from pm_core.prompt_gen import (
    _format_pr_notes,
    generate_prompt, generate_review_prompt,
    generate_qa_planner_prompt, generate_qa_child_prompt,
)


# ---------------------------------------------------------------------------
# store.generate_note_id
# ---------------------------------------------------------------------------

class TestGenerateNoteId:
    def test_produces_note_prefix(self):
        nid = store.generate_note_id("pr-001", "hello")
        assert nid.startswith("note-")

    def test_deterministic(self):
        a = store.generate_note_id("pr-001", "hello")
        b = store.generate_note_id("pr-001", "hello")
        assert a == b

    def test_different_text_different_id(self):
        a = store.generate_note_id("pr-001", "hello")
        b = store.generate_note_id("pr-001", "world")
        assert a != b

    def test_different_pr_different_id(self):
        a = store.generate_note_id("pr-001", "hello")
        b = store.generate_note_id("pr-002", "hello")
        assert a != b

    def test_avoids_existing_ids(self):
        nid = store.generate_note_id("pr-001", "hello")
        nid2 = store.generate_note_id("pr-001", "hello", existing_ids={nid})
        assert nid2 != nid
        assert nid2.startswith("note-")

    def test_min_length_7(self):
        nid = store.generate_note_id("pr-x", "y")
        # note- prefix + at least 7 hex chars
        assert len(nid) >= len("note-") + 7


# ---------------------------------------------------------------------------
# CLI: pm pr note add / list / delete
# ---------------------------------------------------------------------------

def _make_state(tmp_path, notes=None):
    """Create a minimal project.yaml and return its path."""
    pr = {
        "id": "pr-001",
        "plan": None,
        "title": "Test PR",
        "branch": "pm/pr-001-test",
        "status": "in_progress",
        "depends_on": [],
        "description": "A test PR",
        "agent_machine": None,
        "gh_pr": None,
        "gh_pr_number": None,
    }
    if notes is not None:
        pr["notes"] = notes
    data = {
        "project": {"name": "test", "repo": "/tmp/fake", "base_branch": "master"},
        "plans": [],
        "prs": [pr],
    }
    store.save(data, tmp_path)
    return tmp_path


class TestPrNoteAdd:
    def test_add_note(self, tmp_path):
        root = _make_state(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "add", "pr-001", "Fix the bug first"])
        assert result.exit_code == 0
        assert "Added note" in result.output
        # Verify persisted
        data = store.load(root)
        pr = store.get_pr(data, "pr-001")
        assert len(pr["notes"]) == 1
        assert pr["notes"][0]["text"] == "Fix the bug first"
        assert pr["notes"][0]["id"].startswith("note-")

    def test_add_note_has_timestamp(self, tmp_path):
        root = _make_state(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "add", "pr-001", "Timestamped note"])
        assert result.exit_code == 0
        data = store.load(root)
        pr = store.get_pr(data, "pr-001")
        note = pr["notes"][0]
        assert "created_at" in note
        assert "last_edited" in note
        # ISO 8601 UTC format: YYYY-MM-DDTHH:MM:SSZ
        ts_re = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
        assert re.match(ts_re, note["created_at"])
        assert re.match(ts_re, note["last_edited"])
        # On creation, both timestamps are the same
        assert note["created_at"] == note["last_edited"]

    def test_add_multiple_notes(self, tmp_path):
        root = _make_state(tmp_path)
        runner = CliRunner()
        runner.invoke(cli, ["-C", str(root), "pr", "note", "add", "pr-001", "Note one"])
        runner.invoke(cli, ["-C", str(root), "pr", "note", "add", "pr-001", "Note two"])
        data = store.load(root)
        pr = store.get_pr(data, "pr-001")
        assert len(pr["notes"]) == 2
        assert pr["notes"][0]["text"] == "Note one"
        assert pr["notes"][1]["text"] == "Note two"
        # Both have timestamps
        assert pr["notes"][0]["created_at"]
        assert pr["notes"][0]["last_edited"]
        assert pr["notes"][1]["created_at"]
        assert pr["notes"][1]["last_edited"]

    def test_add_note_unknown_pr(self, tmp_path):
        root = _make_state(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "add", "pr-999", "text"])
        assert result.exit_code != 0


class TestPrNoteList:
    def test_list_empty(self, tmp_path):
        root = _make_state(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "list", "pr-001"])
        assert result.exit_code == 0
        assert "No notes" in result.output

    def test_list_with_notes(self, tmp_path):
        notes = [
            {"id": "note-abc1234", "text": "First note", "created_at": "2026-01-15T10:30:00Z"},
            {"id": "note-def5678", "text": "Second note", "created_at": "2026-01-16T14:00:00Z"},
        ]
        root = _make_state(tmp_path, notes=notes)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "list", "pr-001"])
        assert result.exit_code == 0
        assert "First note" in result.output
        assert "Second note" in result.output
        assert "note-abc1234" in result.output

    def test_list_shows_timestamps(self, tmp_path):
        notes = [
            {"id": "note-abc1234", "text": "A note", "created_at": "2026-01-15T10:30:00Z"},
        ]
        root = _make_state(tmp_path, notes=notes)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "list", "pr-001"])
        assert "2026-01-15T10:30:00Z" in result.output

    def test_list_without_timestamps(self, tmp_path):
        """Notes created before timestamps were added still display fine."""
        notes = [
            {"id": "note-abc1234", "text": "Legacy note"},
        ]
        root = _make_state(tmp_path, notes=notes)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "list", "pr-001"])
        assert result.exit_code == 0
        assert "Legacy note" in result.output


class TestPrNoteEdit:
    def test_edit_note_text(self, tmp_path):
        notes = [
            {"id": "note-abc1234", "text": "Old text", "created_at": "2026-01-15T10:30:00Z", "last_edited": "2026-01-15T10:30:00Z"},
        ]
        root = _make_state(tmp_path, notes=notes)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "edit", "pr-001", "note-abc1234", "New text"])
        assert result.exit_code == 0
        assert "Updated note" in result.output
        data = store.load(root)
        pr = store.get_pr(data, "pr-001")
        assert len(pr["notes"]) == 1
        assert pr["notes"][0]["text"] == "New text"

    def test_edit_updates_last_edited(self, tmp_path):
        notes = [
            {"id": "note-abc1234", "text": "Old text", "created_at": "2026-01-15T10:30:00Z", "last_edited": "2026-01-15T10:30:00Z"},
        ]
        root = _make_state(tmp_path, notes=notes)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "edit", "pr-001", "note-abc1234", "New text"])
        assert result.exit_code == 0
        data = store.load(root)
        pr = store.get_pr(data, "pr-001")
        note = pr["notes"][0]
        # created_at should be preserved
        assert note["created_at"] == "2026-01-15T10:30:00Z"
        # last_edited should be updated
        assert note["last_edited"] != "2026-01-15T10:30:00Z"
        ts_re = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
        assert re.match(ts_re, note["last_edited"])

    def test_edit_changes_note_id(self, tmp_path):
        """Note ID is hash-based, so editing text should produce a new ID."""
        notes = [
            {"id": "note-abc1234", "text": "Old text", "created_at": "2026-01-15T10:30:00Z", "last_edited": "2026-01-15T10:30:00Z"},
        ]
        root = _make_state(tmp_path, notes=notes)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "edit", "pr-001", "note-abc1234", "New text"])
        assert result.exit_code == 0
        data = store.load(root)
        pr = store.get_pr(data, "pr-001")
        assert pr["notes"][0]["id"] != "note-abc1234"
        assert pr["notes"][0]["id"].startswith("note-")

    def test_edit_unknown_note(self, tmp_path):
        notes = [{"id": "note-abc1234", "text": "A note", "created_at": "2026-01-15T10:30:00Z", "last_edited": "2026-01-15T10:30:00Z"}]
        root = _make_state(tmp_path, notes=notes)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "edit", "pr-001", "note-nope", "New text"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_edit_unknown_pr(self, tmp_path):
        root = _make_state(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "edit", "pr-999", "note-abc", "New text"])
        assert result.exit_code != 0

    def test_edit_preserves_other_notes(self, tmp_path):
        notes = [
            {"id": "note-abc1234", "text": "Keep this", "created_at": "2026-01-15T10:30:00Z", "last_edited": "2026-01-15T10:30:00Z"},
            {"id": "note-def5678", "text": "Edit this", "created_at": "2026-01-16T14:00:00Z", "last_edited": "2026-01-16T14:00:00Z"},
        ]
        root = _make_state(tmp_path, notes=notes)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "edit", "pr-001", "note-def5678", "Edited text"])
        assert result.exit_code == 0
        data = store.load(root)
        pr = store.get_pr(data, "pr-001")
        assert len(pr["notes"]) == 2
        assert pr["notes"][0]["id"] == "note-abc1234"
        assert pr["notes"][0]["text"] == "Keep this"
        assert pr["notes"][1]["text"] == "Edited text"


class TestPrNoteDelete:
    def test_delete_note(self, tmp_path):
        notes = [
            {"id": "note-abc1234", "text": "First note", "created_at": "2026-01-15T10:30:00Z"},
            {"id": "note-def5678", "text": "Second note", "created_at": "2026-01-16T14:00:00Z"},
        ]
        root = _make_state(tmp_path, notes=notes)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "delete", "pr-001", "note-abc1234"])
        assert result.exit_code == 0
        assert "Deleted" in result.output
        data = store.load(root)
        pr = store.get_pr(data, "pr-001")
        assert len(pr["notes"]) == 1
        assert pr["notes"][0]["id"] == "note-def5678"

    def test_delete_unknown_note(self, tmp_path):
        notes = [{"id": "note-abc1234", "text": "A note"}]
        root = _make_state(tmp_path, notes=notes)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "delete", "pr-001", "note-nope"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_delete_from_empty(self, tmp_path):
        root = _make_state(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(root), "pr", "note", "delete", "pr-001", "note-nope"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# pr edit — notes in editor template
# ---------------------------------------------------------------------------

class TestPrEditNotes:
    def test_edit_adds_note(self, tmp_path):
        """Simulating editor interaction: user adds a note."""
        root = _make_state(tmp_path)
        runner = CliRunner()

        # Use --title to trigger non-editor path (no note change)
        result = runner.invoke(cli, ["-C", str(root), "pr", "edit", "pr-001", "--title", "New Title"])
        assert result.exit_code == 0
        assert "title=" in result.output

    def test_editor_template_shows_no_notes_comment(self, tmp_path):
        """When PR has no notes, the template should show a comment placeholder."""
        root = _make_state(tmp_path)
        data = store.load(root)
        pr = store.get_pr(data, "pr-001")
        # Check that the template would contain the no-notes comment
        notes = pr.get("notes") or []
        assert len(notes) == 0

    def test_editor_template_shows_notes(self, tmp_path):
        """When PR has notes, they appear as bulleted list."""
        notes = [{"id": "note-abc", "text": "Important context", "created_at": "2026-01-15T10:30:00Z"}]
        root = _make_state(tmp_path, notes=notes)
        data = store.load(root)
        pr = store.get_pr(data, "pr-001")
        assert pr["notes"][0]["text"] == "Important context"
        assert pr["notes"][0]["created_at"] == "2026-01-15T10:30:00Z"

    def test_editor_roundtrip_preserves_notes(self, tmp_path):
        """Saving the editor template without changes must not alter notes.

        Regression test: timestamps rendered as '# ...' comments in the
        template were being parsed back as part of the note text, causing
        every note to get a new hash ID on each save.
        """
        notes = [
            {"id": "note-abc", "text": "First note", "created_at": "2026-01-15T10:30:00Z"},
            {"id": "note-def", "text": "Second note", "created_at": "2026-01-16T14:00:00Z"},
        ]
        root = _make_state(tmp_path, notes=notes)
        runner = CliRunner()

        def fake_watched_editor(template, on_save, **kwargs):
            # Save unchanged template — should detect no changes
            on_save(template)
            return 0, True

        with patch("pm_core.editor.run_watched_editor", side_effect=fake_watched_editor):
            result = runner.invoke(cli, ["-C", str(root), "pr", "edit", "pr-001"])

        # Notes should be unchanged
        data = store.load(root)
        pr = store.get_pr(data, "pr-001")
        assert len(pr["notes"]) == 2
        assert pr["notes"][0]["id"] == "note-abc"
        assert pr["notes"][0]["text"] == "First note"
        assert pr["notes"][1]["id"] == "note-def"
        assert pr["notes"][1]["text"] == "Second note"

    def test_editor_new_note_gets_both_timestamps(self, tmp_path):
        """A note added via the editor should have created_at and last_edited."""
        root = _make_state(tmp_path)
        runner = CliRunner()

        def fake_watched_editor(template, on_save, **kwargs):
            content = template.replace("# (no notes)\n", "- Brand new note\n")
            on_save(content)
            return 0, True

        with patch("pm_core.editor.run_watched_editor", side_effect=fake_watched_editor):
            result = runner.invoke(cli, ["-C", str(root), "pr", "edit", "pr-001"])

        assert result.exit_code == 0
        data = store.load(root)
        pr = store.get_pr(data, "pr-001")
        assert len(pr["notes"]) == 1
        note = pr["notes"][0]
        assert note["text"] == "Brand new note"
        assert "created_at" in note
        assert "last_edited" in note
        assert note["created_at"] == note["last_edited"]

    def test_editor_sorts_notes_by_last_edited(self, tmp_path):
        """After editor save, notes should be sorted by last_edited."""
        notes = [
            {"id": "note-old", "text": "Old note", "created_at": "2026-01-10T00:00:00Z", "last_edited": "2026-01-20T00:00:00Z"},
            {"id": "note-new", "text": "New note", "created_at": "2026-01-15T00:00:00Z", "last_edited": "2026-01-12T00:00:00Z"},
        ]
        root = _make_state(tmp_path, notes=notes)
        runner = CliRunner()

        def fake_watched_editor(template, on_save, **kwargs):
            content = template.replace(
                "# Description (everything below this line):",
                "- Third note\n\n# Description (everything below this line):"
            )
            on_save(content)
            return 0, True

        with patch("pm_core.editor.run_watched_editor", side_effect=fake_watched_editor):
            result = runner.invoke(cli, ["-C", str(root), "pr", "edit", "pr-001"])

        assert result.exit_code == 0
        data = store.load(root)
        pr = store.get_pr(data, "pr-001")
        assert len(pr["notes"]) == 3
        # Sorted by last_edited: note-new (Jan 12) < note-old (Jan 20) < Third note (now)
        assert pr["notes"][0]["id"] == "note-new"
        assert pr["notes"][1]["id"] == "note-old"
        assert pr["notes"][2]["text"] == "Third note"


# ---------------------------------------------------------------------------
# Prompt generation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Workdir note merging (_format_pr_notes)
# ---------------------------------------------------------------------------

def _make_workdir_state(tmp_path, pr_id, notes):
    """Create a pm/project.yaml inside tmp_path with a single PR carrying notes."""
    pr = {
        "id": pr_id,
        "plan": None,
        "title": "Test PR",
        "branch": f"pm/{pr_id}",
        "status": "in_progress",
        "depends_on": [],
        "description": "desc",
        "agent_machine": None,
        "gh_pr": None,
        "gh_pr_number": None,
        "notes": notes,
    }
    data = {
        "project": {"name": "test", "repo": str(tmp_path), "base_branch": "master"},
        "plans": [],
        "prs": [pr],
    }
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir(exist_ok=True)
    store.save(data, pm_dir)
    return str(tmp_path)


class TestFormatPrNotesWorkdirMerge:
    """Tests for _format_pr_notes merging notes from main + workdir."""

    def test_no_workdir(self):
        """Without workdir, behaves as before."""
        pr = {"id": "pr-001", "notes": [
            {"id": "n1", "text": "Main note", "created_at": "2026-01-01T00:00:00Z"},
        ]}
        result = _format_pr_notes(pr)
        assert "Main note" in result
        assert "## PR Notes" in result

    def test_workdir_adds_unique_notes(self, tmp_path):
        """Notes only in the workdir are included in the merged output."""
        workdir = _make_workdir_state(tmp_path, "pr-001", [
            {"id": "wd-1", "text": "Workdir note", "created_at": "2026-01-02T00:00:00Z"},
        ])
        pr = {"id": "pr-001", "notes": [
            {"id": "n1", "text": "Main note", "created_at": "2026-01-01T00:00:00Z"},
        ]}
        result = _format_pr_notes(pr, workdir=workdir)
        assert "Main note" in result
        assert "Workdir note" in result

    def test_dedup_prefers_later_last_edited(self, tmp_path):
        """When both have the same note ID, the one with later last_edited wins."""
        workdir = _make_workdir_state(tmp_path, "pr-001", [
            {"id": "n1", "text": "Updated in workdir", "created_at": "2026-01-01T00:00:00Z",
             "last_edited": "2026-01-03T00:00:00Z"},
        ])
        pr = {"id": "pr-001", "notes": [
            {"id": "n1", "text": "Original in main", "created_at": "2026-01-01T00:00:00Z",
             "last_edited": "2026-01-01T00:00:00Z"},
        ]}
        result = _format_pr_notes(pr, workdir=workdir)
        assert "Updated in workdir" in result
        assert "Original in main" not in result

    def test_dedup_main_wins_when_newer(self, tmp_path):
        """When main's last_edited is later, main version is kept."""
        workdir = _make_workdir_state(tmp_path, "pr-001", [
            {"id": "n1", "text": "Older workdir version", "created_at": "2026-01-01T00:00:00Z",
             "last_edited": "2026-01-01T00:00:00Z"},
        ])
        pr = {"id": "pr-001", "notes": [
            {"id": "n1", "text": "Newer main version", "created_at": "2026-01-01T00:00:00Z",
             "last_edited": "2026-01-05T00:00:00Z"},
        ]}
        result = _format_pr_notes(pr, workdir=workdir)
        assert "Newer main version" in result
        assert "Older workdir version" not in result

    def test_dedup_falls_back_to_created_at(self, tmp_path):
        """When last_edited is missing, falls back to created_at for comparison."""
        workdir = _make_workdir_state(tmp_path, "pr-001", [
            {"id": "n1", "text": "Workdir version", "created_at": "2026-01-05T00:00:00Z"},
        ])
        pr = {"id": "pr-001", "notes": [
            {"id": "n1", "text": "Main version", "created_at": "2026-01-01T00:00:00Z"},
        ]}
        result = _format_pr_notes(pr, workdir=workdir)
        assert "Workdir version" in result
        assert "Main version" not in result

    def test_sorted_by_created_at(self, tmp_path):
        """Merged notes are sorted by created_at."""
        workdir = _make_workdir_state(tmp_path, "pr-001", [
            {"id": "wd-1", "text": "Middle note", "created_at": "2026-01-02T00:00:00Z"},
        ])
        pr = {"id": "pr-001", "notes": [
            {"id": "n1", "text": "First note", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "n2", "text": "Last note", "created_at": "2026-01-03T00:00:00Z"},
        ]}
        result = _format_pr_notes(pr, workdir=workdir)
        first_pos = result.index("First note")
        middle_pos = result.index("Middle note")
        last_pos = result.index("Last note")
        assert first_pos < middle_pos < last_pos

    def test_workdir_missing_path(self):
        """Non-existent workdir path degrades gracefully."""
        pr = {"id": "pr-001", "notes": [
            {"id": "n1", "text": "Main note", "created_at": "2026-01-01T00:00:00Z"},
        ]}
        result = _format_pr_notes(pr, workdir="/nonexistent/path")
        assert "Main note" in result

    def test_workdir_no_matching_pr(self, tmp_path):
        """Workdir has project.yaml but not this PR — still works."""
        workdir = _make_workdir_state(tmp_path, "pr-OTHER", [
            {"id": "wd-1", "text": "Other PR note", "created_at": "2026-01-02T00:00:00Z"},
        ])
        pr = {"id": "pr-001", "notes": [
            {"id": "n1", "text": "Main note", "created_at": "2026-01-01T00:00:00Z"},
        ]}
        result = _format_pr_notes(pr, workdir=workdir)
        assert "Main note" in result
        assert "Other PR note" not in result

    def test_both_empty_returns_empty(self, tmp_path):
        """Both sources with no notes returns empty string."""
        workdir = _make_workdir_state(tmp_path, "pr-001", [])
        pr = {"id": "pr-001", "notes": []}
        result = _format_pr_notes(pr, workdir=workdir)
        assert result == ""

    def test_only_workdir_has_notes(self, tmp_path):
        """Main has no notes but workdir does — workdir notes appear."""
        workdir = _make_workdir_state(tmp_path, "pr-001", [
            {"id": "wd-1", "text": "Workdir only", "created_at": "2026-01-01T00:00:00Z"},
        ])
        pr = {"id": "pr-001"}
        result = _format_pr_notes(pr, workdir=workdir)
        assert "Workdir only" in result


class TestPromptGenNotes:
    def _data(self, notes=None):
        pr = {
            "id": "pr-001",
            "plan": None,
            "title": "Test PR",
            "branch": "pm/pr-001",
            "status": "in_progress",
            "depends_on": [],
            "description": "Do the thing",
            "agent_machine": None,
            "gh_pr": None,
            "gh_pr_number": None,
        }
        if notes is not None:
            pr["notes"] = notes
        return {
            "project": {"name": "test", "repo": "/tmp/fake", "base_branch": "master", "backend": "local"},
            "plans": [],
            "prs": [pr],
        }

    @patch("pm_core.prompt_gen.notes.notes_for_prompt", return_value=("", ""))
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_no_notes(self, mock_root, mock_notes):
        data = self._data()
        prompt = generate_prompt(data, "pr-001")
        assert "PR Notes" not in prompt

    @patch("pm_core.prompt_gen.notes.notes_for_prompt", return_value=("", ""))
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_with_notes(self, mock_root, mock_notes):
        data = self._data(notes=[
            {"id": "note-abc", "text": "Use the new API", "created_at": "2026-01-15T10:30:00Z"},
            {"id": "note-def", "text": "Don't touch auth module", "created_at": "2026-01-16T14:00:00Z"},
        ])
        prompt = generate_prompt(data, "pr-001")
        assert "## PR Notes" in prompt
        assert "Use the new API" in prompt
        assert "Don't touch auth module" in prompt

    @patch("pm_core.prompt_gen.notes.notes_for_prompt", return_value=("", ""))
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_prompt_includes_timestamps(self, mock_root, mock_notes):
        data = self._data(notes=[
            {"id": "note-abc", "text": "A note", "created_at": "2026-01-15T10:30:00Z"},
        ])
        prompt = generate_prompt(data, "pr-001")
        assert "2026-01-15T10:30:00Z" in prompt

    @patch("pm_core.prompt_gen.notes.notes_for_prompt", return_value=("", ""))
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_prompt_handles_missing_timestamp(self, mock_root, mock_notes):
        """Legacy notes without timestamps still render."""
        data = self._data(notes=[
            {"id": "note-abc", "text": "Legacy note"},
        ])
        prompt = generate_prompt(data, "pr-001")
        assert "Legacy note" in prompt

    def test_review_no_notes(self):
        data = self._data()
        prompt = generate_review_prompt(data, "pr-001")
        assert "PR Notes" not in prompt

    def test_review_with_notes(self):
        data = self._data(notes=[
            {"id": "note-abc", "text": "Check edge cases", "created_at": "2026-01-15T10:30:00Z"},
        ])
        prompt = generate_review_prompt(data, "pr-001")
        assert "## PR Notes" in prompt
        assert "Check edge cases" in prompt
        assert "2026-01-15T10:30:00Z" in prompt

    def test_review_handles_missing_timestamp(self):
        """Legacy notes without timestamps still render in review prompt."""
        data = self._data(notes=[
            {"id": "note-abc", "text": "Legacy note"},
        ])
        prompt = generate_review_prompt(data, "pr-001")
        assert "Legacy note" in prompt

    @patch("pm_core.prompt_gen.notes.notes_for_prompt", return_value=("", ""))
    @patch("pm_core.qa_instructions.instruction_summary_for_prompt", return_value="No instructions.")
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_qa_planner_no_notes(self, mock_root, mock_instr, mock_notes):
        data = self._data()
        prompt = generate_qa_planner_prompt(data, "pr-001")
        assert "PR Notes" not in prompt

    @patch("pm_core.prompt_gen.notes.notes_for_prompt", return_value=("", ""))
    @patch("pm_core.qa_instructions.instruction_summary_for_prompt", return_value="No instructions.")
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_qa_planner_with_notes(self, mock_root, mock_instr, mock_notes):
        """QA planner should see prior QA results from PR notes."""
        data = self._data(notes=[
            {"id": "note-abc", "text": "QA NEEDS_WORK: Login: NEEDS_WORK", "created_at": "2026-01-15T10:30:00Z"},
        ])
        prompt = generate_qa_planner_prompt(data, "pr-001")
        assert "## PR Notes" in prompt
        assert "QA NEEDS_WORK: Login: NEEDS_WORK" in prompt
        assert "2026-01-15T10:30:00Z" in prompt

    def test_qa_child_no_notes(self):
        from pm_core.qa_loop import QAScenario
        data = self._data()
        scenario = QAScenario(index=1, title="Test", focus="testing", steps="Run tests")
        prompt = generate_qa_child_prompt(data, "pr-001", scenario, "/tmp/workdir")
        assert "PR Notes" not in prompt

    def test_qa_child_with_notes(self):
        """QA child sessions should see prior QA results from PR notes."""
        from pm_core.qa_loop import QAScenario
        data = self._data(notes=[
            {"id": "note-abc", "text": "QA PASS: All passed", "created_at": "2026-01-15T10:30:00Z"},
        ])
        scenario = QAScenario(index=1, title="Test", focus="testing", steps="Run tests")
        prompt = generate_qa_child_prompt(data, "pr-001", scenario, "/tmp/workdir")
        assert "## PR Notes" in prompt
        assert "QA PASS: All passed" in prompt


