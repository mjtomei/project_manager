"""Memory governor integration in the QA loop.

Covers stop-on-idle on QA verdict transitions, memory admission of queued
scenarios (waiting, retry, release), and the initial batch admission.
The launch queue is real (isolated under a temp ``~/.pm`` by conftest);
memory measurement is patched.
"""

import contextlib
import time
from unittest.mock import patch

import pytest

from pm_core import launch_queue as lq
from pm_core import memory_governor as mg
from pm_core.qa_loop import (
    QALoopState,
    QAScenario,
    VERDICT_INPUT_REQUIRED,
    VERDICT_NEEDS_WORK,
    VERDICT_PASS,
    _admit_initial_batch,
    _get_window_pane_ids,
    _maybe_stop_idle_container,
    _poll_tmux_verdicts,
)


_real_sleep = time.sleep  # qa_loop's time.sleep patch is process-wide


def _scenario(idx, launched=True):
    s = QAScenario(index=idx, title=f"S{idx}", focus="f")
    if launched:
        s.window_name = f"qa-pr-1-s{idx}"
        s.container_name = f"pm-t-qa-pr-1-loop-s{idx}"
        s.session_id = f"sid-{idx}"
        s.transcript_path = f"/t/s{idx}.jsonl"
    return s


def _state(scenarios):
    state = QALoopState(pr_id="pr-1")
    state.loop_id = "loop"
    state.session_tag = "t"
    state.scenarios = list(scenarios)
    return state


@contextlib.contextmanager
def _governor(target_g=48, used_g=30, proj_g=8, error="", running=()):
    """Active governor with a fixed measurement."""
    def _snap(stats=None):
        return mg.MemorySnapshot(
            target_mb=target_g * 1024, used_mb=None if error else used_g * 1024,
            measured_mb=None if error else used_g * 1024,
            running_names=set(running), error=error)

    with patch("pm_core.memory_governor.get_memory_target",
               return_value=target_g * 1024), \
         patch("pm_core.memory_governor.take_snapshot", side_effect=_snap) as snap, \
         patch("pm_core.memory_governor.project_memory",
               side_effect=lambda t, stats=None: proj_g * 1024), \
         patch("pm_core.memory_governor.load_stats", return_value={}):
        yield snap


def _drive(tmp_path, state, *, verdicts=None, use_containers=True,
           verify=False, verify_result=(True, ""), queued=None, cap=0,
           entry_id_map=None, pending_entry_ids=None, max_sleeps=400,
           on_sleep=None):
    """Run _poll_tmux_verdicts with hook-driven verdict mocks.

    *verdicts* maps scenario index -> verdict its transcript holds.
    Returns (stop_mock, write_status_mock, launched_indices).
    """
    verdicts = verdicts or {}
    sleeps = []
    launched = []

    def fake_sleep(secs):
        sleeps.append(secs)
        if on_sleep:
            on_sleep(len(sleeps))
        _real_sleep(0.001)  # let verification threads run
        if len(sleeps) >= max_sleeps:
            state.stop_requested = True

    def fake_launch(st, data, pr_data, session, repo_root, workdir_path,
                    pm_root=None, _status_scenarios=None):
        for sc in st.scenarios:
            launched.append(sc.index)
            sc.window_name = f"qa-pr-1-s{sc.index}"
            sc.container_name = f"pm-t-qa-pr-1-loop-s{sc.index}"
            sc.session_id = f"sid-{sc.index}"
            sc.transcript_path = f"/t/s{sc.index}.jsonl"

    def verdict_for(path, _all):
        idx = int(path.rsplit("/s", 1)[1].split(".")[0])
        return verdicts.get(idx)

    event = {"event_type": "idle_prompt", "timestamp": time.time() + 1000}
    with patch("pm_core.qa_loop._VERDICT_GRACE_PERIOD", 0), \
         patch("pm_core.qa_loop.time.sleep", side_effect=fake_sleep), \
         patch("pm_core.qa_loop._write_status_file") as write_status, \
         patch("pm_core.qa_loop._write_resume_file"), \
         patch("pm_core.qa_loop._is_verification_enabled", return_value=verify), \
         patch("pm_core.qa_loop._get_verification_max_retries", return_value=0), \
         patch("pm_core.qa_loop._get_verdict_reminder_timeout", return_value=None), \
         patch("pm_core.qa_loop._get_scenario_pane", return_value="%10"), \
         patch("pm_core.tmux.pane_exists", return_value=True), \
         patch("pm_core.hook_events.read_event", return_value=event), \
         patch("pm_core.qa_loop.extract_verdict_from_transcript",
               side_effect=verdict_for), \
         patch("pm_core.qa_loop.extract_verdict_reason_from_transcript",
               return_value="because"), \
         patch("pm_core.qa_loop._verify_single_scenario",
               return_value=(*verify_result, None)), \
         patch("pm_core.qa_loop._maybe_stop_idle_container") as stop, \
         patch("pm_core.qa_loop._launch_scenarios_in_containers",
               side_effect=fake_launch), \
         patch("pm_core.qa_loop._launch_scenarios_in_tmux",
               side_effect=fake_launch):
        _poll_tmux_verdicts(
            state, {}, {}, "sess", "/tmp/w", tmp_path / "status.json",
            lambda: None, queued_scenarios=queued, concurrency_cap=cap,
            use_containers=use_containers, entry_id_map=entry_id_map,
            pending_entry_ids=pending_entry_ids,
        )
    return stop, write_status, launched


