"""QA run ownership survives a restart during worker startup (pr-3201ea8).

Before the fix, ``qa_resume.json`` was first written only after *every*
scenario refiner had finished and every worker had launched.  A TUI
restart while one scenario was executing and another still refining left
no snapshot: the run was forgotten (W3.4) and auto-start launched a second
run beside the original workers (#234).

The harness models tmux (windows, panes, start commands), Claude sessions
(JSONL transcripts + idle hooks) and the pm session in memory, so every
"restart" is deterministic: a snapshot captured at a chosen moment is fed
to ``build_resume_state`` / ``resume_qa_sync`` exactly as the TUI would,
and the test counts what gets launched.
"""

import itertools
import json
import os
import threading
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pm_core import qa_loop, store
from pm_core.qa_loop import (
    QALoopState,
    QAScenario,
    VERDICT_PASS,
    _load_resume_file,
    build_resume_state,
)
from pm_core.tui import qa_loop_ui

PR = {"id": "pr-001", "title": "T", "branch": "b", "status": "qa"}
REFINED = "REFINED_STEPS_START\nGIVEN: x\nWHEN: y\nTHEN: z\nREFINED_STEPS_END"


# ---------------------------------------------------------------------------
# In-memory tmux + Claude
# ---------------------------------------------------------------------------

