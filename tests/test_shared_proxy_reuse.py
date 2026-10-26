"""Shared reuse verifies the mounted proxy rather than a healthy unrelated path."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from pm_core import container as cm, push_proxy as pp


@pytest.mark.parametrize("case", ["matching", "missing", "other-mount", "other-owner", "inspect-failed"])
def test_shared_reuse_checks_authoritative_mount(tmp_path, monkeypatch, case):
    name = "pm-tag-impl-pr-aaaa"
    socket_dir = tmp_path / "shared"
    labels = {cm.LABEL_MANAGED: "1", cm.LABEL_SESSION: "tag", cm.LABEL_PR: "pr-aaaa"}
    if case == "other-owner":
        labels[cm.LABEL_PR] = "pr-bbbb"
    source = str(tmp_path / "other") if case == "other-mount" else str(socket_dir)
    row = {"Name": name, "Config": {"Labels": labels}, "Mounts": [] if case == "missing" else [
        {"Source": source, "Destination": pp._CONTAINER_SOCKET_DIR}]}
    monkeypatch.setattr(cm, "container_is_running", lambda n: True)
    monkeypatch.setattr(cm, "current_container_id", lambda n: "cid")
    monkeypatch.setattr(cm, "_probe_setup", lambda n: (True, "", ""))
    monkeypatch.setattr(cm, "_run_runtime", Mock(return_value=Mock(
        returncode=1 if case == "inspect-failed" else 0,
        stdout=json.dumps([row]), stderr="inspection failed")))
    monkeypatch.setattr(pp, "_shared_sock_dir_path", lambda *a: str(socket_dir))
    start = Mock(return_value=str(socket_dir / "push.sock"))
    monkeypatch.setattr(pp, "start_push_proxy", start)
    monkeypatch.setattr(pp, "proxy_is_alive", lambda p: True)
    if case == "matching":
        assert cm._ensure_reusable(name, Path("/work"), "branch",
                                   session_tag="tag", pr_id="pr-aaaa") == "cid"
        start.assert_called_once()
    else:
        with pytest.raises(cm.ContainerError, match="mounted push proxy"):
            cm._ensure_reusable(name, Path("/work"), "branch", session_tag="tag", pr_id="pr-aaaa")
        start.assert_not_called()
