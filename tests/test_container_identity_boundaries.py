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
    assert "domain unknown" in failure["error"]
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
