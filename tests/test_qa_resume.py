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
import yaml

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
    del app._foreign_qa_pr_ids  # MagicMock: start with no cache attribute
    return app


def _seed_run(home, *, overall="", pr_id="pr-001", loop="loop1",
              first_index=1, indices=None, scenario_start=0):
    """Create a qa workdir under <home>/.pm/workdirs/qa with resume+status.

    *first_index* numbers the run's scenarios, as a later run of the same
    PR continues from the earlier runs' indices; *indices* replaces the
    scenarios with bare ones numbered as given."""
    qa_dir = home / ".pm" / "workdirs" / "qa" / f"{pr_id}-{loop}"
    qa_dir.mkdir(parents=True, exist_ok=True)
    state = _make_state(qa_dir)
    state.pr_id = pr_id
    for i, sc in enumerate(state.scenarios):
        sc.index = first_index + i
    if indices is not None:
        state.scenarios = [QAScenario(index=i, title=f"S{i}", focus="")
                           for i in indices]
    state.scenario_start = scenario_start
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


def test_resume_incomplete_starts_poll_timer(tmp_path):
    # Only the poll timer processes the resumed run's completion.
    app = _make_app(tmp_path)
    app._review_loop_timer = None
    _seed_run(tmp_path, overall="")

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background"):
        qa_loop_ui._resume_incomplete_qa(app)

    app.set_interval.assert_called_once()


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
         patch.object(qa_loop, "get_pm_session",
                      return_value="pm-project_manager-deadbeef"), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_not_called()
    on_complete.assert_not_called()
    # Recorded so it isn't rechecked every tick.
    assert "pr-001" in app._resumed_qa_pr_ids
    # The PR left QA, so its stale snapshot is dropped from disk.
    assert not _resume_file_path(qa_dir).exists()


@pytest.mark.parametrize("other_session_live", [True, False])
def test_stale_status_keeps_another_clones_snapshot(tmp_path,
                                                    other_session_live):
    """Two clones of one project: clone B moved the PR to QA and its TUI
    died mid-run (with or without its whole tmux session), while this
    clone's project.yaml still has the PR at an older status.  Where the
    run came from decides, not whether B's session is up: the snapshot is
    kept until this project.yaml changes, adopted once a pull brings the
    PR here in QA, and then driven in B's session if it is up, else in
    this TUI's own."""
    app = _make_app(tmp_path, pr_status="in_review")
    qa_dir = _seed_run(tmp_path, overall="")
    run_session = "pm-project_manager-deadbeef"
    live = {"pm-clone-a"} | ({run_session} if other_session_live else set())

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "get_pm_session", return_value="pm-clone-a"), \
         patch("pm_core.tmux.session_exists",
               side_effect=lambda name, *a, **k: name.lstrip("=") in live), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg:
        qa_loop_ui._resume_incomplete_qa(app)
        resume_bg.assert_not_called()
        assert _resume_file_path(qa_dir).is_file()
        assert "pr-001" not in app._resumed_qa_pr_ids

        data = store.load(app._root)
        data["prs"][0]["status"] = "qa"
        store.save(data, app._root)
        qa_loop_ui._resume_incomplete_qa(app)

        resume_bg.assert_called_once()
        state = resume_bg.call_args.args[0]
        assert qa_loop._resume_session(state) == (
            run_session if other_session_live else "pm-clone-a")
    assert _resume_file_path(qa_dir).is_file()


def test_stale_status_drops_this_sessions_own_snapshot(tmp_path):
    """A run launched from this session whose PR has left QA here is
    cleaned up."""
    app = _make_app(tmp_path, pr_status="in_review")
    qa_dir = _seed_run(tmp_path, overall="")

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "get_pm_session",
                      return_value="pm-project_manager-deadbeef"), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg:
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_not_called()
    assert "pr-001" in app._resumed_qa_pr_ids
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


