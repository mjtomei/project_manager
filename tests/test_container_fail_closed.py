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


def _execution_only_state(qa_workdir: Path,
                          scenarios: list[QAScenario] | None = None
                          ) -> QALoopState:
    state = QALoopState(pr_id="pr-c", planning_phase=False)
    state.qa_workdir = str(qa_workdir)
    state.scenarios = (scenarios if scenarios is not None
                       else [QAScenario(index=1, title="S1", focus="f")])
    return state


def _run_execution_only(tmp_path, *, container_enabled: bool,
                        runtime_available: bool,
                        container_launch_error: BaseException | None = None,
                        scenarios: list[QAScenario] | None = None):
    """Drive run_qa_sync's execution-only path with launch spies."""
    pr, data, workdir, qa_workdir = _pm_fixture(tmp_path)
    state = _execution_only_state(qa_workdir, scenarios)
    host_launch = MagicMock()
    container_launch = MagicMock(side_effect=container_launch_error)
    scenario0 = MagicMock()
    finalize = MagicMock(return_value=state)
    resume_write = MagicMock()
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
        stack.enter_context(patch("pm_core.qa_loop._write_resume_file",
                                  resume_write))
        run_qa_sync(state, tmp_path / "pm", pr, lambda *a: None,
                    max_scenarios=1)
    return (state, host_launch, container_launch, scenario0, finalize,
            resume_write)


