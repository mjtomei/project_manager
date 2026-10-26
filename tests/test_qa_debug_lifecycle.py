"""Debug launch failures release allocations and preserve the original error."""

import importlib
import subprocess
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from pm_core import claude_launcher, container, loop_shared, qa_instructions, qa_loop, store, tmux
from pm_core.cli import cli

qa_cli = importlib.import_module("pm_core.cli.qa")


@pytest.fixture
def debug_context(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    instruction = tmp_path / "instruction.md"
    instruction.write_text("Check the test fixture.")
    monkeypatch.setattr(qa_cli, "state_root", lambda: tmp_path / "pm")
    monkeypatch.setattr(qa_instructions, "get_instruction", lambda *a: {
        "path": str(instruction), "title": "fixture"})
    monkeypatch.setattr(store, "load", lambda *a: {})
    monkeypatch.setattr(loop_shared, "get_pm_session", lambda: "pm-test")
    monkeypatch.setattr(qa_loop, "create_scenario_workdir",
                        lambda *a, **k: (tmp_path / "clone", tmp_path / "scratch"))
    monkeypatch.setattr(qa_loop, "_setup_clone_override", lambda *a: None)
    monkeypatch.setattr(container, "is_container_mode_enabled", lambda: True)
    monkeypatch.setattr(container, "_runtime_available", lambda: True)
    monkeypatch.setattr(container, "load_container_config", MagicMock())

    def create(**kwargs):
        kwargs["allocation_identity"].update(id="cid", generation="gen")
        return "cid"

    monkeypatch.setattr(container, "create_qa_container", create)
    monkeypatch.setattr(container, "build_exec_cmd", lambda *a, **k: "exec-worker")
    monkeypatch.setattr(claude_launcher, "build_claude_shell_cmd", lambda **k: "worker")
    discard = MagicMock(return_value=True)
    monkeypatch.setattr(container, "discard_unowned_container", discard)
    return discard


@pytest.mark.parametrize("stage", ["tmux", "command", "exec-command", "foreground"])
def test_debug_launch_failure_discards_captured_allocation(debug_context, monkeypatch, stage):
    discard = debug_context
    error = subprocess.CalledProcessError(1, "tmux", stderr="can't find session: test")
    new_window = MagicMock(side_effect=error)
    monkeypatch.setattr(tmux, "new_window_get_pane", new_window)
    if stage == "command":
        monkeypatch.setattr(claude_launcher, "build_claude_shell_cmd",
                            MagicMock(side_effect=RuntimeError("command build failed")))
    elif stage == "exec-command":
        monkeypatch.setattr(container, "build_exec_cmd",
                            MagicMock(side_effect=container.ContainerError("generation unavailable")))
    elif stage == "foreground":
        monkeypatch.setattr(qa_cli.os, "chdir", lambda *a: None)
        monkeypatch.setattr(qa_cli.os, "execvp",
                            MagicMock(side_effect=OSError("bash unavailable")))
    args = ["qa", "debug", "fixture", "--branch", "test"]
    if stage == "foreground":
        args.append("--foreground")
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    discard.assert_called_once()
    assert discard.call_args.kwargs == {"container_id": "cid", "generation": "gen"}
    assert not isinstance(result.exception, UnboundLocalError)
    expected_error = {
        "tmux": "can't find session: test",
        "command": "command build failed",
        "exec-command": "generation unavailable",
        "foreground": "bash unavailable",
    }[stage]
    assert expected_error in result.output
    if stage != "tmux":
        new_window.assert_not_called()


def test_successful_debug_attachment_keeps_allocation(debug_context, monkeypatch):
    monkeypatch.setattr(tmux, "new_window_get_pane", lambda *a, **k: "%7")
    result = CliRunner().invoke(cli, ["qa", "debug", "fixture", "--branch", "test"])
    assert result.exit_code == 0, result.output
    assert "Launched debug session" in result.output
    debug_context.assert_not_called()


def test_foreground_debug_outside_tmux_uses_project_session(debug_context, tmp_path, monkeypatch):
    from pm_core.cli import helpers

    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(loop_shared, "get_pm_session", lambda: None)
    monkeypatch.setattr(helpers, "_get_session_name_for_cwd", lambda: "pm-project-tag")
    created = []
    commands = []

    def create(**kwargs):
        created.append(kwargs)
        kwargs["allocation_identity"].update(id="cid", generation="gen")
        return "cid"

    def command(*args, **kwargs):
        commands.append(kwargs)
        return "exec-worker"

    monkeypatch.setattr(container, "create_qa_container", create)
    monkeypatch.setattr(container, "build_exec_cmd", command)
    monkeypatch.setattr(qa_cli.os, "chdir", lambda path: None)
    # Successful exec never returns, so SystemExit models process replacement.
    monkeypatch.setattr(qa_cli.os, "execvp", MagicMock(side_effect=SystemExit(0)))
    window = MagicMock()
    monkeypatch.setattr(tmux, "new_window_get_pane", window)
    result = CliRunner().invoke(cli, ["qa", "debug", "fixture", "--branch", "test", "--foreground"])
    assert result.exit_code == 0, result.output
    assert created[0]["session_tag"] == "project-tag"
    assert commands[0]["interactive_owner"] is True
    window.assert_not_called()
    debug_context.assert_not_called()


def test_window_debug_still_requires_current_session(debug_context, monkeypatch):
    monkeypatch.setattr(loop_shared, "get_pm_session", lambda: None)
    create = MagicMock()
    monkeypatch.setattr(container, "create_qa_container", create)
    result = CliRunner().invoke(cli, ["qa", "debug", "fixture", "--branch", "test"])
    assert result.exit_code != 0
    assert "No pm session found" in result.output
    create.assert_not_called()


def test_debug_host_mode_does_not_require_runtime(debug_context, monkeypatch):
    monkeypatch.setattr(container, "is_container_mode_enabled", lambda: False)
    runtime = MagicMock(side_effect=AssertionError("host mode must not probe runtime"))
    monkeypatch.setattr(container, "_runtime_available", runtime)
    create = MagicMock()
    monkeypatch.setattr(container, "create_qa_container", create)
    monkeypatch.setattr(tmux, "new_window_get_pane", lambda *args, **kwargs: "%7")
    result = CliRunner().invoke(cli, ["qa", "debug", "fixture", "--branch", "test"])
    assert result.exit_code == 0, result.output
    assert "Launched debug session" in result.output
    runtime.assert_not_called()
    create.assert_not_called()


@pytest.mark.parametrize("foreground", [False, True])
def test_debug_unavailable_runtime_never_falls_back_to_host(debug_context, tmp_path, monkeypatch, foreground):
    monkeypatch.setattr(container, "_runtime_available", lambda: False)
    clone = MagicMock(return_value=(tmp_path / "clone", tmp_path / "scratch"))
    monkeypatch.setattr(qa_loop, "create_scenario_workdir", clone)
    builder = MagicMock(return_value="host-worker")
    monkeypatch.setattr(claude_launcher, "build_claude_shell_cmd", builder)
    window = MagicMock(return_value="%7")
    monkeypatch.setattr(tmux, "new_window_get_pane", window)
    monkeypatch.setattr(qa_cli.os, "chdir", lambda path: None)
    execute = MagicMock(side_effect=SystemExit(0))
    monkeypatch.setattr(qa_cli.os, "execvp", execute)
    args = ["qa", "debug", "fixture", "--branch", "test"]
    if foreground:
        args.append("--foreground")
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    assert "runtime" in result.output.lower()
    clone.assert_not_called()
    builder.assert_not_called()
    window.assert_not_called()
    execute.assert_not_called()
