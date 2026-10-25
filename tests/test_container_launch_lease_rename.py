"""Attachment leases follow allocations across runtime renames."""
import os
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from pm_core import container as cm, container_reaper as reaper
from pm_core.cli import cli


OLD = "pm-qa-debug-original"
NEW = "pm-qa-debug-renamed"
CID = "allocation-id"


@pytest.fixture
def renamed(monkeypatch):
    cm._renew_launch(OLD, CID)
    monkeypatch.setattr(cm, "current_container_id", lambda name: CID)
    monkeypatch.setattr(reaper, "_owner_panes", lambda *a, **kw: ([], False))
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a, **kw: [])
    return reaper.ContainerInfo(name=NEW, id=CID, created=time.time() - 1000)


def test_renamed_reuse_preserves_attaching_owner(renamed, monkeypatch):
    recover = Mock(return_value=CID)
    monkeypatch.setattr(cm, "_ensure_reusable", recover)
    with pytest.raises(cm.ContainerError, match="attaching"):
        cm.create_container(NEW, cm.ContainerConfig(), Path("/work"))
    recover.assert_not_called()


def test_reaper_plan_keeps_renamed_attachment(renamed):
    decision = reaper._decide(renamed, reaper.Scope(), reaper._PaneCache(),
                              reaper._PrStatus(), time.time())
    assert decision.action == "keep"
    assert "launching" in decision.reason


def test_reaper_final_check_keeps_renamed_attachment(renamed, monkeypatch):
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    removed, reason = reaper._remove_checked(
        reaper.Decision(renamed, "remove", "no owner"), reaper.Scope())
    assert not removed
    assert "attaching" in reason
    remove.assert_not_called()


def test_preflight_keeps_renamed_attachment(renamed, monkeypatch):
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    assert not cm.discard_unowned_container(NEW)
    remove.assert_not_called()


def test_restart_keeps_renamed_attachment(renamed, monkeypatch):
    monkeypatch.setattr(cm, "canonical_container_name", lambda name: NEW)
    monkeypatch.setattr(cm, "pids_usage", lambda: {})
    restart = Mock()
    monkeypatch.setattr(cm, "restart_container", restart)
    result = CliRunner().invoke(cli, ["container", "restart", NEW])
    assert result.exit_code == 1, result.output
    assert "awaiting attachment" in result.output
    restart.assert_not_called()


def test_expired_identity_lease_allows_reap(renamed, monkeypatch):
    expired = time.time() - 1000
    os.utime(cm._identity_generation_path(CID), (expired, expired))
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    removed, _ = reaper._remove_checked(
        reaper.Decision(renamed, "remove", "no owner"), reaper.Scope())
    assert removed
    remove.assert_called_once_with(NEW)


def test_identity_lease_does_not_cross_runtime_domains(renamed, monkeypatch):
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: {"runtime": "test", "id": "other"})
    assert not cm.recent_launch(NEW, reaper.LAUNCH_GRACE, CID)


def test_unknown_identity_lease_defers_reap(renamed, monkeypatch):
    monkeypatch.setattr(cm, "_identity_generation_path", Mock(side_effect=PermissionError("unreadable")))
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    removed, reason = reaper._remove_checked(
        reaper.Decision(renamed, "remove", "no owner"), reaper.Scope())
    assert not removed
    assert "unknown" in reason
    remove.assert_not_called()
