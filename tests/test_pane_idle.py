"""Tests for PaneIdleTracker — the hook-event driven idle tracker.

The old hash-comparison path is gone; registration requires a
transcript path whose symlink (or UUID-named file) yields a
Claude session_id.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pm_core.pane_idle import PaneIdleTracker


@pytest.fixture
def tracker():
    return PaneIdleTracker()


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    """Create a transcript symlink whose target filename is a UUID."""
    sid = "12345678-1234-1234-1234-123456789abc"
    target = tmp_path / f"{sid}.jsonl"
    target.write_text("")
    link = tmp_path / "t.jsonl"
    link.symlink_to(target)
    return link


class TestRegistration:
    def test_register_and_is_tracked(self, tracker, transcript):
        tracker.register("key-1", "%0", str(transcript))
        assert tracker.is_tracked("key-1")
        assert not tracker.is_idle("key-1")

    def test_register_rejects_unrecoverable_transcript(self, tracker, tmp_path):
        bogus = tmp_path / "not-a-uuid.jsonl"
        bogus.write_text("")
        with pytest.raises(ValueError):
            tracker.register("k", "%0", str(bogus))

    def test_unregister(self, tracker, transcript):
        tracker.register("k", "%0", str(transcript))
        tracker.unregister("k")
        assert not tracker.is_tracked("k")


class TestPolling:
    def test_poll_unknown_key(self, tracker):
        assert tracker.poll("nope") is False

    def test_poll_pane_gone(self, tracker, transcript):
        tracker.register("k", "%0", str(transcript))
        with patch("pm_core.pane_idle.tmux_mod.pane_exists", return_value=False):
            assert tracker.poll("k") is False
        assert tracker.is_gone("k")

    def test_idle_prompt_hook_marks_idle(self, tracker, transcript, monkeypatch):
        tracker.register("k", "%0", str(transcript))
        monkeypatch.setattr("pm_core.pane_idle.tmux_mod.pane_exists",
                            lambda p: True)

        def fake_read_event(session_id):
            return {"event_type": "idle_prompt", "timestamp": 123.0,
                    "session_id": session_id, "matcher": "Notification"}

        monkeypatch.setattr("pm_core.hook_events.read_event", fake_read_event)
        assert tracker.poll("k") is True
        assert tracker.is_idle("k")

    def test_became_idle_one_shot(self, tracker, transcript, monkeypatch):
        tracker.register("k", "%0", str(transcript))
        monkeypatch.setattr("pm_core.pane_idle.tmux_mod.pane_exists",
                            lambda p: True)
        monkeypatch.setattr(
            "pm_core.hook_events.read_event",
            lambda sid: {"event_type": "idle_prompt", "timestamp": 1.0,
                         "session_id": sid},
        )
        tracker.poll("k")
        assert tracker.became_idle("k") is True
        assert tracker.became_idle("k") is False

    def test_stop_event_does_not_flip_idle(self, tracker, transcript, monkeypatch):
        tracker.register("k", "%0", str(transcript))
        monkeypatch.setattr("pm_core.pane_idle.tmux_mod.pane_exists",
                            lambda p: True)
        monkeypatch.setattr(
            "pm_core.hook_events.read_event",
            lambda sid: {"event_type": "Stop", "timestamp": 1.0,
                         "session_id": sid},
        )
        assert tracker.poll("k") is False
        assert not tracker.is_idle("k")


def test_tracked_keys(tracker, transcript, tmp_path):
    sid2 = "87654321-4321-4321-4321-cba987654321"
    target2 = tmp_path / f"{sid2}.jsonl"
    target2.write_text("")
    link2 = tmp_path / "t2.jsonl"
    link2.symlink_to(target2)

    tracker.register("a", "%0", str(transcript))
    tracker.register("b", "%1", str(link2))
    assert set(tracker.tracked_keys()) == {"a", "b"}


def test_mark_active(tracker, transcript, monkeypatch):
    tracker.register("k", "%0", str(transcript))
    monkeypatch.setattr("pm_core.pane_idle.tmux_mod.pane_exists",
                        lambda p: True)
    monkeypatch.setattr(
        "pm_core.hook_events.read_event",
        lambda sid: {"event_type": "idle_prompt", "timestamp": 1.0,
                     "session_id": sid},
    )
    tracker.poll("k")
    assert tracker.is_idle("k")
    tracker.mark_active("k")
    assert not tracker.is_idle("k")
