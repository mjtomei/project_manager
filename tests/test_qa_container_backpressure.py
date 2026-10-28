"""Queued QA work releases settled allocations rather than accumulating them."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pm_core import container_reaper, hook_events, qa_loop, tmux


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

    def release(state, session, *, scenarios=None, kept_indices=None):
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
                        lambda st, session, *, scenarios=None, kept_indices=None: False)
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


def test_reclamp_grows_a_reduced_batch_back_to_the_desired_size(monkeypatch):
    """Re-clamping the already-clamped batch could only keep or lower it.

    A batch reduced to one by an unreadable inventory (or a momentarily full
    runtime) must grow back to the run's batch once slots are free, otherwise
    the rest of the run stays serialized.
    """
    from pm_core import container as container_mod
    monkeypatch.setattr(container_mod, "max_running_containers", lambda: 4)
    monkeypatch.setattr(container_mod, "running_container_count", lambda: 0)
    assert qa_loop._container_headroom_cap(1, desired=4) == 4
    assert qa_loop._container_headroom_cap(1, desired=0) == 4  # unlimited desired
    # No desired batch (older callers): unchanged behaviour.
    assert qa_loop._container_headroom_cap(1) == 1


def test_poll_reclamps_from_the_desired_batch_not_the_clamped_one(
        tmp_path, monkeypatch):
    """The poll re-clamps the total batch from the run's original size.

    The run starts with ``concurrency_cap=1`` (an unreadable inventory clamps
    to one) and ``desired_cap=3``. With one worker running the fresh headroom
    is ``limit - running = 3`` more, so the total batch is the desired 3 and a
    queued scenario launches. Re-clamping the already-clamped ``1`` could only
    keep or lower it, so the run would stay serialized.
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

    class ImmediateThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(container_mod, "max_running_containers", lambda: 4)
    # The one running container is this run's active worker.
    monkeypatch.setattr(container_mod, "running_container_count", lambda: 1)
    # Spy on the re-clamp: the batch reaching the cap check must be recomputed
    # from the desired size, not left at the start-time clamped value.
    real_room = qa_loop._container_launch_room_known
    reclamps: list[tuple[int | None, int, int]] = []

    def _spy(cap, desired=None, active=0, own=()):
        result = real_room(cap, desired=desired, active=active, own=own)
        reclamps.append((desired, active, result[0]))
        return result

    monkeypatch.setattr(qa_loop, "_container_launch_room_known", _spy)
    # Settled s1's container is gone by then: only the active worker runs.
    monkeypatch.setattr(container_reaper, "list_containers", lambda: [
        container_reaper.ContainerInfo(name="pm-t-qa-pr-aaaa-L-s2", running=True)])
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
                        lambda st, session, *, scenarios=None, kept_indices=None: False)
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
        concurrency_cap=1, desired_cap=3, use_containers=True)

    # concurrency_cap started at 1 (unreadable inventory), but the fresh
    # headroom (limit 4, 1 running) makes the total batch 3, so the queued
    # scenario launches instead of the run staying serialized.
    assert launched == [1, 2]
    assert reclamps, "the poll must re-clamp with a fresh running count"
    assert reclamps[0][0] == 3, "the re-clamp starts from the desired batch"
    assert reclamps[0][2] == 3, "one active worker + 3 headroom = the desired batch"


def test_reclamp_counts_this_runs_active_workers_as_headroom(monkeypatch):
    """``container-max-running`` counts this run's workers, so the batch is
    ``active + remaining headroom`` — not the headroom compared to ``active``.

    Comparing ``active`` directly to the headroom would stall a capped run at
    roughly half the configured concurrency.
    """
    from pm_core import container as container_mod
    monkeypatch.setattr(container_mod, "max_running_containers", lambda: 4)
    # Three running containers, all this run's active workers: one slot left.
    monkeypatch.setattr(container_mod, "running_container_count", lambda: 3)
    assert qa_loop._container_headroom_cap(1, desired=4, active=3) == 4
    # A momentarily full runtime leaves no room to launch.
    monkeypatch.setattr(container_mod, "running_container_count", lambda: 4)
    assert qa_loop._container_headroom_cap(1, desired=4, active=2) == 2
    # Unknown inventory still launches one at a time.
    monkeypatch.setattr(container_mod, "running_container_count", lambda: None)
    assert qa_loop._container_headroom_cap(4, desired=4, active=2) == 1


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


