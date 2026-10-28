"""Tests for QA scenario INPUT_REQUIRED continuation (pr-2c67d50).

A QA scenario worker that emits INPUT_REQUIRED is not finalized: it moves
into ``QALoopState.waiting_for_input`` and its own transcript is polled for a
follow-up PASS/NEEDS_WORK turn newer than the INPUT_REQUIRED turn (the same
baseline rule review_loop uses).  The run finalizes as INPUT_REQUIRED and is
*held* so the follow-up can reopen it, and the hold survives a TUI restart.
"""

import json
from unittest.mock import patch

from pm_core import qa_loop
from pm_core.qa_loop import (
    QALoopState,
    QAScenario,
    VERDICT_INPUT_REQUIRED,
    VERDICT_NEEDS_WORK,
    VERDICT_PASS,
    _newer_verdict,
    _scan_waiting_scenarios,
    _waiting_source_is_current,
    build_resume_state,
    _load_resume_file,
    _write_resume_file,
)


# ---------------------------------------------------------------------------
# Transcript helpers
# ---------------------------------------------------------------------------

def _assistant(text, uuid="", ts="2026-05-13T14:00:00.000Z"):
    return json.dumps({
        "type": "assistant",
        "uuid": uuid,
        "timestamp": ts,
        "message": {"role": "assistant",
                    "content": [{"type": "text", "text": text}]},
    })


def _user(text):
    return json.dumps({
        "type": "user",
        "message": {"role": "user", "content": text},
    })


PROMPT = _user('You are running QA scenario 1: "Test"')


def _write(path, *records):
    path.write_text("\n".join(records) + "\n")
    return str(path)


def _waiting_state(transcript, *, session="sid-1", pane="%1",
                   head="old-head"):
    scenario = QAScenario(
        index=1, title="Test", focus="t", window_name="qa-s1",
        pane_id=pane, transcript_path=str(transcript), session_id=session,
    )
    state = QALoopState(pr_id="pr-001")
    state.qa_workdir = None
    state.scenarios = [scenario]
    state.scenario_verdicts = {1: VERDICT_INPUT_REQUIRED}
    state.scenario_verdict_sources = {1: {
        "pr_id": "pr-001", "loop_id": state.loop_id, "scenario": 1,
        "session_id": session, "turn_id": "ir-1",
        "timestamp": "2026-05-13T14:01:00.000Z",
    }}
    state.scenario_verdict_reasons = {1: "need a decision"}
    state.waiting_for_input = {1}
    state.waiting_input_sources = {1: {
        "pr_id": "pr-001", "loop_id": state.loop_id, "scenario": 1,
        "session_id": session, "transcript_path": str(transcript),
        "turn_id": "ir-1", "timestamp": "2026-05-13T14:01:00.000Z",
        "line_index": 2, "head": head, "reason": "need a decision",
    }}
    return state


# ---------------------------------------------------------------------------
# _newer_verdict baseline rules
# ---------------------------------------------------------------------------

