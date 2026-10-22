"""Nonblocking, per-scenario QA worker launch retries (pr-1ab9075).

One scenario whose worker cannot be created, dies before Claude starts
(e.g. ``podman exec`` failing on PID or keyring exhaustion) or exits
mid-run must be retried on its own bounded backoff without holding up
verdict collection, verification, queued launches or a stop request for
the other scenarios.  Failures here are synthetic and bounded — no real
fork storm or quota exhaustion.
"""

import json
import os
import subprocess
import threading
import time
from contextlib import ExitStack
from unittest.mock import patch

from pm_core import container as container_mod
from pm_core import qa_status
from pm_core.qa_loop import (
    QALoopState,
    QAScenario,
    VERDICT_INPUT_REQUIRED,
    VERDICT_NEEDS_WORK,
    VERDICT_PASS,
    _POLL_INTERVAL,
    _SCENARIO_MAX_RETRIES,
    _SCENARIO_RETRY_MAX_DELAY,
    _VERDICT_GRACE_PERIOD,
    _launch_scenarios_in_tmux,
    _load_resume_file,
    _poll_tmux_verdicts,
    _relaunch_scenario_window,
    _retry_delay,
    _write_resume_file,
    _write_status_file,
    build_resume_state,
)

_real_sleep = time.sleep

PID_STDERR = ("Error: crun: fork: Resource temporarily unavailable: "
              "OCI runtime error\nbash: Cannot fork")
KEYRING_STDERR = ("Error: unable to start container process: unable to join "
                  "session keyring: unable to create session key: disk quota "
                  "exceeded")


class FakeClock:
    """Wall + monotonic clock advanced only by the poll loop's sleeps.

    Before advancing, each sleep lets in-flight background ``qa-*`` threads
    (launch / diagnosis / verification) finish so ticks are deterministic.
    """

    def __init__(self, on_tick=None):
        self.start = self.t = 1_000_000.0
        self.sleeps: list[float] = []
        self.on_tick = on_tick

    def now(self) -> float:
        return self.t

    def sleep(self, secs: float) -> None:
        self.sleeps.append(secs)
        for th in threading.enumerate():
            if th is not threading.current_thread() and th.name.startswith("qa-"):
                th.join(0.2)
        self.t += secs
        if self.on_tick:
            self.on_tick(self)
        if len(self.sleeps) > 2000:
            raise RuntimeError("poll loop never finished")


def _idle(sid: str) -> dict:
    return {"event_type": "idle_prompt", "timestamp": 1.0, "session_id": sid}


def _base_patches(clock, events: dict, verdicts: dict, verify: bool = False):
    return [
        patch("pm_core.qa_loop.time.sleep", clock.sleep),
        patch("pm_core.qa_loop.time.time", clock.now),
        patch("pm_core.qa_loop.time.monotonic", clock.now),
        patch("pm_core.hook_events.read_event",
              side_effect=lambda sid: events.get(sid)),
        patch("pm_core.qa_loop.extract_verdict_from_transcript",
              side_effect=lambda tp, _v: verdicts.get(tp)),
        patch("pm_core.qa_loop.extract_verdict_reason_from_transcript",
              return_value=""),
        patch("pm_core.qa_loop._is_verification_enabled", return_value=verify),
        patch("pm_core.container._get_runtime", return_value="podman"),
    ]


def _run(state, tmp_path, patches, **kw):
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        _poll_tmux_verdicts(state, {}, {}, "sess", str(tmp_path),
                            tmp_path / "qa_status.json", lambda *a: None, **kw)


def _runtime(stderr: str):
    """Fake ``_run_runtime``: the container is running but exec fails."""
    def _fake(*args, check=True, timeout=None):
        if args[0] == "inspect":
            return subprocess.CompletedProcess(args, 0, "running\n", "")
        return subprocess.CompletedProcess(args, 1, "", stderr)
    return _fake


