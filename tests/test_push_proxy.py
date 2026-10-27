"""Tests for the host-side git push proxy."""

import contextlib
import glob
import fcntl
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import pm_core.push_proxy as push_proxy_mod
from pm_core.push_proxy import (
    PushProxy,
    start_push_proxy,
    stop_push_proxy,
    stop_all_proxies,
    stop_session_proxies,
    get_proxy_socket_path,
    container_socket_path,
    _CONTAINER_SOCKET_PATH,
)


@pytest.fixture(autouse=True)
def _sweep_proxy_state():
    """Reset in-memory bookkeeping and remove /tmp dirs this test created.

    Shared proxies deliberately keep their socket directory after
    ``stop_push_proxy`` (a container may still bind-mount it), so a test
    that only stops the proxy would otherwise leave
    ``/tmp/pm-push-proxy-*`` directories and lock files behind.
    """
    before = set(glob.glob("/tmp/pm-push-proxy-*"))
    yield
    with push_proxy_mod._proxy_lock:
        push_proxy_mod._active_proxies.clear()
        push_proxy_mod._proxy_refs.clear()
        push_proxy_mod._container_to_proxy_key.clear()
    for path in set(glob.glob("/tmp/pm-push-proxy-*")) - before:
        real = os.path.realpath(path)
        if os.path.islink(path):
            try:
                os.unlink(path)
            except OSError:
                pass
        if os.path.isdir(real):
            shutil.rmtree(real, ignore_errors=True)
        else:
            try:
                os.unlink(real)
            except OSError:
                pass


@pytest.fixture
def sock_path(tmp_path):
    return str(tmp_path / "test.sock")


@pytest.fixture
def proxy(sock_path):
    p = PushProxy(sock_path, "/tmp/fake-workdir", "pm/pr-123-feature")
    p.start()
    yield p
    p.stop()


def _send_request(sock_path: str, request: dict) -> dict:
    """Helper: send a JSON request to the proxy and return the response."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sock_path)
    s.sendall((json.dumps(request) + "\n").encode())
    data = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data.decode())


def _send_raw(sock_path: str, payload: bytes) -> dict:
    """Helper: send raw bytes to the proxy and return the parsed response."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sock_path)
    s.sendall(payload)
    data = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data.decode())


class TestPushProxyBranchValidation:
    def test_rejects_wrong_branch(self, proxy, sock_path):
        resp = _send_request(sock_path, {"args": ["origin", "main"]})
        assert resp["exit_code"] == 1
        assert "rejected" in resp["stderr"]
        assert "main" in resp["stderr"]

    def test_rejects_wrong_branch_with_refspec(self, proxy, sock_path):
        resp = _send_request(sock_path, {"args": ["origin", "HEAD:main"]})
        assert resp["exit_code"] == 1
        assert "rejected" in resp["stderr"]

    def test_rejects_refs_heads_wrong_branch(self, proxy, sock_path):
        resp = _send_request(sock_path, {"args": ["origin", "refs/heads/main"]})
        assert resp["exit_code"] == 1
        assert "rejected" in resp["stderr"]

    @patch("subprocess.run")
    def test_allows_correct_branch(self, mock_run, proxy, sock_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="pushed\n", stderr="")
        resp = _send_request(sock_path,
                             {"args": ["origin", "pm/pr-123-feature"]})
        assert resp["exit_code"] == 0
        # Push runs as `git -C <source> push <args>` (post-PR-6be8ee6 design:
        # source is the caller's clone, which has origin set to the real
        # upstream).  Find that call.
        push_call = [c for c in mock_run.call_args_list
                     if c[0][0][:2] == ["git", "-C"] and "push" in c[0][0]]
        assert len(push_call) == 1
        cmd = push_call[0][0][0]
        assert cmd[3:] == ["push", "origin", "pm/pr-123-feature"]

    @patch("subprocess.run")
    def test_allows_force_push_plus_prefix(self, mock_run, proxy, sock_path):
        """'+branch' force-push syntax should be recognised as the correct branch."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr="")
        resp = _send_request(sock_path,
                             {"args": ["origin", "+pm/pr-123-feature"]})
        assert resp["exit_code"] == 0

    @patch("subprocess.run")
    def test_allows_correct_branch_with_refspec(self, mock_run, proxy, sock_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr="")
        resp = _send_request(sock_path,
                             {"args": ["origin", "HEAD:pm/pr-123-feature"]})
        assert resp["exit_code"] == 0

    @patch("subprocess.run")
    def test_allows_refs_heads_correct_branch(self, mock_run, proxy, sock_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr="")
        resp = _send_request(sock_path,
                             {"args": ["origin", "refs/heads/pm/pr-123-feature"]})
        assert resp["exit_code"] == 0

    @patch("subprocess.run")
    def test_allows_push_origin_HEAD(self, mock_run, proxy, sock_path):
        """'git push origin HEAD' should resolve HEAD and allow if on correct branch."""
        def side_effect(cmd, **kwargs):
            if "rev-parse" in cmd:
                return MagicMock(returncode=0, stdout="pm/pr-123-feature\n")
            return MagicMock(returncode=0, stdout="ok\n", stderr="")
        mock_run.side_effect = side_effect
        resp = _send_request(sock_path,
                             {"args": ["origin", "HEAD"]})
        assert resp["exit_code"] == 0

    @patch("subprocess.run")
    def test_rejects_push_origin_HEAD_wrong_branch(self, mock_run, proxy, sock_path):
        """'git push origin HEAD' should reject if HEAD is on wrong branch."""
        mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
        resp = _send_request(sock_path,
                             {"args": ["origin", "HEAD"]})
        assert resp["exit_code"] == 1
        assert "rejected" in resp["stderr"]

    @patch("subprocess.run")
    def test_no_refspec_checks_head(self, mock_run, proxy, sock_path):
        """Without explicit refspec, proxy checks current branch via HEAD."""
        # First call: git rev-parse --abbrev-ref HEAD
        # Second call: git push origin (if allowed)
        def side_effect(cmd, **kwargs):
            if "rev-parse" in cmd:
                return MagicMock(returncode=0, stdout="pm/pr-123-feature\n")
            return MagicMock(returncode=0, stdout="ok\n", stderr="")
        mock_run.side_effect = side_effect

        resp = _send_request(sock_path, {"args": ["origin"]})
        assert resp["exit_code"] == 0

    @patch("subprocess.run")
    def test_no_refspec_rejects_wrong_head(self, mock_run, proxy, sock_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
        resp = _send_request(sock_path, {"args": ["origin"]})
        assert resp["exit_code"] == 1
        assert "rejected" in resp["stderr"]

    def test_rejects_multiple_refspecs(self, proxy, sock_path):
        """Multiple refspecs must be rejected to prevent pushing to extra branches."""
        resp = _send_request(sock_path,
                             {"args": ["origin", "pm/pr-123-feature", "main"]})
        assert resp["exit_code"] == 1
        assert "could not determine" in resp["stderr"]

    def test_rejects_all_flag(self, proxy, sock_path):
        resp = _send_request(sock_path, {"args": ["--all"]})
        assert resp["exit_code"] == 1
        assert "rejected" in resp["stderr"]
        assert "--all" in resp["stderr"]

    def test_rejects_mirror_flag(self, proxy, sock_path):
        resp = _send_request(sock_path, {"args": ["--mirror"]})
        assert resp["exit_code"] == 1
        assert "rejected" in resp["stderr"]

    def test_rejects_tags_flag(self, proxy, sock_path):
        resp = _send_request(sock_path, {"args": ["origin", "--tags"]})
        assert resp["exit_code"] == 1
        assert "rejected" in resp["stderr"]

    @patch("subprocess.run")
    def test_rejects_undetermined_branch(self, mock_run, proxy, sock_path):
        """When target branch can't be determined, push is rejected (fail-closed)."""
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        resp = _send_request(sock_path, {"args": []})
        assert resp["exit_code"] == 1
        assert "could not determine" in resp["stderr"]

    @patch("subprocess.run")
    def test_passes_flags_through(self, mock_run, proxy, sock_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr="")
        resp = _send_request(sock_path,
                             {"args": ["-u", "origin", "pm/pr-123-feature"]})
        assert resp["exit_code"] == 0
        push_call = [c for c in mock_run.call_args_list
                     if c[0][0][:2] == ["git", "-C"] and "push" in c[0][0]]
        assert len(push_call) == 1
        cmd = push_call[0][0][0]
        # cmd is ["git", "-C", <source>, "push", "-u", "origin", "pm/pr-123-feature"]
        assert cmd[3:] == ["push", "-u", "origin", "pm/pr-123-feature"]


