"""Tests for review loop state persistence via breadcrumb files.

Covers save_breadcrumb serialization of ReviewLoopState, consume_breadcrumb
restoration, and the pm tui restart CLI command.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from pm_core.review_loop import ReviewLoopState, ReviewIteration


def _run_async(coro):
    """Run an async coroutine in a fresh event loop (safe across tests)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(
    auto_start: bool = True,
    target: str | None = "pr-001",
    run_id: str = "autostart-pr-001-abcd1234",
    review_loops: dict | None = None,
    prs: list | None = None,
    root: Path | None = None,
):
    """Create a minimal mock app with auto-start and review loop fields."""
    app = MagicMock()
    app._auto_start = auto_start
    app._auto_start_target = target
    app._auto_start_run_id = run_id
    app._review_loops = review_loops or {}
    app._root = root or Path("/tmp/pm-test")
    app._data = {"prs": prs or []}
    app._watcher_state = None
    app._review_loop_timer = None
    return app


def _make_running_state(pr_id: str = "pr-001", iteration: int = 3,
                        stop_on_suggestions: bool = False) -> ReviewLoopState:
    """Create a ReviewLoopState that looks like a running loop."""
    state = ReviewLoopState(
        pr_id=pr_id,
        running=True,
        iteration=iteration,
        latest_verdict="NEEDS_WORK",
        stop_on_suggestions=stop_on_suggestions,
        loop_id="ab12",
        _transcript_dir="/tmp/pm-test/transcripts/autostart-pr-001-abcd1234",
    )
    state.history = [
        ReviewIteration(iteration=1, verdict="NEEDS_WORK", output="output1",
                        timestamp="2025-01-01T00:00:00"),
        ReviewIteration(iteration=2, verdict="NEEDS_WORK", output="output2",
                        timestamp="2025-01-01T00:01:00"),
        ReviewIteration(iteration=3, verdict="NEEDS_WORK", output="output3",
                        timestamp="2025-01-01T00:02:00"),
    ]
    return state


# ---------------------------------------------------------------------------
# save_breadcrumb tests
# ---------------------------------------------------------------------------

class TestSaveBreadcrumbReviewLoops:
    """Test that save_breadcrumb persists review loop state."""

    def test_saves_running_review_loops(self, tmp_path):
        state = _make_running_state("pr-001", iteration=3)
        app = _make_app(review_loops={"pr-001": state})

        # Create marker file
        (tmp_path / "merge-restart").touch()

        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path), \
             patch("pm_core.tui.watcher_ui.is_running", return_value=False):
            from pm_core.tui.auto_start import save_breadcrumb
            save_breadcrumb(app)

        breadcrumb = tmp_path / "autostart-resume.json"
        assert breadcrumb.exists()
        data = json.loads(breadcrumb.read_text())

        assert "review_loops" in data
        loops = data["review_loops"]
        assert "pr-001" in loops
        loop_data = loops["pr-001"]
        assert loop_data["iteration"] == 3
        assert loop_data["latest_verdict"] == "NEEDS_WORK"
        assert loop_data["stop_on_suggestions"] is False
        assert loop_data["loop_id"] == "ab12"
        assert len(loop_data["history"]) == 3
        assert loop_data["history"][0]["verdict"] == "NEEDS_WORK"
        assert loop_data["history"][0]["iteration"] == 1

    def test_skips_non_running_loops(self, tmp_path):
        state = _make_running_state("pr-001")
        state.running = False  # Not running

        app = _make_app(review_loops={"pr-001": state})
        (tmp_path / "merge-restart").touch()

        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path), \
             patch("pm_core.tui.watcher_ui.is_running", return_value=False):
            from pm_core.tui.auto_start import save_breadcrumb
            save_breadcrumb(app)

        data = json.loads((tmp_path / "autostart-resume.json").read_text())
        assert "review_loops" not in data

    def test_saves_multiple_loops(self, tmp_path):
        state1 = _make_running_state("pr-001", iteration=3)
        state2 = _make_running_state("pr-002", iteration=1)
        state2.loop_id = "cd34"
        state2.history = [
            ReviewIteration(iteration=1, verdict="NEEDS_WORK", output="out",
                            timestamp="2025-01-01T00:00:00"),
        ]

        app = _make_app(review_loops={"pr-001": state1, "pr-002": state2})
        (tmp_path / "merge-restart").touch()

        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path), \
             patch("pm_core.tui.watcher_ui.is_running", return_value=False):
            from pm_core.tui.auto_start import save_breadcrumb
            save_breadcrumb(app)

        data = json.loads((tmp_path / "autostart-resume.json").read_text())
        assert len(data["review_loops"]) == 2
        assert "pr-001" in data["review_loops"]
        assert "pr-002" in data["review_loops"]

    def test_no_breadcrumb_when_auto_start_disabled(self, tmp_path):
        app = _make_app(auto_start=False)
        (tmp_path / "merge-restart").touch()

        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path):
            from pm_core.tui.auto_start import save_breadcrumb
            save_breadcrumb(app)

        assert not (tmp_path / "autostart-resume.json").exists()

    def test_history_output_not_stored(self, tmp_path):
        """Breadcrumb should not include full output text (too large)."""
        state = _make_running_state("pr-001")
        app = _make_app(review_loops={"pr-001": state})
        (tmp_path / "merge-restart").touch()

        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path), \
             patch("pm_core.tui.watcher_ui.is_running", return_value=False):
            from pm_core.tui.auto_start import save_breadcrumb
            save_breadcrumb(app)

        data = json.loads((tmp_path / "autostart-resume.json").read_text())
        for h in data["review_loops"]["pr-001"]["history"]:
            assert "output" not in h

    def test_input_required_persisted(self, tmp_path):
        """input_required flag should be saved in the breadcrumb."""
        state = _make_running_state("pr-001")
        state.input_required = True
        app = _make_app(review_loops={"pr-001": state})
        (tmp_path / "merge-restart").touch()

        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path), \
             patch("pm_core.tui.watcher_ui.is_running", return_value=False):
            from pm_core.tui.auto_start import save_breadcrumb
            save_breadcrumb(app)

        data = json.loads((tmp_path / "autostart-resume.json").read_text())
        assert data["review_loops"]["pr-001"]["input_required"] is True


