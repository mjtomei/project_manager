"""Regression coverage for lifecycle ownership handoff and runtime domains."""
import contextlib
import json
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pm_core import container as cm, container_reaper as reaper, push_proxy as pp

NAME = "pm-tag-impl-pr-aaaa"


def test_retain_inspects_only_under_removal_lock(monkeypatch):
    held = []

    @contextlib.contextmanager
    def lock(name, **kw):
        held.append(name)
        yield True
        held.pop()

    monkeypatch.setattr(cm, "launch_lock", lock)

    def identity(name):
        assert held == [NAME]
        return "cid"

    monkeypatch.setattr(cm, "current_container_id", identity)
    reaper.retain_current(NAME)
    assert reaper.is_retained(NAME, "cid")


def test_retain_after_removal_does_not_claim_success(monkeypatch):
    monkeypatch.setattr(cm, "current_container_id", lambda n: "")
    with pytest.raises(cm.ContainerError):
        reaper.retain_current(NAME)
    assert not reaper.is_retained(NAME)


def test_marker_write_waits_for_removal_lock(monkeypatch):
    monkeypatch.setattr(cm, "launch_lock", lambda *a, **k: contextlib.nullcontext(False))
    with pytest.raises(cm.ContainerError, match="lock"):
        reaper.retain(NAME, container_id="cid")
    assert not reaper.is_retained(NAME)


def test_reuse_invalidates_old_release_and_protects_attach_gap(monkeypatch):
    reaper._record_release(NAME, "cid", "", "old-owner")
    monkeypatch.setattr(cm, "_ensure_reusable", lambda *a, **kw: "cid")
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    assert cm.create_container(NAME, cm.ContainerConfig(), Path("/w")) == "cid"
    assert cm.cleanup_generation(NAME)
    info = reaper.ContainerInfo(NAME, id="cid", running=True, created=time.time()-3600)
    monkeypatch.setattr(reaper, "_owner_panes", lambda *a, **k: ([], False))
    decision = reaper._decide(info, reaper.Scope(), reaper._PaneCache(),
                              reaper._PrStatus(), time.time(),
                              release_records=[r for _, r in reaper._release_records()])
    assert decision.action == "keep" and "launching" in decision.reason
    old = reaper.Decision(info, "remove", "old release", released=True, release_generation="")
    monkeypatch.setattr(cm, "current_container_id", lambda n: "cid")
    removed = MagicMock()
    monkeypatch.setattr(cm, "remove_container", removed)
    assert not reaper._remove_checked(old, reaper.Scope())[0]
    removed.assert_not_called()


def test_final_recheck_sees_new_attachment_lease(monkeypatch):
    info = reaper.ContainerInfo(NAME, id="cid", created=time.time()-3600)
    decision = reaper.Decision(info, "remove", "unowned")
    cm._renew_launch(NAME)
    monkeypatch.setattr(cm, "current_container_id", lambda n: "cid")
    removed = MagicMock()
    monkeypatch.setattr(cm, "remove_container", removed)
    assert reaper._remove_checked(decision, reaper.Scope()) == (False, "skipped: new owner attaching")
    removed.assert_not_called()


@pytest.mark.parametrize("rc,stderr", [(125, "OCI runtime unavailable"), (126, "permission denied"), (1, "runtime unavailable"), (125, "")])
def test_unknown_exec_failure_preserves_container(monkeypatch, rc, stderr):
    monkeypatch.setattr(cm, "container_is_running", lambda n: True)
    monkeypatch.setattr(cm, "current_container_id", lambda n: "cid")
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw: subprocess.CompletedProcess(a, rc, "", stderr))
    removed = MagicMock()
    monkeypatch.setattr(cm, "remove_container", removed)
    with pytest.raises(cm.ContainerLaunchError):
        cm._ensure_reusable(NAME, Path("/w"), None, session_tag="tag", pr_id="pr-aaaa")
    removed.assert_not_called()