class TestDangerousFlags:
    """Flags that could execute arbitrary programs must be blocked."""

    def test_rejects_upload_pack_in_fetch(self, proxy, sock_path):
        resp = _send_request(sock_path,
                             {"cmd": "fetch", "args": ["--upload-pack=/workspace/evil.sh"]})
        assert resp["exit_code"] == 1
        assert "rejected" in resp["stderr"]
        assert "--upload-pack" in resp["stderr"]

    def test_rejects_upload_pack_in_pull(self, proxy, sock_path):
        resp = _send_request(sock_path,
                             {"cmd": "pull", "args": ["--upload-pack=/workspace/evil.sh"]})
        assert resp["exit_code"] == 1
        assert "--upload-pack" in resp["stderr"]

    def test_rejects_receive_pack_in_push(self, proxy, sock_path):
        resp = _send_request(sock_path,
                             {"args": ["--receive-pack=/workspace/evil.sh",
                                       "origin", "pm/pr-123-feature"]})
        assert resp["exit_code"] == 1
        assert "--receive-pack" in resp["stderr"]

    def test_rejects_exec_in_push(self, proxy, sock_path):
        resp = _send_request(sock_path,
                             {"args": ["--exec=/workspace/evil.sh",
                                       "origin", "pm/pr-123-feature"]})
        assert resp["exit_code"] == 1
        assert "--exec" in resp["stderr"]

    def test_rejects_upload_pack_equals_syntax(self, proxy, sock_path):
        resp = _send_request(sock_path,
                             {"cmd": "fetch", "args": ["--upload-pack=cat /etc/passwd"]})
        assert resp["exit_code"] == 1

    def test_rejects_upload_pack_in_ls_remote(self, proxy, sock_path):
        resp = _send_request(sock_path,
                             {"cmd": "ls-remote", "args": ["--upload-pack=/evil"]})
        assert resp["exit_code"] == 1


class TestPushProxyProtocol:
    def test_rejects_non_string_args(self, proxy, sock_path):
        resp = _send_request(sock_path, {"args": [123, None]})
        assert resp["exit_code"] == 1
        assert "list of strings" in resp["stderr"]

    def test_rejects_non_list_args(self, proxy, sock_path):
        resp = _send_request(sock_path, {"args": "not a list"})
        assert resp["exit_code"] == 1
        assert "list of strings" in resp["stderr"]

    def test_rejects_non_string_workdir(self, proxy, sock_path):
        resp = _send_request(sock_path, {
            "cmd": "push",
            "args": ["origin", "pm/pr-123-feature"],
            "workdir": {"nested": True},
        })
        assert resp["exit_code"] == 1
        assert "must be a string" in resp["stderr"]

    @pytest.mark.parametrize("bad", [[], 0, False])
    def test_rejects_falsy_non_string_workdir(self, proxy, sock_path, bad):
        """A falsy non-string must be rejected, not treated as 'absent'."""
        resp = _send_request(sock_path, {
            "cmd": "push",
            "args": ["origin", "pm/pr-123-feature"],
            "workdir": bad,
        })
        assert resp["exit_code"] == 1
        assert "must be a string" in resp["stderr"]

    def test_invalid_json(self, proxy, sock_path):
        resp = _send_raw(sock_path, b"not json\n")
        assert resp["exit_code"] == 1
        assert "invalid" in resp["stderr"]

    def test_rejects_non_object_request(self, proxy, sock_path):
        """Valid JSON that is not an object must get a reply, not a drop."""
        resp = _send_raw(sock_path, b'["origin", "branch"]\n')
        assert resp["exit_code"] == 1
        assert "JSON object" in resp["stderr"]

    @patch("subprocess.run")
    def test_push_timeout(self, mock_run, proxy, sock_path):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=120)
        resp = _send_request(sock_path,
                             {"args": ["origin", "pm/pr-123-feature"]})
        assert resp["exit_code"] == 1
        assert "timed out" in resp["stderr"]


