"""Setup and recovery must not switch to a same-name replacement allocation."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from pm_core import container as cm, container_reaper as reaper, push_proxy


NAME = "pm-tag-review-pr-aaaa"
CID = "original-id"


@pytest.fixture
def fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(cm, "image_exists", lambda *a: True)
    monkeypatch.setattr(cm, "_get_runtime", lambda: "podman")
    monkeypatch.setattr(cm, "_nested_podman_enabled", lambda: False)
    monkeypatch.setattr(cm, "_resolve_claude_binary", lambda: None)
    monkeypatch.setattr(cm, "_relieve_keyring_pressure", lambda: None)
    monkeypatch.setattr(cm, "remove_container", Mock())
    monkeypatch.setattr(cm.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(cm, "_run_runtime", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, CID, ""))

    def create():
        return cm._create_fresh(NAME, cm.ContainerConfig(), tmp_path,
                                extra_ro_mounts=None, extra_rw_mounts=None,
                                allowed_push_branch=None, session_tag="tag",
                                pr_id="pr-aaaa", labels={})
    return create


@pytest.mark.parametrize("failure", [False, True])
def test_fresh_setup_and_failure_cleanup_pin_created_id(fresh, monkeypatch, failure):
    targets = []
    monkeypatch.setattr(cm, "_wait_for_setup", lambda target: targets.append(target))
    def post(target, *args):
        targets.append(target)
        if failure:
            raise cm.ContainerError("config copy failed")
    monkeypatch.setattr(cm, "_post_setup", post)
    discard = Mock()
    monkeypatch.setattr(cm, "discard_container", discard)
    if failure:
        with pytest.raises(cm.ContainerError, match="config copy failed"):
            fresh()
        discard.assert_called_once_with(NAME, container_id=CID)
    else:
        assert fresh() == CID
    assert targets == [CID, CID]


def test_fresh_run_without_identity_preserves_the_allocation(fresh, monkeypatch):
    """An empty id from a successful run is unknown, not proof of absence.

    Falling through would probe by the reusable name and finally remove by
    name, which can delete an allocation a concurrent launcher attached.
    """
    monkeypatch.setattr(cm, "_run_runtime", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, "", ""))
    wait, discard = Mock(), Mock()
    monkeypatch.setattr(cm, "_wait_for_setup", wait)
    monkeypatch.setattr(cm, "discard_container", discard)

    with pytest.raises(cm.ContainerLaunchError) as error:
        fresh()

    assert error.value.kind == "runtime"
    assert "without a container id" in str(error.value)
    wait.assert_not_called()
    discard.assert_not_called()


@pytest.mark.parametrize("phase", ["finish", "remove", "restart", "shared", "unshared"])
def test_reuse_pins_setup_recovery_and_mount_inspection(monkeypatch, tmp_path, phase):
    monkeypatch.setattr(cm, "container_is_running", lambda n: True)
    monkeypatch.setattr(cm, "current_container_id", lambda n: CID)
    monkeypatch.setattr(reaper, "is_retained", lambda *a: False)
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    probes = []
    def probe(target):
        probes.append(target)
        return (phase in {"shared", "unshared"}, "pids" if phase == "restart" else "", "Cannot fork")
    monkeypatch.setattr(cm, "_probe_setup", probe)
    runtime = Mock(return_value=subprocess.CompletedProcess([], 0 if phase == "finish" else 1, "", ""))
    monkeypatch.setattr(cm, "_run_runtime", runtime)
    post = Mock()
    monkeypatch.setattr(cm, "_post_setup", post)
    complete = Mock(return_value=True)
    monkeypatch.setattr(cm, "_setup_complete", complete)
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    restart = Mock()
    monkeypatch.setattr(cm, "restart_container", restart)
    validate = Mock()
    repair = Mock(return_value="socket")
    monkeypatch.setattr(push_proxy, "validate_shared_proxy_mount", validate)
    monkeypatch.setattr(push_proxy, "repair_unshared_proxy", repair)
    monkeypatch.setattr(push_proxy, "start_push_proxy", Mock(return_value="socket"))
    monkeypatch.setattr(push_proxy, "proxy_is_alive", lambda p: True)
    result = cm._ensure_reusable(NAME, tmp_path, "topic" if phase in {"shared", "unshared"} else None,
                                 session_tag="tag" if phase == "shared" else None,
                                 pr_id="pr-aaaa" if phase == "shared" else None)
    assert probes == [CID]
    if phase == "finish":
        assert runtime.call_args.args[1] == CID
        assert post.call_args.args[0] == CID
        complete.assert_called_once_with(CID)
    elif phase == "remove":
        remove.assert_called_once_with(NAME, container_id=CID)
        assert result is None
    elif phase == "restart":
        restart.assert_called_once_with(NAME, container_id=CID)
    elif phase == "shared":
        validate.assert_called_once_with(CID, "tag", "pr-aaaa")
    else:
        repair.assert_called_once_with(CID, str(tmp_path), "topic")


def test_owner_metadata_is_inspected_by_captured_id(monkeypatch):
    inspected = []
    def inspect(names, **kwargs):
        inspected.extend(names)
        return [reaper.ContainerInfo("renamed", id=CID)]
    monkeypatch.setattr(reaper, "_inspect", inspect)
    monkeypatch.setattr(cm, "activity_owner", lambda *a: False)
    monkeypatch.setattr(reaper, "_owner_panes", lambda *a, **k: ([], False))
    assert reaper.live_owner_panes(NAME, CID) == []
    assert inspected == [CID]


@pytest.mark.parametrize("current", ["replacement-id", "", None])
def test_renew_refuses_changed_or_unknown_identity(monkeypatch, current):
    monkeypatch.setattr(cm, "current_container_id", lambda n: current)
    write = Mock()
    monkeypatch.setattr(cm, "_write_identity_generation", write)
    with pytest.raises(cm.ContainerLaunchError, match="identity changed"):
        cm._renew_launch(NAME, CID)
    write.assert_not_called()


def test_publication_failure_discards_only_captured_allocation(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "recent_launch", lambda *a: False)
    monkeypatch.setattr(cm, "_ensure_reusable", lambda *a, **k: None)
    monkeypatch.setattr(cm, "_create_fresh", lambda *a, **k: CID)
    monkeypatch.setattr(cm, "_renew_launch", Mock(side_effect=KeyboardInterrupt()))
    discard = Mock()
    monkeypatch.setattr(cm, "discard_container", discard)
    with pytest.raises(KeyboardInterrupt):
        cm.create_container(NAME, cm.ContainerConfig(), tmp_path)
    discard.assert_called_once_with(NAME, container_id=CID)


def test_recovery_refuses_replacement_before_changing_generation(monkeypatch):
    monkeypatch.setattr(cm, "current_container_id", lambda n: "replacement-id")
    runtime = Mock()
    monkeypatch.setattr(cm, "_run_runtime", runtime)
    with pytest.raises(cm.ContainerError, match="identity.*changed"):
        cm.restart_container(NAME, container_id=CID)
    runtime.assert_not_called()
    assert not cm._restart_generation_path(NAME).exists()


def test_removal_records_proxy_scope_from_captured_id(monkeypatch, tmp_path):
    proxy = (NAME, str(tmp_path / "push.sock"), (1, 2, 3), "renamed")
    monkeypatch.setattr(push_proxy, "capture_unshared_proxy", lambda target: proxy)
    deferred = Mock(return_value=tmp_path / "release.json")
    monkeypatch.setattr(push_proxy, "defer_unshared_release", deferred)
    monkeypatch.setattr(push_proxy, "forget_unshared_proxy", Mock())
    monkeypatch.setattr(push_proxy, "release_captured_unshared_proxy", lambda p: True)
    monkeypatch.setattr(cm, "_run_runtime", lambda *a, **k:
                        subprocess.CompletedProcess(a, 1, "", "no such container"))
    assert cm.remove_container(NAME, container_id=CID)
    deferred.assert_called_once_with(proxy, CID)


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_post_setup_directory_failure_never_stamps_complete(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(cm, "_host_claude_json", lambda: tmp_path / "absent-config")
    calls = []
    def runtime(*args, **kwargs):
        calls.append(args)
        if "mkdir" in args:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(args, 5)
            return subprocess.CompletedProcess(args, 1, "", "mkdir: Permission denied")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(cm, "_run_runtime", runtime)
    with pytest.raises(cm.ContainerLaunchError, match="ownership|Permission denied"):
        cm._post_setup(CID, tmp_path, True)
    assert not any(cm.SETUP_COMPLETE_SENTINEL in args for args in calls)


def test_post_setup_creates_pm_home_without_optional_hook_mount(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "_host_claude_json", lambda: tmp_path / "absent-config")
    created = False
    stamped = False
    def runtime(*args, **kwargs):
        nonlocal created, stamped
        if "mkdir" in args:
            assert args[-1] == "/home/pm/.pm"
            created = True
        if "chown" in args and not created:
            return subprocess.CompletedProcess(args, 1, "", "chown: No such file or directory")
        if cm.SETUP_COMPLETE_SENTINEL in args:
            stamped = True
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(cm, "_run_runtime", runtime)
    cm._post_setup(CID, tmp_path, True)
    assert created and stamped


@pytest.mark.parametrize("is_podman", [False, True])
@pytest.mark.parametrize("has_config", [False, True])
def test_post_setup_repairs_ownership_as_root(monkeypatch, tmp_path, is_podman, has_config):
    config = tmp_path / ".claude.json"
    if has_config:
        config.write_text("{}")
    monkeypatch.setattr(cm, "_host_claude_json", lambda: config)
    from pm_core import workspace_trust
    monkeypatch.setattr(workspace_trust, "approved_path", lambda p: False)
    calls = []

    def runtime(*args, **kwargs):
        calls.append(args)
        # Both supported runtimes may default to USER pm. A runtime-created
        # hooks parent (and Docker cp's config) belongs to root, not that user.
        if args[0] == "exec" and "chown" in args and args[1:3] != ("--user", "0"):
            error = "chown: Operation not permitted"
            if kwargs.get("check", True):
                raise subprocess.CalledProcessError(1, args, stderr=error)
            return subprocess.CompletedProcess(args, 1, "", error)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    cm._post_setup(CID, tmp_path, is_podman)
    ownership_calls = [args for args in calls if "mkdir" in args or "chown" in args]
    assert ownership_calls
    assert all(args[:4] == ("exec", "--user", "0", CID) for args in ownership_calls)
    if has_config and not is_podman:
        assert any(args[-1] == "/home/pm/.claude.json" for args in ownership_calls)
    assert any(cm.SETUP_COMPLETE_SENTINEL in args for args in calls)


def test_reused_setup_timeout_does_not_claim_container_removed(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "container_is_running", lambda n: True)
    monkeypatch.setattr(cm, "current_container_id", lambda n: CID)
    monkeypatch.setattr(reaper, "is_retained", lambda *a: False)
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    monkeypatch.setattr(cm, "_probe_setup", lambda n: (False, "", ""))
    monkeypatch.setattr(cm, "_host_claude_json", lambda: tmp_path / "absent-config")

    def runtime(*args, **kwargs):
        if "mkdir" in args:
            raise subprocess.TimeoutExpired(args, 5)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm._ensure_reusable(NAME, tmp_path, None, session_tag=None, pr_id=None)
    assert error.value.kind == "timeout"
    assert "ownership timed out" in str(error.value)
    assert "was removed" not in str(error.value)
    assert "pm container reap --dry-run" in str(error.value)
    remove.assert_not_called()


@pytest.mark.parametrize("failure", ["conflict", "timeout", "cancel", "proxy"])
@pytest.mark.parametrize("allocation", ["ours", "foreign", "unknown", "absent"])
def test_fresh_failure_cleanup_requires_attempt_identity(fresh, monkeypatch, tmp_path,
                                                        failure, allocation):
    attempt = "this-launch-attempt"
    discarded = Mock()
    stopped = Mock()
    monkeypatch.setattr(cm, "discard_container", discarded)
    monkeypatch.setattr(push_proxy, "stop_push_proxy", stopped)

    def runtime(*args, **kwargs):
        if args[0] == "run":
            if failure == "timeout":
                raise subprocess.TimeoutExpired(args, 60)
            if failure == "cancel":
                raise KeyboardInterrupt()
            return subprocess.CompletedProcess(args, 125, "", "container name is already in use")
        assert args[0] == "inspect"
        if allocation == "unknown":
            return subprocess.CompletedProcess(args, 1, "", "runtime unavailable")
        if allocation == "absent":
            return subprocess.CompletedProcess(args, 1, "", "no such container")
        labels = {cm.LABEL_ATTEMPT: attempt if allocation == "ours" else "other-attempt"}
        return subprocess.CompletedProcess(args, 0,
            json.dumps([{"Id": CID, "Config": {"Labels": labels}}]), "")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    if failure == "proxy":
        monkeypatch.setattr(push_proxy, "start_push_proxy",
                            Mock(side_effect=cm.ContainerError("proxy failed")))
    expected_error = KeyboardInterrupt if failure == "cancel" else cm.ContainerError
    with pytest.raises(expected_error):
        cm._create_fresh(NAME, cm.ContainerConfig(), tmp_path,
                         extra_ro_mounts=None, extra_rw_mounts=None,
                         allowed_push_branch="topic" if failure == "proxy" else None,
                         session_tag=None, pr_id=None,
                         labels={cm.LABEL_ATTEMPT: attempt})
    if allocation == "ours":
        discarded.assert_called_once_with(NAME, container_id=CID)
    else:
        discarded.assert_not_called()
    assert stopped.call_count == (1 if allocation == "absent" else 0)
    # Fresh creation must not pre-delete a name that may have been claimed
    # after the caller established absence. Stopped allocation cleanup belongs
    # to the earlier immutable-ID reuse check instead.
    cm.remove_container.assert_not_called()


@pytest.mark.parametrize("allocation", ["absent", "stopped", "retained"])
def test_stopped_preclean_uses_identity_captured_before_state(monkeypatch, tmp_path, allocation):
    events = []
    def identity(name):
        events.append(("identity", name))
        return "" if allocation == "absent" else CID
    def running(target):
        events.append(("state", target))
        assert target == CID
        return False
    monkeypatch.setattr(cm, "current_container_id", identity)
    monkeypatch.setattr(cm, "container_is_running", running)
    monkeypatch.setattr(reaper, "is_retained", lambda *a: allocation == "retained")
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    if allocation == "retained":
        with pytest.raises(cm.ContainerError, match="retained"):
            cm._ensure_reusable(NAME, tmp_path, None, session_tag=None, pr_id=None)
    else:
        assert cm._ensure_reusable(NAME, tmp_path, None, session_tag=None, pr_id=None) is None
    assert events == [("identity", NAME)] + ([] if allocation == "absent" else [("state", CID)])
    if allocation == "stopped":
        remove.assert_called_once_with(NAME, container_id=CID)
    else:
        remove.assert_not_called()
