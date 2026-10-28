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
    _enter_waiting,
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

    def test_dead_pane_accepts_a_pass_after_a_repeated_input_required(
            self, tmp_path):
        """A worker that asks again and then passes before its pane exits must
        have that PASS collected — not dropped with the attempt because the
        repeated INPUT_REQUIRED was the newest turn when the pane died."""
        path = _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
            _user("use option B"),
            _assistant("Reason: need the other secret\nINPUT_REQUIRED",
                       "turn-ir-2", "2026-05-13T14:10:00.000Z"),
            # A wakeup (not a new task) delivers the answer, so the repeated
            # INPUT_REQUIRED and the PASS share one task segment.
            _user("<task-notification> the secret is in the vault"),
            _assistant("Reason: blocker resolved\nPASS", "turn-pass",
                       "2026-05-13T14:33:00.000Z"),
        )
        state = _waiting_state(path)
        with self._patch_pane(False):
            scan = _scan_waiting_scenarios(state)
        assert scan.dropped == set()
        assert scan.follow_ups[1].verdict == VERDICT_PASS

    def test_live_pane_collects_a_pass_after_a_repeated_input_required(
            self, tmp_path):
        """With the worker still alive, a repeated INPUT_REQUIRED only moves
        the baseline this tick; the PASS that follows it in the same turn is
        collected on the next poll."""
        path = _write(
            tmp_path / "t.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
            _user("use option B"),
            _assistant("Reason: need the other secret\nINPUT_REQUIRED",
                       "turn-ir-2", "2026-05-13T14:10:00.000Z"),
            # A wakeup (not a new task) delivers the answer, so the repeated
            # INPUT_REQUIRED and the PASS share one task segment.
            _user("<task-notification> the secret is in the vault"),
            _assistant("Reason: blocker resolved\nPASS", "turn-pass",
                       "2026-05-13T14:33:00.000Z"),
        )
        state = _waiting_state(path)
        with self._patch_pane(True):
            first = _scan_waiting_scenarios(state)
            second = _scan_waiting_scenarios(state)
        assert first.follow_ups == {}
        assert state.waiting_input_sources[1]["turn_id"] == "turn-ir-2"
        assert second.follow_ups[1].verdict == VERDICT_PASS

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


