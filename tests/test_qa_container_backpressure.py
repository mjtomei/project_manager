"""Queued QA work releases settled allocations rather than accumulating them."""

from unittest.mock import MagicMock

import pytest

from pm_core import hook_events, qa_loop, tmux


@pytest.mark.parametrize("verify", [False, True])
@pytest.mark.parametrize("failed_second", [False, True])
def test_queue_releases_completed_containers_before_next_launch(
        tmp_path, monkeypatch, verify, failed_second):
    state = qa_loop.QALoopState(pr_id="pr-aaaa")
    state.scenarios = [
        qa_loop.QAScenario(index=i, title=f"s{i}", focus="",
                           container_name=f"pm-t-qa-pr-aaaa-L-s{i}")
        for i in range(1, 5)
    ]
    live = set()
    peak = 0
    launched = []
    released = []

    def launch(scenario):
        nonlocal peak
        launched.append(scenario.index)
        if failed_second and scenario.index == 2:
            qa_loop._record_launch_failure(state, scenario, "runtime unavailable")
            return
        live.add(scenario.index)
        peak = max(peak, len(live))
        scenario.window_name = f"qa-s{scenario.index}"
        scenario.pane_id = f"%{scenario.index}"
        scenario.session_id = f"sid-{scenario.index}"
        scenario.transcript_path = str(tmp_path / f"s{scenario.index}.jsonl")

    launch(state.scenarios[0])

    def release(state, session, *, scenarios=None):
        for scenario in scenarios or state.scenarios:
            if scenario.index not in live:
                continue
            assert state.scenario_verdicts[scenario.index] == qa_loop.VERDICT_PASS
            if verify:
                assert scenario.index in state.verified_scenarios
            live.remove(scenario.index)
            released.append(scenario.index)
        return False

    ticks = 0

    def tick(_seconds):
        nonlocal ticks
        ticks += 1
        assert ticks < 12, "queued launch failures must not strand the remaining queue"

    class ImmediateThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(qa_loop, "_is_verification_enabled", lambda: verify)
    monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
    # The queued-launch path re-clamps only when container-max-running is
    # configured; keep this test off the host's real setting and inventory.
    from pm_core import container as container_mod
    monkeypatch.setattr(container_mod, "max_running_containers", lambda: 0)
    monkeypatch.setattr(qa_loop.time, "sleep", tick)
    monkeypatch.setattr(qa_loop.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(qa_loop, "_write_resume_file", MagicMock())
    monkeypatch.setattr(qa_loop, "_write_status_file", MagicMock())
    monkeypatch.setattr(qa_loop, "_verify_single_scenario",
                        lambda *a, **k: (True, "verified", "%99"))
    monkeypatch.setattr(qa_loop, "_launch_scenarios_in_containers",
                        lambda st, *a, **k: launch(st.scenarios[0]))
    monkeypatch.setattr(qa_loop, "_release_scenario_containers", release)
    monkeypatch.setattr(tmux, "pane_exists", lambda p: True)
    monkeypatch.setattr(hook_events, "read_event",
                        lambda sid: {"event_type": "idle_prompt", "timestamp": 1})
    monkeypatch.setattr(qa_loop, "extract_verdict_from_transcript", lambda *a: "PASS")
    monkeypatch.setattr(qa_loop, "extract_verdict_reason_from_transcript", lambda *a: None)

    qa_loop._poll_tmux_verdicts(
        state, {}, {}, "pm-t", str(tmp_path), tmp_path / "status.json",
        lambda: None, queued_scenarios=state.scenarios[1:],
        concurrency_cap=1, use_containers=True)

    assert launched == [1, 2, 3, 4]
    assert peak == 1
    assert 1 in released and 3 in released
    if failed_second:
        assert 2 not in state.scenario_verdicts
        assert qa_loop._is_launch_failure(state, 2)


def test_unknown_running_count_does_not_disable_the_cap(monkeypatch):
    """An unavailable inventory must not read as "zero running containers".

    ``running_container_count`` returns None when the runtime cannot be
    inventoried — exactly the pressure the cap protects against.  Treating
    that as 0 launched a full batch.  Clamping to one still starts queued
    work and re-clamps on the next poll.
    """
    from pm_core import container as container_mod
    monkeypatch.setattr(container_mod, "max_running_containers", lambda: 4)
    monkeypatch.setattr(container_mod, "running_container_count", lambda: None)
    assert qa_loop._clamp_to_container_headroom(4) == 1
    assert qa_loop._clamp_to_container_headroom(0) == 1
    monkeypatch.setattr(container_mod, "running_container_count", lambda: 1)
    assert qa_loop._clamp_to_container_headroom(4) == 3
    monkeypatch.setattr(container_mod, "running_container_count", lambda: 3)
    assert qa_loop._clamp_to_container_headroom(4) == 1


def test_poll_reclamps_container_headroom_before_a_queued_launch(
        tmp_path, monkeypatch):
    """The poll re-clamps the batch with a fresh count before each launch.

    A cap clamped at run start from an unreadable inventory is one; leaving it
    there would serialize the rest of the run after the runtime recovered.
    """
    from pm_core import container as container_mod
    state = qa_loop.QALoopState(pr_id="pr-aaaa")
    state.scenarios = [
        qa_loop.QAScenario(index=i, title=f"s{i}", focus="",
                           container_name=f"pm-t-qa-pr-aaaa-L-s{i}")
        for i in range(1, 3)
    ]
    launched = []

    def launch(scenario):
        launched.append(scenario.index)
        scenario.window_name = f"qa-s{scenario.index}"
        scenario.pane_id = f"%{scenario.index}"
        scenario.session_id = f"sid-{scenario.index}"
        scenario.transcript_path = str(tmp_path / f"s{scenario.index}.jsonl")

    launch(state.scenarios[0])
    reclamps = []

    def reclamp(cap):
        reclamps.append(cap)
        return 1

    class ImmediateThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(container_mod, "max_running_containers", lambda: 4)
    monkeypatch.setattr(qa_loop, "_clamp_to_container_headroom", reclamp)
    monkeypatch.setattr(qa_loop, "_is_verification_enabled", lambda: False)
    monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
    ticks = 0

    def tick(_seconds):
        nonlocal ticks
        ticks += 1
        assert ticks < 12, "the verdict poll must terminate"

    monkeypatch.setattr(qa_loop.time, "sleep", tick)
    monkeypatch.setattr(qa_loop.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(qa_loop, "_write_resume_file", MagicMock())
    monkeypatch.setattr(qa_loop, "_write_status_file", MagicMock())
    monkeypatch.setattr(qa_loop, "_release_scenario_containers",
                        lambda st, session, *, scenarios=None: False)
    monkeypatch.setattr(qa_loop, "_launch_scenarios_in_containers",
                        lambda st, *a, **k: launch(st.scenarios[0]))
    monkeypatch.setattr(tmux, "pane_exists", lambda p: True)
    monkeypatch.setattr(hook_events, "read_event",
                        lambda sid: {"event_type": "idle_prompt", "timestamp": 1})
    monkeypatch.setattr(qa_loop, "extract_verdict_from_transcript", lambda *a: "PASS")
    monkeypatch.setattr(qa_loop, "extract_verdict_reason_from_transcript",
                        lambda *a: None)

    qa_loop._poll_tmux_verdicts(
        state, {}, {}, "pm-t", str(tmp_path), tmp_path / "status.json",
        lambda: None, queued_scenarios=state.scenarios[1:],
        concurrency_cap=1, use_containers=True)

    assert reclamps, "the poll must re-clamp with a fresh running count"
    assert launched == [1, 2]


def test_unlimited_cap_costs_no_inventory_per_launch(monkeypatch):
    """The default (container-max-running=0) path performs no inventory."""
    from pm_core import container as container_mod
    monkeypatch.setattr(container_mod, "max_running_containers", lambda: 0)
    monkeypatch.setattr(container_mod, "running_container_count",
                        lambda: pytest.fail("no inventory expected"))
    assert qa_loop._container_headroom_cap(3) == 3


@pytest.mark.parametrize("verdict", ["PASS", "NEEDS_WORK", "INPUT_REQUIRED"])
def test_resume_does_not_relaunch_settled_scenarios(tmp_path, monkeypatch, verdict):
    scenario = qa_loop.QAScenario(
        index=1, title="done", focus="", window_name="qa-s1", pane_id="%1",
        session_id="completed-worker")
    state = qa_loop.QALoopState(pr_id="pr-aaaa")
    state.scenarios = [scenario]
    state.scenario_verdicts = {1: verdict}
    state.verified_scenarios.add(1)
    monkeypatch.setattr(qa_loop, "_is_verification_enabled", lambda: True)
    monkeypatch.setattr(tmux, "pane_exists", lambda p: False)
    monkeypatch.setattr(qa_loop.time, "sleep", lambda seconds: None)
    relaunch = MagicMock(return_value=False)
    monkeypatch.setattr(qa_loop, "_relaunch_scenario_window", relaunch)
    qa_loop._poll_tmux_verdicts(
        state, {}, {}, "pm-t", str(tmp_path), tmp_path / "status.json", lambda: None)
    relaunch.assert_not_called()
    assert state.scenario_verdicts == {1: verdict}