class TestNewerVerdict:
    def _transcript(self, tmp_path):
        # line 0 prompt, line 1 PASS, line 2 INPUT_REQUIRED (same task)
        return _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: first look\nPASS", "turn-pass",
                       "2026-05-13T14:00:30.000Z"),
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
        )

    def test_rejects_a_pass_before_the_input_required_baseline(self, tmp_path):
        path = self._transcript(tmp_path)
        source = {"line_index": 2, "timestamp": "2026-05-13T14:01:00.000Z",
                  "turn_id": "turn-ir"}
        assert _newer_verdict(
            path, (VERDICT_PASS, VERDICT_NEEDS_WORK), source) is None

    def test_accepts_a_pass_after_the_baseline(self, tmp_path):
        path = _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
            _user("I fixed it, please continue"),
            _assistant("Reason: blocker resolved\nPASS", "turn-pass",
                       "2026-05-13T14:33:00.000Z"),
        )
        source = {"line_index": 1, "timestamp": "2026-05-13T14:01:00.000Z",
                  "turn_id": "turn-ir"}
        hit = _newer_verdict(path, (VERDICT_PASS, VERDICT_NEEDS_WORK), source)
        assert hit is not None and hit.verdict == VERDICT_PASS

    def test_timestamp_fallback_after_transcript_truncation(self, tmp_path):
        path = _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: done\nPASS", "turn-pass",
                       "2026-05-13T14:33:00.000Z"),
        )
        # The recorded line index is beyond the (rotated) file.
        source = {"line_index": 99, "timestamp": "2026-05-13T14:01:00.000Z",
                  "turn_id": "turn-ir"}
        hit = _newer_verdict(path, (VERDICT_PASS,), source)
        assert hit is not None and hit.verdict == VERDICT_PASS

    def test_same_turn_never_counts_as_newer(self, tmp_path):
        path = _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: done\nPASS", "turn-pass",
                       "2026-05-13T14:00:30.000Z"),
        )
        source = {"line_index": 99, "timestamp": "2026-05-13T14:01:00.000Z",
                  "turn_id": "turn-pass"}
        assert _newer_verdict(path, (VERDICT_PASS,), source) is None


# ---------------------------------------------------------------------------
# _scan_waiting_scenarios
# ---------------------------------------------------------------------------

