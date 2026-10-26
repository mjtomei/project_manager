"""A launch's attachment lease ends once its worker pane has attached.

QA20: ``pm pr review A --fresh`` within LAUNCH_GRACE of the previous launch
killed the live review window, then refused to reuse or replace its
allocation as "still owned by an attaching launch" — the predecessor that had
attached long ago.  The user lost the worker and got no replacement.
"""
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from pm_core import container as cm, container_reaper as reaper

NAME = "pm-repo-tag-review-pr-a"
CID = "allocation-id"


@pytest.fixture
def launched(monkeypatch):
    monkeypatch.setattr(cm, "current_container_id", lambda name: CID)
    cm._renew_launch(NAME, CID)
    monkeypatch.setattr(reaper, "_owner_panes", lambda *a, **kw: ([], False))
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a, **kw: [])
    monkeypatch.setattr(reaper, "is_retained", lambda *a, **kw: False)
    return cm.cleanup_generation(NAME)


def _attach(generation, monkeypatch):
    monkeypatch.setattr(cm.subprocess, "call", Mock(return_value=0))
    assert cm.run_interactive_exec(NAME, CID, generation, str(cm.container_state_dir()),
                                   "worker", "podman", "0") == 0


def test_attached_launch_no_longer_holds_lease(launched, monkeypatch):
    assert cm.recent_launch(NAME, reaper.LAUNCH_GRACE)
    _attach(launched, monkeypatch)
    assert not cm.recent_launch(NAME, reaper.LAUNCH_GRACE)
    assert not cm.recent_launch(NAME, reaper.LAUNCH_GRACE, CID)
    # The generation itself is unchanged: old EXIT releases stay valid.
    assert cm.cleanup_generation(NAME) == launched


def test_fresh_relaunch_discards_attached_predecessor(launched, monkeypatch):
    _attach(launched, monkeypatch)
    # The window was killed (--fresh); no pane owns the allocation any more.
    remove = Mock(return_value=True)
    monkeypatch.setattr(cm, "remove_container", remove)
    assert cm.discard_unowned_container(NAME)
    remove.assert_called_once_with(CID)


def test_fresh_relaunch_creates_after_attached_predecessor(launched, monkeypatch):
    _attach(launched, monkeypatch)
    monkeypatch.setattr(cm, "_ensure_reusable", Mock(return_value=CID))
    renew = Mock()
    monkeypatch.setattr(cm, "_renew_launch", renew)
    assert cm.create_container(NAME, cm.ContainerConfig(), Path("/work")) == CID
    renew.assert_called_once_with(NAME, CID)


def test_unattached_launch_keeps_lease(launched, monkeypatch):
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    assert not cm.discard_unowned_container(NAME)
    with pytest.raises(cm.ContainerError, match="attaching"):
        cm.create_container(NAME, cm.ContainerConfig(), Path("/work"))
    remove.assert_not_called()


def test_stale_attach_does_not_end_newer_lease(launched, monkeypatch):
    cm._renew_launch(NAME, CID)  # a newer launch now owns the allocation
    monkeypatch.setattr(cm.subprocess, "call", Mock(return_value=0))
    with pytest.raises(cm.ContainerError):
        cm.run_interactive_exec(NAME, CID, launched, str(cm.container_state_dir()),
                                "worker", "podman", "0")
    assert cm.recent_launch(NAME, reaper.LAUNCH_GRACE, CID)
    assert time.time() - cm._restart_generation_path(NAME).stat().st_mtime < 5