# ---------------------------------------------------------------------------
# The regression: dead worker vs PASS + NEEDS_WORK siblings
# ---------------------------------------------------------------------------

def test_dead_worker_backoff_does_not_block_healthy_verdicts(tmp_path):
    dead = QAScenario(index=1, title="dead", focus="f", window_name="qa-x-s1",
                      pane_id="%1", session_id="sid-1",
                      container_name="pm-qa-x-s1")
    ok = QAScenario(index=2, title="pass", focus="f", window_name="qa-x-s2",
                    pane_id="%2", session_id="sid-2", transcript_path="/t/s2")
    nw = QAScenario(index=3, title="nw", focus="f", window_name="qa-x-s3",
                    pane_id="%3", session_id="sid-3", transcript_path="/t/s3")
    state = QALoopState(pr_id="pr-x")
    state.scenarios = [dead, ok, nw]

    clock = FakeClock()
    relaunches: list[float] = []
    verified_at: list[float] = []

    def fake_relaunch(scenario, st, *a):
        assert scenario is dead
        relaunches.append(clock.t)
        # The new window is created, but exec dies again at once.
        scenario.pane_id = f"%1r{len(relaunches)}"
        scenario.session_id = f"sid-1r{len(relaunches)}"
        return True

    def fake_verify(scenario, verdict, *a, **kw):
        verified_at.append(clock.t)
        return True, "exercised", None

    patches = _base_patches(
        clock, {"sid-2": _idle("sid-2"), "sid-3": _idle("sid-3")},
        {"/t/s2": VERDICT_PASS, "/t/s3": VERDICT_NEEDS_WORK}, verify=True) + [
        patch("pm_core.tmux.pane_exists",
              side_effect=lambda pid: not pid.startswith("%1")),
        patch("pm_core.qa_loop._relaunch_scenario_window",
              side_effect=fake_relaunch),
        patch("pm_core.qa_loop._verify_single_scenario",
              side_effect=fake_verify),
        patch("pm_core.container._run_runtime", side_effect=_runtime(PID_STDERR)),
    ]
    _run(state, tmp_path, patches)

    # Healthy verdicts and verification advanced on their own schedule.
    assert state.scenario_verdicts[2] == VERDICT_PASS
    assert state.verified_scenarios == {2}
    assert state.scenario_verdicts[3] == VERDICT_NEEDS_WORK
    assert verified_at[0] - clock.start <= _VERDICT_GRACE_PERIOD + 3 * _POLL_INTERVAL
    # …while the dead worker was still inside its retry schedule.
    assert any(t > verified_at[0] for t in relaunches)
    # The loop never blocked for longer than one poll interval.
    assert max(clock.sleeps) == _POLL_INTERVAL

    # Bounded retries, with non-decreasing capped gaps.
    assert len(relaunches) == _SCENARIO_MAX_RETRIES
    gaps = [b - a for a, b in zip(relaunches, relaunches[1:])]
    assert gaps == sorted(gaps)
    assert max(gaps) <= _SCENARIO_RETRY_MAX_DELAY + 3 * _POLL_INTERVAL

    # The runtime cause is surfaced, not a bare request for judgment.
    assert state.scenario_verdicts[1] == VERDICT_INPUT_REQUIRED
    reason = state.scenario_verdict_reasons[1]
    assert "not an agent verdict" in reason
    assert "PID" in reason
    assert "podman restart pm-qa-x-s1" in reason
    assert state.launch_retries[1]["kind"] == "exec"
    status = json.loads((tmp_path / "qa_status.json").read_text())
    s1 = next(s for s in status["scenarios"] if s["index"] == 1)
    assert s1["verdict"] == VERDICT_INPUT_REQUIRED
    assert "PID" in s1["verdict_reason"]