class TestScanWaitingScenarios:
    def _patch_pane(self, alive=True):
        return patch("pm_core.tmux.pane_exists", return_value=alive)

    def test_collects_a_follow_up_after_the_user_answers(self, tmp_path):
        path = _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
            _user("I fixed it, please continue"),
            _assistant("Reason: blocker resolved\nPASS", "turn-pass",
                       "2026-05-13T14:33:00.000Z"),
        )
        state = _waiting_state(path)
        with self._patch_pane(True):
            scan = _scan_waiting_scenarios(state)
        assert scan.follow_ups[1].verdict == VERDICT_PASS
        # The caller promotes it; the scan itself leaves the entry in place.
        assert 1 in state.waiting_for_input

    def test_repeated_input_required_keeps_waiting_and_moves_the_baseline(
            self, tmp_path):
        path = _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
            _user("Use option B"),
            _assistant("Reason: need the other secret\nINPUT_REQUIRED",
                       "turn-ir-2", "2026-05-13T14:10:00.000Z"),
        )
        state = _waiting_state(path)
        with self._patch_pane(True):
            scan = _scan_waiting_scenarios(state)
        assert scan.follow_ups == {}
        assert scan.changed is True
        source = state.waiting_input_sources[1]
        assert source["turn_id"] == "turn-ir-2"
        assert source["line_index"] == 3
        assert state.scenario_verdict_reasons[1] == "need the other secret"
        assert state.scenario_verdicts[1] == VERDICT_INPUT_REQUIRED

    def test_stale_pass_in_the_same_task_is_not_a_follow_up(self, tmp_path):
        path = _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: first look\nPASS", "turn-pass",
                       "2026-05-13T14:00:30.000Z"),
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
        )
        state = _waiting_state(path)
        with self._patch_pane(True):
            scan = _scan_waiting_scenarios(state)
        assert scan.follow_ups == {}
        assert scan.dropped == set()

    def test_dead_pane_with_a_follow_up_still_accepts_it(self, tmp_path):
        path = _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
            _user("I fixed it"),
            _assistant("Reason: resolved\nNEEDS_WORK", "turn-nw",
                       "2026-05-13T14:33:00.000Z"),
        )
        state = _waiting_state(path)
        with self._patch_pane(False):
            scan = _scan_waiting_scenarios(state)
        assert scan.follow_ups[1].verdict == VERDICT_NEEDS_WORK

    def test_dead_pane_without_a_follow_up_is_dropped_for_relaunch(
            self, tmp_path):
        path = _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
        )
        state = _waiting_state(path)
        with self._patch_pane(False):
            scan = _scan_waiting_scenarios(state)
        assert scan.dropped == {1}
        assert 1 not in state.waiting_for_input
        assert 1 not in state.scenario_verdicts

    def test_superseded_attempt_is_dropped(self, tmp_path):
        path = _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
        )
        state = _waiting_state(path)
        state.scenarios[0].session_id = "sid-new"   # worker relaunched
        with self._patch_pane(True):
            scan = _scan_waiting_scenarios(state)
        assert scan.dropped == {1}
        assert 1 not in state.waiting_for_input
        assert 1 not in state.scenario_verdicts
        assert 1 not in state.verified_scenarios

    def test_unchanged_transcript_is_not_reparsed(self, tmp_path):
        path = _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
        )
        state = _waiting_state(path)
        with self._patch_pane(True):
            _scan_waiting_scenarios(state)
            with patch("pm_core.qa_loop.find_verdict_turn") as finder:
                scan = _scan_waiting_scenarios(state)
        finder.assert_not_called()
        assert scan.follow_ups == {}

    def test_follow_up_is_recollected_after_the_hold_scan(self, tmp_path):
        """The hold loop discards the follow-up it finds and reopens the
        live loop, which rescans the same transcript.  A transcript with an
        unconsumed follow-up must not be cached as scanned."""
        path = _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
            _user("I fixed it, please continue"),
            _assistant("Reason: blocker resolved\nPASS", "turn-pass",
                       "2026-05-13T14:33:00.000Z"),
        )
        state = _waiting_state(path)
        with self._patch_pane(True):
            held_scan = _scan_waiting_scenarios(state)
            live_scan = _scan_waiting_scenarios(state)
        assert held_scan.follow_ups[1].verdict == VERDICT_PASS
        assert live_scan.follow_ups[1].verdict == VERDICT_PASS

    def test_repeated_pane_loss_is_capped(self, tmp_path):
        """Each hold/reopen cycle gives the live loop a fresh retry budget,
        so the waiting scan caps its own relaunches: a worker that asks for
        input and then keeps dying must not be relaunched forever."""
        path = _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"))
        state = _waiting_state(path)
        source = dict(state.waiting_input_sources[1])
        with self._patch_pane(False):
            for _ in range(qa_loop._SCENARIO_MAX_RETRIES):
                assert _scan_waiting_scenarios(state).dropped == {1}
                # The live loop "relaunches": back to waiting for a retry.
                state.waiting_for_input.add(1)
                state.waiting_input_sources[1] = dict(source)
                state.scenario_verdicts[1] = VERDICT_INPUT_REQUIRED
                state.scenarios[0].pane_id = "%1"
            scan = _scan_waiting_scenarios(state)
        assert scan.dropped == set()
        assert 1 not in state.waiting_for_input
        # Terminal evidence is kept rather than waiting (and relaunching)
        # forever.
        assert state.scenario_verdicts[1] == VERDICT_INPUT_REQUIRED

    def test_waiting_source_identity_requires_the_same_attempt(self):
        state = _waiting_state("/tmp/x.jsonl")
        scenario = state.scenarios[0]
        source = state.waiting_input_sources[1]
        assert _waiting_source_is_current(state, scenario, source)
        source["session_id"] = "other"
        assert not _waiting_source_is_current(state, scenario, source)
        # A relaunched worker can reuse the per-scenario transcript path, so
        # the session check is what catches it — but a different transcript
        # is also a different attempt.
        source["session_id"] = scenario.session_id
        source["transcript_path"] = "/tmp/y.jsonl"
        assert not _waiting_source_is_current(state, scenario, source)


# ---------------------------------------------------------------------------
# Live collection loop
# ---------------------------------------------------------------------------