def test_failed_settled_release_is_retried_so_the_batch_grows_back(
        tmp_path, monkeypatch):
    """A settled worker whose release failed (e.g. during an inventory outage)
    is retried on a later poll rather than only at run end.

    ``container-max-running`` counts every running pm container, including
    this run's settled-but-unreleased workers. Marking a failed release as
    done left those containers counted against the headroom for the rest of
    the run, so after the runtime recovered the re-clamp kept the queue
    serialized (one worker at a time) instead of growing back.
    """
    from pm_core import container as container_mod
    state = qa_loop.QALoopState(pr_id="pr-aaaa")
    state.scenarios = [
        qa_loop.QAScenario(index=i, title=f"s{i}", focus="",
                           container_name=f"pm-t-qa-pr-aaaa-L-s{i}")
        for i in range(1, 6)
    ]
    running = set()      # containers the runtime still runs (this run only)
    launched = []
    outage = {"polls_left": 2}

    def launch(scenario):
        launched.append(scenario.index)
        running.add(scenario.index)
        scenario.window_name = f"qa-s{scenario.index}"
        scenario.pane_id = f"%{scenario.index}"
        scenario.session_id = f"sid-{scenario.index}"
        scenario.transcript_path = str(tmp_path / f"s{scenario.index}.jsonl")

    for sc in state.scenarios[:2]:
        launch(sc)

    def release(st, session, *, scenarios=None, kept_indices=None):
        if outage["polls_left"] > 0:
            return True  # deferred: inventory unreadable, containers survive
        for sc in scenarios:
            running.discard(sc.index)
        return False

    # Workers 1 and 2 settle on the first poll; later workers stay verdictless
    # so the run's progress is decided by how far the batch grows back.
    verdict_for = {1: "PASS", 2: "PASS"}
    ticks = 0

    def tick(_seconds):
        nonlocal ticks
        ticks += 1
        outage["polls_left"] -= 1
        if ticks >= 6:
            state.stop_requested = True

    def inventory():
        if outage["polls_left"] > 0:
            return None  # the outage: the runtime cannot be listed
        return [container_reaper.ContainerInfo(
            name=f"pm-t-qa-pr-aaaa-L-s{i}", running=True) for i in sorted(running)]

    monkeypatch.setattr(container_mod, "max_running_containers", lambda: 2)
    monkeypatch.setattr(container_mod, "running_container_count",
                        lambda: None if (inv := inventory()) is None else len(inv))
    monkeypatch.setattr(container_reaper, "list_containers", inventory)
    monkeypatch.setattr(qa_loop, "_is_verification_enabled", lambda: False)
    monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
    monkeypatch.setattr(qa_loop, "_POLL_INTERVAL", 0)
    monkeypatch.setattr(qa_loop.time, "sleep", tick)
    monkeypatch.setattr(qa_loop, "_write_resume_file", MagicMock())
    monkeypatch.setattr(qa_loop, "_write_status_file", MagicMock())
    monkeypatch.setattr(qa_loop, "_release_scenario_containers", release)
    monkeypatch.setattr(qa_loop, "_launch_scenarios_in_containers",
                        lambda st, *a, **k: launch(st.scenarios[0]))
    monkeypatch.setattr(tmux, "pane_exists", lambda p: True)
    monkeypatch.setattr(hook_events, "read_event",
                        lambda sid: {"event_type": "idle_prompt", "timestamp": 1})
    monkeypatch.setattr(
        qa_loop, "extract_verdict_from_transcript",
        lambda path, *a: verdict_for.get(int(Path(path).stem[1:])))
    monkeypatch.setattr(qa_loop, "extract_verdict_reason_from_transcript",
                        lambda *a: None)

    qa_loop._poll_tmux_verdicts(
        state, {}, {}, "pm-t", str(tmp_path), tmp_path / "status.json",
        lambda: None, queued_scenarios=state.scenarios[2:],
        concurrency_cap=2, desired_cap=2, use_containers=True)

    # While the inventory is unreadable the release is deferred and the
    # unknown count admits one queued worker (the outage floor). Once the retried release succeeds,
    # the batch grows back to the desired two active workers.
    assert running.isdisjoint({1, 2}), "the deferred release must be retried in-run"
    assert launched == [1, 2, 3, 4]


