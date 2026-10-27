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


def test_setup_probe_oserror_is_a_launch_error(monkeypatch):
    """A vanished runtime executable must not escape as a raw OSError."""
    def runtime(*args, **kwargs):
        raise FileNotFoundError("podman")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm._probe_setup("captured-id")
    assert error.value.kind == "runtime"
    assert "podman" in str(error.value)


@pytest.mark.parametrize("complete", [False, True])
def test_completion_probe_without_runtime_error_remains_boolean(monkeypatch, complete):
    monkeypatch.setattr(cm, "_probe_setup", lambda target: (complete, "", ""))
    assert cm._setup_complete("existing-allocation") is complete


def test_running_state_probe_timeout_is_a_retryable_launch_error(monkeypatch, tmp_path):
    """An unanswered running-state probe must not be read as "stopped"."""
    name, cid = "pm-tag-review-pr-aaaa", "existing-allocation"
    monkeypatch.setattr(cm, "current_container_id", lambda target: cid)

    def running(target):
        raise subprocess.TimeoutExpired(["podman", "inspect"], 10)

    monkeypatch.setattr(cm, "container_is_running", running)
    monkeypatch.setattr(reaper, "is_retained", lambda *a: False)
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm._ensure_reusable(name, tmp_path, None, session_tag=None, pr_id=None)
    assert error.value.kind == "timeout"
    assert name in str(error.value)
    assert "running-state probe" in str(error.value)
    remove.assert_not_called()


def test_running_state_error_names_the_container_not_its_id(monkeypatch, tmp_path):
    """A classified running-state failure must name the container to act on."""
    name, cid = "pm-tag-review-pr-aaaa", "e3b0c44298fc1c149afbf4c8996fb924"
    monkeypatch.setattr(cm, "current_container_id", lambda target: cid)

    def running(target):
        raise cm.launch_error(target, "runtime", "runtime returned an unknown running state",
                              stage="inspect existing container")

    monkeypatch.setattr(cm, "container_is_running", running)
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm._ensure_reusable(name, tmp_path, None, session_tag=None, pr_id=None)
    message = str(error.value)
    assert name in message
    assert cid not in message
    assert error.value.kind == "runtime"
    remove.assert_not_called()


def test_in_place_setup_error_names_the_container_not_its_id(monkeypatch, tmp_path):
    """Post-setup addresses the id; the launch error must name the container."""
    name, cid = "pm-tag-review-pr-aaaa", "e3b0c44298fc1c149afbf4c8996fb924"
    monkeypatch.setattr(cm, "current_container_id", lambda target: cid)
    monkeypatch.setattr(cm, "container_is_running", lambda target: True)
    monkeypatch.setattr(cm, "_probe_setup", lambda target: (False, "", ""))
    monkeypatch.setattr(reaper, "is_retained", lambda *a: False)
    monkeypatch.setattr(cm, "_run_runtime", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, "", ""))
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)

    def post(target, workdir, is_podman):
        raise cm.launch_error(target, "config", "copying ~/.claude.json failed",
                              stage="receive ~/.claude.json")

    monkeypatch.setattr(cm, "_post_setup", post)
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm._ensure_reusable(name, tmp_path, None, session_tag=None, pr_id=None)
    message = str(error.value)
    assert error.value.kind == "config"
    assert name in message
    assert cid not in message
    assert "copying ~/.claude.json failed" in message
    remove.assert_not_called()


def test_readiness_probe_timeout_is_a_retryable_launch_error(monkeypatch, tmp_path):
    """An unanswered readiness probe is unknown, not proof setup never ran."""
    name, cid = "pm-tag-review-pr-aaaa", "existing-allocation"
    monkeypatch.setattr(cm, "current_container_id", lambda target: cid)
    monkeypatch.setattr(cm, "container_is_running", lambda target: True)
    monkeypatch.setattr(cm, "_probe_setup", lambda target: (False, "", ""))
    monkeypatch.setattr(reaper, "is_retained", lambda *a: False)

    def runtime(*args, **kwargs):
        raise subprocess.TimeoutExpired(["podman", *args], kwargs.get("timeout"))

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    remove, post = Mock(), Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    monkeypatch.setattr(cm, "_post_setup", post)
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm._ensure_reusable(name, tmp_path, None, session_tag=None, pr_id=None)
    assert error.value.kind == "timeout"
    assert name in str(error.value)
    assert "readiness probe" in str(error.value)
    remove.assert_not_called()
    post.assert_not_called()


def test_reuse_probe_timeout_names_the_container_not_its_id(monkeypatch, tmp_path):
    """The i1 probe-timeout error must name the container a user can act on."""
    name, cid = "pm-tag-review-pr-aaaa", "e3b0c44298fc1c149afbf4c8996fb924"
    monkeypatch.setattr(cm, "current_container_id", lambda target: cid)
    monkeypatch.setattr(cm, "container_is_running", lambda target: True)
    monkeypatch.setattr(reaper, "is_retained", lambda *a: False)

    def probe(target):
        raise cm.launch_error(target, "timeout", "probe did not return",
                              stage="verify existing setup")

    monkeypatch.setattr(cm, "_probe_setup", probe)
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm._ensure_reusable(name, tmp_path, None, session_tag=None, pr_id=None)
    message = str(error.value)
    assert name in message
    assert cid not in message
    assert error.value.kind == "timeout"


def test_completion_sentinel_timeout_is_a_retryable_launch_error(monkeypatch, tmp_path):
    """A slow `touch` of the completion sentinel is a classified launch error."""
    name, cid = "pm-tag-review-pr-aaaa", "existing-allocation"
    monkeypatch.setattr(cm, "_host_claude_json", lambda: tmp_path / "absent-config")

    def runtime(*args, **kwargs):
        if args[0] == "exec" and args[-1] == cm.SETUP_COMPLETE_SENTINEL:
            raise subprocess.TimeoutExpired(["podman", *args], kwargs.get("timeout"))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm._post_setup(cid, tmp_path, True)
    assert error.value.kind == "timeout"
    assert "record completed setup" in str(error.value)