class TestPollWaitingInLiveLoop:
    def _patch_loop(self, pane_alive=True, verification=False):
        return [
            patch("pm_core.qa_loop._get_scenario_pane",
                  side_effect=lambda _s, w: "%1" if "s1" in w else "%2"),
            patch("pm_core.qa_loop.time.sleep"),
            patch("pm_core.qa_loop.time.monotonic", side_effect=[0, 100]),
            patch("pm_core.hook_events.read_event",
                  return_value={"event_type": "idle_prompt",
                                "timestamp": 1e12}),
            patch("pm_core.tmux.pane_exists", return_value=pane_alive),
            patch("pm_core.qa_loop._is_verification_enabled",
                  return_value=verification),
        ]

    def test_input_required_enters_waiting_while_other_scenarios_finish(
            self, tmp_path):
        """A waiting scenario must not stop runnable work from proceeding."""
        from contextlib import ExitStack

        ir = _write(
            tmp_path / "s1.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"))
        ok = _write(
            tmp_path / "s2.jsonl", PROMPT,
            _assistant("Reason: all good\nPASS", "turn-pass",
                       "2026-05-13T14:01:00.000Z"))
        s1 = QAScenario(index=1, title="IR", focus="f", window_name="qa-s1",
                        pane_id="%1", transcript_path=ir, session_id="sid-1")
        s2 = QAScenario(index=2, title="OK", focus="f", window_name="qa-s2",
                        pane_id="%2", transcript_path=ok, session_id="sid-2")
        state = QALoopState(pr_id="pr-001")
        state.qa_workdir = None
        state.scenarios = [s1, s2]

        with ExitStack() as stack:
            for p in self._patch_loop():
                stack.enter_context(p)
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", "/tmp/work",
                tmp_path / "status.json", lambda *a: None)

        # Both were collected in the same run; s1 stays provisional/waiting.
        assert state.scenario_verdicts == {1: VERDICT_INPUT_REQUIRED,
                                           2: VERDICT_PASS}
        assert state.waiting_for_input == {1}
        assert state.waiting_input_sources[1]["session_id"] == "sid-1"
        assert state.held is False   # live collection, not finalized yet

    def test_follow_up_reopens_the_waiting_scenario(self, tmp_path):
        """A follow-up PASS collected on a resumed run is verified normally."""
        path = _write(
            tmp_path / "s1.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
            _user("I fixed it, please continue"),
            _assistant("Reason: blocker resolved\nPASS", "turn-pass",
                       "2026-05-13T14:33:00.000Z"))
        state = _waiting_state(path)
        state.verified_scenarios = {1}   # must not be inherited

        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop.time.monotonic", return_value=100), \
             patch("pm_core.tmux.pane_exists", return_value=True), \
             patch("pm_core.qa_loop._is_verification_enabled",
                   return_value=False), \
             patch("pm_core.qa_loop._current_pr_head", return_value=None):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", "/tmp/work",
                tmp_path / "status.json", lambda *a: None)

        assert state.waiting_for_input == set()
        assert state.scenario_verdicts == {1: VERDICT_PASS}
        assert state.scenario_verdict_sources[1]["turn_id"] == "turn-pass"
        assert state.held is False

    def test_new_source_head_forces_needs_work(self, tmp_path):
        path = _write(
            tmp_path / "s1.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
            _user("I fixed it in the branch"),
            _assistant("Reason: looks good now\nPASS", "turn-pass",
                       "2026-05-13T14:33:00.000Z"))
        state = _waiting_state(path, head="old-head")

        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop.time.monotonic", return_value=100), \
             patch("pm_core.tmux.pane_exists", return_value=True), \
             patch("pm_core.qa_loop._is_verification_enabled",
                   return_value=True), \
             patch("pm_core.qa_loop._current_pr_head",
                   return_value="new-head"):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", "/tmp/work",
                tmp_path / "status.json", lambda *a: None)

        assert state.scenario_verdicts[1] == VERDICT_NEEDS_WORK
        assert state.input_wait_code_changes
        assert "review" in state.scenario_verdict_reasons[1]


