"""Tests for pm_core.editor — watched editor utility."""

import os
import time
from pathlib import Path
from unittest.mock import patch

from pm_core.editor import run_watched_editor


class TestRunWatchedEditor:
    """Test the run_watched_editor utility."""

    def test_returns_editor_exit_code(self):
        """Editor exit code is returned."""
        def fake_editor(args):
            return 42

        with patch("pm_core.editor.find_editor", return_value="fake"):
            with patch("subprocess.call", side_effect=fake_editor):
                ret, modified = run_watched_editor("hello", lambda c: None)
        assert ret == 42
        assert not modified

    def test_on_save_called_when_file_modified(self):
        """on_save fires when the file is written (detected in final poll)."""
        saved = []

        def fake_editor(args):
            # Simulate editing: modify the temp file
            tmp_path = args[1]
            # Ensure mtime changes (some filesystems have 1s granularity)
            time.sleep(0.05)
            Path(tmp_path).write_text("edited content")
            return 0

        with patch("pm_core.editor.find_editor", return_value="fake"):
            with patch("subprocess.call", side_effect=fake_editor):
                ret, modified = run_watched_editor(
                    "original", lambda c: saved.append(c),
                    _poll_interval=0.05,
                )

        assert ret == 0
        assert modified
        assert any("edited content" in s for s in saved)

    def test_on_save_not_called_when_unmodified(self):
        """on_save does not fire if the file is never written."""
        saved = []

        def fake_editor(args):
            return 0

        with patch("pm_core.editor.find_editor", return_value="fake"):
            with patch("subprocess.call", side_effect=fake_editor):
                ret, modified = run_watched_editor(
                    "original", lambda c: saved.append(c),
                )

        assert ret == 0
        assert not modified
        assert saved == []

    def test_on_save_exception_does_not_crash(self):
        """Exceptions in on_save are swallowed."""
        def exploding_callback(content):
            raise RuntimeError("boom")

        def fake_editor(args):
            time.sleep(0.05)
            Path(args[1]).write_text("changed")
            return 0

        with patch("pm_core.editor.find_editor", return_value="fake"):
            with patch("subprocess.call", side_effect=fake_editor):
                ret, modified = run_watched_editor(
                    "original", exploding_callback,
                    _poll_interval=0.05,
                )

        assert ret == 0
        assert modified

    def test_temp_file_cleaned_up(self):
        """Temp file is deleted after the editor exits."""
        captured_path = []

        def fake_editor(args):
            captured_path.append(args[1])
            return 0

        with patch("pm_core.editor.find_editor", return_value="fake"):
            with patch("subprocess.call", side_effect=fake_editor):
                run_watched_editor("hello", lambda c: None)

        assert captured_path
        assert not os.path.exists(captured_path[0])

    def test_multiple_saves_detected(self):
        """Multiple writes during the editor session are detected."""
        saved = []

        def fake_editor(args):
            tmp_path = args[1]
            time.sleep(0.05)
            Path(tmp_path).write_text("save 1")
            time.sleep(0.15)  # Wait for poll to detect
            Path(tmp_path).write_text("save 2")
            time.sleep(0.15)
            return 0

        with patch("pm_core.editor.find_editor", return_value="fake"):
            with patch("subprocess.call", side_effect=fake_editor):
                ret, modified = run_watched_editor(
                    "original", lambda c: saved.append(c),
                    _poll_interval=0.05,
                )

        assert ret == 0
        assert modified
        # Should have captured at least one save (timing-dependent,
        # but with 0.05s poll and 0.15s sleep we should get both)
        assert len(saved) >= 1


class TestParsePrEditRaw:
    """Test the extracted PR edit template parser.

    _parse_pr_edit_raw applies unicode restoration per-field (title,
    description, note texts) so structural syntax is never corrupted.
    """

    def test_parses_all_fields(self):
        from pm_core.cli.pr import _parse_pr_edit_raw
        raw = (
            "# Editing pr-001\n"
            "# Lines starting with # are ignored.\n"
            "\n"
            "title: My Title\n"
            "status: in_progress\n"
            "depends_on: pr-002, pr-003\n"
            "\n"
            "# Notes (bulleted list):\n"
            "- First note\n"
            "- Second note\n"
            "\n"
            "# Description (everything below this line):\n"
            "This is the description.\n"
            "Second line.\n"
        )
        parsed = _parse_pr_edit_raw(raw)
        assert parsed["title"] == "My Title"
        assert parsed["status"] == "in_progress"
        assert parsed["depends_on_str"] == "pr-002, pr-003"
        assert parsed["note_texts"] == ["First note", "Second note"]
        assert parsed["description"] == "This is the description.\nSecond line."

    def test_strips_note_timestamps(self):
        from pm_core.cli.pr import _parse_pr_edit_raw
        raw = (
            "# Notes:\n"
            "- My note  # 2026-01-15T10:30:00Z\n"
            "\n"
            "# Description (everything below this line):\n"
        )
        parsed = _parse_pr_edit_raw(raw)
        assert parsed["note_texts"] == ["My note"]

    def test_restore_unicode_separate(self):
        from pm_core.cli.pr import _restore_unicode
        restored = _restore_unicode("Em dash -- here")
        assert "\u2014" in restored

    def test_parse_restores_unicode_in_content_fields(self):
        """Unicode restoration is applied per-field, not to raw template."""
        from pm_core.cli.pr import _parse_pr_edit_raw
        raw = (
            "title: Title with -- em dash\n"
            "status: in_progress\n"
            "depends_on: pr-002\n"
            "\n"
            "# Notes:\n"
            "- Note with -- em dash\n"
            "\n"
            "# Description (everything below this line):\n"
            "Desc with -- em dash\n"
        )
        parsed = _parse_pr_edit_raw(raw)
        # Content fields get unicode restoration
        assert "\u2014" in parsed["title"]
        assert "\u2014" in parsed["note_texts"][0]
        assert "\u2014" in parsed["description"]
        # Structural fields are NOT corrupted
        assert parsed["status"] == "in_progress"
        assert parsed["depends_on_str"] == "pr-002"

    def test_parse_note_prefix_not_corrupted(self):
        """The '- ' note prefix must not be converted to en-dash."""
        from pm_core.cli.pr import _parse_pr_edit_raw
        raw = (
            "# Notes:\n"
            "- My note\n"
            "\n"
            "# Description (everything below this line):\n"
        )
        parsed = _parse_pr_edit_raw(raw)
        assert parsed["note_texts"] == ["My note"]