# ---------------------------------------------------------------------------
# consume_breadcrumb tests
# ---------------------------------------------------------------------------

class TestConsumeBreadcrumbReviewLoops:
    """Test that consume_breadcrumb restores review loop state."""

    def test_restores_review_loop_state(self, tmp_path):
        breadcrumb_data = {
            "target": "pr-001",
            "run_id": "autostart-pr-001-abcd1234",
            "review_loops": {
                "pr-001": {
                    "iteration": 3,
                    "latest_verdict": "NEEDS_WORK",
                    "stop_on_suggestions": False,
                    "loop_id": "ab12",
                    "input_required": False,
                    "_transcript_dir": "/tmp/transcripts",
                    "history": [
                        {"iteration": 1, "verdict": "NEEDS_WORK", "timestamp": "2025-01-01T00:00:00"},
                        {"iteration": 2, "verdict": "NEEDS_WORK", "timestamp": "2025-01-01T00:01:00"},
                        {"iteration": 3, "verdict": "NEEDS_WORK", "timestamp": "2025-01-01T00:02:00"},
                    ],
                }
            },
        }
        (tmp_path / "autostart-resume.json").write_text(json.dumps(breadcrumb_data))

        pr_data = {"id": "pr-001", "status": "in_review", "workdir": "/tmp/wd"}

        app = _make_app(auto_start=False, root=tmp_path)
        app._update_display = MagicMock()
        app.log_message = MagicMock()

        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path), \
             patch("pm_core.tui.auto_start.check_and_start", new_callable=AsyncMock), \
             patch("pm_core.tui.auto_start.store") as mock_store, \
             patch("pm_core.tui.review_loop_ui._start_loop") as mock_start:
            mock_store.get_pr.return_value = pr_data
            from pm_core.tui.auto_start import consume_breadcrumb
            _run_async(consume_breadcrumb(app))

        # Check auto-start was restored
        assert app._auto_start is True
        assert app._auto_start_target == "pr-001"

        # Check review loop state was restored
        assert "pr-001" in app._review_loops
        rstate = app._review_loops["pr-001"]
        assert rstate.iteration == 3
        assert rstate.latest_verdict == "NEEDS_WORK"
        assert rstate.stop_on_suggestions is False
        assert rstate.loop_id == "ab12"
        assert len(rstate.history) == 3

        # Check _start_loop was called with resume_state
        mock_start.assert_called_once()
        _, kwargs = mock_start.call_args
        assert kwargs.get("resume_state") is rstate

    def test_skips_loop_restart_if_pr_not_in_review(self, tmp_path):
        breadcrumb_data = {
            "target": "pr-001",
            "run_id": "run-123",
            "review_loops": {
                "pr-001": {
                    "iteration": 2,
                    "latest_verdict": "NEEDS_WORK",
                    "stop_on_suggestions": True,
                    "loop_id": "xy99",
                    "history": [],
                }
            },
        }
        (tmp_path / "autostart-resume.json").write_text(json.dumps(breadcrumb_data))

        app = _make_app(auto_start=False, root=tmp_path)
        app._update_display = MagicMock()
        app.log_message = MagicMock()

        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path), \
             patch("pm_core.tui.auto_start.check_and_start", new_callable=AsyncMock), \
             patch("pm_core.tui.auto_start.store") as mock_store, \
             patch("pm_core.tui.review_loop_ui._start_loop") as mock_start:
            # PR is merged — should not restart loop
            mock_store.get_pr.return_value = {"id": "pr-001", "status": "merged"}
            from pm_core.tui.auto_start import consume_breadcrumb
            _run_async(consume_breadcrumb(app))

        # State is restored into _review_loops
        assert "pr-001" in app._review_loops
        # But _start_loop should NOT have been called (PR not in_review)
        mock_start.assert_not_called()

    def test_no_review_loops_key_is_fine(self, tmp_path):
        """Breadcrumb without review_loops key should work (backward compat)."""
        breadcrumb_data = {"target": "pr-001", "run_id": "run-123"}
        (tmp_path / "autostart-resume.json").write_text(json.dumps(breadcrumb_data))

        app = _make_app(auto_start=False, root=tmp_path)
        app._update_display = MagicMock()
        app.log_message = MagicMock()

        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path), \
             patch("pm_core.tui.auto_start.check_and_start", new_callable=AsyncMock):
            from pm_core.tui.auto_start import consume_breadcrumb
            _run_async(consume_breadcrumb(app))

        assert app._auto_start is True
        assert app._review_loops == {}

    def test_breadcrumb_deleted_after_consumption(self, tmp_path):
        breadcrumb_data = {"target": "pr-001", "run_id": "run-123"}
        breadcrumb_path = tmp_path / "autostart-resume.json"
        breadcrumb_path.write_text(json.dumps(breadcrumb_data))

        app = _make_app(auto_start=False, root=tmp_path)
        app._update_display = MagicMock()
        app.log_message = MagicMock()

        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path), \
             patch("pm_core.tui.auto_start.check_and_start", new_callable=AsyncMock):
            from pm_core.tui.auto_start import consume_breadcrumb
            _run_async(consume_breadcrumb(app))

        assert not breadcrumb_path.exists()


