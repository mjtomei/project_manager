"""Cancellation during preparation must not launch or retain new QA workers."""

from unittest.mock import MagicMock

import pytest

from pm_core import container, container_reaper, qa_loop, tmux


@pytest.mark.parametrize("stage", ["clone", "create", "concretize", "reject"])
@pytest.mark.parametrize("containers", [True, False])
def test_cancelled_preparation_does_not_launch_or_record_verdict(tmp_path, monkeypatch, stage, containers):
    if stage == "create" and not containers:
        pytest.skip("host workers have no container allocation")
    state = qa_loop.QALoopState(pr_id="pr-aaaa", session_tag="t", loop_id="L")
    state.qa_workdir = str(tmp_path)
    scenario = qa_loop.QAScenario(index=1, title="s1", focus="")
    state.scenarios = [scenario]
    clone = tmp_path / "s1" / "clone"
    clone.mkdir(parents=True)

    def clone_workdir(*args, **kwargs):
        if stage == "clone":
            state.stop_requested = True
        return clone, clone.parent / "scratch"

    def create(**kwargs):
        kwargs["allocation_identity"].update(id="cid", generation="epoch")
        if stage == "create":
            state.stop_requested = True
        return "cid"

    def concretize(*args, **kwargs):
        state.stop_requested = True
        return None, "needs a human" if stage == "reject" else None

    monkeypatch.setattr(qa_loop, "create_scenario_workdir", clone_workdir)
    monkeypatch.setattr(qa_loop, "_resolve_qa_model", MagicMock())
    monkeypatch.setattr(container, "load_container_config", MagicMock())
    allocation = MagicMock(side_effect=create)
    monkeypatch.setattr(container, "create_qa_container", allocation)
    monkeypatch.setattr(qa_loop, "_build_concretize_cmd", lambda *a, **k: "concretizer")
    monkeypatch.setattr(qa_loop, "_concretize_scenario", concretize)
    monkeypatch.setattr(qa_loop, "_build_scenario_run_cmd", lambda *a, **k: ("worker", str(clone)))
    monkeypatch.setattr(qa_loop, "_write_status_file", MagicMock())
    window = MagicMock(return_value="%5")
    split = MagicMock(return_value="%6")
    monkeypatch.setattr(tmux, "new_window_get_pane", window)
    monkeypatch.setattr(tmux, "split_pane_at", split)
    monkeypatch.setattr(tmux, "pane_window_id", lambda *a: None)
    monkeypatch.setattr(qa_loop, "_viewed_window_ids", lambda *a: set())
    release = MagicMock(return_value=container_reaper.Outcome())
    monkeypatch.setattr(container_reaper, "release_containers", release)

    launch = (qa_loop._launch_scenarios_in_containers if containers
              else qa_loop._launch_scenarios_in_tmux)
    launch(state, {}, {"id": state.pr_id}, "pm-t", None, str(clone))
    monkeypatch.setattr(qa_loop, "_is_verification_enabled", lambda: False)
    qa_loop._poll_tmux_verdicts(
        state, {}, {"id": state.pr_id}, "pm-t", str(clone),
        tmp_path / "status.json", lambda: None, use_containers=True)
    qa_loop._release_scenario_containers(state, "pm-t")

    split.assert_not_called()
    assert not state.scenario_verdicts
    if stage == "clone" or not containers:
        allocation.assert_not_called()
        release.assert_not_called()
    else:
        release.assert_called_once_with(
            [scenario.container_name], reason="qa-run-end", owner_release=True,
            expected_ids={scenario.container_name: "cid"},
            expected_generations={scenario.container_name: "epoch"})
    if stage in {"clone", "create"}:
        window.assert_not_called()


def test_concretizer_poll_observes_cancellation(monkeypatch, tmp_path):
    from pm_core import claude_launcher

    scenario = qa_loop.QAScenario(index=1, title="s1", focus="")
    stopped = False

    def poll(*args, **kwargs):
        nonlocal stopped
        stop_check = kwargs.get("stop_check")
        assert stop_check is not None
        assert not stop_check()
        stopped = True
        assert stop_check()
        return None

    monkeypatch.setattr(claude_launcher, "transcript_path_for", lambda *a: tmp_path / "log")
    monkeypatch.setattr(qa_loop, "poll_for_verdict", poll)
    assert qa_loop._concretize_scenario(
        scenario, {}, {}, "%5", "sid", str(tmp_path),
        stop_check=lambda: stopped) == (None, None)
