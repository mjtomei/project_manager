"""Container release for QA runs held for a human (spec impl.md A11).

master@4a74d880 (pr-2c67d50) keeps a worker that emitted INPUT_REQUIRED
under observation and holds a finalized INPUT_REQUIRED run open until a
follow-up arrives.  The hold has no time limit, so the run's settled
containers must not wait for it to end, and a waiting worker is not a
settled one: releasing it as "kept" would leave its later follow-up's
container running until the run ends.
"""

import itertools
import json
from contextlib import ExitStack
from unittest.mock import patch

from pm_core import qa_loop
from pm_core.qa_loop import (
    QALoopState,
    QAScenario,
    VERDICT_INPUT_REQUIRED,
    VERDICT_PASS,
)


def _assistant(text, uuid, ts):
    return json.dumps({
        "type": "assistant", "uuid": uuid, "timestamp": ts,
        "message": {"role": "assistant",
                    "content": [{"type": "text", "text": text}]},
    })


PROMPT = json.dumps({"type": "user", "message": {
    "role": "user", "content": 'You are running QA scenario 1: "Test"'}})


def _transcript(path, *records):
    path.write_text("\n".join(records) + "\n")
    return str(path)


def _scenario(idx, transcript):
    return QAScenario(
        index=idx, title=f"S{idx}", focus="f", window_name=f"qa-s{idx}",
        pane_id=f"%{idx}", transcript_path=transcript,
        session_id=f"sid-{idx}", container_name=f"pm-t-qa-pr-001-x-s{idx}",
        container_id=f"{idx:064x}", container_generation=1)


class TestWaitingWorkerIsNotSettled:
    def test_follow_up_container_is_released_during_the_poll(self, tmp_path):
        """s1 waits for input while s2 is still running, then answers PASS.

        The waiting worker must not be released (and marked released) as a
        settled one; once its follow-up lands it is settled and released
        before the poll ends.
        """
        s1_path = tmp_path / "s1.jsonl"
        s1 = _scenario(1, _transcript(
            s1_path, PROMPT,
            _assistant("Reason: need a decision\nINPUT_REQUIRED", "ir",
                       "2026-05-13T14:01:00.000Z")))
        s2 = _scenario(2, _transcript(
            tmp_path / "s2.jsonl", PROMPT,
            _assistant("Reason: fine\nPASS", "p2",
                       "2026-05-13T14:01:00.000Z")))
        state = QALoopState(pr_id="pr-001")
        state.qa_workdir = None
        state.scenarios = [s1, s2]

        sleeps = itertools.count(1)

        def _sleep(_secs):
            if next(sleeps) == 2:
                # The user answered in s1's pane after it started waiting.
                with s1_path.open("a") as f:
                    f.write(_assistant("Reason: answered\nPASS", "p1",
                                       "2026-05-13T14:05:00.000Z") + "\n")

        s2_events = itertools.count(1)

        def _event(session_id):
            if session_id == "sid-2" and next(s2_events) < 4:
                return None   # s2 is still working for a few ticks
            return {"event_type": "idle_prompt", "timestamp": 1e12}

        # (scenario, was it waiting for input when handed to a release?)
        released: list[tuple[int, bool]] = []

        def _release(st, _session, *, scenarios=None, kept_indices=None):
            released.extend((s.index, s.index in st.waiting_for_input)
                            for s in scenarios)
            return False

        clock = itertools.count(0, 1000)
        with ExitStack() as stack:
            for p in (
                patch("pm_core.qa_loop.time.sleep", side_effect=_sleep),
                patch("pm_core.qa_loop.time.monotonic",
                      side_effect=lambda: next(clock)),
                patch("pm_core.hook_events.read_event", side_effect=_event),
                patch("pm_core.tmux.pane_exists", return_value=True),
                patch("pm_core.qa_loop._is_verification_enabled",
                      return_value=False),
                patch("pm_core.qa_loop._release_scenario_containers",
                      side_effect=_release),
                patch("pm_core.claude_launcher.WorkspacePromptWatch"),
            ):
                stack.enter_context(p)
            # s2's worker shows no trust dialog while it has no hook event.
            from pm_core import claude_launcher
            claude_launcher.WorkspacePromptWatch.return_value.check.return_value = None
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", "/tmp/work",
                tmp_path / "status.json", lambda *a: None,
                use_containers=True)

        assert state.scenario_verdicts == {1: VERDICT_PASS, 2: VERDICT_PASS}
        assert not state.waiting_for_input
        # s1 was never handed to a release while it waited, and was released
        # once its follow-up settled it.
        assert (1, True) not in released
        assert (1, False) in released


