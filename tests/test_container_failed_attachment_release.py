"""Failed worker attachment must not strand its still-live concretizer."""

import time
from unittest.mock import MagicMock

import pytest

from pm_core import container as cm, container_reaper as reaper, push_proxy

NAME = "pm-tag-qa-pr-aaaa-loop-s1"


@pytest.fixture
def allocation(monkeypatch):
    info = reaper.ContainerInfo(NAME, id="cid", running=True,
                               created=time.time() - 3600)
    state = {"info": info, "owners": ["%5"], "fail": True}
    monkeypatch.setattr(reaper, "list_containers", lambda: [state["info"]] if state["info"] else [])
    monkeypatch.setattr(cm, "current_container_id", lambda name: state["info"].id if state["info"] else "")
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a, **kw: state["owners"])
    monkeypatch.setattr(reaper, "_owner_panes", lambda *a, **kw: (state["owners"], False))
    monkeypatch.setattr(reaper, "_release_unused_proxies", lambda *a: [])
    monkeypatch.setattr(cm, "running_container_count", lambda: int(state["info"] is not None))
    monkeypatch.setattr(cm, "keyring_summary", lambda: "")
    monkeypatch.setattr(cm, "pids_pressure", lambda *a: [])
    monkeypatch.setattr(push_proxy, "stop_push_proxy", MagicMock())

    def remove(name, *, container_id=None):
        assert (container_id or name) == state["info"].id
        if state["fail"]:
            raise cm.ContainerError("runtime rm timed out")
        state["info"] = None
        return True

    state["remove"] = MagicMock(side_effect=remove)
    monkeypatch.setattr(cm, "remove_container", state["remove"])
    return state


@pytest.mark.parametrize("remaining", ["cid", None, "", "timeout", "os-error"])
def test_missing_name_discard_checks_captured_allocation(monkeypatch, remaining):
    import subprocess

    inspected = []

    def identity(name):
        inspected.append(name)
        if name == NAME:
            return ""
        assert name == "cid"
        if remaining == "timeout":
            raise subprocess.TimeoutExpired(["podman", "inspect", name], 10)
        if remaining == "os-error":
            raise OSError("runtime unavailable")
        return remaining

    monkeypatch.setattr(cm, "current_container_id", identity)
    remove = MagicMock()
    stop_proxy = MagicMock()
    monkeypatch.setattr(cm, "remove_container", remove)
    monkeypatch.setattr(push_proxy, "stop_push_proxy", stop_proxy)

    assert cm.discard_unowned_container(
        NAME, container_id="cid", generation="captured") is (remaining == "")
    assert inspected == [NAME, "cid"]
    remove.assert_not_called()
    stop_proxy.assert_not_called()


def test_missing_name_preflight_needs_no_allocation_probe(monkeypatch):
    identity = MagicMock(return_value="")
    monkeypatch.setattr(cm, "current_container_id", identity)
    assert cm.discard_unowned_container(NAME)
    identity.assert_called_once_with(NAME)


def discard():
    return cm.discard_unowned_container(
        NAME, container_id="cid", generation="", allowed_owner_panes={"%5"})


def test_failed_concretizer_discard_is_visible_and_retried(allocation):
    assert not discard()
    assert NAME in reaper.pending_failures()
    assert reaper.pending_releases()[NAME]["id"] == "cid"
    # QA clears its worker pane after failed attachment. An ordinary cleanup
    # cannot prove that the remaining concretizer may be ended.
    assert not cm.discard_unowned_container(NAME, container_id="cid", generation="")
    retry = reaper.reconcile(reason="periodic")
    assert "runtime rm timed out" in retry.failures[NAME]
    assert NAME in reaper.pending_failures()
    allocation["fail"] = False
    outcome = reaper.reconcile(reason="periodic")
    assert outcome.removed == [NAME]
    assert not reaper.pending_failures()


@pytest.mark.parametrize("protection", ["other-owner", "retained", "unknown-domain", "write-failure"])
def test_failed_attachment_does_not_authorize_unsafe_release(allocation, monkeypatch, protection):
    if protection == "other-owner":
        allocation["owners"].append("%6")
    elif protection == "retained":
        monkeypatch.setattr(reaper, "is_retained", lambda *a: True)
    elif protection == "unknown-domain":
        monkeypatch.setattr(reaper, "_runtime_domain", lambda: None)
    else:
        monkeypatch.setattr(reaper, "_record_release", MagicMock(side_effect=OSError("disk full")))
    assert not discard()
    allocation["remove"].assert_not_called()
    assert not reaper.pending_releases()


@pytest.mark.parametrize("change", ["replacement", "restart"])
def test_failed_attachment_release_cannot_remove_new_owner(allocation, change):
    assert not discard()
    assert NAME in reaper.pending_releases()
    if change == "replacement":
        allocation["info"].id = "replacement"
    else:
        cm._renew_launch(NAME, "cid")
    allocation["fail"] = False
    allocation["remove"].reset_mock()
    assert not reaper.reconcile(reason="periodic").removed
    allocation["remove"].assert_not_called()
