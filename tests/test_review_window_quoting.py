"""Regression tests for pr-315f753.

PR titles containing apostrophes (or other shell metacharacters) used to
break the diff_cmd shell pipeline built in ``_launch_review_window``,
killing the diff pane's shell before tmux registered the new window.
``find_window_by_name`` then returned ``None`` and the review loop
reported "Review window not found after launch".

These tests verify that the diff_cmd is now constructed safely and that
the silent-failure path now logs a warning.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from pm_core.cli import pr as pr_mod


HOSTILE_TITLES = [
    "Bug: pm pr start <new-pr> doesn't open",  # apostrophe
    "Fix: handle $HOME and `whoami` cases",     # dollar + backtick
    'Fix "quoted" segments and ; semicolons',   # double-quote + semi
    "Refactor: foo() && bar() | baz",           # parens / && / pipe
    "Empty test '' edge",                       # adjacent single quotes
]


def _make_data():
    return {
        "project": {
            "name": "demo",
            "base_branch": "master",
            "backend": "vanilla",
        },
        "prs": [],
        "plans": [],
    }


def _make_pr(title: str, workdir: str):
    return {
        "id": "pr-001",
        "title": title,
        "branch": "pm/pr-001",
        "status": "in_progress",
        "workdir": workdir,
    }


@pytest.fixture
def fake_tmux(tmp_path, monkeypatch):
    """Patch enough of pr_mod's environment that ``_launch_review_window``
    will run all the way through diff_cmd construction in a unit test."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    captured: dict = {}

    def fake_new_window_get_pane(session, name, cmd, wd, switch=False):
        captured["diff_cmd"] = cmd
        captured["workdir"] = wd
        return "%fake-diff-pane"

    monkeypatch.setattr(pr_mod.tmux_mod, "has_tmux", lambda: True)
    monkeypatch.setattr(pr_mod.tmux_mod, "in_tmux", lambda: True)
    monkeypatch.setattr(pr_mod.tmux_mod, "session_exists", lambda s: True)
    monkeypatch.setattr(pr_mod.tmux_mod, "find_window_by_name",
                        lambda s, n: None)
    monkeypatch.setattr(pr_mod.tmux_mod, "new_window_get_pane",
                        fake_new_window_get_pane)
    monkeypatch.setattr(pr_mod.tmux_mod, "split_pane_at",
                        lambda *a, **k: "%fake-claude-pane")
    monkeypatch.setattr(pr_mod.tmux_mod, "set_shared_window_size",
                        lambda *a, **k: None)
    monkeypatch.setattr(pr_mod, "_get_pm_session", lambda: "pm-test")
    monkeypatch.setattr(pr_mod.prompt_gen, "generate_review_prompt",
                        lambda *a, **k: "fake-review-prompt")
    monkeypatch.setattr(pr_mod, "build_claude_shell_cmd",
                        lambda **kw: "fake-claude-cmd")

    # wrap_claude_cmd / container helpers
    import pm_core.container as container_mod
    monkeypatch.setattr(container_mod, "is_container_mode_enabled",
                        lambda: False)
    monkeypatch.setattr(container_mod, "wrap_claude_cmd",
                        lambda cmd, wd, **kw: (cmd, ""))
    monkeypatch.setattr(container_mod, "remove_container",
                        lambda *a, **k: None)

    # Skip post-creation tmux interactions that need a real server.
    monkeypatch.setattr(pr_mod.subprocess, "run",
                        lambda *a, **k: mock.Mock(stdout="", stderr="", returncode=0))

    return {"workdir": str(workdir), "captured": captured}


@pytest.mark.parametrize("title", HOSTILE_TITLES)
def test_diff_cmd_is_shell_safe(fake_tmux, title):
    """diff_cmd must be syntactically valid bash for any PR title."""
    data = _make_data()
    pr_entry = _make_pr(title, fake_tmux["workdir"])

    pr_mod._launch_review_window(data, pr_entry)

    diff_cmd = fake_tmux["captured"].get("diff_cmd")
    assert diff_cmd, "new_window_get_pane was not called"

    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not available")

    # bash -n parses without executing; non-zero exit => syntax error.
    result = subprocess.run([bash, "-n", "-c", diff_cmd],
                            capture_output=True, text=True)
    assert result.returncode == 0, (
        f"diff_cmd has shell syntax error for title={title!r}:\n"
        f"  stderr: {result.stderr}\n"
        f"  cmd: {diff_cmd}"
    )


def test_diff_cmd_workdir_with_apostrophe(fake_tmux, tmp_path):
    """A workdir path containing an apostrophe must not break diff_cmd."""
    hostile_workdir = tmp_path / "it's a dir"
    hostile_workdir.mkdir()
    data = _make_data()
    pr_entry = _make_pr("ordinary title", str(hostile_workdir))

    pr_mod._launch_review_window(data, pr_entry)

    diff_cmd = fake_tmux["captured"]["diff_cmd"]
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not available")
    result = subprocess.run([bash, "-n", "-c", diff_cmd],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_logs_warning_when_pane_creation_fails(fake_tmux, monkeypatch):
    """When new_window_get_pane returns None, a diagnostic warning fires."""
    monkeypatch.setattr(pr_mod.tmux_mod, "new_window_get_pane",
                        lambda *a, **k: None)

    fake_log = mock.Mock()
    monkeypatch.setattr(pr_mod, "_log", fake_log)

    data = _make_data()
    pr_entry = _make_pr("Test PR", fake_tmux["workdir"])

    pr_mod._launch_review_window(data, pr_entry)

    fake_log.warning.assert_called()
    msg = fake_log.warning.call_args.args[0]
    assert "new_window_get_pane returned None" in msg