class TestPushProxyLifecycle:
    def test_start_and_stop(self):
        with patch("pm_core.push_proxy.PushProxy.start"), \
             patch("pm_core.push_proxy.PushProxy.stop"):
            sock = start_push_proxy("test-container", "/w", "pm/pr-123")
            assert os.path.dirname(sock)  # Has a directory
            stop_push_proxy("test-container")

    def test_stop_nonexistent_is_noop(self):
        stop_push_proxy("nonexistent-container")  # Should not raise

    def test_proxy_subprocess_does_not_inherit_stdin(self, tmp_path):
        """Detached proxy daemon must redirect stdin to /dev/null.

        Otherwise it inherits its parent's FD 0 — when the parent is a tmux
        popup pty (`display-popup -E pm _popup-cmd`), the popup overlay
        cannot close until every FD on the pty closes, so the long-lived
        proxy daemon hangs the popup indefinitely. See pr-7b3b639.
        """
        from pm_core.push_proxy import _start_proxy_subprocess

        sock = str(tmp_path / "push.sock")
        with patch("pm_core.push_proxy.subprocess.Popen") as mock_popen, \
             patch("pm_core.push_proxy.proxy_is_alive", return_value=True), \
             patch("pm_core.push_proxy.os.path.exists", return_value=True):
            mock_popen.return_value = MagicMock(pid=12345)
            _start_proxy_subprocess(sock, "/workdir", "pm/pr-x")

        assert mock_popen.called
        kwargs = mock_popen.call_args.kwargs
        assert kwargs.get("stdin") is subprocess.DEVNULL, (
            "proxy daemon must not inherit popup pty stdin "
            "(would hang display-popup -E)"
        )
        assert kwargs.get("stdout") is subprocess.DEVNULL
        assert kwargs.get("stderr") is subprocess.DEVNULL
        assert kwargs.get("start_new_session") is True

    def test_container_socket_path(self):
        assert container_socket_path() == _CONTAINER_SOCKET_PATH
        assert container_socket_path() == "/run/pm-push-proxy/push.sock"

    def test_legacy_registration_happens_under_the_start_lock(self):
        """A concurrent legacy stop must see the registration before killing.

        stop_push_proxy re-checks _container_to_proxy_key while holding the
        per-directory start lock.  That guard is only effective if
        start_push_proxy registers *before* releasing the lock — otherwise
        the stop can slip in after the spawn and kill the fresh socket (the
        shared path already registers under the lock).
        """
        cname = "legacy-registration-test"
        registered_at_release = []
        real_lock = push_proxy_mod._start_lock

        @contextlib.contextmanager
        def tracking_lock(sock_dir, blocking=True):
            with real_lock(sock_dir, blocking=blocking) as locked:
                yield locked
            # Runs when start_push_proxy exits the with-block.
            with push_proxy_mod._proxy_lock:
                registered_at_release.append(
                    cname in push_proxy_mod._container_to_proxy_key)

        def fake_start(sock_path, workdir, branch):
            os.makedirs(os.path.dirname(sock_path), exist_ok=True)
            Path(sock_path).touch()
            return True

        try:
            with patch("pm_core.push_proxy._start_proxy_subprocess",
                       side_effect=fake_start), \
                 patch("pm_core.push_proxy._start_lock", tracking_lock):
                start_push_proxy(cname, "/w", "pm/pr-123")
            assert registered_at_release == [True], (
                "the legacy proxy was registered after the start lock was "
                "released; a concurrent stop could kill the fresh socket")
        finally:
            stop_push_proxy(cname)

    def test_get_proxy_socket_path(self):
        with patch("pm_core.push_proxy.PushProxy.start"), \
             patch("pm_core.push_proxy.PushProxy.stop"):
            sock = start_push_proxy("lookup-test", "/w", "pm/pr-123")
            assert get_proxy_socket_path("lookup-test") == sock
            stop_push_proxy("lookup-test")
            assert get_proxy_socket_path("lookup-test") is None

    def test_get_proxy_socket_path_nonexistent(self):
        assert get_proxy_socket_path("no-such-container") is None

    def test_legacy_stop_clears_its_start_lock(self):
        """Per-container stop holds the start lock; it must clear the file.

        `_clear_lock_file` cannot unlink a lock this process holds through
        another fd, so the stop path must pass ``lock_held=True`` or every
        legacy stop leaks a ``.lock`` in /tmp.
        """
        cname = "legacy-lock-test"
        sock = start_push_proxy(cname, "/w", "pm/pr-123")
        sock_dir = os.path.dirname(sock)
        assert os.path.exists(sock_dir + ".lock")

        stop_push_proxy(cname)

        assert not os.path.exists(sock_dir)
        assert not os.path.exists(sock_dir + ".lock")

    def test_thread_exits_when_socket_removed(self, sock_path):
        """Proxy thread self-terminates when its socket file is deleted."""
        proxy = PushProxy(sock_path, "/w", "branch")
        proxy.start()
        assert proxy._thread.is_alive()
        # Remove the socket file — thread should exit within a few seconds
        os.unlink(sock_path)
        proxy._thread.join(timeout=5)
        assert not proxy._thread.is_alive()
        # Clean up (stop is safe to call even after thread exited)
        proxy.stop()

    @patch("subprocess.run")
    def test_socket_is_world_writable(self, mock_run, sock_path):
        proxy = PushProxy(sock_path, "/w", "branch")
        proxy.start()
        try:
            mode = os.stat(sock_path).st_mode
            assert mode & 0o777 == 0o777
        finally:
            proxy.stop()

    def test_stop_leaves_a_socket_it_no_longer_owns(self, sock_path):
        """A daemon whose path was rebound must not unlink the new socket."""
        proxy = PushProxy(sock_path, "/w", "branch")
        proxy.start()
        # Another daemon replaces the socket at the same path.
        os.unlink(sock_path)
        Path(sock_path).write_text("replacement")
        proxy.stop()
        assert Path(sock_path).read_text() == "replacement"

    def test_stop_does_not_unlink_a_socket_it_never_bound(self, sock_path):
        """start() that raised at bind() owns no socket and must not unlink."""
        Path(sock_path).write_text("someone else's socket")
        proxy = PushProxy(sock_path, "/w", "branch")
        proxy._server_socket = MagicMock()  # created, then bind() raised
        proxy._bound = False
        proxy.stop()
        assert Path(sock_path).read_text() == "someone else's socket"

    def test_socket_is_current_tracks_removal_and_replacement(self, sock_path):
        """Both the serve loop and the daemon wait loop use this check."""
        proxy = PushProxy(sock_path, "/w", "branch")
        proxy.start()
        try:
            assert proxy.socket_is_current()
            os.unlink(sock_path)
            assert not proxy.socket_is_current()  # removed -> exit
            Path(sock_path).write_text("replacement")
            assert not proxy.socket_is_current()  # rebound -> not ours
        finally:
            proxy.stop()

    def test_socket_is_current_falls_back_to_existence_without_inode(
            self, sock_path):
        """Without a recorded inode the daemon still notices removal."""
        proxy = PushProxy(sock_path, "/w", "branch")
        proxy.start()
        try:
            proxy._sock_ino = None  # stat failed at bind time
            assert proxy.socket_is_current()
            os.unlink(sock_path)
            assert not proxy.socket_is_current()
        finally:
            proxy.stop()

    def test_daemon_wait_loop_exits_when_socket_is_replaced(self, sock_path):
        """The daemon *process* must exit, not just its serve thread."""
        proxy = PushProxy(sock_path, "/w", "branch")
        proxy.start()
        try:
            os.unlink(sock_path)
            Path(sock_path).write_text("replacement")
            done = threading.Event()

            def run() -> None:
                push_proxy_mod._wait_for_socket_exit(
                    proxy, threading.Event(), interval=0.01)
                done.set()

            threading.Thread(target=run, daemon=True).start()
            assert done.wait(5.0), (
                "daemon wait loop did not notice the replaced socket")
        finally:
            proxy.stop()


class TestStartLock:
    """The per-directory start lock must survive a racing teardown (R7).

    ``flock`` locks the inode, not the name: a lock file unlinked between
    ``open()`` and ``flock()`` leaves the holder with a lock no other
    process can see, so a second process can create a fresh file and enter
    the check-and-spawn critical section concurrently.
    """

    def test_start_lock_retries_when_the_lock_file_is_replaced(self,
                                                               tmp_path):
        sock_dir = str(tmp_path / "lockdir")
        lock_path = sock_dir + ".lock"
        real_flock = fcntl.flock
        raced = []

        def racy_flock(fd, flags):
            real_flock(fd, flags)
            if not raced:
                raced.append(True)
                # A teardown clears the lock file in the open→flock window.
                os.unlink(lock_path)

        with patch("pm_core.push_proxy.fcntl.flock", side_effect=racy_flock):
            with push_proxy_mod._start_lock(sock_dir) as locked:
                assert locked is True
                assert os.path.exists(lock_path), (
                    "lock held on an unlinked inode; a concurrent start "
                    "could create a fresh lock file and bypass it")
                with push_proxy_mod._start_lock(sock_dir,
                                                blocking=False) as second:
                    assert second is False, (
                        "the retried lock must be exclusive")

    def test_clear_lock_file_keeps_a_replacement(self, tmp_path):
        """A lock file replaced in the open→flock window is not ours to delete."""
        lock_path = str(tmp_path / "x.lock")
        Path(lock_path).write_text("old")
        real_flock = fcntl.flock
        raced = []

        def racy_flock(fd, flags):
            real_flock(fd, flags)
            if not raced:
                raced.append(True)
                os.unlink(lock_path)
                Path(lock_path).write_text("new")

        with patch("pm_core.push_proxy.fcntl.flock", side_effect=racy_flock):
            push_proxy_mod._clear_lock_file(lock_path)

        assert Path(lock_path).exists(), (
            "teardown deleted a replacement lock file another process owns")
        assert Path(lock_path).read_text() == "new"

    @pytest.mark.skipif(os.geteuid() == 0,
                        reason="root ignores the 0o000 lock-file mode")
    def test_unopenable_lock_file_is_skipped_by_teardown(self, tmp_path):
        """A /tmp lock file another user planted must not abort a sweep.

        Teardown takes the lock non-blocking and treats "cannot open" like
        "busy": skip this directory.  A start, by contrast, must fail loudly
        as a PushProxyError rather than leak a bare PermissionError.
        """
        from pm_core.push_proxy import PushProxyError

        sock_dir = str(tmp_path / "lockperm")
        os.makedirs(sock_dir, exist_ok=True)
        lock_path = sock_dir + ".lock"
        Path(lock_path).write_text("")
        os.chmod(lock_path, 0o000)
        try:
            with push_proxy_mod._start_lock(sock_dir, blocking=False) as held:
                assert held is False
            with pytest.raises(PushProxyError, match="start lock"):
                with push_proxy_mod._start_lock(sock_dir, blocking=True):
                    pass
        finally:
            os.chmod(lock_path, 0o600)


