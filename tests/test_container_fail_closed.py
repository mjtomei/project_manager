"""Fail-closed container-mode launches (pr-574e851).

Container mode is an execution boundary: when it is enabled for a
container-eligible launch, an unusable runtime or a container that cannot be
created/lost must stop that launch with an infrastructure error.  It must
never silently run the agent on the host and never be turned into an invented
scenario verdict.

These tests assert the *absence of host execution*, not just an error string.
The core regression test is written against APIs that exist on the pre-fix
base too (``_runtime_available``), so it fails there for the same reason: the
pre-fix preflight downgrades to ``_launch_scenarios_in_tmux``.
"""

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

import pm_core.container as container_mod
import pm_core.qa_loop as qa_loop
from pm_core.qa_loop import QALoopState, QAScenario, run_qa_sync


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated HOME (pm settings + workdirs) and Claude config dir."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    cfg_dir = tmp_path / "claude-cfg"
    cfg_dir.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg_dir))
    return h


def _patch_runtime(stack: ExitStack, available: bool):
    """Force the runtime probe down/up on pre- or post-fix code."""
    if hasattr(container_mod, "_runtime_status"):
        return stack.enter_context(patch.object(
            container_mod, "_runtime_status",
            return_value=(available,
                          "" if available else "runtime unavailable")))
    return stack.enter_context(patch.object(
        container_mod, "_runtime_available", return_value=available))


def _pm_fixture(tmp_path: Path):
    workdir = tmp_path / "wd"
    workdir.mkdir()
    pr = {"id": "pr-c", "title": "T", "branch": "", "status": "qa",
          "workdir": str(workdir)}
    data = {"project": {"name": "t", "base_branch": "master",
                        "backend": "local"},
            "prs": [pr], "plans": []}
    qa_workdir = tmp_path / "qa"
    qa_workdir.mkdir()
    return pr, data, workdir, qa_workdir


def _execution_only_state(qa_workdir: Path) -> QALoopState:
    state = QALoopState(pr_id="pr-c", planning_phase=False)
    state.qa_workdir = str(qa_workdir)
    state.scenarios = [QAScenario(index=1, title="S1", focus="f")]
    return state


def _run_execution_only(tmp_path, *, container_enabled: bool,
                        runtime_available: bool):
    """Drive run_qa_sync's execution-only path with launch spies."""
    pr, data, workdir, qa_workdir = _pm_fixture(tmp_path)
    state = _execution_only_state(qa_workdir)
    host_launch = MagicMock()
    container_launch = MagicMock()
    scenario0 = MagicMock()
    finalize = MagicMock(return_value=state)
    with ExitStack() as stack:
        stack.enter_context(patch("pm_core.qa_loop.get_pm_session",
                                  return_value="pm-s"))
        stack.enter_context(patch("pm_core.store.load", return_value=data))
        stack.enter_context(patch("pm_core.store.get_pr", return_value=pr))
        stack.enter_context(patch("pm_core.qa_loop._resolve_qa_model",
                                  return_value=SimpleNamespace(
                                      model=None, provider=None, effort=None)))
        stack.enter_context(patch("pm_core.qa_loop._get_qa_spec",
                                  return_value={"ok": True}))
        stack.enter_context(patch("pm_core.qa_loop._ensure_qa_main_pane",
                                  return_value=None))
        stack.enter_context(patch("pm_core.qa_loop._add_status_pane"))
        stack.enter_context(patch.object(container_mod,
                                         "is_container_mode_enabled",
                                         return_value=container_enabled))
        _patch_runtime(stack, runtime_available)
        stack.enter_context(patch("pm_core.qa_loop._launch_scenarios_in_tmux",
                                  host_launch))
        stack.enter_context(patch(
            "pm_core.qa_loop._launch_scenarios_in_containers",
            container_launch))
        stack.enter_context(patch("pm_core.qa_loop._launch_scenario_0",
                                  scenario0))
        stack.enter_context(patch("pm_core.qa_loop._execute_and_finalize",
                                  finalize))
        run_qa_sync(state, tmp_path / "pm", pr, lambda *a: None,
                    max_scenarios=1)
    return state, host_launch, container_launch, scenario0, finalize


def test_run_qa_sync_fails_closed_when_runtime_unavailable(tmp_path, home):
    """Pre-fix: the preflight flips use_containers=False and launches the
    refiner/worker via _launch_scenarios_in_tmux (host).  Post-fix: it aborts
    with ERROR before any launch."""
    state, host_launch, container_launch, scenario0, finalize = (
        _run_execution_only(tmp_path, container_enabled=True,
                            runtime_available=False))

    # The boundary: zero host (and container) agent launches.  Asserted
    # first so a pre-fix run fails on the host launch, not on a side effect.
    host_launch.assert_not_called()
    container_launch.assert_not_called()
    scenario0.assert_not_called()
    finalize.assert_not_called()
    assert state.running is False
    assert state.latest_verdict == "ERROR"
    assert "container" in state.latest_output.lower()
    assert "no agent was launched on the host" in state._error