def test_outage_admits_one_floor_launch_not_one_per_settled_worker(
        tmp_path, monkeypatch):
    """QA S59 story 3: an inventory outage that starts with the runtime full.

    A's s1-s4 + B fill container-max-running=5 when the inventory becomes
    unreadable. Releases need the same inventory, so each settled worker keeps
    running. The unknown count admits one floor launch (s5, L+1 = 6, qa.md
    resolution 19). Before the fix, s5's own settlement admitted s6 as another
    floor launch while every earlier release was still deferred: 7 = L+2.
    After recovery the deferred releases complete and the batch grows back.
    """
    from pm_core import container as container_mod
    state = qa_loop.QALoopState(pr_id="pr-aaaa")
    state.scenarios = [
        qa_loop.QAScenario(index=i, title=f"s{i}", focus="",
                           container_name=f"pm-t-qa-pr-aaaa-L-s{i}")
        for i in range(1, 9)
    ]
    running = set()      # this run's containers the runtime still runs
    launched = []
    outage = {"polls_left": 5}
    peak = {"outage": 0, "after": 0}

    def launch(scenario):
        launched.append(scenario.index)
        running.add(scenario.index)
        key = "outage" if outage["polls_left"] > 0 else "after"
        peak[key] = max(peak[key], 1 + len(running))  # + B's held container
        scenario.window_name = f"qa-s{scenario.index}"
        scenario.pane_id = f"%{scenario.index}"
        scenario.session_id = f"sid-{scenario.index}"
        scenario.transcript_path = str(tmp_path / f"s{scenario.index}.jsonl")

    for sc in state.scenarios[:4]:
        launch(sc)  # s1-s4 + B = 5 = L when the outage starts

    def release(st, session, *, scenarios=None, kept_indices=None):
        if outage["polls_left"] > 0:
            return True  # deferred: the inventory is unreadable
        for sc in scenarios:
            running.discard(sc.index)
        return False

    ticks = 0

    def tick(_seconds):
        nonlocal ticks
        ticks += 1
        outage["polls_left"] -= 1
        if ticks >= 14:
            state.stop_requested = True

    def inventory():
        if outage["polls_left"] > 0:
            return None
        return _running(B_IMPL, *(f"pm-t-qa-pr-aaaa-L-s{i}" for i in sorted(running)))

    monkeypatch.setattr(container_mod, "max_running_containers", lambda: 5)
    monkeypatch.setattr(container_mod, "running_container_count",
                        lambda: None if (inv := inventory()) is None else len(inv))
    monkeypatch.setattr(container_reaper, "list_containers", inventory)
    monkeypatch.setattr(qa_loop, "_is_verification_enabled", lambda: False)
    monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
    monkeypatch.setattr(qa_loop, "_POLL_INTERVAL", 0)
    monkeypatch.setattr(qa_loop.time, "sleep", tick)
    monkeypatch.setattr(qa_loop, "_write_resume_file", MagicMock())
    monkeypatch.setattr(qa_loop, "_write_status_file", MagicMock())
    monkeypatch.setattr(qa_loop, "_release_scenario_containers", release)
    monkeypatch.setattr(qa_loop, "_launch_scenarios_in_containers",
                        lambda st, *a, **k: launch(st.scenarios[0]))
    monkeypatch.setattr(tmux, "pane_exists", lambda p: True)
    monkeypatch.setattr(hook_events, "read_event",
                        lambda sid: {"event_type": "idle_prompt", "timestamp": 1})
    monkeypatch.setattr(qa_loop, "extract_verdict_from_transcript",
                        lambda path, *a: "PASS")
    monkeypatch.setattr(qa_loop, "extract_verdict_reason_from_transcript",
                        lambda *a: None)

    qa_loop._poll_tmux_verdicts(
        state, {}, {}, "pm-t", str(tmp_path), tmp_path / "status.json",
        lambda: None, queued_scenarios=state.scenarios[4:],
        concurrency_cap=4, desired_cap=4, use_containers=True)

    assert peak["outage"] == 6, peak       # one floor launch: L+1, never L+2
    assert peak["after"] <= 5, peak
    assert launched == list(range(1, 9)), "the queue drains after recovery"
    assert not running, "every deferred release completed after recovery"