def test_run_qa_sync_fails_closed_when_runtime_unavailable(tmp_path, home):
    """Pre-fix: the preflight flips use_containers=False and launches the
    refiner/worker via _launch_scenarios_in_tmux (host).  Post-fix: it aborts
    with ERROR before any launch."""
    state, host_launch, container_launch, scenario0, finalize, resume = (
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
    # Nothing launched, so there is no resumable snapshot to re-enter.
    resume.assert_not_called()
    # The failure is published for the dashboard and the next TUI, with the
    # original cause (not just a bare ERROR).
    status = (tmp_path / "qa" / "qa_status.json").read_text()
    assert '"overall": "ERROR"' in status
    assert "runtime unavailable" in status


def test_run_qa_sync_uses_containers_when_runtime_healthy(tmp_path, home):
    state, host_launch, container_launch, scenario0, finalize, _resume = (
        _run_execution_only(tmp_path, container_enabled=True,
                            runtime_available=True))

    container_launch.assert_called_once()
    host_launch.assert_not_called()
    finalize.assert_called_once()
    assert state.latest_verdict != "ERROR"


def test_run_qa_sync_host_execution_when_container_disabled(tmp_path, home):
    """Explicitly disabled container mode still supports host execution."""
    state, host_launch, container_launch, scenario0, finalize, _resume = (
        _run_execution_only(tmp_path, container_enabled=False,
                            runtime_available=False))

    host_launch.assert_called_once()
    container_launch.assert_not_called()
    finalize.assert_called_once()
    assert state.latest_verdict != "ERROR"


def test_run_qa_sync_reports_error_when_container_launch_raises(
        tmp_path, home):
    """A create/setup failure during the initial launch stops the run with
    ERROR: no host launch, no finalize pane, no invented scenario verdict."""
    from pm_core.qa_loop import ContainerLaunchError

    state, host_launch, container_launch, scenario0, finalize, _resume = (
        _run_execution_only(
            tmp_path, container_enabled=True, runtime_available=True,
            container_launch_error=ContainerLaunchError(
                "image not found; refusing to launch on the host")))

    host_launch.assert_not_called()
    finalize.assert_not_called()
    assert state.running is False
    assert state.latest_verdict == "ERROR"
    # latest_output stays a single TUI log line; the full cause+remedy is
    # preserved in _error (and the status file).
    assert "\n" not in state.latest_output
    assert state.latest_output.startswith("Container launch failed:")
    assert "refusing to launch on the host" in state._error
    assert state.scenario_verdicts == {}
    # The infrastructure failure is published, not dropped.
    status = (tmp_path / "qa" / "qa_status.json").read_text()
    assert '"overall": "ERROR"' in status


def test_queued_container_create_failure_raises_from_poll(tmp_path, home):
    """A queued scenario whose container cannot be created must raise out of
    the polling loop (so _execute_and_finalize publishes ERROR) instead of
    being recorded as an invented INPUT_REQUIRED verdict."""
    from pm_core.qa_loop import ContainerLaunchError, _poll_tmux_verdicts

    clone = tmp_path / "clone"
    clone.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    queued = QAScenario(index=2, title="S2", focus="f")
    state = QALoopState(pr_id="pr-c", planning_phase=False)
    state.qa_workdir = str(tmp_path)
    state.session_tag = "s"
    state.scenarios = [queued]

    with ExitStack() as stack:
        stack.enter_context(patch("pm_core.qa_loop._resolve_qa_model",
                                  return_value=SimpleNamespace(
                                      model=None, provider=None, effort=None)))
        stack.enter_context(patch(
            "pm_core.qa_loop.create_scenario_workdir",
            return_value=(clone, scratch)))
        create = stack.enter_context(patch.object(
            container_mod, "create_qa_container",
            side_effect=container_mod.ContainerError("image not found")))
        remove = stack.enter_context(
            patch.object(container_mod, "remove_container"))
        new_window = stack.enter_context(patch(
            "pm_core.tmux.new_window_get_pane", return_value="%1"))
        stack.enter_context(patch("pm_core.qa_loop._write_status_file"))

        with pytest.raises(ContainerLaunchError):
            _poll_tmux_verdicts(
                state, {}, {"id": "pr-c", "branch": "b"}, "pm-s",
                str(tmp_path), tmp_path / "qa_status.json", lambda *a: None,
                queued_scenarios=[queued], use_containers=True,
            )

    create.assert_called_once()  # the container path ran, not the host path
    # Only the failed attempt's exact container is released.
    assert remove.call_count == 1
    new_window.assert_not_called()
    assert state.scenario_verdicts == {}
    assert state.scenarios == [queued]  # the queue swap was unwound


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

        with pytest.raises(qa_loop.ContainerLaunchError) as excinfo:
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


def test_relaunch_reuses_the_running_container(tmp_path, home):
    """Healthy control: a container run whose worker pane died but whose
    container is still alive relaunches via the container (exec) command —
    it does not host-launch and does not downgrade the run."""
    state = QALoopState(pr_id="pr-c")
    state.qa_workdir = str(tmp_path)
    scenario = QAScenario(index=1, title="S1", focus="f",
                          container_name="pm-x", worktree_path=str(tmp_path))

    with ExitStack() as stack:
        stack.enter_context(patch("pm_core.qa_loop._resolve_qa_model",
                                  return_value=SimpleNamespace(
                                      model=None, provider=None, effort=None)))
        stack.enter_context(patch.object(container_mod,
                                         "container_is_running",
                                         return_value=True))
        build = stack.enter_context(patch(
            "pm_core.qa_loop._build_scenario_run_cmd",
            return_value=("EXEC-CMD", "/clone")))
        new_window = stack.enter_context(patch(
            "pm_core.tmux.new_window_get_pane", return_value="%1"))
        stack.enter_context(patch("pm_core.tmux.pane_window_id",
                                  return_value=None))
        stack.enter_context(patch(
            "pm_core.claude_launcher.session_id_from_transcript",
            return_value="sid"))
        relaunched = qa_loop._relaunch_scenario_window(
            scenario, state, {}, {"id": "pr-c", "branch": "b"},
            "pm-s", str(tmp_path), use_containers=True)

    assert relaunched is True
    new_window.assert_called_once()
    # The container shapes the prompt without a host pm session, and the
    # pane runs the container command.
    assert build.call_args.kwargs["session"] is None
    assert new_window.call_args.args[2] == "EXEC-CMD"
    assert scenario.container_name == "pm-x"
    assert scenario.pane_id == "%1"


def test_relaunch_host_mode_control(tmp_path, home):
    """Explicitly disabled container mode still relaunches on the host: a
    host run has no container name, must not be probed for one, and keeps
    the pm session in the prompt shape."""
    state = QALoopState(pr_id="pr-c")
    state.qa_workdir = str(tmp_path)
    scenario = QAScenario(index=1, title="S1", focus="f",
                          container_name=None, worktree_path=str(tmp_path))

    with ExitStack() as stack:
        stack.enter_context(patch("pm_core.qa_loop._resolve_qa_model",
                                  return_value=SimpleNamespace(
                                      model=None, provider=None, effort=None)))
        running = stack.enter_context(patch.object(
            container_mod, "container_is_running", return_value=False))
        build = stack.enter_context(patch(
            "pm_core.qa_loop._build_scenario_run_cmd",
            return_value=("HOST-CMD", str(tmp_path))))
        new_window = stack.enter_context(patch(
            "pm_core.tmux.new_window_get_pane", return_value="%1"))
        stack.enter_context(patch("pm_core.tmux.pane_window_id",
                                  return_value=None))
        stack.enter_context(patch(
            "pm_core.claude_launcher.session_id_from_transcript",
            return_value="sid"))
        relaunched = qa_loop._relaunch_scenario_window(
            scenario, state, {}, {"id": "pr-c", "branch": "b"},
            "pm-s", str(tmp_path), use_containers=False)

    assert relaunched is True
    running.assert_not_called()  # no container is consulted in host mode
    assert build.call_args.kwargs["session"] == "pm-s"
    assert new_window.call_args.args[2] == "HOST-CMD"


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
    assert state.held is False
    assert state.latest_verdict == "ERROR"
    assert "no agent was launched on the host" in state._error
    finalize.assert_not_called()
    # The completed ERROR is published so a TUI restart clears the snapshot
    # instead of re-adopting the same unusable container run.
    status = (qa_workdir / "qa_status.json").read_text()
    assert '"overall": "ERROR"' in status
    assert "no agent was launched on the host" in status


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

        with patch("subprocess.run",
                   side_effect=OSError("permission denied")):
            ok, problem = container_mod._runtime_status()
        assert ok is False
        assert "could not run" in problem and "permission denied" in problem

        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=1,
                                         stderr="daemon not running",
                                         stdout="")
            ok, problem = container_mod._runtime_status()
        assert ok is False
        assert "exited 1" in problem and "daemon not running" in problem

        # capture_output without text=True hands back bytes; the diagnostic
        # must still read as text.
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=125,
                                         stderr=b"permission denied\n",
                                         stdout=b"")
            ok, problem = container_mod._runtime_status()
        assert ok is False
        assert "exited 125" in problem and "permission denied" in problem

        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stderr="", stdout="")
            ok, problem = container_mod._runtime_status()
        assert ok is True and problem == ""


