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
from types import SimpleNamespace
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


class _InlineThread:
    """Runs the adopt-and-resume thread inline so tests can assert on it."""

    def __init__(self, target, args=(), **_kw):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


@pytest.fixture(autouse=True)
def _inline_adopt_thread():
    # Only qa_loop_ui's reference: the real threading module stays intact.
    with patch.object(qa_loop_ui, "threading",
                      SimpleNamespace(Thread=_InlineThread)):
        yield


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


def test_resume_skips_run_owned_by_live_process(tmp_path):
    """A run another live process drives (a `pm pr auto-sequence` QA child)
    is not orphaned: adopting it would start a second orchestration loop —
    duplicate verifier / finalize panes and a second completion.  Once that
    process is gone the run is recovered as before."""
    import subprocess
    app = _make_app(tmp_path)
    qa_dir = _seed_run(tmp_path, overall="")
    owner = subprocess.Popen(["sleep", "30"])
    try:
        rfile = _resume_file_path(qa_dir)
        data = json.loads(rfile.read_text())
        data["owner_pid"] = owner.pid
        data["owner_start"] = qa_loop._proc_start_time(owner.pid)
        rfile.write_text(json.dumps(data))

        with patch("pathlib.Path.home", return_value=tmp_path), \
             patch.object(qa_loop, "resume_qa_background") as resume_bg, \
             patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
            qa_loop_ui._resume_incomplete_qa(app)
        resume_bg.assert_not_called()
        on_complete.assert_not_called()
        assert "pr-001" not in app._qa_loops
        assert "pr-001" not in app._resumed_qa_pr_ids   # re-checked later
        assert rfile.is_file()
    finally:
        owner.kill()
        owner.wait()

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg:
        qa_loop_ui._resume_incomplete_qa(app)
    resume_bg.assert_called_once()
    assert "pr-001" in app._qa_loops


def test_owner_pid_reused_by_unrelated_process_is_not_owner():
    """The dead owner's pid now belongs to an unrelated process (different
    start time): the run is orphaned and must stay resumable."""
    import subprocess
    other = subprocess.Popen(["sleep", "30"])
    try:
        start = qa_loop._proc_start_time(other.pid)
        assert start
        live = {"owner_pid": other.pid, "owner_start": start}
        assert qa_loop.resume_owned_elsewhere(live)
        reused = {"owner_pid": other.pid, "owner_start": str(int(start) + 1)}
        assert not qa_loop.resume_owned_elsewhere(reused)
        # Snapshots written before owner_start existed: pid liveness only.
        assert qa_loop.resume_owned_elsewhere({"owner_pid": other.pid})
    finally:
        other.kill()
        other.wait()


def _run_cli_qa_driver(tmp_path, run_side_effect):
    """Invoke the detached ``pm pr qa-run-bg`` driver with run_qa_sync faked."""
    from click.testing import CliRunner
    from pm_core.cli.pr import pr_qa_run_bg
    data = store.load(tmp_path / "pm")
    with patch("pm_core.cli.pr.state_root", return_value=tmp_path / "pm"), \
         patch("pm_core.cli.pr.store.locked_update"), \
         patch("pm_core.qa_loop.run_qa_sync", side_effect=run_side_effect):
        return CliRunner().invoke(pr_qa_run_bg, ["pr-001"], obj=data)