def test_run_qa_sync_uses_containers_when_runtime_healthy(tmp_path, home):
    state, host_launch, container_launch, scenario0, finalize = (
        _run_execution_only(tmp_path, container_enabled=True,
                            runtime_available=True))

    container_launch.assert_called_once()
    host_launch.assert_not_called()
    finalize.assert_called_once()
    assert state.latest_verdict != "ERROR"


def test_run_qa_sync_host_execution_when_container_disabled(tmp_path, home):
    """Explicitly disabled container mode still supports host execution."""
    state, host_launch, container_launch, scenario0, finalize = (
        _run_execution_only(tmp_path, container_enabled=False,
                            runtime_available=False))

    host_launch.assert_called_once()
    container_launch.assert_not_called()
    finalize.assert_called_once()
    assert state.latest_verdict != "ERROR"


def test_container_create_failure_raises_instead_of_host_launch(tmp_path, home):
    """A create/setup failure is an infrastructure error, not a scenario
    verdict, and must not produce a host launch."""
    state = QALoopState(pr_id="pr-c", planning_phase=False)
    state.qa_workdir = str(tmp_path)
    state.scenarios = [QAScenario(index=1, title="S1", focus="f")]
    clone = tmp_path / "clone"
    clone.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    with ExitStack() as stack:
        stack.enter_context(patch("pm_core.qa_loop._resolve_qa_model",
                                  return_value=SimpleNamespace(
                                      model=None, provider=None, effort=None)))
        stack.enter_context(patch(
            "pm_core.qa_loop.create_scenario_workdir",
            return_value=(clone, scratch)))
        stack.enter_context(patch.object(
            container_mod, "create_qa_container",
            side_effect=container_mod.ContainerError("image not found")))
        stack.enter_context(patch.object(container_mod, "remove_container"))
        new_window = stack.enter_context(patch(
            "pm_core.tmux.new_window_get_pane", return_value="%1"))
        stack.enter_context(patch("pm_core.qa_loop._write_status_file"))

        with pytest.raises(Exception) as excinfo:
            qa_loop._launch_scenarios_in_containers(
                state, {}, {"id": "pr-c", "branch": "pm/c"}, "pm-s",
                None, str(tmp_path))

    assert "image not found" in str(excinfo.value)
    assert "host" in str(excinfo.value).lower()
    # No concretizer/worker window was created.
    new_window.assert_not_called()
    # No invented scenario verdict.
    assert state.scenario_verdicts == {}


def test_execute_and_finalize_publishes_error_on_container_launch_failure(
        tmp_path, home):
    state = QALoopState(pr_id="pr-c", planning_phase=False)
    state.qa_workdir = str(tmp_path)
    state.scenarios = [QAScenario(index=1, title="S1", focus="f")]

    from pm_core.qa_loop import ContainerLaunchError
    with ExitStack() as stack:
        stack.enter_context(patch(
            "pm_core.qa_loop._write_resume_file"))
        stack.enter_context(patch("pm_core.qa_loop._write_status_file"))
        stack.enter_context(patch(
            "pm_core.qa_loop._persist_scenario_verdicts"))
        finalize = stack.enter_context(patch(
            "pm_core.qa_loop._run_qa_finalize_pane"))
        stack.enter_context(patch(
            "pm_core.qa_loop._poll_tmux_verdicts",
            side_effect=ContainerLaunchError(
                "container 'pm-x' is no longer running; refusing to "
                "relaunch the worker on the host")))

        result = qa_loop._execute_and_finalize(
            state, tmp_path, {"id": "pr-c", "branch": "b"}, {}, "pm-s",
            "qa-pr-c", str(tmp_path), tmp_path / "qa_status.json", None,
            use_containers=True, concurrency_cap=0, queued_scenarios=[],
            notify=lambda: None)

    assert result is state
    assert state.running is False
    assert state.latest_verdict == "ERROR"
    assert state.latest_verdict != "INPUT_REQUIRED"
    assert "no longer running" in state._error
    finalize.assert_not_called()


def test_relaunch_refuses_host_when_container_run_has_no_container(
        tmp_path, home):
    state = QALoopState(pr_id="pr-c")
    state.qa_workdir = str(tmp_path)
    scenario = QAScenario(index=1, title="S1", focus="f",
                          container_name=None, worktree_path=str(tmp_path))

    from pm_core.qa_loop import ContainerLaunchError
    with ExitStack() as stack:
        stack.enter_context(patch("pm_core.qa_loop._resolve_qa_model",
                                  return_value=SimpleNamespace(
                                      model=None, provider=None, effort=None)))
        new_window = stack.enter_context(patch(
            "pm_core.tmux.new_window_get_pane", return_value="%1"))
        with pytest.raises(ContainerLaunchError):
            qa_loop._relaunch_scenario_window(
                scenario, state, {}, {"id": "pr-c", "branch": "b"},
                "pm-s", str(tmp_path), use_containers=True)

    new_window.assert_not_called()