def test_stop_during_backoff_returns_on_next_tick(tmp_path):
    """A stop request is honoured within one poll interval even while a
    scenario waits out a long backoff, and nothing is relaunched."""
    sc = QAScenario(index=1, title="dead", focus="f", window_name="qa-x-s1",
                    pane_id="%1", session_id="sid-1")
    state = QALoopState(pr_id="pr-x")
    state.scenarios = [sc]

    def on_tick(clock):
        if len(clock.sleeps) == 2:
            state.stop_requested = True

    clock = FakeClock(on_tick)
    state.launch_retries = {1: {"attempts": 5, "kind": "exec", "cause": "x",
                                "state": "waiting", "sessions": [],
                                "retry_at": clock.t + 300}}
    patches = _base_patches(clock, {}, {}) + [
        patch("pm_core.tmux.pane_exists", return_value=False)]
    with patch("pm_core.qa_loop._relaunch_scenario_window") as relaunch:
        _run(state, tmp_path, patches)

    assert len(clock.sleeps) == 2
    relaunch.assert_not_called()
    assert 1 not in state.scenario_verdicts


def test_relaunch_after_stop_creates_no_window():
    sc = QAScenario(index=1, title="t", focus="f", container_name="c")
    state = QALoopState(pr_id="pr-x")
    state.stop_requested = True
    with patch("pm_core.tmux.new_window_get_pane") as new_window:
        assert _relaunch_scenario_window(sc, state, {}, {}, "sess", "/w") is False
    new_window.assert_not_called()


def test_launcher_skips_worker_split_after_stop(tmp_path):
    """A background launch whose concretizer finishes after a stop must not
    split a worker pane."""
    sc = QAScenario(index=4, title="t", focus="f")
    state = QALoopState(pr_id="pr-x")
    state.qa_workdir = str(tmp_path)
    state.scenarios = [sc]

    def concretize(*a, **kw):
        state.stop_requested = True
        return None, None

    with patch("pm_core.qa_loop._resolve_qa_model"), \
         patch("pm_core.qa_loop.create_scenario_workdir",
               return_value=(tmp_path / "repo", tmp_path / "scratch")), \
         patch("pm_core.qa_loop._build_concretize_cmd", return_value="cmd"), \
         patch("pm_core.tmux.new_window_get_pane", return_value="%9"), \
         patch("pm_core.qa_loop._concretize_scenario",
               side_effect=concretize) as concretizer, \
         patch("pm_core.tmux.split_pane_at") as split:
        _launch_scenarios_in_tmux(state, {}, {"id": "pr-x"}, "sess", None,
                                  str(tmp_path), scenarios=[sc],
                                  write_status=False)
    concretizer.assert_called_once()
    split.assert_not_called()
    assert sc.pane_id is None


# ---------------------------------------------------------------------------
# Failure kinds: creation (no pane), exec before start, exit after start
# ---------------------------------------------------------------------------

def test_no_pane_create_failure_is_retried_until_launch_succeeds(tmp_path):
    """#239: container creation hit key EDQUOT before any pane existed.
    The scenario is retried through the full launcher once quota recovers
    instead of being written off as INPUT_REQUIRED."""
    sc = QAScenario(index=1, title="t", focus="f")
    state = QALoopState(pr_id="pr-x")
    state.scenarios = [sc]
    keyring = container_mod.classify_runtime_error(KEYRING_STDERR)
    state.scenario_verdict_reasons[1] = f"container create failed: {keyring}"
    calls = []
    seen_status = []

    def fake_launch(st, data, pr_data, session, repo_root, wd, pm_root=None,
                    scenarios=None, write_status=True, **kw):
        calls.append((list(scenarios), write_status))
        target = scenarios[0]
        if len(calls) < 3:
            st.scenario_verdict_reasons[target.index] = (
                f"container create failed: {keyring}")
            return
        target.window_name = "qa-x-s1"
        target.pane_id = "%5"
        target.session_id = "sid-new"
        target.transcript_path = "/t/s1"

    def on_tick(clock):
        path = tmp_path / "qa_status.json"
        if path.exists():
            seen_status.append(json.loads(path.read_text())["scenarios"][0])

    clock = FakeClock(on_tick)
    patches = _base_patches(clock, {"sid-new": _idle("sid-new")},
                            {"/t/s1": VERDICT_PASS}) + [
        patch("pm_core.tmux.pane_exists", return_value=True),
        patch("pm_core.qa_loop._launch_scenarios_in_containers",
              side_effect=fake_launch),
    ]
    _run(state, tmp_path, patches, use_containers=True)

    assert len(calls) == 3
    assert all(scs == [sc] and ws is False for scs, ws in calls)
    assert state.scenario_verdicts[1] == VERDICT_PASS
    # The launch error does not linger beside the real verdict.
    assert "keyring" not in state.scenario_verdict_reasons.get(1, "")
    assert state.launch_retries[1]["attempts"] == 3
    assert state.launch_retries[1]["kind"] == "create"
    retrying = [s for s in seen_status if "(launch-retry" in s["verdict"]]
    assert retrying and "keyring quota exhausted" in retrying[0]["verdict_reason"]


