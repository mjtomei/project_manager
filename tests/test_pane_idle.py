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

    def test_permission_prompt_marks_waiting_for_input(self, tracker, transcript, monkeypatch):
        tracker.register("k", "%0", str(transcript))
        monkeypatch.setattr("pm_core.pane_idle.tmux_mod.pane_exists",
                            lambda p: True)
        monkeypatch.setattr(
            "pm_core.hook_events.read_event",
            lambda sid: {"event_type": "permission_prompt", "timestamp": 1.0,
                         "session_id": sid},
        )
        tracker.poll("k")
        assert tracker.is_waiting_for_input("k") is True
        assert tracker.is_idle("k") is False

    def test_idle_after_permission_clears_waiting(self, tracker, transcript, monkeypatch):
        tracker.register("k", "%0", str(transcript))
        monkeypatch.setattr("pm_core.pane_idle.tmux_mod.pane_exists",
                            lambda p: True)

        sequence = [
            {"event_type": "permission_prompt", "timestamp": 1.0, "session_id": "s"},
            {"event_type": "idle_prompt", "timestamp": 2.0, "session_id": "s"},
        ]

        def read_event(sid):
            return sequence.pop(0) if sequence else None

        monkeypatch.setattr("pm_core.hook_events.read_event", read_event)
        tracker.poll("k")
        assert tracker.is_waiting_for_input("k") is True
        tracker.poll("k")
        assert tracker.is_waiting_for_input("k") is False
        assert tracker.is_idle("k") is True

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


class TestUserPromptTurnStart:
    """pr-2a44020: a typed turn after idle reads as working again."""

    def _events(self, monkeypatch):
        monkeypatch.setattr("pm_core.pane_idle.tmux_mod.pane_exists",
                            lambda p: True)
        cur = {}
        monkeypatch.setattr("pm_core.hook_events.read_event",
                            lambda sid: dict(cur, session_id=sid))

        def emit(etype, ts):
            cur.clear()
            cur.update(event_type=etype, timestamp=ts)
        return emit

    def test_user_prompt_after_idle_reads_working_then_idle_again(
            self, tracker, transcript, monkeypatch):
        tracker.register("k", "%0", str(transcript))
        emit = self._events(monkeypatch)
        emit("idle_prompt", 1.0)
        assert tracker.poll("k") is True
        assert tracker.became_idle("k")
        emit("user_prompt", 2.0)
        assert tracker.poll("k") is False
        assert not tracker.is_idle("k")
        assert not tracker.is_waiting_for_input("k")
        assert not tracker.became_idle("k")
        emit("Stop", 3.0)
        assert tracker.poll("k") is False
        emit("idle_prompt", 4.0)
        assert tracker.poll("k") is True
        # The new turn's end is a fresh idle transition.
        assert tracker.became_idle("k")

    def test_fast_turn_whose_user_prompt_was_overwritten_reads_working(
            self, tracker, transcript, monkeypatch):
        # S35 story 2: a typed turn answered in ~0.1 s.  The hook file
        # holds only the latest event, so the 5 s impl poll saw Stop (not
        # user_prompt) and the node stayed idle while the picker said
        # [working].  The Stop is newer than the idle_prompt already seen,
        # so a new turn ran: working until the next idle_prompt.
        tracker.register("k", "%0", str(transcript))
        emit = self._events(monkeypatch)
        emit("idle_prompt", 1.0)
        assert tracker.poll("k") is True
        assert tracker.became_idle("k")
        emit("user_prompt", 2.0)
        emit("Stop", 2.1)  # overwrites user_prompt before the next poll
        assert tracker.poll("k") is False
        assert not tracker.is_idle("k")
        assert not tracker.became_idle("k")
        assert tracker.poll("k") is False  # same Stop again: still working
        emit("idle_prompt", 62.1)
        assert tracker.poll("k") is True
        assert tracker.became_idle("k")

    def test_user_prompt_clears_waiting_for_input(
            self, tracker, transcript, monkeypatch):
        tracker.register("k", "%0", str(transcript))
        emit = self._events(monkeypatch)
        emit("permission_prompt", 1.0)
        tracker.poll("k")
        assert tracker.is_waiting_for_input("k")
        emit("user_prompt", 2.0)
        tracker.poll("k")
        assert not tracker.is_waiting_for_input("k")
        assert not tracker.is_idle("k")

    def test_blocked_prompt_reidles_on_claudes_next_idle_prompt(
            self, tracker, transcript, monkeypatch):
        # A user UserPromptSubmit hook that blocks the prompt: pm's record
        # still lands (no ordering between hooks), no Stop follows, and
        # Claude fires idle_prompt again about a minute later.
        tracker.register("k", "%0", str(transcript))
        emit = self._events(monkeypatch)
        emit("idle_prompt", 1.0)
        tracker.poll("k")
        tracker.became_idle("k")
        emit("user_prompt", 2.0)
        tracker.poll("k")
        assert not tracker.is_idle("k")
        emit("idle_prompt", 62.0)
        assert tracker.poll("k") is True


@pytest.mark.parametrize("key,action", [("pr-abc1234", "start"),
                                        ("qa:pr-abc1234:s1", "qa")])
def test_picker_status_reads_working_after_user_prompt(
        tracker, transcript, monkeypatch, key, action):
    """The picker (runtime_state, another process) sees the typed turn too."""
    from pm_core import runtime_state
    tracker.register(key, "%0", str(transcript))
    cur = {"event_type": "idle_prompt", "timestamp": 1.0}
    monkeypatch.setattr("pm_core.hook_events.read_event",
                        lambda sid: dict(cur, session_id=sid))
    assert runtime_state.derive_action_status("pr-abc1234", action)["state"] == "idle"
    cur.update(event_type="user_prompt", timestamp=2.0)
    assert runtime_state.derive_action_status("pr-abc1234", action)["state"] == "running"
