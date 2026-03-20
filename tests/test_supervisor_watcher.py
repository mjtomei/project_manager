"""Tests for supervisor watcher: SupervisorWatcher and feedback logging."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pm_core.watchers.supervisor_watcher import (
    SupervisorWatcher,
    _EXCLUDED_WINDOWS,
    _MAX_FEEDBACK_PER_ITERATION,
)
from pm_core.supervisor_feedback import (
    FeedbackEntry,
    log_feedback,
    read_feedback_log,
    format_feedback_log,
    SUPERVISOR_LOG_DIR,
)
from pm_core.watcher_base import WatcherState


# --- SupervisorWatcher class configuration ---

class TestSupervisorWatcherConfig:
    """Test SupervisorWatcher class-level attributes."""

    def test_watcher_type(self):
        assert SupervisorWatcher.WATCHER_TYPE == "supervisor"

    def test_display_name(self):
        assert SupervisorWatcher.DISPLAY_NAME == "Supervisor Watcher"

    def test_window_name(self):
        assert SupervisorWatcher.WINDOW_NAME == "supervisor"

    def test_default_interval(self):
        assert SupervisorWatcher.DEFAULT_INTERVAL == 180

    def test_verdicts(self):
        assert "CONTINUE" in SupervisorWatcher.VERDICTS
        assert "FEEDBACK_SENT" in SupervisorWatcher.VERDICTS
        assert "NO_ISSUES" in SupervisorWatcher.VERDICTS
        assert "INPUT_REQUIRED" in SupervisorWatcher.VERDICTS

    def test_high_effort_grace_period(self):
        assert SupervisorWatcher.VERDICT_GRACE_PERIOD == 45

    def test_should_continue_verdicts(self):
        w = SupervisorWatcher(pm_root="")
        assert w.should_continue("CONTINUE") is True
        assert w.should_continue("FEEDBACK_SENT") is True
        assert w.should_continue("NO_ISSUES") is True
        assert w.should_continue("INPUT_REQUIRED") is False
        assert w.should_continue("UNKNOWN") is False


# --- Target discovery ---

class TestTargetDiscovery:
    """Test SupervisorWatcher.discover_targets()."""

    def _make_watcher(self, target_filter=None):
        return SupervisorWatcher(pm_root="", target_filter=target_filter)

    @patch("pm_core.loop_shared.get_pm_session", return_value="test-session")
    def test_excludes_infrastructure_windows(self, mock_session):
        w = self._make_watcher()
        windows = [
            {"id": "@1", "index": "1", "name": "tui"},
            {"id": "@2", "index": "2", "name": "watcher"},
            {"id": "@3", "index": "3", "name": "supervisor"},
            {"id": "@4", "index": "4", "name": "repl"},
            {"id": "@5", "index": "5", "name": "pr-abc-impl"},
        ]
        with patch("pm_core.tmux.list_windows", return_value=windows), \
             patch("pm_core.tmux.get_pane_indices", return_value=[("%5", 0)]), \
             patch("pm_core.tmux.capture_pane", return_value="some output"):
            targets = w.discover_targets()
        assert len(targets) == 1
        assert targets[0]["window_name"] == "pr-abc-impl"

    @patch("pm_core.loop_shared.get_pm_session", return_value="test-session")
    def test_target_filter(self, mock_session):
        w = self._make_watcher(target_filter="pr-abc")
        windows = [
            {"id": "@1", "index": "1", "name": "pr-abc-impl"},
            {"id": "@2", "index": "2", "name": "pr-def-impl"},
        ]
        with patch("pm_core.tmux.list_windows", return_value=windows), \
             patch("pm_core.tmux.get_pane_indices", return_value=[("%1", 0)]), \
             patch("pm_core.tmux.capture_pane", return_value="output"):
            targets = w.discover_targets()
        assert len(targets) == 1
        assert targets[0]["window_name"] == "pr-abc-impl"

    @patch("pm_core.loop_shared.get_pm_session", return_value=None)
    def test_no_session(self, mock_session):
        w = self._make_watcher()
        targets = w.discover_targets()
        assert targets == []

    @patch("pm_core.loop_shared.get_pm_session", return_value="test-session")
    def test_skips_empty_panes(self, mock_session):
        w = self._make_watcher()
        windows = [{"id": "@1", "index": "1", "name": "pr-abc"}]
        with patch("pm_core.tmux.list_windows", return_value=windows), \
             patch("pm_core.tmux.get_pane_indices", return_value=[("%1", 0)]), \
             patch("pm_core.tmux.capture_pane", return_value=""):
            targets = w.discover_targets()
        assert targets == []


# --- Verdict parsing ---

class TestSupervisorVerdictParsing:
    """Test SupervisorWatcher.parse_verdict()."""

    def test_feedback_sent(self):
        w = SupervisorWatcher(pm_root="")
        output = 'some analysis\n\nFEEDBACK_SENT\n'
        assert w.parse_verdict(output) == "FEEDBACK_SENT"

    def test_no_issues(self):
        w = SupervisorWatcher(pm_root="")
        output = 'all looks good\n\nNO_ISSUES\n'
        assert w.parse_verdict(output) == "NO_ISSUES"

    def test_continue(self):
        w = SupervisorWatcher(pm_root="")
        output = 'will check again\n\nCONTINUE\n'
        assert w.parse_verdict(output) == "CONTINUE"

    def test_input_required(self):
        w = SupervisorWatcher(pm_root="")
        output = 'need help\n\nINPUT_REQUIRED\n'
        assert w.parse_verdict(output) == "INPUT_REQUIRED"

    def test_default_with_feedback_blocks(self):
        w = SupervisorWatcher(pm_root="")
        output = (
            'analysis\n'
            '```json\n'
            '{"target_window": "pr-abc", "observation": "bug", "feedback": "fix it"}\n'
            '```\n'
        )
        assert w.parse_verdict(output) == "FEEDBACK_SENT"

    def test_default_no_feedback(self):
        w = SupervisorWatcher(pm_root="")
        output = 'some random text without verdict\n'
        assert w.parse_verdict(output) == "NO_ISSUES"


# --- Feedback extraction ---

class TestFeedbackExtraction:
    """Test SupervisorWatcher._extract_feedback()."""

    def test_extracts_json_feedback(self):
        output = (
            'Analysis:\n\n'
            '```json\n'
            '{"target_window": "pr-abc", "observation": "missing test", "feedback": "add edge case test"}\n'
            '```\n\n'
            'FEEDBACK_SENT\n'
        )
        feedback = SupervisorWatcher._extract_feedback(output)
        assert len(feedback) == 1
        assert feedback[0]["target_window"] == "pr-abc"
        assert feedback[0]["observation"] == "missing test"
        assert feedback[0]["feedback"] == "add edge case test"

    def test_extracts_multiple_feedback(self):
        output = (
            '{"target_window": "a", "observation": "o1", "feedback": "f1"}\n'
            '{"target_window": "b", "observation": "o2", "feedback": "f2"}\n'
        )
        feedback = SupervisorWatcher._extract_feedback(output)
        assert len(feedback) == 2

    def test_skips_invalid_json(self):
        output = (
            '{"target_window": "a", "observation": "o1", "feedback": "f1"}\n'
            '{invalid json}\n'
        )
        feedback = SupervisorWatcher._extract_feedback(output)
        assert len(feedback) == 1

    def test_skips_incomplete_json(self):
        output = '{"target_window": "a", "other_key": "value"}\n'
        feedback = SupervisorWatcher._extract_feedback(output)
        assert len(feedback) == 0

    def test_empty_output(self):
        feedback = SupervisorWatcher._extract_feedback("")
        assert feedback == []


# --- Feedback logging ---

class TestFeedbackLogging:
    """Test supervisor_feedback module."""

    def test_log_and_read(self, tmp_path):
        log_dir = tmp_path / "logs" / "supervisor"
        with patch("pm_core.supervisor_feedback.SUPERVISOR_LOG_DIR", log_dir):
            entry = FeedbackEntry(
                timestamp="2026-03-14T10:00:00",
                supervisor_id="supervisor-abc",
                target_window="pr-xyz-impl",
                target_pane="%5",
                observation="bug in error handling",
                feedback="add try/except around the API call",
                injected=True,
            )
            log_path = log_feedback(entry)
            assert log_path.exists()

            # Read back and assert round-trip inside the patch context
            entries = read_feedback_log(supervisor_id="supervisor-abc")
            assert len(entries) == 1
            assert entries[0].supervisor_id == "supervisor-abc"
            assert entries[0].target_window == "pr-xyz-impl"
            assert entries[0].injected is True

    def test_read_with_target_filter(self, tmp_path):
        log_dir = tmp_path / "logs" / "supervisor"
        log_dir.mkdir(parents=True)

        # Write two entries to a log file
        log_file = log_dir / "sup-123.jsonl"
        entries_data = [
            {"timestamp": "t1", "supervisor_id": "sup-123",
             "target_window": "pr-abc", "target_pane": "%1",
             "observation": "o1", "feedback": "f1", "injected": True},
            {"timestamp": "t2", "supervisor_id": "sup-123",
             "target_window": "pr-def", "target_pane": "%2",
             "observation": "o2", "feedback": "f2", "injected": False},
        ]
        log_file.write_text("\n".join(json.dumps(e) for e in entries_data) + "\n")

        with patch("pm_core.supervisor_feedback.SUPERVISOR_LOG_DIR", log_dir):
            # Filter by target
            result = read_feedback_log(target_filter="pr-abc")
            assert len(result) == 1
            assert result[0].target_window == "pr-abc"

            # No filter
            result = read_feedback_log()
            assert len(result) == 2

    def test_format_feedback_log_empty(self):
        assert format_feedback_log([]) == "No supervisor feedback found."

    def test_format_feedback_log_entries(self):
        entries = [
            FeedbackEntry(
                timestamp="2026-03-14T10:00:00.123",
                supervisor_id="sup-1",
                target_window="pr-abc",
                target_pane="%1",
                observation="found bug",
                feedback="fix the bug",
                injected=True,
            )
        ]
        output = format_feedback_log(entries)
        assert "sup-1" in output
        assert "pr-abc" in output
        assert "found bug" in output
        assert "fix the bug" in output
        assert "Injected: yes" in output


# --- Feedback injection (on_verdict) ---

class TestFeedbackInjection:
    """Test SupervisorWatcher.on_verdict() feedback injection."""

    @patch("pm_core.loop_shared.get_pm_session", return_value="test-session")
    @patch("pm_core.watchers.supervisor_watcher.log_feedback")
    def test_injects_feedback_via_send_keys(self, mock_log, mock_session):
        w = SupervisorWatcher(pm_root="")
        w._pending_feedback = [
            {"target_window": "pr-abc", "observation": "bug", "feedback": "fix it"},
        ]

        with patch("pm_core.tmux.find_window_by_name",
                    return_value={"id": "@1", "index": "1", "name": "pr-abc"}), \
             patch("pm_core.tmux.get_pane_indices", return_value=[("%5", 0)]), \
             patch("pm_core.tmux.send_keys") as mock_send:
            w.on_verdict("FEEDBACK_SENT", "output")

        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert "%5" in call_args[0]
        assert "[SUPERVISOR FEEDBACK]" in call_args[0][1]
        mock_log.assert_called_once()

    @patch("pm_core.loop_shared.get_pm_session", return_value="test-session")
    @patch("pm_core.watchers.supervisor_watcher.log_feedback")
    def test_logs_even_when_injection_fails(self, mock_log, mock_session):
        w = SupervisorWatcher(pm_root="")
        w._pending_feedback = [
            {"target_window": "pr-abc", "observation": "bug", "feedback": "fix it"},
        ]

        with patch("pm_core.tmux.find_window_by_name", return_value=None):
            w.on_verdict("FEEDBACK_SENT", "output")

        # Should still log, just with injected=False
        mock_log.assert_called_once()
        entry = mock_log.call_args[0][0]
        assert entry.injected is False

    def test_no_pending_feedback_is_noop(self):
        w = SupervisorWatcher(pm_root="")
        w._pending_feedback = []
        # Should not raise
        w.on_verdict("NO_ISSUES", "output")


# --- Prompt generation ---

class TestSupervisorPromptGeneration:
    """Test SupervisorWatcher.generate_prompt()."""

    @patch("pm_core.loop_shared.get_pm_session", return_value="test-session")
    def test_no_targets_prompt(self, mock_session):
        w = SupervisorWatcher(pm_root="")
        with patch("pm_core.tmux.list_windows", return_value=[]):
            prompt = w.generate_prompt(1)
        assert "No active target sessions" in prompt
        assert "NO_ISSUES" in prompt

    @patch("pm_core.loop_shared.get_pm_session", return_value="test-session")
    def test_prompt_includes_targets(self, mock_session):
        w = SupervisorWatcher(pm_root="")
        windows = [{"id": "@1", "index": "1", "name": "pr-abc-impl"}]
        with patch("pm_core.tmux.list_windows", return_value=windows), \
             patch("pm_core.tmux.get_pane_indices", return_value=[("%1", 0)]), \
             patch("pm_core.tmux.capture_pane", return_value="doing some work"):
            prompt = w.generate_prompt(1)
        assert "pr-abc-impl" in prompt
        assert "doing some work" in prompt
        assert "senior engineer" in prompt


# --- Build launch command ---

class TestBuildLaunchCmd:
    """Test SupervisorWatcher.build_launch_cmd()."""

    def test_basic_command(self):
        w = SupervisorWatcher(pm_root="")
        cmd = w.build_launch_cmd(1)
        assert "supervisor-iter" in cmd
        assert "--iteration" in cmd
        assert "1" in cmd

    def test_includes_window_name(self):
        w = SupervisorWatcher(pm_root="")
        cmd = w.build_launch_cmd(1)
        assert "--window-name" in cmd
        assert w.WINDOW_NAME in cmd

    def test_with_target_filter(self):
        w = SupervisorWatcher(pm_root="", target_filter="pr-abc")
        cmd = w.build_launch_cmd(1)
        assert "--target" in cmd
        assert "pr-abc" in cmd

    def test_with_transcript(self):
        w = SupervisorWatcher(pm_root="")
        cmd = w.build_launch_cmd(1, transcript="/tmp/test.jsonl")
        assert "--transcript" in cmd
        assert "/tmp/test.jsonl" in cmd

    def test_multiple_instances_have_unique_window_names(self):
        """Multiple supervisor instances must not share a window name."""
        w1 = SupervisorWatcher(pm_root="")
        w2 = SupervisorWatcher(pm_root="")
        assert w1.WINDOW_NAME != w2.WINDOW_NAME


# --- Watcher registry ---

class TestSupervisorRegistry:
    """Test that supervisor is properly registered."""

    def test_in_registry(self):
        from pm_core.watchers import WATCHER_REGISTRY
        assert "supervisor" in WATCHER_REGISTRY
        assert WATCHER_REGISTRY["supervisor"] is SupervisorWatcher

    def test_get_watcher_class(self):
        from pm_core.watchers import get_watcher_class
        cls = get_watcher_class("supervisor")
        assert cls is SupervisorWatcher

    def test_list_watcher_types(self):
        from pm_core.watchers import list_watcher_types
        types = list_watcher_types()
        type_names = [t["type"] for t in types]
        assert "supervisor" in type_names


# --- Model config ---

class TestSupervisorModelConfig:
    """Test supervisor session type in model config."""

    def test_session_type_registered(self):
        from pm_core.model_config import SESSION_TYPES
        assert "supervisor" in SESSION_TYPES

    def test_fallback_to_watcher(self):
        from pm_core.model_config import _FALLBACK_TYPES
        assert _FALLBACK_TYPES.get("supervisor") == "watcher"

    def test_default_high_effort(self):
        from pm_core.model_config import DEFAULT_SESSION_EFFORT
        assert DEFAULT_SESSION_EFFORT.get("supervisor") == "high"

    def test_resolve_high_effort(self):
        from pm_core.model_config import resolve_model_and_provider
        # Clear env vars and global settings that could override effort
        with patch.dict(os.environ, {}, clear=False):
            env = os.environ.copy()
            env.pop("PM_EFFORT", None)
            env.pop("PM_MODEL", None)
            with patch.dict(os.environ, env, clear=True), \
                 patch("pm_core.model_config.get_global_setting_value", return_value=None):
                resolution = resolve_model_and_provider("supervisor")
                assert resolution.effort == "high"