def test_readiness_runtime_failure_preserves_container(monkeypatch):
    monkeypatch.setattr(cm, "container_is_running", lambda n: True)
    monkeypatch.setattr(cm, "current_container_id", lambda n: "cid")
    monkeypatch.setattr(cm, "_probe_setup", lambda n: (False, "", ""))
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw: subprocess.CompletedProcess(a, 125, "", "runtime unavailable"))
    removed = MagicMock()
    monkeypatch.setattr(cm, "remove_container", removed)
    with pytest.raises(cm.ContainerLaunchError):
        cm._ensure_reusable(NAME, Path("/w"), None, session_tag="tag", pr_id="pr-aaaa")
    removed.assert_not_called()


@pytest.mark.parametrize("current,owner,allowed", [
    ({"runtime":"docker", "daemon_id":"a"}, {"runtime":"docker", "daemon_id":"a"}, True),
    ({"runtime":"docker", "daemon_id":"a"}, {"runtime":"docker", "daemon_id":"b"}, False),
    ({"runtime":"docker", "daemon_id":"a"}, None, False),
    (None, {"runtime":"docker", "daemon_id":"a"}, False),
])
def test_proxy_sweep_requires_matching_runtime_domain(monkeypatch, current, owner, allowed):
    monkeypatch.setattr(pp, "runtime_domain", lambda: current)
    monkeypatch.setattr(pp, "list_shared_proxies", lambda: [
        {"session_tag":"tag", "pr_id":"pr-aaaa", "runtime_domain":owner}])
    release = MagicMock(return_value=True)
    monkeypatch.setattr(pp, "release_proxy_if_unused", release)
    result = reaper._release_unused_proxies(reaper.Scope(), {})
    assert bool(result) is allowed
    assert release.called is allowed


@pytest.mark.parametrize("runtime,info,expected", [
    ("docker", {"ID":"daemon"}, {"runtime":"docker", "daemon_id":"daemon"}),
    ("podman", {"host":{"hostname":"host"}, "store":{"graphRoot":"/g", "runRoot":"/r"}},
     {"runtime":"podman", "hostname":"host", "graph_root":"/g", "run_root":"/r", "endpoint":"", "connection":""}),
    ("podman", {"store":{"graphRoot":"/g"}}, None),
    ("docker", {}, None),
])
def test_runtime_domain_parser(monkeypatch, runtime, info, expected):
    monkeypatch.delenv("CONTAINER_HOST", raising=False)
    monkeypatch.delenv("CONTAINER_CONNECTION", raising=False)
    monkeypatch.setattr(cm, "_get_runtime", lambda: runtime)
    monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw: subprocess.CompletedProcess(a, 0, json.dumps(info), ""))
    assert pp.runtime_domain() == expected


@pytest.mark.parametrize("operation", ["reuse", "release"])
def test_known_foreign_proxy_domain_is_preserved(monkeypatch, tmp_path, operation):
    (tmp_path / "push.sock").touch()
    (tmp_path / pp._OWNER_FILE).write_text(json.dumps({"runtime_domain": {"runtime":"docker", "daemon_id":"a"}}))
    monkeypatch.setattr(pp, "runtime_domain", lambda: {"runtime":"docker", "daemon_id":"b"})
    monkeypatch.setattr(pp, "_shared_sock_dir", lambda *a: str(tmp_path))
    monkeypatch.setattr(pp, "_shared_sock_dir_path", lambda *a: str(tmp_path))
    monkeypatch.setattr(pp, "proxy_is_alive", lambda p: True)
    monkeypatch.setattr(cm, "containers_for_pr", lambda *a: set())
    killed = MagicMock()
    monkeypatch.setattr(pp, "_kill_proxy_socket", killed)
    if operation == "reuse":
        with pytest.raises(cm.ContainerError, match="runtime"):
            pp.start_push_proxy(NAME, "/w", "branch", session_tag="tag", pr_id="pr-aaaa")
    else:
        assert pp.release_proxy_if_unused("tag", "pr-aaaa") is False
    killed.assert_not_called()


