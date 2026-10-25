"""A retired proxy cannot unlink or outlive its replacement socket."""

from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from pm_core import push_proxy


def test_old_proxy_stop_preserves_replacement_socket(tmp_path):
    path = str(tmp_path / "push.sock")
    old = push_proxy.PushProxy(path, str(tmp_path), "branch")
    replacement = push_proxy.PushProxy(path, str(tmp_path), "branch")
    old.start()
    try:
        push_proxy._kill_proxy_socket(path)
        replacement.start()
        old.stop()
        assert push_proxy.proxy_is_alive(path)
    finally:
        old.stop()
        replacement.stop()


@pytest.mark.parametrize("shutdown", ["replacement", "late-signal"])
def test_daemon_process_exits_without_unlinking_replacement(tmp_path, shutdown):
    path = str(tmp_path / "push.sock")
    proc = subprocess.Popen(
        [sys.executable, "-m", "pm_core.push_proxy", path, str(tmp_path), "branch"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    replacement = push_proxy.PushProxy(path, str(tmp_path), "branch")
    try:
        deadline = time.monotonic() + 5
        while not push_proxy.proxy_is_alive(path):
            assert proc.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.01)
        # Pause the old daemon across replacement to make the ordering exact.
        proc.send_signal(signal.SIGSTOP)
        while Path(f"/proc/{proc.pid}/status").read_text().split("State:", 1)[1].splitlines()[0].strip()[0] != "T":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        push_proxy._kill_proxy_socket(path)
        replacement.start()
        if shutdown == "late-signal":
            proc.send_signal(signal.SIGTERM)
        proc.send_signal(signal.SIGCONT)
        assert proc.wait(timeout=5) == 0
        assert push_proxy.proxy_is_alive(path)
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGCONT)
            proc.terminate()
            proc.wait(timeout=5)
        replacement.stop()


def test_old_server_notices_replacement_without_missing_path(tmp_path):
    path = str(tmp_path / "push.sock")
    old = push_proxy.PushProxy(path, str(tmp_path), "branch")
    replacement = push_proxy.PushProxy(path, str(tmp_path), "branch")
    old.start()
    try:
        # Keep accept blocked while replacement appears, so the old server
        # never observes a missing pathname between its polling iterations.
        old._server_socket.settimeout(0.05)
        replacement.start()
        old._thread.join(timeout=3)
        assert not old._thread.is_alive()
        assert push_proxy.proxy_is_alive(path)
    finally:
        old.stop()
        replacement.stop()
