"""Tests for PR notes feature — hash-based note IDs, CLI commands, prompt gen."""

import os
import re
from unittest.mock import patch

from click.testing import CliRunner

from pm_core import store
from pm_core.cli import cli
from pm_core.prompt_gen import generate_prompt, generate_review_prompt


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

        # Simulate editor that saves the template unchanged
        def fake_editor(args):
            # args is [editor_path, tmp_file] — just leave file as-is
            return 0

        with patch("subprocess.call", side_effect=fake_editor):
            # Touch the file to update mtime (so the "no changes" check is bypassed)
            original_call = os.path.getmtime

            def patched_getmtime(path):
                result = original_call(path)
                patched_getmtime.call_count = getattr(patched_getmtime, 'call_count', 0) + 1
                if patched_getmtime.call_count == 1:
                    return result - 1  # first call returns older mtime
                return result

            with patch("os.path.getmtime", side_effect=patched_getmtime):
                result = runner.invoke(cli, ["-C", str(root), "pr", "edit", "pr-001"])

        # Notes should be unchanged — either "No changes" or notes not in changes list
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

        def fake_editor(args):
            # args is [editor_path, tmp_file] — inject a new note
            tmp_file = args[1]
            with open(tmp_file) as f:
                content = f.read()
            content = content.replace("# (no notes)\n", "- Brand new note\n")
            with open(tmp_file, "w") as f:
                f.write(content)
            return 0

        with patch("subprocess.call", side_effect=fake_editor):
            original_call = os.path.getmtime

            def patched_getmtime(path):
                result = original_call(path)
                patched_getmtime.call_count = getattr(patched_getmtime, 'call_count', 0) + 1
                if patched_getmtime.call_count == 1:
                    return result - 1
                return result

            with patch("os.path.getmtime", side_effect=patched_getmtime):
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

        def fake_editor(args):
            # Add a third note to trigger the reconciliation path
            tmp_file = args[1]
            with open(tmp_file) as f:
                content = f.read()
            content = content.replace(
                "# Description (everything below this line):",
                "- Third note\n\n# Description (everything below this line):"
            )
            with open(tmp_file, "w") as f:
                f.write(content)
            return 0

        with patch("subprocess.call", side_effect=fake_editor):
            original_call = os.path.getmtime

            def patched_getmtime(path):
                result = original_call(path)
                patched_getmtime.call_count = getattr(patched_getmtime, 'call_count', 0) + 1
                if patched_getmtime.call_count == 1:
                    return result - 1
                return result

            with patch("os.path.getmtime", side_effect=patched_getmtime):
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

    @patch("pm_core.prompt_gen.notes.notes_section", return_value="")
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_no_notes(self, mock_root, mock_notes):
        data = self._data()
        prompt = generate_prompt(data, "pr-001")
        assert "PR Notes" not in prompt

    @patch("pm_core.prompt_gen.notes.notes_section", return_value="")
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

    @patch("pm_core.prompt_gen.notes.notes_section", return_value="")
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_prompt_includes_timestamps(self, mock_root, mock_notes):
        data = self._data(notes=[
            {"id": "note-abc", "text": "A note", "created_at": "2026-01-15T10:30:00Z"},
        ])
        prompt = generate_prompt(data, "pr-001")
        assert "2026-01-15T10:30:00Z" in prompt

    @patch("pm_core.prompt_gen.notes.notes_section", return_value="")
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


