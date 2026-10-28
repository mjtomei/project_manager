"""A restart's lease protects the allocation from cleanup, not from its relaunch.

QA S38: ``pm container restart`` on a pre-marker container printed "the next
launch finishes that step in place", but running that launch right away was
refused for LAUNCH_GRACE as "still owned by an attaching launch" — no launch
was attaching; the lease was the restart's own.
"""
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from pm_core import container as cm, container_reaper as reaper

NAME = "pm-repo-tag-impl-pr-c"
CID = "allocation-id"


@pytest.fixture
def restarted(monkeypatch):
    monkeypatch.setattr(cm, "current_container_id", lambda name: CID)
    boot = json.dumps("2026-10-27T19:40:30.000000001Z")
    monkeypatch.setattr(cm, "_run_runtime", lambda *args, **kw: subprocess.CompletedProcess(
        args, 0, boot if args[0] == "inspect" else "", ""))
    monkeypatch.setattr(cm, "_wait_for_setup", lambda *a, **kw: None)
    monkeypatch.setattr(cm, "_setup_complete", lambda cid: True)
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a, **kw: [])
    monkeypatch.setattr(reaper, "is_retained", lambda *a, **kw: False)
    cm.restart_container(NAME)


def test_restart_lease_still_keeps_cleanup_away(restarted):
    assert cm.recent_launch(NAME, reaper.LAUNCH_GRACE, CID)
    assert cm.restart_lease_only(NAME, reaper.LAUNCH_GRACE, CID)


def test_next_launch_adopts_restarted_allocation(restarted, monkeypatch):
    monkeypatch.setattr(cm, "_ensure_reusable", Mock(return_value=CID))
    renew = Mock(wraps=cm._renew_launch)
    monkeypatch.setattr(cm, "_renew_launch", renew)
    assert cm.create_container(NAME, cm.ContainerConfig(), Path("/work")) == CID
    renew.assert_called_once_with(NAME, CID)
    # That launch now owns an ordinary lease, which a competitor must respect.
    assert not cm.restart_lease_only(NAME, reaper.LAUNCH_GRACE, CID)
    with pytest.raises(cm.ContainerError, match="attaching"):
        cm.create_container(NAME, cm.ContainerConfig(), Path("/work"))


def test_launch_lease_on_identity_is_not_a_restart_lease(restarted):
    # A launch that reused the allocation under another name renewed only the
    # rename-stable identity lease; the restart-tagged name lease must not
    # override it.
    cm._write_identity_generation(CID, "launch-generation")
    assert not cm.restart_lease_only(NAME, reaper.LAUNCH_GRACE, CID)


def test_no_lease_is_not_a_restart_lease():
    assert not cm.restart_lease_only(NAME, reaper.LAUNCH_GRACE, CID)


def test_repeat_restart_is_not_awaiting_attachment(restarted, monkeypatch):
    from click.testing import CliRunner
    from pm_core.cli import cli
    monkeypatch.setattr(cm, "pids_usage", lambda: {NAME: (5, 0)})
    restart = Mock()
    monkeypatch.setattr(cm, "restart_container", restart)
    result = CliRunner().invoke(cli, ["container", "restart", NAME])
    assert result.exit_code == 0, result.output
    assert "awaiting attachment" not in result.output
    restart.assert_called_once_with(NAME, container_id=CID)
