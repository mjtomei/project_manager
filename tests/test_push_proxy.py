"""Tests for the host-side git push proxy."""

import json
import os
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pm_core.push_proxy import (
    PushProxy,
    start_push_proxy,
    stop_push_proxy,
    stop_all_proxies,
    get_proxy_socket_path,
    container_socket_path,
    _CONTAINER_SOCKET_PATH,
)


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
        # First call: _resolve_local_remote_url checks origin URL
        # Second call: the actual git push
        push_call = [c for c in mock_run.call_args_list
                     if "push" in c[0][0]]
        assert len(push_call) == 1
        assert push_call[0][0][0] == ["git", "-C", "/tmp/fake-workdir", "push", "origin", "pm/pr-123-feature"]

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
        cmd = mock_run.call_args[0][0]
        assert cmd == ["git", "-C", "/tmp/fake-workdir", "push", "-u", "origin", "pm/pr-123-feature"]


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

    def test_invalid_json(self, proxy, sock_path):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(sock_path)
        s.sendall(b"not json\n")
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        resp = json.loads(data.decode())
        assert resp["exit_code"] == 1
        assert "invalid" in resp["stderr"]

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

    def test_container_socket_path(self):
        assert container_socket_path() == _CONTAINER_SOCKET_PATH
        assert container_socket_path() == "/run/pm-push-proxy.sock"

    def test_get_proxy_socket_path(self):
        with patch("pm_core.push_proxy.PushProxy.start"), \
             patch("pm_core.push_proxy.PushProxy.stop"):
            sock = start_push_proxy("lookup-test", "/w", "pm/pr-123")
            assert get_proxy_socket_path("lookup-test") == sock
            stop_push_proxy("lookup-test")
            assert get_proxy_socket_path("lookup-test") is None

    def test_get_proxy_socket_path_nonexistent(self):
        assert get_proxy_socket_path("no-such-container") is None

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