# ---------------------------------------------------------------------------
# _start_loop resume_state tests
# ---------------------------------------------------------------------------

class TestStartLoopResumeState:
    """Test that _start_loop properly handles resume_state."""

    def test_resume_preserves_iteration_and_history(self):
        from pm_core.tui.review_loop_ui import _start_loop
        from pm_core import tmux as tmux_mod

        app = MagicMock()
        app._review_loops = {}
        app._review_loop_timer = None

        pr = {"id": "pr-001", "workdir": "/tmp/wd", "status": "in_review"}

        state = ReviewLoopState(
            pr_id="pr-001",
            iteration=3,
            latest_verdict="NEEDS_WORK",
            stop_on_suggestions=False,
            loop_id="ab12",
        )
        state.history = [
            ReviewIteration(iteration=1, verdict="NEEDS_WORK", output=""),
            ReviewIteration(iteration=2, verdict="NEEDS_WORK", output=""),
            ReviewIteration(iteration=3, verdict="NEEDS_WORK", output=""),
        ]
        state.stop_requested = True  # Should be reset

        with patch.object(tmux_mod, "in_tmux", return_value=True), \
             patch("pm_core.tui.review_loop_ui.store") as mock_store, \
             patch("pm_core.tui.review_loop_ui.start_review_loop_background") as mock_bg, \
             patch("pm_core.tui.review_loop_ui._ensure_poll_timer"):
            mock_store.find_project_root.return_value = Path("/tmp/pm")
            _start_loop(app, "pr-001", pr, stop_on_suggestions=False,
                        resume_state=state)

        # State should be in app._review_loops
        assert app._review_loops["pr-001"] is state
        # stop_requested should be reset
        assert state.stop_requested is False
        # UI notification flags should be reset
        assert state._ui_notified_done is False
        assert state._ui_notified_input is False
        # start_review_loop_background should be called with the same state
        mock_bg.assert_called_once()
        assert mock_bg.call_args.kwargs["state"] is state

    def test_fresh_start_creates_new_state(self):
        from pm_core.tui.review_loop_ui import _start_loop
        from pm_core import tmux as tmux_mod

        app = MagicMock()
        app._review_loops = {}
        app._review_loop_timer = None

        pr = {"id": "pr-002", "workdir": "/tmp/wd", "status": "in_review"}

        with patch.object(tmux_mod, "in_tmux", return_value=True), \
             patch("pm_core.tui.review_loop_ui.store") as mock_store, \
             patch("pm_core.tui.review_loop_ui.start_review_loop_background"), \
             patch("pm_core.tui.review_loop_ui._ensure_poll_timer"):
            mock_store.find_project_root.return_value = Path("/tmp/pm")
            _start_loop(app, "pr-002", pr, stop_on_suggestions=True)

        state = app._review_loops["pr-002"]
        assert state.pr_id == "pr-002"
        assert state.iteration == 0
        assert state.stop_on_suggestions is True
        assert state.history == []