def test_exec_and_exit_failures_are_distinguished(tmp_path):
    started = QAScenario(index=1, title="ran", focus="f", window_name="w1",
                         pane_id="%1", session_id="sid-1",
                         transcript_path=str(tmp_path / "t1.jsonl"))
    (tmp_path / "t1.jsonl").write_text("{}\n")
    # Transcript symlink exists but Claude never wrote its target.
    os.symlink(tmp_path / "missing.jsonl", tmp_path / "t2.jsonl")
    never = QAScenario(index=2, title="never", focus="f", window_name="w2",
                       pane_id="%2", session_id="sid-2",
                       transcript_path=str(tmp_path / "t2.jsonl"))
    state = QALoopState(pr_id="pr-x")
    state.scenarios = [started, never]

    def on_tick(clock):
        if len(clock.sleeps) == 1:
            state.stop_requested = True

    clock = FakeClock(on_tick)
    patches = _base_patches(clock, {}, {}) + [
        patch("pm_core.tmux.pane_exists", return_value=False)]
    _run(state, tmp_path, patches)

    assert state.launch_retries[1]["kind"] == "exit"
    assert "mid-run" in state.launch_retries[1]["cause"]
    assert state.launch_retries[1]["sessions"] == ["sid-1"]
    assert state.launch_retries[2]["kind"] == "exec"
    assert "at startup" in state.launch_retries[2]["cause"]
    assert all(r["state"] == "waiting" for r in state.launch_retries.values())
    assert not state.scenario_verdicts


def test_container_exit_mid_run_names_diagnosed_cause(tmp_path):
    """A started container worker that dies mid-run (the #236 fork storm)
    is an ``exit`` failure, but still carries the probed runtime cause."""
    tp = tmp_path / "t1.jsonl"
    tp.write_text("{}\n")
    sc = QAScenario(index=1, title="ran", focus="f", window_name="w1",
                    pane_id="%1", session_id="sid-1", transcript_path=str(tp),
                    container_name="pm-qa-x-s1")
    state = QALoopState(pr_id="pr-x")
    state.scenarios = [sc]

    def on_tick(clock):
        if state.launch_retries:
            state.stop_requested = True

    clock = FakeClock(on_tick)
    patches = _base_patches(clock, {}, {}) + [
        patch("pm_core.tmux.pane_exists", return_value=False),
        patch("pm_core.container._run_runtime", side_effect=_runtime(PID_STDERR)),
    ]
    _run(state, tmp_path, patches)

    rec = state.launch_retries[1]
    assert rec["kind"] == "exit"
    assert "PID" in rec["cause"] and "podman restart pm-qa-x-s1" in rec["cause"]


# ---------------------------------------------------------------------------
# Restart and queue interplay
# ---------------------------------------------------------------------------

