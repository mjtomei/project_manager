"""Late ownership changes must survive container cleanup."""

import contextlib
import json
import subprocess
from unittest.mock import Mock

import pytest

from pm_core import container as cm, container_reaper as reaper, push_proxy


@pytest.mark.parametrize("owner", ["replacement", "attaching", "unknown", "absent"])
def test_renamed_removal_preserves_original_names_proxy(monkeypatch, tmp_path, owner):
    original = "pm-qa-debug-original"
    directory = tmp_path / ("pm-push-proxy-" + original)
    directory.mkdir()
    socket = directory / "push.sock"
    socket.touch()  # replacement is already published BEFORE cleanup captures it
    inspected = [{"Config": {"Labels": {cm.LABEL_MANAGED: "1"}},
                  "Mounts": [{"Source": str(directory),
                              "Destination": push_proxy._CONTAINER_SOCKET_DIR}]}]
    removed = False

    def runtime(*args, **kwargs):
        nonlocal removed
        if args[0] == "ps":
            return subprocess.CompletedProcess(args, 0,
                "new-id\n" if owner == "replacement" else "", "")
        if args[0] == "inspect" and "{{json .Mounts}}" in args:
            return subprocess.CompletedProcess(args, 0,
                json.dumps(inspected[0]["Mounts"]), "")
        if args[0] == "rm":
            removed = True
            return subprocess.CompletedProcess(args, 0, "", "")
        if removed:
            return subprocess.CompletedProcess(args, 1, "", "no such container")
        return subprocess.CompletedProcess(args, 0, json.dumps(inspected), "")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    monkeypatch.setattr(cm, "current_container_id", lambda name:
                        None if owner == "unknown" else "new-id" if owner == "replacement" else "")
    monkeypatch.setattr(push_proxy, "stop_push_proxy", Mock())
    guard = cm.launch_lock(original) if owner == "attaching" else contextlib.nullcontext()
    with guard:
        if owner == "unknown":
            with pytest.raises(cm.ContainerError, match="proxy"):
                cm.remove_container("renamed")
        else:
            cm.remove_container("renamed")
    assert removed
    assert socket.exists() == (owner != "absent")


@pytest.mark.parametrize("include_retained", [False, True])
def test_pr_cleanup_rechecks_retention_after_inventory(monkeypatch, include_retained):
    name = "pm-tag-impl-pr-aaaa"
    info = reaper.ContainerInfo(name, "cid", True, session_tag="tag", pr_id="pr-aaaa", kind="impl")
    monkeypatch.setattr(reaper, "list_containers", lambda: [info])
    retained = False

    def current_id(_):
        nonlocal retained
        # Simulate retain_current completing after the initial candidate filter,
        # before the removal worker obtains its lock.
        retained = True
        return "cid"

    monkeypatch.setattr(cm, "current_container_id", current_id)
    monkeypatch.setattr(cm, "cleanup_generation", lambda name: "epoch")
    monkeypatch.setattr(reaper, "is_retained", lambda *args: retained)
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    result = cm.cleanup_pr_containers("pr-aaaa", "tag", include_retained=include_retained)
    assert result == ([name] if include_retained else [])
    assert remove.call_count == int(include_retained)