@pytest.mark.parametrize("reused", [False, True])
def test_launch_generation_failure_is_typed_and_only_discards_fresh(monkeypatch, reused):
    monkeypatch.setattr(cm, "_ensure_reusable", lambda *a, **kw: "cid" if reused else None)
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    monkeypatch.setattr(cm, "_create_fresh", lambda *a, **kw: "cid")
    monkeypatch.setattr(cm, "_renew_launch", MagicMock(side_effect=cm.ContainerError("read-only")))
    discard = MagicMock()
    monkeypatch.setattr(cm, "discard_container", discard)
    with pytest.raises(cm.ContainerError, match="read-only"):
        cm.create_container(NAME, cm.ContainerConfig(), Path("/w"))
    assert discard.called is not reused


def test_proxy_owner_records_domain_on_creation(monkeypatch, tmp_path):
    domain = {"runtime":"docker", "daemon_id":"a"}
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: domain)
    pp._write_owner_file(str(tmp_path), "tag", "pr-aaaa", "/w")
    assert json.loads((tmp_path / pp._OWNER_FILE).read_text())["runtime_domain"] == domain


@pytest.mark.parametrize("change", ["id", "generation", "unknown", "unchanged"])
def test_bulk_cleanup_rechecks_queued_allocations(monkeypatch, change):
    current = {"id": "original-id", "generation": "original-generation"}
    acquisitions = 0
    held = False

    @contextlib.contextmanager
    def lock(*args, **kwargs):
        nonlocal acquisitions, held
        acquisitions += 1
        # Allocation capture is the first acquisition; deletion is the second.
        if acquisitions == 2:
            if change == "id":
                current["id"] = "replacement-id"
            elif change == "generation":
                current["generation"] = "replacement-generation"
            elif change == "unknown":
                current["id"] = None
        held = True
        try:
            yield True
        finally:
            held = False

    monkeypatch.setattr(cm, "launch_lock", lock)
    monkeypatch.setattr(cm, "current_container_id", lambda n: current["id"])
    monkeypatch.setattr(cm, "cleanup_generation", lambda n: current["generation"])
    removed_under_lock = []
    def remove(name, *, container_id):
        assert container_id == "original-id"
        removed_under_lock.append(held)
    monkeypatch.setattr(cm, "remove_container", remove)
    # Explicit removal still ignores retention/live ownership for the original.
    monkeypatch.setattr(reaper, "is_retained", lambda *a: True)
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a, **k: ["%live"])
    removed, failures = cm.remove_containers([NAME])
    if change == "unchanged":
        assert removed == [NAME]
        assert not failures
        assert removed_under_lock == [True]
    else:
        assert not removed
        assert NAME in failures
        assert not removed_under_lock


def test_bulk_cleanup_refuses_unavailable_lifecycle_lock(monkeypatch):
    @contextlib.contextmanager
    def lock(*args, **kwargs):
        yield False
    monkeypatch.setattr(cm, "launch_lock", lock)
    remove = MagicMock()
    monkeypatch.setattr(cm, "remove_container", remove)
    removed, failures = cm.remove_containers([NAME])
    assert not removed
    assert NAME in failures
    remove.assert_not_called()


def test_generation_isolated_between_runtime_domains(monkeypatch):
    domain = {"runtime": "docker", "daemon_id": "a"}
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: domain)
    cm._renew_launch(NAME)
    first = cm.cleanup_generation(NAME)
    domain = {"runtime": "docker", "daemon_id": "b"}
    cm._renew_launch(NAME)
    second = cm.cleanup_generation(NAME)
    assert first != second
    domain = {"runtime": "docker", "daemon_id": "a"}
    assert cm.cleanup_generation(NAME) == first


