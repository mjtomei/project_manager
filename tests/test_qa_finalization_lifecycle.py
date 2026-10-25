"""Finalization preserves the actual queue and releases allocations on errors."""

from unittest.mock import MagicMock

import pytest

from pm_core import claude_launcher, container, prompt_gen, qa_loop


@pytest.fixture
def finalize_context(tmp_path, monkeypatch):
    state = qa_loop.QALoopState(pr_id="pr-aaaa")
    state.scenarios = [qa_loop.QAScenario(index=i, title=f"s{i}", focus="",
                                        container_name=f"pm-t-qa-pr-aaaa-L-s{i}")
                       for i in (1, 2)]
    state.qa_workdir = str(tmp_path)
    snapshots = []
    monkeypatch.setattr(qa_loop, "_write_resume_file",
                        lambda st, containers, cap, queued: snapshots.append(set(queued)))
    monkeypatch.setattr(qa_loop, "_write_status_file", MagicMock())
    monkeypatch.setattr(qa_loop, "_persist_scenario_verdicts", MagicMock())
    monkeypatch.setattr(qa_loop, "_run_qa_finalize_pane", MagicMock())
    release = MagicMock(return_value=False)
    monkeypatch.setattr(qa_loop, "_release_scenario_containers", release)

    def run():
        return qa_loop._execute_and_finalize(
            state, tmp_path, {"branch": "b"}, {}, "pm-t", "qa-w",
            str(tmp_path), tmp_path / "status.json", None,
            use_containers=True, concurrency_cap=1,
            queued_scenarios=[state.scenarios[1]], notify=lambda: None)

    return state, snapshots, release, run


@pytest.mark.parametrize("outcome", ["PASS", "launch-failure", "stopped"])
def test_final_snapshot_does_not_requeue_attempted_scenarios(
        finalize_context, monkeypatch, outcome):
    state, snapshots, release, run = finalize_context

    def poll(*args, **kwargs):
        state.scenario_verdicts[1] = "PASS"
        if outcome == "PASS":
            state.scenarios[1].window_name = "qa-s2"
            state.scenario_verdicts[2] = "PASS"
        elif outcome == "launch-failure":
            qa_loop._record_launch_failure(state, state.scenarios[1], "exec failed")
        else:
            state.stop_requested = True

    monkeypatch.setattr(qa_loop, "_poll_tmux_verdicts", poll)
    run()
    assert snapshots[0] == {2}
    assert snapshots[-1] == ({2} if outcome == "stopped" else set())
    release.assert_called_once_with(state, "pm-t")


@pytest.mark.parametrize("outcome", ["PASS", "launch-failure"])
def test_resume_ignores_stale_queue_entries(tmp_path, monkeypatch, outcome):
    state = qa_loop.QALoopState(pr_id="pr-aaaa")
    scenario = qa_loop.QAScenario(index=1, title="settled", focus="")
    state.scenarios = [scenario]
    if outcome == "PASS":
        state.scenario_verdicts[1] = "PASS"
    else:
        qa_loop._record_launch_failure(state, scenario, "exec failed")
    monkeypatch.setattr(qa_loop, "_is_verification_enabled", lambda: False)
    monkeypatch.setattr(qa_loop, "_write_status_file", MagicMock())
    launch = MagicMock(side_effect=AssertionError("settled work must not relaunch"))
    monkeypatch.setattr(qa_loop, "_launch_scenarios_in_containers", launch)
    qa_loop._poll_tmux_verdicts(
        state, {}, {}, "pm-t", str(tmp_path), tmp_path / "status.json",
        lambda: None, queued_scenarios=[scenario], concurrency_cap=1,
        use_containers=True)
    launch.assert_not_called()
    if outcome == "PASS":
        assert state.scenario_verdicts[1] == "PASS"


