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
import os
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from pm_core.cli import pr as pr_mod

# The ``fake_tmux`` fixture monkeypatches ``pr_mod.subprocess.run`` — that
# is the global ``subprocess.run`` — so tests that genuinely shell out must
# use this reference captured at import time, or they silently get a Mock.
_real_run = subprocess.run


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


@pytest.mark.parametrize("failure", ["missing-diff", "split-error"])
def test_launch_failure_preserves_live_or_unknown_container(fake_tmux, monkeypatch, failure):
    from pm_core import container
    monkeypatch.setattr(container, "is_container_mode_enabled", lambda: True)
    monkeypatch.setattr(container, "wrap_claude_cmd",
                        lambda *a, **k: ("EXEC", "pm-test-review-pr-001"))
    safe = mock.Mock(return_value=False)
    unsafe = mock.Mock()
    monkeypatch.setattr(container, "discard_unowned_container", safe)
    monkeypatch.setattr(container, "discard_container", unsafe)
    if failure == "missing-diff":
        monkeypatch.setattr(pr_mod.tmux_mod, "new_window_get_pane", lambda *a, **k: None)
    else:
        monkeypatch.setattr(pr_mod.tmux_mod, "split_pane_at",
                            mock.Mock(side_effect=RuntimeError("pane lookup unavailable")))
    pr_mod._launch_review_window(_make_data(), _make_pr("Review", fake_tmux["workdir"]))
    unsafe.assert_not_called()
    assert safe.call_args_list == [mock.call("pm-test-review-pr-001")] * 2


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
    result = _real_run([bash, "-n", "-c", diff_cmd],
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
    result = _real_run([bash, "-n", "-c", diff_cmd],
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


# --- pr-71e9ec7: diff pane must not depend on ``less`` being installed ---

def _git(repo, *args):
    _real_run(["git", "-C", str(repo), *args], check=True,
              capture_output=True, text=True)


@pytest.fixture
def diff_repo(tmp_path):
    """A git repo on ``pm/pr-001`` with one commit ahead of ``origin/master``."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("base\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "update-ref", "refs/remotes/origin/master", "HEAD")
    _git(repo, "checkout", "-qb", "pm/pr-001")
    (repo / "f.txt").write_text("base\nREVIEW_DIFF_MARKER\n")
    _git(repo, "commit", "-qam", "change")
    return repo


def _path_without_less(bin_dir: Path, *, fake_less: bool = False) -> str:
    """Mirror every executable on PATH into *bin_dir* except ``less``.

    With *fake_less*, install a stand-in ``less`` that tags its output so
    the test can tell it was used.
    """
    bin_dir.mkdir()
    for d in os.environ.get("PATH", "").split(":"):
        src = Path(d)
        if not d or not src.is_dir():
            continue
        for entry in src.iterdir():
            dst = bin_dir / entry.name
            if entry.name == "less" or dst.exists() or dst.is_symlink():
                continue
            dst.symlink_to(entry)
    if fake_less:
        less = bin_dir / "less"
        less.write_text("#!/bin/sh\necho FAKE_LESS \"$@\"\ncat\n")
        less.chmod(0o755)
    return str(bin_dir)


def _run_diff_pane(fake_tmux, repo, path):
    """Build diff_cmd for *repo* and run it (minus the trailing interactive
    ``exec $SHELL``) under *path*, returning the CompletedProcess."""
    pr_mod._launch_review_window(_make_data(), _make_pr("Demo PR", str(repo)))
    diff_cmd = fake_tmux["captured"]["diff_cmd"]
    pane_cmd, sep, _ = diff_cmd.rpartition("; exec ")
    assert sep, f"diff_cmd no longer ends in exec $SHELL: {diff_cmd}"
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not available")
    return _real_run([bash, "-c", pane_cmd], capture_output=True, text=True,
                     env={"PATH": path, "HOME": str(repo.parent)})


def test_diff_pane_falls_back_to_cat_without_less(fake_tmux, diff_repo, tmp_path):
    """With no ``less`` on PATH the diff pane must still print the diff
    instead of swallowing it into a failed pager (blank pane)."""
    path = _path_without_less(tmp_path / "bin")
    result = _run_diff_pane(fake_tmux, diff_repo, path)

    assert "less: command not found" not in result.stderr, result.stderr
    assert "=== Review: pr-001" in result.stdout, result.stdout
    assert "--- Full diff ---" in result.stdout
    assert "+REVIEW_DIFF_MARKER" in result.stdout


def test_diff_pane_cat_fallback_pads_before_prompt(fake_tmux, diff_repo, tmp_path):
    """The cat fallback ends with blank rows so a wrapped shell prompt's
    resize redraw (which moves up by its old row count) overwrites padding
    rather than the last diff line."""
    path = _path_without_less(tmp_path / "bin")
    result = _run_diff_pane(fake_tmux, diff_repo, path)

    assert result.stdout.endswith("+REVIEW_DIFF_MARKER\n\n\n"), result.stdout


def test_diff_pane_still_uses_less_when_present(fake_tmux, diff_repo, tmp_path):
    """When ``less`` is available it is still the pager, invoked with -R."""
    path = _path_without_less(tmp_path / "bin", fake_less=True)
    result = _run_diff_pane(fake_tmux, diff_repo, path)

    assert result.stdout.startswith("FAKE_LESS -R\n"), result.stdout
    assert "+REVIEW_DIFF_MARKER" in result.stdout


def test_review_claude_pane_starts_in_pr_workdir(fake_tmux, monkeypatch):
    """pr-b53bfe2: the review Claude pane must start in the PR workdir.

    Without ``cwd`` tmux starts a split in the *calling* process's cwd (the
    TUI's pm dir), so host-mode reviewers ran outside the checkout pm had
    just trusted and sat at Claude's workspace-trust prompt.
    """
    calls = []
    monkeypatch.setattr(pr_mod.tmux_mod, "split_pane_at",
                        lambda *a, **k: calls.append((a, k)) or "%fake-claude-pane")
    pr_mod._launch_review_window(_make_data(),
                                 _make_pr("t", fake_tmux["workdir"]))
    assert calls, "claude pane was never split"
    args, kwargs = calls[0]
    assert args[2] == "fake-claude-cmd"
    assert kwargs.get("cwd") == fake_tmux["workdir"]


# --- pr-24f022e: launch config follows the tmux session, not the cwd ---

def test_review_claude_cmd_uses_tmux_session_tag(fake_tmux, monkeypatch):
    """Run from a PR workdir (picker / prefix+M popup), the cwd's tag names
    no session, so fake-claude / skip-permissions must be looked up under
    the tmux session's tag."""
    seen: list[dict] = []

    def fake_build(**kw):
        seen.append(kw)
        return "fake-claude-cmd"

    monkeypatch.setattr(pr_mod, "build_claude_shell_cmd", fake_build)
    pr_mod._launch_review_window(_make_data(),
                                 _make_pr("t", fake_tmux["workdir"]))
    assert seen and seen[0]["session_tag"] == "test"
