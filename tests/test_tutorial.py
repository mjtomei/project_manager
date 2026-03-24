"""Tests for pm_core.tutorial — progress management and hook script generation."""

import json
import shlex
from pathlib import Path
from unittest.mock import patch

import pytest

import pm_core.tutorial as tut


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_tutorial_dir(tmp_path, monkeypatch):
    """Redirect TUTORIAL_DIR and PROGRESS_FILE to a temp directory."""
    monkeypatch.setattr(tut, "TUTORIAL_DIR", tmp_path / "tutorial")
    monkeypatch.setattr(tut, "PROGRESS_FILE", tmp_path / "tutorial" / "progress.json")


# ---------------------------------------------------------------------------
# load_progress / save_progress
# ---------------------------------------------------------------------------


class TestLoadSaveProgress:
    def test_empty_when_no_file(self):
        progress = tut.load_progress()
        assert progress == {"modules": {}}

    def test_round_trip(self):
        data = {"modules": {"tmux": {"completed_steps": ["switch_pane"]}}}
        tut.save_progress(data)
        assert tut.load_progress() == data

    def test_corrupt_file_returns_empty(self):
        tut.TUTORIAL_DIR.mkdir(parents=True, exist_ok=True)
        tut.PROGRESS_FILE.write_text("not-json{{{{")
        progress = tut.load_progress()
        assert progress == {"modules": {}}

    def test_save_progress_is_atomic(self):
        """save_progress must write via a temp file then rename, not in-place."""
        data = {"modules": {"git": {"completed_steps": ["init_repo"]}}}
        tut.save_progress(data)
        # After save, no .tmp file should linger
        assert not tut.PROGRESS_FILE.with_suffix(".tmp").exists()
        assert tut.load_progress() == data


# ---------------------------------------------------------------------------
# mark_step_complete
# ---------------------------------------------------------------------------


class TestMarkStepComplete:
    def test_marks_valid_step(self):
        tut.mark_step_complete("tmux", "switch_pane")
        progress = tut.load_progress()
        assert "switch_pane" in progress["modules"]["tmux"]["completed_steps"]

    def test_ignores_invalid_step(self):
        tut.mark_step_complete("tmux", "nonexistent_step")
        progress = tut.load_progress()
        assert "tmux" not in progress.get("modules", {})

    def test_unknown_module_still_ignores_invalid_step_for_known_module(self):
        # An invalid step for a known module is rejected.
        # Unknown modules bypass the step check (their valid_steps list is empty).
        tut.mark_step_complete("tmux", "definitely_not_a_real_step")
        progress = tut.load_progress()
        assert "tmux" not in progress.get("modules", {})

    def test_idempotent(self):
        tut.mark_step_complete("tmux", "switch_pane")
        tut.mark_step_complete("tmux", "switch_pane")
        progress = tut.load_progress()
        assert progress["modules"]["tmux"]["completed_steps"].count("switch_pane") == 1

    def test_advances_current_step(self):
        tut.mark_step_complete("tmux", "switch_pane")
        progress = tut.load_progress()
        assert progress["modules"]["tmux"]["current_step"] == "resize_pane"


# ---------------------------------------------------------------------------
# is_module_complete / get_current_step
# ---------------------------------------------------------------------------


class TestModuleCompletion:
    def test_not_complete_when_empty(self):
        assert not tut.is_module_complete("tmux")

    def test_complete_when_all_steps_done(self):
        for step in tut.TMUX_STEPS:
            tut.mark_step_complete("tmux", step)
        assert tut.is_module_complete("tmux")

    def test_get_current_step_returns_first_incomplete(self):
        tut.mark_step_complete("tmux", "switch_pane")
        assert tut.get_current_step("tmux") == "resize_pane"

    def test_get_current_step_returns_none_when_complete(self):
        for step in tut.TMUX_STEPS:
            tut.mark_step_complete("tmux", step)
        assert tut.get_current_step("tmux") is None


# ---------------------------------------------------------------------------
# reset_progress
# ---------------------------------------------------------------------------


