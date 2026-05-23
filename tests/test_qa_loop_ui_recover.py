"""Tests for _recover_completed_qa_from_disk in qa_loop_ui.py."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import types

import pytest

# Stub out textual and other heavy TUI deps so qa_loop_ui can be imported
# in environments without those packages installed.
for _mod in ("textual", "textual.message", "textual.app", "textual.widgets",
             "textual.reactive", "textual.css", "textual.css.query",
             "textual.screen"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
# Provide the Message base class used by pm_core/tui/__init__.py
sys.modules["textual.message"].Message = object

from pm_core.tui.qa_loop_ui import _recover_completed_qa_from_disk  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(qa_loops=None, root=None):
    """Return a minimal mock app object."""
    app = MagicMock()
    app._qa_loops = qa_loops if qa_loops is not None else {}
    app._root = root
    # Ensure hasattr(_recovered_qa_pr_ids) returns False initially
    if hasattr(app, "_recovered_qa_pr_ids"):
        del app._recovered_qa_pr_ids
    # MagicMock has all attrs by default; remove the one we want absent
    app._spec_class = None
    return app


def _make_app_clean(qa_loops=None, root=None):
    """Return a simple object (not MagicMock) so hasattr works correctly."""
    class FakeApp:
        pass
    app = FakeApp()
    app._qa_loops = qa_loops if qa_loops is not None else {}
    app._root = root
    app.log_message = MagicMock()
    return app


def _write_status(directory: Path, pr_id: str, overall: str,
                  scenarios=None) -> Path:
    """Write a qa_status.json file and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    data = {
        "pr_id": pr_id,
        "overall": overall,
        "scenarios": scenarios or [
            {"index": 1, "title": "Scenario 1", "verdict": overall,
             "window_name": "qa-s1"},
        ],
    }
    path = directory / "qa_status.json"
    path.write_text(json.dumps(data))
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRecoverCompletedQAFromDisk:

    def test_no_qa_root_returns_early(self, tmp_path, monkeypatch):
        """If the qa workdir root doesn't exist, function returns silently."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        app = _make_app_clean()
        _recover_completed_qa_from_disk(app)  # should not raise

    def test_recovers_completed_pr(self, tmp_path, monkeypatch):
        """A completed qa_status.json with PR in 'qa' status triggers _on_qa_complete."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        qa_dir = tmp_path / ".pm" / "workdirs" / "qa" / "pr-001"
        _write_status(qa_dir, "pr-001", "PASS")

        app = _make_app_clean(root=tmp_path)

        with patch("pm_core.tui.qa_loop_ui.store") as mock_store, \
             patch("pm_core.tui.qa_loop_ui._on_qa_complete") as mock_complete:
            mock_store.load.return_value = {"prs": [{"id": "pr-001", "status": "qa"}]}
            mock_store.get_pr.return_value = {"id": "pr-001", "status": "qa"}
            _recover_completed_qa_from_disk(app)

        mock_complete.assert_called_once()
        state = mock_complete.call_args[0][1]
        assert state.pr_id == "pr-001"
        assert state.latest_verdict == "PASS"
        assert "pr-001" in app._recovered_qa_pr_ids

    def test_skips_if_pr_already_in_qa_loops(self, tmp_path, monkeypatch):
        """PR already tracked in app._qa_loops is not recovered again."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        qa_dir = tmp_path / ".pm" / "workdirs" / "qa" / "pr-002"
        _write_status(qa_dir, "pr-002", "NEEDS_WORK")

        app = _make_app_clean(qa_loops={"pr-002": MagicMock()})

        with patch("pm_core.tui.qa_loop_ui._on_qa_complete") as mock_complete:
            _recover_completed_qa_from_disk(app)

        mock_complete.assert_not_called()

    def test_skips_if_already_recovered(self, tmp_path, monkeypatch):
        """PR already in _recovered_qa_pr_ids is not processed again."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        qa_dir = tmp_path / ".pm" / "workdirs" / "qa" / "pr-003"
        _write_status(qa_dir, "pr-003", "PASS")

        app = _make_app_clean()
        app._recovered_qa_pr_ids = {"pr-003"}

        with patch("pm_core.tui.qa_loop_ui._on_qa_complete") as mock_complete:
            _recover_completed_qa_from_disk(app)

        mock_complete.assert_not_called()

    def test_skips_if_overall_not_set(self, tmp_path, monkeypatch):
        """Status file without overall verdict is ignored."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        qa_dir = tmp_path / ".pm" / "workdirs" / "qa" / "pr-004"
        qa_dir.mkdir(parents=True)
        (qa_dir / "qa_status.json").write_text(json.dumps({
            "pr_id": "pr-004",
            "overall": "",
            "scenarios": [],
        }))

        app = _make_app_clean()

        with patch("pm_core.tui.qa_loop_ui._on_qa_complete") as mock_complete:
            _recover_completed_qa_from_disk(app)

        mock_complete.assert_not_called()

    def test_skips_if_pr_not_in_qa_status(self, tmp_path, monkeypatch):
        """PR already transitioned away from 'qa' status is skipped."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        qa_dir = tmp_path / ".pm" / "workdirs" / "qa" / "pr-005"
        _write_status(qa_dir, "pr-005", "PASS")

        app = _make_app_clean(root=tmp_path)

        with patch("pm_core.tui.qa_loop_ui.store") as mock_store, \
             patch("pm_core.tui.qa_loop_ui._on_qa_complete") as mock_complete:
            mock_store.load.return_value = {}
            mock_store.get_pr.return_value = {"id": "pr-005", "status": "in_review"}
            _recover_completed_qa_from_disk(app)

        mock_complete.assert_not_called()
        # Should still be added to recovered set to avoid re-checking
        assert "pr-005" in app._recovered_qa_pr_ids

    def test_skips_corrupted_json(self, tmp_path, monkeypatch):
        """Corrupted status file is silently skipped."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        qa_dir = tmp_path / ".pm" / "workdirs" / "qa" / "pr-006"
        qa_dir.mkdir(parents=True)
        (qa_dir / "qa_status.json").write_text("not valid json{{{")

        app = _make_app_clean()

        with patch("pm_core.tui.qa_loop_ui._on_qa_complete") as mock_complete:
            _recover_completed_qa_from_disk(app)

        mock_complete.assert_not_called()

    def test_interactive_scenarios_excluded_from_state(self, tmp_path, monkeypatch):
        """Scenario 0 (interactive) is excluded from the recovered state."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        qa_dir = tmp_path / ".pm" / "workdirs" / "qa" / "pr-007"
        _write_status(qa_dir, "pr-007", "PASS", scenarios=[
            {"index": 0, "title": "Interactive", "verdict": "interactive",
             "window_name": "qa-s0"},
            {"index": 1, "title": "Scenario 1", "verdict": "PASS",
             "window_name": "qa-s1"},
        ])

        app = _make_app_clean(root=tmp_path)

        with patch("pm_core.tui.qa_loop_ui.store") as mock_store, \
             patch("pm_core.tui.qa_loop_ui._on_qa_complete") as mock_complete:
            mock_store.load.return_value = {}
            mock_store.get_pr.return_value = {"id": "pr-007", "status": "qa"}
            _recover_completed_qa_from_disk(app)

        mock_complete.assert_called_once()
        state = mock_complete.call_args[0][1]
        # Only non-interactive scenario
        assert len(state.scenarios) == 1
        assert state.scenarios[0].index == 1
        assert state.scenario_verdicts == {1: "PASS"}

    def test_idempotent_across_calls(self, tmp_path, monkeypatch):
        """Second call does not re-trigger _on_qa_complete for the same PR."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        qa_dir = tmp_path / ".pm" / "workdirs" / "qa" / "pr-008"
        _write_status(qa_dir, "pr-008", "NEEDS_WORK")

        app = _make_app_clean(root=tmp_path)

        with patch("pm_core.tui.qa_loop_ui.store") as mock_store, \
             patch("pm_core.tui.qa_loop_ui._on_qa_complete") as mock_complete:
            mock_store.load.return_value = {}
            mock_store.get_pr.return_value = {"id": "pr-008", "status": "qa"}
            _recover_completed_qa_from_disk(app)
            _recover_completed_qa_from_disk(app)

        assert mock_complete.call_count == 1

    def test_project_data_loaded_only_once_for_multiple_prs(self, tmp_path, monkeypatch):
        """store.load is called at most once even with multiple candidate PRs."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        for pr_id in ("pr-009", "pr-010"):
            qa_dir = tmp_path / ".pm" / "workdirs" / "qa" / pr_id
            _write_status(qa_dir, pr_id, "PASS")

        app = _make_app_clean(root=tmp_path)

        with patch("pm_core.tui.qa_loop_ui.store") as mock_store, \
             patch("pm_core.tui.qa_loop_ui._on_qa_complete"):
            mock_store.load.return_value = {}
            mock_store.get_pr.return_value = {"id": "pr-009", "status": "qa"}
            _recover_completed_qa_from_disk(app)

        assert mock_store.load.call_count == 1