def test_other_projects_snapshots_are_left_alone(tmp_path):
    """~/.pm/workdirs/qa is shared by every project.  A run of another
    project's PR whose TUI just died (owner gone) is that TUI's to resume:
    this TUI neither adopts it nor drops its snapshots as "left QA", nor
    drops an older superseded snapshot of it (S39)."""
    app = _make_app(tmp_path)
    older = _seed_run(tmp_path, overall="PASS", pr_id="pr-0ther", loop="old")
    live = _seed_run(tmp_path, overall="", pr_id="pr-0ther", loop="live",
                     first_index=4)

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_not_called()
    on_complete.assert_not_called()
    assert "pr-0ther" not in app._qa_loops
    assert "pr-0ther" not in app._resumed_qa_pr_ids
    assert _resume_file_path(live).is_file()
    assert _resume_file_path(older).is_file()


def test_other_projects_snapshots_load_the_project_once(tmp_path):
    """The scan runs every few seconds, and another project's snapshot can
    stay for the whole session: its PR is looked up in this project once,
    not on every scan."""
    app = _make_app(tmp_path)
    _seed_run(tmp_path, overall="", pr_id="pr-0ther", loop="live")

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui.store, "load",
                      wraps=qa_loop_ui.store.load) as load:
        qa_loop_ui._resume_incomplete_qa(app)
        qa_loop_ui._resume_incomplete_qa(app)

    assert load.call_count == 1
    resume_bg.assert_not_called()
    assert app._foreign_qa_pr_ids == {"pr-0ther"}


def test_snapshot_seen_before_its_pr_arrives_resumes_after_pull(tmp_path):
    """A snapshot whose PR is not in this project yet (it arrives by a pull
    or import of project.yaml) is not foreign forever: once project.yaml
    has the PR in QA, the next scan resumes it.  A truly foreign snapshot
    seen alongside it stays untouched."""
    app = _make_app(tmp_path)
    late = _seed_run(tmp_path, overall="", pr_id="pr-late", loop="late")
    other = _seed_run(tmp_path, overall="", pr_id="pr-0ther", loop="other")

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg:
        qa_loop_ui._resume_incomplete_qa(app)
        resume_bg.assert_not_called()
        assert app._foreign_qa_pr_ids == {"pr-late", "pr-0ther"}

        data = store.load(app._root)
        data["prs"].append({"id": "pr-late", "title": "L", "branch": "l",
                            "status": "qa", "workdir": str(tmp_path / "wl"),
                            "notes": []})
        store.save(data, app._root)

        qa_loop_ui._resume_incomplete_qa(app)

    assert [c.args[2]["id"] for c in resume_bg.call_args_list] == ["pr-late"]
    assert "pr-late" in app._qa_loops
    assert "pr-0ther" not in app._qa_loops
    assert app._foreign_qa_pr_ids == {"pr-0ther"}
    assert _resume_file_path(late).is_file()
    assert _resume_file_path(other).is_file()


def test_in_place_project_edit_also_forgets_foreign_ids(tmp_path):
    """store.save replaces project.yaml (new inode), but an editor (under
    `pm edit`, for example) may rewrite it in place: that edit must
    clear the remembered ids too."""
    app = _make_app(tmp_path)
    _seed_run(tmp_path, overall="", pr_id="pr-late", loop="late")
    project_file = app._root / "project.yaml"

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg:
        qa_loop_ui._resume_incomplete_qa(app)
        assert app._foreign_qa_pr_ids == {"pr-late"}

        inode = project_file.stat().st_ino
        data = store.load(app._root)
        data["prs"].append({"id": "pr-late", "title": "L", "branch": "l",
                            "status": "qa", "workdir": str(tmp_path / "wl"),
                            "notes": []})
        text = yaml.safe_dump(data, sort_keys=False)
        project_file.chmod(0o644)  # store.save leaves it read-only
        with open(project_file, "r+") as f:
            f.write(text)
            f.truncate()
        assert project_file.stat().st_ino == inode

        qa_loop_ui._resume_incomplete_qa(app)

    assert [c.args[2]["id"] for c in resume_bg.call_args_list] == ["pr-late"]
    assert app._foreign_qa_pr_ids == set()


