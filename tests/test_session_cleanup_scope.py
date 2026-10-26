"""Session teardown selects exact label/legacy ownership, never a name prefix."""

from unittest.mock import Mock

from pm_core import container as cm, container_reaper as reaper


def test_session_cleanup_preserves_prefix_neighbor_and_includes_renamed(monkeypatch):
    own = reaper.ContainerInfo(name="pm-demo-impl-pr-aaaa", id="own", session_tag="demo")
    renamed = reaper.ContainerInfo(name="renamed", id="renamed", session_tag="demo")
    neighbor = reaper.ContainerInfo(name="pm-demo-other-impl-pr-bbbb", id="other", session_tag="demo-other")
    monkeypatch.setattr(reaper, "list_containers", lambda: [own, renamed, neighbor])
    monkeypatch.setattr(cm, "_list_names", lambda *a: [own.name, neighbor.name])
    remove = Mock(return_value=([own.name, renamed.name], {}))
    monkeypatch.setattr(cm, "remove_containers", remove)
    assert cm.cleanup_session_containers("demo") == 2
    remove.assert_called_once_with([own.name, renamed.name])


def test_session_cleanup_inventory_failure_removes_nothing(monkeypatch):
    monkeypatch.setattr(reaper, "list_containers", lambda: None)
    monkeypatch.setattr(cm, "_list_names", lambda *a: ["pm-demo-other-impl-pr-bbbb"])
    remove = Mock(return_value=([], {}))
    monkeypatch.setattr(cm, "remove_containers", remove)
    assert cm.cleanup_session_containers("demo") == 0
    remove.assert_not_called()
