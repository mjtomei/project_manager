"""Tests designed to catch potential bugs in session resume and guide logic."""

import json
from pathlib import Path

import pytest

from pm_core.claude_launcher import (
    load_session,
    save_session,
    clear_session,
    _parse_session_id,
    SESSION_REGISTRY,
)
from pm_core.guide import (
    resolve_guide_step,
    detect_state,
    mark_step_started,
    mark_step_completed,
    STEP_ORDER,
)


@pytest.fixture
def tmp_pm_root(tmp_path):
    """Create a temporary PM root directory."""
    return tmp_path


class TestSessionRegistryBugs:
    """Tests for edge cases that might cause crashes or unexpected behavior."""

    def test_load_session_with_array_instead_of_dict(self, tmp_pm_root):
        """BUG: If registry contains a JSON array, load_session crashes."""
        registry = tmp_pm_root / SESSION_REGISTRY
        registry.write_text('["not", "a", "dict"]')
        # Should not crash, should return None
        result = load_session(tmp_pm_root, "guide:no_project")
        assert result is None

    def test_save_session_with_array_instead_of_dict(self, tmp_pm_root):
        """BUG: If registry contains a JSON array, save_session crashes."""
        registry = tmp_pm_root / SESSION_REGISTRY
        registry.write_text('["not", "a", "dict"]')
        # Should not crash, should overwrite with valid data
        save_session(tmp_pm_root, "guide:no_project", "sess-123")
        data = json.loads(registry.read_text())
        assert data["guide:no_project"]["session_id"] == "sess-123"

    def test_clear_session_with_array_instead_of_dict(self, tmp_pm_root):
        """BUG: If registry contains a JSON array, clear_session crashes."""
        registry = tmp_pm_root / SESSION_REGISTRY
        registry.write_text('["not", "a", "dict"]')
        # Should not crash
        clear_session(tmp_pm_root, "guide:no_project")

    def test_save_session_when_pm_root_missing(self, tmp_path):
        """BUG: If pm_root doesn't exist, save_session crashes."""
        missing_root = tmp_path / "does" / "not" / "exist"
        # Should this create the directory or fail gracefully?
        with pytest.raises(FileNotFoundError):
            save_session(missing_root, "key", "sess-123")

    def test_parse_session_id_with_non_string_value(self):
        """BUG: If session_id is not a string, might cause issues downstream."""
        stderr = '{"session_id": 12345}\n'
        result = _parse_session_id(stderr)
        # Should this return None or the int? Currently returns int.
        # Downstream code might expect a string.
        assert result == 12345  # Documents current behavior

    def test_parse_session_id_with_null_value(self):
        """Edge case: session_id is null."""
        stderr = '{"session_id": null}\n'
        result = _parse_session_id(stderr)
        assert result is None

    def test_parse_session_id_with_empty_string(self):
        """Edge case: session_id is empty string."""
        stderr = '{"session_id": ""}\n'
        result = _parse_session_id(stderr)
        # Empty string is falsy but still a valid return
        assert result == ""

    def test_load_session_with_empty_session_id(self, tmp_pm_root):
        """Edge case: stored session_id is empty string."""
        registry = tmp_pm_root / SESSION_REGISTRY
        registry.write_text(json.dumps({
            "guide:no_project": {"session_id": "", "timestamp": "2024-01-01T00:00:00Z"}
        }))
        result = load_session(tmp_pm_root, "guide:no_project")
        # Empty string is falsy - does this cause issues?
        assert result == ""


