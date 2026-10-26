"""Regression coverage for remaining lifecycle ownership boundaries."""

import json
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from pm_core import container as cm, container_reaper as reaper, push_proxy
from pm_core.cli import cli


@pytest.mark.parametrize("force", [False, True])
def test_restart_respects_pending_attachment(monkeypatch, force):
    name = "pm-review-pr-1234"
    cm._renew_launch(name)
    monkeypatch.setattr(cm, "pids_usage", lambda: {})
    monkeypatch.setattr(reaper, "live_owner_panes", lambda _: [])
    restart = Mock()
    monkeypatch.setattr(cm, "restart_container", restart)
    result = CliRunner().invoke(cli, ["container", "restart", name] + (["--force"] if force else []))
    assert result.exit_code == (0 if force else 1), result.output
    assert restart.called is force
    if not force:
        assert "attach" in result.output


def test_stopped_renamed_retention_prevents_recreation(monkeypatch, tmp_path):
    old, new, cid = "pm-review-pr-1234", "pm-review-pr-abcd", "retained-id"
    reaper._write_retention(old, "keep filesystem", cid)
    monkeypatch.setattr(cm, "container_is_running", lambda _: False)
    monkeypatch.setattr(cm, "current_container_id", lambda _: cid)
    with pytest.raises(cm.ContainerLaunchError, match="retained"):
        cm._ensure_reusable(new, tmp_path, None, session_tag=None, pr_id=None)


def test_interactive_owner_survives_runtime_rename(monkeypatch):
    old, new, cid = "pm-qa-debug-original", "renamed-debug", "active-id"
    monkeypatch.setattr(cm, "current_container_id", lambda _: cid)
    monkeypatch.setattr(cm, "cleanup_generation", lambda _: "generation")
    monkeypatch.setattr(reaper, "_servers_for", lambda _: [])

    def execute(*args, **kwargs):
        info = reaper.ContainerInfo(name=new, id=cid)
        owners, unknown = reaper._owner_panes(info, reaper._PaneCache())
        assert owners == ["interactive client"]
        assert not unknown
        return 0

    monkeypatch.setattr(cm.subprocess, "call", execute)
    cm.run_interactive_exec(old, cid, "generation", str(cm.container_state_dir()), "worker", "podman")


def test_unknown_domain_release_never_authorizes_other_store(monkeypatch):
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: None)
    reaper._record_release("pm-review-pr-1234", "cloned-id", "cloned-generation", "exit")
    assert reaper._current_release_records() == []
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: {"id": "other-store"})
    assert reaper._current_release_records() == []
    assert len(reaper._release_records()) == 1  # keep diagnostic evidence
    failure = reaper.pending_failures()["pm-review-pr-1234"]
    assert not failure["owner_release"]
    assert failure["unverifiable_release"] is True
    assert "diagnostic" in failure["error"]
    monkeypatch.setattr(reaper, "list_containers", lambda: [reaper.ContainerInfo(
        name="pm-review-pr-1234", id="cloned-id", running=True, created=0)])
    monkeypatch.setattr(cm, "cleanup_generation", lambda _: "cloned-generation")
    monkeypatch.setattr(reaper, "_owner_panes", lambda *a, **k: (["%live"], False))
    decision, = reaper.plan().decisions
    assert decision.action == "keep"
    assert not decision.released


def test_unknown_domain_release_does_not_overwrite_scoped_record(monkeypatch):
    domain = {"id": "original-store"}
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: domain)
    reaper._record_release("pm-review-pr-1234", "cid", "generation", "exit")
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: None)
    reaper._record_release("pm-review-pr-1234", "cid", "generation", "exit")
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: domain)
    assert len(reaper._release_records()) == 2
    assert len(reaper._current_release_records()) == 1


def test_legacy_unscoped_release_remains_readable(monkeypatch):
    directory = reaper._release_dir()
    directory.mkdir(parents=True)
    (directory / "legacy.json").write_text(json.dumps({
        "name": "pm-review-pr-1234", "id": "cid", "generation": "", "at": 1}))
    assert len(reaper._current_release_records()) == 1