def _live_foreign_process():
    import subprocess
    return subprocess.Popen(["sleep", "60"])


def test_scan_does_not_adopt_a_run_another_tui_claimed_after_the_check(
        tmp_path):
    """Check-then-adopt race between two TUIs (S41): both read the dead
    owner; the other one adopts the run (its pid lands in the snapshot)
    after this scan's ownership check but before this scan resumes.  The
    barrier puts the other TUI's claim exactly in that window.  The scan
    must re-check under the claim and leave the run alone."""
    app = _make_app(tmp_path)
    qa_dir = _seed_run(tmp_path, overall="")
    other = _live_foreign_process()
    real = qa_loop.resume_owned_elsewhere
    calls = []

    def check_then_other_adopts(rdata):
        owned = real(rdata)
        if not calls:  # the scan's first (stale) check: then B adopts
            data = json.loads(_resume_file_path(qa_dir).read_text())
            data["owner_pid"] = other.pid
            data["owner_start"] = qa_loop._proc_start_time(other.pid)
            _resume_file_path(qa_dir).write_text(json.dumps(data))
        calls.append(owned)
        return owned

    try:
        with patch("pathlib.Path.home", return_value=tmp_path), \
             patch.object(qa_loop, "resume_owned_elsewhere",
                          side_effect=check_then_other_adopts), \
             patch.object(qa_loop, "resume_qa_background") as resume_bg, \
             patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
            qa_loop_ui._resume_incomplete_qa(app)
    finally:
        other.kill()
        other.wait()

    resume_bg.assert_not_called()
    on_complete.assert_not_called()
    assert "pr-001" not in app._qa_loops
    assert "pr-001" not in app._resumed_qa_pr_ids  # re-checked next scan
    assert json.loads(_resume_file_path(qa_dir).read_text())["owner_pid"] \
        == other.pid


def test_two_processes_claiming_one_orphan_get_exactly_one_owner(tmp_path):
    """Two processes (two TUIs) released together onto the same dead-owner
    snapshot: exactly one claim succeeds and the snapshot names it."""
    import subprocess
    import sys
    import time
    qa_dir = _seed_run(tmp_path, overall="")
    dead = subprocess.Popen(["true"])
    dead.wait()
    data = json.loads(_resume_file_path(qa_dir).read_text())
    data["owner_pid"] = dead.pid
    _resume_file_path(qa_dir).write_text(json.dumps(data))
    go = tmp_path / "go"
    code = (
        "import os, sys, time\n"
        "from pm_core import qa_loop\n"
        # widen the read-to-write window so an unlocked claim always races
        "_read = qa_loop._load_resume_file\n"
        "def _slow(d):\n"
        "    r = _read(d); time.sleep(0.5); return r\n"
        "qa_loop._load_resume_file = _slow\n"
        "open(sys.argv[2] + '.ready.' + str(os.getpid()), 'w').close()\n"
        "while not os.path.exists(sys.argv[2]): time.sleep(0.001)\n"
        "d = qa_loop.claim_resume_file(sys.argv[1], sys.argv[3])\n"
        "print('claimed' if d else 'skipped', os.getpid())\n"
        # keep the claimant alive so the other one sees a live owner
        "time.sleep(2)\n")
    import os
    from pathlib import Path
    env = dict(os.environ,
               PYTHONPATH=str(Path(qa_loop.__file__).resolve().parents[1]))
    procs = [subprocess.Popen([sys.executable, "-c", code, str(qa_dir),
                               str(go), data["loop_id"]],
                              stdout=subprocess.PIPE, text=True, env=env)
             for _ in range(2)]
    deadline = time.monotonic() + 20
    while (len(list(tmp_path.glob("go.ready.*"))) < 2
           and time.monotonic() < deadline):
        time.sleep(0.01)
    go.touch()
    out = [p.communicate(timeout=30)[0].split() for p in procs]
    winners = [int(pid) for res, pid in out if res == "claimed"]
    assert len(winners) == 1, out
    assert json.loads(_resume_file_path(qa_dir).read_text())["owner_pid"] \
        == winners[0]