def test_outage_counts_containers_kept_for_a_human_as_held(
        tmp_path, monkeypatch):
    """An outage admits one floor launch; a settled worker kept for a human
    (INPUT_REQUIRED) keeps running, so it must hold the queue like a deferred
    release. Before the fix the kept worker counted as released: every
    INPUT_REQUIRED settlement admitted another blind launch (L+2, L+3...)."""
    from pm_core import container as container_mod
    state = qa_loop.QALoopState(pr_id="pr-aaaa")
    state.scenarios = [
        qa_loop.QAScenario(index=i, title=f"s{i}", focus="",
                           container_name=f"pm-t-qa-pr-aaaa-L-s{i}")
        for i in range(1, 5)
    ]
    launched = []

    def launch(scenario):
        launched.append(scenario.index)
        scenario.window_name = f"qa-s{scenario.index}"
        scenario.pane_id = f"%{scenario.index}"
        scenario.session_id = f"sid-{scenario.index}"
        scenario.transcript_path = str(tmp_path / f"s{scenario.index}.jsonl")

    launch(state.scenarios[0])  # s1 + others fill container-max-running

    def release(st, session, *, scenarios=None, kept_indices=None):
        for sc in scenarios:  # every settled worker awaits a human: kept
            kept_indices.add(sc.index)
        return False

    ticks = 0

    def tick(_seconds):
        nonlocal ticks
        ticks += 1
        if ticks >= 12:
            state.stop_requested = True

    monkeypatch.setattr(container_mod, "max_running_containers", lambda: 5)
    monkeypatch.setattr(container_mod, "running_container_count", lambda: None)
    monkeypatch.setattr(container_reaper, "list_containers", lambda: None)
    monkeypatch.setattr(qa_loop, "_is_verification_enabled", lambda: False)
    monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
    monkeypatch.setattr(qa_loop, "_POLL_INTERVAL", 0)
    monkeypatch.setattr(qa_loop.time, "sleep", tick)
    monkeypatch.setattr(qa_loop, "_write_resume_file", MagicMock())
    monkeypatch.setattr(qa_loop, "_write_status_file", MagicMock())
    monkeypatch.setattr(qa_loop, "_release_scenario_containers", release)
    monkeypatch.setattr(qa_loop, "_launch_scenarios_in_containers",
                        lambda st, *a, **k: launch(st.scenarios[0]))
    monkeypatch.setattr(tmux, "pane_exists", lambda p: True)
    monkeypatch.setattr(hook_events, "read_event",
                        lambda sid: {"event_type": "idle_prompt", "timestamp": 1})
    monkeypatch.setattr(qa_loop, "extract_verdict_from_transcript",
                        lambda path, *a: "INPUT_REQUIRED")
    monkeypatch.setattr(qa_loop, "extract_verdict_reason_from_transcript",
                        lambda *a: None)

    qa_loop._poll_tmux_verdicts(
        state, {}, {}, "pm-t", str(tmp_path), tmp_path / "status.json",
        lambda: None, queued_scenarios=state.scenarios[1:],
        concurrency_cap=1, desired_cap=4, use_containers=True)

    assert launched == [1, 2], "one floor launch, then wait for the inventory"


def _running(*names):
    return [container_reaper.ContainerInfo(name=n, id=f"id-{n}", running=True)
            for n in names]


A_WORKERS = [f"pm-a-qa-pr-aaaa-L-s{i}" for i in range(17, 21)]
B_IMPL = "pm-a-impl-pr-bbbb"
C1, C2 = "pm-c-qa-pr-cccc-L-s1", "pm-c-qa-pr-cccc-L-s2"