class TestSharedProxy:
    """Tests for (session_tag, pr_id) shared proxy behaviour."""

    def _mock_start(self):
        """Patch _start_proxy_subprocess to create a dummy socket file."""
        def fake_start(sock_path, workdir, branch):
            os.makedirs(os.path.dirname(sock_path), exist_ok=True)
            Path(sock_path).touch()
            return True
        return patch("pm_core.push_proxy._start_proxy_subprocess",
                     side_effect=fake_start)

    def test_shared_proxy_reuse(self):
        """Multiple containers on the same branch reuse one proxy."""
        with self._mock_start(), \
             patch("pm_core.push_proxy.proxy_is_alive", return_value=True):
            sock1 = start_push_proxy("c1", "/w", "pm/pr-1",
                                     session_tag="repo-abc", pr_id="pr-1")
            sock2 = start_push_proxy("c2", "/w", "pm/pr-1",
                                     session_tag="repo-abc", pr_id="pr-1")
            # Same socket path
            assert sock1 == sock2
            # Both containers can look up the socket
            assert get_proxy_socket_path("c1") == sock1
            assert get_proxy_socket_path("c2") == sock1

            # Stopping c1 should NOT stop the proxy (c2 still using it)
            stop_push_proxy("c1")
            assert get_proxy_socket_path("c2") == sock1

            # Stopping c2 should stop the proxy
            stop_push_proxy("c2")
            assert get_proxy_socket_path("c2") is None

    def test_shared_proxy_deterministic_path(self):
        """Shared proxy socket path is deterministic per workdir."""
        with self._mock_start():
            sock = start_push_proxy("c1", "/w", "pm/pr-1",
                                    session_tag="repo-abc", pr_id="pr-1")
            token = push_proxy_mod._workdir_token("/w")
            assert sock == (
                f"/tmp/pm-push-proxy-repo-abc-pr-1-{token}/push.sock")
            # A different workdir gets its own deterministic path.
            sock2 = start_push_proxy("c2", "/w2", "pm/pr-1",
                                     session_tag="repo-abc", pr_id="pr-1")
            assert sock2 != sock
            stop_push_proxy("c1")
            stop_push_proxy("c2")

    def test_stop_session_proxies(self):
        """stop_session_proxies cleans up all proxies for a session."""
        with self._mock_start():
            start_push_proxy("c1", "/w", "b1",
                             session_tag="repo-abc", pr_id="pr-1")
            start_push_proxy("c2", "/w", "b2",
                             session_tag="repo-abc", pr_id="pr-2")
            assert get_proxy_socket_path("c1") is not None
            assert get_proxy_socket_path("c2") is not None

            count = stop_session_proxies("repo-abc")
            assert count == 2
            assert get_proxy_socket_path("c1") is None
            assert get_proxy_socket_path("c2") is None

    def test_different_sessions_different_proxies(self):
        """Different sessions get separate proxies even for the same PR."""
        with self._mock_start():
            sock1 = start_push_proxy("c1", "/w", "b",
                                     session_tag="repo-aaa", pr_id="pr-1")
            sock2 = start_push_proxy("c2", "/w", "b",
                                     session_tag="repo-bbb", pr_id="pr-1")
            assert sock1 != sock2
            stop_push_proxy("c1")
            stop_push_proxy("c2")


class TestCallerWorkdir:
    """The 'workdir' request field must match the proxy's own workdir.

    Each proxy is keyed by (session_tag, pr_id, workdir), so a request that
    names a *different* workdir must be rejected rather than silently run
    against another clone.
    """

    @pytest.fixture
    def workdir(self, tmp_path):
        d = tmp_path / "proxy-workdir"
        d.mkdir()
        return d

    @pytest.fixture
    def proxy(self, sock_path, workdir):
        p = PushProxy(sock_path, str(workdir), "pm/pr-123-feature")
        p.start()
        yield p
        p.stop()

    @patch("subprocess.run")
    @patch("pm_core.push_proxy._resolve_local_remote_url",
           return_value="/some/pr-workdir")
    def test_rejects_local_path_origin(self, _mock_resolve, mock_run,
                                       proxy, sock_path, workdir):
        """Local-path origins are rejected: the old fetch-into-target fallback
        silently desynced the target's worktree, so this is now fail-closed.
        Scenario clones must rewrite origin to the real upstream URL before
        pushing."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        resp = _send_request(sock_path, {
            "cmd": "push",
            "args": ["origin", "pm/pr-123-feature"],
            "workdir": str(workdir),
        })
        assert resp["exit_code"] == 1
        assert "local path" in resp["stderr"]
        # No git push subprocess should have been invoked.
        push_calls = [c for c in mock_run.call_args_list
                      if c[0][0][:2] == ["git", "-C"] and "push" in c[0][0]]
        assert not push_calls

    @patch("subprocess.run")
    @patch("pm_core.push_proxy._resolve_local_remote_url", return_value=None)
    def test_push_runs_from_proxy_workdir(self, _mock_resolve, mock_run,
                                          proxy, sock_path, workdir):
        """When origin is a real URL, push runs `git -C <proxy workdir>`."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        resp = _send_request(sock_path, {
            "cmd": "push",
            "args": ["origin", "pm/pr-123-feature"],
            "workdir": str(workdir),
        })
        assert resp["exit_code"] == 0
        push_calls = [c for c in mock_run.call_args_list
                      if c[0][0][:2] == ["git", "-C"] and "push" in c[0][0]]
        assert len(push_calls) == 1
        push_cmd = push_calls[0][0][0]
        assert push_cmd[2] == str(workdir)
        assert push_cmd[3:] == ["push", "origin", "pm/pr-123-feature"]

    @patch("subprocess.run")
    def test_fetch_uses_proxy_workdir(self, mock_run, proxy, sock_path,
                                      workdir):
        """git fetch runs from the proxy's own workdir."""
        mock_run.return_value = MagicMock(returncode=0, stdout="fetched\n", stderr="")
        resp = _send_request(sock_path, {
            "cmd": "fetch",
            "args": ["origin"],
            "workdir": str(workdir),
        })
        assert resp["exit_code"] == 0
        fetch_call = mock_run.call_args
        assert fetch_call[1]["cwd"] == str(workdir)

    @patch("subprocess.run")
    def test_pull_uses_proxy_workdir(self, mock_run, proxy, sock_path, workdir):
        """git pull runs from the proxy's own workdir."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        resp = _send_request(sock_path, {
            "cmd": "pull",
            "args": ["origin"],
            "workdir": str(workdir),
        })
        assert resp["exit_code"] == 0
        assert mock_run.call_args[1]["cwd"] == str(workdir)

    @patch("subprocess.run")
    def test_no_workdir_field_falls_back_to_self_workdir(self, mock_run, proxy,
                                                          sock_path, workdir):
        """Legacy requests without 'workdir' fall back to self.workdir."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        resp = _send_request(sock_path, {
            "cmd": "fetch",
            "args": ["origin"],
            # no "workdir" key
        })
        assert resp["exit_code"] == 0
        assert mock_run.call_args[1]["cwd"] == str(workdir)

    @patch("subprocess.run")
    def test_empty_workdir_field_falls_back_to_self_workdir(self, mock_run, proxy,
                                                             sock_path, workdir):
        """An empty-string 'workdir' is treated the same as absent."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        resp = _send_request(sock_path, {
            "cmd": "pull",
            "args": [],
            "workdir": "",
        })
        assert resp["exit_code"] == 0
        assert mock_run.call_args[1]["cwd"] == str(workdir)

    @patch("subprocess.run")
    @patch("pm_core.push_proxy._resolve_local_remote_url", return_value=None)
    def test_no_workdir_push_falls_back_to_self_workdir(
            self, _mock_resolve, mock_run, proxy, sock_path, workdir):
        """Legacy push without 'workdir' falls back to self.workdir as source."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        resp = _send_request(sock_path, {
            "cmd": "push",
            "args": ["origin", "pm/pr-123-feature"],
            # no "workdir" key — legacy caller
        })
        assert resp["exit_code"] == 0
        push_calls = [c for c in mock_run.call_args_list
                      if c[0][0][:2] == ["git", "-C"] and "push" in c[0][0]]
        assert len(push_calls) == 1
        push_cmd = push_calls[0][0][0]
        # Source must be self.workdir, not some caller path
        assert push_cmd[2] == str(workdir)

    @patch("subprocess.run")
    @patch("pm_core.push_proxy._resolve_local_remote_url", return_value=None)
    def test_empty_workdir_push_falls_back_to_self_workdir(
            self, _mock_resolve, mock_run, proxy, sock_path, workdir):
        """An empty-string 'workdir' in a push request falls back to self.workdir."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        resp = _send_request(sock_path, {
            "cmd": "push",
            "args": ["origin", "pm/pr-123-feature"],
            "workdir": "",   # empty string — behaves like absent
        })
        assert resp["exit_code"] == 0
        push_calls = [c for c in mock_run.call_args_list
                      if c[0][0][:2] == ["git", "-C"] and "push" in c[0][0]]
        assert len(push_calls) == 1
        push_cmd = push_calls[0][0][0]
        assert push_cmd[2] == str(workdir)

    @patch("subprocess.run")
    def test_ls_remote_accepts_proxy_workdir(self, mock_run, proxy, sock_path,
                                             workdir):
        """ls-remote runs from the proxy's workdir."""
        mock_run.return_value = MagicMock(returncode=0, stdout="abc HEAD\n", stderr="")
        resp = _send_request(sock_path, {
            "cmd": "ls-remote",
            "args": ["origin"],
            "workdir": str(workdir),
        })
        assert resp["exit_code"] == 0
        assert resp["stdout"] == "abc HEAD\n"

    @patch("subprocess.run")
    def test_foreign_workdir_is_rejected(self, mock_run, proxy, sock_path,
                                         tmp_path):
        """A request naming another existing clone is rejected, not served."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        other = tmp_path / "other-clone"
        other.mkdir()
        resp = _send_request(sock_path, {
            "cmd": "push",
            "args": ["origin", "pm/pr-123-feature"],
            "workdir": str(other),
        })
        assert resp["exit_code"] == 1
        assert "does not match" in resp["stderr"]
        assert not [c for c in mock_run.call_args_list
                    if c[0][0][:2] == ["git", "-C"]]

    @patch("subprocess.run")
    def test_missing_workdir_is_rejected(self, mock_run, proxy, sock_path,
                                         workdir):
        """A request naming a workdir that no longer exists fails explicitly."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        # The request matches the proxy's own workdir, but the clone is gone.
        workdir.rmdir()
        resp = _send_request(sock_path, {
            "cmd": "push",
            "args": ["origin", "pm/pr-123-feature"],
            "workdir": str(workdir),
        })
        assert resp["exit_code"] == 1
        assert "does not exist" in resp["stderr"]
        assert not [c for c in mock_run.call_args_list
                    if c[0][0][:2] == ["git", "-C"]]

    @patch("subprocess.run")
    def test_no_refspec_head_resolved_from_proxy_workdir(self, mock_run,
                                                         sock_path, workdir):
        """_extract_target_branch resolves HEAD in the proxy's workdir."""
        p = PushProxy(sock_path, str(workdir), "feature/x")
        p.start()

        def side_effect(cmd, **kwargs):
            cwd = kwargs.get("cwd", "")
            if "rev-parse" in cmd:
                if cwd == str(workdir):
                    return MagicMock(returncode=0, stdout="feature/x\n", stderr="")
                return MagicMock(returncode=0, stdout="main\n", stderr="")
            if "remote" in cmd and "get-url" in cmd:
                # Return non-zero so _resolve_local_remote_url returns None
                # (no local target → fall through to git push path)
                return MagicMock(returncode=1, stdout="", stderr="")
            # Actual git push
            return MagicMock(returncode=0, stdout="ok\n", stderr="")

        mock_run.side_effect = side_effect

        resp = _send_request(sock_path, {
            "cmd": "push",
            "args": ["origin"],  # no refspec — HEAD must be resolved
            "workdir": str(workdir),
        })

        assert resp["exit_code"] == 0, (
            "Expected push to be allowed; got: " + resp.get("stderr", "")
        )

        rev_parse_calls = [
            c for c in mock_run.call_args_list
            if "rev-parse" in c[0][0]
        ]
        assert len(rev_parse_calls) >= 1
        assert all(
            c[1].get("cwd") == str(workdir)
            for c in rev_parse_calls
        ), "rev-parse must run in the proxy's workdir"

        p.stop()


