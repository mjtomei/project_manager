"""A concretizer exception must not authorize another tmux server's pane."""
from unittest.mock import MagicMock

import pytest

from pm_core import container as cm, container_reaper as reaper, push_proxy

NAME = "pm-tag-qa-pr-aaaa-loop-s1"
CID = "a" * 64


@pytest.mark.parametrize("local,foreign,removed", [
    (["%0"], ["%0"], False),
    ([], ["%0"], False),
    (["%0"], ["%1"], False),
    (["%0"], None, False),
    (["%0"], [], True),
    ([], [], True),
])
def test_failed_attachment_keeps_other_server_owners(monkeypatch, tmp_path,
                                                    local, foreign, removed):
    local_socket = str(tmp_path / "local.sock")
    foreign_socket = str(tmp_path / "foreign.sock")
    monkeypatch.setenv("PM_TMUX_SOCKET", local_socket)
    info = reaper.ContainerInfo(NAME, id=CID, labels={cm.LABEL_TMUX_SOCKET: local_socket})
    servers = [reaper._server_for_socket(local_socket),
               reaper._server_for_socket(foreign_socket)]
    monkeypatch.setattr(reaper, "_servers_for", lambda _: servers)
    monkeypatch.setattr(reaper, "_inspect", lambda *a, **kw: [info])

    def snapshot(server):
        panes = local if server.socket_file == local_socket else foreign
        return reaper._PaneSnapshot(None if panes is None else [
            (pane, "pm-tag", f"podman exec -it {CID} sh") for pane in panes])

    monkeypatch.setattr(reaper, "_query_server", snapshot)
    monkeypatch.setattr(cm, "current_container_id", lambda _: CID)
    remove = MagicMock(return_value=True)
    monkeypatch.setattr(cm, "remove_container", remove)
    monkeypatch.setattr(push_proxy, "stop_push_proxy", MagicMock())
    assert cm.discard_unowned_container(
        NAME, container_id=CID, generation="", allowed_owner_panes={"%0"}) is removed
    assert remove.called is removed
    assert bool(reaper.pending_releases()) is removed


@pytest.mark.parametrize("source", ["explicit", "tmux", "default"])
def test_same_server_socket_alias_allows_concretizer(monkeypatch, tmp_path, source):
    socket = tmp_path / "tmux-1000" / "default"
    socket.parent.mkdir()
    socket.touch()
    alias = tmp_path / "alias.sock"
    alias.symlink_to(socket)
    monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("TMUX_TMPDIR", str(tmp_path))
    monkeypatch.setattr(reaper.os, "getuid", lambda: 1000)
    if source == "explicit":
        monkeypatch.setenv("PM_TMUX_SOCKET", str(alias))
    elif source == "tmux":
        monkeypatch.setenv("TMUX", f"{alias},123,0")
    info = reaper.ContainerInfo(NAME, id=CID, labels={cm.LABEL_TMUX_SOCKET: str(socket)})
    monkeypatch.setattr(reaper, "_inspect", lambda *a, **kw: [info])
    monkeypatch.setattr(reaper, "_query_server", lambda server: reaper._PaneSnapshot([
        ("%0", "pm-tag", f"podman exec -it {CID} sh")]
        if reaper.os.path.realpath(server.socket_file) == str(socket) else []))
    monkeypatch.setattr(cm, "current_container_id", lambda _: CID)
    monkeypatch.setattr(cm, "remove_container", MagicMock(return_value=True))
    assert cm.discard_unowned_container(
        NAME, container_id=CID, generation="", allowed_owner_panes={"%0"})