def test_container_preflight_error_only_when_enabled_and_unavailable():
    """The preflight gate is inert for explicitly disabled container mode."""
    with patch.object(container_mod, "is_container_mode_enabled",
                      return_value=False), \
            patch.object(container_mod, "_runtime_status",
                         return_value=(False, "runtime down")):
        assert container_mod.container_preflight_error() is None

    with patch.object(container_mod, "is_container_mode_enabled",
                      return_value=True), \
            patch.object(container_mod, "_runtime_status",
                         return_value=(False, "runtime down")):
        assert container_mod.container_preflight_error() == "runtime down"

    with patch.object(container_mod, "is_container_mode_enabled",
                      return_value=True), \
            patch.object(container_mod, "_runtime_status",
                         return_value=(True, "")):
        assert container_mod.container_preflight_error() is None


def test_qa_debug_fails_closed_when_create_raises_non_container_error(
        tmp_path, home):
    """A runtime that dies between the preflight and the create surfaces as
    OSError; the command must still report it and exit — never fall through
    to the host branch."""
    from pm_core.cli.qa import qa as qa_group

    root = tmp_path / "pm"
    root.mkdir()
    instr = tmp_path / "repro.md"
    instr.write_text("# repro\n")
    item = {"path": str(instr), "title": "Repro", "description": "d"}
    data = {"project": {"name": "t"}, "prs": [], "plans": []}
    clone = tmp_path / "clone"
    clone.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    build_cmd = MagicMock(return_value="claude ...")
    remove = MagicMock()
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
        _patch_runtime(stack, True)
        stack.enter_context(patch(
            "pm_core.qa_loop.create_scenario_workdir",
            return_value=(clone, scratch)))
        stack.enter_context(patch.object(
            container_mod, "create_qa_container",
            side_effect=OSError("podman: No such file or directory")))
        stack.enter_context(patch.object(container_mod, "remove_container",
                                         remove))
        stack.enter_context(patch(
            "pm_core.claude_launcher.build_claude_shell_cmd", build_cmd))
        result = CliRunner().invoke(qa_group,
                                    ["debug", "repro", "--branch", "b"])

    assert result.exit_code == 1
    assert "could not be created" in result.output.lower()
    assert "No such file or directory" in result.output
    assert "host" in result.output.lower()
    build_cmd.assert_not_called()
    # Only this attempt's own container is released.
    assert remove.call_count == 1


def test_resume_keeps_host_mode_when_snapshot_says_host(tmp_path, home):
    """The persisted per-run mode wins: a host run resumes on the host even
    when container mode is enabled and the runtime is down now."""
    pr, data, workdir, qa_workdir = _pm_fixture(tmp_path)
    state = _execution_only_state(qa_workdir)
    state.session_tag = "s"
    qa_loop._write_resume_file(state, False, 0, set())

    finalize = MagicMock(return_value=state)
    with ExitStack() as stack:
        stack.enter_context(patch("pm_core.qa_loop.get_pm_session",
                                  return_value="pm-s"))
        stack.enter_context(patch("pm_core.store.load", return_value=data))
        stack.enter_context(patch("pm_core.store.get_pr", return_value=pr))
        stack.enter_context(patch.object(container_mod,
                                         "is_container_mode_enabled",
                                         return_value=True))
        _patch_runtime(stack, False)
        stack.enter_context(patch("pm_core.qa_loop._execute_and_finalize",
                                  finalize))
        result = qa_loop.resume_qa_sync(state, tmp_path / "pm", pr,
                                        lambda *a: None)

    assert result is state
    finalize.assert_called_once()
    assert state.latest_verdict != "ERROR"