class TestGuideStepResolutionBugs:
    """Tests for edge cases in guide step resolution."""

    @pytest.fixture
    def pm_root_initialized(self, tmp_path):
        """PM root with just project.yaml (initialized state)."""
        root = tmp_path / "pm"
        root.mkdir()
        (root / "project.yaml").write_text(
            "project:\n  name: test\n  repo: /tmp/test\n  base_branch: main\n"
        )
        return root

    def test_started_step_not_in_step_order(self, pm_root_initialized):
        """Edge case: started_step is an invalid/unknown step name."""
        from pm_core.guide import GUIDE_STATE_FILE
        state_file = pm_root_initialized / GUIDE_STATE_FILE
        state_file.write_text(json.dumps({"started_step": "unknown_step"}))

        # Should not crash
        state, ctx = resolve_guide_step(pm_root_initialized)
        # Should fall back to detected state since started is invalid
        assert state == "initialized"

    def test_completed_step_not_in_step_order(self, pm_root_initialized):
        """Edge case: completed_step is an invalid/unknown step name."""
        from pm_core.guide import GUIDE_STATE_FILE
        state_file = pm_root_initialized / GUIDE_STATE_FILE
        state_file.write_text(json.dumps({"completed_step": "unknown_step"}))

        # Should not crash
        state, ctx = resolve_guide_step(pm_root_initialized)
        assert state == "initialized"

    def test_started_ahead_of_completed(self, pm_root_initialized):
        """Edge case: started_step is ahead of completed_step (shouldn't happen normally)."""
        from pm_core.guide import GUIDE_STATE_FILE
        state_file = pm_root_initialized / GUIDE_STATE_FILE
        # Started step 3, but only completed step 1
        state_file.write_text(json.dumps({
            "started_step": "has_plan_draft",  # step 3
            "completed_step": "no_project",     # step 1
        }))

        state, ctx = resolve_guide_step(pm_root_initialized)
        # What should happen here? Currently the completed logic takes precedence
        # and returns step 2 (initialized) since that's next after completed
        assert state == "initialized"

    def test_both_started_and_completed_none(self, pm_root_initialized):
        """When neither started nor completed is tracked."""
        state, ctx = resolve_guide_step(pm_root_initialized)
        # Should use artifact-based detection
        assert state == "initialized"

    def test_guide_state_file_is_not_json(self, pm_root_initialized):
        """Edge case: .guide-state exists but isn't valid JSON."""
        from pm_core.guide import GUIDE_STATE_FILE
        state_file = pm_root_initialized / GUIDE_STATE_FILE
        state_file.write_text("this is not json {{{")

        # Should not crash, should fall back to detection
        state, ctx = resolve_guide_step(pm_root_initialized)
        assert state == "initialized"

    def test_detect_state_with_corrupted_project_yaml(self, tmp_path):
        """Edge case: project.yaml exists but is corrupted."""
        root = tmp_path / "pm"
        root.mkdir()
        (root / "project.yaml").write_text("not: valid: yaml: {{{")

        # Should raise an error (current behavior) or handle gracefully?
        with pytest.raises(Exception):
            detect_state(root)


class TestResumeRetryLogicBugs:
    """Tests for the resume/retry logic - these document potential issues."""

    def test_retry_on_any_nonzero_exit(self):
        """
        POTENTIAL BUG: Current logic retries whenever resume_id is set and
        returncode != 0. But user might have pressed Ctrl+C (exit code 130)
        or claude might have had a legitimate error.

        We retry unnecessarily in these cases, showing the prompt twice.
        Should probably only retry on specific "invalid session" errors.
        """
        # This is a design documentation test, not an actual test
        # The fix would require checking stderr for specific error messages
        pass

    def test_tmux_path_doesnt_save_session(self):
        """
        BUG: The tmux path in _run_guide uses os.execvp which replaces the
        process. The --verbose flag is added but stderr goes to the terminal,
        not captured. Session resume can't work because session_id is never
        saved after the tmux path runs.

        The command is:
          claude --verbose ... ; pm guide done ; pm guide

        After claude exits, pm guide done runs, then pm guide runs again.
        But the session_id from claude's stderr was never captured.
        """
        # This is a design documentation test
        # Fix would require a wrapper script that captures stderr
        pass
