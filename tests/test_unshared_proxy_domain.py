"""Legacy unshared mounts and cross-runtime proxy ownership."""

import json
import subprocess
import tempfile
from unittest.mock import Mock

import pytest

from pm_core import container as cm, container_reaper as reaper, push_proxy


@pytest.fixture
def proxy_fixture(monkeypatch, tmp_path):
    name = "pm-impl-pr-abcdef0"
    directory = tmp_path / ("pm-push-proxy-" + name)
    directory.mkdir()
    socket = directory / "push.sock"
    socket.touch()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(push_proxy, "_container_to_proxy_key", {})
    monkeypatch.setattr(push_proxy, "_active_proxies", {})
    monkeypatch.setattr(push_proxy, "unshared_proxy_in_use", lambda path: False)
    monkeypatch.setattr(push_proxy, "proxy_is_alive", lambda path: True)
    spawn = Mock()
    monkeypatch.setattr(push_proxy, "_start_proxy_subprocess", spawn)
    def runtime(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, json.dumps([{
            "Name": name, "Config": {"Labels": None},
            "Mounts": [{"Source": str(directory),
                        "Destination": push_proxy._CONTAINER_SOCKET_DIR}],
        }]), "")
    monkeypatch.setattr(cm, "_run_runtime", runtime)
    return name, directory, socket, spawn


@pytest.mark.parametrize("alive", [True, False])
def test_legacy_unlabeled_mount_can_be_reused(proxy_fixture, monkeypatch, alive):
    name, directory, socket, spawn = proxy_fixture
    monkeypatch.setattr(push_proxy, "proxy_is_alive", lambda path: alive)
    assert push_proxy.repair_unshared_proxy(name, "/work", "branch") == str(socket)
    assert spawn.call_count == int(not alive)


def test_new_unshared_proxy_records_runtime_domain(proxy_fixture):
    name, directory, socket, spawn = proxy_fixture
    push_proxy.start_push_proxy(name, "/work", "branch")
    owner = json.loads((directory / "owner.json").read_text())
    assert owner["runtime_domain"] == reaper._runtime_domain()


@pytest.mark.parametrize("operation", ["start", "repair", "captured-release", "stop", "local-stop"])
def test_foreign_unshared_proxy_is_preserved(proxy_fixture, monkeypatch, operation):
    name, directory, socket, spawn = proxy_fixture
    (directory / "owner.json").write_text(json.dumps({
        "runtime_domain": {"runtime": "test", "id": "other-store"},
        "container_name": name,
    }))
    before = socket.stat()
    if operation == "start":
        with pytest.raises(cm.ContainerError, match="runtime"):
            push_proxy.start_push_proxy(name, "/work", "branch")
    elif operation == "repair":
        with pytest.raises(cm.ContainerError, match="runtime"):
            push_proxy.repair_unshared_proxy(name, "/work", "branch")
    elif operation == "captured-release":
        captured = (name, str(socket), (before.st_dev, before.st_ino, before.st_ctime_ns), name)
        assert not push_proxy.release_captured_unshared_proxy(captured)
    else:
        if operation == "local-stop":
            monkeypatch.setattr(push_proxy, "_container_to_proxy_key", {name: name})
        push_proxy.stop_push_proxy(name)
    assert socket.exists()
    assert socket.stat().st_ino == before.st_ino
    spawn.assert_not_called()


def test_unknown_domain_preserves_container_before_removal(proxy_fixture, monkeypatch):
    name, directory, socket, spawn = proxy_fixture
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: None)
    runtime = Mock(wraps=cm._run_runtime)
    monkeypatch.setattr(cm, "_run_runtime", runtime)
    with pytest.raises(cm.ContainerError, match="runtime domain unknown"):
        cm.remove_container(name)
    assert not any(call.args[0] == "rm" for call in runtime.call_args_list)
    assert socket.exists()


def test_mounted_removal_forgets_local_bookkeeping(proxy_fixture, monkeypatch):
    name, directory, socket, spawn = proxy_fixture
    push_proxy._active_proxies[name] = str(socket)
    push_proxy._container_to_proxy_key[name] = name
    original_runtime = cm._run_runtime
    removed = False
    def runtime(*args, **kwargs):
        nonlocal removed
        if args[0] == "rm":
            removed = True
        if removed:
            return subprocess.CompletedProcess(args, 1, "", "no such container")
        return original_runtime(*args, **kwargs)
    monkeypatch.setattr(cm, "_run_runtime", runtime)
    assert cm.remove_container(name)
    assert name not in push_proxy._active_proxies
    assert name not in push_proxy._container_to_proxy_key


@pytest.mark.parametrize("name", ["other-container", "pm-tag-impl-pr-abcdef0"])
def test_legacy_non_pm_and_shared_mounts_are_not_unshared(proxy_fixture, monkeypatch, name):
    _, directory, _, _ = proxy_fixture
    monkeypatch.setattr(cm, "_run_runtime", lambda *args, **kwargs:
        subprocess.CompletedProcess(args, 0, json.dumps([{
            "Name": name, "Config": {"Labels": None},
            "Mounts": [{"Source": str(directory),
                        "Destination": push_proxy._CONTAINER_SOCKET_DIR}],
        }]), ""))
    assert push_proxy.mounted_unshared_proxy(name) is None


def test_forgetting_old_proxy_preserves_different_local_registration(proxy_fixture):
    name, _, socket, _ = proxy_fixture
    push_proxy._active_proxies[name] = "/another/push.sock"
    push_proxy._container_to_proxy_key[name] = name
    push_proxy.forget_unshared_proxy(name, str(socket))
    assert push_proxy._active_proxies[name] == "/another/push.sock"
    assert push_proxy._container_to_proxy_key[name] == name