def test_relaunch_refuses_when_container_lost(tmp_path, home):
    state = QALoopState(pr_id="pr-c")
    state.qa_workdir = str(tmp_path)
    scenario = QAScenario(index=1, title="S1", focus="f",
                          container_name="pm-x", worktree_path=str(tmp_path))

    from pm_core.qa_loop import ContainerLaunchError
    with ExitStack() as stack:
        stack.enter_context(patch("pm_core.qa_loop._resolve_qa_model",
                                  return_value=SimpleNamespace(
                                      model=None, provider=None, effort=None)))
        stack.enter_context(patch.object(container_mod,
                                         "container_is_running",
                                         return_value=False))
        new_window = stack.enter_context(patch(
            "pm_core.tmux.new_window_get_pane", return_value="%1"))
        with pytest.raises(ContainerLaunchError):
            qa_loop._relaunch_scenario_window(
                scenario, state, {}, {"id": "pr-c", "branch": "b"},
                "pm-s", str(tmp_path), use_containers=True)

    new_window.assert_not_called()


def test_resume_fails_closed_when_runtime_unavailable(tmp_path, home):
    pr, data, workdir, qa_workdir = _pm_fixture(tmp_path)
    state = _execution_only_state(qa_workdir)
    state.session_tag = "s"
    qa_loop._write_resume_file(state, True, 0, set())

    finalize = MagicMock(return_value=state)
    with ExitStack() as stack:
        stack.enter_context(patch("pm_core.qa_loop.get_pm_session",
                                  return_value="pm-s"))
        stack.enter_context(patch("pm_core.store.load", return_value=data))
        stack.enter_context(patch("pm_core.store.get_pr", return_value=pr))
        _patch_runtime(stack, False)
        stack.enter_context(patch("pm_core.qa_loop._execute_and_finalize",
                                  finalize))
        result = qa_loop.resume_qa_sync(state, tmp_path / "pm", pr,
                                        lambda *a: None)

    assert result is state
    assert state.running is False
    assert state.latest_verdict == "ERROR"
    assert "no agent was launched on the host" in state._error
    finalize.assert_not_called()


def test_qa_debug_fails_closed_when_runtime_unavailable(tmp_path, home):
    from pm_core.cli.qa import qa as qa_group

    root = tmp_path / "pm"
    root.mkdir()
    instr = tmp_path / "repro.md"
    instr.write_text("# repro\n")
    item = {"path": str(instr), "title": "Repro", "description": "d"}
    data = {"project": {"name": "t"}, "prs": [], "plans": []}

    create_workdir = MagicMock()
    build_cmd = MagicMock(return_value="claude ...")
    with ExitStack() as stack:
        stack.enter_context(patch("pm_core.cli.qa.state_root",
                                  return_value=root))
        stack.enter_context(patch("pm_core.qa_instructions.get_instruction",
                                  return_value=item))
        stack.enter_context(patch("pm_core.store.load", return_value=data))
        stack.enter_context(patch("pm_core.loop_shared.get_pm_session",
                                  return_value="pm-s"))
        stack.enter_context(patch.object(container_mod,
                                         "is_container_mode_enabled",
                                         return_value=True))
        _patch_runtime(stack, False)
        stack.enter_context(patch(
            "pm_core.qa_loop.create_scenario_workdir", create_workdir))
        stack.enter_context(patch(
            "pm_core.claude_launcher.build_claude_shell_cmd", build_cmd))
        result = CliRunner().invoke(qa_group, ["debug", "repro"])

    assert result.exit_code != 0
    assert "container runtime" in result.output.lower()
    create_workdir.assert_not_called()
    build_cmd.assert_not_called()


def test_runtime_status_reports_the_cause():
    """The diagnostic names the original cause for each failure shape."""
    import subprocess

    with patch.object(container_mod, "_get_runtime", return_value="podman"):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            ok, problem = container_mod._runtime_status()
        assert ok is False and "not found" in problem

        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired("podman info", 10)):
            ok, problem = container_mod._runtime_status()
        assert ok is False and "timed out" in problem

        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=1,
                                         stderr="daemon not running",
                                         stdout="")
            ok, problem = container_mod._runtime_status()
        assert ok is False
        assert "exited 1" in problem and "daemon not running" in problem

        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            ok, problem = container_mod._runtime_status()
        assert ok is True and problem == ""