def _queue_entries():
    return lq._load_queue()["entries"]


# ---------------------------------------------------------------------------
# Stop-on-idle on verdict transitions
# ---------------------------------------------------------------------------

class TestStopOnIdleVerdicts:
    def test_needs_work_stops_with_verdict_time(self, tmp_path):
        s1 = _scenario(1)
        state = _state([s1])
        stop, _, _ = _drive(tmp_path, state, verdicts={1: VERDICT_NEEDS_WORK})
        stop.assert_called_once()
        args = stop.call_args[0]
        assert args[0] is s1 and args[1] == "sess"
        assert args[2] > time.time()  # the idle_prompt event's timestamp

    def test_input_required_keeps_container(self, tmp_path):
        state = _state([_scenario(1)])
        stop, _, _ = _drive(tmp_path, state, verdicts={1: VERDICT_INPUT_REQUIRED})
        assert state.scenario_verdicts[1] == VERDICT_INPUT_REQUIRED
        stop.assert_not_called()

    def test_pass_stops_only_after_verification_passes(self, tmp_path):
        state = _state([_scenario(1)])
        stop, _, _ = _drive(tmp_path, state, verdicts={1: VERDICT_PASS},
                            verify=True, verify_result=(True, ""))
        assert 1 in state.verified_scenarios
        stop.assert_called_once()

    def test_failed_verification_becomes_needs_work_and_stops(self, tmp_path):
        state = _state([_scenario(1)])
        stop, _, _ = _drive(tmp_path, state, verdicts={1: VERDICT_PASS},
                            verify=True, verify_result=(False, "no evidence"))
        assert state.scenario_verdicts[1] == VERDICT_NEEDS_WORK
        stop.assert_called_once()

    def test_host_mode_never_stops(self, tmp_path):
        state = _state([_scenario(1)])
        stop, _, _ = _drive(tmp_path, state, verdicts={1: VERDICT_NEEDS_WORK},
                            use_containers=False)
        stop.assert_not_called()


class TestMaybeStopIdleContainer:
    def test_forwards_exact_container_panes_and_idle_time(self):
        s1 = _scenario(1)
        with patch("pm_core.qa_loop._get_window_pane_ids",
                   return_value=["%1", "%2"]) as panes, \
             patch("pm_core.container.stop_idle_in_background") as bg:
            _maybe_stop_idle_container(s1, "sess", 123.0)
        panes.assert_called_once_with("sess", s1.window_name)
        bg.assert_called_once_with(
            s1.container_name, "qa_scenario", pane_ids=["%1", "%2"],
            transcript_path=s1.transcript_path, idle_since=123.0)

    def test_no_container_does_nothing(self):
        s = _scenario(1)
        s.container_name = None
        with patch("pm_core.container.stop_idle_in_background") as bg:
            _maybe_stop_idle_container(s, "sess", 1.0)
        bg.assert_not_called()