class TestReopenDoesNotDuplicateWorkers:
    def test_launched_queued_scenarios_are_not_relaunched(self, tmp_path):
        """A held run reopens with the original queue list, which still
        names scenarios launched in the earlier pass.  Reopening must not
        relaunch them (duplicate worker) — only genuinely unlaunched ones."""
        from contextlib import ExitStack

        ok = _write(
            tmp_path / "s1.jsonl", PROMPT,
            _assistant("Reason: all good\nPASS", "turn-pass",
                       "2026-05-13T14:01:00.000Z"))
        ok2 = _write(
            tmp_path / "s2.jsonl", PROMPT,
            _assistant("Reason: all good\nPASS", "turn-pass",
                       "2026-05-13T14:01:00.000Z"))
        running = QAScenario(index=1, title="Run", focus="f",
                             window_name="qa-s1", pane_id="%1",
                             transcript_path=ok, session_id="sid-1")
        already_launched = QAScenario(index=2, title="Launched", focus="f",
                                      window_name="qa-s2", pane_id="%2",
                                      transcript_path=ok2, session_id="sid-2")
        fresh = QAScenario(index=3, title="Fresh", focus="f")
        state = QALoopState(pr_id="pr-001")
        state.qa_workdir = None
        state.scenarios = [running, already_launched, fresh]

        launched: list[int] = []
        mono = {"n": 0}

        def _monotonic():
            # First call is grace_start; later calls must be past the
            # verdict grace period or no transcript is ever polled.
            mono["n"] += 1
            return 0 if mono["n"] == 1 else 100

        def _fake_launch(_state, *_a, **_k):
            scenario = _state.scenarios[0]
            launched.append(scenario.index)
            scenario.window_name = f"qa-s{scenario.index}"
            scenario.pane_id = f"%{scenario.index}"
            scenario.transcript_path = ok
            scenario.session_id = f"sid-{scenario.index}"

        with ExitStack() as stack:
            stack.enter_context(patch("pm_core.qa_loop._get_scenario_pane",
                                      return_value="%1"))
            stack.enter_context(patch("pm_core.qa_loop.time.sleep"))
            stack.enter_context(patch("pm_core.qa_loop.time.monotonic",
                                      side_effect=_monotonic))
            stack.enter_context(patch("pm_core.hook_events.read_event",
                                      return_value={"event_type": "idle_prompt",
                                                    "timestamp": 1e12}))
            stack.enter_context(patch("pm_core.tmux.pane_exists",
                                      return_value=True))
            stack.enter_context(patch(
                "pm_core.qa_loop._is_verification_enabled",
                return_value=False))
            stack.enter_context(patch(
                "pm_core.qa_loop._launch_scenarios_in_tmux",
                side_effect=_fake_launch))
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", "/tmp/work",
                tmp_path / "status.json", lambda *a: None,
                queued_scenarios=[already_launched, fresh],
                concurrency_cap=0)

        assert launched == [3]


# ---------------------------------------------------------------------------
# Hold loop
# ---------------------------------------------------------------------------

class TestHoldForFollowUp:
    def _ir_only(self, tmp_path):
        return _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"))

    def test_hold_returns_true_when_a_follow_up_is_present(self, tmp_path):
        path = _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
            _user("I fixed it, please continue"),
            _assistant("Reason: blocker resolved\nPASS", "turn-pass",
                       "2026-05-13T14:33:00.000Z"))
        state = _waiting_state(path)

        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.tmux.pane_exists", return_value=True), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop._write_resume_file") as write_resume:
            reopened = qa_loop._hold_for_follow_up(
                state, None, tmp_path / "status.json", False, 0, set())

        assert reopened is True
        # The hold only reports the follow-up; the live loop records it.
        assert state.waiting_for_input == {1}
        # Unchanged wait: no per-tick snapshot churn.
        write_resume.assert_not_called()

    def test_hold_ends_on_stop(self, tmp_path):
        state = _waiting_state(self._ir_only(tmp_path))
        state.stop_requested = True
        with patch("pm_core.qa_loop.time.sleep"):
            assert qa_loop._hold_for_follow_up(
                state, None, tmp_path / "status.json", False, 0, set()) is False

    def test_hold_ends_when_the_pr_leaves_qa(self, tmp_path):
        from pm_core import store

        state = _waiting_state(self._ir_only(tmp_path))
        pm_root = tmp_path / "pm"
        pm_root.mkdir()
        store.save({"project": {"name": "t", "repo": "/tmp/r",
                                "base_branch": "master"},
                    "plans": [],
                    "prs": [{"id": "pr-001", "status": "in_review"}]},
                   pm_root)

        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.tmux.pane_exists", return_value=True), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop._write_resume_file"):
            assert qa_loop._hold_for_follow_up(
                state, pm_root, tmp_path / "status.json", False, 0, set()) is False