class TestEnterWaiting:
    def _hit(self):
        from pm_core.verdict_transcript import VerdictHit
        return VerdictHit(
            verdict=VERDICT_INPUT_REQUIRED,
            text="Reason: need a decision\nINPUT_REQUIRED",
            turn_id="turn-ir", timestamp="2026-05-13T14:01:00.000Z",
            line_index=2)

    def test_planner_head_skips_the_blocking_upstream_lookup(self):
        """The per-scenario head is only a fallback baseline.  Resolving it
        queries the upstream (up to a 15s timeout), so a run that already has
        a planner head must not pay for it on every INPUT_REQUIRED."""
        state = _waiting_state("/tmp/x.jsonl")
        state.planner_head = "planner-head"
        with patch("pm_core.qa_loop._current_pr_head") as head:
            _enter_waiting(state, state.scenarios[0], self._hit(), "why",
                           "/tmp/w", "b")
        head.assert_not_called()
        assert state.waiting_input_sources[1]["head"] is None

    def test_head_is_recorded_when_there_is_no_planner_head(self):
        state = _waiting_state("/tmp/x.jsonl")
        state.planner_head = None
        with patch("pm_core.qa_loop._current_pr_head",
                   return_value="current-head") as head:
            _enter_waiting(state, state.scenarios[0], self._hit(), "why",
                           "/tmp/w", "b")
        head.assert_called_once_with("/tmp/w", "b")
        assert state.waiting_input_sources[1]["head"] == "current-head"


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
        # Adopted as a held run: collecting the follow-up must clear the
        # hold so the reopened result gets its own finalize.
        state.held = True

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

    def test_follow_up_pass_is_independently_verified(self, tmp_path):
        """R6: a follow-up PASS is not trusted because the worker said PASS.

        The scenario's PASS verification was discarded when it entered
        waiting, so the follow-up must go through the normal independent
        verifier exactly like a first-pass verdict.
        """
        path = _write(
            tmp_path / "s1.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"),
            _user("I fixed it, please continue"),
            _assistant("Reason: blocker resolved\nPASS", "turn-pass",
                       "2026-05-13T14:33:00.000Z"))
        state = _waiting_state(path)
        # An earlier PASS for this scenario was verified; entering waiting
        # discarded that, so the follow-up PASS must be verified afresh.
        state.verified_scenarios = {1}

        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop.time.monotonic", return_value=100), \
             patch("pm_core.tmux.pane_exists", return_value=True), \
             patch("pm_core.qa_loop._is_verification_enabled",
                   return_value=True), \
             patch("pm_core.qa_loop._current_pr_head", return_value=None), \
             patch("pm_core.qa_loop._verify_single_scenario",
                   return_value=(True, "", None)) as verify:
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", "/tmp/work",
                tmp_path / "status.json", lambda *a: None)

        assert state.scenario_verdicts == {1: VERDICT_PASS}
        verify.assert_called_once()
        # The verifier's result was collected by the loop, not left dangling.
        assert state.verified_scenarios == {1}

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

    def test_restored_completed_scenario_is_not_re_polled(self, tmp_path):
        """A restored/held run must not re-read a completed scenario's stale
        turn.  With a live pane and a fresh hook event the collector would
        otherwise re-accept the old verdict (re-recording it, or re-spawning
        a verifier for an already verified PASS).  Only an unverified PASS
        is polled again."""
        done = QAScenario(index=1, title="Done", focus="f",
                          window_name="qa-s1", pane_id="%1",
                          transcript_path=str(tmp_path / "s1.jsonl"),
                          session_id="sid-1")
        state = QALoopState(pr_id="pr-001")
        state.qa_workdir = None  # skip snapshot writes inside the loop
        state.scenarios = [done]
        state.scenario_verdicts = {1: VERDICT_NEEDS_WORK}

        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop.find_verdict_turn") as find, \
             patch("pm_core.hook_events.read_event",
                   return_value={"event_type": "idle_prompt",
                                 "timestamp": 1e12}), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", "/tmp/work",
                tmp_path / "status.json", lambda *a: None)

        find.assert_not_called()
        assert state.scenario_verdicts == {1: VERDICT_NEEDS_WORK}


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

    def test_terminal_clear_keeps_the_hold_for_other_waiting_scenarios(
            self, tmp_path):
        """Clearing one scenario's attempt (here: no session left to poll)
        must not end the hold or persist ``held=False`` while another
        scenario still waits.  The TUI's completion poll would otherwise drop
        the run from ``_qa_loops`` and delete the resume snapshot, so the
        remaining scenario's follow-up could never be collected."""
        a = QAScenario(index=1, title="A", focus="a", window_name="w1",
                       transcript_path=str(tmp_path / "a.jsonl"),
                       session_id="")
        b_path = _write(
            tmp_path / "b.jsonl", PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "turn-ir",
                       "2026-05-13T14:01:00.000Z"))
        b = QAScenario(index=2, title="B", focus="b", window_name="w2",
                       pane_id="%2", transcript_path=b_path,
                       session_id="sid-b")
        state = QALoopState(pr_id="pr-001")
        state.qa_workdir = str(tmp_path)
        state.scenarios = [a, b]
        state.scenario_verdicts = {1: VERDICT_INPUT_REQUIRED,
                                   2: VERDICT_INPUT_REQUIRED}
        state.waiting_for_input = {1, 2}
        state.waiting_input_sources = {
            1: {"pr_id": "pr-001", "loop_id": state.loop_id, "scenario": 1,
                "session_id": "",
                "transcript_path": str(tmp_path / "a.jsonl"),
                "turn_id": "ir-a", "timestamp": "2026-05-13T14:01:00.000Z",
                "line_index": 2, "head": None, "reason": "need a decision"},
            2: {"pr_id": "pr-001", "loop_id": state.loop_id, "scenario": 2,
                "session_id": "sid-b", "transcript_path": b_path,
                "turn_id": "ir-b", "timestamp": "2026-05-13T14:01:00.000Z",
                "line_index": 2, "head": None, "reason": "need a decision"},
        }
        state.held = True
        state.latest_verdict = VERDICT_INPUT_REQUIRED

        real_scan = qa_loop._scan_waiting_scenarios

        def _scan_one_tick(s):
            scan = real_scan(s)
            s.stop_requested = True   # exit the hold after this tick
            return scan

        with patch("pm_core.qa_loop._scan_waiting_scenarios",
                   side_effect=_scan_one_tick), \
             patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.tmux.pane_exists", return_value=True), \
             patch("pm_core.qa_loop._write_status_file"):
            assert qa_loop._hold_for_follow_up(
                state, None, tmp_path / "status.json", False, 0,
                set()) is False

        assert state.waiting_for_input == {2}
        # The published wait still describes a held run: a restart (or the
        # TUI's next poll) re-adopts it instead of finalizing it as done.
        snapshot = _load_resume_file(tmp_path)
        assert snapshot["held"] is True
        assert snapshot["waiting_for_input"] == [2]

    def test_reopening_never_publishes_a_finished_looking_run(self, tmp_path):
        """A dropped last waiting attempt must not leave the state as
        (not running, not held, INPUT_REQUIRED): the TUI's completion poll
        reads exactly that as a finished run, drops it from ``_qa_loops`` and
        deletes the resume snapshot, so the reopened run's verdict could
        never be collected.  ``running`` is published (and ``held`` kept)
        before returning; the reopen block in _execute_and_finalize does the
        rest."""
        state = _waiting_state(self._ir_only(tmp_path))
        state.held = True
        state.latest_verdict = VERDICT_INPUT_REQUIRED

        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.tmux.pane_exists", return_value=False), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop._write_resume_file"):
            assert qa_loop._hold_for_follow_up(
                state, None, tmp_path / "status.json", False, 0,
                set()) is True

        # The attempt was dropped back to the retry path ...
        assert state.waiting_for_input == set()
        # ... and the run is published as live, never as finished.
        assert state.running is True
        assert state.held is True


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
        state.input_wait_code_changes = ["aaaa..bbbb"]
        _write_resume_file(state, use_containers=False, concurrency_cap=0)

        rebuilt = build_resume_state(_load_resume_file(tmp_path))
        assert rebuilt.waiting_for_input == {1}
        assert rebuilt.waiting_input_sources[1]["line_index"] == 2
        # The per-scenario head is the fallback baseline for a run with no
        # planner head; a resume must not lose it.
        assert rebuilt.waiting_input_sources[1]["head"] == "old-head"
        assert rebuilt.held is True
        assert rebuilt.completion_processed is True
        assert rebuilt.latest_verdict == VERDICT_INPUT_REQUIRED
        assert rebuilt.input_wait_code_changes == ["aaaa..bbbb"]

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

    def test_waiting_entry_without_a_source_is_dropped_but_keeps_the_verdict(
            self, tmp_path):
        """A waiting entry with no recoverable attempt (its source or the
        scenario is gone) can never be polled again: the wait is dropped but
        the INPUT_REQUIRED verdict stays as terminal evidence (R3)."""
        state = _waiting_state(tmp_path / "t.jsonl")
        state.qa_workdir = str(tmp_path)
        state.held = True
        _write_resume_file(state, use_containers=False, concurrency_cap=0)

        data = _load_resume_file(tmp_path)
        data["waiting_input_sources"] = {}
        rebuilt = build_resume_state(data)

        assert rebuilt.waiting_for_input == set()
        # Terminal evidence is preserved, unlike a superseded attempt.
        assert rebuilt.scenario_verdicts[1] == VERDICT_INPUT_REQUIRED
        assert rebuilt.held is False

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

    def test_restored_held_run_finalizes_a_collected_follow_up(self, tmp_path):
        """A restored held run whose follow-up is collected on the first
        iteration must still run the finalize pane for the new result.
        The live loop's ``_poll_waiting`` clears ``held`` when it records the
        follow-up, so ``was_held`` is False for that iteration; if it stayed
        True the follow-up PASS would be promoted without the push /
        fast-forward verification the finalize pane performs."""
        state = _waiting_state(tmp_path / "t.jsonl")
        state.held = True
        state.completion_processed = True
        state.latest_verdict = VERDICT_INPUT_REQUIRED

        def _poll(_state, *_a, **_k):
            # What the live loop's _clear_waiting + _accept_hit do.
            _state.waiting_for_input.clear()
            _state.waiting_input_sources.clear()
            _state.held = False
            _state.scenario_verdicts = {1: VERDICT_PASS}

        finalize, _ = self._finalize(
            state, tmp_path, hold_returns=(False,), poll_side_effect=_poll)
        assert finalize.call_count == 1
        assert state.latest_verdict == VERDICT_PASS

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

    def test_reopen_publishes_in_progress_so_a_restart_resumes(self, tmp_path):
        """The held finalize leaves an INPUT_REQUIRED ``overall`` in
        qa_status.json.  Reopening must clear it, or a restart during the
        (possibly long) collection window reads that stale result as final
        and drops the run before its follow-up verdict is collected."""
        state = _waiting_state(tmp_path / "t.jsonl")
        state.qa_workdir = str(tmp_path)
        state.held = True
        state.completion_processed = True
        state.latest_verdict = VERDICT_INPUT_REQUIRED

        overalls: list[str] = []
        snapshots: list[dict] = []

        def _status(*_a, **kw):
            overalls.append(kw.get("overall", ""))

        def _resume(state_, *_a, **_k):
            snapshots.append({"held": state_.held,
                              "latest_verdict": state_.latest_verdict,
                              "waiting": sorted(state_.waiting_for_input)})

        with patch("pm_core.qa_loop._persist_scenario_verdicts"), \
             patch("pm_core.qa_loop._write_status_file",
                   side_effect=_status), \
             patch("pm_core.qa_loop._write_resume_file",
                   side_effect=_resume), \
             patch("pm_core.qa_loop._hold_for_follow_up",
                   side_effect=[True, False]), \
             patch("pm_core.qa_loop._poll_tmux_verdicts"), \
             patch("pm_core.qa_loop._run_qa_finalize_pane",
                   return_value="FINALIZE_DONE"):
            qa_loop._execute_and_finalize(
                state, tmp_path, {"branch": "b"}, {}, "pm-test", "qa-w",
                str(tmp_path), tmp_path / "status.json", None,
                use_containers=False, concurrency_cap=0,
                queued_scenarios=[], notify=lambda: None)

        # Held result → in-progress reopen → the second result.
        assert overalls == [VERDICT_INPUT_REQUIRED, "", VERDICT_INPUT_REQUIRED]
        # The snapshot written at the reopen describes a live collection, so
        # build_resume_state/_resume_incomplete_qa resumes it instead of
        # treating the run as complete.
        in_progress = [s for s in snapshots if s["latest_verdict"] == ""]
        assert in_progress == [{"held": False, "latest_verdict": "",
                                "waiting": [1]}]

    def test_status_file_marks_the_wait_while_the_run_is_held(self, tmp_path):
        """A held run is the genuine input wait: the status file must flag
        the scenario so qa_status renders its "(waiting)" marker."""
        state = _waiting_state(tmp_path / "t.jsonl")
        state.qa_workdir = str(tmp_path)
        calls = []

        with patch("pm_core.qa_loop._persist_scenario_verdicts"), \
             patch("pm_core.qa_loop._write_resume_file"), \
             patch("pm_core.qa_loop._write_status_file",
                   side_effect=lambda *_a, **kw: calls.append(kw)), \
             patch("pm_core.qa_loop._hold_for_follow_up",
                   return_value=False), \
             patch("pm_core.qa_loop._poll_tmux_verdicts"), \
             patch("pm_core.qa_loop._run_qa_finalize_pane",
                   return_value="FINALIZE_DONE"):
            qa_loop._execute_and_finalize(
                state, tmp_path, {"branch": "b"}, {}, "pm-test", "qa-w",
                str(tmp_path), tmp_path / "status.json", None,
                use_containers=False, concurrency_cap=0,
                queued_scenarios=[], notify=lambda: None)

        assert calls[0]["waiting_for_input"] == {1}

    def test_status_file_drops_the_waiting_marker_once_the_run_leaves_qa(
            self, tmp_path):
        """A NEEDS_WORK result ends the hold.  The remaining INPUT_REQUIRED
        scenario stays recorded as evidence for the next run, but nothing
        polls its pane any more — advertising it as "(waiting)" would send
        the user to answer a worker whose follow-up can never be collected."""
        state = _waiting_state(tmp_path / "t.jsonl")
        state.qa_workdir = str(tmp_path)
        second = QAScenario(index=2, title="Two", focus="t",
                            window_name="qa-s2", session_id="sid-2",
                            transcript_path=str(tmp_path / "t2.jsonl"))
        state.scenarios = [state.scenarios[0], second]
        state.scenario_verdicts = {1: VERDICT_INPUT_REQUIRED,
                                   2: VERDICT_NEEDS_WORK}
        calls = []

        with patch("pm_core.qa_loop._persist_scenario_verdicts"), \
             patch("pm_core.qa_loop._write_resume_file"), \
             patch("pm_core.qa_loop._write_status_file",
                   side_effect=lambda *_a, **kw: calls.append(kw)), \
             patch("pm_core.qa_loop._hold_for_follow_up",
                   return_value=False), \
             patch("pm_core.qa_loop._poll_tmux_verdicts"), \
             patch("pm_core.qa_loop._run_qa_finalize_pane",
                   return_value="FINALIZE_DONE"):
            qa_loop._execute_and_finalize(
                state, tmp_path, {"branch": "b"}, {}, "pm-test", "qa-w",
                str(tmp_path), tmp_path / "status.json", None,
                use_containers=False, concurrency_cap=0,
                queued_scenarios=[], notify=lambda: None)

        assert state.latest_verdict == VERDICT_NEEDS_WORK
        assert state.held is False
        assert calls[0]["waiting_for_input"] == set()
        # The INPUT_REQUIRED evidence itself is kept.
        assert state.waiting_for_input == {1}
        assert state.scenario_verdicts[1] == VERDICT_INPUT_REQUIRED


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


