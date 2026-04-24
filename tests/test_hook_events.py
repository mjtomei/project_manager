"""Tests for Claude Code hook-driven idle/verdict detection."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


@pytest.fixture
def tmp_hooks_home(tmp_path, monkeypatch):
    """Point HOME at a tmp dir so ~/.pm/hooks and ~/.claude isolate per test."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # Some code uses Path.home() which reads $HOME on POSIX
    yield tmp_path


def _write_event(home: Path, session_id: str, event_type: str,
                 ts: float | None = None) -> dict:
    d = home / ".pm" / "hooks"
    d.mkdir(parents=True, exist_ok=True)
    record = {
        "event_type": event_type,
        "timestamp": ts if ts is not None else time.time(),
        "session_id": session_id,
        "matcher": event_type,
        "cwd": "/tmp",
    }
    (d / f"{session_id}.json").write_text(json.dumps(record))
    return record


def test_hook_receiver_writes_event(tmp_hooks_home):
    # Invoke the receiver module as a subprocess with stdin payload
    payload = json.dumps({"session_id": "abc-123", "cwd": "/tmp"})
    result = subprocess.run(
        [sys.executable, "-m", "pm_core.hook_receiver", "idle_prompt"],
        input=payload, text=True, capture_output=True,
        env={
            **__import__("os").environ,
            "HOME": str(tmp_hooks_home),
        },
    )
    assert result.returncode == 0, result.stderr
    path = tmp_hooks_home / ".pm" / "hooks" / "abc-123.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["event_type"] == "idle_prompt"
    assert data["session_id"] == "abc-123"
    assert isinstance(data["timestamp"], (int, float))


def test_hook_receiver_silent_on_bad_input(tmp_hooks_home):
    result = subprocess.run(
        [sys.executable, "-m", "pm_core.hook_receiver", "Stop"],
        input="not-json", text=True, capture_output=True,
        env={
            **__import__("os").environ,
            "HOME": str(tmp_hooks_home),
        },
    )
    assert result.returncode == 0
    assert not (tmp_hooks_home / ".pm" / "hooks").glob("*.json") or list(
        (tmp_hooks_home / ".pm" / "hooks").glob("*.json")
    ) == []


def _reload_hook_events():
    """Reimport hook_events so Path.home() is re-evaluated."""
    import importlib
    from pm_core import hook_events
    return importlib.reload(hook_events)


def test_wait_for_event_returns_matching(tmp_hooks_home):
    hook_events = _reload_hook_events()
    sid = "sid-wait-1"

    def writer():
        time.sleep(0.1)
        _write_event(tmp_hooks_home, sid, "idle_prompt", ts=time.time() + 1)

    t = threading.Thread(target=writer)
    t.start()
    ev = hook_events.wait_for_event(sid, {"idle_prompt"}, timeout=2.0, tick=0.05)
    t.join()
    assert ev is not None
    assert ev["event_type"] == "idle_prompt"


def test_wait_for_event_times_out(tmp_hooks_home):
    hook_events = _reload_hook_events()
    ev = hook_events.wait_for_event("no-such-sid", {"idle_prompt"}, timeout=0.2, tick=0.05)
    assert ev is None


def test_wait_for_event_respects_newer_than(tmp_hooks_home):
    hook_events = _reload_hook_events()
    sid = "sid-newer"
    old_ts = time.time() - 10
    _write_event(tmp_hooks_home, sid, "idle_prompt", ts=old_ts)

    # Baseline is now — the stale event must NOT be returned
    ev = hook_events.wait_for_event(
        sid, {"idle_prompt"}, timeout=0.2, tick=0.05,
        newer_than=time.time(),
    )
    assert ev is None


def test_hooks_available_reads_settings(tmp_hooks_home):
    hook_events = _reload_hook_events()
    settings = tmp_hooks_home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({
        "hooks": {
            "Notification": [
                {"matcher": "idle_prompt",
                 "hooks": [{"type": "command",
                            "command": f"{sys.executable} -m pm_core.hook_receiver idle_prompt"}]}
            ]
        }
    }))
    assert hook_events.hooks_available() is True


