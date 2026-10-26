"""Implementation launch failures preserve runtime stderr without double launching."""
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from pm_core import container, model_config, signoff
from pm_core.cli import pr as pr_mod


@pytest.mark.parametrize("companion,renamed", [(False, False), (True, False), (False, True)])
def test_impl_launch_reports_stderr(monkeypatch, tmp_path, companion, renamed):
    entry = {"id": "pr-001", "title": "Test", "status": "in_progress",
             "branch": "topic", "workdir": str(tmp_path)}
    data = {"project": {"repo": str(tmp_path), "backend": "local"}, "prs": [entry]}
    monkeypatch.setattr(pr_mod, "state_root", lambda: tmp_path)
    monkeypatch.setattr(pr_mod.store, "load", lambda *a: data)
    monkeypatch.setattr(pr_mod.store, "locked_update", lambda *a: data)
    monkeypatch.setattr(pr_mod, "trigger_tui_refresh", Mock())
    monkeypatch.setattr(pr_mod, "_get_pm_session", lambda: "pm-test")
    monkeypatch.setattr(pr_mod.tmux_mod, "session_exists", lambda *a: True)
    monkeypatch.setattr(pr_mod.tmux_mod, "find_window_by_name", lambda *a: None)
    monkeypatch.setattr(pr_mod.git_ops, "run_git", Mock(return_value=SimpleNamespace(
        returncode=0, stdout="prs:\n- id: pr-001\n")))
    monkeypatch.setattr(pr_mod.git_ops, "is_git_repo", lambda *a: True)
    monkeypatch.setattr(pr_mod, "_workdir_is_dirty", lambda *a: True)
    monkeypatch.setattr(pr_mod.prompt_gen, "generate_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(model_config, "resolve_model_and_provider", lambda *a, **k:
                        SimpleNamespace(model=None, provider=None, effort=None))
    monkeypatch.setattr(pr_mod, "find_claude", lambda: "claude")
    monkeypatch.setattr(pr_mod, "build_claude_shell_cmd", lambda **k: "worker")
    monkeypatch.setattr(container, "is_container_mode_enabled", lambda: True)
    def wrap(*a, allocation_identity, **k):
        allocation_identity.update(id="cid", generation="gen")
        return "EXEC", "pm-test-impl-pr-001"
    monkeypatch.setattr(container, "wrap_claude_cmd", wrap)
    discard = Mock(wraps=container.discard_unowned_container) if renamed else Mock(return_value=False)
    monkeypatch.setattr(container, "discard_unowned_container", discard)
    if renamed:
        monkeypatch.setattr(container, "current_container_id",
                            lambda name: "" if name == "pm-test-impl-pr-001" else "cid")
    launch = Mock()
    monkeypatch.setattr(pr_mod, "launch_claude", launch)
    error = subprocess.CalledProcessError(1, ["tmux"], stderr=b"can't find session: pm-test")
    monkeypatch.setattr(pr_mod.tmux_mod, "new_window", Mock(side_effect=error))
    monkeypatch.setattr(pr_mod.tmux_mod, "new_window_get_pane", lambda *a, **k: "%worker")
    monkeypatch.setattr(pr_mod, "_add_companion_pane", Mock(side_effect=error))
    monkeypatch.setattr(signoff, "clear_return_awaiting", Mock())
    if companion:
        # Fast-path lookup misses; after creating the worker the window is found.
        monkeypatch.setattr(pr_mod.tmux_mod, "find_window_by_name", Mock(
            side_effect=[None, {"id": "@1"}]))
    result = CliRunner().invoke(pr_mod.pr, ["start", "pr-001", "--companion"] if companion
                                else ["start", "pr-001"])
    assert "can't find session: pm-test" in result.output
    assert "Launching Claude in current terminal" not in result.output
    launch.assert_not_called()
    if companion:
        assert result.exit_code == 0, result.output
        discard.assert_not_called()
    else:
        assert result.exit_code == 1, result.output
        discard.assert_called_once_with("pm-test-impl-pr-001", container_id="cid", generation="gen")