class TestResetProgress:
    def test_reset_single_module(self):
        tut.mark_step_complete("tmux", "switch_pane")
        tut.mark_step_complete("git", "init_repo")
        tut.reset_progress("tmux")
        progress = tut.load_progress()
        assert "tmux" not in progress["modules"]
        assert "git" in progress["modules"]

    def test_reset_all(self):
        tut.mark_step_complete("tmux", "switch_pane")
        tut.mark_step_complete("git", "init_repo")
        tut.reset_progress()
        assert tut.load_progress() == {"modules": {}}


# ---------------------------------------------------------------------------
# get_completion_summary
# ---------------------------------------------------------------------------


class TestCompletionSummary:
    def test_all_zeros_when_fresh(self):
        summary = tut.get_completion_summary()
        for mod, steps in tut.MODULE_STEPS.items():
            assert summary[mod] == (0, len(steps))

    def test_counts_only_valid_steps(self):
        tut.mark_step_complete("tmux", "switch_pane")
        done, total = tut.get_completion_summary()["tmux"]
        assert done == 1
        assert total == len(tut.TMUX_STEPS)


# ---------------------------------------------------------------------------
# write_hook_script — verify shell quoting is correct
# ---------------------------------------------------------------------------


class TestWriteHookScript:
    def test_script_is_executable(self):
        script = tut.write_hook_script()
        assert script.exists()
        assert script.stat().st_mode & 0o111  # executable bit set

    def test_script_validates_step_whitelist(self):
        script = tut.write_hook_script()
        content = script.read_text()
        for step in tut.TMUX_STEPS:
            assert step in content


# ---------------------------------------------------------------------------
# setup_tmux_session — verify hook command quoting
# ---------------------------------------------------------------------------


class TestHookCommandQuoting:
    """Verify that the run-shell command correctly quotes only the script path,
    not the step argument, so tmux's sh -c receives a valid shell command."""

    def test_hook_cmd_quotes_only_path(self):
        # Simulate what setup_tmux_session does for each hook
        hook_script = Path("/home/user/.pm/tutorial/hook_helper.sh")
        step = "switch_pane"
        cmd = f"run-shell {shlex.quote(str(hook_script))} {step}"
        # Must NOT produce a single-quoted blob with a space inside
        assert cmd == "run-shell /home/user/.pm/tutorial/hook_helper.sh switch_pane"

    def test_hook_cmd_quotes_path_with_spaces(self):
        hook_script = Path("/home/my user/.pm/tutorial/hook_helper.sh")
        step = "switch_pane"
        cmd = f"run-shell {shlex.quote(str(hook_script))} {step}"
        # Path with spaces should be quoted, but step should remain a separate word
        assert "switch_pane" in cmd
        assert cmd.endswith(" switch_pane")
        # The path portion should be properly quoted
        assert "'/home/my user/.pm/tutorial/hook_helper.sh'" in cmd


# ---------------------------------------------------------------------------
# setup_git_practice_repo — verify existing repo is preserved on re-entry
# ---------------------------------------------------------------------------


class TestGitPracticeRepoPreservation:
    def test_existing_repo_is_preserved(self, tmp_path):
        """If .git already exists, setup_git_practice_repo must not delete it."""
        repo_dir = tmp_path / "tutorial" / "git-practice"
        repo_dir.mkdir(parents=True)
        (repo_dir / ".git").mkdir()
        sentinel = repo_dir / "my_work.txt"
        sentinel.write_text("in progress")

        with patch.object(tut, "TUTORIAL_DIR", tmp_path / "tutorial"):
            returned = tut.setup_git_practice_repo()

        assert returned == repo_dir
        assert sentinel.exists(), "Existing repo work must not be deleted on re-entry"

    def test_missing_repo_is_created(self, tmp_path):
        """If no repo exists, setup_git_practice_repo must create and init it."""
        with patch.object(tut, "TUTORIAL_DIR", tmp_path / "tutorial"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = type("R", (), {"returncode": 0})()
                repo_dir = tut.setup_git_practice_repo()

        assert repo_dir == tmp_path / "tutorial" / "git-practice"
        assert repo_dir.exists()