def test_claim_refuses_a_replaced_run(tmp_path):
    qa_dir = _seed_run(tmp_path, overall="")
    assert qa_loop.claim_resume_file(qa_dir, "some-other-loop") is None
    assert qa_loop.claim_resume_file(qa_dir, "abc123") is not None


def test_unparseable_project_file_does_not_escape_the_scan(tmp_path):
    """A git pull that conflicts on project.yaml leaves conflict markers in
    it.  The resume scan loads the file when it sees a snapshot of an
    unknown PR (or to check a known one's status); the parse error used
    to escape the poll tick, which re-raises and so killed the TUI (S41).
    The scan now skips until the file parses, then resumes as usual."""
    app = _make_app(tmp_path)
    _seed_run(tmp_path, overall="", pr_id="pr-001")
    project_file = app._root / "project.yaml"
    good = project_file.read_text()
    project_file.chmod(0o644)
    project_file.write_text(good.replace(
        "prs:\n", "prs:\n<<<<<<< HEAD\n=======\n>>>>>>> abc\n", 1))

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg:
        qa_loop_ui._resume_incomplete_qa(app)
        qa_loop_ui._resume_incomplete_qa(app)
        resume_bg.assert_not_called()
        assert "pr-001" not in app._foreign_qa_pr_ids

        project_file.write_text(good)
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_called_once()


@pytest.mark.parametrize("breakage", ["missing", "bad_plan_parent"])
def test_unloadable_project_file_does_not_escape_the_scan(tmp_path, breakage):
    """Besides conflict markers, a pull can leave a project.yaml that
    parses but fails plan validation (PlanValidationError), and a checkout
    unlinks the file before rewriting it (FileNotFoundError).  Either used
    to escape the scan like the parse error did."""
    app = _make_app(tmp_path)
    _seed_run(tmp_path, overall="", pr_id="pr-001")
    project_file = app._root / "project.yaml"
    good = project_file.read_text()
    project_file.chmod(0o644)
    if breakage == "missing":
        project_file.unlink()
    else:
        project_file.write_text(good + "plans:\n- id: plan-a\n"
                                "  name: A\n  parent: plan-missing\n")

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg:
        qa_loop_ui._resume_incomplete_qa(app)
        resume_bg.assert_not_called()

        project_file.write_text(good)
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_called_once()


def test_resume_of_a_pulled_pr_reloads_the_tree(tmp_path):
    """A PR that arrived by a git pull is in project.yaml but not in the
    TUI's loaded state (a pull signals no reload): resuming its run
    reloads, so its node shows at once, not at the 300 s sync (S41)."""
    app = _make_app(tmp_path)
    app._data = {"prs": []}
    _seed_run(tmp_path, overall="")

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg:
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_called_once()
    app._load_state.assert_called_once()


def test_resume_of_a_shown_pr_does_not_reload(tmp_path):
    app = _make_app(tmp_path)
    app._data = store.load(app._root)
    _seed_run(tmp_path, overall="")

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg:
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_called_once()
    app._load_state.assert_not_called()


def _resume_in(tmp_path, *, live_sessions):
    """resume_qa_sync for a run recorded by session tag "clone-b" in a TUI
    whose own session is pm-clone-a; returns the session it drives."""
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()
    wd = tmp_path / "wd"
    wd.mkdir()
    pr = {"id": "pr-001", "title": "T", "branch": "b", "status": "qa",
          "workdir": str(wd), "notes": []}
    store.save({"project": {"name": "test", "repo": "/tmp/r",
                            "base_branch": "master"}, "prs": [pr]}, pm_dir)
    state = _make_state(tmp_path / "qa")
    state.session_tag = "clone-b"
    with patch.object(qa_loop, "get_pm_session", return_value="pm-clone-a"), \
         patch("pm_core.tmux.session_exists",
               side_effect=lambda name, *a, **k: name.lstrip("=") in live_sessions), \
         patch.object(qa_loop, "_execute_and_finalize",
                      return_value=state) as run:
        qa_loop.resume_qa_sync(state, pm_dir, pr)
    return run.call_args.args[4]


