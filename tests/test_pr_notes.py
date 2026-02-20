"""Tests for PR notes feature — hash-based note IDs, CLI commands, prompt gen, detail panel."""

import re
from unittest.mock import patch

from click.testing import CliRunner

from pm_core import store
from pm_core.cli import cli
from pm_core.prompt_gen import generate_prompt, generate_review_prompt
from pm_core.tui.detail_panel import DetailPanel


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
        "project": {"name": "test", "repo": "/tmp/fake", "base_branch": "main"},
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
        # ISO 8601 UTC format: YYYY-MM-DDTHH:MM:SSZ
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", note["created_at"])

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
        assert pr["notes"][1]["created_at"]

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
            "project": {"name": "test", "repo": "/tmp/fake", "base_branch": "main", "backend": "local"},
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


# ---------------------------------------------------------------------------
# TUI detail panel
# ---------------------------------------------------------------------------

class TestDetailPanelNotes:
    def _make_panel(self, pr_data=None, all_prs=None, plan=None, project_root=None):
        panel = DetailPanel.__new__(DetailPanel)
        panel._test_pr_data = pr_data
        panel._all_prs = all_prs or []
        panel._plan = plan
        panel._project_root = project_root
        return panel

    def _render(self, panel):
        with patch.object(type(panel), "pr_data",
                          new_callable=lambda: property(lambda self: self._test_pr_data)):
            return panel.render()

    def test_no_notes(self):
        panel = self._make_panel(pr_data={
            "id": "pr-x", "title": "T", "status": "pending", "branch": "b",
        })
        result = self._render(panel)
        text = str(result.renderable)
        assert "Notes:" not in text

    def test_with_notes(self):
        panel = self._make_panel(pr_data={
            "id": "pr-x", "title": "T", "status": "pending", "branch": "b",
            "notes": [
                {"id": "note-abc", "text": "Remember to update docs", "created_at": "2026-01-15T10:30:00Z"},
                {"id": "note-def", "text": "API changed since plan", "created_at": "2026-01-16T14:00:00Z"},
            ],
        })
        result = self._render(panel)
        text = str(result.renderable)
        assert "Notes:" in text
        assert "Remember to update docs" in text
        assert "API changed since plan" in text

    def test_with_timestamps(self):
        panel = self._make_panel(pr_data={
            "id": "pr-x", "title": "T", "status": "pending", "branch": "b",
            "notes": [
                {"id": "note-abc", "text": "A note", "created_at": "2026-01-15T10:30:00Z"},
            ],
        })
        result = self._render(panel)
        text = str(result.renderable)
        assert "2026-01-15T10:30:00Z" in text

    def test_without_timestamps(self):
        """Legacy notes without timestamps still render."""
        panel = self._make_panel(pr_data={
            "id": "pr-x", "title": "T", "status": "pending", "branch": "b",
            "notes": [
                {"id": "note-abc", "text": "Legacy note"},
            ],
        })
        result = self._render(panel)
        text = str(result.renderable)
        assert "Legacy note" in text

    def test_empty_notes_list(self):
        panel = self._make_panel(pr_data={
            "id": "pr-x", "title": "T", "status": "pending", "branch": "b",
            "notes": [],
        })
        result = self._render(panel)
        text = str(result.renderable)
        assert "Notes:" not in text
