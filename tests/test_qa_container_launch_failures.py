"""QA window failures are launch errors, not agent verdicts or successful retries."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pm_core import container, qa_loop, tmux


@pytest.fixture
def scenario_state(tmp_path, monkeypatch):
    clone = tmp_path / "s1" / "clone"
    clone.mkdir(parents=True)
    state = qa_loop.QALoopState(pr_id="pr-aaaa")
    state.loop_id, state.session_tag = "L", "t"
    state.qa_workdir = str(tmp_path)
    scenario = qa_loop.QAScenario(
        index=1, title="s1", focus="", worktree_path=str(clone),
        container_name="pm-t-qa-pr-aaaa-L-s1", window_name="qa-pr-aaaa-s1")
    state.scenarios = [scenario]
    monkeypatch.setattr(container, "is_container_mode_enabled", lambda: True)
    monkeypatch.setattr(container, "_runtime_available", lambda: True)
    monkeypatch.setattr(container, "load_container_config", MagicMock())
    def create(**kwargs):
        if kwargs.get("allocation_identity") is not None:
            kwargs["allocation_identity"].update(id="cid", generation="captured-generation")
        return "cid"
    monkeypatch.setattr(container, "create_qa_container", create)
    monkeypatch.setattr(qa_loop, "_resolve_qa_model", MagicMock())
    monkeypatch.setattr(qa_loop, "_build_scenario_run_cmd",
                        lambda *a, **k: ("worker", str(clone)))
    return state, scenario


@pytest.mark.parametrize("failure", [None, "exception"])
def test_relaunch_window_failure_is_not_success(scenario_state, monkeypatch, failure):
    state, scenario = scenario_state
    new_window = MagicMock(return_value=None)
    if failure:
        new_window.side_effect = subprocess.CalledProcessError(
            1, "tmux new-window", stderr="can't find session: test")
    monkeypatch.setattr(tmux, "new_window_get_pane", new_window)
    discard = MagicMock()
    monkeypatch.setattr(container, "discard_unowned_container", discard)

    assert not qa_loop._relaunch_scenario_window(
        scenario, state, {}, {"id": state.pr_id}, "pm-t", scenario.worktree_path)
    assert qa_loop._is_launch_failure(state, 1)
    assert not state.scenario_verdicts
    assert scenario.pane_id is None
    discard.assert_called_once_with(scenario.container_name, container_id="cid",
                                    generation=scenario.container_generation)
    if failure:
        assert "can't find session: test" in state.scenario_verdict_reasons[1]
    release = MagicMock()
    monkeypatch.setattr(qa_loop, "_viewed_window_ids", lambda *a: set())
    from pm_core import container_reaper
    monkeypatch.setattr(container_reaper, "release_containers", release)
    qa_loop._release_scenario_containers(state, "pm-t")
    release.assert_not_called()  # unknown/live owners remain protected at run end
    assert discard.call_count == 2


def test_successful_retry_clears_launch_failure(scenario_state, monkeypatch):
    state, scenario = scenario_state
    qa_loop._record_launch_failure(state, scenario, "old tmux failure")
    monkeypatch.setattr(tmux, "new_window_get_pane", lambda *a, **k: "%7")
    monkeypatch.setattr(tmux, "pane_window_id", lambda *a: None)
    discard = MagicMock()
    monkeypatch.setattr(container, "discard_unowned_container", discard)

    assert qa_loop._relaunch_scenario_window(
        scenario, state, {}, {"id": state.pr_id}, "pm-t", scenario.worktree_path)
    assert scenario.pane_id == "%7"
    assert not qa_loop._is_launch_failure(state, 1)
    discard.assert_not_called()


@pytest.mark.parametrize("failure", [None, "exception", "build"])
@pytest.mark.parametrize("containers", [True, False])
def test_concretizer_launch_failure_keeps_real_error(scenario_state, monkeypatch, failure, containers):
    state, scenario = scenario_state
    scenario.window_name = None
    clone = Path(scenario.worktree_path)
    monkeypatch.setattr(qa_loop, "create_scenario_workdir",
                        lambda *a, **k: (clone, clone.parent / "scratch"))
    command = MagicMock(return_value="concretizer")
    window = MagicMock(return_value=None)
    if failure == "build":
        command.side_effect = RuntimeError("command build failed")
    elif failure == "exception":
        window.side_effect = subprocess.CalledProcessError(
            1, "tmux new-window", stderr=b"can't find session: pm-t")
    monkeypatch.setattr(qa_loop, "_build_concretize_cmd", command)
    monkeypatch.setattr(tmux, "new_window_get_pane", window)
    discard = MagicMock()
    monkeypatch.setattr(container, "discard_unowned_container", discard)
    launch = (qa_loop._launch_scenarios_in_containers if containers
              else qa_loop._launch_scenarios_in_tmux)
    launch(state, {}, {"id": state.pr_id}, "pm-t", None, str(clone))

    assert qa_loop._is_launch_failure(state, 1)
    assert not state.scenario_verdicts
    assert scenario.window_name is None
    if failure == "build":
        assert "command build failed" in state.scenario_verdict_reasons[1]
    elif failure == "exception":
        assert "can't find session: pm-t" in state.scenario_verdict_reasons[1]
    if containers:
        discard.assert_called_once_with(
            scenario.container_name, container_id="cid", generation="captured-generation")
    else:
        discard.assert_not_called()


@pytest.mark.parametrize("viewed", [{"@5"}, {"@other"}, set()])
def test_pre_worker_status_failure_preserves_viewed_concretizer(
        scenario_state, monkeypatch, viewed):
    from pm_core import container_reaper

    state, scenario = scenario_state
    clone = Path(scenario.worktree_path)
    monkeypatch.setattr(qa_loop, "create_scenario_workdir",
                        lambda *a, **k: (clone, clone.parent / "scratch"))
    monkeypatch.setattr(qa_loop, "_build_concretize_cmd", lambda *a, **k: "concretizer")
    monkeypatch.setattr(tmux, "new_window_get_pane", lambda *a, **k: "%5")
    monkeypatch.setattr(qa_loop, "_write_status_file",
                        MagicMock(side_effect=OSError("status disk full")))
    monkeypatch.setattr(qa_loop, "_viewed_window_ids", lambda *a: viewed)
    monkeypatch.setattr(tmux, "pane_window_id", lambda *a: "@5")
    release = MagicMock(return_value=container_reaper.Outcome())
    monkeypatch.setattr(container_reaper, "release_containers", release)

    with pytest.raises(OSError, match="status disk full"):
        qa_loop._launch_scenarios_in_containers(
            state, {}, {"id": state.pr_id}, "pm-t", None, str(clone))
    qa_loop._release_scenario_containers(state, "pm-t")
    if "@5" in viewed:
        release.assert_not_called()
    else:
        release.assert_called_once()
    assert scenario.pane_id == "%5"


@pytest.mark.parametrize("failure", [None, "exception", "build", "poll"])
@pytest.mark.parametrize("viewed", [set(), {"@5"}, None])
@pytest.mark.parametrize("containers", [True, False])
def test_worker_split_failure_keeps_real_launch_error(scenario_state, monkeypatch, failure, viewed, containers):
    state, scenario = scenario_state
    scenario.window_name = None
    clone = Path(scenario.worktree_path)
    monkeypatch.setattr(qa_loop, "create_scenario_workdir",
                        lambda *a, **k: (clone, clone.parent / "scratch"))
    monkeypatch.setattr(qa_loop, "_build_concretize_cmd", lambda *a, **k: "concretizer")
    monkeypatch.setattr(qa_loop, "_concretize_scenario", lambda *a, **k: (None, None))
    monkeypatch.setattr(qa_loop, "_write_status_file", MagicMock())
    monkeypatch.setattr(tmux, "new_window_get_pane", lambda *a, **k: "%5")
    split = MagicMock(return_value=None)
    if failure == "exception":
        split.side_effect = subprocess.CalledProcessError(
            1, "tmux split-window", stderr="can't find pane: %5")
    elif failure == "build":
        monkeypatch.setattr(qa_loop, "_build_scenario_run_cmd",
                            MagicMock(side_effect=RuntimeError("command build failed")))
    elif failure == "poll":
        monkeypatch.setattr(qa_loop, "_concretize_scenario",
                            MagicMock(side_effect=OSError("concretizer polling failed")))
    monkeypatch.setattr(tmux, "split_pane_at", split)
    release = MagicMock(return_value=False)
    monkeypatch.setattr(qa_loop, "_release_scenario_containers", release)
    discard = MagicMock()
    monkeypatch.setattr(container, "discard_unowned_container", discard)
    monkeypatch.setattr(qa_loop, "_viewed_window_ids", lambda *a: viewed)
    monkeypatch.setattr(tmux, "pane_window_id", lambda *a: "@5")

    launch = (qa_loop._launch_scenarios_in_containers if containers
              else qa_loop._launch_scenarios_in_tmux)
    launch(state, {}, {"id": state.pr_id}, "pm-t", None, str(clone))

    assert qa_loop._is_launch_failure(state, 1)
    assert not state.scenario_verdicts
    assert scenario.session_id is None
    assert scenario.window_name is None
    release.assert_not_called()
    if containers and viewed == set():
        discard.assert_called_once_with(
            scenario.container_name, container_id="cid", generation="captured-generation",
            allowed_owner_panes={"%5"})
    else:
        discard.assert_not_called()
    assert scenario.pane_id is None
    if failure == "exception":
        assert "can't find pane: %5" in state.scenario_verdict_reasons[1]
    elif failure == "build":
        assert "command build failed" in state.scenario_verdict_reasons[1]
    elif failure == "poll":
        assert "concretizer polling failed" in state.scenario_verdict_reasons[1]
        split.assert_not_called()
    monkeypatch.setattr(qa_loop, "_is_verification_enabled", lambda: False)
    qa_loop._poll_tmux_verdicts(
        state, {}, {"id": state.pr_id}, "pm-t", str(clone),
        Path(state.qa_workdir) / "status.json", lambda: None)
    assert not state.scenario_verdicts