def test_restart_preserves_results_and_retry_state(tmp_path):
    clock = FakeClock()
    dead = QAScenario(index=1, title="dead", focus="f", window_name="w1",
                      pane_id="%1", session_id="sid-old")
    done = QAScenario(index=2, title="done", focus="f", window_name="w2",
                      pane_id="%2", session_id="sid-2", transcript_path="/t/s2")
    state = QALoopState(pr_id="pr-x")
    state.qa_workdir = str(tmp_path)
    state.scenarios = [dead, done]
    state.scenario_verdicts = {2: VERDICT_NEEDS_WORK}
    state.scenario_verdict_reasons = {2: "found and fixed a bug"}
    state.launch_retries = {1: {"attempts": 4, "kind": "exec", "cause": "boom",
                                "state": "waiting", "retry_at": clock.t - 1,
                                "sessions": ["sid-older"]}}
    _write_resume_file(state, use_containers=False, concurrency_cap=0)

    restored = build_resume_state(_load_resume_file(tmp_path))
    assert restored.launch_retries == state.launch_retries
    assert restored.scenario_verdicts == {2: VERDICT_NEEDS_WORK}

    relaunched = []

    def fake_relaunch(scenario, st, *a):
        relaunched.append(scenario.index)
        scenario.pane_id = f"%1r{len(relaunched)}"
        scenario.session_id = f"sid-r{len(relaunched)}"
        return True

    patches = _base_patches(clock, {}, {}) + [
        # Both old panes died with the previous controller.
        patch("pm_core.tmux.pane_exists", return_value=False),
        patch("pm_core.qa_loop._relaunch_scenario_window",
              side_effect=fake_relaunch),
    ]
    _run(restored, tmp_path, patches)

    # Retry budget continued from the snapshot; the finished worker was
    # never relaunched and kept its result.
    assert relaunched == [1] * (_SCENARIO_MAX_RETRIES - 4)
    assert restored.scenario_verdicts[2] == VERDICT_NEEDS_WORK
    assert restored.scenario_verdict_reasons[2] == "found and fixed a bug"
    assert restored.scenario_verdicts[1] == VERDICT_INPUT_REQUIRED
    assert "sid-older" in restored.launch_retries[1]["sessions"]
    snap = _load_resume_file(tmp_path)
    assert snap["launch_retries"]["1"]["attempts"] == _SCENARIO_MAX_RETRIES


def test_queued_launch_runs_off_the_poll_thread(tmp_path):
    """A slow dequeued launch (concretizer still running) does not stall
    verdict collection for running scenarios."""
    running = QAScenario(index=1, title="run", focus="f", window_name="w1",
                         pane_id="%1", session_id="sid-1", transcript_path="/t/s1")
    queued = QAScenario(index=2, title="q", focus="f")
    state = QALoopState(pr_id="pr-x")
    state.scenarios = [running, queued]
    outcome = {}

    def slow_launch(st, data, pr_data, session, repo_root, wd, pm_root=None,
                    scenarios=None, write_status=True, **kw):
        deadline = time.monotonic_ns() + 5_000_000_000
        while 1 not in st.scenario_verdicts and time.monotonic_ns() < deadline:
            _real_sleep(0.01)
        outcome["saw_verdict_first"] = 1 in st.scenario_verdicts
        sc = scenarios[0]
        sc.window_name, sc.pane_id = "w2", "%2"
        sc.session_id, sc.transcript_path = "sid-2", "/t/s2"

    clock = FakeClock()
    patches = _base_patches(
        clock, {"sid-1": _idle("sid-1"), "sid-2": _idle("sid-2")},
        {"/t/s1": VERDICT_PASS, "/t/s2": VERDICT_NEEDS_WORK}) + [
        patch("pm_core.tmux.pane_exists", return_value=True),
        patch("pm_core.qa_loop._launch_scenarios_in_tmux",
              side_effect=slow_launch),
    ]
    _run(state, tmp_path, patches, queued_scenarios=[queued],
         concurrency_cap=2)

    assert outcome["saw_verdict_first"] is True
    assert state.scenario_verdicts == {1: VERDICT_PASS, 2: VERDICT_NEEDS_WORK}


