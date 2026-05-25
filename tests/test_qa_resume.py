"""Tests for QA verdict-collection restart survival (pr-4a89e52).

The QA orchestration loop (run_qa_sync / _poll_tmux_verdicts) runs in a
daemon thread inside the TUI process.  A TUI restart kills that thread, so
verdict collection, the overall verdict, and the lifecycle transition are
lost even though the scenario tmux windows keep running.

The fix persists a ``qa_resume.json`` snapshot per run and, on the next
poll tick, the TUI either re-spawns the orchestration loop (incomplete
runs) or processes the completion (runs that finished during downtime).

Covers:
  - resume snapshot round-trip (_write_resume_file / _load_resume_file /
    build_resume_state) including scenario runtime fields, verdicts,
    reasons, verified set, and finalize verdict
  - clear_resume_file removal
  - _resume_incomplete_qa: incomplete → re-spawn; completed → process +
    clear; skip non-qa PRs; skip already-tracked/recovered PRs
  - poll_qa_state clears the snapshot once completion is processed
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from pm_core import qa_loop
from pm_core.qa_loop import (
    QAScenario,
    QALoopState,
    VERDICT_PASS,
    VERDICT_NEEDS_WORK,
    _write_resume_file,
    _load_resume_file,
    build_resume_state,
    clear_resume_file,
    _resume_file_path,
)
from pm_core import store
from pm_core.tui import qa_loop_ui


# ---------------------------------------------------------------------------
# Round-trip serialization
# ---------------------------------------------------------------------------

def _make_state(qa_workdir) -> QALoopState:
    state = QALoopState(pr_id="pr-001")
    state.loop_id = "abc123"
    state.qa_workdir = str(qa_workdir)
    state.session_tag = "project_manager-deadbeef"
    state.planning_phase = False
    state.scenarios = [
        QAScenario(
            index=1, title="Login flow", focus="auth",
            steps="do the thing",
            window_name="qa-pr1-s1", pane_id="%5",
            worktree_path="/wd/worktree-1",
            transcript_path="/wd/transcript-s1.jsonl",
            session_id="sess-1",
            concretize_session_id="csess-1",
            verifier_pane_id="%9", verifier_session_id="vsess-1",
            verifier_transcript="/wd/verify-1.jsonl",
            verifier_cwd="/wd/worktree-1",
        ),
        QAScenario(
            index=2, title="Logout flow", focus="auth",
            window_name="qa-pr1-s2", pane_id="%6",
            transcript_path="/wd/transcript-s2.jsonl",
            session_id="sess-2",
        ),
    ]
    state.scenario_0 = QAScenario(
        index=0, title="Interactive", focus="", window_name="qa-pr1-s0",
    )
    state.scenario_verdicts = {1: VERDICT_PASS}
    state.scenario_verdict_reasons = {1: "looks good"}
    state.verified_scenarios = {1}
    state.finalize_verdict = "FINALIZE_DONE"
    return state


def test_resume_roundtrip(tmp_path):
    state = _make_state(tmp_path)
    _write_resume_file(state, use_containers=True, concurrency_cap=2,
                       queued_indices={2})

    assert _resume_file_path(tmp_path).is_file()
    loaded = _load_resume_file(tmp_path)
    assert loaded is not None
    assert loaded["pr_id"] == "pr-001"
    assert loaded["use_containers"] is True
    assert loaded["concurrency_cap"] == 2
    assert loaded["queued_indices"] == [2]

    rebuilt = build_resume_state(loaded)
    assert rebuilt.pr_id == "pr-001"
    assert rebuilt.loop_id == "abc123"
    assert rebuilt.qa_workdir == str(tmp_path)
    assert rebuilt.session_tag == "project_manager-deadbeef"
    assert rebuilt.planning_phase is False
    assert rebuilt.finalize_verdict == "FINALIZE_DONE"
    assert rebuilt.verified_scenarios == {1}
    assert rebuilt.scenario_verdicts == {1: VERDICT_PASS}
    assert rebuilt.scenario_verdict_reasons == {1: "looks good"}

    # Scenario runtime fields the orchestration loop depends on survive.
    s1 = next(s for s in rebuilt.scenarios if s.index == 1)
    assert s1.session_id == "sess-1"
    assert s1.transcript_path == "/wd/transcript-s1.jsonl"
    assert s1.pane_id == "%5"
    assert s1.worktree_path == "/wd/worktree-1"
    assert s1.verifier_session_id == "vsess-1"
    assert s1.verifier_pane_id == "%9"

    assert rebuilt.scenario_0 is not None
    assert rebuilt.scenario_0.index == 0
    assert rebuilt.scenario_0.window_name == "qa-pr1-s0"


def test_write_resume_file_noop_without_workdir():
    state = QALoopState(pr_id="pr-x")
    state.qa_workdir = None
    # Should not raise.
    _write_resume_file(state, use_containers=False, concurrency_cap=0)


def test_clear_resume_file(tmp_path):
    state = _make_state(tmp_path)
    _write_resume_file(state, use_containers=False, concurrency_cap=0)
    assert _resume_file_path(tmp_path).is_file()
    clear_resume_file(tmp_path)
    assert not _resume_file_path(tmp_path).exists()
    # Idempotent.
    clear_resume_file(tmp_path)


def test_load_resume_file_missing(tmp_path):
    assert _load_resume_file(tmp_path) is None


# ---------------------------------------------------------------------------
# _resume_incomplete_qa
# ---------------------------------------------------------------------------

def _make_app(tmp_path, *, pr_status="qa"):
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir(exist_ok=True)
    data = {
        "project": {"name": "test", "repo": "/tmp/r", "base_branch": "master"},
        "prs": [{"id": "pr-001", "title": "T", "branch": "b",
                 "status": pr_status, "workdir": str(tmp_path / "wd"),
                 "notes": []}],
    }
    store.save(data, pm_dir)

    app = MagicMock()
    app._root = pm_dir
    app._qa_loops = {}
    app._resumed_qa_pr_ids = set()
    return app


def _seed_run(home, *, overall="", pr_id="pr-001"):
    """Create a qa workdir under <home>/.pm/workdirs/qa with resume+status."""
    qa_dir = home / ".pm" / "workdirs" / "qa" / f"{pr_id}-loop1"
    qa_dir.mkdir(parents=True, exist_ok=True)
    state = _make_state(qa_dir)
    state.pr_id = pr_id
    # Incomplete by default: clear verdicts so it has pending work.
    state.scenario_verdicts = {}
    state.verified_scenarios = set()
    _write_resume_file(state, use_containers=False, concurrency_cap=0)
    status = {
        "pr_id": pr_id,
        "scenarios": [{"index": 1, "title": "Login flow", "verdict": "",
                       "window_name": "qa-pr1-s1"}],
        "overall": overall,
        "error": "",
    }
    (qa_dir / "qa_status.json").write_text(json.dumps(status))
    return qa_dir


def test_resume_incomplete_respawns_loop(tmp_path):
    app = _make_app(tmp_path)
    qa_dir = _seed_run(tmp_path, overall="")

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)

    # Re-spawned, tracked, NOT completed, snapshot kept for the resumed run.
    resume_bg.assert_called_once()
    on_complete.assert_not_called()
    assert "pr-001" in app._qa_loops
    assert "pr-001" in app._resumed_qa_pr_ids
    assert _resume_file_path(qa_dir).is_file()


def test_resume_completed_processes_and_clears(tmp_path):
    app = _make_app(tmp_path)
    qa_dir = _seed_run(tmp_path, overall=VERDICT_NEEDS_WORK)

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)

    # Completed during downtime: processed via _on_qa_complete, snapshot
    # removed, NOT re-spawned, NOT left in _qa_loops.
    resume_bg.assert_not_called()
    on_complete.assert_called_once()
    completed_state = on_complete.call_args[0][1]
    assert completed_state.latest_verdict == VERDICT_NEEDS_WORK
    assert "pr-001" not in app._qa_loops
    assert "pr-001" in app._resumed_qa_pr_ids
    assert not _resume_file_path(qa_dir).exists()


def test_resume_skips_non_qa_pr(tmp_path):
    app = _make_app(tmp_path, pr_status="merged")
    qa_dir = _seed_run(tmp_path, overall="")

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_not_called()
    on_complete.assert_not_called()
    # Recorded so it isn't rechecked every tick.
    assert "pr-001" in app._resumed_qa_pr_ids
    # The PR left QA, so its stale snapshot is dropped from disk.
    assert not _resume_file_path(qa_dir).exists()


def test_resume_skips_already_tracked(tmp_path):
    app = _make_app(tmp_path)
    app._qa_loops["pr-001"] = QALoopState(pr_id="pr-001")
    _seed_run(tmp_path, overall="")

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_not_called()
    on_complete.assert_not_called()


def test_resume_skips_already_recovered(tmp_path):
    app = _make_app(tmp_path)
    app._resumed_qa_pr_ids.add("pr-001")
    _seed_run(tmp_path, overall="")

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_not_called()
    on_complete.assert_not_called()


def test_resume_noop_when_no_qa_root(tmp_path):
    app = _make_app(tmp_path)
    # No qa workdirs created at all.
    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg:
        qa_loop_ui._resume_incomplete_qa(app)
    resume_bg.assert_not_called()


# ---------------------------------------------------------------------------
# poll_qa_state clears the snapshot on in-memory completion
# ---------------------------------------------------------------------------

def test_poll_qa_state_clears_snapshot_on_completion(tmp_path):
    app = _make_app(tmp_path)
    app._pane_idle_tracker = MagicMock()

    qa_dir = tmp_path / "qa-run"
    qa_dir.mkdir()
    state = _make_state(qa_dir)
    state.running = False
    state.latest_verdict = VERDICT_PASS
    state._ui_complete_notified = True  # second-cycle: ready to be dropped
    _write_resume_file(state, use_containers=False, concurrency_cap=0)
    app._qa_loops["pr-001"] = state

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop_ui, "_on_qa_complete"), \
         patch.object(qa_loop_ui, "_resume_incomplete_qa"):
        qa_loop_ui.poll_qa_state(app)

    assert "pr-001" not in app._qa_loops
    assert not _resume_file_path(qa_dir).exists()


def test_poll_qa_state_clears_snapshot_on_first_completion_tick(tmp_path):
    """The snapshot is dropped as soon as the completion is first processed
    (tick 1), not deferred to the tick-2 cleanup.

    A PASS with auto-start off leaves the PR in ``qa`` and keeps the loop
    in ``_qa_loops`` for one more cycle.  If the snapshot survived that
    one-tick gap, a TUI restart could let ``_resume_incomplete_qa`` re-run
    ``_on_qa_complete`` and record a duplicate QA note.  Clearing on the
    first tick closes that window."""
    app = _make_app(tmp_path)
    app._pane_idle_tracker = MagicMock()

    qa_dir = tmp_path / "qa-run"
    qa_dir.mkdir()
    state = _make_state(qa_dir)
    state.running = False
    state.latest_verdict = VERDICT_PASS
    state._ui_complete_notified = False  # first cycle
    _write_resume_file(state, use_containers=False, concurrency_cap=0)
    app._qa_loops["pr-001"] = state

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop_ui, "_on_qa_complete"), \
         patch.object(qa_loop_ui, "_resume_incomplete_qa"):
        qa_loop_ui.poll_qa_state(app)

    # Loop is kept for one more cycle, but the snapshot is already gone so
    # a restart in this gap cannot re-process the run.
    assert "pr-001" in app._qa_loops
    assert state._ui_complete_notified is True
    assert not _resume_file_path(qa_dir).exists()


def test_poll_qa_state_throttles_resume_scan(tmp_path):
    """The orphan-recovery disk scan is throttled to ~every 5 poll ticks
    (it would otherwise stat every historical QA workdir each second)."""
    app = _make_app(tmp_path)
    app._pane_idle_tracker = MagicMock()
    app._qa_loops = {}
    # Start from a clean integer counter (MagicMock default would break the
    # modulo), mirroring the real App where the attr is unset → getattr → 0.
    app._qa_resume_poll_counter = 0

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop_ui, "_resume_incomplete_qa") as resume_scan:
        for _ in range(10):
            qa_loop_ui.poll_qa_state(app)

    # Ticks 0 and 5 trigger the scan; the other 8 are skipped.
    assert resume_scan.call_count == 2


# ---------------------------------------------------------------------------
# Resumed runs trust prior verification (don't re-spawn verifier sessions)
# ---------------------------------------------------------------------------

def test_resumed_pass_skips_reverification(tmp_path):
    """A PASS already in verified_scenarios (restored from the snapshot)
    must not be re-verified when the resumed poll loop re-reads it — the
    persisted verified set exists precisely to avoid that rework."""
    from pm_core.qa_loop import _poll_tmux_verdicts

    scenario = QAScenario(index=1, title="Test", focus="t",
                          window_name="qa-test-s1", pane_id="%1",
                          transcript_path="/tmp/t.jsonl",
                          session_id="sid-verified-1")
    state = QALoopState(pr_id="pr-001")
    state.qa_workdir = None  # skip snapshot writes inside the loop
    state.scenarios = [scenario]
    state.scenario_verdicts = {1: VERDICT_PASS}
    state.verified_scenarios = {1}  # restored from a prior run

    fake_event = {"event_type": "idle_prompt",
                  "timestamp": 1e12, "session_id": scenario.session_id}
    status_path = tmp_path / "status.json"

    with patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
         patch("pm_core.qa_loop.time.sleep"), \
         patch("pm_core.qa_loop.time.monotonic", side_effect=[0, 100]), \
         patch("pm_core.hook_events.read_event", return_value=fake_event), \
         patch("pm_core.qa_loop.extract_verdict_from_transcript",
               return_value="PASS"), \
         patch("pm_core.tmux.pane_exists", return_value=True), \
         patch("pm_core.qa_loop._is_verification_enabled", return_value=True), \
         patch("pm_core.qa_loop._verify_single_scenario") as mock_verify:
        _poll_tmux_verdicts(
            state, {}, {}, "sess", "/tmp/work", status_path, lambda *a: None,
        )

    mock_verify.assert_not_called()
    # latest_output is set synchronously in the main loop: the "verifying"
    # phrase only appears when a verifier thread is spawned, so this catches
    # the regression deterministically (no dependency on thread timing).
    assert "verifying" not in state.latest_output
    assert state.scenario_verdicts[1] == VERDICT_PASS
    assert 1 in state.verified_scenarios


# ---------------------------------------------------------------------------
# Last scenario's verdict survives a restart (pr-3d1fa55 QA follow-up)
# ---------------------------------------------------------------------------

def test_last_verdict_is_persisted_before_loop_exits(tmp_path):
    """The resume snapshot must include the *last* scenario's verdict.

    The snapshot was previously written only at the top of each poll
    iteration, so the verdict recorded in the final iteration — which
    empties pending/verifying and exits the loop before the next
    top-of-loop write — never made it to qa_resume.json.  A TUI restart
    at that moment rebuilt state from the stale snapshot and the verdict
    was lost (observed as a scenario losing its NEEDS_WORK after a
    restart).  The loop must persist the snapshot on every verdict change.
    """
    from pm_core.qa_loop import _poll_tmux_verdicts

    scenario = QAScenario(index=1, title="Concurrent finalize", focus="t",
                          window_name="qa-test-s1", pane_id="%1",
                          transcript_path="/tmp/t.jsonl",
                          session_id="sid-needs-work-1")
    state = QALoopState(pr_id="pr-001")
    state.qa_workdir = str(tmp_path)  # snapshot writes land here
    state.scenarios = [scenario]

    fake_event = {"event_type": "idle_prompt",
                  "timestamp": 1e12, "session_id": scenario.session_id}
    status_path = tmp_path / "status.json"

    with patch("pm_core.qa_loop._get_scenario_pane", return_value="%1"), \
         patch("pm_core.qa_loop.time.sleep"), \
         patch("pm_core.qa_loop.time.monotonic", side_effect=[0] + [1000] * 20), \
         patch("pm_core.hook_events.read_event", return_value=fake_event), \
         patch("pm_core.qa_loop.extract_verdict_from_transcript",
               return_value="NEEDS_WORK"), \
         patch("pm_core.tmux.pane_exists", return_value=True):
        _poll_tmux_verdicts(
            state, {}, {}, "sess", str(tmp_path), status_path, lambda *a: None,
        )

    assert state.scenario_verdicts[1] == VERDICT_NEEDS_WORK

    # The on-disk snapshot — the only thing a restart sees — must already
    # carry the final verdict.
    resume = _load_resume_file(tmp_path)
    assert resume is not None
    assert resume["scenario_verdicts"].get("1") == VERDICT_NEEDS_WORK

    # And a state rebuilt from that snapshot (as the TUI does on restart)
    # preserves the verdict.
    rebuilt = build_resume_state(resume)
    assert rebuilt.scenario_verdicts.get(1) == VERDICT_NEEDS_WORK