# ---------------------------------------------------------------------------
# Round-trip test: save → consume
# ---------------------------------------------------------------------------

class TestBreadcrumbRoundTrip:
    """Test that save_breadcrumb → consume_breadcrumb preserves state."""

    def test_round_trip(self, tmp_path):
        # Create marker
        (tmp_path / "merge-restart").touch()

        # Build app with running review loop
        state = _make_running_state("pr-001", iteration=5)
        state.stop_on_suggestions = True
        state.loop_id = "ff99"
        save_app = _make_app(
            review_loops={"pr-001": state},
            root=tmp_path,
        )

        # Save breadcrumb
        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path), \
             patch("pm_core.tui.watcher_ui.is_running", return_value=False):
            from pm_core.tui.auto_start import save_breadcrumb
            save_breadcrumb(save_app)

        # Consume from a fresh app
        pr_data = {"id": "pr-001", "status": "in_review", "workdir": "/tmp/wd"}

        restore_app = _make_app(auto_start=False, root=tmp_path)
        restore_app._update_display = MagicMock()
        restore_app.log_message = MagicMock()

        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path), \
             patch("pm_core.tui.auto_start.check_and_start", new_callable=AsyncMock), \
             patch("pm_core.tui.auto_start.store") as mock_store, \
             patch("pm_core.tui.review_loop_ui._start_loop") as mock_start:
            mock_store.get_pr.return_value = pr_data
            from pm_core.tui.auto_start import consume_breadcrumb
            _run_async(consume_breadcrumb(restore_app))

        # Verify restored state
        assert "pr-001" in restore_app._review_loops
        rstate = restore_app._review_loops["pr-001"]
        assert rstate.iteration == 5
        assert rstate.stop_on_suggestions is True
        assert rstate.loop_id == "ff99"
        assert rstate.latest_verdict == "NEEDS_WORK"
        assert len(rstate.history) == 3

        # _start_loop was called with the restored state
        mock_start.assert_called_once()


# ---------------------------------------------------------------------------
# pm tui restart command tests
# ---------------------------------------------------------------------------

class TestTuiRestartCommand:
    """Test the pm tui restart CLI command."""

    def test_restart_without_breadcrumb(self):
        from click.testing import CliRunner
        from pm_core.cli.tui import tui_restart

        runner = CliRunner()
        with patch("pm_core.cli.tui._find_tui_pane", return_value=("%42", "pm-test-12345678")), \
             patch("pm_core.cli.tui.tmux_mod") as mock_tmux:
            result = runner.invoke(tui_restart, [])

        assert result.exit_code == 0
        assert "Sent restart" in result.output
        mock_tmux.send_keys_literal.assert_called_once_with("%42", "C-r")

    def test_restart_with_breadcrumb(self, tmp_path):
        from click.testing import CliRunner
        from pm_core.cli.tui import tui_restart

        runner = CliRunner()
        with patch("pm_core.cli.tui._find_tui_pane", return_value=("%42", "pm-test-12345678")), \
             patch("pm_core.paths.pm_home", return_value=tmp_path), \
             patch("pm_core.cli.tui.tmux_mod") as mock_tmux:
            result = runner.invoke(tui_restart, ["--breadcrumb"])

        assert result.exit_code == 0
        assert "merge-restart marker" in result.output
        assert (tmp_path / "merge-restart").exists()
        mock_tmux.send_keys_literal.assert_called_once_with("%42", "C-r")

    def test_restart_breadcrumb_cleaned_on_failure(self, tmp_path):
        from click.testing import CliRunner
        from pm_core.cli.tui import tui_restart

        runner = CliRunner()
        with patch("pm_core.cli.tui._find_tui_pane", return_value=("%42", "pm-test-12345678")), \
             patch("pm_core.paths.pm_home", return_value=tmp_path), \
             patch("pm_core.cli.tui.tmux_mod") as mock_tmux:
            mock_tmux.send_keys_literal.side_effect = Exception("tmux error")
            result = runner.invoke(tui_restart, ["--breadcrumb"])

        assert result.exit_code != 0
        # Marker should be cleaned up on failure
        assert not (tmp_path / "merge-restart").exists()

    def test_restart_no_tui_pane(self):
        from click.testing import CliRunner
        from pm_core.cli.tui import tui_restart

        runner = CliRunner()
        with patch("pm_core.cli.tui._find_tui_pane", return_value=(None, None)):
            result = runner.invoke(tui_restart, [])

        assert result.exit_code == 1
        assert "No TUI pane found" in result.output