def test_resumed_run_is_driven_in_the_session_that_holds_its_windows(tmp_path):
    """A run adopted from another clone's pm session keeps its windows
    there: the resumed loop must look for them (finalizer, relaunches) in
    that session, not this TUI's, which skipped the finalizer (S41)."""
    assert _resume_in(tmp_path, live_sessions={"pm-clone-a", "pm-clone-b"}) \
        == "pm-clone-b"


def test_resumed_run_uses_own_session_when_its_session_is_gone(tmp_path):
    assert _resume_in(tmp_path, live_sessions={"pm-clone-a"}) == "pm-clone-a"


@pytest.mark.parametrize("stale_loop", ["aaa", "zzz"])
@pytest.mark.parametrize("stale_mtime", [1_000_000, 4_000_000_000])
def test_resume_prefers_live_snapshot_over_superseded_run(tmp_path,
                                                          stale_loop,
                                                          stale_mtime):
    """A fresh start leaves the stopped run's snapshot (overall written,
    completion never processed) beside the live run's.  The restart must
    resume the live run whatever the directory order, even when a late
    write from the stopped run made its snapshot the newest, and drop the
    superseded snapshot."""
    import os
    app = _make_app(tmp_path)
    stale = _seed_run(tmp_path, overall="INPUT_REQUIRED", loop=stale_loop)
    live = _seed_run(tmp_path, overall="", loop="live")
    os.utime(_resume_file_path(stale), (stale_mtime, stale_mtime))

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_called_once()
    assert resume_bg.call_args[0][0].qa_workdir == str(live)
    on_complete.assert_not_called()
    assert _resume_file_path(live).is_file()
    assert not _resume_file_path(stale).exists()


def test_superseded_snapshot_owned_by_live_process_is_kept(tmp_path):
    """An older finished snapshot whose run another live process still
    drives (e.g. an auto-sequence QA child finalizing) is not deleted just
    because a newer run exists for the PR."""
    import os
    app = _make_app(tmp_path)
    owned = _seed_run(tmp_path, overall="INPUT_REQUIRED", loop="owned")
    os.utime(_resume_file_path(owned), (1_000_000, 1_000_000))
    live = _seed_run(tmp_path, overall="", loop="live")

    def _owned_elsewhere(rdata):
        return rdata.get("qa_workdir") == str(owned)

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_owned_elsewhere",
                      side_effect=_owned_elsewhere), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete"):
        qa_loop_ui._resume_incomplete_qa(app)

    assert _resume_file_path(owned).is_file()
    resume_bg.assert_called_once()
    assert resume_bg.call_args[0][0].qa_workdir == str(live)


def test_superseded_snapshot_of_in_memory_loop_is_kept(tmp_path):
    """The snapshot of a loop this TUI still tracks in memory is never
    deleted as superseded, even when it is older and finished."""
    import os
    app = _make_app(tmp_path)
    current = _seed_run(tmp_path, overall="PASS", loop="current")
    os.utime(_resume_file_path(current), (1_000_000, 1_000_000))
    _seed_run(tmp_path, overall="INPUT_REQUIRED", loop="other")
    tracked = _make_state(current)
    tracked.pr_id = "pr-001"
    app._qa_loops["pr-001"] = tracked

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)

    assert _resume_file_path(current).is_file()
    resume_bg.assert_not_called()
    on_complete.assert_not_called()