def test_generation_unknown_runtime_fails_closed(monkeypatch):
    cm._renew_launch(NAME)
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: None)
    with pytest.raises(OSError, match="runtime"):
        cm.cleanup_generation(NAME)
    with pytest.raises(cm.ContainerError, match="runtime"):
        cm._renew_launch(NAME)


def test_scoped_generation_supersedes_legacy_marker():
    legacy = cm._lock_path(f"restart-{NAME}").with_suffix(".generation")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("legacy-generation")
    assert cm.cleanup_generation(NAME) == "legacy-generation"
    cm._renew_launch(NAME)
    current = cm.cleanup_generation(NAME)
    legacy.write_text("late-legacy-write")
    assert current != "legacy-generation"
    assert cm.cleanup_generation(NAME) == current


def test_allocation_identity_captured_before_concurrent_reuse(monkeypatch):
    monkeypatch.setattr(cm, "current_container_id", lambda *a: "cid")
    monkeypatch.setattr(cm, "_ensure_reusable", lambda *a, **kw: "cid")
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    first, second = {}, {}
    cm.create_container(NAME, cm.ContainerConfig(), Path("/w"), allocation_identity=first)
    cm.create_container(NAME, cm.ContainerConfig(), Path("/w"), allocation_identity=second,
                        reuse_identity=first)
    assert first["id"] == second["id"] == "cid"
    assert first["generation"] != second["generation"]
    command = cm.build_exec_cmd(NAME, "true", container_id=first["id"],
                                generation=first["generation"])
    assert first["generation"] in command and second["generation"] not in command


@pytest.mark.parametrize("state", ["stopped", "incomplete", "pids", "memory"])
def test_retention_blocks_destructive_reuse(monkeypatch, state):
    reaper.retain(NAME, container_id="cid")
    monkeypatch.setattr(cm, "container_is_running", lambda n: state != "stopped")
    monkeypatch.setattr(cm, "current_container_id", lambda n: "cid")
    monkeypatch.setattr(cm, "_probe_setup", lambda n: (False, state if state in ("pids", "memory") else "", "exhausted"))
    monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw: subprocess.CompletedProcess(a, 1, "", ""))
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a, **kw: [])
    removed, restarted = MagicMock(), MagicMock()
    monkeypatch.setattr(cm, "remove_container", removed)
    monkeypatch.setattr(cm, "restart_container", restarted)
    monkeypatch.setattr(cm, "_create_fresh", MagicMock(return_value="replacement"))
    with pytest.raises(cm.ContainerError, match="retained"):
        cm.create_container(NAME, cm.ContainerConfig(), Path("/w"))
    removed.assert_not_called()
    restarted.assert_not_called()


def test_proxy_repair_and_validation_hold_shared_lock(monkeypatch):
    held = []
    @contextlib.contextmanager
    def lock(*args, **kwargs):
        held.append(True)
        yield True
        held.pop()
    monkeypatch.setattr(cm, "proxy_lock", lock)
    monkeypatch.setattr(cm, "container_is_running", lambda n: True)
    monkeypatch.setattr(cm, "current_container_id", lambda n: "cid")
    monkeypatch.setattr(cm, "_probe_setup", lambda n: (True, "", ""))
    def start(*args, **kwargs):
        assert held
        return "/sock"
    def validate(*args):
        assert held
    monkeypatch.setattr(pp, "validate_shared_proxy_mount", validate)
    monkeypatch.setattr(pp, "start_push_proxy", start)
    monkeypatch.setattr(pp, "proxy_is_alive", lambda p: True)
    assert cm._ensure_reusable(NAME, Path("/w"), "branch", session_tag="tag", pr_id="pr-aaaa") == "cid"


