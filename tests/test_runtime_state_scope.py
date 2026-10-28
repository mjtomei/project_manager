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


def _write_legacy(home, pr_id, actions):
    import json
    shared = home / ".pm" / "runtime"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / f"{pr_id}.json").write_text(
        json.dumps({"pr_id": pr_id, "actions": actions}))


def test_upgrade_keeps_a_hold_verdict_recorded_at_the_shared_path(
        home, monkeypatch):
    """Records an older pm wrote at ~/.pm/runtime/<pr>.json: a QA hold
    verdict must survive the move to per-session directories, or auto-start
    relaunches QA on a PR waiting for a human.  In-flight entries belong to
    the older pm's processes and are not carried."""
    _write_legacy(home, "pr-p", {
        "qa": {"state": "done", "verdict": "INPUT_REQUIRED",
               "updated_at": "2026-10-27T10:00:00+00:00",
               "suppress_switch": True},
        "review-loop": {"state": "running"},
    })
    _write_legacy(home, "pr-q", {"start": {"state": "running"}})
    _as(monkeypatch, "pm-A-1111")
    assert auto_start.recorded_qa_verdict("pr-p") == "INPUT_REQUIRED"
    assert rs.get_action_state("pr-p", "review-loop") == {}
    assert not rs.get_action_state("pr-p", "qa").get("suppress_switch")
    assert not rs.runtime_path("pr-q").exists()
    # The shared record is left as it was, and no seed directory remains.
    shared = home / ".pm" / "runtime"
    assert '"running"' in (shared / "pr-p.json").read_text()
    assert sorted(p.name for p in shared.iterdir()) == [
        "pm-A-1111", "pr-p.json", "pr-q.json"]


def test_shared_path_is_copied_once_per_session(home, monkeypatch):
    """After the copy, an older pm (another clone) writing the shared path
    does not leak into this session's records."""
    _write_legacy(home, "pr-p", {"qa": {"state": "done", "verdict": "PASS"}})
    _as(monkeypatch, "pm-A-1111")
    rs.set_action_state("pr-p", "qa", "done", verdict="INPUT_REQUIRED")
    _write_legacy(home, "pr-p", {"qa": {"state": "done", "verdict": "PASS"}})
    _write_legacy(home, "pr-new", {"qa": {"state": "done", "verdict": "PASS"}})
    assert auto_start.recorded_qa_verdict("pr-p") == "INPUT_REQUIRED"
    assert auto_start.recorded_qa_verdict("pr-new") is None


def test_session_created_concurrently_is_left_as_it_is(home, monkeypatch):
    """Another process of the session created the directory between the
    check and the copy: its records stand and no seed directory is left."""
    _write_legacy(home, "pr-p", {"qa": {"state": "done", "verdict": "PASS"}})
    shared = home / ".pm" / "runtime"
    d = shared / "pm-A-1111"
    d.mkdir()
    (d / "pr-p.json").write_text('{"pr_id": "pr-p", "actions": {}}')
    rs._seed_session_dir(shared, d)
    assert (d / "pr-p.json").read_text() == '{"pr_id": "pr-p", "actions": {}}'
    assert sorted(p.name for p in shared.iterdir()) == ["pm-A-1111", "pr-p.json"]


def test_live_pm_qa_run_shows_working_over_the_last_full_runs_verdict(
        home, monkeypatch):
    """S125: ``pm qa run`` never writes the PR's qa entry, so while it ran
    the picker kept the last full run's ``[done PASS]``.  Its verdict is
    still never the PR's: once it exits, the full run's badge is back."""
    import json
    import subprocess
    from pm_core import qa_loop
    from pm_core.cli.session import _format_action_status
    _as(monkeypatch, "pm-A-1111")
    monkeypatch.setattr(qa_loop, "get_pm_session", lambda: "pm-A-1111")
    rs.set_action_state("pr-p", "qa", "done", verdict="PASS")
    wd = home / ".pm" / "workdirs" / "qa" / "pr-p-cli-pr-p"
    wd.mkdir(parents=True)
    child = subprocess.Popen(["sleep", "30"])
    try:
        (wd / "qa_run.json").write_text(json.dumps({
            "pr_id": "pr-p", "loop_id": "cli-pr-p", "session_tag": "A-1111",
            "started_at": 1.0, "owner_pid": child.pid,
            "owner_start": qa_loop._proc_start_time(child.pid)}))
        assert _format_action_status("pr-p", "qa") == " [working]"
        # The recorded entry is untouched: auto-start still reads the PASS.
        assert auto_start.recorded_qa_verdict("pr-p") == "PASS"
    finally:
        child.kill()
        child.wait()
    assert _format_action_status("pr-p", "qa") == " [done PASS]"
