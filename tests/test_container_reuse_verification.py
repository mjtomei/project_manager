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


def test_unreadable_attachment_lease_is_a_launch_error(monkeypatch, tmp_path):
    """An unknown lease/generation is not absence; it must name the container."""
    name = "pm-tag-impl-pr-aaaa"

    def unreadable(*args, **kwargs):
        raise OSError("Cannot determine allocation identity for attachment lease")

    monkeypatch.setattr(cm, "recent_launch", unreadable)
    monkeypatch.setattr(cm, "_ensure_reusable", Mock(side_effect=AssertionError("no reuse")))
    monkeypatch.setattr(cm, "_create_fresh", Mock(side_effect=AssertionError("no create")))
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm.create_container(name, cm.ContainerConfig(), tmp_path)
    assert error.value.kind == "runtime"
    assert name in str(error.value)
    assert "attachment lease" in str(error.value)


def test_unclassified_fresh_create_failure_names_the_container(monkeypatch, tmp_path):
    """An auto-build/git failure must not escape as an unrelated traceback."""
    name = "pm-tag-impl-pr-aaaa"
    monkeypatch.setattr(cm, "recent_launch", lambda *a: False)
    monkeypatch.setattr(cm, "_ensure_reusable", lambda *a, **kw: None)
    monkeypatch.setattr(cm, "_create_fresh",
                        Mock(side_effect=RuntimeError("Image build failed: boom")))
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm.create_container(name, cm.ContainerConfig(), tmp_path)
    assert error.value.kind == "runtime"
    assert name in str(error.value)
    assert "Image build failed" in str(error.value)


def test_remove_container_rm_timeout_is_a_container_error(monkeypatch, tmp_path):
    """A hung `rm` must not bypass the callers' ContainerError retry path."""
    from pm_core import push_proxy

    def runtime(*args, **kwargs):
        if args[0] == "rm":
            raise subprocess.TimeoutExpired(["podman", "rm"], 30)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    monkeypatch.setattr(push_proxy, "capture_unshared_proxy", lambda target: None)
    monkeypatch.setattr(push_proxy, "stop_push_proxy", lambda name: None)
    with pytest.raises(cm.ContainerError) as error:
        cm.remove_container("pm-tag-impl-pr-aaaa")
    assert "pm-tag-impl-pr-aaaa" in str(error.value)
    assert "timed out" in str(error.value)


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


def test_restart_finishes_missing_host_setup_in_place(monkeypatch, tmp_path):
    """A restarted container without the completion marker is still recovered.

    Every container created before that marker existed lacks it. The restart
    clears the pressure and keeps the filesystem, so the launch must finish
    the idempotent post-setup instead of reporting a failed recovery.
    """
    name, cid = "pm-tag-review-pr-cccc", "legacy-allocation"
    monkeypatch.setattr(cm, "recent_launch", lambda *a: False)
    monkeypatch.setattr(cm, "current_container_id", lambda target: cid)
    monkeypatch.setattr(cm, "container_is_running", lambda target: True)
    monkeypatch.setattr(cm, "_host_claude_json", lambda: tmp_path / "absent-config")
    monkeypatch.setattr(cm, "running_container_count", lambda: 1)
    monkeypatch.setattr(reaper, "is_retained", lambda *a: False)
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    monkeypatch.setattr(cm, "_renew_launch", Mock())

    def restart(target, *, container_id=None):
        raise cm.launch_error(name, "incomplete", "setup markers missing after restart",
                              stage="restart")
    monkeypatch.setattr(cm, "restart_container", restart)

    completed = {"done": False}
    probes = {"setup": 0}

    def runtime(*args, **kwargs):
        assert args[:2] == ("exec", cid)
        if args[2:4] == ("test", "-f"):  # readiness marker after the restart
            return subprocess.CompletedProcess(args, 0, "", "")
        probes["setup"] += 1
        if probes["setup"] == 1:  # wedged: cannot exec at all
            return subprocess.CompletedProcess(args, 125, "", "cannot fork")
        return subprocess.CompletedProcess(args, 0 if completed["done"] else 1, "", "")
    monkeypatch.setattr(cm, "_run_runtime", runtime)

    post = Mock(side_effect=lambda *a: completed.update(done=True))
    monkeypatch.setattr(cm, "_post_setup", post)
    remove, fresh = Mock(), Mock(return_value="replacement")
    monkeypatch.setattr(cm, "remove_container", remove)
    monkeypatch.setattr(cm, "_create_fresh", fresh)

    assert cm.create_container(name, cm.ContainerConfig(), tmp_path) == cid
    post.assert_called_once_with(cid, tmp_path, "podman" in cm._get_runtime())
    remove.assert_not_called()
    fresh.assert_not_called()