class TestReleaseBeforeHold:
    def _finalize(self, state, tmp_path, release, hold):
        with patch("pm_core.qa_loop._persist_scenario_verdicts"), \
             patch("pm_core.qa_loop._write_resume_file"), \
             patch("pm_core.qa_loop._write_status_file"), \
             patch("pm_core.qa_loop._poll_tmux_verdicts"), \
             patch("pm_core.qa_loop._run_qa_finalize_pane",
                   return_value="FINALIZE_DONE"), \
             patch("pm_core.qa_loop._release_scenario_containers",
                   side_effect=release), \
             patch("pm_core.qa_loop._hold_for_follow_up", side_effect=hold):
            qa_loop._execute_and_finalize(
                state, tmp_path, {"branch": "b"}, {}, "pm-test", "qa-w",
                str(tmp_path), tmp_path / "status.json", None,
                use_containers=True, concurrency_cap=0,
                queued_scenarios=[], notify=lambda: None)

    def _held_state(self, tmp_path):
        s1 = _scenario(1, str(tmp_path / "s1.jsonl"))
        s2 = _scenario(2, str(tmp_path / "s2.jsonl"))
        state = QALoopState(pr_id="pr-001")
        state.qa_workdir = None
        state.scenarios = [s1, s2]
        state.scenario_verdicts = {1: VERDICT_INPUT_REQUIRED, 2: VERDICT_PASS}
        state.waiting_for_input = {1}
        state.waiting_input_sources = {1: {
            "pr_id": "pr-001", "loop_id": state.loop_id, "scenario": 1,
            "session_id": "sid-1", "transcript_path": s1.transcript_path,
            "line_index": 1}}
        return state

    def test_settled_containers_are_released_before_the_hold(self, tmp_path):
        state = self._held_state(tmp_path)
        events: list[str] = []

        def _release(_state, _session, **_kw):
            events.append("release")
            return False

        def _hold(*_a, **_kw):
            events.append("hold")
            return False

        self._finalize(state, tmp_path, _release, _hold)
        # Released before waiting for the human, and again at run end.
        assert events == ["release", "hold", "release"]
        assert state._deferred_release_session == ""

    def test_deferred_release_before_the_hold_is_retried_by_it(self, tmp_path):
        state = self._held_state(tmp_path)
        results = iter([True, False])   # deferred before the hold, then done

        def _release(_state, _session, **_kw):
            return next(results)

        def _hold(st, *_a, **_kw):
            assert st._deferred_release_session == "pm-test"
            return False

        with patch("pm_core.qa_loop._RELEASE_RETRY_DELAYS", ()):
            self._finalize(state, tmp_path, _release, _hold)

    def test_hold_retries_a_deferred_release(self, tmp_path):
        state = self._held_state(tmp_path)
        state._deferred_release_session = "pm-test"
        ticks = itertools.count(1)

        def _scan(st):
            if next(ticks) >= 2:
                st.stop_requested = True
            return qa_loop._WaitingScan()

        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop._HOLD_STATUS_CHECK_TICKS", 1), \
             patch("pm_core.qa_loop._scan_waiting_scenarios",
                   side_effect=_scan), \
             patch("pm_core.qa_loop._release_scenario_containers",
                   return_value=False) as release:
            reopened = qa_loop._hold_for_follow_up(
                state, None, tmp_path / "status.json", True, 0, set(),
                session="pm-test")

        assert reopened is False
        release.assert_called_with(state, "pm-test")
        assert state._deferred_release_session == ""


def test_resume_scan_restores_a_held_runs_floor_claim(tmp_path, monkeypatch):
    """A held run's kept floor container keeps the slot across a restart."""
    from types import SimpleNamespace
    from pm_core.tui import qa_loop_ui

    home = tmp_path / "home"
    qa_dir = home / ".pm" / "workdirs" / "qa" / "pr-001-abc"
    qa_dir.mkdir(parents=True)
    state = QALoopState(pr_id="pr-001")
    state.qa_workdir = str(qa_dir)
    s1 = _scenario(1, str(qa_dir / "s1.jsonl"))
    state.scenarios = [s1]
    state.scenario_verdicts = {1: VERDICT_INPUT_REQUIRED}
    state.waiting_for_input = {1}
    state.waiting_input_sources = {1: {
        "pr_id": "pr-001", "loop_id": state.loop_id, "scenario": 1,
        "session_id": "sid-1", "transcript_path": s1.transcript_path,
        "line_index": 1}}
    state.held = True
    state.completion_processed = True
    with patch("pm_core.qa_loop._own_floor_container",
               return_value=s1.container_name):
        qa_loop._write_resume_file(state, True, 1, set(), desired_cap=4)
    (qa_dir / "qa_status.json").write_text(
        json.dumps({"overall": VERDICT_INPUT_REQUIRED}))

    monkeypatch.setattr(qa_loop, "_floor_slot", {})
    monkeypatch.setattr(qa_loop, "resume_owned_elsewhere", lambda _d: False)
    app = SimpleNamespace(
        _qa_loops={}, _root=tmp_path, log_message=lambda *a, **k: None,
        call_from_thread=lambda *a, **k: None)
    spawned = []
    with patch("pathlib.Path.home", return_value=home), \
         patch("pm_core.store.load", return_value={}), \
         patch("pm_core.store.get_pr",
               return_value={"id": "pr-001", "status": "qa"}), \
         patch("pm_core.qa_loop.resume_qa_background",
               side_effect=lambda st, *_a: spawned.append(
                   dict(qa_loop._floor_slot))):
        qa_loop_ui._resume_incomplete_qa(app)

    assert app._qa_loops["pr-001"].held is True
    # The claim was back before the held run's watcher was spawned.
    assert spawned == [{"run": ("pr-001", state.loop_id),
                        "name": s1.container_name}]