class TestGetWindowPaneIds:
    def test_returns_pane_ids(self):
        with patch("pm_core.tmux.find_window_by_name",
                   return_value={"id": "@1", "index": "2", "name": "w"}), \
             patch("pm_core.tmux.get_pane_indices",
                   return_value=[("%10", 0), ("%11", 1)]) as idx:
            assert _get_window_pane_ids("pm", "w") == ["%10", "%11"]
        idx.assert_called_with("pm", "2")

    def test_missing_window_or_error(self):
        assert _get_window_pane_ids("pm", None) == []
        with patch("pm_core.tmux.find_window_by_name", return_value=None):
            assert _get_window_pane_ids("pm", "gone") == []
        with patch("pm_core.tmux.find_window_by_name",
                   side_effect=RuntimeError("tmux dead")):
            assert _get_window_pane_ids("pm", "w") == []


# ---------------------------------------------------------------------------
# Queued scenario admission in the poll loop
# ---------------------------------------------------------------------------

def _waiting_writes(write_status):
    """(memory_waiting set, reasons) for every status write."""
    out = []
    for c in write_status.call_args_list:
        out.append((set(c.kwargs.get("memory_waiting_scenarios") or ()),
                    c.kwargs.get("verdict_reasons") or {}))
    return out


class TestQueuedAdmission:
    def test_waits_for_memory_with_reason(self, tmp_path):
        s2 = _scenario(2, launched=False)
        state = _state([s2])
        with _governor(used_g=44):
            _, ws, launched = _drive(tmp_path, state, queued=[s2], max_sleeps=3)
        assert launched == []
        waiting = [w for w in _waiting_writes(ws) if 2 in w[0]]
        assert waiting, "scenario 2 never shown as waiting_memory"
        assert "waiting for memory" in waiting[0][1][2]
        assert "target" in waiting[0][1][2]

    def test_measurement_failure_waits_instead_of_launching(self, tmp_path):
        """Regression: failed stats used to let queued scenarios launch."""
        s2 = _scenario(2, launched=False)
        state = _state([s2])
        with _governor(error="podman stats failed (rc=125)"):
            _, ws, launched = _drive(tmp_path, state, queued=[s2], max_sleeps=3)
        assert launched == []
        reasons = [w[1].get(2, "") for w in _waiting_writes(ws) if 2 in w[0]]
        assert reasons and "rc=125" in reasons[0]

    def test_launches_once_memory_frees_and_releases_entry(self, tmp_path):
        s1 = _scenario(1)
        s2 = _scenario(2, launched=False)
        state = _state([s1, s2])
        used = {"g": 44}

        def snap(stats=None):
            return mg.MemorySnapshot(target_mb=48 * 1024,
                                     used_mb=used["g"] * 1024,
                                     measured_mb=used["g"] * 1024)

        def on_sleep(n):
            if n == 3:
                used["g"] = 30  # s1's container went away

        with _governor(), \
             patch("pm_core.memory_governor.take_snapshot", side_effect=snap), \
             patch("pm_core.qa_loop._MEMORY_RETRY_INTERVAL", 0):
            _, _, launched = _drive(tmp_path, state, queued=[s2],
                                    verdicts={1: VERDICT_NEEDS_WORK},
                                    max_sleeps=8, on_sleep=on_sleep)
        assert launched == [2]
        assert _queue_entries() == []

    def test_capped_scenarios_do_not_reserve_memory(self, tmp_path):
        """Only scenarios with a free slot get queue entries: the ones held
        back by the concurrency cap must not reserve memory."""
        s1 = _scenario(1)
        queued = [_scenario(i, launched=False) for i in (2, 3, 4)]
        state = _state([s1, *queued])
        seen = []
        # cap 2 with s1 running: one free slot, and no room for it.
        with _governor(used_g=44):
            _drive(tmp_path, state, queued=queued, cap=2, max_sleeps=3,
                   on_sleep=lambda n: seen.append(
                       sorted(e["key"] for e in _queue_entries())))
        assert seen and all(keys == ["pr-1-loop:s2"] for keys in seen), seen

    def test_full_cap_creates_no_entries(self, tmp_path):
        s1 = _scenario(1)
        queued = [_scenario(i, launched=False) for i in (2, 3)]
        state = _state([s1, *queued])
        seen = []
        with _governor():
            _drive(tmp_path, state, queued=queued, cap=1, max_sleeps=3,
                   on_sleep=lambda n: seen.append(len(_queue_entries())))
        assert set(seen) == {0}

    def test_retries_are_rate_limited(self, tmp_path):
        s2 = _scenario(2, launched=False)
        state = _state([s2])
        with _governor(used_g=44) as snap, \
             patch("pm_core.qa_loop._MEMORY_RETRY_INTERVAL", 3600):
            _drive(tmp_path, state, queued=[s2], max_sleeps=10)
        assert snap.call_count == 1

    def test_stop_releases_all_entries(self, tmp_path):
        queued = [_scenario(i, launched=False) for i in (2, 3)]
        state = _state(queued)
        seen = []
        with _governor(used_g=44):
            _drive(tmp_path, state, queued=queued, max_sleeps=3,
                   on_sleep=lambda n: seen.append(len(_queue_entries())))
        assert max(seen) >= 1      # the head held a waiting entry
        assert _queue_entries() == []

    def test_governor_off_launches_without_queue(self, tmp_path):
        s2 = _scenario(2, launched=False)
        state = _state([s2])
        _, _, launched = _drive(tmp_path, state, queued=[s2], max_sleeps=2)
        assert launched == [2]
        assert not (lq._queue_path()).exists()

    def test_target_set_mid_run_applies(self, tmp_path):
        """E8: a target set while scenarios are queued gates them."""
        s1 = _scenario(1)
        queued = [_scenario(2, launched=False)]
        state = _state([s1, *queued])
        with _governor(used_g=44):
            _, _, launched = _drive(tmp_path, state, queued=queued, cap=1,
                                    verdicts={1: VERDICT_NEEDS_WORK},
                                    max_sleeps=3)
        assert launched == []

    def test_resumed_run_rejoins_queue_lazily(self, tmp_path):
        """No entry map after a restart: entries are re-created on demand
        under the run's stable key and adopted if still present."""
        s2 = _scenario(2, launched=False)
        state = _state([s2])
        [old] = lq.enqueue("qa_scenario", qa_run_id="pr-1-loop",
                           keys=["pr-1-loop:s2"])
        q = lq._load_queue()
        q["entries"][0]["instance"] = "pre-restart"
        q["entries"][0]["enqueued_at"] = 1.0
        lq._save_queue(q)
        ids_seen = []
        with _governor(used_g=44):
            _drive(tmp_path, state, queued=[s2], max_sleeps=2,
                   on_sleep=lambda n: ids_seen.extend(
                       (e["id"], e["enqueued_at"]) for e in _queue_entries()))
        assert (old, 1.0) in ids_seen


