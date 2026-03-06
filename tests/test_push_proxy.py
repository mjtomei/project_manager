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
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["git", "push", "origin", "pm/pr-123-feature"]

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
        assert cmd == ["git", "push", "-u", "origin", "pm/pr-123-feature"]


class TestPushProxyProtocol:
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

    @patch("subprocess.run")
    def test_socket_is_world_writable(self, mock_run, sock_path):
        proxy = PushProxy(sock_path, "/w", "branch")
        proxy.start()
        try:
            mode = os.stat(sock_path).st_mode
            assert mode & 0o777 == 0o777
        finally:
            proxy.stop()