def test_proxy_probe_timeout_names_the_container(monkeypatch, tmp_path):
    """An unanswered proxy inspect must be a classified error naming the container."""
    from pm_core import push_proxy
    name, cid = "pm-tag-impl-pr-dddd", "e3b0c44298fc1c149afbf4c8996fb924"
    monkeypatch.setattr(cm, "recent_launch", lambda *a: False)
    monkeypatch.setattr(cm, "current_container_id", lambda target: cid)
    monkeypatch.setattr(cm, "container_is_running", lambda target: True)
    monkeypatch.setattr(cm, "_probe_setup", lambda target: (True, "", ""))
    monkeypatch.setattr(cm, "_host_claude_json", lambda: tmp_path / "absent-config")
    monkeypatch.setattr(reaper, "is_retained", lambda *a: False)
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    monkeypatch.setattr(cm, "_renew_launch", Mock())

    def validate(target, session_tag, pr_id):
        try:
            raise subprocess.TimeoutExpired(["podman", "inspect"], 10)
        except subprocess.TimeoutExpired as exc:
            raise cm.ContainerError(
                f"Cannot inspect mounted push proxy for '{target}': {exc}") from exc
    monkeypatch.setattr(push_proxy, "validate_shared_proxy_mount", validate)

    with pytest.raises(cm.ContainerLaunchError) as error:
        cm.create_container(name, cm.ContainerConfig(), tmp_path,
                            allowed_push_branch="b", session_tag="tag",
                            pr_id="pr-dddd")
    assert error.value.kind == "timeout"
    assert str(error.value).startswith(f"Container '{name}'")


def test_setup_wait_keeps_running_state_probe_cause(monkeypatch, tmp_path):
    """A failed inspect during the setup wait must not become a bare timeout."""
    name = "pm-tag-review-pr-eeee"
    monkeypatch.setattr(cm, "_SETUP_TIMEOUT", 0.05)
    monkeypatch.setattr(cm, "_SETUP_POLL_INTERVAL", 0.005)

    def runtime(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "container state improper")

    monkeypatch.setattr(cm, "_run_runtime", runtime)

    def running(target):
        raise cm.launch_error(name, "runtime", "storage lock unavailable",
                              stage="inspect existing container")
    monkeypatch.setattr(cm, "container_is_running", running)

    with pytest.raises(cm.ContainerLaunchError) as error:
        cm._wait_for_setup(name)
    assert error.value.kind == "timeout"
    assert "storage lock unavailable" in str(error.value)
    assert "container state improper" in str(error.value)


def test_reuse_os_error_is_a_classified_launch_error(monkeypatch, tmp_path):
    """A reuse-path OS failure must not escape as an unclassified traceback.

    ``_ensure_reusable`` touches the push-proxy sockets and the runtime
    directly.  ``qa debug`` only catches ContainerError, so a raw OSError
    (full /tmp, EMFILE, a vanished runtime binary) reached the user as a
    traceback instead of a launch error naming the container.
    """
    name = "pm-tag-review-pr-aaaa"
    monkeypatch.setattr(cm, "recent_launch", lambda *a, **k: False)
    monkeypatch.setattr(cm, "_ensure_reusable",
                        Mock(side_effect=OSError(28, "No space left on device")))
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm.create_container(name, cm.ContainerConfig(), tmp_path)
    assert error.value.kind == "runtime"
    assert "No space left on device" in str(error.value)
    assert name in str(error.value)