class FakeWorld:
    """tmux panes/windows plus Claude transcripts and idle hooks."""

    def __init__(self, home: Path):
        self.home = home
        self.windows: dict[str, list[str]] = {}
        self.panes: dict[str, dict] = {}
        self.events: dict[str, dict] = {}
        self._ids = itertools.count(10)
        self.launches: list[tuple[str, str]] = []   # (kind, window)
        self.lock = threading.Lock()
        self.on_launch = None      # hook(kind, window, pane, cmd)

    # -- tmux -------------------------------------------------------------
    def _add(self, window: str, cmd: str, kind: str) -> str:
        with self.lock:
            pane = f"%{next(self._ids)}"
            self.windows.setdefault(window, []).append(pane)
            self.panes[pane] = {"cmd": cmd, "window": window, "alive": True}
            self.launches.append((kind, window))
        if self.on_launch:
            self.on_launch(kind, window, pane, cmd)
        return pane

    def kind_of(self, cmd: str) -> str:
        return cmd.split()[0]

    def new_window_get_pane(self, session, name, cmd, cwd=None, switch=False):
        return self._add(name, cmd, self.kind_of(cmd))

    def new_window(self, session, name, cmd, cwd=None, switch=False):
        self._add(name, cmd, self.kind_of(cmd))

    def split_pane_at(self, pane, direction, cmd, background=True, cwd=None):
        return self._add(self.panes[pane]["window"], cmd, self.kind_of(cmd))

    def find_window_by_name(self, session, name):
        if any(self.panes[p]["alive"] for p in self.windows.get(name, [])):
            return {"index": name, "id": name, "name": name}
        return None

    def get_pane_indices(self, session, index):
        live = [p for p in self.windows.get(index, [])
                if self.panes[p]["alive"]]
        return [(p, i) for i, p in enumerate(live)]

    def pane_start_command(self, pane):
        info = self.panes.get(pane)
        return info["cmd"] if info and info["alive"] else ""

    def pane_exists(self, pane):
        return bool(pane) and pane in self.panes and self.panes[pane]["alive"]

    def kill(self, pane):
        self.panes[pane]["alive"] = False

    # -- Claude -----------------------------------------------------------
    def native_transcript(self, cwd: str, sid: str) -> Path:
        mangled = cwd.replace("/", "-").replace(".", "-")
        return self.home / ".claude" / "projects" / mangled / f"{sid}.jsonl"

    def finish(self, transcript: str | Path, text: str, sid: str):
        """The session ends its turn with *text* and goes idle."""
        p = Path(transcript)
        target = Path(os.readlink(p)) if p.is_symlink() else p
        target.parent.mkdir(parents=True, exist_ok=True)
        rec = {"type": "assistant", "message": {
            "content": [{"type": "text", "text": text}]}}
        target.write_text(json.dumps(rec) + "\n")
        self.events[sid] = {"event_type": "idle_prompt",
                            "timestamp": 1_000.0 + len(self.events)}

    def read_event(self, sid):
        return self.events.get(sid)

    def wait_for_event(self, sid, event_types, timeout, newer_than=0.0,
                       tick=0.2, stop_check=None):
        import time
        time.sleep(0.01)
        ev = self.events.get(sid)
        if ev and ev["event_type"] in event_types and ev["timestamp"] > newer_than:
            return ev
        return None


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    w = FakeWorld(home)
    from pm_core import tmux, hook_events
    for name in ("new_window_get_pane", "new_window", "split_pane_at",
                 "find_window_by_name", "get_pane_indices",
                 "pane_start_command", "pane_exists"):
        monkeypatch.setattr(tmux, name, getattr(w, name))
    monkeypatch.setattr(tmux, "pane_window_id", lambda p: None)
    monkeypatch.setattr(tmux, "send_keys", lambda *a, **k: None)
    monkeypatch.setattr(tmux, "capture_pane", lambda *a, **k: "")
    monkeypatch.setattr(hook_events, "read_event", w.read_event)
    monkeypatch.setattr(hook_events, "wait_for_event", w.wait_for_event)
    from pm_core.claude_launcher import WorkspacePromptWatch
    monkeypatch.setattr(WorkspacePromptWatch, "check", lambda self: None)

    monkeypatch.setattr(qa_loop, "_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
    monkeypatch.setattr(qa_loop, "_ADOPT_WAIT", 0.01, raising=False)
    monkeypatch.setattr(qa_loop, "_is_verification_enabled", lambda: False)
    monkeypatch.setattr(qa_loop, "_get_verdict_reminder_timeout", lambda: None)
    monkeypatch.setattr(qa_loop, "_resolve_qa_model", MagicMock())
    monkeypatch.setattr(qa_loop, "_setup_clone_override", lambda *a: None)
    monkeypatch.setattr(qa_loop, "_persist_scenario_verdicts", lambda *a: None)
    monkeypatch.setattr(qa_loop, "_add_status_pane", lambda *a: None)
    monkeypatch.setattr(qa_loop, "get_pm_session", lambda: "pm-sess")

    w.prepared: list[int] = []

    def _create_workdir(qa_workdir, index, **kw):
        w.prepared.append(index)
        repo = Path(qa_workdir) / f"s-{index}" / "repo"
        scratch = Path(qa_workdir) / f"s-{index}" / "scratch"
        repo.mkdir(parents=True, exist_ok=True)
        scratch.mkdir(parents=True, exist_ok=True)
        return repo, scratch
    monkeypatch.setattr(qa_loop, "create_scenario_workdir", _create_workdir)

    def _concretize_cmd(scenario, pr_data, data, cwd, session_id=None, **kw):
        return f"refiner --session-id {session_id}"
    monkeypatch.setattr(qa_loop, "_build_concretize_cmd", _concretize_cmd)

    def _run_cmd(scenario, state, data, transcript, res, *, session,
                 workdir_path):
        sid = str(uuid.uuid4())
        cwd = scenario.worktree_path or workdir_path
        Path(transcript).parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(transcript):
            os.unlink(transcript)
        os.symlink(w.native_transcript(cwd, sid), transcript)
        return f"worker --session-id {sid}", cwd
    monkeypatch.setattr(qa_loop, "_build_scenario_run_cmd", _run_cmd)

    # A refiner launched fresh finishes at once (poll_for_verdict is only
    # used for refiners this process launched itself).
    monkeypatch.setattr(qa_loop, "poll_for_verdict",
                        lambda *a, **k: REFINED)
    return w


def _pm_root(tmp_path) -> Path:
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir(exist_ok=True)
    wd = tmp_path / "wd"
    wd.mkdir(exist_ok=True)
    store.save({"project": {"name": "t", "repo": str(wd),
                            "base_branch": "master"},
                "prs": [dict(PR, workdir=str(wd), notes=[])]}, pm_dir)
    return pm_dir


def _plan(n=3) -> list[QAScenario]:
    return [QAScenario(index=i, title=f"S{i}", focus="f", steps=f"draft {i}",
                       launch_phase="queued") for i in range(1, n + 1)]


def _new_state(tmp_path) -> QALoopState:
    state = QALoopState(pr_id="pr-001")
    state.qa_workdir = str(tmp_path / "qa")
    Path(state.qa_workdir).mkdir(parents=True, exist_ok=True)
    state.session_tag = "tag"
    state.planning_phase = False
    state.concurrency_cap = 2
    state.run_phase = "launching"
    state.started_at = "2026-10-22T00:00:00+00:00"
    state.scenarios = _plan()
    return state


def _launch_with_restart_point(world, tmp_path, state):
    """Launch s1 and s2 (cap 2; s3 queued).  s1's refiner finishes and its
    worker starts; s2's refiner is still running when the 'controller is
    killed'.  Returns the snapshot as it was on disk at that moment."""
    gate = threading.Event()
    captured = {}
    real_poll = qa_loop.poll_for_verdict

    def _poll(pane, transcript, **kw):
        if world.panes[pane]["window"].endswith("-s2"):
            # s1 is executing now; capture what a restart would see.
            for _ in range(500):
                s1 = next(s for s in state.scenarios if s.index == 1)
                if s1.launch_phase == "running":
                    break
                threading.Event().wait(0.01)
            captured.update(_load_resume_file(state.qa_workdir))
            gate.set()
            return None   # this "process" dies here; result never consumed
        return real_poll(pane, transcript, **kw)

    with patch.object(qa_loop, "poll_for_verdict", _poll):
        qa_loop._launch_scenarios_in_tmux(
            state, {}, PR, "pm-sess", tmp_path / "wd", str(tmp_path / "wd"),
            scenarios=state.scenarios[:2])
    assert gate.is_set()
    return captured


# ---------------------------------------------------------------------------
# Ownership during startup
# ---------------------------------------------------------------------------

def test_snapshot_exists_while_a_scenario_is_still_refining(world, tmp_path):
    """W3.4 / #234: s1 executing, s2 refining, s3 queued — the run must
    already be on disk with each scenario's phase and identities."""
    (tmp_path / "wd").mkdir()
    state = _new_state(tmp_path)
    snap = _launch_with_restart_point(world, tmp_path, state)

    assert snap["pr_id"] == "pr-001" and snap["loop_id"] == state.loop_id
    assert snap["phase"] == "launching" and not snap["cancelled"]
    by = {s["index"]: s for s in snap["scenarios"]}
    # s1: worker identity distinct from its refiner's.
    assert by[1]["launch_phase"] == "running"
    assert by[1]["pane_id"] and by[1]["session_id"]
    assert by[1]["concretize_session_id"] != by[1]["session_id"]
    assert by[1]["steps"].startswith("GIVEN: x")
    # s2: refiner recorded, no worker yet.
    assert by[2]["launch_phase"] == "refining"
    assert by[2]["concretize_session_id"] and by[2]["concretize_pane_id"]
    assert by[2]["session_id"] is None and by[2]["pane_id"] is None
    # s3: not launched.
    assert by[3]["launch_phase"] == "queued"
    assert snap["queued_indices"] == [3]


def test_refiner_identity_recorded_before_its_window(world, tmp_path):
    """A kill between 'refiner chosen' and 'window created' must not leave
    a refiner the snapshot doesn't know about."""
    (tmp_path / "wd").mkdir()
    state = _new_state(tmp_path)
    seen = []

    def _on_launch(kind, window, pane, cmd):
        snap = _load_resume_file(state.qa_workdir)
        sc = next(s for s in snap["scenarios"] if window.endswith(f"-s{s['index']}"))
        sid = cmd.split("--session-id ")[1].split()[0]
        if kind == "refiner":
            seen.append(("refiner", sc["launch_phase"],
                         sc["concretize_session_id"] == sid))
        else:
            seen.append(("worker", sc["launch_phase"], sc["session_id"] == sid))
    world.on_launch = _on_launch
    qa_loop._launch_scenarios_in_tmux(
        state, {}, PR, "pm-sess", tmp_path / "wd", str(tmp_path / "wd"),
        scenarios=state.scenarios[:1])
    assert seen == [("refiner", "refining", True),
                    ("worker", "launching", True)]
    snap = _load_resume_file(state.qa_workdir)
    assert snap["scenarios"][0]["launch_phase"] == "running"


# ---------------------------------------------------------------------------
# Restart: adopt the same run, launch only missing work once
# ---------------------------------------------------------------------------

def _resume(world, tmp_path, snap, finalize=None):
    pm_root = _pm_root(tmp_path)
    finalize = finalize or MagicMock(return_value="FINALIZE_DONE")
    state = build_resume_state(snap)
    with patch.object(qa_loop, "_run_qa_finalize_pane", finalize):
        qa_loop.resume_qa_sync(state, pm_root, dict(PR, workdir=str(tmp_path / "wd")))
    return state, finalize


def test_restart_mid_startup_adopts_run_and_launches_missing_work_once(
        world, tmp_path):
    (tmp_path / "wd").mkdir()
    state = _new_state(tmp_path)
    snap = _launch_with_restart_point(world, tmp_path, state)
    by = {s["index"]: s for s in snap["scenarios"]}

    # During the downtime: s1's worker finishes (its idle hook fires with
    # nobody watching); s2's refiner finishes too.
    world.finish(by[1]["transcript_path"], "All good\nPASS", by[1]["session_id"])
    s2_refiner = world.native_transcript(by[2]["concretize_cwd"],
                                         by[2]["concretize_session_id"])
    world.finish(s2_refiner, REFINED, by[2]["concretize_session_id"])

    # Workers launched after the restart finish straight away.
    def _on_launch(kind, window, pane, cmd):
        if kind == "worker":
            sid = cmd.split("--session-id ")[1].split()[0]
            idx = int(window.rsplit("-s", 1)[1])
            transcript = Path(state.qa_workdir) / f"transcript-s{idx}.jsonl"
            world.finish(transcript, "Done\nPASS", sid)
    world.on_launch = _on_launch
    before = list(world.launches)
    world.prepared.clear()

    resumed, finalize = _resume(world, tmp_path, snap)

    after = world.launches[len(before):]
    # Same run, nothing duplicated: s1 untouched, s2 gets only its worker,
    # s3 is prepared, refined and launched exactly once.
    assert resumed.loop_id == state.loop_id
    assert after.count(("refiner", "qa-pr-001-s1")) == 0
    assert after.count(("worker", "qa-pr-001-s1")) == 0
    assert after.count(("refiner", "qa-pr-001-s2")) == 0
    assert after.count(("worker", "qa-pr-001-s2")) == 1
    assert after.count(("refiner", "qa-pr-001-s3")) == 1
    assert after.count(("worker", "qa-pr-001-s3")) == 1
    assert world.prepared == [3]
    # s2's worker runs the refined steps the refiner wrote while we were down.
    s2 = next(s for s in resumed.scenarios if s.index == 2)
    assert s2.steps.startswith("GIVEN: x")
    # Results collected, normal finalizer reached once, then done.
    assert resumed.scenario_verdicts == {1: VERDICT_PASS, 2: VERDICT_PASS,
                                         3: VERDICT_PASS}
    assert finalize.call_count == 1
    assert resumed.latest_verdict == VERDICT_PASS
    final = _load_resume_file(state.qa_workdir)
    assert final["phase"] == "done" and final["latest_verdict"] == VERDICT_PASS


def test_restart_adopts_live_refiner_that_finishes_after_restart(
        world, tmp_path):
    (tmp_path / "wd").mkdir()
    state = _new_state(tmp_path)
    snap = _launch_with_restart_point(world, tmp_path, state)
    by = {s["index"]: s for s in snap["scenarios"]}
    world.finish(by[1]["transcript_path"], "PASS", by[1]["session_id"])

    def _late():
        threading.Event().wait(0.2)
        world.finish(world.native_transcript(by[2]["concretize_cwd"],
                                             by[2]["concretize_session_id"]),
                     REFINED, by[2]["concretize_session_id"])

    def _on_launch(kind, window, pane, cmd):
        if kind == "worker":
            sid = cmd.split("--session-id ")[1].split()[0]
            idx = int(window.rsplit("-s", 1)[1])
            world.finish(Path(state.qa_workdir) / f"transcript-s{idx}.jsonl",
                         "PASS", sid)
    world.on_launch = _on_launch
    before = len(world.launches)
    threading.Thread(target=_late, daemon=True).start()
    resumed, _ = _resume(world, tmp_path, snap)
    after = world.launches[before:]
    assert ("refiner", "qa-pr-001-s2") not in after
    assert after.count(("worker", "qa-pr-001-s2")) == 1
    assert set(resumed.scenario_verdicts) == {1, 2, 3}


def test_restart_right_after_worker_split_adopts_that_worker(world, tmp_path):
    """Kill after the worker pane exists but before the snapshot names it:
    the restart finds the pane by its session id instead of launching a
    second worker into the same clone."""
    (tmp_path / "wd").mkdir()
    state = _new_state(tmp_path)
    state.scenarios = state.scenarios[:1]
    snap_at_split = {}

    def _on_launch(kind, window, pane, cmd):
        if kind == "worker":
            snap_at_split.update(_load_resume_file(state.qa_workdir))
    world.on_launch = _on_launch
    qa_loop._launch_scenarios_in_tmux(
        state, {}, PR, "pm-sess", tmp_path / "wd", str(tmp_path / "wd"))
    s = snap_at_split["scenarios"][0]
    assert s["launch_phase"] == "launching" and s["pane_id"] is None
    world.finish(s["transcript_path"], "PASS", s["session_id"])

    world.on_launch = None
    before = len(world.launches)
    resumed, finalize = _resume(world, tmp_path, snap_at_split)
    assert world.launches[before:] == []
    assert resumed.scenario_verdicts == {1: VERDICT_PASS}
    assert finalize.call_count == 1


def test_restart_right_after_relaunch_adopts_relaunched_worker(world, tmp_path):
    """A worker relaunched just before a restart (dead pane still in the
    snapshot) is found by its new session id, not relaunched again."""
    (tmp_path / "wd").mkdir()
    state = _new_state(tmp_path)
    state.scenarios = state.scenarios[:1]
    qa_loop._launch_scenarios_in_tmux(
        state, {}, PR, "pm-sess", tmp_path / "wd", str(tmp_path / "wd"))
    sc = state.scenarios[0]
    world.kill(sc.pane_id)              # the worker died
    snap_at_relaunch = {}

    def _on_launch(kind, window, pane, cmd):
        snap_at_relaunch.update(_load_resume_file(state.qa_workdir))
    world.on_launch = _on_launch
    with patch("pm_core.container.is_container_mode_enabled",
               return_value=False):
        assert qa_loop._relaunch_scenario_window(
            sc, state, {}, PR, "pm-sess", str(tmp_path / "wd"))
    s = snap_at_relaunch["scenarios"][0]
    assert s["session_id"] == sc.session_id          # written ahead
    assert s["pane_id"] is None and s["launch_phase"] == "launching"
    world.finish(sc.transcript_path, "PASS", sc.session_id)

    world.on_launch = None
    before = len(world.launches)
    resumed, _ = _resume(world, tmp_path, snap_at_relaunch)
    assert world.launches[before:] == []
    assert resumed.scenario_verdicts == {1: VERDICT_PASS}


def test_settled_scenarios_are_not_relaunched(world, tmp_path):
    """A scenario that already has a final verdict and a dead pane (e.g.
    retries exhausted) is not polled back into a relaunch on resume."""
    (tmp_path / "wd").mkdir()
    state = _new_state(tmp_path)
    state.scenarios = state.scenarios[:1]
    qa_loop._launch_scenarios_in_tmux(
        state, {}, PR, "pm-sess", tmp_path / "wd", str(tmp_path / "wd"))
    world.kill(state.scenarios[0].pane_id)
    state.scenario_verdicts[1] = "INPUT_REQUIRED"
    qa_loop._checkpoint(state)
    before = len(world.launches)
    resumed, _ = _resume(world, tmp_path, _load_resume_file(state.qa_workdir))
    assert world.launches[before:] == []
    assert resumed.latest_verdict == "INPUT_REQUIRED"


def test_restart_during_finalize_adopts_finalizer(world, tmp_path):
    (tmp_path / "wd").mkdir()
    state = _new_state(tmp_path)
    state.scenarios = state.scenarios[:1]
    state.scenarios[0].launch_phase = "running"
    state.scenarios[0].window_name = "qa-pr-001-s1"
    state.scenario_verdicts = {1: VERDICT_PASS}
    state.verified_scenarios = {1}
    state.latest_verdict = VERDICT_PASS
    world.new_window("pm-sess", "qa-pr-001", "planner --session-id x")
    fsid = str(uuid.uuid4())
    state.finalize_session_id = fsid
    world.split_pane_at(world.windows["qa-pr-001"][0], "v",
                        f"finalizer --session-id {fsid}")
    world.finish(world.native_transcript(str(tmp_path / "wd"), fsid),
                 "FINALIZE_DONE", fsid)
    before = len(world.launches)
    verdict = qa_loop._run_qa_finalize_pane(
        state, PR, "pm-sess", "qa-pr-001", str(tmp_path / "wd"))
    assert verdict == "FINALIZE_DONE"
    assert world.launches[before:] == []


# ---------------------------------------------------------------------------
# TUI: which run is adopted, and when the lifecycle may advance
# ---------------------------------------------------------------------------

def _app(tmp_path):
    app = MagicMock()
    app._root = _pm_root(tmp_path)
    app._qa_loops = {}
    app._resumed_qa_runs = set()
    return app


def _seed(home, name, **fields):
    qa_dir = home / ".pm" / "workdirs" / "qa" / f"pr-001-{name}"
    qa_dir.mkdir(parents=True)
    state = QALoopState(pr_id="pr-001", loop_id=name)
    state.qa_workdir = str(qa_dir)
    state.planning_phase = False
    for k, v in fields.items():
        setattr(state, k, v)
    qa_loop._write_resume_file(state, False, 0)
    return qa_dir


def test_tui_does_not_advance_lifecycle_before_finalizer(world, tmp_path):
    """qa_status.json carries ``overall`` before the finalizer runs; a
    restart then must resume (finalizer), not process completion."""
    qa_dir = _seed(world.home, "fin", run_phase="finalizing",
                   started_at="2026-10-22T01:00:00", latest_verdict="PASS")
    (qa_dir / "qa_status.json").write_text(json.dumps({"overall": "PASS"}))
    app = _app(tmp_path)
    with patch.object(qa_loop, "resume_qa_background") as bg, \
         patch.object(qa_loop_ui, "_on_qa_complete") as done:
        qa_loop_ui._resume_incomplete_qa(app)
    done.assert_not_called()
    bg.assert_called_once()
    assert bg.call_args[0][0].run_phase == "finalizing"


def test_tui_adopts_only_newest_run_and_never_a_cancelled_one(world, tmp_path):
    _seed(world.home, "old", run_phase="executing",
          started_at="2026-10-22T01:00:00")
    _seed(world.home, "new", run_phase="launching",
          started_at="2026-10-22T02:00:00")
    app = _app(tmp_path)
    with patch.object(qa_loop, "resume_qa_background") as bg:
        qa_loop_ui._resume_incomplete_qa(app)
    assert bg.call_count == 1
    assert bg.call_args[0][0].loop_id == "new"

    app = _app(tmp_path)
    qa_loop.mark_resume_cancelled(world.home / ".pm/workdirs/qa/pr-001-new")
    with patch.object(qa_loop, "resume_qa_background") as bg:
        qa_loop_ui._resume_incomplete_qa(app)
    bg.assert_not_called()      # nor the older, replaced run


def test_start_qa_adopts_in_progress_run_instead_of_starting_another(
        world, tmp_path):
    """#234: auto-start / review→qa on a PR whose run survived a restart
    must not start a second run beside the original workers."""
    _seed(world.home, "live", run_phase="launching",
          started_at="2026-10-22T01:00:00")
    app = _app(tmp_path)
    with patch.object(qa_loop, "resume_qa_background") as bg, \
         patch.object(qa_loop_ui, "start_qa_background") as start_bg:
        qa_loop_ui.start_qa(app, "pr-001")
    start_bg.assert_not_called()
    bg.assert_called_once()
    assert app._qa_loops["pr-001"].loop_id == "live"


def test_start_qa_starts_fresh_after_finished_or_cancelled_run(world, tmp_path):
    qa_dir = _seed(world.home, "gone", run_phase="launching",
                   started_at="2026-10-22T01:00:00")
    qa_loop.mark_resume_cancelled(qa_dir)
    app = _app(tmp_path)
    with patch.object(qa_loop, "resume_qa_background") as bg, \
         patch.object(qa_loop_ui, "start_qa_background") as start_bg:
        qa_loop_ui.start_qa(app, "pr-001")
    bg.assert_not_called()
    start_bg.assert_called_once()


def test_stop_marks_snapshot_cancelled_immediately(world, tmp_path):
    qa_dir = _seed(world.home, "stop", run_phase="executing",
                   started_at="2026-10-22T01:00:00")
    app = _app(tmp_path)
    state = QALoopState(pr_id="pr-001", running=True)
    state.qa_workdir = str(qa_dir)
    app._qa_loops["pr-001"] = state
    qa_loop_ui.stop_qa(app, "pr-001")
    assert _load_resume_file(qa_dir)["cancelled"] is True


def test_legacy_snapshot_still_resumes(world, tmp_path):
    """Snapshots written before phases existed resume as before."""
    qa_dir = world.home / ".pm" / "workdirs" / "qa" / "pr-001-legacy"
    qa_dir.mkdir(parents=True)
    (qa_dir / "qa_resume.json").write_text(json.dumps({
        "pr_id": "pr-001", "loop_id": "legacy", "qa_workdir": str(qa_dir),
        "queued_indices": [2],
        "scenarios": [{"index": 1, "window_name": "w1"},
                      {"index": 2}, {"index": 3}],
    }))
    state = build_resume_state(_load_resume_file(qa_dir))
    assert state.run_phase == "executing"
    assert [s.launch_phase for s in state.scenarios] == [
        "running", "queued", "settled"]


# ---------------------------------------------------------------------------
# Restart during planning
# ---------------------------------------------------------------------------

PLAN = ("QA_PLAN_START\n\n"
        "SCENARIO 1: Alpha\nFOCUS: a\nSTEPS: do a\n\n"
        "SCENARIO 2: Beta\nFOCUS: b\nSTEPS: do b\n\n"
        "QA_PLAN_END\n")


def _planning_snapshot(world, tmp_path, planner_alive: bool):
    state = QALoopState(pr_id="pr-001", loop_id="plan1")
    state.qa_workdir = str(tmp_path / "qa")
    Path(state.qa_workdir).mkdir(parents=True)
    state.session_tag = "tag"
    state.run_phase = "planning"
    state.started_at = "2026-10-22T00:00:00+00:00"
    state.planner_session_id = str(uuid.uuid4())
    state.scenario_start = 1
    if planner_alive:
        world.new_window("pm-sess", "qa-pr-001",
                         f"planner --session-id {state.planner_session_id}")
    qa_loop._checkpoint(state)
    return _load_resume_file(state.qa_workdir)


@pytest.fixture
def planning_env(world, monkeypatch):
    monkeypatch.setattr(qa_loop, "_get_qa_spec", lambda pr, phase: "spec")
    monkeypatch.setattr(qa_loop, "_publish_planner_head",
                        lambda wd, branch: "c" * 40)
    monkeypatch.setattr(qa_loop, "_planner_code_changes", lambda *a: [])
    monkeypatch.setattr(qa_loop, "_rev_parse", lambda *a: "c" * 40)

    def _on_launch(kind, window, pane, cmd):
        if kind == "worker":
            sid = cmd.split("--session-id ")[1].split()[0]
            idx = int(window.rsplit("-s", 1)[1])
            world.finish(world._qa_dir / f"transcript-s{idx}.jsonl",
                         "PASS", sid)
    world.on_launch = _on_launch
    return world


def test_restart_during_planning_adopts_plan_emitted_while_down(
        planning_env, tmp_path):
    world = planning_env
    (tmp_path / "wd").mkdir()
    snap = _planning_snapshot(world, tmp_path, planner_alive=False)
    world._qa_dir = tmp_path / "qa"
    world.finish(world.native_transcript(str(tmp_path / "wd"),
                                         snap["planner_session_id"]),
                 PLAN, snap["planner_session_id"])
    before = len(world.launches)
    resumed, finalize = _resume(world, tmp_path, snap)
    kinds = [k for k, _ in world.launches[before:]]
    assert "planner" not in kinds          # no second planner
    assert kinds.count("refiner") == 2 and kinds.count("worker") == 2
    assert resumed.loop_id == "plan1"
    assert resumed.scenario_verdicts == {1: VERDICT_PASS, 2: VERDICT_PASS}
    assert finalize.call_count == 1


def test_restart_during_planning_without_plan_does_not_replan(
        planning_env, tmp_path):
    world = planning_env
    (tmp_path / "wd").mkdir()
    snap = _planning_snapshot(world, tmp_path, planner_alive=False)
    before = len(world.launches)
    resumed, finalize = _resume(world, tmp_path, snap)
    # Only the status window that shows the error; no planner or workers.
    assert [k for k, _ in world.launches[before:]] in ([], ["echo"])
    assert resumed.latest_verdict == "INPUT_REQUIRED"
    assert "during a restart" in resumed.latest_output
    finalize.assert_not_called()
    assert _load_resume_file(tmp_path / "qa")["phase"] == "done"


def test_resume_claims_ownership_before_blocking_on_adopted_refiner(
        world, tmp_path):
    """While an adopted refiner is still running, the snapshot must already
    name the resuming process as owner (not the dead controller)."""
    (tmp_path / "wd").mkdir()
    state = _new_state(tmp_path)
    snap = _launch_with_restart_point(world, tmp_path, state)
    snap["owner_pid"] = 999_999_999          # the killed controller
    by = {s["index"]: s for s in snap["scenarios"]}
    world.finish(by[1]["transcript_path"], "PASS", by[1]["session_id"])
    owners = []
    real_await = qa_loop._await_adopted_session

    def _await(*a, **k):
        owners.append(_load_resume_file(state.qa_workdir)["owner_pid"])
        world.finish(world.native_transcript(by[2]["concretize_cwd"],
                                             by[2]["concretize_session_id"]),
                     REFINED, by[2]["concretize_session_id"])
        return real_await(*a, **k)

    def _on_launch(kind, window, pane, cmd):
        if kind == "worker":
            sid = cmd.split("--session-id ")[1].split()[0]
            idx = int(window.rsplit("-s", 1)[1])
            world.finish(Path(state.qa_workdir) / f"transcript-s{idx}.jsonl",
                         "PASS", sid)
    world.on_launch = _on_launch
    with patch.object(qa_loop, "_await_adopted_session", _await):
        _resume(world, tmp_path, snap)
    assert owners == [os.getpid()]
