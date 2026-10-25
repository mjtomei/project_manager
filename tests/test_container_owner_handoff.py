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
    result = reaper._release_unused_proxies(reaper.Scope())
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
    monkeypatch.setattr(cm, "_create_fresh", lambda *a, **kw: "cid")
    monkeypatch.setattr(cm, "_renew_launch", MagicMock(side_effect=cm.ContainerError("read-only")))
    discard = MagicMock()
    monkeypatch.setattr(cm, "discard_container", discard)
    with pytest.raises(cm.ContainerError, match="read-only"):
        cm.create_container(NAME, cm.ContainerConfig(), Path("/w"))
    assert discard.called is not reused


def test_proxy_owner_records_domain_on_creation(monkeypatch, tmp_path):
    domain = {"runtime":"docker", "daemon_id":"a"}
    monkeypatch.setattr(pp, "runtime_domain", lambda: domain)
    pp._write_owner_file(str(tmp_path), "tag", "pr-aaaa", "/w")
    assert json.loads((tmp_path / pp._OWNER_FILE).read_text())["runtime_domain"] == domain
