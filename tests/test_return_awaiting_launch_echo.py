"""QA S75: a sign-off return's ``awaiting`` is cleared even when the
launch's stdout is a broken pipe.

The TUI launches a routed review (``pm pr review --fresh --review-loop``)
or rework (``pm pr start --fresh``) as a subprocess whose stdout it reads.
A TUI restart right after its own hop leaves that pipe broken: the window
opens, then the "Opened review window" / "Launched Claude" echo raises
EPIPE.  The clear used to come after the echo, so ``awaiting`` and the hop's
launch claim outlived the session the launch opened, and a tick after the
claim expired launched a second --fresh session over it.
"""

from __future__ import annotations

from unittest import mock

import click
import pytest

from pm_core import signoff
from pm_core.cli import pr as pr_mod

PR = "pr-001"


def _broken_echo(prefix):
    """click.echo whose pipes break at the first *prefix* line: the TUI that
    reads both stdout and stderr exec'd itself, so every later echo (the
    error report included) raises too."""
    real = click.echo
    broken = []

    def echo(message=None, *a, **k):
        if broken or str(message or "").startswith(prefix):
            broken.append(message)
            raise BrokenPipeError(32, "Broken pipe")
        return real(message, *a, **k)
    return echo


@pytest.fixture
def review_env(tmp_path, monkeypatch):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    monkeypatch.setattr(pr_mod.tmux_mod, "has_tmux", lambda: True)
    monkeypatch.setattr(pr_mod.tmux_mod, "in_tmux", lambda: True)
    monkeypatch.setattr(pr_mod.tmux_mod, "session_exists", lambda s: True)
    monkeypatch.setattr(pr_mod.tmux_mod, "find_window_by_name", lambda s, n: None)
    monkeypatch.setattr(pr_mod.tmux_mod, "new_window_get_pane",
                        lambda *a, **k: "%diff")
    monkeypatch.setattr(pr_mod.tmux_mod, "split_pane_at", lambda *a, **k: "%claude")
    monkeypatch.setattr(pr_mod.tmux_mod, "set_shared_window_size", lambda *a, **k: None)
    monkeypatch.setattr(pr_mod, "_get_pm_session", lambda: "pm-test")
    monkeypatch.setattr(pr_mod.prompt_gen, "generate_review_prompt",
                        lambda *a, **k: "prompt")
    monkeypatch.setattr(pr_mod, "build_claude_shell_cmd", lambda **kw: "claude-cmd")
    import pm_core.container as container_mod
    monkeypatch.setattr(container_mod, "is_container_mode_enabled", lambda: False)
    monkeypatch.setattr(container_mod, "wrap_claude_cmd", lambda cmd, wd, **kw: (cmd, ""))
    monkeypatch.setattr(container_mod, "remove_container", lambda *a, **k: None)
    monkeypatch.setattr(pr_mod.subprocess, "run",
                        lambda *a, **k: mock.Mock(stdout="", stderr="", returncode=0))
    monkeypatch.setattr(pr_mod, "state_root", lambda: tmp_path)
    cleared = []
    monkeypatch.setattr(signoff, "clear_return_awaiting",
                        lambda root, pr_id, hop, **k: cleared.append((pr_id, hop)))
    data = {"project": {"name": "demo", "base_branch": "master", "backend": "vanilla"},
            "prs": [], "plans": []}
    pr_entry = {"id": PR, "title": "T", "branch": "pm/pr-001",
                "status": "in_review", "workdir": str(workdir)}
    return data, pr_entry, cleared


def test_review_return_cleared_when_launch_echo_hits_a_broken_pipe(review_env, monkeypatch):
    data, pr_entry, cleared = review_env
    monkeypatch.setattr(pr_mod.click, "echo", _broken_echo("Opened review window"))
    # The echo's error is caught and reported (itself through a broken pipe
    # in production); the window is open either way.
    try:
        pr_mod._launch_review_window(data, pr_entry, fresh=True)
    except BrokenPipeError:
        pass
    assert cleared == [(PR, "review")]


def test_review_return_cleared_on_a_normal_launch(review_env):
    data, pr_entry, cleared = review_env
    pr_mod._launch_review_window(data, pr_entry, fresh=True)
    assert cleared == [(PR, "review")]


def test_impl_return_cleared_when_launch_echo_hits_a_broken_pipe(tmp_path, monkeypatch):
    import yaml
    from click.testing import CliRunner
    from pm_core import git_ops, store

    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()
    workdir = tmp_path / "wd"
    workdir.mkdir()
    data = {"project": {"name": "demo", "repo": str(tmp_path), "base_branch": "master",
                        "backend": "local"},
            "prs": [{"id": PR, "title": "T", "branch": "pm/pr-001", "status": "in_progress",
                     "workdir": str(workdir),
                     "signoff_return": {"verdict": "SIGNOFF_IMPL", "hop": "impl",
                                        "awaiting": "impl"}}],
            "plans": []}
    store.save(data, pm_dir)
    windows = {}
    monkeypatch.setattr(pr_mod, "state_root", lambda: pm_dir)
    monkeypatch.setattr(pr_mod, "_get_pm_session", lambda: "pm-test")
    monkeypatch.setattr(pr_mod.tmux_mod, "has_tmux", lambda: True)
    monkeypatch.setattr(pr_mod.tmux_mod, "in_tmux", lambda: True)
    monkeypatch.setattr(pr_mod.tmux_mod, "session_exists", lambda s: True)
    monkeypatch.setattr(pr_mod.tmux_mod, "find_window_by_name",
                        lambda s, n: windows.get(n))
    monkeypatch.setattr(pr_mod.tmux_mod, "new_window",
                        lambda s, n, *a, **k: windows.setdefault(n, {"id": "@1"}))
    monkeypatch.setattr(pr_mod.tmux_mod, "set_shared_window_size", lambda *a, **k: None)
    monkeypatch.setattr(pr_mod, "find_claude", lambda: "/usr/bin/claude")
    monkeypatch.setattr(pr_mod, "build_claude_shell_cmd", lambda **kw: "claude-cmd")
    import pm_core.container as container_mod
    monkeypatch.setattr(container_mod, "is_container_mode_enabled", lambda: False)
    monkeypatch.setattr(container_mod, "wrap_claude_cmd", lambda cmd, wd, **kw: (cmd, ""))
    yaml_dump = yaml.safe_dump(data)
    monkeypatch.setattr(git_ops, "run_git", lambda *a, **k: mock.Mock(
        returncode=0, stdout=yaml_dump if a[:1] == ("show",) else "abc12345\n", stderr=""))
    monkeypatch.setattr(git_ops, "is_git_repo", lambda p: False)
    monkeypatch.setattr(git_ops, "checkout_branch", lambda *a, **k: None)
    cleared = []
    monkeypatch.setattr(signoff, "clear_return_awaiting",
                        lambda root, pr_id, hop, **k: cleared.append((pr_id, hop)))
    monkeypatch.setattr(pr_mod.click, "echo", _broken_echo("Launched Claude in tmux window"))

    CliRunner().invoke(pr_mod.pr, ["start", PR, "--fresh", "--background"])

    assert windows, "the impl window was not opened"
    assert cleared == [(PR, "impl")]
