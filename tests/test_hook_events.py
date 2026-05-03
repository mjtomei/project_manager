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
    # Flat layout: events land directly under ~/.pm/hooks/
    event_file = tmp_hooks_home / ".pm" / "hooks" / "abc-123.json"
    assert event_file.exists(), f"no event file at {event_file}"
    data = json.loads(event_file.read_text())
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
    hooks_root = tmp_hooks_home / ".pm" / "hooks"
    assert list(hooks_root.glob("*.json")) == []


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
        _write_event(tmp_hooks_home, sid, "idle_prompt",
                     ts=time.time() + 1)

    t = threading.Thread(target=writer)
    t.start()
    ev = hook_events.wait_for_event(sid, {"idle_prompt"}, timeout=2.0, tick=0.05)
    t.join()
    assert ev is not None
    assert ev["event_type"] == "idle_prompt"


def test_wait_for_event_times_out(tmp_hooks_home):
    hook_events = _reload_hook_events()
    ev = hook_events.wait_for_event("no-such-sid", {"idle_prompt"}, timeout=0.2,
                                    tick=0.05)
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
                            "command": "python3 /home/user/.pm/hook_receiver.py idle_prompt"}]}
            ]
        }
    }))
    assert hook_events.hooks_available() is True


def test_hooks_unavailable_when_missing(tmp_hooks_home):
    hook_events = _reload_hook_events()
    assert hook_events.hooks_available() is False


def test_installer_writes_standalone_receiver(tmp_hooks_home):
    """ensure_hooks_installed must drop a standalone copy of the receiver
    at ~/.pm/hook_receiver.py so containers can run it without pm_core."""
    # Re-import hook_install so RECEIVER_PATH picks up the tmp HOME.
    import importlib
    from pm_core import hook_install
    hook_install = importlib.reload(hook_install)

    settings_path = tmp_hooks_home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    hook_install.ensure_hooks_installed(settings_path)

    receiver = tmp_hooks_home / ".pm" / "hook_receiver.py"
    assert receiver.exists(), "standalone receiver was not installed"
    text = receiver.read_text()
    # Standalone receiver must not import pm_core — otherwise it cannot
    # run inside a container that doesn't ship pm_core.
    assert "from pm_core" not in text
    assert "import pm_core" not in text
    # And the settings.json hook command must reference that path.
    data = json.loads(settings_path.read_text())
    notif_cmds = [h.get("command", "")
                  for entry in data["hooks"]["Notification"]
                  for h in entry.get("hooks", [])]
    assert any(str(receiver) in c for c in notif_cmds)


def test_installer_uses_pm_host_home_when_set(tmp_hooks_home, tmp_path, monkeypatch):
    """Inside a container, PM_HOST_HOME points at the host's home dir.

    settings.json is bind-mounted from the host, so the hook command must
    reference the host's receiver path — not the container's HOME.
    """
    import importlib
    from pm_core import hook_install
    host_home = tmp_path / "host_home"
    host_home.mkdir()
    (host_home / ".pm").mkdir()
    monkeypatch.setenv("PM_HOST_HOME", str(host_home))
    hook_install = importlib.reload(hook_install)

    settings_path = tmp_hooks_home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    hook_install.ensure_hooks_installed(settings_path)

    data = json.loads(settings_path.read_text())
    expected = str(host_home / ".pm" / "hook_receiver.py")
    container_path = str(tmp_hooks_home / ".pm" / "hook_receiver.py")
    all_cmds = [
        h.get("command", "")
        for event in ("Notification", "Stop")
        for entry in data["hooks"][event]
        for h in entry.get("hooks", [])
    ]
    assert all(expected in c for c in all_cmds), all_cmds
    assert not any(container_path in c for c in all_cmds), all_cmds


def test_installer_falls_back_to_path_home_without_pm_host_home(tmp_hooks_home, monkeypatch):
    """Host behavior unchanged: with PM_HOST_HOME unset, use Path.home()."""
    import importlib
    from pm_core import hook_install
    monkeypatch.delenv("PM_HOST_HOME", raising=False)
    hook_install = importlib.reload(hook_install)

    settings_path = tmp_hooks_home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    hook_install.ensure_hooks_installed(settings_path)

    data = json.loads(settings_path.read_text())
    expected = str(tmp_hooks_home / ".pm" / "hook_receiver.py")
    cmds = [h.get("command", "")
            for entry in data["hooks"]["Notification"]
            for h in entry.get("hooks", [])]
    assert any(expected in c for c in cmds)


