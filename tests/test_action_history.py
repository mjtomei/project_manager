"""Tests for the PR action-history journal, query model, CLI and pane entry."""

import json
import multiprocessing
import os
import socket
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pm_core import action_history as ah
from pm_core import history_query as hq
from pm_core import runtime_state as rs
from pm_core import store

PR = "pr-001"
T0 = 1_800_000_000.0


class FakeClock:
    def __init__(self, t: float = T0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


@pytest.fixture
def clock():
    c = FakeClock()
    with ah.use_clock(c):
        yield c


def _dead_owner():
    return {"pid": 999_999, "start": "dead:1", "host": socket.gethostname()}


def _attempts(pr_id=PR):
    """{attempt id: start event} in journal order."""
    return {e["attempt"]: e for e in ah.read_events(pr_id)
            if e["kind"] == "attempt_start"}


def _ends(pr_id=PR):
    return {e["attempt"]: e for e in ah.read_events(pr_id)
            if e["kind"] == "attempt_end"}


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------

class TestJournal:
    def test_record_and_read_roundtrip(self, clock):
        a = ah.start_attempt(PR, "review", label="x")
        clock.advance(5)
        ah.end_attempt(PR, a, "done", verdict="PASS")
        evs = ah.read_events(PR)
        assert [e["kind"] for e in evs] == ["attempt_start", "attempt_end"]
        assert evs[0]["t"] == T0 and evs[1]["t"] == T0 + 5
        assert evs[1]["verdict"] == "PASS"
        assert evs[0]["owner"]["pid"] > 0

    def test_garbage_lines_are_skipped(self, clock):
        ah.start_attempt(PR, "review")
        with open(ah.journal_path(PR), "a") as f:
            f.write("{not json\n\n")
        ah.start_attempt(PR, "merge")
        assert [e["action"] for e in ah.read_events(PR)] == ["review", "merge"]

    def test_write_failure_never_raises(self, tmp_path, monkeypatch):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        monkeypatch.setattr(ah, "history_dir", lambda: blocker / "sub")
        aid = ah.start_attempt(PR, "review")  # must not raise
        assert aid
        ah.arm_timer(PR, "t", purpose="p", owner_action="review", duration=1)
        assert ah.read_events(PR) == []

    def test_rotation_keeps_one_generation(self, clock, monkeypatch):
        monkeypatch.setattr(ah, "MAX_JOURNAL_BYTES", 2000)
        for i in range(40):
            ah.start_attempt(PR, "review", label=f"n{i}")
        assert ah.journal_path(PR).with_name(f"{PR}.1.jsonl").exists()
        labels = [e["label"] for e in ah.read_events(PR)]
        assert labels[-1] == "n39"
        assert len(labels) == len(set(labels))

    def test_stale_writer_does_not_rotate_over_old_generation(
            self, clock, monkeypatch):
        """A writer whose fd points at an already-rotated file must not
        rotate the fresh journal over the previous generation."""
        path = ah.journal_path(PR)
        rotated = path.with_name(f"{PR}.1.jsonl")
        real_open = os.open
        stale = {}

        def _open(p, flags, *a):
            # The first write past the limit opens the file, then another
            # writer rotates it and starts a fresh journal before it locks.
            fd = real_open(p, flags, *a)
            if stale.get("arm") and str(p) == str(path):
                stale["arm"] = False
                os.replace(path, rotated)
                path.write_text("")
                ah.record(PR, "attempt_start", attempt="fresh",
                          action="review")
            return fd

        for i in range(12):
            ah.start_attempt(PR, "review", label=f"n{i}")
        assert not rotated.exists()
        # The next write crosses the limit.
        monkeypatch.setattr(ah, "MAX_JOURNAL_BYTES", path.stat().st_size + 1)
        stale["arm"] = True
        monkeypatch.setattr(ah.os, "open", _open)
        ah.start_attempt(PR, "review", label="late")
        monkeypatch.setattr(ah.os, "open", real_open)
        labels = [e.get("label") for e in ah.read_events(PR)]
        assert [f"n{i}" for i in range(12)] == labels[:12]
        assert "late" in labels and any(
            e["attempt"] == "fresh" for e in ah.read_events(PR))

    def test_concurrent_writers_never_interleave(self, clock):
        ctx = multiprocessing.get_context("fork")

        def _writer(n):
            for i in range(150):
                ah.start_attempt(PR, "qa", scenario=n, label="x" * 300)

        procs = [ctx.Process(target=_writer, args=(n,)) for n in range(4)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(30)
        evs = ah.read_events(PR)
        assert len(evs) == 600
        assert len({e["attempt"] for e in evs}) == 600
        assert len({e["owner"]["pid"] for e in evs}) == 4

    def test_exec_restart_releases_owner(self):
        """An in-place exec keeps pid + start time but not the owner lock."""
        import os
        import subprocess
        import sys
        code = ("import json, pathlib; "
                "from pm_core import action_history as ah; "
                "ah.history_dir = lambda: pathlib.Path(%r); "
                "print(json.dumps(ah.owner_token()))")
        d = str(ah.history_dir())
        out = subprocess.run([sys.executable, "-c", code % d],
                             capture_output=True, text=True,
                             env={**os.environ, "PYTHONPATH": os.getcwd()})
        token = json.loads(out.stdout)
        # Same identity as a live process image (ours), different instance:
        # its lock file exists but nobody holds it any more.
        me = ah.owner_token()
        ghost = {**me, "instance": token["instance"]}
        assert ah.owner_alive(ghost) is False
        assert ah.owner_alive(me) is True

    def test_forked_child_owner_lock(self):
        ctx = multiprocessing.get_context("fork")
        q = ctx.Queue()
        ev = ctx.Event()

        def _child():
            q.put(ah.owner_token())
            ev.wait(10)

        p = ctx.Process(target=_child)
        p.start()
        child = q.get(timeout=10)
        assert child["instance"] != ah.owner_token()["instance"]
        assert ah.owner_alive(child) is True
        ev.set()
        p.join(10)
        assert ah.owner_alive(child) is False

    def test_owner_liveness(self):
        me = ah.owner_token()
        assert ah.owner_alive(me) is True
        assert ah.owner_alive(_dead_owner()) is False
        # Same pid, different start token = recycled pid → not alive.
        assert ah.owner_alive({**me, "start": "other:0"}) is False
        assert ah.owner_alive({**me, "host": "elsewhere"}) is None
        assert ah.owner_alive(None) is None


# ---------------------------------------------------------------------------
# runtime_state → attempts
# ---------------------------------------------------------------------------

class TestRuntimeCapture:
    def test_running_then_done(self, clock):
        rs.set_action_state(PR, "review", "running", pane_id="%1",
                            session_id="s1")
        aid = rs.get_action_state(PR, "review")["attempt_id"]
        clock.advance(30)
        rs.set_action_state(PR, "review", "done", verdict="LGTM")
        assert _attempts()[aid]["source"] == "runtime"
        assert _ends()[aid]["outcome"] == "done"
        assert _ends()[aid]["verdict"] == "LGTM"

    def test_repeat_running_is_one_attempt(self, clock):
        rs.set_action_state(PR, "start", "running", pane_id="%1",
                            session_id="s1")
        rs.set_action_state(PR, "start", "running", pane_id="%1",
                            session_id="s1")
        assert len(_attempts()) == 1

    def test_new_loop_id_supersedes(self, clock):
        rs.set_action_state(PR, "review-loop", "running", loop_id="aaaa")
        first = rs.get_action_state(PR, "review-loop")["attempt_id"]
        rs.set_action_state(PR, "review-loop", "running", loop_id="bbbb")
        second = rs.get_action_state(PR, "review-loop")["attempt_id"]
        assert first != second
        assert _ends()[first]["outcome"] == "superseded"

    def test_rerun_after_done_is_new_attempt(self, clock):
        rs.set_action_state(PR, "review", "running", session_id="s1")
        rs.set_action_state(PR, "review", "done", verdict="NEEDS_WORK")
        rs.set_action_state(PR, "review", "running", session_id="s2")
        assert len(_attempts()) == 2

    def test_pane_gone_vs_restart_sweep(self, clock):
        rs.set_action_state(PR, "merge", "running", session_id="s1")
        merge = rs.get_action_state(PR, "merge")["attempt_id"]
        rs.clear_action(PR, "merge")
        assert _ends()[merge]["outcome"] == "vanished"

        rs.set_action_state(PR, "start", "running", session_id="s2")
        start = rs.get_action_state(PR, "start")["attempt_id"]
        rs.sweep_stale_states("tui-mount")
        assert _ends()[start]["outcome"] == "interrupted"
        assert "tui-mount" in _ends()[start]["detail"]

    def test_cancelled_outcome_override(self, clock):
        rs.set_action_state(PR, "review-loop", "running", loop_id="aaaa")
        aid = rs.get_action_state(PR, "review-loop")["attempt_id"]
        rs.set_action_state(PR, "review-loop", "done",
                            history_outcome="cancelled", verdict="NEEDS_WORK")
        assert _ends()[aid]["outcome"] == "cancelled"
        # The override is not persisted into the runtime entry.
        assert "history_outcome" not in rs.get_action_state(PR, "review-loop")

    def test_qa_runtime_entry_not_journaled(self, clock):
        rs.set_action_state(PR, "qa", "running", panes={"s1": {}})
        rs.set_action_state(PR, "qa", "done", verdict="PASS")
        assert ah.read_events(PR) == []

    def test_journal_failure_leaves_runtime_unchanged(self, tmp_path,
                                                     monkeypatch):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        monkeypatch.setattr(ah, "history_dir", lambda: blocker / "sub")
        rs.set_action_state(PR, "review", "running", session_id="s1")
        rs.set_action_state(PR, "review", "done", verdict="LGTM")
        entry = rs.get_action_state(PR, "review")
        assert entry["state"] == "done" and entry["verdict"] == "LGTM"


# ---------------------------------------------------------------------------
# Review loop
# ---------------------------------------------------------------------------

_PR_DATA = {"id": PR, "title": "t", "branch": "b", "workdir": "/tmp"}


def _drive_review_loop(clock, outputs, follow_up=None, stop_after=None):
    """Run run_review_loop_sync with tmux/launch/poll faked on *clock*."""
    from pm_core import review_loop as rl

    state = rl.ReviewLoopState(pr_id=PR)
    rs.set_action_state(PR, "review-loop", "running", iteration=0,
                        loop_id=state.loop_id)
    outs = list(outputs)

    def _launch(*a, **k):
        clock.advance(3)

    def _poll(*a, **k):
        clock.advance(100)
        out = outs.pop(0)
        if isinstance(out, Exception):
            raise out
        if stop_after is not None and len(outs) < stop_after:
            state.stop_requested = True
        return out

    def _follow(*a, **k):
        clock.advance(600)
        return follow_up

    with patch.object(rl, "_get_pm_session", return_value="pm-x"), \
            patch("pm_core.tmux.session_exists", return_value=True), \
            patch.object(rl, "_launch_review_window", side_effect=_launch), \
            patch.object(rl.time, "sleep", side_effect=clock.advance), \
            patch.object(rl, "_find_claude_pane", return_value="%9"), \
            patch.object(rl, "_poll_for_verdict", side_effect=_poll), \
            patch.object(rl, "_wait_for_follow_up_verdict",
                         side_effect=_follow):
        rl.run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp")
    return state


class TestReviewLoopHistory:
    def test_iterations_phases_and_grace_timers(self, clock):
        state = _drive_review_loop(clock, ["bugs\nNEEDS_WORK", "ok\nPASS"])
        rs.set_action_state(PR, "review-loop", "done", iteration=2,
                            verdict=state.latest_verdict)
        model = hq.build_history(PR, now=clock.t, live=False)
        (loop,) = model["attempts"]
        assert loop["outcome"] == "done" and loop["verdict"] == "PASS"
        i1, i2 = loop["children"]
        assert (i1["iteration"], i1["verdict"]) == (1, "NEEDS_WORK")
        assert (i2["iteration"], i2["verdict"]) == (2, "PASS")
        assert [p["phase"] for p in i1["phases"]] == [
            "launching", "agent", "verdict"]
        launching, agent, _ = i1["phases"]
        assert launching["duration_s"] == 5   # 3 s launch + 2 s settle
        assert agent["duration_s"] == 100
        assert i1["exec_s"] == i1["elapsed_s"] == 105
        assert i1["wait_s"] == 0
        # Both grace timers were cleared when polling returned.
        assert model["timers"]["active"] == []
        assert {r["resolution"] for r in model["timers"]["recent"]} == {"elapsed"}

    def test_input_required_hold_counts_as_wait(self, clock):
        _drive_review_loop(clock, ["need you\nINPUT_REQUIRED"],
                           follow_up="fine\nPASS")
        model = hq.build_history(PR, now=clock.t, live=False)
        (it,) = model["attempts"][0]["children"]
        assert it["verdict"] == "PASS"
        assert "waiting_human" in [p["phase"] for p in it["phases"]]
        assert it["wait_s"] == 600
        assert it["exec_s"] == it["elapsed_s"] - 600
        holds = [r for r in model["timers"]["recent"]
                 if r["timer"].startswith("review-input-required")]
        assert holds and holds[0]["resolution"] == "released"
        # The phase breakdown (launching · agent · verdict · waiting on
        # human · verdict) wraps instead of overflowing 80 columns.
        lines = hq.render_text(model)
        assert max(len(line) for line in lines) <= 80, "\n".join(
            line for line in lines if len(line) > 80)
        text = "\n".join(lines)
        assert "waiting on human 10m00s" in text and text.count("]") >= 1

    def test_input_required_hold_is_active_while_waiting(self, clock):
        from pm_core import review_loop as rl
        seen = {}

        def _follow(*a, **k):
            clock.advance(60)
            seen["model"] = hq.build_history(PR, now=clock.t, live=False)
            return "ok\nPASS"

        state = rl.ReviewLoopState(pr_id=PR)
        rs.set_action_state(PR, "review-loop", "running",
                            loop_id=state.loop_id)
        with patch.object(rl, "_run_claude_review",
                          return_value="x\nINPUT_REQUIRED"), \
                patch.object(rl, "_wait_for_follow_up_verdict",
                             side_effect=_follow):
            # _run_claude_review is mocked, so phases come only from the loop.
            rl.run_review_loop_sync(state, "/tmp", _PR_DATA,
                                    transcript_dir="/tmp")
        m = seen["model"]
        (hold,) = m["holds"]
        assert hold["due_at"] is None and hold["remaining_s"] is None
        assert m["waiting_for"].startswith("human: review INPUT_REQUIRED")
        text = "\n".join(hq.render_text(m))
        assert "no countdown" in text

    def test_pane_killed_and_cancel(self, clock):
        from pm_core import review_loop as rl
        _drive_review_loop(clock, [rl.PaneKilledError("gone")])
        (it,) = [a for a in _attempts().values()
                 if a.get("iteration") == 1 and a.get("source") is None]
        assert _ends()[it["attempt"]]["outcome"] == "vanished"

    def test_grace_cleared_as_cancelled_when_pane_dies_early(self, clock):
        from pm_core import review_loop as rl

        def _killed(*a, **k):
            clock.advance(5)  # inside the 20 s grace
            return None

        state = rl.ReviewLoopState(pr_id=PR)
        with patch.object(rl, "_launch_review_window"), \
                patch.object(rl, "_get_pm_session", return_value="pm-x"), \
                patch("pm_core.tmux.session_exists", return_value=True), \
                patch.object(rl.time, "sleep", side_effect=clock.advance), \
                patch.object(rl, "_find_claude_pane", return_value="%9"), \
                patch.object(rl, "_poll_for_verdict", side_effect=_killed):
            with pytest.raises(rl.PaneKilledError):
                rl._run_claude_review(PR, "/tmp", _PR_DATA, "/tmp/t.jsonl",
                                      iteration=1, history_attempt="a1")
        model = hq.build_history(PR, now=clock.t, live=False)
        (row,) = model["timers"]["recent"]
        assert row["resolution"] == "cancelled"
        assert state.iteration == 0

    def test_adopted_iteration_records_agent_phase(self, clock, tmp_path):
        from pm_core import review_loop as rl
        transcript = tmp_path / f"review-{PR}-i2.jsonl"
        transcript.write_text("")
        state = rl.ReviewLoopState(pr_id=PR)
        state.iteration = 2
        with patch.object(rl, "_get_pm_session", return_value="pm-x"), \
                patch.object(rl, "_find_claude_pane", return_value="%9"), \
                patch("pm_core.claude_launcher.session_id_from_transcript",
                      return_value="sess-a"), \
                patch("pm_core.hook_events.read_event", return_value=None), \
                patch.object(rl, "_poll_for_verdict", return_value="ok\nPASS"):
            out = rl._adopt_in_flight_review(state, _PR_DATA, str(tmp_path),
                                             history_attempt="a2")
        assert out == "ok\nPASS"
        (ev,) = [e for e in ah.read_events(PR) if e["kind"] == "phase"]
        assert (ev["attempt"], ev["phase"], ev["session_id"]) == (
            "a2", "agent", "sess-a")

    def test_stop_requested_marks_loop_cancelled(self, clock):
        state = _drive_review_loop(clock, ["x\nNEEDS_WORK", "y\nNEEDS_WORK"],
                                   stop_after=1)
        assert state.stop_requested
        rs.set_action_state(PR, "review-loop", "done",
                            history_outcome="cancelled",
                            verdict=state.latest_verdict)
        model = hq.build_history(PR, now=clock.t, live=False)
        assert model["attempts"][0]["outcome"] == "cancelled"

    def test_instrumentation_does_not_alter_execution(self, clock, tmp_path,
                                                      monkeypatch):
        outs = ["a\nNEEDS_WORK", "b\nINPUT_REQUIRED", "c\nPASS"]
        with_journal = _drive_review_loop(clock, outs, follow_up="d\nNEEDS_WORK")
        blocker = tmp_path / "file"
        blocker.write_text("x")
        monkeypatch.setattr(ah, "history_dir", lambda: blocker / "sub")
        without = _drive_review_loop(clock, outs, follow_up="d\nNEEDS_WORK")
        assert ([(h.iteration, h.verdict) for h in with_journal.history]
                == [(h.iteration, h.verdict) for h in without.history])
        assert with_journal.latest_verdict == without.latest_verdict


# ---------------------------------------------------------------------------
# QA scenarios
# ---------------------------------------------------------------------------

def _sc(i, title=None):
    return SimpleNamespace(index=i, title=title or f"scenario {i}",
                           session_id=f"sess-{i}", transcript_path=None)


class TestScenarioObserver:
    def _run(self, clock):
        run = ah.start_attempt(PR, "qa", loop_id="L1", label="QA run")
        obs = ah.ScenarioObserver(PR, run, "L1")
        scs = [_sc(1), _sc(2), _sc(3)]
        verdicts = {}
        # s1, s2 run concurrently; s3 waits for a slot (cap 2).
        obs.observe(scs, pending={1, 2}, verifying=set(), queued={3},
                    verdicts=verdicts)
        clock.advance(100)
        verdicts[1] = "PASS"
        obs.observe(scs, pending={2}, verifying={1}, queued={3},
                    verdicts=verdicts)
        clock.advance(20)
        # s2's window dies: backoff, relaunch.
        obs.relaunching(scs[1], 1, 5)
        clock.advance(5)
        obs.relaunched(scs[1], True)
        obs.observe(scs, pending={2, 3}, verifying=set(), queued=set(),
                    verdicts=verdicts)
        clock.advance(200)
        verdicts.update({2: "NEEDS_WORK", 3: "PASS"})
        obs.observe(scs, pending=set(), verifying=set(), queued=set(),
                    verdicts=verdicts)
        obs.finish(stopped=False)
        clock.advance(10)
        ah.end_attempt(PR, run, "done", verdict="NEEDS_WORK")
        return run

    def test_overlapping_scenarios_not_summed(self, clock):
        self._run(clock)
        model = hq.build_history(PR, now=clock.t, live=False)
        (run,) = model["attempts"]
        assert run["elapsed_s"] == 335
        sc = run["scenarios"]
        assert sc["count"] == 3 and sc["attempts"] == 4
        assert sc["max_concurrency"] == 2
        assert sc["wall_s"] <= run["elapsed_s"] < sc["sum_s"]
        text = "\n".join(hq.render_text(model))
        assert "(not wall-clock)" in text
        assert max(len(line) for line in text.splitlines()) <= 80

    def test_scenario_outcomes_retry_and_queue_wait(self, clock):
        self._run(clock)
        model = hq.build_history(PR, now=clock.t, live=False)
        kids = model["attempts"][0]["children"]
        by = {(k["scenario"], k.get("retry", 0)): k for k in kids}
        assert by[(1, 0)]["verdict"] == "PASS"
        assert "verifying" in [p["phase"] for p in by[(1, 0)]["phases"]]
        assert by[(2, 0)]["outcome"] == "vanished"
        assert by[(2, 1)]["verdict"] == "NEEDS_WORK"
        # The relaunch backoff is the retry attempt's leading wait.
        assert [p["phase"] for p in by[(2, 1)]["phases"]] == ["backoff",
                                                              "agent"]
        assert by[(2, 1)]["wait_s"] == 5
        assert by[(3, 0)]["wait_s"] == 125   # queued until s2's relaunch
        backoff = [r for r in model["timers"]["recent"]
                   if r["timer"].startswith("qa-backoff")]
        assert backoff[0]["resolution"] == "fired"

    def test_backoff_timer_active_mid_sleep(self, clock):
        run = ah.start_attempt(PR, "qa", loop_id="L1", label="QA run")
        obs = ah.ScenarioObserver(PR, run, "L1")
        obs.observe([_sc(1)], pending={1}, verifying=set(), queued=set(),
                    verdicts={})
        obs.relaunching(_sc(1), 3, 40)
        clock.advance(15)
        m = hq.build_history(PR, now=clock.t, live=False)
        (t,) = m["timers"]["active"]
        assert t["remaining_s"] == 25 and t["effect"] == "fires"
        assert "relaunch backoff" in m["waiting_for"]
        (row,) = m["current"]
        assert row["name"] == "qa s1 retry 3" and row["state"] == "backoff"
        assert hq.summary_badge(m) == " [qa s1 retry 3: backoff, 25s left]"

    def test_failed_relaunch_ends_backoff_attempt(self, clock):
        run = ah.start_attempt(PR, "qa", loop_id="L1", label="QA run")
        obs = ah.ScenarioObserver(PR, run, "L1")
        obs.observe([_sc(1)], pending={1}, verifying=set(), queued=set(),
                    verdicts={})
        obs.relaunching(_sc(1), 1, 4)
        clock.advance(4)
        obs.relaunched(_sc(1), False)
        kids = hq.build_history(PR, now=clock.t, live=False)[
            "attempts"][0]["children"]
        assert [(k.get("retry"), k["outcome"]) for k in kids] == [
            (None, "vanished"), (1, "failed")]
        assert kids[1]["wait_s"] == 4

    def test_relaunched_window_uses_new_session(self, clock):
        run = ah.start_attempt(PR, "qa", loop_id="L1", label="QA run")
        obs = ah.ScenarioObserver(PR, run, "L1")
        sc = _sc(1)
        obs.observe([sc], pending={1}, verifying=set(), queued=set(),
                    verdicts={})
        obs.relaunching(sc, 1, 4)
        sc.session_id = "sess-new"
        obs.relaunched(sc, True)
        kids = hq.build_history(PR, now=clock.t, live=False)[
            "attempts"][0]["children"]
        assert kids[1]["session_id"] == "sess-new"

    def test_relaunched_without_backoff_attempt_tracks_status(self, clock):
        """If the backoff attempt was never opened, ``relaunched`` opens
        one and the observer keeps tracking it (no duplicate agent phase
        on the next tick)."""
        run = ah.start_attempt(PR, "qa", loop_id="L1", label="QA run")
        obs = ah.ScenarioObserver(PR, run, "L1")
        sc = _sc(1)
        obs.relaunched(sc, True)
        obs.observe([sc], pending={1}, verifying=set(), queued=set(),
                    verdicts={})
        (kid,) = hq.build_history(PR, now=clock.t, live=False)[
            "attempts"][0]["children"]
        assert [p["phase"] for p in kid["phases"]] == ["agent"]


class TestQARunJournal:
    @pytest.mark.parametrize("stop,verdict,run_out,planner_out", [
        (False, "", "cancelled", "cancelled"),   # e.g. PR merged mid-plan
        (True, "", "cancelled", "cancelled"),
        (False, "INPUT_REQUIRED", "done", "failed"),
    ])
    def test_abandoned_planner_follows_run(self, clock, stop, verdict,
                                           run_out, planner_out):
        from pm_core import qa_loop
        state = qa_loop.QALoopState(pr_id=PR)
        state.loop_id = "L1"
        with qa_loop._journal_qa_run(state, resumed=False):
            state._history_planner = ah.start_attempt(
                PR, "qa", parent=state.history_attempt, label="planner")
            state.stop_requested = stop
            state.latest_verdict = verdict
        (run,) = hq.build_history(PR, now=clock.t, live=False)["attempts"]
        assert run["outcome"] == run_out
        assert run["children"][0]["outcome"] == planner_out

    @pytest.mark.parametrize("stop_after,reason", [(0, "cancelled"),
                                                   (31, "elapsed")])
    def test_poll_grace_clear_reason(self, clock, tmp_path, stop_after,
                                     reason):
        """The shared QA grace is cleared as ``elapsed`` only once it ran
        out; a stop inside the grace window reads ``cancelled``."""
        from pm_core import qa_loop
        sc = qa_loop.QAScenario(index=1, title="T", focus="t")
        sc.window_name = "qa-s1"
        state = qa_loop.QALoopState(pr_id=PR)
        state.loop_id = "L1"
        state.scenarios = [sc]

        def _sleep(_s):
            clock.advance(stop_after)
            state.stop_requested = True

        with patch.object(qa_loop.time, "sleep", side_effect=_sleep), \
                patch.object(qa_loop, "_write_status_file"):
            qa_loop._poll_tmux_verdicts(state, {}, {}, "sess", "/tmp/w",
                                        tmp_path / "s.json", lambda *a: None)
        (row,) = [r for r in hq.build_history(PR, now=clock.t, live=False)
                  ["timers"]["recent"] if r["timer"] == "qa-grace:L1"]
        assert row["resolution"] == reason


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

class TestReconciliation:
    def test_timer_states(self, clock):
        owner = ah.start_attempt(PR, "review-loop")
        ah.arm_timer(PR, "g", purpose="grace", owner_action="review-loop",
                     owner_attempt=owner, duration=10, effect="gate")
        ah.arm_timer(PR, "f", purpose="deadline", owner_action="qa",
                     owner_attempt=owner, duration=10, effect="fires")
        ah.arm_timer(PR, "a", purpose="later", owner_action="qa",
                     owner_attempt=owner, duration=100, effect="fires")
        clock.advance(30)
        m = hq.build_history(PR, now=clock.t, live=False)
        assert [r["timer"] for r in m["timers"]["active"]] == ["a"]
        assert m["timers"]["active"][0]["remaining_s"] == 70
        (od,) = m["timers"]["overdue"]
        assert od["timer"] == "f" and od["overdue_s"] == 20
        assert {r["timer"]: r["resolution"] for r in m["timers"]["recent"]} \
            == {"g": "elapsed"}
        assert "overdue" in m["waiting_for"]
        # Owner ends → its timers are cancelled, not active.
        ah.end_attempt(PR, owner, "done")
        m = hq.build_history(PR, now=clock.t, live=False)
        assert not m["timers"]["active"] and not m["timers"]["overdue"]
        assert {r["resolution"] for r in m["timers"]["recent"]
                if r["timer"] in ("a", "f")} == {"cancelled (owner ended)"}

    def test_restart_dead_owner_interrupts_attempt_and_loses_timers(self,
                                                                    clock):
        ah.record(PR, "attempt_start", attempt="old", action="review-loop",
                  loop_id="L", owner=_dead_owner())
        ah.record(PR, "attempt_start", attempt="kid", action="review-loop",
                  parent="old", iteration=2, owner=_dead_owner())
        clock.advance(50)
        ah.record(PR, "phase", attempt="kid", phase="agent",
                  owner=_dead_owner())
        ah.record(PR, "timer_arm", timer="g", purpose="grace",
                  owner_action="review-loop", owner_attempt="kid",
                  armed_t=clock.t, due_t=clock.t + 1000, effect="gate",
                  owner=_dead_owner())
        clock.advance(500)
        # The restarted TUI resumes the loop as a new attempt.
        new = ah.start_attempt(PR, "review-loop", loop_id="L", resumed=True)
        m = hq.build_history(PR, now=clock.t, live=False)
        old = next(a for a in m["attempts"] if a["id"] == "old")
        assert old["outcome"] == "interrupted"
        assert old["ended_at"] is None and old["elapsed_s"] is None
        assert old["elapsed_lower_bound_s"] == 50
        assert old["children"][0]["outcome"] == "interrupted"
        assert not m["timers"]["active"]
        assert m["timers"]["recent"][0]["resolution"].startswith("lost")
        assert [a["id"] for a in m["attempts"] if a.get("open")] == [new]
        text = "\n".join(hq.render_text(m))
        assert "unknown" in text and ">50s" in text

    def test_open_child_closed_at_parent_end(self, clock):
        p = ah.start_attempt(PR, "qa", label="QA run")
        c = ah.start_attempt(PR, "qa", parent=p, scenario=1)
        clock.advance(40)
        ah.end_attempt(PR, p, "cancelled")
        m = hq.build_history(PR, now=clock.t + 100, live=False)
        (kid,) = m["attempts"][0]["children"]
        assert kid["id"] == c and kid["outcome"] == "cancelled"
        assert kid["elapsed_s"] == 40

    def test_open_child_of_superseded_parent(self, clock):
        p = ah.start_attempt(PR, "review-loop", source="runtime",
                             loop_id="L1")
        # Journaled without a parent id: linked to the loop by loop_id.
        c = ah.start_attempt(PR, "review-loop", loop_id="L1", iteration=1)
        clock.advance(30)
        ah.end_attempt(PR, p, "superseded")
        m = hq.build_history(PR, now=clock.t + 100, live=False)
        (kid,) = m["attempts"][0]["children"]
        assert kid["id"] == c and kid["outcome"] == "superseded"
        assert kid["elapsed_s"] == 30 and not kid.get("open")
        assert m["current"] == []

    def test_derived_holds(self, clock):
        pr = {"id": PR, "status": "in_progress",
              "spec_pending": {"phase": "impl",
                               "generated_at": "2027-01-15T08:00:00Z"}}
        m = hq.build_history(PR, pr=pr, now=clock.t, live=False)
        (hold,) = m["holds"]
        assert hold["remaining_s"] is None
        assert m["waiting_for"] == "human: impl spec awaiting approval"

    def test_merged_pr_releases_uncleared_hold(self, clock):
        # ``g`` merges via ``pm pr merge``, which never reaches the TUI's
        # release point: the hold's live owner leaves it uncleared.
        ah.arm_timer(PR, f"merge-hold:{PR}", purpose="manual merge hold",
                     owner_action="merge", duration=None, effect="fires")
        pr = {"id": PR, "status": "sign_off"}
        m = hq.build_history(PR, pr=pr, now=clock.t, live=False)
        assert m["waiting_for"] == "human: manual merge hold"
        clock.advance(60)
        pr = {"id": PR, "status": "merged", "merged_at": ah.iso(clock.t)}
        m = hq.build_history(PR, pr=pr, now=clock.t, live=False)
        assert m["holds"] == []
        assert not m["waiting_for"].startswith("human")
        (row,) = m["timers"]["recent"]
        assert row["resolution"] == "released (PR merged)"
        assert row["resolved_t"] == clock.t

    def test_missing_history_is_honest(self, clock):
        pr = {"id": PR, "status": "merged", "title": "Old",
              "created_at": "2026-01-01T00:00:00Z",
              "merged_at": "2026-01-02T00:00:00Z"}
        m = hq.build_history(PR, pr=pr, now=clock.t, live=False)
        assert m["attempts"] == [] and m["journal"]["exists"] is False
        assert m["waiting_for"] == "nothing recorded"
        text = "\n".join(hq.render_text(m))
        assert "No recorded action history" in text
        assert "merged" in text  # milestone from project.yaml

    def test_live_turn_finished_vs_working(self, clock, monkeypatch):
        a = ah.start_attempt(PR, "review-loop", iteration=1,
                             session_id="sess-1")
        ah.phase(PR, a, "agent")
        ah.arm_timer(PR, "g", purpose="grace", owner_action="review-loop",
                     owner_attempt=a, duration=20, effect="gate")
        clock.advance(10)
        events = {}
        from pm_core import hook_events
        monkeypatch.setattr(hook_events, "read_event",
                            lambda sid: events.get(sid))
        m = hq.build_history(PR, now=clock.t)
        assert m["current"][0]["state"] == "agent_working"
        events["sess-1"] = {"event_type": "idle_prompt",
                            "timestamp": clock.t - 2}
        m = hq.build_history(PR, now=clock.t)
        row = m["current"][0]
        assert row["state"] == "turn_finished"
        assert "verdict grace until" in row["text"]
        events["sess-1"] = {"event_type": "permission_prompt",
                            "timestamp": clock.t}
        m = hq.build_history(PR, now=clock.t)
        assert m["current"][0]["state"] == "blocked_on_permission"
        ah.phase(PR, a, "verdict")
        m = hq.build_history(PR, now=clock.t)
        assert m["current"][0]["state"] == "processing_verdict"

    def test_badge_and_waiting_for_headline_the_human_blocked_row(
            self, clock, monkeypatch):
        """A permission prompt on an older scenario outranks a newer
        scenario that is merely working, in both the badge and summary."""
        run = ah.start_attempt(PR, "qa", label="QA run")
        s1 = ah.start_attempt(PR, "qa", parent=run, scenario=1,
                              session_id="sess-1")
        ah.phase(PR, s1, "agent")
        clock.advance(5)
        s2 = ah.start_attempt(PR, "qa", parent=run, scenario=2,
                              session_id="sess-2")
        ah.phase(PR, s2, "agent")
        clock.advance(5)
        from pm_core import hook_events
        events = {"sess-1": {"event_type": "permission_prompt",
                             "timestamp": clock.t}}
        monkeypatch.setattr(hook_events, "read_event",
                            lambda sid: events.get(sid))
        m = hq.build_history(PR, now=clock.t)
        assert m["waiting_for"].startswith("qa s1: agent waiting on a "
                                           "permission prompt")
        assert hq.summary_badge(m) == " [qa s1: permission prompt]"

    def test_scenario_turn_finished_sees_shared_run_grace(
            self, clock, monkeypatch):
        """The QA verdict grace is owned by the run but gates every
        scenario: an idle scenario is in grace, not waiting for a turn."""
        run = ah.start_attempt(PR, "qa", label="QA run")
        ah.arm_timer(PR, "qa-grace:L1", purpose="QA scenario verdict grace",
                     owner_action="qa", owner_attempt=run, duration=30,
                     effect="gate")
        s1 = ah.start_attempt(PR, "qa", parent=run, scenario=1,
                              session_id="sess-1")
        ah.phase(PR, s1, "agent")
        clock.advance(10)
        from pm_core import hook_events
        monkeypatch.setattr(hook_events, "read_event", lambda sid: {
            "event_type": "idle_prompt", "timestamp": clock.t - 1})
        m = hq.build_history(PR, now=clock.t)
        (row,) = m["current"]
        assert row["state"] == "turn_finished"
        assert "verdict grace until" in row["text"]
        assert row["grace_remaining_s"] == 20
        assert hq.summary_badge(m) == " [qa s1: turn done, 20s left]"
        clock.advance(25)  # grace elapsed: now really waiting for a turn
        m = hq.build_history(PR, now=clock.t)
        assert "no verdict accepted yet" in m["current"][0]["text"]


# ---------------------------------------------------------------------------
# CLI + pane
# ---------------------------------------------------------------------------

def _project(tmp_path, status="in_review"):
    data = {
        "project": {"name": "t", "repo": "/tmp/fake", "base_branch": "master"},
        "plans": [],
        "prs": [{"id": PR, "title": "Test PR", "branch": "b", "status": status,
                 "depends_on": [], "gh_pr_number": 42,
                 "created_at": "2027-01-15T07:00:00Z"}],
    }
    store.save(data, tmp_path)
    return tmp_path


def _seed(clock):
    a = ah.start_attempt(PR, "review", session_id="s")
    clock.advance(90)
    ah.end_attempt(PR, a, "done", verdict="NEEDS_WORK")


class TestCliAndPane:
    def test_text_and_json(self, tmp_path, clock):
        root = _project(tmp_path)
        _seed(clock)
        r = CliRunner().invoke(
            __import__("pm_core.cli", fromlist=["cli"]).cli,
            ["-C", str(root), "pr", "history", "#42"])
        assert r.exit_code == 0, r.output
        assert "History — #42 (pr-001)" in r.output
        assert "1m30s" in r.output and "NEEDS_WORK" in r.output
        r = CliRunner().invoke(
            __import__("pm_core.cli", fromlist=["cli"]).cli,
            ["-C", str(root), "pr", "history", PR, "--json"])
        model = json.loads(r.stdout)
        assert model["schema"] == "pm.pr.history/1"
        assert model["attempts"][0]["elapsed_s"] == 90

    def test_available_after_merge_and_for_removed_prs(self, tmp_path, clock):
        from pm_core.cli import cli
        root = _project(tmp_path, status="merged")
        _seed(clock)
        r = CliRunner().invoke(cli, ["-C", str(root), "pr", "history", PR])
        assert r.exit_code == 0 and "NEEDS_WORK" in r.output
        ah.start_attempt("pr-gone", "review")
        r = CliRunner().invoke(cli, ["-C", str(root), "pr", "history",
                                     "pr-gone"])
        assert r.exit_code == 0 and "History — pr-gone" in r.output
        r = CliRunner().invoke(cli, ["-C", str(root), "pr", "history",
                                     "pr-nope"])
        assert r.exit_code == 1

    def test_pane_matches_cli(self, tmp_path, clock, monkeypatch):
        from pm_core.cli import cli, session
        root = _project(tmp_path)
        _seed(clock)
        cli_out = CliRunner().invoke(
            cli, ["-C", str(root), "pr", "history", PR]).stdout
        monkeypatch.setattr(session, "state_root", lambda: root)
        shown = {}
        with patch("shutil.which", return_value="/usr/bin/less"), \
                patch.object(session.subprocess, "run",
                             side_effect=lambda cmd, input, **k:
                             shown.update(cmd=cmd, text=input)):
            session._run_picker_command(f"view:history {PR}", "pm-x")
        assert shown["cmd"][0] == "less"
        assert shown["text"] == cli_out

    def test_catalog_entry(self):
        from pm_core import action_catalog
        h = action_catalog.get("history")
        assert h.kind == "view" and h.shortcut == "H"
        assert h.available_for("merged") and h.available_for("pending")
        assert h.cli.format(pr_id=PR) == f"pr history {PR}"