def test_cli_driver_drops_snapshot_of_run_it_completed(tmp_path):
    """A run the `pm pr auto-sequence` QA child finished itself must not be
    "recovered" by the TUI once that child exits.  Live repro: a sign-off
    re-qa bounce retired the CLI's first QA run; its driver finished the run
    late and the TUI then logged "QA PASS for <pr> — press i to sign off"
    while the PR's new QA run was still going."""
    app = _make_app(tmp_path)          # PR is back in qa (re-qa bounce)
    qa_dir = tmp_path / ".pm" / "workdirs" / "qa" / "pr-001-old"
    qa_dir.mkdir(parents=True)

    def _completed_run(state, *a, **kw):
        state.qa_workdir = str(qa_dir)
        _write_resume_file(state, use_containers=False, concurrency_cap=0)
        state.latest_verdict = VERDICT_PASS
        state.running = False
        (qa_dir / "qa_status.json").write_text(json.dumps(
            {"pr_id": "pr-001", "scenarios": [], "overall": VERDICT_PASS,
             "error": ""}))

    result = _run_cli_qa_driver(tmp_path, _completed_run)
    assert result.exit_code == 0, result.output
    assert not _resume_file_path(qa_dir).exists()
    assert (qa_dir / "qa_status.json").is_file()   # CLI reads this itself

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)
    resume_bg.assert_not_called()
    on_complete.assert_not_called()


def test_cli_driver_keeps_snapshot_when_run_did_not_finish(tmp_path):
    """A CLI driver that dies mid-run leaves its snapshot so the TUI can
    still recover the run (R15: a dead CLI owner's run is not stranded)."""
    app = _make_app(tmp_path)
    qa_dir = tmp_path / ".pm" / "workdirs" / "qa" / "pr-001-dead"
    qa_dir.mkdir(parents=True)

    def _crashed_run(state, *a, **kw):
        state.qa_workdir = str(qa_dir)
        _write_resume_file(state, use_containers=False, concurrency_cap=0)
        raise RuntimeError("driver died mid-run")

    result = _run_cli_qa_driver(tmp_path, _crashed_run)
    assert result.exit_code == 1
    assert _resume_file_path(qa_dir).is_file()

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg:
        qa_loop_ui._resume_incomplete_qa(app)
    resume_bg.assert_called_once()


def test_resume_snapshot_records_owner_pid(tmp_path):
    import os
    state = _make_state(tmp_path)
    _write_resume_file(state, use_containers=False, concurrency_cap=0)
    loaded = _load_resume_file(tmp_path)
    assert loaded["owner_pid"] == os.getpid()
    assert loaded["owner_start"] == qa_loop._proc_start_time(os.getpid())
    # Our own pid (a TUI restart execs in place) is never "elsewhere".
    assert not qa_loop.resume_owned_elsewhere(loaded)


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


def test_resume_adopts_every_queued_entry_of_every_run(tmp_path):
    """A TUI restart (same PID, new launch-queue instance) must keep each
    resumed run's waiting entries -- all of them, with their ids and place
    in line -- even when two runs resume in the same TUI.  Adoption happens
    before any resumed loop starts, since a loop's first queue access cleans
    the pre-restart entries (QA S44, note-5eab8c7)."""
    from pm_core import launch_queue as lq

    app = _make_app(tmp_path)
    pm_dir = app._root
    data = store.load(pm_dir)
    data["prs"].append(dict(data["prs"][0], id="pr-002"))
    store.save(data, pm_dir)
    runs = {}
    for pr_id in ("pr-001", "pr-002"):
        qa_dir = _seed_run(tmp_path, pr_id=pr_id)
        state = build_resume_state(_load_resume_file(qa_dir))
        _write_resume_file(state, use_containers=True, concurrency_cap=4,
                           queued_indices={1, 2})
        runs[pr_id] = qa_loop._qa_run_key(state)

    lq_home = tmp_path / "lqhome"
    lq_home.mkdir()
    with patch("pm_core.launch_queue.pm_home", return_value=lq_home):
        for pr_id in ("pr-001", "pr-002"):
            run = runs[pr_id]
            lq.enqueue("qa_scenario", qa_run_id=run,
                       keys=[f"{run}:s1", f"{run}:s2"])
        q = lq._load_queue()
        for e in q["entries"]:
            e["instance"] = "pre-restart"
        lq._save_queue(q)
        before = {e["key"]: (e["id"], e["enqueued_at"]) for e in q["entries"]}

        started = []

        def _resume_bg(state, *a, **k):
            # A resumed loop's first queue access cleans stale entries.
            entry_map, _ = qa_loop.adopt_queue_entries(state)
            lq.keepalive(list(entry_map.values()))
            started.append(entry_map)

        with patch("pathlib.Path.home", return_value=tmp_path), \
             patch.object(qa_loop, "resume_qa_background",
                          side_effect=_resume_bg):
            qa_loop_ui._resume_incomplete_qa(app)
        after = {e["key"]: (e["id"], e["enqueued_at"])
                 for e in lq._load_queue()["entries"]}

    assert len(started) == 2
    assert after == before
    assert all(sorted(m) == [1, 2] for m in started)