# ---------------------------------------------------------------------------
# Persistence and reconciliation
# ---------------------------------------------------------------------------

class TestWaitingPersistence:
    def test_roundtrip(self, tmp_path):
        state = _waiting_state(tmp_path / "t.jsonl")
        state.qa_workdir = str(tmp_path)
        state.held = True
        state.completion_processed = True
        state.latest_verdict = VERDICT_INPUT_REQUIRED
        _write_resume_file(state, use_containers=False, concurrency_cap=0)

        rebuilt = build_resume_state(_load_resume_file(tmp_path))
        assert rebuilt.waiting_for_input == {1}
        assert rebuilt.waiting_input_sources[1]["line_index"] == 2
        assert rebuilt.held is True
        assert rebuilt.completion_processed is True
        assert rebuilt.latest_verdict == VERDICT_INPUT_REQUIRED

    def test_superseded_session_drops_waiting_and_verdict(self, tmp_path):
        state = _waiting_state(tmp_path / "t.jsonl")
        state.qa_workdir = str(tmp_path)
        state.held = True
        _write_resume_file(state, use_containers=False, concurrency_cap=0)

        data = _load_resume_file(tmp_path)
        data["scenarios"][0]["session_id"] = "sid-relaunched"
        rebuilt = build_resume_state(data)
        assert rebuilt.waiting_for_input == set()
        assert 1 not in rebuilt.scenario_verdicts
        assert rebuilt.held is False

    def test_drop_foreign_verdicts_keeps_matching_waiting(self, tmp_path):
        state = _waiting_state(tmp_path / "t.jsonl")
        state.qa_workdir = str(tmp_path)
        _write_resume_file(state, use_containers=False, concurrency_cap=0)
        rebuilt = build_resume_state(_load_resume_file(tmp_path))
        assert rebuilt.waiting_for_input == {1}
        assert rebuilt.scenario_verdicts[1] == VERDICT_INPUT_REQUIRED

    def test_superseded_run_never_rewrites_the_snapshot(self, tmp_path):
        """A fresh start clears the snapshot; the still-winding-down held
        thread must not recreate it or a restart scan resurrects the run."""
        state = _waiting_state(tmp_path / "t.jsonl")
        state.qa_workdir = str(tmp_path)
        state.held = True
        _write_resume_file(state, use_containers=False, concurrency_cap=0)
        assert (tmp_path / "qa_resume.json").is_file()

        qa_loop.clear_resume_file(tmp_path)
        state.superseded = True
        _write_resume_file(state, use_containers=False, concurrency_cap=0)
        qa_loop.mark_completion_processed(state)

        assert not (tmp_path / "qa_resume.json").exists()


# ---------------------------------------------------------------------------
# Finalize / hold
# ---------------------------------------------------------------------------

