"""Tests for the loop guard functionality."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pm_core.cli import loop_guard_cmd


@pytest.fixture
def loop_file(tmp_path):
    """Create a temp directory for loop guard files."""
    with patch.object(Path, 'home', return_value=tmp_path):
        loop_dir = tmp_path / ".pm-pane-registry"
        loop_dir.mkdir(parents=True, exist_ok=True)
        yield tmp_path


class TestLoopGuard:
    def test_first_run_succeeds(self, loop_file):
        """First run should succeed (no prior timestamps)."""
        runner = CliRunner()
        with patch.object(Path, 'home', return_value=loop_file):
            with patch('time.sleep'):  # Don't actually sleep in tests
                result = runner.invoke(loop_guard_cmd, ['test-loop'])
        assert result.exit_code == 0

    def test_few_restarts_succeed(self, loop_file):
        """A few restarts should succeed."""
        runner = CliRunner()
        loop_path = loop_file / ".pm-pane-registry" / "loop-test-loop.json"

        # Simulate 3 prior restarts spread over time
        now = time.time()
        timestamps = [now - 10, now - 7, now - 4]
        loop_path.write_text(json.dumps(timestamps))

        with patch.object(Path, 'home', return_value=loop_file):
            with patch('time.sleep'):
                result = runner.invoke(loop_guard_cmd, ['test-loop'])
        assert result.exit_code == 0

    def test_rapid_restarts_blocked(self, loop_file):
        """5 restarts in <7 seconds should be blocked."""
        runner = CliRunner()
        loop_path = loop_file / ".pm-pane-registry" / "loop-test-loop.json"

        # Simulate 4 very recent restarts (5th will be the current one)
        now = time.time()
        timestamps = [now - 3, now - 2.5, now - 2, now - 1]
        loop_path.write_text(json.dumps(timestamps))

        with patch.object(Path, 'home', return_value=loop_file):
            with patch('time.sleep'):
                result = runner.invoke(loop_guard_cmd, ['test-loop'])

        assert result.exit_code == 1
        assert "Loop guard triggered" in result.output

    def test_old_timestamps_ignored(self, loop_file):
        """Timestamps older than 30 seconds should be ignored."""
        runner = CliRunner()
        loop_path = loop_file / ".pm-pane-registry" / "loop-test-loop.json"

        # All timestamps are old (outside the 30-second window)
        now = time.time()
        timestamps = [now - 60, now - 50, now - 45, now - 40, now - 35]
        loop_path.write_text(json.dumps(timestamps))

        with patch.object(Path, 'home', return_value=loop_file):
            with patch('time.sleep'):
                result = runner.invoke(loop_guard_cmd, ['test-loop'])

        assert result.exit_code == 0

    def test_loop_file_cleared_after_trigger(self, loop_file):
        """Loop file should be cleared after triggering to allow manual retry."""
        runner = CliRunner()
        loop_path = loop_file / ".pm-pane-registry" / "loop-test-loop.json"

        now = time.time()
        timestamps = [now - 3, now - 2.5, now - 2, now - 1]
        loop_path.write_text(json.dumps(timestamps))

        with patch.object(Path, 'home', return_value=loop_file):
            with patch('time.sleep'):
                result = runner.invoke(loop_guard_cmd, ['test-loop'])

        assert result.exit_code == 1
        assert not loop_path.exists()  # File should be deleted

    def test_corrupted_loop_file_handled(self, loop_file):
        """Corrupted loop file should not crash."""
        runner = CliRunner()
        loop_path = loop_file / ".pm-pane-registry" / "loop-test-loop.json"
        loop_path.write_text("not valid json {{{")

        with patch.object(Path, 'home', return_value=loop_file):
            with patch('time.sleep'):
                result = runner.invoke(loop_guard_cmd, ['test-loop'])

        assert result.exit_code == 0

    def test_non_list_loop_file_handled(self, loop_file):
        """Loop file with non-list content should not crash."""
        runner = CliRunner()
        loop_path = loop_file / ".pm-pane-registry" / "loop-test-loop.json"
        loop_path.write_text('{"not": "a list"}')

        with patch.object(Path, 'home', return_value=loop_file):
            with patch('time.sleep'):
                result = runner.invoke(loop_guard_cmd, ['test-loop'])

        assert result.exit_code == 0