def test_resume_adoption_runs_off_the_ui_thread(tmp_path):
    """Adoption waits on the governor lock, which another pm process may
    hold for seconds while it measures runtime stats; the poll tick that
    finds the run must not wait with it."""
    import threading

    app = _make_app(tmp_path)
    qa_dir = _seed_run(tmp_path)
    state = build_resume_state(_load_resume_file(qa_dir))
    _write_resume_file(state, use_containers=True, concurrency_cap=4,
                       queued_indices={1})
    lock_free = threading.Event()
    resumed = threading.Event()

    def _adopt(state, *a):
        assert lock_free.wait(5)
        return {}, set()

    with patch.object(qa_loop_ui, "threading", threading), \
         patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "adopt_queue_entries", side_effect=_adopt), \
         patch.object(qa_loop, "resume_qa_background",
                      side_effect=lambda *a: resumed.set()):
        qa_loop_ui._resume_incomplete_qa(app)
        assert "pr-001" in app._qa_loops
        assert not resumed.is_set()
        # While adoption waits, the run already counts as running, so a
        # user's t / zz t sees it instead of starting a second loop.
        assert app._qa_loops["pr-001"].running
        qa_loop_ui.stop_qa(app, "pr-001")
        assert app._qa_loops["pr-001"].stop_requested
        lock_free.set()
        assert resumed.wait(5)


def test_resume_that_cannot_start_reports_error(tmp_path):
    app = _make_app(tmp_path)
    _seed_run(tmp_path)

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "adopt_queue_entries",
                      return_value=({}, set())), \
         patch.object(qa_loop, "resume_qa_background",
                      side_effect=RuntimeError("can't start new thread")):
        qa_loop_ui._resume_incomplete_qa(app)

    state = app._qa_loops["pr-001"]
    assert not state.running
    assert state.latest_verdict == "ERROR"
    app.call_from_thread.assert_called()


def test_resume_whose_adopt_thread_cannot_start_reports_error(tmp_path):
    """The runs are published as running before the adoption thread starts;
    if it cannot start they must not stay running with no loop behind them
    (t / zz t would be blocked until the next TUI restart)."""
    app = _make_app(tmp_path)
    _seed_run(tmp_path)

    def _no_thread(*a, **k):
        raise RuntimeError("can't start new thread")

    with patch.object(qa_loop_ui, "threading", SimpleNamespace(Thread=_no_thread)), \
         patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg:
        qa_loop_ui._resume_incomplete_qa(app)

    state = app._qa_loops["pr-001"]
    assert not state.running
    assert state.latest_verdict == "ERROR"
    resume_bg.assert_not_called()
    # Not resuming: its pre-restart entries go to the next clean.
    from pm_core import launch_queue as lq
    assert not lq.awaiting_adoption(qa_loop._qa_run_key(state))