class TestFinalizeHoldsForInput:
    def _finalize(self, state, tmp_path, *, hold_returns=(False,),
                  poll_side_effect=None):
        from contextlib import ExitStack
        patches = [
            patch("pm_core.qa_loop._persist_scenario_verdicts"),
            patch("pm_core.qa_loop._write_resume_file"),
            patch("pm_core.qa_loop._write_status_file"),
            patch("pm_core.qa_loop._hold_for_follow_up",
                  side_effect=list(hold_returns)),
        ]
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            finalize = stack.enter_context(
                patch("pm_core.qa_loop._run_qa_finalize_pane",
                      return_value="FINALIZE_DONE"))
            poll = stack.enter_context(
                patch("pm_core.qa_loop._poll_tmux_verdicts",
                      side_effect=poll_side_effect))
            qa_loop._execute_and_finalize(
                state, tmp_path, {"branch": "b"}, {}, "pm-test", "qa-w",
                str(tmp_path), tmp_path / "status.json", None,
                use_containers=False, concurrency_cap=0,
                queued_scenarios=[], notify=lambda: None)
        return finalize, poll

    def test_input_required_run_is_held_and_finalized(self, tmp_path):
        state = _waiting_state(tmp_path / "t.jsonl")
        finalize, _ = self._finalize(state, tmp_path, hold_returns=(False,))
        assert state.latest_verdict == VERDICT_INPUT_REQUIRED
        assert state.held is False           # hold ended
        assert state.running is False
        finalize.assert_called_once()

    def test_restored_held_run_does_not_re_finalize(self, tmp_path):
        state = _waiting_state(tmp_path / "t.jsonl")
        state.held = True
        state.completion_processed = True
        finalize, _ = self._finalize(state, tmp_path, hold_returns=(False,))
        finalize.assert_not_called()
        assert state.latest_verdict == VERDICT_INPUT_REQUIRED

    def test_follow_up_reopens_and_re_finalizes(self, tmp_path):
        state = _waiting_state(tmp_path / "t.jsonl")
        calls = {"n": 0}

        def _poll(_state, *_a, **_k):
            calls["n"] += 1
            if calls["n"] < 2:
                return
            # Simulate the live loop collecting the follow-up on reopen.
            _state.waiting_for_input.clear()
            _state.waiting_input_sources.clear()
            _state.held = False
            _state.scenario_verdicts = {1: VERDICT_NEEDS_WORK}

        finalize, poll = self._finalize(
            state, tmp_path, hold_returns=(True,), poll_side_effect=_poll)
        assert poll.call_count == 2
        assert finalize.call_count == 2
        assert state.latest_verdict == VERDICT_NEEDS_WORK
        assert state.held is False

    def test_input_wait_source_changes_force_needs_work(self, tmp_path):
        state = QALoopState(pr_id="pr-001")
        state.scenarios = [QAScenario(index=1, title="A", focus="a")]
        state.scenario_verdicts = {1: VERDICT_PASS}
        state.verified_scenarios = {1}
        state.input_wait_code_changes = ["aaaa..bbbb"]
        self._finalize(state, tmp_path, hold_returns=(False,))
        assert state.latest_verdict == VERDICT_NEEDS_WORK

    def test_hold_is_persisted_before_the_finalize_pane(self, tmp_path):
        """The finalize pane can run for minutes.  A restart during it must
        still recover the wait, so the snapshot written first already says
        held."""
        (tmp_path / "t.jsonl").write_text("")
        state = _waiting_state(tmp_path / "t.jsonl")
        state.qa_workdir = str(tmp_path)
        seen = {}

        def _finalize(*_a, **_k):
            seen["snapshot"] = _load_resume_file(tmp_path) or {}
            return "FINALIZE_DONE"

        with patch("pm_core.qa_loop._persist_scenario_verdicts"), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop._hold_for_follow_up", return_value=False), \
             patch("pm_core.qa_loop._poll_tmux_verdicts"), \
             patch("pm_core.qa_loop._run_qa_finalize_pane",
                   side_effect=_finalize):
            qa_loop._execute_and_finalize(
                state, tmp_path, {"branch": "b"}, {}, "pm-test", "qa-w",
                str(tmp_path), tmp_path / "status.json", None,
                use_containers=False, concurrency_cap=0,
                queued_scenarios=[], notify=lambda: None)

        assert seen["snapshot"]["held"] is True
        assert seen["snapshot"]["waiting_for_input"] == [1]


# ---------------------------------------------------------------------------
# Prompt reconciliation
# ---------------------------------------------------------------------------

