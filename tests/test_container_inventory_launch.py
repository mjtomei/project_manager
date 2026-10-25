"""Label inventory and failed runtime-spawn cleanup regressions."""

import contextlib
import errno
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from pm_core import container as cm
from pm_core import container_reaper as reaper
from pm_core import push_proxy


def _result(stdout="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def test_inventory_includes_renamed_managed_proxy_user(monkeypatch):
    legacy = "pm-tag-review-pr-aaaa"
    renamed = "retained-discussion"
    labels = {cm.LABEL_MANAGED: "1", cm.LABEL_SESSION: "tag", cm.LABEL_PR: "pr-aaaa"}
    inspected = []

    def runtime(command, *args, **kwargs):
        if command == "ps":
            if f"label={cm.LABEL_MANAGED}=1" in args:
                return _result(f"{renamed}\n{legacy}\nnot-managed\n")
            return _result(f"{legacy}\nnpm-cache\n")
        assert command == "inspect"
        inspected.extend(args[2:])
        return _result("\n".join(
            f"/{name}\tid-{name}\ttrue\trunning\t{json.dumps(labels if name != 'not-managed' else {})}"
            for name in args[2:]))

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    infos = reaper.list_containers()
    assert {info.name for info in infos} == {legacy, renamed}
    assert len(inspected) == len(set(inspected))
    assert "npm-cache" not in inspected
    assert cm.containers_for_pr("tag", "pr-aaaa") == {legacy, renamed}
    monkeypatch.setattr(cm, "proxy_lock", lambda *args, **kwargs: contextlib.nullcontext(True))
    monkeypatch.setattr(push_proxy, "_owner_domain_matches", lambda *args: True)
    stop = Mock()
    monkeypatch.setattr(push_proxy, "_kill_proxy_socket", stop)
    assert push_proxy.release_proxy_if_unused("tag", "pr-aaaa", exclude={legacy}) is False
    stop.assert_not_called()


@pytest.mark.parametrize("failure", ["status", "timeout", "oserror"])
def test_label_inventory_failure_is_not_absence(monkeypatch, failure):
    inspect = Mock()

    def runtime(command, *args, **kwargs):
        assert command == "ps"
        if f"label={cm.LABEL_MANAGED}=1" in args:
            if failure == "timeout":
                raise subprocess.TimeoutExpired("podman ps", 30)
            if failure == "oserror":
                raise OSError("runtime unavailable")
            return _result(returncode=125)
        return _result()

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    monkeypatch.setattr(reaper, "_inspect", inspect)
    assert reaper.list_containers() is None
    inspect.assert_not_called()


@pytest.mark.parametrize("failure", ["oserror", "interrupt"])
def test_run_spawn_failure_discards_after_proxy_unlock(monkeypatch, tmp_path, failure):
    name = "pm-tag-review-pr-aaaa"
    held = False
    events = []

    @contextlib.contextmanager
    def proxy_lock(*args, **kwargs):
        nonlocal held
        held = True
        try:
            yield True
        finally:
            held = False
            events.append("unlock")

    def start(*args, **kwargs):
        assert held
        events.append("start-proxy")
        return str(tmp_path / "push.sock")

    def runtime(*args, **kwargs):
        assert held and args[0] == "run"
        events.append("run")
        if failure == "oserror":
            raise OSError(errno.EAGAIN, "Resource temporarily unavailable")
        raise KeyboardInterrupt()

    def discard(target):
        assert target == name
        assert not held
        events.append("discard")

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(cm, "remove_container", Mock())
    monkeypatch.setattr(cm, "discard_container", discard)
    monkeypatch.setattr(cm, "image_exists", lambda *args: True)
    monkeypatch.setattr(cm, "_get_runtime", lambda: "podman")
    monkeypatch.setattr(cm, "_nested_podman_enabled", lambda: False)
    monkeypatch.setattr(cm, "_resolve_claude_binary", lambda: None)
    monkeypatch.setattr(cm, "_relieve_keyring_pressure", lambda: None)
    monkeypatch.setattr(cm, "proxy_lock", proxy_lock)
    monkeypatch.setattr(cm, "_run_runtime", runtime)
    monkeypatch.setattr(cm.subprocess, "run", lambda *args, **kwargs: _result())
    monkeypatch.setattr(push_proxy, "start_push_proxy", start)
    expected = cm.ContainerLaunchError if failure == "oserror" else KeyboardInterrupt
    with pytest.raises(expected) as exc:
        cm._create_fresh(
            name, cm.ContainerConfig(), tmp_path,
            extra_ro_mounts=None, extra_rw_mounts=None, allowed_push_branch="topic",
            session_tag="tag", pr_id="pr-aaaa", labels={})
    if failure == "oserror":
        assert "Resource temporarily unavailable" in str(exc.value)
        assert "Errno 11" in str(exc.value)
    assert events == ["start-proxy", "run", "unlock", "discard"]