def test_poll_qa_state_keeps_a_run_reopened_mid_tick(tmp_path):
    """The held watcher can reopen the run while ``_on_qa_complete`` is doing
    its note I/O.  The TUI already decided the state was finished, so without
    a re-check it would clear the reopened run's snapshot and mark the
    completion notified — its follow-up verdict would never be processed."""
    from pm_core.tui import qa_loop_ui

    app = _poll_app(tmp_path)
    state = _waiting_state(tmp_path / "t.jsonl")
    state.qa_workdir = str(tmp_path)
    state.held = True
    state.running = False
    state.latest_verdict = VERDICT_INPUT_REQUIRED
    state._ui_complete_notified = True
    _write_resume_file(state, use_containers=False, concurrency_cap=0)
    app._qa_loops = {"pr-001": state}

    def _reopen(_app, s):
        # The hold thread accepted a follow-up mid-tick.
        s.running = True
        s.held = False
        s.latest_verdict = ""
        s._ui_complete_notified = False

    with patch.object(qa_loop_ui, "_resume_incomplete_qa"), \
         patch.object(qa_loop_ui, "_on_qa_complete", side_effect=_reopen):
        qa_loop_ui.poll_qa_state(app)

    assert app._qa_loops.get("pr-001") is state
    assert (tmp_path / "qa_resume.json").exists()
    assert state._ui_complete_notified is False