class TestKeepaliveDuringLaunch:
    def test_queued_launch_keeps_waiting_entries_alive(self, tmp_path):
        """The launch blocks on the refiner for minutes; scenarios still
        waiting for memory are renewed meanwhile instead of expiring."""
        s2 = _scenario(2, launched=False)
        s3 = _scenario(3, launched=False)
        state = _state([s2, s3])
        [e3] = lq.enqueue("qa_scenario", qa_run_id="pr-1-loop",
                          keys=["pr-1-loop:s3"])
        renewed = []

        @contextlib.contextmanager
        def recording(ids, interval=15.0):
            renewed.append(set(ids))
            yield

        with _governor(used_g=30), \
             patch("pm_core.launch_queue.keepalive_during", recording):
            _, _, launched = _drive(tmp_path, state, queued=[s2, s3],
                                    entry_id_map={3: e3},
                                    pending_entry_ids={e3}, max_sleeps=2)
        assert launched[:1] == [2]
        assert e3 in renewed[0]


class TestInitialBatch:
    def test_partial_admission(self):
        scenarios = [_scenario(i, launched=False) for i in (1, 2, 3, 4)]
        state = _state(scenarios)
        with _governor(used_g=30, proj_g=8):
            admitted, blocked, entry_map, pending, reason = \
                _admit_initial_batch(state, scenarios)
        assert [s.index for s in admitted] == [1, 2]
        assert [s.index for s in blocked] == [3, 4]
        assert pending == {entry_map[3], entry_map[4]}
        assert "target" in reason
        names = {e["container_name"] for e in _queue_entries()}
        assert "pm-t-qa-pr-1-loop-s1" in names

    def test_governor_off_admits_all_without_entries(self):
        scenarios = [_scenario(i, launched=False) for i in (1, 2)]
        admitted, blocked, entry_map, pending, reason = \
            _admit_initial_batch(_state(scenarios), scenarios)
        assert admitted == scenarios and blocked == [] and entry_map == {}
        assert reason == ""

    def test_lock_busy_blocks_batch(self):
        scenarios = [_scenario(1, launched=False)]
        with _governor(), \
             patch("pm_core.launch_queue.governor_lock",
                   side_effect=lq.GovernorLockTimeout("busy")):
            admitted, blocked, _m, _p, reason = \
                _admit_initial_batch(_state(scenarios), scenarios)
        assert admitted == [] and blocked == scenarios
        assert "busy" in reason

    def test_scenario_larger_than_target_says_so(self):
        """E2: a scenario projected above the whole target can never launch
        until the target is raised — the waiting reason must say that."""
        scenarios = [_scenario(1, launched=False)]
        with _governor(target_g=4, used_g=0, proj_g=8):
            admitted, _b, _m, _p, reason = \
                _admit_initial_batch(_state(scenarios), scenarios)
        assert admitted == []
        assert "a single container cannot fit" in reason

    def test_measurement_failure_blocks_batch(self):
        scenarios = [_scenario(1, launched=False)]
        with _governor(error="stats unavailable"):
            admitted, blocked, _m, _p, reason = \
                _admit_initial_batch(_state(scenarios), scenarios)
        assert admitted == [] and "stats unavailable" in reason


