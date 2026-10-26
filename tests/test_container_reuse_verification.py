"""Failed verification after in-place setup must preserve existing files."""

import subprocess
from unittest.mock import Mock

import pytest

from pm_core import container as cm, container_reaper as reaper


@pytest.mark.parametrize("kind,stderr", [
    ("pids", "cannot fork"),
    ("memory", "cannot allocate memory"),
    ("keyring", "unable to join session keyring: disk quota exceeded"),
    ("incomplete", ""),
])
def test_failed_post_setup_verification_preserves_reused_allocation(
        monkeypatch, tmp_path, kind, stderr):
    name, cid = "pm-tag-review-pr-aaaa", "existing-allocation"
    monkeypatch.setattr(cm, "recent_launch", lambda *a: False)
    monkeypatch.setattr(cm, "current_container_id", lambda target: cid)
    monkeypatch.setattr(cm, "container_is_running", lambda target: True)
    monkeypatch.setattr(cm, "_host_claude_json", lambda: tmp_path / "absent-config")
    monkeypatch.setattr(cm, "running_container_count", lambda: 1)
    monkeypatch.setattr(reaper, "is_retained", lambda *a: False)
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    post = Mock()
    remove, fresh = Mock(), Mock(return_value="replacement")
    monkeypatch.setattr(cm, "_post_setup", post)
    monkeypatch.setattr(cm, "remove_container", remove)
    monkeypatch.setattr(cm, "_create_fresh", fresh)
    monkeypatch.setattr(cm, "_renew_launch", Mock())
    probes = 0

    def runtime(*args, **kwargs):
        nonlocal probes
        assert args[:2] == ("exec", cid)
        if args[2:4] == ("test", "-f"):
            return subprocess.CompletedProcess(args, 0, "", "")
        probes += 1
        return subprocess.CompletedProcess(args, 1, "", stderr if probes == 2 else "")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm.create_container(name, cm.ContainerConfig(), tmp_path)
    assert error.value.kind == kind
    if stderr:
        assert stderr in str(error.value)
    post.assert_called_once_with(cid, tmp_path, "podman" in cm._get_runtime())
    remove.assert_not_called()
    fresh.assert_not_called()


@pytest.mark.parametrize("kind,stderr", [
    ("pids", "cannot fork"),
    ("memory", "cannot allocate memory"),
    ("keyring", "unable to join session keyring: disk quota exceeded"),
])
def test_restart_completion_probe_preserves_runtime_cause(monkeypatch, kind, stderr):
    cid = "existing-allocation"
    monkeypatch.setattr(cm, "current_container_id", lambda target: cid)
    monkeypatch.setattr(cm, "_wait_for_setup", Mock())
    monkeypatch.setattr(cm, "_probe_setup", lambda target: (False, kind, stderr))
    calls = []

    def runtime(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, '"2026-10-26T00:00:00Z"', "")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm.restart_container("pm-tag-review-pr-aaaa")
    assert error.value.kind == kind
    assert stderr in str(error.value)
    assert not any(args[0] == "rm" for args in calls)


@pytest.mark.parametrize("kind,stderr", [
    ("pids", "cannot fork"),
    ("memory", "cannot allocate memory"),
    ("keyring", "unable to join session keyring: disk quota exceeded"),
    ("runtime", "runtime connection lost"),
])
def test_incomplete_readiness_probe_preserves_runtime_cause(
        monkeypatch, tmp_path, kind, stderr):
    name, cid = "pm-tag-review-pr-aaaa", "existing-allocation"
    monkeypatch.setattr(cm, "current_container_id", lambda target: cid)
    monkeypatch.setattr(cm, "container_is_running", lambda target: True)
    monkeypatch.setattr(cm, "_probe_setup", lambda target: (False, "", ""))
    monkeypatch.setattr(cm, "running_container_count", lambda: 1)
    monkeypatch.setattr(reaper, "is_retained", lambda *a: False)
    remove, restart, post = Mock(), Mock(), Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    monkeypatch.setattr(cm, "restart_container", restart)
    monkeypatch.setattr(cm, "_post_setup", post)

    def runtime(*args, **kwargs):
        assert args == ("exec", cid, "test", "-f", cm._READY_SENTINEL)
        return subprocess.CompletedProcess(args, 125, "", stderr)

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm._ensure_reusable(name, tmp_path, None, session_tag=None, pr_id=None)
    assert error.value.kind == kind
    assert stderr in str(error.value)
    if kind == "pids":
        assert "pm container restart" in str(error.value)
    elif kind in ("memory", "keyring"):
        assert "pm container reap" in str(error.value)
    remove.assert_not_called()
    restart.assert_not_called()
    post.assert_not_called()


@pytest.mark.parametrize("complete", [False, True])
def test_completion_probe_without_runtime_error_remains_boolean(monkeypatch, complete):
    monkeypatch.setattr(cm, "_probe_setup", lambda target: (complete, "", ""))
    assert cm._setup_complete("existing-allocation") is complete
