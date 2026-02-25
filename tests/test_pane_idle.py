"""Tests for pane idle detection (pm_core.pane_idle)."""

import time
from unittest.mock import patch

import pytest

from pm_core.pane_idle import PaneIdleTracker, content_has_interactive_prompt


@pytest.fixture
def tracker():
    """Create a tracker with a short threshold for fast tests."""
    return PaneIdleTracker(idle_threshold=1.0)


class TestPaneIdleTracker:
    """Unit tests for PaneIdleTracker."""

    def test_register_and_is_tracked(self, tracker):
        assert not tracker.is_tracked("pr-001")
        tracker.register("pr-001", "%5")
        assert tracker.is_tracked("pr-001")

    def test_unregister(self, tracker):
        tracker.register("pr-001", "%5")
        tracker.unregister("pr-001")
        assert not tracker.is_tracked("pr-001")

    def test_unregister_unknown_key_is_noop(self, tracker):
        tracker.unregister("nonexistent")  # should not raise

    @patch("pm_core.pane_idle.tmux_mod.pane_exists", return_value=True)
    @patch("pm_core.pane_idle.tmux_mod.capture_pane", return_value="hello world")
    def test_poll_not_idle_before_threshold(self, mock_capture, mock_exists, tracker):
        tracker.register("pr-001", "%5")
        result = tracker.poll("pr-001")
        assert result is False
        assert not tracker.is_idle("pr-001")

    @patch("pm_core.pane_idle.tmux_mod.pane_exists", return_value=True)
    @patch("pm_core.pane_idle.tmux_mod.capture_pane", return_value="hello world")
    def test_poll_idle_after_threshold(self, mock_capture, mock_exists, tracker):
        tracker.register("pr-001", "%5")

        # First poll: sets the content hash
        tracker.poll("pr-001")
        assert not tracker.is_idle("pr-001")

        # Backdate the last_change_time to simulate time passing
        with tracker._lock:
            tracker._states["pr-001"].last_change_time = time.monotonic() - 2.0

        # Second poll: same content, threshold exceeded
        result = tracker.poll("pr-001")
        assert result is True
        assert tracker.is_idle("pr-001")

    @patch("pm_core.pane_idle.tmux_mod.pane_exists", return_value=True)
    @patch("pm_core.pane_idle.tmux_mod.capture_pane")
    def test_content_change_resets_idle(self, mock_capture, mock_exists, tracker):
        tracker.register("pr-001", "%5")

        # First poll with content A
        mock_capture.return_value = "content A"
        tracker.poll("pr-001")

        # Backdate to exceed threshold
        with tracker._lock:
            tracker._states["pr-001"].last_change_time = time.monotonic() - 2.0

        # Poll with different content — should reset, not be idle
        mock_capture.return_value = "content B"
        result = tracker.poll("pr-001")
        assert result is False
        assert not tracker.is_idle("pr-001")

    @patch("pm_core.pane_idle.tmux_mod.pane_exists", return_value=False)
    def test_pane_gone(self, mock_exists, tracker):
        tracker.register("pr-001", "%5")
        result = tracker.poll("pr-001")
        assert result is False
        assert tracker.is_gone("pr-001")

    @patch("pm_core.pane_idle.tmux_mod.pane_exists", return_value=True)
    @patch("pm_core.pane_idle.tmux_mod.capture_pane", return_value="hello")
    def test_register_new_pane_resets_state(self, mock_capture, mock_exists, tracker):
        tracker.register("pr-001", "%5")
        tracker.poll("pr-001")

        # Backdate and become idle
        with tracker._lock:
            tracker._states["pr-001"].last_change_time = time.monotonic() - 2.0
        tracker.poll("pr-001")
        assert tracker.is_idle("pr-001")

        # Re-register with a new pane — should reset
        tracker.register("pr-001", "%9")
        assert not tracker.is_idle("pr-001")

    @patch("pm_core.pane_idle.tmux_mod.pane_exists", return_value=True)
    @patch("pm_core.pane_idle.tmux_mod.capture_pane", return_value="hello")
    def test_register_same_pane_does_not_reset(self, mock_capture, mock_exists, tracker):
        tracker.register("pr-001", "%5")
        tracker.poll("pr-001")

        # Backdate and become idle
        with tracker._lock:
            tracker._states["pr-001"].last_change_time = time.monotonic() - 2.0
        tracker.poll("pr-001")
        assert tracker.is_idle("pr-001")

        # Re-register with same pane — should NOT reset
        tracker.register("pr-001", "%5")
        assert tracker.is_idle("pr-001")

    @patch("pm_core.pane_idle.tmux_mod.pane_exists", return_value=True)
    @patch("pm_core.pane_idle.tmux_mod.capture_pane", return_value="hello")
    def test_mark_active(self, mock_capture, mock_exists, tracker):
        tracker.register("pr-001", "%5")
        tracker.poll("pr-001")

        # Backdate and become idle
        with tracker._lock:
            tracker._states["pr-001"].last_change_time = time.monotonic() - 2.0
        tracker.poll("pr-001")
        assert tracker.is_idle("pr-001")

        # mark_active should reset
        tracker.mark_active("pr-001")
        assert not tracker.is_idle("pr-001")

    @patch("pm_core.pane_idle.tmux_mod.pane_exists", return_value=True)
    @patch("pm_core.pane_idle.tmux_mod.capture_pane", return_value="hello")
    def test_became_idle_fires_once(self, mock_capture, mock_exists, tracker):
        tracker.register("pr-001", "%5")
        tracker.poll("pr-001")

        # Not idle yet
        assert not tracker.became_idle("pr-001")

        # Backdate and become idle
        with tracker._lock:
            tracker._states["pr-001"].last_change_time = time.monotonic() - 2.0
        tracker.poll("pr-001")
        assert tracker.is_idle("pr-001")

        # First call returns True
        assert tracker.became_idle("pr-001")
        # Second call returns False (already notified)
        assert not tracker.became_idle("pr-001")

    @patch("pm_core.pane_idle.tmux_mod.pane_exists", return_value=True)
    @patch("pm_core.pane_idle.tmux_mod.capture_pane")
    def test_became_idle_resets_on_activity(self, mock_capture, mock_exists, tracker):
        tracker.register("pr-001", "%5")

        # Go idle
        mock_capture.return_value = "content A"
        tracker.poll("pr-001")
        with tracker._lock:
            tracker._states["pr-001"].last_change_time = time.monotonic() - 2.0
        tracker.poll("pr-001")
        assert tracker.became_idle("pr-001")

        # New content makes it active again
        mock_capture.return_value = "content B"
        tracker.poll("pr-001")
        assert not tracker.is_idle("pr-001")

        # Go idle again
        with tracker._lock:
            tracker._states["pr-001"].last_change_time = time.monotonic() - 2.0
        tracker.poll("pr-001")

        # became_idle fires again for the new transition
        assert tracker.became_idle("pr-001")

    @patch("pm_core.pane_idle.tmux_mod.pane_exists", return_value=True)
    @patch("pm_core.pane_idle.tmux_mod.capture_pane", return_value="hello")
    def test_mark_active_resets_became_idle(self, mock_capture, mock_exists, tracker):
        tracker.register("pr-001", "%5")
        tracker.poll("pr-001")
        with tracker._lock:
            tracker._states["pr-001"].last_change_time = time.monotonic() - 2.0
        tracker.poll("pr-001")
        assert tracker.became_idle("pr-001")

        # mark_active resets the notification
        tracker.mark_active("pr-001")
        assert not tracker.became_idle("pr-001")

        # Go idle again — should fire
        with tracker._lock:
            tracker._states["pr-001"].last_change_time = time.monotonic() - 2.0
        tracker.poll("pr-001")
        assert tracker.became_idle("pr-001")

    def test_poll_unknown_key(self, tracker):
        result = tracker.poll("nonexistent")
        assert result is False

    def test_is_idle_unknown_key(self, tracker):
        assert not tracker.is_idle("nonexistent")

    def test_is_gone_unknown_key(self, tracker):
        assert not tracker.is_gone("nonexistent")

    @patch("pm_core.pane_idle.tmux_mod.pane_exists", return_value=False)
    def test_gone_then_reregister(self, mock_exists, tracker):
        tracker.register("pr-001", "%5")
        tracker.poll("pr-001")
        assert tracker.is_gone("pr-001")

        # Re-register with new pane
        tracker.register("pr-001", "%10")
        assert not tracker.is_gone("pr-001")

    @patch("pm_core.pane_idle.tmux_mod.pane_exists", return_value=True)
    @patch("pm_core.pane_idle.tmux_mod.capture_pane", return_value="hello world")
    def test_get_content(self, mock_capture, mock_exists, tracker):
        tracker.register("pr-001", "%5")
        tracker.poll("pr-001")
        assert tracker.get_content("pr-001") == "hello world"

    def test_get_content_unknown_key(self, tracker):
        assert tracker.get_content("nonexistent") == ""


