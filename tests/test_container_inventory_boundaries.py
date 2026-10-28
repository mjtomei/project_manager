"""Inventory identity must survive runtime failures and container renames."""

import json
import subprocess
from unittest.mock import Mock

import pytest

from pm_core import container as cm, container_reaper as reaper, push_proxy


@pytest.mark.parametrize("rc,stdout,stderr,expected", [
    (125, "", "dial unix /run/podman.sock: no such file or directory", None),
    (0, "", "", None),
    (1, "", "Error: No such container: old", ""),
    (1, "", 'Error: no container with name or ID "old" found', ""),
    (0, "cid\n", "", "cid"),
])
def test_identity_requires_explicit_absence(monkeypatch, rc, stdout, stderr, expected):
    monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw:
                        subprocess.CompletedProcess(a, rc, stdout, stderr))
    assert cm.current_container_id("old") == expected


def test_renamed_managed_inventory_counts_and_scopes_cleanup(monkeypatch):
    infos = [reaper.ContainerInfo("renamed", "cid", True, session_tag="tag", pr_id="pr-aaaa", kind="qa"),
             reaper.ContainerInfo("other", "other-id", True, session_tag="other", pr_id="pr-aaaa", kind="qa"),
             reaper.ContainerInfo("stopped", "stopped-id", False, session_tag="tag", pr_id="pr-aaaa", kind="impl")]
    monkeypatch.setattr(reaper, "list_containers", lambda: infos)
    remove = Mock(return_value=(["renamed", "stopped"], {}))
    monkeypatch.setattr(cm, "remove_containers", remove)
    assert cm.running_container_count() == 2
    assert cm.cleanup_pr_containers("pr-aaaa", "tag") == ["renamed", "stopped"]
    remove.assert_called_once_with(["renamed", "stopped"], workers=8, include_retained=True)


@pytest.mark.parametrize("renamed", [False, True])
def test_renamed_unshared_proxy_is_released_after_container_removal(monkeypatch, tmp_path, renamed):
    directory = tmp_path / "pm-push-proxy-pm-qa-debug-original"
    directory.mkdir()
    socket = directory / "push.sock"
    socket.touch()
    inspected = [{"Config": {"Labels": {cm.LABEL_MANAGED: "1"}},
                  "Mounts": [{"Source": str(directory), "Destination": push_proxy._CONTAINER_SOCKET_DIR}]}]
    removed = False

    def runtime(*args, **kw):
        nonlocal removed
        if args[0] == "ps":
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "rm":
            removed = True
            return subprocess.CompletedProcess(args, 0, "", "")
        if removed:
            return subprocess.CompletedProcess(args, 1, "", "no such container")
        return subprocess.CompletedProcess(args, 0, json.dumps(inspected), "")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    monkeypatch.setattr(push_proxy, "stop_push_proxy", lambda name: None)
    cm.remove_container("renamed" if renamed else "pm-qa-debug-original")
    assert removed
    assert not socket.exists()


def test_old_proxy_capture_preserves_replacement(monkeypatch, tmp_path):
    socket = tmp_path / "push.sock"
    socket.touch()
    stat = socket.stat()
    identity = (stat.st_dev, stat.st_ino, stat.st_ctime_ns)
    socket.unlink()
    socket.touch()
    push_proxy._kill_proxy_socket(str(socket), expected_identity=identity)
    assert socket.exists()