@pytest.fixture
def live_proxies():
    """Start real in-process PushProxy daemons instead of subprocesses.

    Patches ``_start_proxy_subprocess`` so ``start_push_proxy`` drives a
    real socket in this process.  Every daemon is stopped and its socket
    directory removed at teardown.
    """
    started = []

    def fake_start(sock_path, workdir, branch):
        os.makedirs(os.path.dirname(sock_path), exist_ok=True)
        p = PushProxy(sock_path, workdir, branch)
        p.start()
        started.append(p)
        return True

    with patch("pm_core.push_proxy._start_proxy_subprocess",
               side_effect=fake_start):
        yield started

    for p in started:
        p.stop()
        d = os.path.dirname(p.socket_path)
        real = os.path.realpath(d)
        try:
            os.unlink(real + ".lock")
        except OSError:
            pass
        shutil.rmtree(real, ignore_errors=True)
        if os.path.islink(d):
            try:
                os.unlink(d)
            except OSError:
                pass


class TestWorkdirKeyedProxies:
    """impl and QA containers on one PR must not share a proxy socket."""

    TAG = "repo-wd"
    PR = "pr-wd"
    BRANCH = "pm/pr-wd"

    def _workdir(self, tmp_path, name):
        d = tmp_path / name
        d.mkdir()
        return d

    def _start(self, container, workdir, tag=None, pr=None, branch=None):
        return start_push_proxy(
            container, str(workdir), branch or self.BRANCH,
            session_tag=tag or self.TAG, pr_id=pr or self.PR,
        )

    def test_impl_and_qa_get_distinct_proxies(self, tmp_path, live_proxies):
        impl = self._workdir(tmp_path, "impl")
        qa1 = self._workdir(tmp_path, "s-1")
        qa2 = self._workdir(tmp_path, "s-2")

        s_impl = self._start("impl-wd", impl)
        s_qa1 = self._start("qa-wd-1", qa1)
        s_qa2 = self._start("qa-wd-2", qa2)

        assert len({s_impl, s_qa1, s_qa2}) == 3
        assert all(push_proxy_mod.proxy_is_alive(s)
                   for s in (s_impl, s_qa1, s_qa2))

        # Same workdir + same PR still reuses one proxy.
        s_impl2 = self._start("impl-wd-2", impl)
        assert s_impl2 == s_impl

    @patch("pm_core.push_proxy._resolve_local_remote_url", return_value=None)
    @patch("subprocess.run")
    def test_each_proxy_serves_its_own_workdir(self, mock_run, _mock_resolve,
                                               tmp_path, live_proxies):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        impl = self._workdir(tmp_path, "impl")
        qa = self._workdir(tmp_path, "s-1")
        s_impl = self._start("impl-wd", impl)
        s_qa = self._start("qa-wd", qa)

        for sock, wd in ((s_impl, impl), (s_qa, qa)):
            resp = _send_request(sock, {
                "cmd": "push",
                "args": ["origin", self.BRANCH],
                "workdir": str(wd),
            })
            assert resp["exit_code"] == 0, resp.get("stderr")

        pushes = [c[0][0] for c in mock_run.call_args_list
                  if c[0][0][:2] == ["git", "-C"] and "push" in c[0][0]]
        assert [cmd[2] for cmd in pushes] == [str(impl), str(qa)]

    def test_stopping_one_workdir_leaves_others_alive(self, tmp_path,
                                                      live_proxies):
        impl = self._workdir(tmp_path, "impl")
        qa1 = self._workdir(tmp_path, "s-1")
        qa2 = self._workdir(tmp_path, "s-2")
        s_impl = self._start("impl-wd", impl)
        s_qa1 = self._start("qa-wd-1", qa1)
        s_qa2 = self._start("qa-wd-2", qa2)

        stop_push_proxy("qa-wd-1")

        assert not push_proxy_mod.proxy_is_alive(s_qa1)
        assert push_proxy_mod.proxy_is_alive(s_impl)
        assert push_proxy_mod.proxy_is_alive(s_qa2)

    def test_respawn_keeps_other_containers_references(self, tmp_path,
                                                       live_proxies):
        """Respawning must not drop a sibling container's refcount.

        Two containers share one workdir; the socket dies; the first one to
        restart respawns the daemon.  Stopping *it* must not kill the proxy
        the other container still uses.
        """
        impl = self._workdir(tmp_path, "impl")
        sock = self._start("impl-a", impl)
        assert self._start("impl-b", impl) == sock  # reuse, refs {a, b}

        os.unlink(sock)  # daemon died
        time.sleep(0.1)
        assert self._start("impl-a", impl) == sock  # respawn

        stop_push_proxy("impl-a")
        assert push_proxy_mod.proxy_is_alive(sock), (
            "impl-b still references this proxy")

    def test_container_moving_workdir_drops_its_old_reference(
            self, tmp_path, live_proxies):
        """A container only ever pins one proxy key."""
        first = self._workdir(tmp_path, "first")
        second = self._workdir(tmp_path, "second")
        self._start("mover", first)
        self._start("mover", second)

        old_key = push_proxy_mod._shared_proxy_key(
            self.TAG, self.PR, push_proxy_mod._workdir_token(str(first)))
        assert "mover" not in push_proxy_mod._proxy_refs.get(old_key, set())

    def test_restart_after_socket_death_does_not_disturb_other_workdir(
            self, tmp_path, live_proxies):
        impl = self._workdir(tmp_path, "impl")
        qa = self._workdir(tmp_path, "s-1")
        s_impl = self._start("impl-wd", impl)
        s_qa = self._start("qa-wd", qa)
        assert s_impl != s_qa

        # Simulate the daemon dying between an impl restart and a QA launch.
        os.unlink(s_impl)
        time.sleep(0.1)

        s_impl2 = self._start("impl-wd-restart", impl)
        assert s_impl2 == s_impl
        assert push_proxy_mod.proxy_is_alive(s_impl2)
        assert push_proxy_mod.proxy_is_alive(s_qa)

    def test_shared_stop_keeps_socket_dir(self, tmp_path, live_proxies):
        impl = self._workdir(tmp_path, "impl")
        sock = self._start("impl-wd", impl)
        sock_dir = os.path.dirname(sock)

        stop_push_proxy("impl-wd")

        assert not os.path.exists(sock)
        # The directory is kept so a container bind-mount stays valid.
        assert os.path.isdir(sock_dir)

    def _key_for(self, workdir):
        return push_proxy_mod._shared_proxy_key(
            self.TAG, self.PR, push_proxy_mod._workdir_token(str(workdir)))

    def test_shared_stop_kills_an_unreferenced_socket(self, tmp_path,
                                                      live_proxies):
        """The guarded stop path still stops a proxy nothing references."""
        impl = self._workdir(tmp_path, "impl")
        sock = self._start("impl-wd", impl)
        sock_dir = os.path.dirname(sock)
        key = self._key_for(impl)
        with push_proxy_mod._proxy_lock:
            push_proxy_mod._proxy_refs.pop(key, None)

        push_proxy_mod._stop_shared_proxy_socket(key, sock_dir, sock)

        assert not push_proxy_mod.proxy_is_alive(sock)
        assert os.path.isdir(sock_dir)  # R6: dir kept for the mount

    def test_shared_stop_skips_a_socket_re_referenced_mid_stop(
            self, tmp_path, live_proxies):
        """A start that reused the socket during the stop must keep it alive.

        The stopping container's reference is already gone when the kill
        runs; a concurrent start can register a new container on the same
        key in that window.  Unlinking then would leave the new container
        with a dead socket (the S18 failure through another door).
        """
        impl = self._workdir(tmp_path, "impl")
        sock = self._start("impl-wd", impl)
        key = self._key_for(impl)
        with push_proxy_mod._proxy_lock:
            push_proxy_mod._proxy_refs.pop(key, None)
            # Simulate the concurrent start re-registering a container.
            push_proxy_mod._proxy_refs.setdefault(key, set()).add("late-wd")

        push_proxy_mod._stop_shared_proxy_socket(
            key, os.path.dirname(sock), sock)

        assert push_proxy_mod.proxy_is_alive(sock)

    def test_shared_stop_skips_when_a_start_holds_the_lock(
            self, tmp_path, live_proxies):
        """A start in flight owns the decision; teardown leaves it alone."""
        impl = self._workdir(tmp_path, "impl")
        sock = self._start("impl-wd", impl)
        sock_dir = os.path.dirname(sock)
        key = self._key_for(impl)
        with push_proxy_mod._proxy_lock:
            push_proxy_mod._proxy_refs.pop(key, None)

        with push_proxy_mod._start_lock(sock_dir, blocking=False) as locked:
            assert locked
            push_proxy_mod._stop_shared_proxy_socket(key, sock_dir, sock)
            assert push_proxy_mod.proxy_is_alive(sock)

    def test_refuses_live_proxy_with_different_workdir(
            self, tmp_path, monkeypatch, live_proxies):
        from pm_core.push_proxy import PushProxyConflict

        impl = self._workdir(tmp_path, "impl")
        other = self._workdir(tmp_path, "other")
        # Force a key collision to exercise the metadata guard.
        monkeypatch.setattr("pm_core.push_proxy._workdir_token",
                            lambda w: "collision")

        self._start("impl-wd", impl)
        with pytest.raises(PushProxyConflict):
            self._start("other-wd", other)

    def test_refuses_live_proxy_with_different_branch(self, tmp_path,
                                                      live_proxies):
        from pm_core.push_proxy import PushProxyConflict

        impl = self._workdir(tmp_path, "impl")
        self._start("impl-wd", impl, branch="pm/pr-a")
        with pytest.raises(PushProxyConflict):
            self._start("impl-wd-2", impl, branch="pm/pr-b")

    def test_get_proxy_socket_path_is_per_workdir(self, tmp_path,
                                                  live_proxies):
        impl = self._workdir(tmp_path, "impl")
        qa = self._workdir(tmp_path, "s-1")
        s_impl = self._start("impl-wd", impl)
        s_qa = self._start("qa-wd", qa)

        assert get_proxy_socket_path(
            "impl-wd", session_tag=self.TAG, pr_id=self.PR,
            workdir=str(impl)) == os.path.realpath(s_impl)
        assert get_proxy_socket_path(
            "qa-wd", session_tag=self.TAG, pr_id=self.PR,
            workdir=str(qa)) == os.path.realpath(s_qa)

        other = self._workdir(tmp_path, "other")
        assert get_proxy_socket_path(
            "other-wd", session_tag=self.TAG, pr_id=self.PR,
            workdir=str(other)) is None

    def test_stale_socket_file_is_replaced(self, tmp_path, live_proxies):
        """A leftover non-listening socket file is replaced, not trusted."""
        impl = self._workdir(tmp_path, "impl")
        token = push_proxy_mod._workdir_token(str(impl))
        sock_dir = push_proxy_mod._shared_sock_dir_path(
            self.TAG, self.PR, token)
        os.makedirs(sock_dir, exist_ok=True)
        sock = os.path.join(sock_dir, "push.sock")
        Path(sock).touch()  # stale regular file, not a listening socket

        started = self._start("impl-wd", impl)
        assert started == sock
        assert push_proxy_mod.proxy_is_alive(started)

    def test_stop_session_removes_kept_socket_dirs(self, tmp_path,
                                                   live_proxies):
        impl = self._workdir(tmp_path, "impl")
        sock = self._start("impl-wd", impl)
        sock_dir = os.path.dirname(sock)

        stop_push_proxy("impl-wd")
        assert os.path.isdir(sock_dir)  # kept for live container mounts

        stop_session_proxies(self.TAG)
        assert not os.path.exists(sock_dir)

    def test_discovery_symlink_failure_does_not_break_start(
            self, tmp_path, live_proxies):
        """The long-name symlink is optional; losing it must not fail a start.

        A session tag long enough to force the hashed directory can also
        make the discovery symlink fail (name too long).  The proxy must
        still start, and session teardown must still find it through the
        in-process registry.
        """
        impl = self._workdir(tmp_path, "impl")
        tag = "t" * 80
        with patch("pm_core.push_proxy.os.symlink",
                   side_effect=OSError("name too long")):
            sock = self._start("impl-nosym", impl, tag=tag)
        try:
            assert push_proxy_mod.proxy_is_alive(sock)
            assert stop_session_proxies(tag) >= 1
            assert not push_proxy_mod.proxy_is_alive(sock)
        finally:
            stop_session_proxies(tag)

    def test_stop_session_finds_hashed_dir_without_long_symlink(
            self, tmp_path, live_proxies):
        """Teardown must stop a proxy the ``{tag}-*`` glob cannot reach.

        A long session tag forces the hashed socket directory plus a
        long-named symlink for discovery.  If that symlink is missing the
        glob matches nothing, but the in-process registry still knows the
        socket and must stop it (otherwise it and its dir leak).
        """
        tag = "t" * 80
        impl = self._workdir(tmp_path, "impl")
        sock = self._start("impl-long", impl, tag=tag)
        sock_dir = os.path.dirname(sock)
        token = push_proxy_mod._workdir_token(str(impl))
        long_dir = f"/tmp/{push_proxy_mod._SOCKET_DIR_PREFIX}{tag}-{self.PR}-{token}"
        assert os.path.islink(long_dir)
        assert sock_dir == push_proxy_mod._shared_sock_dir_path(
            tag, self.PR, token)

        os.unlink(long_dir)  # discovery symlink lost

        assert stop_session_proxies(tag) >= 1
        assert not push_proxy_mod.proxy_is_alive(sock)
        assert not os.path.exists(sock_dir)

    def test_sweep_refuses_to_delete_a_foreign_symlink_target(self, tmp_path):
        """Teardown must not rmtree whatever a /tmp symlink happens to point at."""
        target = tmp_path / "not-a-proxy-dir"
        target.mkdir()
        (target / "keep.txt").write_text("keep\n")
        link = "/tmp/pm-push-proxy-sweepguard-evil"
        os.symlink(str(target), link)
        try:
            push_proxy_mod._remove_proxy_dirs("/tmp/pm-push-proxy-sweepguard-*")
            assert (target / "keep.txt").exists()
            assert not os.path.lexists(link)
        finally:
            if os.path.lexists(link):
                os.unlink(link)

    def test_sweep_refuses_a_dir_owned_by_another_user(self, tmp_path,
                                                       monkeypatch):
        """/tmp is world-writable; only our own proxy dirs may be deleted."""
        other = "/tmp/pm-push-proxy-uidguard-evil"
        os.makedirs(other, exist_ok=True)
        Path(other, "keep.txt").write_text("keep\n")
        real_uid = os.getuid()  # capture before patching the module's os
        monkeypatch.setattr("pm_core.push_proxy.os.getuid",
                            lambda: real_uid + 1)
        try:
            push_proxy_mod._remove_proxy_dirs("/tmp/pm-push-proxy-uidguard-*")
            assert Path(other, "keep.txt").exists()
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_kill_proxy_socket_refuses_a_foreign_symlink_target(self, tmp_path):
        """stop_all/stop_session must not unlink inside a planted link target.

        Those sweeps build their paths from a /tmp glob, so a symlink named
        like a proxy dir must never make the teardown delete files inside
        whatever directory it points at.
        """
        target = tmp_path / "victim"
        target.mkdir()
        (target / "push.sock").write_text("do not delete\n")
        (target / "proxy.json").write_text("{}\n")
        link = "/tmp/pm-push-proxy-killguard-evil"
        os.symlink(str(target), link)
        try:
            push_proxy_mod._kill_proxy_socket(f"{link}/push.sock")
            assert (target / "push.sock").exists()
            assert (target / "proxy.json").exists()
            assert not os.path.lexists(link)
        finally:
            if os.path.lexists(link):
                os.unlink(link)

    def test_kill_proxy_socket_refuses_a_dir_owned_by_another_user(
            self, monkeypatch):
        """Another user's proxy-shaped dir must not abort or be deleted."""
        other = "/tmp/pm-push-proxy-killuid-evil"
        os.makedirs(other, exist_ok=True)
        Path(other, "push.sock").write_text("keep\n")
        real_uid = os.getuid()  # capture before patching the module's os
        monkeypatch.setattr("pm_core.push_proxy.os.getuid",
                            lambda: real_uid + 1)
        try:
            push_proxy_mod._kill_proxy_socket(f"{other}/push.sock")
            assert Path(other, "push.sock").exists()
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_kill_proxy_socket_removes_a_directory_at_the_socket_path(self):
        """Docker leaves a directory where a bind-mounted socket should be."""
        sock_dir = "/tmp/pm-push-proxy-dirguard-impl"
        os.makedirs(os.path.join(sock_dir, "push.sock"), exist_ok=True)
        try:
            push_proxy_mod._kill_proxy_socket(f"{sock_dir}/push.sock")
            assert not os.path.exists(sock_dir)
        finally:
            shutil.rmtree(sock_dir, ignore_errors=True)

    def test_start_raises_when_daemon_not_ready(self, tmp_path):
        from pm_core.push_proxy import PushProxyError

        impl = self._workdir(tmp_path, "impl")
        with patch("pm_core.push_proxy._start_proxy_subprocess",
                   return_value=False):
            with pytest.raises(PushProxyError):
                self._start("not-ready", impl)

    def test_concurrent_starts_spawn_one_daemon(self, tmp_path):
        """The per-directory start lock serialises check-and-spawn (R7)."""
        impl = self._workdir(tmp_path, "impl")
        spawns: list[str] = []
        started: list[PushProxy] = []
        spawn_lock = threading.Lock()

        def fake_start(sock_path, workdir, branch):
            with spawn_lock:
                spawns.append(sock_path)
            time.sleep(0.2)  # widen the unlink→bind window
            os.makedirs(os.path.dirname(sock_path), exist_ok=True)
            p = PushProxy(sock_path, workdir, branch)
            p.start()
            started.append(p)
            return True

        results: list[str] = []

        def worker(name: str) -> None:
            results.append(self._start(name, impl))

        with patch("pm_core.push_proxy._start_proxy_subprocess",
                   side_effect=fake_start):
            threads = [threading.Thread(target=worker, args=(f"c{i}",))
                       for i in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=20)

        try:
            assert not any(t.is_alive() for t in threads)
            assert len(spawns) == 1, f"expected one spawn, got {len(spawns)}"
            assert len(set(results)) == 1
            assert push_proxy_mod.proxy_is_alive(results[0])
        finally:
            for p in started:
                p.stop()

    def test_sweep_leaves_a_live_proxy_dir_in_place(self, tmp_path,
                                                    live_proxies):
        """Teardown must not delete a socket dir a container still mounts."""
        impl = self._workdir(tmp_path, "impl")
        sock = self._start("impl-wd", impl)
        sock_dir = os.path.dirname(sock)

        push_proxy_mod._remove_proxy_dirs(f"/tmp/pm-push-proxy-{self.TAG}-*")

        assert push_proxy_mod.proxy_is_alive(sock)
        assert os.path.isdir(sock_dir)

    def test_sweep_skips_a_dir_whose_start_lock_is_held(self, tmp_path):
        """A start in flight keeps its dir and lock file through teardown."""
        sock_dir = "/tmp/pm-push-proxy-lockguard-impl"
        os.makedirs(sock_dir, exist_ok=True)
        lock = sock_dir + ".lock"
        fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            push_proxy_mod._remove_proxy_dirs(
                "/tmp/pm-push-proxy-lockguard-*")
            assert os.path.isdir(sock_dir)
            assert os.path.exists(lock)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

        push_proxy_mod._remove_proxy_dirs("/tmp/pm-push-proxy-lockguard-*")
        assert not os.path.exists(sock_dir)
        assert not os.path.exists(lock)

    def test_sweep_resolves_a_symlinked_parent(self, tmp_path):
        """A symlinked /tmp (macOS: /tmp -> /private/tmp) must not defeat the sweep.

        ``_remove_proxy_dirs`` compares the resolved entry path against the
        glob's parent, so the parent has to be resolved too — otherwise every
        legitimate proxy directory is refused and teardown leaks them.
        """
        alias = str(tmp_path / "tmpalias")
        os.symlink("/tmp", alias)
        sock_dir = os.path.join(alias, "pm-push-proxy-sweepparent-impl")
        os.makedirs(sock_dir, exist_ok=True)
        Path(sock_dir, "push.sock").write_text("stale\n")
        try:
            push_proxy_mod._remove_proxy_dirs(
                os.path.join(alias, "pm-push-proxy-sweepparent-*"))
            assert not os.path.exists(sock_dir)
        finally:
            shutil.rmtree(sock_dir, ignore_errors=True)

    def test_shared_sock_dir_keeps_a_foreign_directory(self, monkeypatch):
        """/tmp is world-writable; a planted real dir is not ours to delete."""
        tag = "t" * 80  # forces the hashed directory + discovery symlink
        impl = "/tmp/some-impl-workdir"
        token = push_proxy_mod._workdir_token(impl)
        short_dir = push_proxy_mod._shared_sock_dir_path(tag, self.PR, token)
        long_dir = f"/tmp/{push_proxy_mod._SOCKET_DIR_PREFIX}{tag}-{self.PR}-{token}"
        os.makedirs(long_dir, exist_ok=True)
        Path(long_dir, "keep.txt").write_text("keep\n")
        real_uid = os.getuid()  # capture before patching the module's os
        monkeypatch.setattr("pm_core.push_proxy.os.getuid",
                            lambda: real_uid + 1)
        try:
            assert push_proxy_mod._shared_sock_dir(tag, self.PR, token) == short_dir
            assert Path(long_dir, "keep.txt").exists(), (
                "teardown replaced a directory owned by another user")
            assert not os.path.islink(long_dir)
            assert os.path.isdir(short_dir)
        finally:
            shutil.rmtree(long_dir, ignore_errors=True)