def test_older_unfinished_orphan_does_not_outrank_newer_completed_run(
        tmp_path):
    """An older run left unfinished (its driver died) beside a newer run
    that completed while the TUI was down: the newer run's completion is
    processed, the stale run is not revived, and its snapshot is dropped so
    a later restart cannot revive it either."""
    import os
    app = _make_app(tmp_path)
    stale = _seed_run(tmp_path, overall="", loop="old", first_index=1)
    done = _seed_run(tmp_path, overall="PASS", loop="new", first_index=3)
    os.utime(_resume_file_path(done), (1_000_000, 1_000_000))

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_not_called()
    on_complete.assert_called_once()
    assert on_complete.call_args[0][1].qa_workdir == str(done)
    assert not _resume_file_path(stale).exists()


def test_two_unfinished_runs_resume_the_newer_run(tmp_path):
    """Two unfinished snapshots for one PR: the newer run (higher scenario
    numbers) is resumed even when the older one's snapshot is newer on
    disk; the older snapshot is dropped."""
    import os
    app = _make_app(tmp_path)
    old = _seed_run(tmp_path, overall="", loop="old", first_index=1)
    new = _seed_run(tmp_path, overall="", loop="new", first_index=3)
    os.utime(_resume_file_path(new), (1_000_000, 1_000_000))

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_called_once()
    assert resume_bg.call_args[0][0].qa_workdir == str(new)
    on_complete.assert_not_called()
    assert _resume_file_path(new).is_file()
    assert not _resume_file_path(old).exists()


def test_newer_run_with_fewer_scenarios_outranks_queued_tail(tmp_path):
    """An older run's queued scenarios never got workdirs, so a newer run
    numbers on from its launched ones and can end below the older run's
    queued tail (old 1-6 with cap 2 -> new 3-5).  The newer run is still
    resumed, and the older run's stale stop verdict is not processed."""
    app = _make_app(tmp_path)
    old = _seed_run(tmp_path, overall="INPUT_REQUIRED", loop="old",
                    indices=[1, 2, 3, 4, 5, 6])
    new = _seed_run(tmp_path, overall="", loop="new", indices=[3, 4, 5])

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_called_once()
    assert resume_bg.call_args[0][0].qa_workdir == str(new)
    on_complete.assert_not_called()
    assert not _resume_file_path(old).exists()


def test_newer_run_without_scenarios_outranks_older_orphan(tmp_path):
    """A newer run whose planner produced no scenarios has no scenario
    index to order by; the start index it was given (past the older run's
    launched scenarios) does.  Its completion is processed and the older
    orphan is neither revived nor kept."""
    app = _make_app(tmp_path)
    old = _seed_run(tmp_path, overall="", loop="old", indices=[1, 2, 3])
    new = _seed_run(tmp_path, overall="INPUT_REQUIRED", loop="new",
                    indices=[], scenario_start=4)

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)

    resume_bg.assert_not_called()
    on_complete.assert_called_once()
    assert on_complete.call_args[0][1].qa_workdir == str(new)
    assert not _resume_file_path(old).exists()


def test_scenario_start_survives_resume_round_trip(tmp_path):
    state = _make_state(tmp_path)
    state.scenario_start = 7
    _write_resume_file(state, use_containers=False, concurrency_cap=0)
    rebuilt = build_resume_state(_load_resume_file(tmp_path))
    assert rebuilt.scenario_start == 7


def test_older_unfinished_run_owned_elsewhere_is_kept(tmp_path):
    """An older unfinished run another live process still drives is
    neither resumed nor deleted, whatever newer run exists."""
    app = _make_app(tmp_path)
    owned = _seed_run(tmp_path, overall="", loop="owned", first_index=1)
    new = _seed_run(tmp_path, overall="", loop="new", first_index=3)

    def _owned_elsewhere(rdata):
        return rdata.get("qa_workdir") == str(owned)

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_owned_elsewhere",
                      side_effect=_owned_elsewhere), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete"):
        qa_loop_ui._resume_incomplete_qa(app)

    assert _resume_file_path(owned).is_file()
    resume_bg.assert_called_once()
    assert resume_bg.call_args[0][0].qa_workdir == str(new)


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
# A stopped (z t superseded) run leaves no snapshot behind
# ---------------------------------------------------------------------------