def test_foreign_inventory_does_not_prune_retention_or_release(monkeypatch):
    a, b = {"runtime": "docker", "daemon_id": "a"}, {"runtime": "docker", "daemon_id": "b"}
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: a)
    reaper.retain(NAME, container_id="a-id")
    reaper._record_release(NAME, "a-id", "", "owner-exit")
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: b)
    reaper.retain(NAME, container_id="b-id")
    reaper._prune_retain_markers({}, time.time() + 2)
    reaper._prune_releases(reaper.Outcome(), reaper.Scope(), time.time() + 2)
    assert not reaper.is_retained(NAME, "b-id")
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: a)
    assert reaper.is_retained(NAME, "a-id")
    assert any(rec["id"] == "a-id" for _, rec in reaper._release_records())


def test_unknown_domain_cannot_prune_legacy_records(monkeypatch):
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: None)
    reaper.retain(NAME, container_id="cid")
    reaper._record_release(NAME, "cid", "", "owner-exit")
    reaper._prune_retain_markers({}, time.time() + 2)
    reaper._prune_releases(reaper.Outcome(), reaper.Scope(), time.time() + 2)
    assert reaper.is_retained(NAME, "cid")
    assert reaper._release_records()


def test_failures_separate_runtime_domains(monkeypatch):
    domain = {"runtime": "docker", "daemon_id": "a"}
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: domain)
    reaper._record(reaper.Outcome(failures={NAME: "timeout"}), reaper.Scope(), "manual")
    domain = {"runtime": "docker", "daemon_id": "b"}
    reaper._record(reaper.Outcome(), reaper.Scope(), "manual", inventory=set())
    domain = {"runtime": "docker", "daemon_id": "a"}
    assert NAME in reaper.pending_failures()


def test_strict_owner_lookup_preserves_unknown_with_known_concretizer(monkeypatch):
    monkeypatch.setattr(reaper, "_inspect", lambda *a, **kw: [reaper.ContainerInfo(NAME, id="cid")])
    monkeypatch.setattr(reaper, "_owner_panes", lambda *a, **kw: (["%1"], True))
    with pytest.raises(cm.ContainerError, match="unknown"):
        reaper.live_owner_panes(NAME, "cid", strict=True)


@pytest.mark.parametrize("owners,removed", [(["%1"], True), (["%1", "%2"], False)])
def test_discard_allows_only_confirmed_concretizer(monkeypatch, owners, removed):
    monkeypatch.setattr(cm, "current_container_id", lambda n: "cid")
    def live(*a, strict=False):
        assert strict
        return owners
    monkeypatch.setattr(reaper, "live_owner_panes", live)
    remove = MagicMock()
    monkeypatch.setattr(cm, "remove_container", remove)
    monkeypatch.setattr(pp, "stop_push_proxy", MagicMock())
    assert cm.discard_unowned_container(NAME, container_id="cid", generation="", allowed_owner_panes={"%1"}) is removed
    assert remove.called is removed


def test_dead_foreign_proxy_is_not_reassigned(monkeypatch, tmp_path):
    (tmp_path / pp._OWNER_FILE).write_text(json.dumps({"runtime_domain": {"runtime": "docker", "daemon_id": "a"}}))
    monkeypatch.setattr(pp, "runtime_domain", lambda: {"runtime": "docker", "daemon_id": "b"})
    monkeypatch.setattr(pp, "_shared_sock_dir", lambda *a: str(tmp_path))
    start = MagicMock()
    monkeypatch.setattr(pp, "_start_proxy_subprocess", start)
    with pytest.raises(cm.ContainerError, match="runtime"):
        pp.start_push_proxy(NAME, "/w", "branch", session_tag="tag", pr_id="pr-aaaa")
    start.assert_not_called()