class TestIntegrationFetchPull:
    """Integration tests: fetch/pull land in the requesting scenario's clone."""

    @pytest.fixture
    def git_repos(self, tmp_path):
        target_bare = tmp_path / "target_bare"
        clone1      = tmp_path / "clone1"
        clone2      = tmp_path / "clone2"
        upstream    = tmp_path / "upstream"

        def git(*args, cwd=None):
            subprocess.run(
                ["git", "-c", "user.email=t@t.com", "-c",
                 "user.name=T"] + list(args),
                cwd=cwd, check=True, capture_output=True,
            )

        # Bare target
        git("init", "--bare", "-b", "master", str(target_bare))
        # First working clone → push initial commit
        git("clone", str(target_bare), str(clone1))
        git("commit", "--allow-empty", "-m", "initial", cwd=str(clone1))
        git("push", "origin", "master", cwd=str(clone1))
        # Second clone — starts at the same initial commit
        git("clone", str(target_bare), str(clone2))
        # Upstream clone to inject new commits without going through the proxy
        git("clone", str(target_bare), str(upstream))

        return {"bare": target_bare, "clone1": clone1, "clone2": clone2,
                "upstream": upstream, "git": git}

    def test_fetch_pull_land_in_caller_clone(self, sock_path, git_repos, monkeypatch):
        repos = git_repos

        # In this test environment /usr/local/bin/git is a proxy wrapper that
        # intercepts fetch/pull and routes them to the system proxy socket.
        # The push proxy itself must use the real git binary so its subprocess
        # calls don't get re-intercepted.  Prepend the real git's directory to
        # PATH for the duration of this test.
        real_git_dir = "/usr/bin"
        current_path = os.environ.get("PATH", "")
        if real_git_dir not in current_path.split(":")[0]:
            monkeypatch.setenv("PATH", f"{real_git_dir}:{current_path}")

        # Add a new commit to target_bare via the upstream working clone
        repos["git"]("commit", "--allow-empty", "-m", "upstream-change",
                     cwd=str(repos["upstream"]))
        repos["git"]("push", "origin", "master", cwd=str(repos["upstream"]))

        # Start the proxy for clone2 — each workdir gets its own proxy, so
        # the request's workdir must match the proxy's own workdir.
        proxy = PushProxy(sock_path, str(repos["clone2"]), "pm/pr-test")
        proxy.start()

        try:
            def ref_sha(repo, ref):
                return subprocess.check_output(
                    ["git", "-C", str(repo), "rev-parse", ref]
                ).strip()

            pre_clone1 = ref_sha(repos["clone1"], "origin/master")
            pre_clone2 = ref_sha(repos["clone2"], "origin/master")
            assert pre_clone1 == pre_clone2, "both clones should start at the same stale commit"

            # Send a fetch request specifying clone2 as the caller workdir
            resp = _send_request(sock_path, {
                "cmd": "fetch",
                "args": ["origin"],
                "workdir": str(repos["clone2"]),
            })
            assert resp["exit_code"] == 0, f"fetch failed: {resp['stderr']}"

            # Assert that the fetch landed in clone2 and did NOT touch clone1
            clone2_log = subprocess.check_output(
                ["git", "-C", str(repos["clone2"]), "log", "--oneline",
                 "origin/master"]
            ).decode()
            assert "upstream-change" in clone2_log, "clone2 should have fetched upstream-change"

            clone1_log = subprocess.check_output(
                ["git", "-C", str(repos["clone1"]), "log", "--oneline",
                 "origin/master"]
            ).decode()
            assert "upstream-change" not in clone1_log, \
                "clone1 must not be updated — old bug: fetch ran from self.workdir"

            # Push a second upstream commit for pull test
            repos["git"]("commit", "--allow-empty", "-m", "upstream-change-2",
                         cwd=str(repos["upstream"]))
            repos["git"]("push", "origin", "master", cwd=str(repos["upstream"]))

            # Send a pull request specifying clone2 as the caller workdir
            resp = _send_request(sock_path, {
                "cmd": "pull",
                "args": ["origin", "master"],
                "workdir": str(repos["clone2"]),
            })
            assert resp["exit_code"] == 0, f"pull failed: {resp['stderr']}"

            # Assert that pull also landed in clone2 only
            clone2_log = subprocess.check_output(
                ["git", "-C", str(repos["clone2"]), "log", "--oneline",
                 "HEAD"]
            ).decode()
            assert "upstream-change-2" in clone2_log, "clone2 HEAD should include upstream-change-2"

            clone1_log = subprocess.check_output(
                ["git", "-C", str(repos["clone1"]), "log", "--oneline",
                 "HEAD"]
            ).decode()
            assert "upstream-change-2" not in clone1_log, \
                "clone1 HEAD must not change — old bug: pull ran from self.workdir"

        finally:
            proxy.stop()
