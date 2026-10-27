"""Host-side git in a container-writable workdir must not run its hooks.

A PR workdir is bind-mounted read-write into containers, so ``.git/hooks/*``
is container-authored code.  Any host-side pm git command that runs a hook
from that directory (``merge``, ``push``, ``commit``, ``checkout``,
``pull``) would execute it with the host user's credentials — the same
sandbox escape the push proxy blocks for container-initiated git.  pm's own
operations pass ``no_hooks=True`` (``-c core.hooksPath=/dev/null``).

The merge and push stories are real-git tests: the planted hook writes a
marker, so a regression makes the marker appear.  They only ever talk to
local repositories under ``tmp_path`` (pushes target an absolute bare-repo
path, never a named or network remote) and run the real ``git`` binary with
an isolated environment: inside a pm container the ``git`` on PATH is the
push-proxy wrapper, which would forward the test's pushes to the live host
proxy.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from pm_core import git_ops, integration
from pm_core.cli import pr as pr_mod

PR = "pr-001"
BRANCH = "feature"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(cwd: Path, name: str, text: str, msg: str) -> str:
    (cwd / name).write_text(text)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", msg)
    return git(cwd, "rev-parse", "HEAD")


def plant_hook(repo: Path, name: str, marker: Path) -> None:
    """Install an executable hook that records that it ran."""
    hook = repo / ".git" / "hooks" / name
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)


_REAL_GIT_DIRS = ("/usr/bin", "/bin", "/usr/local/bin")


def _is_real_git(path: str) -> bool:
    """False for pm's in-container push-proxy wrapper (a shell script)."""
    try:
        with open(path, "rb") as stream:
            return b"git wrapper" not in stream.read(256)
    except OSError:
        return False


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    real = next((d for d in _REAL_GIT_DIRS
                 if _is_real_git(os.path.join(d, "git"))), None)
    if real is None:
        pytest.skip("no real git binary; refusing to use a proxy wrapper")
    monkeypatch.setenv("PATH", f"{real}:/usr/bin:/bin")
    assert _is_real_git(shutil.which("git") or "")
    # Never inherit a repository binding or the user's git configuration.
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(k, v)
    yield


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "master")
    return path


# ---------------------------------------------------------------------------
# run_git / helper plumbing
# ---------------------------------------------------------------------------

class TestRunGitNoHooks:
    @mock.patch("pm_core.git_ops.subprocess.run")
    @mock.patch("pm_core.git_ops.log_shell_command")
    def test_no_hooks_prepends_the_flag(self, _log, run):
        run.return_value = mock.MagicMock(returncode=0)
        git_ops.run_git("push", "origin", no_hooks=True)
        assert run.call_args[0][0] == [
            "git", "-c", "core.hooksPath=/dev/null", "push", "origin"]

    @mock.patch("pm_core.git_ops.subprocess.run")
    @mock.patch("pm_core.git_ops.log_shell_command")
    def test_default_keeps_the_command_unchanged(self, _log, run):
        run.return_value = mock.MagicMock(returncode=0)
        git_ops.run_git("status")
        assert run.call_args[0][0] == ["git", "status"]

    @mock.patch("pm_core.git_ops.run_git")
    def test_checkout_branch_forwards_no_hooks(self, run):
        run.return_value = mock.MagicMock(returncode=0)
        git_ops.checkout_branch(Path("/tmp/wd"), "b", create=True, no_hooks=True)
        assert run.call_args_list
        assert all(c.kwargs.get("no_hooks") is True for c in run.call_args_list)

    @mock.patch("pm_core.git_ops.run_git")
    def test_pull_rebase_forwards_no_hooks(self, run):
        run.return_value = mock.MagicMock(returncode=0)
        git_ops.pull_rebase(Path("/tmp/wd"), no_hooks=True)
        assert run.call_args.kwargs["no_hooks"] is True

    def test_qa_planner_handoff_git_capture_no_hooks(self, monkeypatch, tmp_path):
        """The planner hand-off pushes from the container-writable PR workdir."""
        from pm_core import qa_loop
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(qa_loop.subprocess, "run", fake_run)
        qa_loop._git_capture(tmp_path, "push", "origin", "ref", no_hooks=True)
        assert seen["cmd"] == ["git", "-c", "core.hooksPath=/dev/null",
                               "push", "origin", "ref"]


# ---------------------------------------------------------------------------
# Real-git stories
# ---------------------------------------------------------------------------

class TestWorkdirHooksDoNotRun:
    def test_apply_integration_merge_skips_workdir_hooks(self, tmp_path):
        repo = _repo(tmp_path / "wd")
        commit(repo, "a.txt", "a", "base")
        git(repo, "checkout", "-q", "-b", BRANCH)
        head = commit(repo, "b.txt", "b", "branch work")
        git(repo, "checkout", "-q", "master")
        base_sha = commit(repo, "c.txt", "c", "base moved")
        git(repo, "checkout", "-q", BRANCH)

        marker = tmp_path / "hook-ran"
        plant_hook(repo, "post-merge", marker)
        plant_hook(repo, "pre-merge-commit", marker)

        data = {"project": {"name": "p", "base_branch": "master"},
                "prs": [{"id": PR, "branch": BRANCH, "workdir": str(repo)}],
                "plans": []}
        record = {"status": integration.CLEAN, "head": head,
                  "base_sha": base_sha, "base_branch": "master",
                  "candidate_tree": None}

        merged, reason = integration.apply_integration(
            tmp_path, PR, record, data=data)

        assert reason is None, reason
        assert merged == git(repo, "rev-parse", "HEAD")
        assert git(repo, "rev-parse", "HEAD^1") == head
        assert git(repo, "rev-parse", "HEAD^2") == base_sha
        assert not marker.exists(), (
            "the container-writable workdir's merge hooks ran on the host")

    def test_publish_vanilla_push_skips_workdir_hooks(self, tmp_path):
        remote = tmp_path / "target.git"
        git(tmp_path, "init", "-q", "--bare", str(remote))
        wd = _repo(tmp_path / "wd")
        base_sha = commit(wd, "a.txt", "a", "base")
        # An absolute local path: never a named remote the git on PATH could
        # resolve elsewhere.
        git(wd, "push", "-q", str(remote), "master:refs/heads/master")
        merge_sha = commit(wd, "b.txt", "b", "merged work")

        marker = tmp_path / "hook-ran"
        plant_hook(wd, "pre-push", marker)

        pr_mod._publish_vanilla(tmp_path, {"id": PR}, str(wd), str(remote),
                                "master", base_sha, merge_sha)

        assert git(remote, "rev-parse", "refs/heads/master") == merge_sha
        assert not marker.exists(), (
            "the container-writable workdir's pre-push hook ran on the host")