def test_a_retained_container_consumes_launch_capacity(monkeypatch):
    """QA S51: A's 4 workers + B + C s1 (INPUT_REQUIRED, kept for a human)
    filled container-max-running=5 and C still launched s2 as its
    at-least-one floor, peaking at 7 = L+2. A retained container is not
    permission to launch past the limit: C's s2 waits for room."""
    from pm_core import container as container_mod
    monkeypatch.setattr(container_mod, "max_running_containers", lambda: 5)
    inventory = _running(*A_WORKERS, B_IMPL, C1)
    monkeypatch.setattr(container_reaper, "list_containers", lambda: inventory)

    batch, held = qa_loop._container_launch_room(1, desired=4, active=0, own={C1})
    assert held == 1
    assert 0 + held >= batch, "C must not launch s2 into a full runtime"

    # Once A's workers are gone there is room again, and C launches.
    inventory = _running(B_IMPL, C1)
    batch, held = qa_loop._container_launch_room(1, desired=4, active=0, own={C1})
    assert (batch, held) == (4, 1) and 0 + held < batch


def test_a_run_holding_nothing_keeps_its_floor_launch(monkeypatch):
    """The floor still admits one launch into a full runtime (L+1) for a run
    with no container of its own, so a fresh run is never starved."""
    from pm_core import container as container_mod
    monkeypatch.setattr(container_mod, "max_running_containers", lambda: 5)
    monkeypatch.setattr(container_reaper, "list_containers",
                        lambda: _running(*A_WORKERS, B_IMPL))
    monkeypatch.setattr(container_mod, "running_container_count", lambda: 5)
    assert qa_loop._container_launch_room(1, desired=4, active=0) == (1, 0)
    # A settled scenario whose container is already released holds nothing.
    assert qa_loop._container_launch_room(
        1, desired=4, active=0, own={C1}) == (1, 0)


def test_poll_defers_a_queued_launch_behind_a_retained_container(
        tmp_path, monkeypatch):
    """QA S51 end to end in the verdict poll: C s1 settles INPUT_REQUIRED and
    keeps its container; with the runtime full, s2 stays queued (no launch),
    and it launches once another process's workers free room."""
    from pm_core import container as container_mod
    state = qa_loop.QALoopState(pr_id="pr-cccc")
    state.scenarios = [
        qa_loop.QAScenario(index=i, title=f"s{i}", focus="",
                           container_name=f"pm-c-qa-pr-cccc-L-s{i}")
        for i in (1, 2)
    ]
    others = list(A_WORKERS) + [B_IMPL]
    running = []          # this run's containers still running
    launched = []
    polls = {"n": 0, "peak": 0}

    def launch(scenario):
        launched.append(scenario.index)
        running.append(scenario.container_name)
        scenario.window_name = f"qa-s{scenario.index}"
        scenario.pane_id = f"%{scenario.index}"
        scenario.session_id = f"sid-{scenario.index}"
        scenario.transcript_path = str(tmp_path / f"s{scenario.index}.jsonl")

    launch(state.scenarios[0])

    def tick(_seconds):
        polls["n"] += 1
        polls["peak"] = max(polls["peak"], len(others) + len(running))
        if polls["n"] == 4:
            del others[:4]  # A's workers finish and are released
        if polls["n"] >= 8:
            state.stop_requested = True

    def release(st, session, *, scenarios=None, kept_indices=None):
        return False  # INPUT_REQUIRED is kept for a human: nothing removed

    monkeypatch.setattr(container_mod, "max_running_containers", lambda: 5)
    monkeypatch.setattr(container_mod, "running_container_count",
                        lambda: len(others) + len(running))
    monkeypatch.setattr(container_reaper, "list_containers",
                        lambda: _running(*others, *running))
    monkeypatch.setattr(qa_loop, "_is_verification_enabled", lambda: False)
    monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
    monkeypatch.setattr(qa_loop, "_POLL_INTERVAL", 0)
    monkeypatch.setattr(qa_loop.time, "sleep", tick)
    monkeypatch.setattr(qa_loop, "_write_resume_file", MagicMock())
    monkeypatch.setattr(qa_loop, "_write_status_file", MagicMock())
    monkeypatch.setattr(qa_loop, "_release_scenario_containers", release)
    monkeypatch.setattr(qa_loop, "_launch_scenarios_in_containers",
                        lambda st, *a, **k: launch(st.scenarios[0]))
    monkeypatch.setattr(tmux, "pane_exists", lambda p: True)
    monkeypatch.setattr(hook_events, "read_event",
                        lambda sid: {"event_type": "idle_prompt", "timestamp": 1})
    monkeypatch.setattr(
        qa_loop, "extract_verdict_from_transcript",
        lambda path, *a: "INPUT_REQUIRED" if Path(path).stem == "s1" else None)
    monkeypatch.setattr(qa_loop, "extract_verdict_reason_from_transcript",
                        lambda *a: None)

    qa_loop._poll_tmux_verdicts(
        state, {}, {}, "pm-c", str(tmp_path), tmp_path / "status.json",
        lambda: None, queued_scenarios=state.scenarios[1:],
        concurrency_cap=1, desired_cap=4, use_containers=True)

    assert state.scenario_verdicts.get(1) == "INPUT_REQUIRED"
    assert launched == [1, 2], "s2 launches once room is free"
    assert C1 in running, "the retained container is preserved"
    # s1's floor launch into the full runtime is L+1 = 6; s2 never ran
    # alongside A4 + B + the retained s1 (the observed L+2 = 7).
    assert polls["peak"] == 6, polls


