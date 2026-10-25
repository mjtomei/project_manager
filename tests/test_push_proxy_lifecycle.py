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


def test_daemon_installs_signal_handlers_before_socket_readiness(monkeypatch, tmp_path):
    from unittest.mock import Mock
    handlers = {}
    monkeypatch.setattr(signal, "signal", lambda sig, handler: handlers.setdefault(sig, handler))
    monkeypatch.setattr(sys, "argv", ["push_proxy", str(tmp_path / "push.sock"), str(tmp_path), "branch"])
    def start(self):
        assert signal.SIGTERM in handlers and signal.SIGINT in handlers
        handlers[signal.SIGTERM]()  # cancellation at the readiness boundary
    # Execute the real entrypoint while replacing only its server publication.
    source = Path(push_proxy.__file__).read_text()
    _, entrypoint = source.split('if __name__ == "__main__":', 1)
    namespace = dict(push_proxy.__dict__)
    fake_proxy = Mock()
    fake_proxy.start.side_effect = lambda: start(fake_proxy)
    namespace["PushProxy"] = Mock(return_value=fake_proxy)
    exec(compile('if True:' + entrypoint, push_proxy.__file__, "exec"), namespace)
    fake_proxy.stop.assert_called_once()


@pytest.mark.parametrize("interrupted", [False, True])
def test_unready_proxy_child_is_terminated_and_reaped(monkeypatch, tmp_path, interrupted):
    from unittest.mock import Mock
    from pm_core.container import ContainerError

    proc = Mock()
    proc.poll.return_value = None
    proc.wait.side_effect = [subprocess.TimeoutExpired("proxy", 1), 0]
    monkeypatch.setattr(push_proxy.subprocess, "Popen", Mock(return_value=proc))
    monkeypatch.setattr(push_proxy, "proxy_is_alive", lambda path: False)
    monkeypatch.setattr(time, "sleep", Mock(
        side_effect=KeyboardInterrupt if interrupted else None))
    with pytest.raises(KeyboardInterrupt if interrupted else ContainerError):
        push_proxy._start_proxy_subprocess(str(tmp_path / "push.sock"), str(tmp_path), "branch")
    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()
    assert proc.wait.call_count == 2


def test_delayed_real_proxy_process_cannot_publish_after_timeout(monkeypatch, tmp_path):
    from pm_core.container import ContainerError

    real_popen = subprocess.Popen
    children = []
    def delayed_start(args, **kwargs):
        child = real_popen([
            sys.executable, "-c",
            "import time, runpy; time.sleep(60); runpy.run_module('pm_core.push_proxy', run_name='__main__')",
            *args[3:],
        ], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(push_proxy.subprocess, "Popen", delayed_start)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    path = tmp_path / "push.sock"
    try:
        with pytest.raises(ContainerError, match="did not become ready"):
            push_proxy._start_proxy_subprocess(str(path), str(tmp_path), "branch")
        assert children[0].poll() is not None
        assert not path.exists()
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


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