def test_qa_error_detail_only_for_error_verdicts(tmp_path, home):
    """``qa_error_detail`` exposes the fail-closed cause+remedy for a CLI
    caller, and stays inert for verdicts that carry no infrastructure error."""
    state = QALoopState(pr_id="pr-c")
    state._error = "boom"
    state.latest_verdict = "INPUT_REQUIRED"
    assert qa_loop.qa_error_detail(state) == ""
    state.latest_verdict = "ERROR"
    assert qa_loop.qa_error_detail(state) == "boom"


def test_qa_run_prints_the_full_cause_and_remedy(tmp_path, home):
    """`pm qa run` is the primary execution entry point: it must report the
    fail-closed launch's cause and retry remedy, not only the one-line
    progress entry ``on_update`` prints."""
    from pm_core.cli.qa import qa as qa_group

    root = tmp_path / "pm"
    root.mkdir()
    instr = tmp_path / "repro.md"
    instr.write_text("# repro\n")
    item = {"path": str(instr), "title": "Repro", "description": "d"}
    data = {"project": {"name": "t"}, "prs": [], "plans": []}
    pr = {"id": "pr-c", "title": "T", "branch": "b", "status": "qa"}

    failed = QALoopState(pr_id="pr-c", planning_phase=False)
    failed.latest_verdict = "ERROR"
    failed.latest_output = (
        "Container mode is enabled but the container runtime is "
        "unavailable: boom")
    failed._error = (
        "Container mode is enabled, but the container runtime is "
        "unavailable, so no agent was launched on the host.\n\n"
        "Cause: boom\n\n"
        "To retry:\n"
        "  - fix the runtime; or\n"
        "  - if host execution is intended, disable container mode "
        "explicitly with 'pm container disable'.")

    with ExitStack() as stack:
        stack.enter_context(patch("pm_core.cli.qa.state_root",
                                  return_value=root))
        stack.enter_context(patch("pm_core.qa_instructions.get_instruction",
                                  return_value=item))
        stack.enter_context(patch("pm_core.store.load", return_value=data))
        stack.enter_context(patch("pm_core.cli.helpers._resolve_pr_id",
                                  return_value=pr))
        stack.enter_context(patch("pm_core.qa_loop.run_qa_sync",
                                  return_value=failed))
        result = CliRunner().invoke(qa_group,
                                    ["run", "repro", "--pr", "pr-c"])

    assert result.exit_code == 0
    # The actionable detail the CLI would otherwise drop (run_qa_sync is
    # stubbed here, so this is the only place it can come from).
    assert "no agent was launched on the host" in result.output
    assert "pm container disable" in result.output
    assert "Result: ERROR" in result.output


def test_initial_launch_keeps_queued_scenarios_visible(tmp_path, home):
    """A concurrency cap must not make queued scenarios vanish from the
    dashboard while the first batch runs.

    ``run_qa_sync`` narrows ``state.scenarios`` to the launch batch before
    calling the launch helper.  The helper's status write (and the initial
    one) must still see every scenario plus the queued set, otherwise the
    status file drops the queued scenarios until their turn comes — the
    launch-time write used to clobber the ``queued`` marker written just
    before it.
    """
    import json

    scenarios = [QAScenario(index=1, title="S1", focus="f"),
                 QAScenario(index=2, title="S2", focus="f")]
    state, host_launch, container_launch, scenario0, finalize, _resume = (
        _run_execution_only(
            tmp_path, container_enabled=True, runtime_available=True,
            scenarios=scenarios))

    container_launch.assert_called_once()
    kwargs = container_launch.call_args.kwargs
    # The launch helper is told about every scenario, not just the batch it
    # is about to start, so its status write can keep the queue visible.
    assert kwargs["_status_scenarios"] == scenarios
    assert kwargs["_queued_indices"] == {2}

    status = json.loads((tmp_path / "qa" / "qa_status.json").read_text())
    by_index = {s["index"]: s for s in status["scenarios"]}
    assert by_index[1]["verdict"] == ""
    assert by_index[2]["verdict"] == "queued"
    assert status["overall"] == ""
