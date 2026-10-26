"""Unshared proxy ownership follows mounted sockets, including cleanup retries."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from pm_core import container as cm, container_reaper as reaper, push_proxy


@pytest.fixture(autouse=True)
def _no_other_mounted_users(monkeypatch):
    monkeypatch.setattr(push_proxy, "unshared_proxy_in_use", lambda path: False)


def _inspection(name, directory):
    return json.dumps([{"Name": name, "Config": {"Labels": {cm.LABEL_MANAGED: "1"}},
                        "Mounts": [{"Source": str(directory),
                                    "Destination": push_proxy._CONTAINER_SOCKET_DIR}]}])


def test_renamed_removal_does_not_release_unrelated_name_proxy(monkeypatch, tmp_path):
    original, renamed = "pm-qa-debug-first", "pm-qa-debug-second"
    directory = tmp_path / ("pm-push-proxy-" + original)
    directory.mkdir()
    socket = directory / "push.sock"
    socket.touch()
    gone = False

    def runtime(*args, **kwargs):
        nonlocal gone
        if args[0] == "rm":
            gone = True
        return subprocess.CompletedProcess(args, int(gone),
            "" if gone else _inspection(renamed, directory),
            "no such container" if gone else "")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    monkeypatch.setattr(cm, "current_container_id", lambda _: "")
    fallback = Mock()
    monkeypatch.setattr(push_proxy, "stop_push_proxy", fallback)
    cm.remove_container(renamed)
    assert not socket.exists()
    fallback.assert_not_called()


def test_renamed_reuse_repairs_actual_mounted_socket(monkeypatch, tmp_path):
    original, renamed = "pm-qa-debug-first", "pm-qa-debug-second"
    directory = tmp_path / ("pm-push-proxy-" + original)
    directory.mkdir()
    socket = directory / "push.sock"  # dead/missing proxy, mount still exists
    monkeypatch.setattr(cm, "container_is_running", lambda _: True)
    monkeypatch.setattr(cm, "current_container_id", lambda name: "cid" if name == renamed else "")
    monkeypatch.setattr(cm, "_probe_setup", lambda _: (True, "", ""))
    monkeypatch.setattr(reaper, "is_retained", lambda *args: False)
    monkeypatch.setattr(cm, "_run_runtime", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, 0, _inspection(renamed, directory), ""))
    started = []
    monkeypatch.setattr(push_proxy, "_start_proxy_subprocess",
                        lambda path, *args: started.append(path))
    monkeypatch.setattr(push_proxy, "proxy_is_alive", lambda path: path in started)
    assert cm._ensure_reusable(renamed, tmp_path, "branch", session_tag=None, pr_id=None) == "cid"
    assert started == [str(socket)]


@pytest.mark.parametrize("blocked", ["unlink", "lock"])
def test_post_removal_unshared_cleanup_is_retried(monkeypatch, tmp_path, blocked):
    original, renamed = "pm-qa-debug-first", "pm-qa-debug-second"
    directory = tmp_path / ("pm-push-proxy-" + original)
    directory.mkdir()
    socket = directory / "push.sock"
    socket.touch()
    gone = False

    def runtime(*args, **kwargs):
        nonlocal gone
        if args[0] == "rm":
            gone = True
        return subprocess.CompletedProcess(args, int(gone),
            "" if gone else _inspection(renamed, directory),
            "no such container" if gone else "")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    monkeypatch.setattr(cm, "current_container_id", lambda _: "")
    monkeypatch.setattr(push_proxy, "stop_push_proxy", Mock())
    monkeypatch.setattr(push_proxy, "runtime_domain", reaper._runtime_domain)
    monkeypatch.setattr(push_proxy, "list_shared_proxies", lambda: [])
    real_unlink = push_proxy.os.unlink
    if blocked == "unlink":
        def denied(path, *args, **kwargs):
            if str(path) == str(socket):
                raise PermissionError("injected socket unlink failure")
            return real_unlink(path, *args, **kwargs)
        monkeypatch.setattr(push_proxy.os, "unlink", denied)
        with pytest.raises(PermissionError):
            cm.remove_container(renamed)
        monkeypatch.setattr(push_proxy.os, "unlink", real_unlink)
    else:
        with cm.launch_lock(original):
            cm.remove_container(renamed)
    assert gone and socket.exists()
    failures = {}
    reaper._release_unused_proxies(reaper.Scope(), failures)
    assert not failures
    assert not socket.exists()


def test_live_renamed_mount_keeps_original_socket(monkeypatch, tmp_path):
    socket = tmp_path / "push.sock"
    socket.touch()
    stat = socket.stat()
    captured = ("pm-original", str(socket),
                (stat.st_dev, stat.st_ino, stat.st_ctime_ns), "pm-original")
    monkeypatch.setattr(push_proxy, "unshared_proxy_in_use", lambda path: True)
    assert not push_proxy.release_captured_unshared_proxy(captured)
    assert socket.exists()


@pytest.mark.parametrize("mode", ["used", "empty", "unavailable", "partial"])
def test_mount_user_inventory_is_complete(monkeypatch, tmp_path, mode):
    # Exercise the actual inventory helper, not the test module's default stub.
    # The original function is saved below, before the autouse monkeypatch runs.
    def runtime(*args, **kwargs):
        if args[0] == "ps":
            return subprocess.CompletedProcess(args, int(mode == "unavailable"), "cid\n", "")
        mounts = [{"Source": str(tmp_path)}] if mode == "used" else []
        return subprocess.CompletedProcess(args, 0,
            "" if mode == "partial" else json.dumps(mounts), "")
    monkeypatch.setattr(cm, "_run_runtime", runtime)
    if mode in ("partial", "unavailable"):
        with pytest.raises(cm.ContainerError):
            _real_mount_inventory(str(tmp_path / "push.sock"))
    else:
        assert _real_mount_inventory(str(tmp_path / "push.sock")) == (mode == "used")


@pytest.mark.parametrize("local", [False, True])
def test_name_fallback_preserves_live_mount(monkeypatch, tmp_path, local):
    import tempfile
    name = "pm-qa-debug-original"
    directory = tmp_path / ("pm-push-proxy-" + name)
    directory.mkdir()
    socket = directory / "push.sock"
    socket.touch()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(push_proxy, "_container_to_proxy_key", {name: name} if local else {})
    monkeypatch.setattr(push_proxy, "_active_proxies", {})
    monkeypatch.setattr(push_proxy, "unshared_proxy_in_use", lambda path: True)
    push_proxy.stop_push_proxy(name)
    assert socket.exists()
    with pytest.raises(cm.ContainerError, match="still mounted"):
        push_proxy.start_push_proxy(name, str(tmp_path), "new-branch")
    assert socket.exists()


@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("socket_state", ["missing", "disappeared", "replaced"])
def test_missing_socket_cleanup_retires_owner(monkeypatch, tmp_path, retry, socket_state):
    name = "pm-qa-debug-original"
    directory = tmp_path / ("pm-push-proxy-" + name)
    directory.mkdir()
    owner = directory / "owner.json"
    owner.write_text(json.dumps({"runtime_domain": reaper._runtime_domain()}))
    socket = directory / "push.sock"
    identity = (0, 0, 0)
    if socket_state == "disappeared":
        socket.touch()
        stat = socket.stat()
        identity = (stat.st_dev, stat.st_ino, stat.st_ctime_ns)
        socket.unlink()
    elif socket_state == "replaced":
        socket.touch()  # new socket must not match the captured absence
    proxy = (name, str(socket), identity, name)
    monkeypatch.setattr(cm, "current_container_id", lambda _: "")
    if retry:
        record = push_proxy.defer_unshared_release(proxy)
        failures = {}
        push_proxy.retry_unshared_releases(reaper.Scope(), failures)
        assert not failures
        assert not record.exists()
    else:
        assert push_proxy.release_captured_unshared_proxy(proxy)
    assert owner.exists() == (socket_state == "replaced")
    assert socket.exists() == (socket_state == "replaced")


_real_mount_inventory = push_proxy.unshared_proxy_in_use