def test_interactive_identity_is_runtime_scoped(monkeypatch):
    domain = {"id": "first"}
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: dict(domain))
    monkeypatch.setattr(cm, "current_container_id", lambda _: "cloned-id")
    monkeypatch.setattr(cm, "cleanup_generation", lambda _: "generation")

    def execute(*args, **kwargs):
        assert cm.activity_owner("renamed", "cloned-id")
        domain["id"] = "second"
        assert not cm.activity_owner("renamed", "cloned-id")
        return 0

    monkeypatch.setattr(cm.subprocess, "call", execute)
    cm.run_interactive_exec("pm-original", "cloned-id", "generation",
                            str(cm.container_state_dir()), "worker", "podman")


@pytest.mark.parametrize("users", [{"replacement"}, None, set()])
def test_session_proxy_cleanup_rechecks_runtime_users(monkeypatch, tmp_path, users):
    tag, pr = "review-i12", "pr-1234"
    directory = tmp_path / f"pm-push-proxy-{tag}-{pr}"
    directory.mkdir()
    socket = directory / "push.sock"
    socket.touch()
    domain = reaper._runtime_domain()
    (directory / "owner.json").write_text(json.dumps({"runtime_domain": domain}))
    monkeypatch.setattr(push_proxy, "_shared_sock_dir_path", lambda *a: str(directory))
    monkeypatch.setattr(push_proxy, "list_shared_proxies", lambda: [
        {"session_tag": tag, "pr_id": pr, "sock_path": str(socket), "runtime_domain": domain}])
    monkeypatch.setattr(cm, "containers_for_pr", lambda *a: users)
    # The old implementation's destructive glob sees the exact same fixture.
    monkeypatch.setattr("glob.glob", lambda _: [str(socket)])
    count = push_proxy.stop_session_proxies(tag)
    assert socket.exists() is (users != set())
    assert count == (1 if users == set() else 0)


@pytest.mark.parametrize("domain", [None, {"id": "foreign-store"}])
def test_session_proxy_cleanup_preserves_unknown_or_foreign_domain(monkeypatch, tmp_path, domain):
    directory = tmp_path / "pm-push-proxy-review-i12-pr-1234"
    directory.mkdir()
    socket = directory / "push.sock"
    socket.touch()
    monkeypatch.setattr(push_proxy, "list_shared_proxies", lambda: [
        {"session_tag": "review-i12", "pr_id": "pr-1234", "sock_path": str(socket),
         "runtime_domain": domain}])
    monkeypatch.setattr("glob.glob", lambda _: [str(socket)])
    release = Mock(return_value=True)
    monkeypatch.setattr(push_proxy, "release_proxy_if_unused", release)
    assert push_proxy.stop_session_proxies("review-i12") == 0
    assert socket.exists()
    release.assert_not_called()


@pytest.mark.parametrize("legacy", [False, True])
def test_owner_release_follows_renamed_allocation(monkeypatch, legacy):
    old, new, cid = "pm-qa-pr-1234-loop-s1", "renamed-worker", "original-id"
    monkeypatch.setattr(cm, "current_container_id", lambda _: cid)
    cm._renew_launch(old, "" if legacy else cid)
    generation = cm.cleanup_generation(old)
    info = reaper.ContainerInfo(new, id=cid, running=True, created=0)
    monkeypatch.setattr(reaper, "list_containers", lambda: [info])
    monkeypatch.setattr(reaper, "_owner_panes", lambda *a, **k: (["%worker"], False))
    monkeypatch.setattr(reaper, "reconcile", lambda scope, **kw: reaper.plan(scope))
    outcome = reaper.release_containers([old], owner_release=True,
        expected_ids={old: cid}, expected_generations={old: generation})
    decision, = outcome.decisions
    assert decision.released
    assert decision.action == "remove"
    # A deferred/retained release must not be pruned merely because the old
    # name disappeared; a later full pass must still find it by ID.
    reaper._prune_releases(outcome, reaper.Scope(), float("inf"))
    assert len(reaper._release_records()) == 1
    assert reaper.plan().decisions[0].released
    monkeypatch.setattr(cm, "current_container_id", lambda _: cid)
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    assert reaper._remove_checked(decision, reaper.Scope())[0]
    remove.assert_called_once_with(new, container_id=cid)
    outcome.removed.append(new)
    reaper._prune_releases(outcome, reaper.Scope(), float("inf"))
    assert reaper._release_records() == []