def test_queued_scenarios_stay_queued_on_the_dashboard_during_launches(
        tmp_path, monkeypatch):
    """Launch-time status writes keep the not-yet-launched queue visible.

    The launchers rewrite the dashboard while workers prepare. Without the
    run's queued set those writes dropped the "queued" label (and the initial
    batch's write dropped the queued scenarios entirely) until a verdict
    happened to rewrite the status.
    """
    state = qa_loop.QALoopState(pr_id="pr-aaaa")
    state.scenarios = [
        qa_loop.QAScenario(index=i, title=f"s{i}", focus="",
                           container_name=f"pm-t-qa-pr-aaaa-L-s{i}")
        for i in range(1, 5)
    ]
    seen = []

    def launch(st, *a, _status_scenarios=None, _queued_indices=None, **k):
        seen.append(([s.index for s in _status_scenarios], set(_queued_indices)))
        sc = st.scenarios[0]
        sc.window_name = f"qa-s{sc.index}"
        sc.pane_id = f"%{sc.index}"
        sc.session_id = f"sid-{sc.index}"
        sc.transcript_path = str(tmp_path / f"s{sc.index}.jsonl")
        state.scenario_verdicts[sc.index] = "PASS"

    from pm_core import container as container_mod
    monkeypatch.setattr(container_mod, "max_running_containers", lambda: 0)
    monkeypatch.setattr(qa_loop, "_is_verification_enabled", lambda: False)
    monkeypatch.setattr(qa_loop, "_VERDICT_GRACE_PERIOD", 0)
    monkeypatch.setattr(qa_loop.time, "sleep", lambda s: None)
    monkeypatch.setattr(qa_loop, "_write_resume_file", MagicMock())
    monkeypatch.setattr(qa_loop, "_write_status_file", MagicMock())
    monkeypatch.setattr(qa_loop, "_release_scenario_containers",
                        lambda st, session, *, scenarios=None, kept_indices=None: False)
    monkeypatch.setattr(qa_loop, "_launch_scenarios_in_containers", launch)
    monkeypatch.setattr(tmux, "pane_exists", lambda p: True)
    monkeypatch.setattr(hook_events, "read_event",
                        lambda sid: {"event_type": "idle_prompt", "timestamp": 1})
    monkeypatch.setattr(qa_loop, "extract_verdict_from_transcript", lambda *a: "PASS")
    monkeypatch.setattr(qa_loop, "extract_verdict_reason_from_transcript",
                        lambda *a: None)

    state.scenarios[0].window_name = "qa-s1"
    state.scenarios[0].pane_id = "%1"
    state.scenarios[0].session_id = "sid-1"
    state.scenarios[0].transcript_path = str(tmp_path / "s1.jsonl")
    qa_loop._poll_tmux_verdicts(
        state, {}, {}, "pm-t", str(tmp_path), tmp_path / "status.json",
        lambda: None, queued_scenarios=state.scenarios[1:],
        concurrency_cap=1, use_containers=True)

    assert seen == [([1, 2, 3, 4], {3, 4}), ([1, 2, 3, 4], {4}),
                    ([1, 2, 3, 4], set())]
