"""A retired proxy cannot unlink or outlive its replacement socket."""

from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from pm_core import push_proxy


def test_renamed_cleanup_preserves_already_published_proxy(monkeypatch, tmp_path):
    from pm_core import container as cm

    path = str(tmp_path / "push.sock")
    replacement = push_proxy.PushProxy(path, str(tmp_path), "branch")
    replacement.start()
    try:
        stat = Path(path).stat()
        captured = ("pm-qa-debug-original", path,
                    (stat.st_dev, stat.st_ino, stat.st_ctime_ns), "renamed")
        monkeypatch.setattr(cm, "current_container_id", lambda name: "replacement-id")
        monkeypatch.setattr(push_proxy, "unshared_proxy_in_use", lambda path: True)
        push_proxy.release_captured_unshared_proxy(captured)
        assert push_proxy.proxy_is_alive(path)
        # Once the last allocation is gone, the same cleanup releases it.
        monkeypatch.setattr(cm, "current_container_id", lambda name: "")
        monkeypatch.setattr(push_proxy, "unshared_proxy_in_use", lambda path: False)
        push_proxy.release_captured_unshared_proxy(captured)
        assert not Path(path).exists()
    finally:
        replacement.stop()


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


def test_kill_proxy_socket_removes_a_directory_at_the_socket_path(tmp_path):
    """A directory at push.sock must not wedge cleanup forever.

    The bind-mounted socket source need not exist, so a container or tool can
    create a directory there. Without handling it the proxy could never be
    released and every reap would retry the same failure.
    """
    sock_dir = tmp_path / "pm-push-proxy-tag-pr-aaaa"
    sock = sock_dir / "push.sock"
    sock.mkdir(parents=True)
    (sock / "junk").write_text("x")

    push_proxy._kill_proxy_socket(str(sock))

    assert not sock.exists()
    assert not sock_dir.exists()


def test_start_clears_a_directory_at_the_socket_path(tmp_path):
    """A repair must clear the Docker bind-mount directory before binding.

    start_push_proxy pre-cleans the path, but repairing an existing
    allocation's socket goes straight to PushProxy.start(); without the same
    guard the child dies with IsADirectoryError on every retry and the
    container can never get a working proxy.
    """
    path = tmp_path / "push.sock"
    path.mkdir()
    (path / "junk").write_text("x")

    proxy = push_proxy.PushProxy(str(path), str(tmp_path), "branch")
    proxy.start()
    try:
        assert push_proxy.proxy_is_alive(str(path))
        assert path.is_socket()
    finally:
        proxy.stop()


def test_failed_daemon_start_fails_fast(monkeypatch, tmp_path):
    """A child that already exited cannot publish; do not wait out the window."""
    from pm_core.container import ContainerError

    class Exited:
        pid = 123
        returncode = 2

        def poll(self):
            return 2

        def terminate(self):  # pragma: no cover - must not be needed
            raise AssertionError("an exited child must not be terminated")

        def wait(self, timeout=None):
            return 2

    monkeypatch.setattr(push_proxy.subprocess, "Popen", lambda *a, **k: Exited())
    started = time.monotonic()
    with pytest.raises(ContainerError, match="exited"):
        push_proxy._start_proxy_subprocess(str(tmp_path / "push.sock"),
                                           str(tmp_path), "branch")
    assert time.monotonic() - started < 2.0


def test_unshared_proxy_in_use_classifies_probe_failures(monkeypatch):
    """A probe timeout is a retryable cleanup failure, not a raw exception."""
    from pm_core import container as cm
    from pm_core.container import ContainerError

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))

    monkeypatch.setattr(cm, "_run_runtime", timed_out)
    with pytest.raises(ContainerError) as err:
        push_proxy.unshared_proxy_in_use("/tmp/pm-push-proxy-x/push.sock")
    assert isinstance(err.value.__cause__, subprocess.TimeoutExpired)


def test_release_record_failure_is_a_container_error(monkeypatch, tmp_path):
    """An unwritable state dir defers removal with a classified error."""
    from pm_core import container as cm
    from pm_core.container import ContainerError

    blocker = tmp_path / "state"
    blocker.write_text("not a directory")
    monkeypatch.setattr(cm, "container_state_dir", lambda: blocker)

    proxy = ("pm-x", "/tmp/pm-push-proxy-pm-x/push.sock", (1, 2, 3), "pm-x")
    with pytest.raises(ContainerError, match="Cannot record unshared proxy release"):
        push_proxy.defer_unshared_release(proxy)


def test_malformed_release_record_is_ignored_not_wedged(monkeypatch, tmp_path):
    """A corrupt release record must not make every reap fail forever."""
    from pm_core import container as cm, container_reaper

    releases = tmp_path / "proxy-releases"
    releases.mkdir()
    (releases / "unreadable.json").write_text("{not json")
    (releases / "shape.json").write_text('{"proxy": ["only", "three"]}')
    monkeypatch.setattr(cm, "container_state_dir", lambda: tmp_path)

    failures: dict[str, str] = {}
    assert push_proxy.retry_unshared_releases(
        container_reaper.Scope(), failures) == []
    assert failures == {}


def test_capture_unshared_proxy_defers_an_unreadable_socket(monkeypatch, tmp_path):
    """A stat error on the socket path must not escape before the container rm.

    ``remove_container`` captures the mounted socket generation before it
    removes anything.  An unverifiable generation cannot authorize cleanup, so
    removal defers with a classified error instead of unlinking a socket it
    cannot identify — or reporting success while stranding the socket and its
    proxy daemon.
    """
    from pm_core.container import ContainerError

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    path = str(blocker / "push.sock")  # ENOTDIR, not ENOENT
    monkeypatch.setattr(push_proxy, "mounted_unshared_proxy",
                        lambda name: ("pm-x", path, "pm-x"))
    with pytest.raises(ContainerError, match="Cannot capture the mounted push proxy"):
        push_proxy.capture_unshared_proxy("pm-x")