class TestPromptReconciliation:
    def test_worker_prompt_describes_input_required_continuation(self):
        from pm_core.prompt_gen import generate_qa_child_prompt
        from pm_core import prompt_gen

        data = {
            "project": {"name": "t", "repo": "/tmp/r",
                        "base_branch": "master", "backend": "local"},
            "plans": [],
            "prs": [{"id": "pr-x", "title": "T", "branch": "pm/pr-x",
                     "status": "qa", "workdir": "/tmp/w"}],
        }
        scenario = QAScenario(index=1, title="T", focus="f", steps="s")
        with patch.object(prompt_gen.store, "find_project_root"):
            prompt = generate_qa_child_prompt(data, "pr-x", scenario, "/tmp/w")
        assert "INPUT_REQUIRED is **not** final" in prompt
        assert "follow-up verdict" in prompt
        assert "PASS and NEEDS_WORK are final for this run" in prompt


# ---------------------------------------------------------------------------
# TUI tracking of a held run
# ---------------------------------------------------------------------------

def _poll_app(tmp_path):
    """Minimal TUI app for poll_qa_state / stop_qa."""
    from unittest.mock import MagicMock

    from pm_core import store

    pm_dir = tmp_path / "pm"
    pm_dir.mkdir(exist_ok=True)
    store.save({"project": {"name": "t", "repo": "/tmp/r",
                            "base_branch": "master"},
                "plans": [],
                "prs": [{"id": "pr-001", "title": "T", "branch": "b",
                         "status": "qa", "workdir": str(tmp_path / "wd"),
                         "notes": []}]}, pm_dir)
    app = MagicMock()
    app._root = pm_dir
    app._qa_loops = {}
    app._resumed_qa_pr_ids = set()
    app._self_driving_qa = {}
    app._qa_resume_poll_counter = 1
    return app


def test_poll_qa_state_drops_a_crashed_held_run(tmp_path):
    """Only a genuine INPUT_REQUIRED result is held.  A run whose thread
    died (verdict ERROR) must take the normal completion path — otherwise
    the state stays pinned in ``_qa_loops`` forever and every later ``t``
    reports "waiting for input" for a run with no watcher."""
    from pm_core.tui import qa_loop_ui

    app = _poll_app(tmp_path)
    state = _waiting_state(tmp_path / "t.jsonl")
    state.qa_workdir = str(tmp_path)
    state.held = True
    state.running = False
    state.latest_verdict = "ERROR"
    state._ui_complete_notified = True
    _write_resume_file(state, use_containers=False, concurrency_cap=0)
    app._qa_loops = {"pr-001": state}

    with patch.object(qa_loop_ui, "_resume_incomplete_qa"), \
         patch("pm_core.runtime_state.set_action_state"):
        qa_loop_ui.poll_qa_state(app)
        qa_loop_ui.poll_qa_state(app)

    assert "pr-001" not in app._qa_loops
    assert not (tmp_path / "qa_resume.json").exists()


def test_stop_qa_requests_stop_on_a_held_run(tmp_path):
    from pm_core.tui import qa_loop_ui

    app = _poll_app(tmp_path)
    state = _waiting_state(tmp_path / "t.jsonl")
    state.running = False
    state.held = True
    app._qa_loops = {"pr-001": state}

    qa_loop_ui.stop_qa(app, "pr-001")

    assert state.stop_requested is True
    app.log_message.assert_called()


def test_waiting_suffix_fits_the_status_line():
    """The "(waiting)" marker must not push a row past the terminal width —
    a wrapped row shifts the whole qa_status screen."""
    import re

    from pm_core import qa_status

    status = {
        "pr_id": "pr-001", "overall": "", "error": "",
        "scenarios": [{"index": 1, "title": "A fairly long scenario title",
                       "verdict": VERDICT_INPUT_REQUIRED,
                       "verdict_reason": "", "waiting_for_input": True}],
    }
    out = qa_status._render(status, -1, 24, 80, tick=0)
    for line in out.splitlines():
        visible = re.sub(r"\033\[[0-9;?]*[A-Za-z]", "", line)
        assert len(visible) <= 80, repr(visible)