def test_resume_whose_adoption_times_out_keeps_expecting_it(tmp_path):
    """QA S52: adoption met a held lock.  The run keeps expecting adoption
    when its loop starts, so no clean drops its pre-restart entries before
    the loop retries."""
    from pm_core import launch_queue as lq

    app = _make_app(tmp_path)
    _seed_run(tmp_path)
    expecting = []

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "adopt_queue_entries",
                      return_value=({}, set())), \
         patch.object(qa_loop, "resume_qa_background",
                      side_effect=lambda state, *a: expecting.append(
                          lq.awaiting_adoption(qa_loop._qa_run_key(state)))):
        qa_loop_ui._resume_incomplete_qa(app)

    assert expecting == [True]


@pytest.mark.parametrize("failure", ["no_session", "thread_crash"])
def test_resume_that_aborts_releases_adopted_entries(tmp_path, failure):
    """The TUI adopts a resumed run's queue entries before resuming it.  A
    resume that fails before its poll loop (no pm session, crash) has no
    loop to renew or release them, so it must drop them itself rather than
    leave them holding other launches' headroom until the TTL."""
    from pm_core import launch_queue as lq

    app = _make_app(tmp_path)
    qa_dir = _seed_run(tmp_path)
    state = build_resume_state(_load_resume_file(qa_dir))
    _write_resume_file(state, use_containers=True, concurrency_cap=4,
                       queued_indices={1, 2})
    run = qa_loop._qa_run_key(state)
    lq_home = tmp_path / "lqhome"
    lq_home.mkdir()
    with patch("pm_core.launch_queue.pm_home", return_value=lq_home):
        lq.enqueue("qa_scenario", qa_run_id=run,
                   keys=[f"{run}:s1", f"{run}:s2"])
        lq.enqueue("impl", keys=["pm-other-impl"])
        q = lq._load_queue()
        for e in q["entries"]:
            if e.get("qa_run_id") == run:
                e["instance"] = "pre-restart"
        lq._save_queue(q)

        def _resume_bg(state, root, pr, cb):
            # Inline stand-in for resume_qa_background's thread body.
            if failure == "no_session":
                with patch.object(qa_loop, "get_pm_session",
                                  return_value=None):
                    qa_loop.resume_qa_sync(state, root, pr, cb)
            else:
                with patch.object(qa_loop, "resume_qa_sync",
                                  side_effect=RuntimeError("boom")), \
                     patch.object(qa_loop.threading, "Thread") as thread:
                    real_resume_bg(state, root, pr, cb)
                    thread.call_args.kwargs["target"]()

        real_resume_bg = qa_loop.resume_qa_background
        with patch("pathlib.Path.home", return_value=tmp_path), \
             patch.object(qa_loop, "resume_qa_background",
                          side_effect=_resume_bg):
            qa_loop_ui._resume_incomplete_qa(app)
        keys = [e["key"] for e in lq._load_queue()["entries"]]

    resumed = app._qa_loops["pr-001"]
    assert not resumed.running
    assert resumed.latest_verdict == "ERROR"
    assert keys == ["pm-other-impl"]


@pytest.mark.parametrize("failure", ["no_session", "workdir_missing"])
def test_resume_that_aborts_tells_the_tui_why(tmp_path, failure):
    """The poll tick's completion line only says "QA finished: ERROR", so an
    aborted resume must push its reason through on_update for the TUI log."""
    qa_dir = _seed_run(tmp_path)
    state = build_resume_state(_load_resume_file(qa_dir))
    updates = []
    pr = {"id": "pr-001", "workdir": str(tmp_path / "gone")}
    with patch.object(qa_loop, "get_pm_session",
                      return_value=None if failure == "no_session" else "pm-x"), \
         patch.object(store, "load", return_value={"prs": [pr]}), \
         patch.object(qa_loop, "_compute_qa_window_name", return_value="qa-pr-001"):
        qa_loop.resume_qa_sync(state, tmp_path, pr,
                               lambda s: updates.append(s.latest_output))

    assert not state.running
    assert state.latest_verdict == "ERROR"
    expected = ("No pm session found" if failure == "no_session"
                else "Workdir for pr-001 missing — cannot resume QA")
    assert updates == [expected]