class TestContentHasInteractivePrompt:
    """Tests for the interactive prompt detection helper."""

    def test_trust_prompt(self):
        content = (
            " Security guide\n"
            " ❯ 1. Yes, I trust this folder\n"
            "   2. No, I don't trust this folder\n"
        )
        assert content_has_interactive_prompt(content) is True

    def test_permission_prompt(self):
        content = (
            "? Allow Read /path/to/file\n"
            " ❯ Allow once\n"
            "   Allow always\n"
            "   Deny\n"
        )
        assert content_has_interactive_prompt(content) is True

    def test_normal_idle_output(self):
        content = (
            "$ claude --dangerously-skip-permissions\n"
            "Claude is working...\n"
            "Done! Created 3 files.\n"
            "\n"
        )
        assert content_has_interactive_prompt(content) is False

    def test_empty_content(self):
        assert content_has_interactive_prompt("") is False

    def test_selector_anywhere_in_output(self):
        """Selector anywhere in the pane content should match."""
        lines = ["line " + str(i) for i in range(25)]
        lines[3] = " ❯ 1. Yes, I trust this folder"
        content = "\n".join(lines)
        assert content_has_interactive_prompt(content) is True

    def test_bare_selector_no_text(self):
        """Bare ❯ without following text (e.g. input cursor) should not match."""
        content = "Some output\n❯ \n"
        assert content_has_interactive_prompt(content) is False