@pytest.mark.parametrize("role", ["concretizer", "worker"])
def test_qa_exec_uses_captured_allocation_identity(tmp_path, monkeypatch, role):
    scenario = qa_loop.QAScenario(
        index=1, title="test", focus="", container_name="pm-t-qa-pr-aaaa-L-s1",
        container_id="allocated-id", container_generation="allocated-generation",
        worktree_path=str(tmp_path))
    state = qa_loop.QALoopState(pr_id="pr-aaaa")
    resolution = MagicMock()
    monkeypatch.setattr(qa_loop, "_resolve_qa_model", lambda *a, **k: resolution)
    monkeypatch.setattr(qa_loop, "_build_concretization_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(prompt_gen, "generate_qa_child_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(qa_loop, "_write_scenario_capture_file", MagicMock())
    monkeypatch.setattr(claude_launcher, "build_claude_shell_cmd", lambda **k: "worker")
    build = MagicMock(return_value="exec")
    monkeypatch.setattr(container, "build_exec_cmd", build)
    if role == "concretizer":
        qa_loop._build_concretize_cmd(scenario, {}, {}, str(tmp_path),
                                      container_name=scenario.container_name)
    else:
        qa_loop._build_scenario_run_cmd(scenario, state, {}, "transcript", resolution,
                                        session=None, workdir_path=str(tmp_path))
    build.assert_called_once_with(scenario.container_name, "worker", cleanup=False,
                                  container_id="allocated-id",
                                  generation="allocated-generation")


@pytest.mark.parametrize("stage", ["poll", "status", "snapshot"])
def test_finalization_errors_still_release_allocations(finalize_context, monkeypatch, stage):
    state, snapshots, release, run = finalize_context
    monkeypatch.setattr(qa_loop, "_poll_tmux_verdicts", MagicMock())
    target = {"poll": "_poll_tmux_verdicts", "status": "_write_status_file",
              "snapshot": "_write_resume_file"}[stage]
    monkeypatch.setattr(qa_loop, target, MagicMock(side_effect=OSError("disk unavailable")))
    with pytest.raises(OSError, match="disk unavailable"):
        run()
    release.assert_called_once_with(state, "pm-t")


@pytest.mark.parametrize("stage", ["launch-status", "notify", "interrupt"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_initial_launch_errors_restore_scenarios_and_release(
        tmp_path, monkeypatch, stage, cleanup_fails):
    from pm_core import store, tmux

    state = qa_loop.QALoopState(pr_id="pr-aaaa", planning_phase=False)
    state.qa_workdir = str(tmp_path)
    scenarios = [qa_loop.QAScenario(index=i, title=f"s{i}", focus="") for i in (1, 2)]
    state.scenarios = scenarios
    pr = {"id": state.pr_id, "workdir": str(tmp_path)}
    monkeypatch.setattr(store, "load", lambda *a, **k: {"prs": [pr]})
    monkeypatch.setattr(qa_loop, "_resolve_qa_model", lambda *a, **k: MagicMock())
    monkeypatch.setattr(qa_loop, "_get_qa_spec", lambda *a: "qa.md")
    monkeypatch.setattr(qa_loop, "get_pm_session", lambda: "pm-t")
    monkeypatch.setattr(container, "is_container_mode_enabled", lambda: True)
    monkeypatch.setattr(container, "_runtime_available", lambda: True)
    monkeypatch.setattr(qa_loop, "_clamp_to_container_headroom", lambda cap: cap)
    monkeypatch.setattr(tmux, "find_window_by_name", lambda *a: {"index": 0})
    monkeypatch.setattr(tmux, "get_pane_indices", lambda *a: [])
    status = MagicMock(side_effect=[None, OSError("disk unavailable")])
    monkeypatch.setattr(qa_loop, "_write_status_file", status)
    error = KeyboardInterrupt("interrupted launch") if stage == "interrupt" else OSError("disk unavailable")

    def launch(*args, **kwargs):
        assert state.scenarios == [scenarios[0]]
        scenarios[0].container_name = "pm-t-qa-pr-aaaa-L-s1"
        scenarios[0].container_id = "allocated-id"
        scenarios[0].container_generation = "allocated-generation"
        if stage == "launch-status":
            # The real launcher writes status after preparation creates panes.
            qa_loop._write_status_file(tmp_path / "status.json")
        elif stage == "interrupt":
            raise error

    monkeypatch.setattr(qa_loop, "_launch_scenarios_in_containers", launch)
    released = []

    def release(st, session):
        released.append(list(st.scenarios))
        if cleanup_fails:
            raise RuntimeError("cleanup unavailable")
        return False

    monkeypatch.setattr(qa_loop, "_release_scenario_containers", release)
    finalize = MagicMock()
    monkeypatch.setattr(qa_loop, "_execute_and_finalize", finalize)

    def notify(st):
        if stage == "notify":
            raise error

    with pytest.raises(type(error), match=str(error)):
        qa_loop.run_qa_sync(state, tmp_path, pr, notify, max_scenarios=1)
    assert state.scenarios is scenarios
    assert released == [scenarios]
    finalize.assert_not_called()