@pytest.mark.parametrize("legacy", [False, True])
def test_renamed_restart_invalidates_original_release(monkeypatch, legacy):
    import subprocess
    old, new, cid = "pm-qa-pr-1234-loop-s1", "renamed-worker", "original-id"
    monkeypatch.setattr(cm, "current_container_id", lambda _: cid)
    cm._renew_launch(old, "" if legacy else cid)
    original = cm.cleanup_generation(old)
    reaper._record_release(old, cid, original, "finished")
    info = reaper.ContainerInfo(new, id=cid, running=True, created=0)
    monkeypatch.setattr(reaper, "list_containers", lambda: [info])
    monkeypatch.setattr(reaper, "_owner_panes", lambda *a, **k: (["%worker"], False))
    decision, = reaper.plan().decisions
    assert decision.released
    monkeypatch.setattr(cm, "current_container_id", lambda _: cid)
    monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw: subprocess.CompletedProcess(
        a, 0, '"2026-10-26T00:00:00Z"' if a[0] == "inspect" else "", ""))
    monkeypatch.setattr(cm, "_wait_for_setup", lambda *a, **k: None)
    monkeypatch.setattr(cm, "_setup_complete", lambda _: True)
    with cm.launch_lock(new):
        cm.restart_container(new)
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    assert not reaper._remove_checked(decision, reaper.Scope())[0]
    remove.assert_not_called()
    assert not reaper.plan().decisions[0].released
    reaper._prune_releases(reaper.plan(), reaper.Scope(), float("inf"))
    assert reaper._release_records() == []


def test_renamed_release_does_not_authorize_original_name_replacement(monkeypatch):
    old, new, cid = "pm-qa-pr-1234-loop-s1", "renamed-worker", "original-id"
    monkeypatch.setattr(cm, "current_container_id", lambda _: cid)
    cm._renew_launch(old, cid)
    generation = cm.cleanup_generation(old)
    reaper._record_release(old, cid, generation, "finished")
    monkeypatch.setattr(cm, "current_container_id", lambda _: "replacement-id")
    cm._renew_launch(old, "replacement-id")
    monkeypatch.setattr(reaper, "list_containers", lambda: [
        reaper.ContainerInfo(old, id="replacement-id", running=True),
        reaper.ContainerInfo(new, id=cid, running=True)])
    monkeypatch.setattr(reaper, "_owner_panes", lambda *a, **k: (["%worker"], False))
    scope = reaper.Scope(names={old}, owner_release=True,
                         expected_ids={old: cid}, expected_generations={old: generation})
    replacement, original = reaper.plan(scope).decisions
    assert replacement.action == "keep"
    assert original.released


def test_identity_generation_isolated_across_runtime_domains(monkeypatch):
    name, cid = "pm-review-pr-1234", "cloned-id"
    monkeypatch.setattr(cm, "current_container_id", lambda _: cid)
    domain = {"id": "first"}
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: dict(domain))
    cm._renew_launch(name, cid)
    first = reaper.allocation_generation(name, cid)
    domain["id"] = "second"
    cm._renew_launch(name, cid)
    second = reaper.allocation_generation(name, cid)
    assert first != second
    domain["id"] = "first"
    assert reaper.allocation_generation("renamed", cid) == first
