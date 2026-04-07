"""Tests for the host-side git push proxy."""

import json
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pm_core.push_proxy import (
    PushProxy,
    start_push_proxy,
    stop_push_proxy,
    stop_all_proxies,
    stop_session_proxies,
    cleanup_stale_proxy_dirs,
    restart_dead_proxies,
    get_proxy_socket_path,
    container_socket_path,
    _CONTAINER_SOCKET_PATH,
    _SOCKET_DIR_PREFIX,
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
                     if c[0][0][0:2] == ["git", "push"]]
        assert len(push_call) == 1
        assert push_call[0][0][0] == ["git", "push", "origin", "pm/pr-123-feature"]

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
        assert cmd == ["git", "push", "-u", "origin", "pm/pr-123-feature"]


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
        assert container_socket_path() == "/run/pm-push-proxy/push.sock"

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


class TestSharedProxy:
    """Tests for (session_tag, pr_id) shared proxy behaviour."""

    def _mock_start(self):
        """Patch _start_proxy_subprocess to create a dummy socket file."""
        def fake_start(sock_path, workdir, branch):
            os.makedirs(os.path.dirname(sock_path), exist_ok=True)
            Path(sock_path).touch()
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
        """Shared proxy socket is at a deterministic path."""
        with self._mock_start():
            sock = start_push_proxy("c1", "/w", "pm/pr-1",
                                    session_tag="repo-abc", pr_id="pr-1")
            assert sock == "/tmp/pm-push-proxy-repo-abc-pr-1/push.sock"
            stop_push_proxy("c1")

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
    """The 'workdir' request field routes push/fetch/pull to the correct clone."""

    @pytest.fixture
    def proxy(self, sock_path):
        p = PushProxy(sock_path, "/proxy-default-workdir", "pm/pr-123-feature")
        p.start()
        yield p
        p.stop()

    @patch("subprocess.run")
    @patch("pm_core.push_proxy._resolve_local_remote_url",
           return_value="/some/pr-workdir")
    def test_local_push_uses_caller_workdir(self, _mock_resolve, mock_run,
                                            proxy, sock_path):
        """_local_push fetches FROM the caller's clone, not self.workdir."""
        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "-C"]:
                # The fetch step in _local_push
                return MagicMock(returncode=0, stdout="", stderr="")
            # resolve_real_origin follow-up (no real upstream)
            return MagicMock(returncode=1, stdout="", stderr="")
        mock_run.side_effect = side_effect

        resp = _send_request(sock_path, {
            "cmd": "push",
            "args": ["origin", "pm/pr-123-feature"],
            "workdir": "/caller-clone",
        })
        assert resp["exit_code"] == 0
        # Find the fetch call: git -C <target> fetch --update-head-ok <source> <refspec>
        fetch_calls = [c for c in mock_run.call_args_list
                       if c[0][0][:2] == ["git", "-C"]]
        assert len(fetch_calls) == 1
        fetch_cmd = fetch_calls[0][0][0]
        # Source must be the caller's clone, not the proxy default workdir
        assert "/caller-clone" in fetch_cmd
        assert "/proxy-default-workdir" not in fetch_cmd

    @patch("subprocess.run")
    def test_fetch_uses_caller_workdir(self, mock_run, proxy, sock_path):
        """git fetch runs from the caller's workdir, not self.workdir."""
        mock_run.return_value = MagicMock(returncode=0, stdout="fetched\n", stderr="")
        resp = _send_request(sock_path, {
            "cmd": "fetch",
            "args": ["origin"],
            "workdir": "/caller-clone",
        })
        assert resp["exit_code"] == 0
        fetch_call = mock_run.call_args
        assert fetch_call[1]["cwd"] == "/caller-clone"

    @patch("subprocess.run")
    def test_pull_uses_caller_workdir(self, mock_run, proxy, sock_path):
        """git pull runs from the caller's workdir, not self.workdir."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        resp = _send_request(sock_path, {
            "cmd": "pull",
            "args": ["origin"],
            "workdir": "/caller-clone",
        })
        assert resp["exit_code"] == 0
        assert mock_run.call_args[1]["cwd"] == "/caller-clone"

    @patch("subprocess.run")
    def test_no_workdir_field_falls_back_to_self_workdir(self, mock_run, proxy,
                                                          sock_path):
        """Legacy requests without 'workdir' fall back to self.workdir."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        resp = _send_request(sock_path, {
            "cmd": "fetch",
            "args": ["origin"],
            # no "workdir" key
        })
        assert resp["exit_code"] == 0
        assert mock_run.call_args[1]["cwd"] == "/proxy-default-workdir"

    @patch("subprocess.run")
    def test_empty_workdir_field_falls_back_to_self_workdir(self, mock_run, proxy,
                                                             sock_path):
        """An empty-string 'workdir' is treated the same as absent."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        resp = _send_request(sock_path, {
            "cmd": "pull",
            "args": [],
            "workdir": "",
        })
        assert resp["exit_code"] == 0
        assert mock_run.call_args[1]["cwd"] == "/proxy-default-workdir"

    @patch("subprocess.run")
    @patch("pm_core.push_proxy._resolve_local_remote_url",
           return_value="/some/pr-workdir")
    def test_no_workdir_push_falls_back_to_self_workdir(
            self, _mock_resolve, mock_run, proxy, sock_path):
        """Legacy push without 'workdir' falls back to self.workdir as source."""
        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "-C"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=1, stdout="", stderr="")
        mock_run.side_effect = side_effect

        resp = _send_request(sock_path, {
            "cmd": "push",
            "args": ["origin", "pm/pr-123-feature"],
            # no "workdir" key — legacy caller
        })
        assert resp["exit_code"] == 0
        fetch_calls = [c for c in mock_run.call_args_list
                       if c[0][0][:2] == ["git", "-C"]]
        assert len(fetch_calls) == 1
        fetch_cmd = fetch_calls[0][0][0]
        # Source must be self.workdir, not some caller path
        assert "/proxy-default-workdir" in fetch_cmd

    @patch("subprocess.run")
    @patch("pm_core.push_proxy._resolve_local_remote_url",
           return_value="/some/pr-workdir")
    def test_empty_workdir_push_falls_back_to_self_workdir(
            self, _mock_resolve, mock_run, proxy, sock_path):
        """An empty-string 'workdir' in a push request falls back to self.workdir."""
        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "-C"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=1, stdout="", stderr="")
        mock_run.side_effect = side_effect

        resp = _send_request(sock_path, {
            "cmd": "push",
            "args": ["origin", "pm/pr-123-feature"],
            "workdir": "",   # empty string — behaves like absent
        })
        assert resp["exit_code"] == 0
        fetch_calls = [c for c in mock_run.call_args_list
                       if c[0][0][:2] == ["git", "-C"]]
        assert len(fetch_calls) == 1
        fetch_cmd = fetch_calls[0][0][0]
        assert "/proxy-default-workdir" in fetch_cmd

    @patch("subprocess.run")
    def test_ls_remote_ignores_workdir(self, mock_run, proxy, sock_path):
        """ls-remote result is workdir-independent; caller workdir is accepted
        without error (proxy just uses it as cwd, which is harmless)."""
        mock_run.return_value = MagicMock(returncode=0, stdout="abc HEAD\n", stderr="")
        resp = _send_request(sock_path, {
            "cmd": "ls-remote",
            "args": ["origin"],
            "workdir": "/caller-clone",
        })
        assert resp["exit_code"] == 0
        assert resp["stdout"] == "abc HEAD\n"

    @patch("subprocess.run")
    def test_no_refspec_head_resolved_from_caller_workdir(self, mock_run, sock_path):
        """_extract_target_branch uses caller_workdir for HEAD resolution,
        not self.workdir, when no explicit refspec is given."""
        p = PushProxy(sock_path, "/proxy-workdir-main", "feature/x")
        p.start()

        def side_effect(cmd, **kwargs):
            cwd = kwargs.get("cwd", "")
            if "rev-parse" in cmd:
                if cwd == "/caller-workdir-feature-x":
                    return MagicMock(returncode=0, stdout="feature/x\n", stderr="")
                # self.workdir would resolve to "main"
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
            "workdir": "/caller-workdir-feature-x",
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
            c[1].get("cwd") == "/caller-workdir-feature-x"
            for c in rev_parse_calls
        ), "rev-parse must run in caller's workdir, not self.workdir"

        p.stop()


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

        # Start the proxy with clone1 as the proxy's default workdir
        proxy = PushProxy(sock_path, str(repos["clone1"]), "pm/pr-test")
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


class TestCleanupStaleProxyDirs:
    """Tests for cleanup_stale_proxy_dirs."""

    def test_removes_dir_with_dead_socket(self, tmp_path):
        """Dirs with no live socket should be removed."""
        sock_dir = tmp_path / f"{_SOCKET_DIR_PREFIX}repo-abc-pr-1"
        sock_dir.mkdir()
        sock_file = sock_dir / "push.sock"
        sock_file.touch()  # Regular file, not a real socket

        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            count = cleanup_stale_proxy_dirs("repo-abc")

        assert count == 1
        assert not sock_dir.exists()

    def test_removes_dir_with_no_socket(self, tmp_path):
        """Dirs with missing socket file should be removed."""
        sock_dir = tmp_path / f"{_SOCKET_DIR_PREFIX}repo-abc-pr-2"
        sock_dir.mkdir()

        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            count = cleanup_stale_proxy_dirs("repo-abc")

        assert count == 1
        assert not sock_dir.exists()

    def test_keeps_dir_with_live_socket(self, tmp_path):
        """Dirs with a live socket server should be kept."""
        sock_dir = tmp_path / f"{_SOCKET_DIR_PREFIX}repo-abc-pr-3"
        sock_dir.mkdir()
        sock_path = str(sock_dir / "push.sock")

        # Start a real socket server
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.listen(1)
        try:
            with patch("tempfile.gettempdir", return_value=str(tmp_path)):
                count = cleanup_stale_proxy_dirs("repo-abc")
            assert count == 0
            assert sock_dir.exists()
        finally:
            srv.close()

    def test_no_matching_dirs(self, tmp_path):
        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            count = cleanup_stale_proxy_dirs("repo-xyz")
        assert count == 0

    def test_cleans_up_via_kill_proxy_socket(self, tmp_path):
        """Delegates to _kill_proxy_socket so the dead proxy is counted."""
        sock_dir = tmp_path / f"{_SOCKET_DIR_PREFIX}repo-abc-pr-4"
        sock_dir.mkdir()
        (sock_dir / "push.sock").touch()

        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            count = cleanup_stale_proxy_dirs("repo-abc")

        assert count == 1
        assert not sock_dir.exists()

    def test_cleans_up_symlink_pointing_to_hashed_dir(self, tmp_path):
        """Long-name symlinks created by _shared_sock_dir are also cleaned."""
        # Simulate: real dir has hash name, symlink has long name
        real_dir = tmp_path / f"{_SOCKET_DIR_PREFIX}abcdef1234567890"
        real_dir.mkdir()
        (real_dir / "push.sock").touch()
        symlink = tmp_path / f"{_SOCKET_DIR_PREFIX}repo-abc-pr-5"
        symlink.symlink_to(real_dir)

        with patch("tempfile.gettempdir", return_value=str(tmp_path)):
            count = cleanup_stale_proxy_dirs("repo-abc")

        assert count == 1
        assert not symlink.exists()  # symlink removed
        assert not real_dir.exists()  # real dir also removed


class TestRestartDeadProxies:
    """Tests for restart_dead_proxies."""

    @patch("pm_core.container._run_docker")
    def test_no_containers_returns_zero(self, mock_docker):
        mock_docker.return_value = MagicMock(returncode=0, stdout="")
        assert restart_dead_proxies("pm-repo-abc", "repo-abc") == 0

    @patch("pm_core.container._run_docker")
    def test_docker_failure_returns_zero(self, mock_docker):
        mock_docker.return_value = MagicMock(returncode=1, stdout="")
        assert restart_dead_proxies("pm-repo-abc", "repo-abc") == 0

    @patch("pm_core.push_proxy.start_push_proxy")
    @patch("subprocess.run")
    @patch("pm_core.push_proxy.proxy_is_alive", return_value=False)
    @patch("pm_core.container._run_docker")
    def test_restarts_dead_proxy(self, mock_docker, mock_alive,
                                 mock_subproc, mock_start):
        # First call: list containers; second call: inspect mounts
        mock_docker.side_effect = [
            MagicMock(returncode=0, stdout="pm-repo-abc-impl-pr-1\n"),
            MagicMock(returncode=0, stdout=(
                "/tmp/pm-push-proxy-repo-abc-pr-1:/run/pm-push-proxy\n"
                "/home/user/project:/workspace\n"
            )),
        ]
        mock_subproc.return_value = MagicMock(
            returncode=0, stdout="pm/pr-1-feature\n",
        )
        mock_start.return_value = "/tmp/pm-push-proxy-repo-abc-pr-1/push.sock"

        count = restart_dead_proxies("pm-repo-abc", "repo-abc")
        assert count == 1
        mock_start.assert_called_once_with(
            "pm-repo-abc-impl-pr-1", "/home/user/project",
            "pm/pr-1-feature",
            session_tag="repo-abc", pr_id="pr-1",
        )

    @patch("pm_core.push_proxy.start_push_proxy")
    @patch("pm_core.push_proxy.proxy_is_alive", return_value=True)
    @patch("pm_core.container._run_docker")
    def test_skips_alive_proxy(self, mock_docker, mock_alive, mock_start):
        mock_docker.side_effect = [
            MagicMock(returncode=0, stdout="pm-repo-abc-impl-pr-1\n"),
            MagicMock(returncode=0, stdout=(
                "/tmp/pm-push-proxy-repo-abc-pr-1:/run/pm-push-proxy\n"
                "/home/user/project:/workspace\n"
            )),
        ]
        count = restart_dead_proxies("pm-repo-abc", "repo-abc")
        assert count == 0
        mock_start.assert_not_called()

    @patch("pm_core.push_proxy.start_push_proxy")
    @patch("pm_core.container._run_docker")
    def test_skips_container_without_proxy_mount(self, mock_docker, mock_start):
        mock_docker.side_effect = [
            MagicMock(returncode=0, stdout="pm-repo-abc-impl-pr-1\n"),
            MagicMock(returncode=0, stdout="/home/user/project:/workspace\n"),
        ]
        count = restart_dead_proxies("pm-repo-abc", "repo-abc")
        assert count == 0
        mock_start.assert_not_called()

    @patch("pm_core.push_proxy.start_push_proxy")
    @patch("subprocess.run")
    @patch("pm_core.push_proxy.proxy_is_alive", return_value=False)
    @patch("pm_core.container._run_docker")
    def test_skips_when_git_branch_fails(self, mock_docker, mock_alive,
                                         mock_subproc, mock_start):
        mock_docker.side_effect = [
            MagicMock(returncode=0, stdout="pm-repo-abc-impl-pr-1\n"),
            MagicMock(returncode=0, stdout=(
                "/tmp/pm-push-proxy-repo-abc-pr-1:/run/pm-push-proxy\n"
                "/home/user/project:/workspace\n"
            )),
        ]
        mock_subproc.return_value = MagicMock(returncode=1, stdout="")
        count = restart_dead_proxies("pm-repo-abc", "repo-abc")
        assert count == 0
        mock_start.assert_not_called()

    @patch("pm_core.push_proxy.start_push_proxy")
    @patch("subprocess.run")
    @patch("pm_core.push_proxy.proxy_is_alive", return_value=False)
    @patch("pm_core.container._run_docker")
    def test_extracts_qa_pr_id(self, mock_docker, mock_alive,
                               mock_subproc, mock_start):
        mock_docker.side_effect = [
            MagicMock(returncode=0,
                      stdout="pm-repo-abc-qa-pr-1234567-loop1-s2\n"),
            MagicMock(returncode=0, stdout=(
                "/tmp/pm-push-proxy-repo-abc-pr-1234567:/run/pm-push-proxy\n"
                "/home/user/clone:/workspace\n"
            )),
        ]
        mock_subproc.return_value = MagicMock(
            returncode=0, stdout="pm/pr-1-branch\n",
        )
        mock_start.return_value = "/tmp/sock"

        count = restart_dead_proxies("pm-repo-abc", "repo-abc")
        assert count == 1
        # pr_id should be extracted as "pr-1234567"
        mock_start.assert_called_once()
        call_kwargs = mock_start.call_args
        assert call_kwargs[1]["pr_id"] == "pr-1234567"