def test_on_qa_complete_ignores_a_completion_with_no_verdict(tmp_path):
    """The held watcher reopens the run (clearing ``latest_verdict``) from
    its own thread.  If that lands between the TUI's entry check and this
    callback's read, there is nothing to record — noting it would write a
    bogus "QA : ..." note and log a verdict-less "QA finished" line."""
    from pm_core.tui import qa_loop_ui

    app = _poll_app(tmp_path)
    state = _waiting_state(tmp_path / "t.jsonl")
    state.latest_verdict = ""  # cleared by the reopen

    with patch.object(qa_loop_ui, "_record_qa_note") as note:
        qa_loop_ui._on_qa_complete(app, state)

    note.assert_not_called()
    app.log_message.assert_not_called()


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


def test_fresh_start_supersedes_a_run_that_has_no_workdir_yet(tmp_path):
    """The superseded flag must not depend on the run having a qa workdir.

    ``run_qa_sync`` creates its workdir after startup, so a run superseded in
    that window would otherwise write a resume snapshot later — and a restart
    scan would re-adopt the discarded run and record a spurious QA note.
    """
    from pm_core.tui import qa_loop_ui

    app = _poll_app(tmp_path)
    state = QALoopState(pr_id="pr-001")
    state.running = True
    state.qa_workdir = None
    app._qa_loops = {"pr-001": state}

    with patch.object(qa_loop_ui, "start_qa"):
        qa_loop_ui.fresh_start_qa(app, "pr-001")

    assert state.stop_requested is True
    assert state.superseded is True

    # Its later snapshot write is suppressed even though it now has a workdir.
    late = tmp_path / "late-workdir"
    late.mkdir()
    state.qa_workdir = str(late)
    _write_resume_file(state, use_containers=False, concurrency_cap=0)
    assert not (late / "qa_resume.json").exists()


