"""~/.pm/runtime is per pm session: two clones of a project share ~/.pm and
their PR ids, but each clone's recorded actions are its own (S93)."""

import pytest

from pm_core import runtime_state as rs
from pm_core.tui import auto_start

# conftest replaces _runtime_dir per test; keep the real one for these tests.
_REAL_RUNTIME_DIR = rs._runtime_dir


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(rs, "_runtime_dir", _REAL_RUNTIME_DIR)
    return tmp_path


def _as(monkeypatch, session):
    monkeypatch.setattr(rs, "_session_scope", session)


def test_another_clones_qa_run_neither_hides_nor_replaces_this_clones_verdict(
        home, monkeypatch):
    """S93 story 2: clone B's qa-run-bg of P wrote ``running`` and then
    ``done``/PASS over clone A's INPUT_REQUIRED record.  A's auto-start then
    relaunched QA (no hold verdict) and handed P to sign-off on B's PASS."""
    _as(monkeypatch, "pm-A-1111")
    rs.set_action_state("pr-p", "qa", "done", verdict="INPUT_REQUIRED")
    _as(monkeypatch, "pm-B-2222")
    rs.set_action_state("pr-p", "qa", "running")
    assert rs.get_action_state("pr-p", "qa")["state"] == "running"
    rs.set_action_state("pr-p", "qa", "done", verdict="PASS")

    _as(monkeypatch, "pm-A-1111")
    assert auto_start.recorded_qa_verdict("pr-p") == "INPUT_REQUIRED"
    assert rs.derive_action_status("pr-p", "qa")["verdict"] == "INPUT_REQUIRED"
    assert rs.runtime_path("pr-p") == home / ".pm" / "runtime" / "pm-A-1111" / "pr-p.json"


def test_tui_mount_sweep_keeps_another_clones_live_entries(home, monkeypatch):
    _as(monkeypatch, "pm-B-2222")
    rs.set_action_state("pr-p", "qa", "running")
    _as(monkeypatch, "pm-A-1111")
    rs.set_action_state("pr-p", "qa", "running")
    assert rs.sweep_stale_states("tui-mount", pr_ids={"pr-p"}) == 1
    _as(monkeypatch, "pm-B-2222")
    assert rs.get_action_state("pr-p", "qa")["state"] == "running"


def test_outside_a_pm_session_the_shared_path_is_used(home, monkeypatch):
    _as(monkeypatch, None)
    rs.set_action_state("pr-p", "qa", "done", verdict="PASS")
    assert rs.runtime_path("pr-p") == home / ".pm" / "runtime" / "pr-p.json"
    assert rs.runtime_path("pr-p").exists()


def test_scope_is_this_processes_pm_session_resolved_once(home, monkeypatch):
    session = ["pm-A-1111"]
    monkeypatch.setattr("pm_core.cli.helpers._get_pm_session",
                        lambda: session[0])
    _as(monkeypatch, rs._UNSET)
    rs.set_action_state("pr-p", "qa", "running")
    session[0] = "pm-B-2222"
    rs.set_action_state("pr-p", "qa", "done", verdict="PASS")
    assert rs.runtime_path("pr-p") == home / ".pm" / "runtime" / "pm-A-1111" / "pr-p.json"
    assert rs.get_action_state("pr-p", "qa")["verdict"] == "PASS"
