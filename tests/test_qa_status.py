"""Tests for the qa_status.py verdict poller and helpers."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pm_core.qa_status import (
    VerdictPoller,
    _extract_verdict,
    _match_verdict,
    _VerdictStabilityTracker,
)


# ---------------------------------------------------------------------------
# _match_verdict
# ---------------------------------------------------------------------------

class TestMatchVerdict:
    def test_exact_match(self):
        assert _match_verdict("PASS") == "PASS"
        assert _match_verdict("NEEDS_WORK") == "NEEDS_WORK"
        assert _match_verdict("INPUT_REQUIRED") == "INPUT_REQUIRED"

    def test_with_markdown(self):
        assert _match_verdict("**PASS**") == "PASS"
        assert _match_verdict("`NEEDS_WORK`") == "NEEDS_WORK"

    def test_no_match(self):
        assert _match_verdict("some text") is None
        assert _match_verdict("PASS with extra") is None
        assert _match_verdict("") is None


# ---------------------------------------------------------------------------
# _extract_verdict
# ---------------------------------------------------------------------------

class TestExtractVerdict:
    def test_verdict_at_end(self):
        content = "lots of output\nmore output\nPASS\n"
        assert _extract_verdict(content) == "PASS"

    def test_verdict_with_markdown(self):
        content = "output\n**NEEDS_WORK**\n"
        assert _extract_verdict(content) == "NEEDS_WORK"

    def test_no_verdict(self):
        content = "just some normal output\nno verdict here\n"
        assert _extract_verdict(content) is None

    def test_verdict_beyond_tail(self):
        """Verdict outside the tail window should not be found."""
        lines = [f"line {i}" for i in range(50)]
        lines[0] = "PASS"  # too far back
        content = "\n".join(lines)
        assert _extract_verdict(content) is None

    def test_empty_content(self):
        assert _extract_verdict("") is None
        assert _extract_verdict("   ") is None


# ---------------------------------------------------------------------------
# _VerdictStabilityTracker
# ---------------------------------------------------------------------------

class TestVerdictStabilityTracker:
    def test_requires_two_polls(self):
        t = _VerdictStabilityTracker()
        assert t.update("k", "PASS") is False  # first poll
        assert t.update("k", "PASS") is True   # second — stable

    def test_reset_on_change(self):
        t = _VerdictStabilityTracker()
        t.update("k", "PASS")
        assert t.update("k", "NEEDS_WORK") is False  # changed — reset
        assert t.update("k", "NEEDS_WORK") is True

    def test_none_clears(self):
        t = _VerdictStabilityTracker()
        t.update("k", "PASS")
        t.update("k", None)  # clears
        assert t.update("k", "PASS") is False  # starts over


# ---------------------------------------------------------------------------
# VerdictPoller
# ---------------------------------------------------------------------------

class TestVerdictPoller:
    """Unit tests for VerdictPoller using mocked tmux calls."""

    def _make_status(self, scenarios, pr_id="pr-001", overall=""):
        return {
            "pr_id": pr_id,
            "scenarios": scenarios,
            "overall": overall,
        }

    def test_skips_when_overall_set(self, tmp_path):
        path = tmp_path / "qa_status.json"
        path.write_text("{}")
        poller = VerdictPoller(path, "sess")
        status = self._make_status([], overall="PASS")
        poller.poll(status)
        # Should return immediately without writing

    def test_skips_interactive_scenarios(self, tmp_path):
        path = tmp_path / "qa_status.json"
        path.write_text("{}")
        poller = VerdictPoller(path, "sess")
        status = self._make_status([
            {"index": 0, "title": "Interactive", "verdict": "interactive",
             "window_name": "qa-s0"},
        ])
        with patch("pm_core.qa_status._find_claude_pane") as mock_find:
            poller.poll(status)
            mock_find.assert_not_called()

    @patch("pm_core.qa_status._find_claude_pane", return_value=None)
    def test_dead_window_gets_input_required(self, mock_find, tmp_path):
        """A window that disappears should be marked INPUT_REQUIRED."""
        path = tmp_path / "qa_status.json"
        path.write_text("{}")
        poller = VerdictPoller(path, "sess")
        status = self._make_status([
            {"index": 1, "title": "Test", "verdict": "",
             "window_name": "qa-s1"},
        ])
        poller.poll(status)
        assert status["scenarios"][0]["verdict"] == "INPUT_REQUIRED"

    @patch("pm_core.qa_status._find_claude_pane", return_value=None)
    def test_dead_window_sets_overall_when_only_scenario(self, mock_find, tmp_path):
        """Single dead scenario → overall INPUT_REQUIRED."""
        path = tmp_path / "qa_status.json"
        path.write_text("{}")
        poller = VerdictPoller(path, "sess")
        status = self._make_status([
            {"index": 1, "title": "Test", "verdict": "",
             "window_name": "qa-s1"},
        ])
        poller.poll(status)
        assert status["overall"] == "INPUT_REQUIRED"

    @patch("pm_core.qa_status._capture_pane", return_value="output\nPASS\n")
    @patch("pm_core.qa_status._find_claude_pane", return_value="%1")
    def test_verdict_detected_after_stability(self, mock_find, mock_cap, tmp_path):
        """Verdict requires 2 stable polls before being accepted."""
        path = tmp_path / "qa_status.json"
        path.write_text("{}")
        poller = VerdictPoller(path, "sess")
        # Override grace period so it doesn't block
        poller._start_time = 0

        status = self._make_status([
            {"index": 1, "title": "Test", "verdict": "",
             "window_name": "qa-s1"},
        ])

        # First poll — not yet stable
        poller.poll(status)
        assert status["scenarios"][0]["verdict"] == ""

        # Second poll — stable, verdict accepted
        poller.poll(status)
        assert status["scenarios"][0]["verdict"] == "PASS"
        assert status["overall"] == "PASS"

    @patch("pm_core.qa_status._find_claude_pane", return_value="%1")
    def test_grace_period_skips_capture(self, mock_find, tmp_path):
        """During grace period, panes are found but not captured."""
        path = tmp_path / "qa_status.json"
        path.write_text("{}")
        poller = VerdictPoller(path, "sess")
        # _start_time is recent, so in_grace=True

        status = self._make_status([
            {"index": 1, "title": "Test", "verdict": "",
             "window_name": "qa-s1"},
        ])

        with patch("pm_core.qa_status._capture_pane") as mock_cap:
            poller.poll(status)
            mock_cap.assert_not_called()

    @patch("pm_core.qa_status._capture_pane")
    @patch("pm_core.qa_status._find_claude_pane")
    def test_overall_needs_work_wins(self, mock_find, mock_cap, tmp_path):
        """NEEDS_WORK in any scenario → overall NEEDS_WORK."""
        path = tmp_path / "qa_status.json"
        path.write_text("{}")
        poller = VerdictPoller(path, "sess")
        poller._start_time = 0

        mock_find.return_value = "%1"
        # Each poll captures both scenarios; need 2 polls for stability.
        # Poll 1: both scenarios captured (count=1, not stable yet)
        # Poll 2: both captured again (count=2, stable — verdicts accepted)
        mock_cap.side_effect = [
            "output\nNEEDS_WORK\n", "output\nPASS\n",  # poll 1
            "output\nNEEDS_WORK\n", "output\nPASS\n",  # poll 2
        ]

        status = self._make_status([
            {"index": 1, "title": "Fail", "verdict": "",
             "window_name": "qa-s1"},
            {"index": 2, "title": "OK", "verdict": "",
             "window_name": "qa-s2"},
        ])

        # Two polls for stability
        poller.poll(status)
        poller.poll(status)

        assert status["overall"] == "NEEDS_WORK"

    def test_write_status_atomic(self, tmp_path):
        """_write_status uses tmp+rename for atomicity."""
        path = tmp_path / "qa_status.json"
        path.write_text("{}")
        poller = VerdictPoller(path, "sess")
        status = {"pr_id": "pr-001", "scenarios": [], "overall": "PASS"}
        poller._write_status(status)

        result = json.loads(path.read_text())
        assert result["overall"] == "PASS"
        # tmp file should not remain
        assert not path.with_suffix(".tmp").exists()
