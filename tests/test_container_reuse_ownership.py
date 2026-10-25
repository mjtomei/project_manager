"""A new launcher cannot adopt a live allocation's cleanup authority."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from pm_core import container as cm, container_reaper as reaper, qa_loop


NAME = "pm-tag-qa-pr-aaaa-loop-s1"


@pytest.fixture
def reusable(monkeypatch):
    monkeypatch.setattr(cm, "_ensure_reusable", lambda *a, **kw: "cid")
    monkeypatch.setattr(cm, "current_container_id", lambda *a: "cid")
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    monkeypatch.setattr(cm, "_create_fresh", Mock(side_effect=AssertionError("no recreate")))
    cm._renew_launch(NAME)
    return {"id": "cid", "generation": cm.cleanup_generation(NAME)}


@pytest.mark.parametrize("ownership", ["pane", "attachment", "unknown"])
def test_new_launch_preserves_existing_owner(reusable, monkeypatch, ownership):
    if ownership == "pane":
        monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: ["%original"])
        monkeypatch.setattr(cm, "recent_launch", lambda *a: False)
    elif ownership == "unknown":
        monkeypatch.setattr(reaper, "live_owner_panes", Mock(
            side_effect=cm.ContainerError("tmux ownership unavailable")))
    with pytest.raises(cm.ContainerError):
        cm.create_container(NAME, cm.ContainerConfig(), Path("/w"))
    assert cm.cleanup_generation(NAME) == reusable["generation"]


def test_unowned_old_allocation_can_be_reused(reusable, monkeypatch):
    monkeypatch.setattr(cm, "recent_launch", lambda *a: False)
    allocation = {}
    assert cm.create_container(NAME, cm.ContainerConfig(), Path("/w"),
                               allocation_identity=allocation) == "cid"
    assert allocation["generation"] != reusable["generation"]


def test_qa_identity_authorizes_its_own_handoff_only(reusable, monkeypatch):
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: ["%concretizer"])
    allocation = {}
    assert cm.create_qa_container(NAME, cm.ContainerConfig(), Path("/w"), Path("/s"),
                                  allocation_identity=allocation,
                                  reuse_identity=reusable) == "cid"
    assert allocation["generation"] != reusable["generation"]
    with pytest.raises(cm.ContainerError):
        cm.create_qa_container(NAME, cm.ContainerConfig(), Path("/w"), Path("/s"),
                               reuse_identity=reusable)
    assert cm.cleanup_generation(NAME) == allocation["generation"]


def test_recovery_generation_is_not_a_competing_launch(reusable, monkeypatch):
    checks = iter([False])
    monkeypatch.setattr(cm, "recent_launch", lambda *a: next(checks))
    def recover(*a, **kw):
        cm._renew_launch(NAME)  # successful restart of an exhausted unowned container
        return "cid"
    monkeypatch.setattr(cm, "_ensure_reusable", recover)
    assert cm.create_container(NAME, cm.ContainerConfig(), Path("/w")) == "cid"


@pytest.mark.parametrize("condition", ["pids", "memory", "incomplete", "stopped"])
def test_attaching_allocation_is_checked_before_recovery(monkeypatch, condition):
    monkeypatch.setattr(cm, "current_container_id", lambda *a: "cid")
    monkeypatch.setattr(cm, "container_is_running", lambda *a: condition != "stopped")
    monkeypatch.setattr(cm, "_probe_setup", lambda *a: (
        False, condition if condition in ("pids", "memory") else "", "Cannot fork"))
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    monkeypatch.setattr(cm, "_run_runtime", lambda *a, **k: Mock(returncode=1, stderr=""))
    restart = Mock()
    remove = Mock()
    fresh = Mock(return_value="replacement")
    monkeypatch.setattr(cm, "restart_container", restart)
    monkeypatch.setattr(cm, "remove_container", remove)
    monkeypatch.setattr(cm, "_create_fresh", fresh)
    cm._renew_launch(NAME)
    generation = cm.cleanup_generation(NAME)
    with pytest.raises(cm.ContainerError, match="attaching"):
        cm.create_container(NAME, cm.ContainerConfig(), Path("/w"))
    restart.assert_not_called()
    remove.assert_not_called()
    fresh.assert_not_called()
    assert cm.cleanup_generation(NAME) == generation


def test_qa_recovery_accepts_identity_before_restart(reusable, monkeypatch):
    def recover(*a, **kw):
        cm._renew_launch(NAME)
        return "cid"
    monkeypatch.setattr(cm, "_ensure_reusable", recover)
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    assert cm.create_container(NAME, cm.ContainerConfig(), Path("/w"),
                               reuse_identity=reusable) == "cid"


def test_qa_relaunch_passes_captured_ownership(monkeypatch):
    scenario = qa_loop.QAScenario(index=1, title="test", focus="", steps="",
                                 container_name=NAME, container_id="cid",
                                 container_generation="old", worktree_path="/w")
    state = qa_loop.QALoopState(pr_id="pr-aaaa", scenarios=[scenario])
    def create(**kwargs):
        assert kwargs["reuse_identity"] == {"id": "cid", "generation": "old"}
        kwargs["allocation_identity"].update(id="cid", generation="new")
        return "cid"
    monkeypatch.setattr(cm, "create_qa_container", create)
    monkeypatch.setattr(cm, "load_container_config", cm.ContainerConfig)
    assert qa_loop._ensure_scenario_container(scenario, state, {})
    assert scenario.container_generation == "new"