def test_hooks_unavailable_when_missing(tmp_hooks_home):
    hook_events = _reload_hook_events()
    assert hook_events.hooks_available() is False


def test_installer_merges_and_is_idempotent(tmp_hooks_home):
    from pm_core.hook_install import ensure_hooks_installed
    settings_path = tmp_hooks_home / ".claude" / "settings.json"
    # Pre-existing user content (unrelated hook + other top-level key)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({
        "theme": "dark",
        "hooks": {
            "Notification": [
                {"matcher": "user_hook",
                 "hooks": [{"type": "command", "command": "echo hi"}]}
            ]
        }
    }))

    assert ensure_hooks_installed(settings_path) is True
    data = json.loads(settings_path.read_text())
    # User content preserved
    assert data["theme"] == "dark"
    notif = data["hooks"]["Notification"]
    assert any(
        entry.get("matcher") == "user_hook" for entry in notif
    ), "user's existing hook was clobbered"
    # pm hook present
    assert any(
        "pm_core.hook_receiver" in h.get("command", "")
        for entry in notif for h in entry.get("hooks", [])
    )
    # Stop hook added
    stop = data["hooks"]["Stop"]
    assert any(
        "pm_core.hook_receiver" in h.get("command", "")
        for entry in stop for h in entry.get("hooks", [])
    )

    # Second call must be a no-op
    assert ensure_hooks_installed(settings_path) is False


def test_poll_for_verdict_hook_fast_path(tmp_hooks_home, monkeypatch):
    hook_events = _reload_hook_events()
    # Install hooks so hooks_available() returns True
    from pm_core.hook_install import ensure_hooks_installed
    settings_path = tmp_hooks_home / ".claude" / "settings.json"
    ensure_hooks_installed(settings_path)
    assert hook_events.hooks_available()

    from pm_core import loop_shared

    fake_pane_content = "some output\nPASS\n"

    def fake_pane_exists(pane_id):
        return True

    def fake_capture_pane(pane_id, full_scrollback=False):
        return fake_pane_content

    import pm_core.tmux as tmux_mod
    monkeypatch.setattr(tmux_mod, "pane_exists", fake_pane_exists)
    monkeypatch.setattr(tmux_mod, "capture_pane", fake_capture_pane)

    sid = "sid-poll-1"

    # Write an idle_prompt event from another thread shortly after we start polling
    def writer():
        time.sleep(0.1)
        _write_event(tmp_hooks_home, sid, "idle_prompt",
                     ts=time.time() + 5)

    t = threading.Thread(target=writer)
    t.start()

    start = time.time()
    content = loop_shared.poll_for_verdict(
        pane_id="%0",
        verdicts=("PASS", "FAIL"),
        keywords=("PASS", "FAIL"),
        poll_interval=1,
        tick_interval=0.1,
        log_prefix="test",
        session_id=sid,
    )
    elapsed = time.time() - start
    t.join()
    assert content is not None
    assert "PASS" in content
    # Hook path should respond well under the 3x polling timeout
    assert elapsed < 2.0, f"hook path was too slow ({elapsed}s)"


def test_session_id_from_transcript(tmp_path):
    from pm_core.claude_launcher import session_id_from_transcript

    target_dir = tmp_path / "projects"
    target_dir.mkdir()
    sid = "12345678-1234-1234-1234-1234567890ab"
    target = target_dir / f"{sid}.jsonl"
    target.write_text("{}")
    symlink = tmp_path / "transcript.jsonl"
    symlink.symlink_to(target)

    assert session_id_from_transcript(symlink) == sid


def test_session_id_from_transcript_missing(tmp_path):
    from pm_core.claude_launcher import session_id_from_transcript
    assert session_id_from_transcript(tmp_path / "nope.jsonl") is None