class TestRunRelease:
    def test_crashed_poll_loop_releases_run_entries(self, tmp_path):
        """_execute_and_finalize releases the run's entries even if the
        poll loop raises (another run's entries are untouched)."""
        from pm_core import qa_loop
        state = _state([_scenario(2, launched=False)])
        lq.enqueue("qa_scenario", qa_run_id="pr-1-loop", keys=["pr-1-loop:s2"])
        lq.enqueue("qa_scenario", qa_run_id="pr-9-other", keys=["pr-9-other:s1"])
        with patch("pm_core.qa_loop._poll_tmux_verdicts",
                   side_effect=RuntimeError("boom")), \
             patch("pm_core.qa_loop._write_resume_file"):
            with pytest.raises(RuntimeError):
                qa_loop._execute_and_finalize(
                    state, tmp_path, {"branch": "b"}, {}, "sess", "qa-w",
                    str(tmp_path), tmp_path / "status.json", None,
                    use_containers=True, concurrency_cap=0,
                    queued_scenarios=[], notify=lambda: None)
        assert [e["qa_run_id"] for e in _queue_entries()] == ["pr-9-other"]

    def test_crashed_qa_thread_releases_run_entries(self, tmp_path):
        """A crash before the poll loop (whose finally releases entries)
        must not leave grants reserving memory for the life of the TUI."""
        from pm_core import qa_loop
        state = _state([_scenario(1, launched=False)])
        lq.enqueue("qa_scenario", qa_run_id="pr-1-loop", keys=["pr-1-loop:s1"])
        lq.enqueue("qa_scenario", qa_run_id="pr-9-other", keys=["pr-9-other:s1"])
        with patch("pm_core.qa_loop.run_qa_sync",
                   side_effect=RuntimeError("boom")):
            qa_loop.start_qa_background(state, tmp_path, {}).join(5)
        assert state.latest_verdict == "ERROR"
        assert [e["qa_run_id"] for e in _queue_entries()] == ["pr-9-other"]