@pytest.mark.parametrize("current,recorded,release_allowed", [
    ({"runtime": "docker", "daemon_id": "a"}, {"runtime": "docker", "daemon_id": "a"}, True),
    ({"runtime": "docker", "daemon_id": "b"}, {"runtime": "docker", "daemon_id": "a"}, False),
    (None, {"runtime": "docker", "daemon_id": "a"}, False),
    ({"runtime": "docker", "daemon_id": "a"}, None, False),
    (None, None, False),
])
def test_plan_release_records_respect_runtime_domain(monkeypatch, current, recorded, release_allowed):
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: recorded)
    reaper._record_release(NAME, "cid", "", "old-exit")
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: current)
    monkeypatch.setattr(reaper, "pending_failures", lambda: {})
    monkeypatch.setattr(reaper, "list_containers", lambda: [
        reaper.ContainerInfo(NAME, id="cid", running=True, created=0)])
    monkeypatch.setattr(reaper, "_owner_panes", lambda *a, **k: (["%live"], False))
    decision, = reaper.plan().decisions
    assert decision.released is release_allowed
    assert decision.action == ("remove" if release_allowed else "keep")


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_post_setup_requires_pm_home_ownership(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(cm, "_host_claude_json", lambda: tmp_path / "absent-config")
    calls = []
    def runtime(*args, **kwargs):
        calls.append(args)
        if "chown" in args:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(args, 5)
            return subprocess.CompletedProcess(args, 1, "", "chown: Operation not permitted")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(cm, "_run_runtime", runtime)
    with pytest.raises(cm.ContainerLaunchError, match="ownership|chown"):
        cm._post_setup(NAME, tmp_path, True)
    assert not any(cm.SETUP_COMPLETE_SENTINEL in args for args in calls)


@pytest.mark.parametrize("runtime", ["podman", "docker"])
def test_tmux_exec_uses_captured_identity_and_attachment_guard(monkeypatch, runtime):
    import shlex
    monkeypatch.setattr(cm, "_get_runtime", lambda: runtime)
    command = cm.build_exec_cmd(NAME, "worker", cleanup=False,
                                container_id="original-id", generation="original-generation")
    argv = shlex.split(command)
    assert "run_interactive_exec" in argv[2]
    assert argv[3:6] == [NAME, "original-id", "original-generation"]
    assert argv[-1] == "0"
    exec_argv = shlex.split(argv[-3])
    assert "original-id" in exec_argv
    assert NAME not in exec_argv


@pytest.mark.parametrize("current_id,current_generation", [
    ("replacement-id", "original-generation"),
    ("original-id", "replacement-generation"),
])
def test_tmux_generated_guard_refuses_stale_attachment(monkeypatch, current_id, current_generation):
    import shlex
    monkeypatch.setattr(cm, "_get_runtime", lambda: "podman")
    command = cm.build_exec_cmd(NAME, "worker", cleanup=False,
                                container_id="original-id", generation="original-generation")
    argv = shlex.split(command)
    assert "run_interactive_exec" in argv[2]
    monkeypatch.setattr(cm, "current_container_id", lambda _: current_id)
    monkeypatch.setattr(cm, "cleanup_generation", lambda _: current_generation)
    execute = MagicMock()
    monkeypatch.setattr(cm.subprocess, "call", execute)
    with pytest.raises(cm.ContainerError):
        cm.run_interactive_exec(*argv[3:])
    execute.assert_not_called()


def test_tmux_guard_does_not_create_foreground_owner(monkeypatch):
    import shlex
    monkeypatch.setattr(cm, "_get_runtime", lambda: "podman")
    command = cm.build_exec_cmd(NAME, "worker", cleanup=False,
                                container_id="cid", generation="g")
    monkeypatch.setattr(cm, "current_container_id", lambda _: "cid")
    monkeypatch.setattr(cm, "cleanup_generation", lambda _: "g")
    def execute(argv, **kwargs):
        assert not cm.activity_owner(NAME)
        assert kwargs["pass_fds"] == ()
        return 7
    monkeypatch.setattr(cm.subprocess, "call", execute)
    assert cm.run_interactive_exec(*shlex.split(command)[3:]) == 7