def test_status_shows_window_of_inflight_launch(tmp_path):
    """The status file picks up a dequeued scenario's concretizer window
    while its launch is still running, so the dashboard can navigate to it."""
    queued = QAScenario(index=2, title="q", focus="f")
    state = QALoopState(pr_id="pr-x")
    state.scenarios = [queued]
    status = tmp_path / "qa_status.json"
    seen = {}

    def slow_launch(st, data, pr_data, session, repo_root, wd, pm_root=None,
                    scenarios=None, write_status=True, **kw):
        sc = scenarios[0]
        sc.window_name = "w2"  # concretizer window up, worker not yet
        deadline = time.monotonic_ns() + 5_000_000_000
        while time.monotonic_ns() < deadline:
            try:
                rows = json.loads(status.read_text())["scenarios"]
            except (OSError, ValueError):
                rows = []
            if any(r["index"] == 2 and r["window_name"] == "w2" for r in rows):
                seen["window"] = True
                break
            _real_sleep(0.01)
        sc.pane_id, sc.session_id, sc.transcript_path = "%2", "sid-2", "/t/s2"

    clock = FakeClock()
    patches = _base_patches(clock, {"sid-2": _idle("sid-2")},
                            {"/t/s2": VERDICT_PASS}) + [
        patch("pm_core.tmux.pane_exists", return_value=True),
        patch("pm_core.qa_loop._launch_scenarios_in_tmux",
              side_effect=slow_launch),
    ]
    _run(state, tmp_path, patches, queued_scenarios=[queued],
         concurrency_cap=1)

    assert seen.get("window") is True
    assert state.scenario_verdicts == {2: VERDICT_PASS}


def test_create_retry_tears_down_previous_attempt(tmp_path):
    """The worker split failed after the container and concretizer window
    were created.  The full relaunch re-clones the scenario dir, so it must
    first remove the old container (create_container would otherwise reuse
    it, still mounting the deleted clone) and the leftover window."""
    sc = QAScenario(index=1, title="t", focus="f", window_name="qa-x-s1",
                    container_name="pm-qa-x-1")
    state = QALoopState(pr_id="pr-x")
    state.scenarios = [sc]
    state.scenario_verdict_reasons[1] = "worker pane creation failed: boom"
    seen_at_launch = []
    killed, removed = [], []

    def fake_launch(st, data, pr_data, session, repo_root, wd, pm_root=None,
                    scenarios=None, write_status=True, **kw):
        target = scenarios[0]
        seen_at_launch.append((target.window_name, target.container_name))
        target.window_name, target.container_name = "qa-x-s1", "pm-qa-x-1"
        target.pane_id, target.session_id = "%5", "sid-new"
        target.transcript_path = "/t/s1"

    clock = FakeClock()
    patches = _base_patches(clock, {"sid-new": _idle("sid-new")},
                            {"/t/s1": VERDICT_PASS}) + [
        patch("pm_core.tmux.pane_exists", return_value=True),
        # A dead relaunch can leave two windows with the scenario's name.
        patch("pm_core.tmux.list_windows", return_value=[
            {"id": "@1", "index": "1", "name": "qa-x-s1"},
            {"id": "@2", "index": "2", "name": "other"},
            {"id": "@3", "index": "3", "name": "qa-x-s1"}]),
        patch("pm_core.home_window.park_if_on"),
        patch("pm_core.tmux.kill_window",
              side_effect=lambda s, w: killed.append(w)),
        patch("pm_core.container.remove_container", side_effect=removed.append),
        patch("pm_core.qa_loop._launch_scenarios_in_containers",
              side_effect=fake_launch),
    ]
    _run(state, tmp_path, patches, use_containers=True)

    assert killed == ["@1", "@3"]
    assert removed == ["pm-qa-x-1"]
    assert seen_at_launch == [(None, None)]
    assert state.launch_retries[1]["kind"] == "create"
    assert state.scenario_verdicts[1] == VERDICT_PASS