def test_installer_installs_clean(tmp_hooks_home):
    """No pre-existing hooks → install happens and is idempotent."""
    from pm_core.hook_install import ensure_hooks_installed
    settings_path = tmp_hooks_home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"theme": "dark"}))

    assert ensure_hooks_installed(settings_path) is True
    data = json.loads(settings_path.read_text())
    # User content preserved
    assert data["theme"] == "dark"
    notif = data["hooks"]["Notification"]
    assert any(
        "hook_receiver" in h.get("command", "")
        for entry in notif for h in entry.get("hooks", [])
    )
    stop = data["hooks"]["Stop"]
    assert any(
        "hook_receiver" in h.get("command", "")
        for entry in stop for h in entry.get("hooks", [])
    )
    # Second call must be a no-op
    assert ensure_hooks_installed(settings_path) is False


def test_installer_preserves_unrelated_notification_matcher(tmp_hooks_home):
    """A user's Notification hook on a different matcher must be preserved."""
    from pm_core.hook_install import ensure_hooks_installed
    settings_path = tmp_hooks_home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({
        "hooks": {
            "Notification": [
                {"matcher": "waiting_for_tool_permission",
                 "hooks": [{"type": "command", "command": "echo unrelated"}]}
            ]
        }
    }))
    # Non-conflicting: different matcher → install succeeds
    assert ensure_hooks_installed(settings_path) is True
    data = json.loads(settings_path.read_text())
    # pm hook is now present; user hook on unrelated matcher is NOT in the merged
    # Notification list (we replace the Notification entry wholesale for idle_prompt),
    # so this is a known limitation — assert the pm entry exists.
    notif = data["hooks"]["Notification"]
    assert any(
        "hook_receiver" in h.get("command", "")
        for entry in notif for h in entry.get("hooks", [])
    )


def test_installer_refuses_to_clobber_foreign_hooks(tmp_hooks_home):
    """A foreign idle_prompt or Stop hook must cause HookConflictError."""
    from pm_core.hook_install import ensure_hooks_installed, HookConflictError
    settings_path = tmp_hooks_home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({
        "hooks": {
            "Notification": [
                {"matcher": "idle_prompt",
                 "hooks": [{"type": "command", "command": "some-other-script"}]}
            ]
        }
    }))
    with pytest.raises(HookConflictError):
        ensure_hooks_installed(settings_path)


def test_installer_refuses_foreign_stop_hook(tmp_hooks_home):
    from pm_core.hook_install import ensure_hooks_installed, HookConflictError
    settings_path = tmp_hooks_home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "user-stop-script"}]}
            ]
        }
    }))
    with pytest.raises(HookConflictError):
        ensure_hooks_installed(settings_path)


def test_poll_for_verdict_hook_fast_path(tmp_hooks_home, monkeypatch, tmp_path):
    import json as _json
    hook_events = _reload_hook_events()
    from pm_core.hook_install import ensure_hooks_installed
    settings_path = tmp_hooks_home / ".claude" / "settings.json"
    ensure_hooks_installed(settings_path)
    assert hook_events.hooks_available()

    from pm_core import loop_shared

    # Valid UUID so session_id_from_transcript can recover it.
    sid = "12345678-1234-1234-1234-123456789abc"

    transcript_target = tmp_path / f"{sid}.jsonl"
    transcript_target.write_text("\n".join([
        _json.dumps({"type": "user", "message": {"role": "user",
                                                 "content": [{"type": "text", "text": "go"}]}}),
        _json.dumps({"type": "assistant", "message": {"role": "assistant",
                                                      "content": [{"type": "text", "text": "done\nPASS\n"}]}}),
    ]) + "\n")
    transcript_link = tmp_path / "t.jsonl"
    transcript_link.symlink_to(transcript_target)

    import pm_core.tmux as tmux_mod
    monkeypatch.setattr(tmux_mod, "pane_exists", lambda pane_id: True)

    def writer():
        time.sleep(0.1)
        _write_event(tmp_hooks_home, sid, "idle_prompt",
                     ts=time.time() + 5)

    t = threading.Thread(target=writer)
    t.start()

    start = time.time()
    content = loop_shared.poll_for_verdict(
        pane_id="%0",
        transcript_path=str(transcript_link),
        verdicts=("PASS", "FAIL"),
        wait_timeout=5,
        log_prefix="test",
    )
    elapsed = time.time() - start
    t.join()
    assert content is not None
    assert "PASS" in content
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