def test_stopped_run_does_not_write_a_snapshot(tmp_path):
    """The stopped loop keeps writing while it winds down (each poll tick
    and once more at the end): those writes drop the snapshot instead."""
    state = _make_state(tmp_path)
    _write_resume_file(state, use_containers=False, concurrency_cap=0)
    state.stop_requested = True
    _write_resume_file(state, use_containers=False, concurrency_cap=0)
    assert not _resume_file_path(tmp_path).exists()


def test_supersede_during_snapshot_write_leaves_no_snapshot(tmp_path):
    """z t lands after a write passed its stop check but before its
    rename: the write must not restore the snapshot z t just cleared
    (a restart before the stopped thread's next write would revive the
    superseded run while the new one is still planning)."""
    state = _make_state(tmp_path)
    _write_resume_file(state, use_containers=False, concurrency_cap=0)
    real_dumps = qa_loop.json.dumps

    def dumps_then_supersede(*a, **kw):
        out = real_dumps(*a, **kw)
        qa_loop.supersede_run(state)  # past the stop check, before rename
        return out

    with patch.object(qa_loop.json, "dumps", side_effect=dumps_then_supersede):
        _write_resume_file(state, use_containers=False, concurrency_cap=0)
    assert state.stop_requested
    assert not _resume_file_path(tmp_path).exists()
    assert not _resume_file_path(tmp_path).with_suffix(".tmp").exists()


def test_supersede_waits_for_an_in_flight_rename(tmp_path):
    """A write paused at its rename: the supersede waits for it and then
    clears, so the renamed snapshot does not outlive the clear."""
    import threading
    from pathlib import Path

    state = _make_state(tmp_path)
    at_rename, release = threading.Event(), threading.Event()
    real_rename = Path.rename

    def paused_rename(self, target):
        if self.name.startswith("qa_resume"):
            at_rename.set()
            assert release.wait(10)
        return real_rename(self, target)

    with patch.object(Path, "rename", paused_rename):
        writer = threading.Thread(target=_write_resume_file,
                                  args=(state, False, 0))
        superseder = threading.Thread(target=qa_loop.supersede_run,
                                      args=(state,))
        writer.start()
        try:
            assert at_rename.wait(10)
            superseder.start()
            superseder.join(0.3)
            assert superseder.is_alive()  # held off by the in-flight write
        finally:
            release.set()
            writer.join(10)
            if superseder.ident is not None:
                superseder.join(10)
    assert not writer.is_alive() and not superseder.is_alive()
    assert state.stop_requested
    assert not _resume_file_path(tmp_path).exists()


def test_fresh_start_drops_superseded_snapshot_before_new_run_has_one(
        tmp_path):
    """z t over a running loop: the new run writes no snapshot while it
    plans (and an empty plan clears its own at once), so the old run's
    snapshot would be the PR's only one — revived by a restart, or
    "recovered" with a stale QA note once the new run is done."""
    app = _make_app(tmp_path)
    old = _seed_run(tmp_path, overall="", loop="old")
    running = build_resume_state(_load_resume_file(old))
    running.running = True
    app._qa_loops["pr-001"] = running

    with patch.object(qa_loop_ui, "start_qa") as start:
        qa_loop_ui.fresh_start_qa(app, "pr-001")
    start.assert_called_once()
    assert running.stop_requested
    assert not _resume_file_path(old).exists()

    # The stopped thread's final write (overall INPUT_REQUIRED) leaves none.
    (old / "qa_status.json").write_text(json.dumps(
        {"pr_id": "pr-001", "scenarios": [], "overall": "INPUT_REQUIRED"}))
    _write_resume_file(running, use_containers=False, concurrency_cap=0)
    app._qa_loops.clear()  # the new run completed and was processed
    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch.object(qa_loop, "resume_qa_background") as resume_bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as on_complete:
        qa_loop_ui._resume_incomplete_qa(app)
    resume_bg.assert_not_called()
    on_complete.assert_not_called()
