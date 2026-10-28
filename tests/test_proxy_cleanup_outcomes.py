"""Proxy cleanup failures retain ownership and stay visible until retry."""

import json
from unittest.mock import Mock

from click.testing import CliRunner

from pm_core import container as cm, container_reaper as reaper, push_proxy
from pm_core.cli import cli


def test_failed_socket_removal_keeps_owner_record(monkeypatch, tmp_path):
    directory = tmp_path / "proxy"
    directory.mkdir()
    owner = directory / "owner.json"
    owner.write_text(json.dumps({"runtime_domain": reaper._runtime_domain()}))
    socket = directory / "push.sock"
    socket.touch()
    monkeypatch.setattr(push_proxy, "_shared_sock_dir_path", lambda *a: str(directory))
    monkeypatch.setattr(cm, "containers_for_pr", lambda *a: set())
    kill = Mock(side_effect=PermissionError("socket unlink denied"))
    monkeypatch.setattr(push_proxy, "_kill_proxy_socket", kill)
    import pytest
    with pytest.raises(PermissionError, match="socket unlink denied"):
        push_proxy.release_proxy_if_unused("tag", "pr-aaaa")
    assert owner.exists(), "failed cleanup must remain discoverable in its runtime domain"
    assert socket.exists()
    kill.side_effect = lambda path: socket.unlink()
    assert push_proxy.release_proxy_if_unused("tag", "pr-aaaa")
    assert not owner.exists()


def test_proxy_sweep_failure_is_reported_persisted_and_retried(monkeypatch):
    domain = reaper._runtime_domain()
    monkeypatch.setattr(reaper, "list_containers", lambda: [])
    monkeypatch.setattr(cm, "running_container_count", lambda: 0)
    monkeypatch.setattr(cm, "keyring_summary", lambda: "")
    monkeypatch.setattr(push_proxy, "runtime_domain", lambda: domain)
    monkeypatch.setattr(push_proxy, "list_shared_proxies", lambda: [
        {"session_tag": "tag", "pr_id": "pr-aaaa", "runtime_domain": domain}])
    release = Mock(side_effect=PermissionError("socket unlink denied"))
    monkeypatch.setattr(push_proxy, "release_proxy_decision", release)
    args = ["container", "reap", "--session", "tag"]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 1, result.output
    assert "socket unlink denied" in result.output
    assert "failed 1" in result.output
    assert any("socket unlink denied" in f["error"]
               for f in reaper.pending_failures().values())
    release.side_effect = None
    release.return_value = push_proxy.PROXY_RELEASED
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, result.output
    assert "stopped 1 unused proxy" in result.output
    assert not reaper.pending_failures()


def test_unknown_proxy_inventory_is_a_visible_retryable_failure(monkeypatch):
    domain = reaper._runtime_domain()
    monkeypatch.setattr(reaper, "list_containers", lambda: [])
    monkeypatch.setattr(cm, "running_container_count", lambda: 0)
    monkeypatch.setattr(cm, "keyring_summary", lambda: "")
    monkeypatch.setattr(push_proxy, "runtime_domain", lambda: domain)
    monkeypatch.setattr(push_proxy, "list_shared_proxies", lambda: [
        {"session_tag": "tag", "pr_id": "pr-aaaa", "runtime_domain": domain}])
    monkeypatch.setattr(push_proxy, "release_proxy_decision",
                        lambda *a: push_proxy.PROXY_UNAVAILABLE)
    result = CliRunner().invoke(cli, ["container", "reap"])
    assert result.exit_code == 1, result.output
    assert "proxy" in result.output and "inventory" in result.output
    assert reaper.pending_failures()


def test_in_use_proxy_resolves_an_earlier_transient_failure(monkeypatch, tmp_path):
    """A proxy proven still in use has no pending work left to retry.

    Its socket directory still exists, so the "gone for good" prune cannot
    clear the record — a later successful pass that finds it in use must.
    """
    domain = reaper._runtime_domain()
    sock_dir = tmp_path / "proxy"
    sock_dir.mkdir()
    monkeypatch.setattr(reaper, "list_containers", lambda: [])
    monkeypatch.setattr(cm, "running_container_count", lambda: 0)
    monkeypatch.setattr(cm, "keyring_summary", lambda: "")
    monkeypatch.setattr(push_proxy, "runtime_domain", lambda: domain)
    monkeypatch.setattr(push_proxy, "_shared_sock_dir_path", lambda *a: str(sock_dir))
    monkeypatch.setattr(push_proxy, "list_shared_proxies", lambda: [
        {"session_tag": "tag", "pr_id": "pr-aaaa", "runtime_domain": domain}])
    monkeypatch.setattr(push_proxy, "release_proxy_decision",
                        lambda *a: push_proxy.PROXY_UNAVAILABLE)
    result = CliRunner().invoke(cli, ["container", "reap"])
    assert result.exit_code == 1, result.output
    assert reaper.pending_failures()

    # Inventory is reachable again and the proxy is legitimately in use.
    monkeypatch.setattr(push_proxy, "release_proxy_decision",
                        lambda *a: push_proxy.PROXY_IN_USE)
    result = CliRunner().invoke(cli, ["container", "reap"])
    assert result.exit_code == 0, result.output
    assert not reaper.pending_failures()