def test_qa_loop_restart_supersedes_a_stale_state(tmp_path):
    """The ``zz t`` restart path marks the discarded state superseded and
    drops its snapshot, so the run it replaces cannot be re-adopted."""
    from pm_core.tui import qa_loop_ui

    app = _poll_app(tmp_path)
    state = QALoopState(pr_id="pr-001")
    state.running = False
    state.qa_workdir = str(tmp_path)
    _write_resume_file(state, use_containers=False, concurrency_cap=0)
    assert (tmp_path / "qa_resume.json").exists()
    app._qa_loops = {"pr-001": state}

    with patch.object(qa_loop_ui, "_enter_qa_status", return_value=True), \
         patch.object(qa_loop_ui, "start_qa_background"):
        qa_loop_ui.start_or_stop_qa_loop(app, "pr-001")

    assert state.superseded is True
    assert not (tmp_path / "qa_resume.json").exists()


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


def test_status_file_marks_waiting_scenarios(tmp_path):
    """The status file is what the TUI renders from, so a waiting scenario
    must be flagged per row (and at the top level) for the ``(waiting)``
    marker to appear."""
    import json

    scenario = QAScenario(index=1, title="A", focus="a")
    status_path = tmp_path / "status.json"
    qa_loop._write_status_file(
        status_path, "pr-001", [scenario],
        {1: VERDICT_INPUT_REQUIRED}, overall=VERDICT_INPUT_REQUIRED,
        waiting_for_input={1})

    data = json.loads(status_path.read_text())
    assert data["waiting_for_input"] == [1]
    assert data["scenarios"][0]["waiting_for_input"] is True


def test_held_run_keeps_the_poll_timer_armed(tmp_path):
    """A held run has ``running=False`` but still needs the shared poll
    timer: without it the follow-up is never collected and the reopened
    result is never processed.  With no active PR to keep the timer alive,
    the held loop itself must count as active."""
    from unittest.mock import MagicMock

    from pm_core.tui import review_loop_ui

    app = MagicMock()
    app._data = {"prs": []}
    app._review_loops = {}
    app._review_loop_timer = None
    state = QALoopState(pr_id="pr-001")
    state.running = False
    state.held = True
    app._qa_loops = {"pr-001": state}

    review_loop_ui.ensure_animation_timer(app)

    assert app._review_loop_timer is not None

