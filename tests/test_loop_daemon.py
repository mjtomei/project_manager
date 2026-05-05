"""Tests for pm_core.loop_daemon — pidfile lifecycle, stale sweep,
and runtime_state interaction."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from pm_core import loop_daemon, runtime_state


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Redirect pm_home and runtime_state to tmp_path."""
    sessions_root = tmp_path / "sessions"
    runtime_root = tmp_path / "runtime"
    sessions_root.mkdir()
    runtime_root.mkdir()
    monkeypatch.setattr(loop_daemon, "sessions_dir", lambda: sessions_root)
    monkeypatch.setattr(runtime_state, "_runtime_dir", lambda: runtime_root)


SESSION = "pm-test-tag"


def test_pidfile_layout():
    pid_path = loop_daemon.pidfile_path(SESSION, "pr-abc", "qa")
    assert pid_path.parent.name == "loops"
    assert pid_path.parent.parent.name == "test-tag"
    assert pid_path.name == "pr-abc-qa.pid"


def test_read_pidfile_missing_returns_none(tmp_path):
    assert loop_daemon.read_pidfile(tmp_path / "nope.pid") is None


def test_sweep_clears_dead_pidfile_and_runtime_state():
    pid_path = loop_daemon.pidfile_path(SESSION, "pr-abc", "qa")
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    # PID 1 is init — always alive on Linux. Use a clearly-bogus PID.
    pid_path.write_text("9999999\nloopid1\n2026-05-04T00:00:00+00:00\n")
    runtime_state.set_action_state("pr-abc", "qa", "running",
                                    loop_id="loopid1")

    swept = loop_daemon.sweep_stale_pidfiles(SESSION)

    assert swept == 1
    assert not pid_path.exists()
    assert runtime_state.get_action_state("pr-abc", "qa") == {}


def test_sweep_keeps_live_pidfile():
    pid_path = loop_daemon.pidfile_path(SESSION, "pr-abc", "review-loop")
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    # Our own PID is guaranteed alive.
    pid_path.write_text(f"{os.getpid()}\nloopid\n2026-05-04T00:00:00+00:00\n")
    runtime_state.set_action_state("pr-abc", "review-loop", "running",
                                    loop_id="loopid")

    swept = loop_daemon.sweep_stale_pidfiles(SESSION)

    assert swept == 0
    assert pid_path.exists()
    assert (runtime_state.get_action_state("pr-abc", "review-loop")
            .get("state") == "running")


def test_is_loop_alive_distinguishes_live_vs_dead():
    pid_path = loop_daemon.pidfile_path(SESSION, "pr-x", "qa")
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{os.getpid()}\nlid\n\n")
    assert loop_daemon.is_loop_alive(SESSION, "pr-x", "qa") is True

    pid_path.write_text("9999999\nlid\n\n")
    assert loop_daemon.is_loop_alive(SESSION, "pr-x", "qa") is False


def test_sweep_protects_alive_in_runtime_state():
    """sweep_stale_states with protect_alive_for_session keeps daemon-owned
    in-flight entries alive across TUI restart."""
    pid_path = loop_daemon.pidfile_path(SESSION, "pr-z", "qa")
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{os.getpid()}\nlid\n\n")
    runtime_state.set_action_state("pr-z", "qa", "running", loop_id="lid")
    # An unrelated in-flight entry without a pidfile — should be cleared.
    runtime_state.set_action_state("pr-y", "review", "running")

    swept = runtime_state.sweep_stale_states(
        "test", protect_alive_for_session=SESSION)

    assert swept == 1
    assert (runtime_state.get_action_state("pr-z", "qa").get("state")
            == "running")
    assert runtime_state.get_action_state("pr-y", "review") == {}


def test_bridge_stop_to_state_flips_state_on_sigterm_flag():
    """bridge_stop_to_state spawns a watcher that flips state.stop_requested
    when the daemon's SIGTERM handler sets the module-level flag."""
    class _S:
        stop_requested = False

    s = _S()
    loop_daemon._STOP_FLAG["set"] = False
    loop_daemon.bridge_stop_to_state(s, poll_interval=0.01)
    # Flag not yet set — watcher idles.
    time.sleep(0.05)
    assert s.stop_requested is False
    # Simulate SIGTERM handler.
    loop_daemon._STOP_FLAG["set"] = True
    deadline = time.time() + 1
    while time.time() < deadline and not s.stop_requested:
        time.sleep(0.01)
    assert s.stop_requested is True
    loop_daemon._STOP_FLAG["set"] = False


def test_spawn_runs_loop_main_in_detached_process():
    """End-to-end: spawn() forks, the child writes runtime_state, exits."""
    sentinel = Path(os.environ.get("PYTEST_TMPDIR", "/tmp")) / (
        f"loop-daemon-spawn-{os.getpid()}.txt"
    )
    sentinel.unlink(missing_ok=True)

    def loop_main():
        sentinel.write_text("ran\n")

    pid = loop_daemon.spawn(
        session=SESSION,
        pr_id="pr-spawn",
        action="qa",
        loop_id="lid-spawn",
        loop_main=loop_main,
    )
    assert pid > 0

    # Wait for the daemon to finish (writes sentinel + cleans up pidfile).
    deadline = time.time() + 5
    pid_path = loop_daemon.pidfile_path(SESSION, "pr-spawn", "qa")
    while time.time() < deadline:
        if not pid_path.exists() and sentinel.exists():
            break
        time.sleep(0.05)

    assert sentinel.exists(), "loop_main never ran"
    assert not pid_path.exists(), "daemon did not clean up pidfile"

    # runtime_state ends in terminal "done" or "failed".
    entry = runtime_state.get_action_state("pr-spawn", "qa")
    assert entry.get("state") in ("done", "failed")

    sentinel.unlink(missing_ok=True)