def test_undetermined_proxy_keeps_an_earlier_failure(monkeypatch, tmp_path):
    """A busy lock (or a foreign owner record) is not proof of use.

    Only a definitive answer may clear a recorded failure: this pass never
    inventoried the containers behind the proxy, so the failure must stay
    visible and retryable.
    """
    domain = reaper._runtime_domain()
    sock_dir = tmp_path / "proxy"
    sock_dir.mkdir()
    monkeypatch.setattr(reaper, "list_containers", lambda: [])
    monkeypatch.setattr(cm, "running_container_count", lambda: 0)
    monkeypatch.setattr(cm, "keyring_summary", lambda: "")
    monkeypatch.setattr(push_proxy, "runtime_domain", lambda: domain)
    monkeypatch.setattr(push_proxy, "_shared_sock_dir_path", lambda *a: str(sock_dir))
    monkeypatch.setattr(push_proxy, "list_shared_proxies", lambda: [
        {"session_tag": "tag", "pr_id": "pr-aaaa", "runtime_domain": domain}])
    monkeypatch.setattr(push_proxy, "release_proxy_decision",
                        lambda *a: push_proxy.PROXY_UNAVAILABLE)
    assert CliRunner().invoke(cli, ["container", "reap"]).exit_code == 1
    assert reaper.pending_failures()

    monkeypatch.setattr(push_proxy, "release_proxy_decision",
                        lambda *a: push_proxy.PROXY_UNDETERMINED)
    result = CliRunner().invoke(cli, ["container", "reap"])
    assert result.exit_code == 0, result.output
    assert reaper.pending_failures(), "a busy lock must not clear the failure"



def _collect_stopped(fn):
    sink: list[str] = []
    token = push_proxy.stopped_proxy_sink.set(sink)
    try:
        fn()
    finally:
        push_proxy.stopped_proxy_sink.reset(token)
    return sink


def test_stopping_a_proxy_reports_it_to_the_sink(tmp_path):
    """QA S45: a reap that stops a removed container's proxy can say so."""
    directory = tmp_path / "pm-push-proxy-tag-pr-aaaa"
    directory.mkdir()
    (directory / "push.sock").touch()
    stopped = _collect_stopped(lambda: push_proxy._kill_proxy_socket(str(directory / "push.sock")))
    assert stopped == [str(directory)]
    assert not directory.exists()


def test_a_proxy_already_stopped_by_another_release_is_reported_once(tmp_path):
    """QA S51: reaping two containers that shared one proxy printed it twice
    and counted "stopped 2 unused proxy(ies)" — the second release found it gone."""
    directory = tmp_path / "pm-push-proxy-tag-pr-aaaa"
    directory.mkdir()
    (directory / "push.sock").touch()
    sock = str(directory / "push.sock")
    stopped = _collect_stopped(lambda: [push_proxy._kill_proxy_socket(sock)
                                        for _ in range(2)])
    assert stopped == [str(directory)]


def test_a_kept_proxy_generation_is_not_reported(tmp_path):
    sock = tmp_path / "proxy" / "push.sock"
    sock.parent.mkdir()
    sock.touch()
    stopped = _collect_stopped(lambda: push_proxy._kill_proxy_socket(
        str(sock), expected_identity=(0, 0, 0)))
    assert stopped == [] and sock.exists()


def test_shared_proxy_release_with_its_container_is_reported(monkeypatch, tmp_path):
    directory = tmp_path / "proxy"
    directory.mkdir()
    (directory / "owner.json").write_text(json.dumps({"runtime_domain": reaper._runtime_domain()}))
    (directory / "push.sock").touch()
    monkeypatch.setattr(push_proxy, "_shared_sock_dir_path", lambda *a: str(directory))
    monkeypatch.setattr(cm, "containers_for_pr", lambda *a: set())
    stopped = _collect_stopped(lambda: push_proxy.release_proxy_if_unused("tag", "pr-aaaa"))
    assert stopped == [str(directory)]


def test_reap_output_lists_proxies_stopped_with_containers(capsys):
    from pm_core.cli.container import echo_reap_outcome
    info = reaper.ContainerInfo(name="pm-tag-impl-pr-aaaa", id="c" * 64, running=True)
    out = reaper.Outcome(scope="session tag", removed=["pm-tag-impl-pr-aaaa"],
                         proxies_stopped=["/tmp/pm-push-proxy-tag-pr-aaaa"])
    out.decisions.append(reaper.Decision(info, "remove", "no owning pane (attempt ended)"))
    echo_reap_outcome(out)
    text = capsys.readouterr().out
    assert "removed  pm-tag-impl-pr-aaaa" in text
    assert "stopped  push proxy /tmp/pm-push-proxy-tag-pr-aaaa" in text
    assert "removed 1, kept 0, failed 0, stopped 1 unused proxy(ies)" in text