# ---------------------------------------------------------------------------
# Display, bounds and runtime-cause classification
# ---------------------------------------------------------------------------

def test_status_shows_launch_retry_as_non_verdict(tmp_path):
    a = QAScenario(index=1, title="a", focus="f")
    b = QAScenario(index=2, title="b", focus="f")
    path = tmp_path / "qa_status.json"
    _write_status_file(path, "pr-x", [a, b], {2: VERDICT_PASS},
                       launch_retries={1: {
                           "attempts": 1, "state": "waiting", "kind": "exec",
                           "cause": "container process (PID) limit exhausted",
                           "retry_at": time.time() + 10}})
    data = json.loads(path.read_text())
    s1 = data["scenarios"][0]
    assert s1["verdict"] == f"(launch-retry:2/{_SCENARIO_MAX_RETRIES})"
    assert s1["verdict_reason"].startswith(
        "worker exited before Claude started: container process (PID)")
    out = qa_status._render(data, 0, 40, 140)
    assert f"launch retry 2/{_SCENARIO_MAX_RETRIES}" in out
    assert "Progress: 1/2 scenarios complete" in out
    assert "1 relaunching" in out


def test_retry_delays_are_bounded():
    delays = [_retry_delay(n) for n in range(_SCENARIO_MAX_RETRIES)]
    assert delays == [5, 10, 20, 40, 80, 160]
    assert _retry_delay(30) == _SCENARIO_RETRY_MAX_DELAY
    assert sum(delays) < 10 * 60


def test_classify_runtime_error():
    keyring = container_mod.classify_runtime_error(KEYRING_STDERR)
    assert "keyring quota exhausted" in keyring and "maxkeys" in keyring
    # crun (podman's default runtime) words the same EDQUOT differently.
    crun = ("Error: OCI runtime error: crun: create keyring `abc123`: "
            "Disk quota exceeded")
    assert "keyring quota exhausted" in container_mod.classify_runtime_error(crun)
    # A filesystem quota is not a keyring problem.
    assert container_mod.classify_runtime_error(
        "write /var/lib/x: disk quota exceeded") is None
    with patch("pm_core.container._get_runtime", return_value="podman"):
        pid = container_mod.classify_runtime_error(PID_STDERR, "pm-c")
    assert "PID" in pid and "podman restart pm-c" in pid
    assert container_mod.classify_runtime_error("no such image") is None
    assert container_mod.runtime_error_summary("a\n\nb\nno such image") == \
        "b | no such image"


def test_launch_error_summary_prefers_runtime_stderr():
    exc = subprocess.CalledProcessError(125, ["podman", "run"],
                                        output="", stderr=KEYRING_STDERR)
    assert "keyring quota exhausted" in container_mod.launch_error_summary(exc)
    assert container_mod.launch_error_summary(
        container_mod.ContainerError("setup timed out")) == "setup timed out"


def test_diagnose_exec_failure():
    with patch("pm_core.container._get_runtime", return_value="podman"), \
         patch("pm_core.container._run_runtime", side_effect=_runtime(PID_STDERR)):
        assert "PID" in container_mod.diagnose_exec_failure("pm-c")

    def stopped(*args, **kw):
        return subprocess.CompletedProcess(args, 0, "exited\n", "")
    with patch("pm_core.container._run_runtime", side_effect=stopped):
        assert container_mod.diagnose_exec_failure("pm-c") == \
            "container pm-c is exited"

    def healthy(*args, **kw):
        out = "running\n" if args[0] == "inspect" else ""
        return subprocess.CompletedProcess(args, 0, out, "")
    with patch("pm_core.container._run_runtime", side_effect=healthy):
        assert container_mod.diagnose_exec_failure("pm-c") == ""

    def hung(*args, **kw):
        raise subprocess.TimeoutExpired(args, 10)
    with patch("pm_core.container._run_runtime", side_effect=hung):
        assert "timed out" in container_mod.diagnose_exec_failure("pm-c")
