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
    _seed_run(tmp_path, overall="")

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_not_called()
    on_complete.assert_not_called()
    # Recorded so it isn't rechecked every tick.
    assert "pr-001" in app._resumed_qa_pr_ids


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
