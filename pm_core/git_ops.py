"""Git clone, branch, push, pull operations."""

import os
import subprocess
from pathlib import Path
from typing import Optional


def is_git_repo(path: Path) -> bool:
    """Check if path is inside a git repository."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def run_git(*args: str, cwd: Optional[str | Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command and return result."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def clone(repo_url: str, dest: Path, branch: Optional[str] = None) -> None:
    """Clone a repo to dest."""
    args = ["clone", repo_url, str(dest)]
    if branch:
        args.extend(["--branch", branch])
    run_git(*args)


def checkout_branch(workdir: Path, branch: str, create: bool = False) -> None:
    """Checkout or create a branch."""
    if create:
        # Check if branch exists on remote first
        result = run_git("ls-remote", "--heads", "origin", branch, cwd=workdir, check=False)
        if result.stdout.strip():
            run_git("fetch", "origin", branch, cwd=workdir)
            run_git("checkout", branch, cwd=workdir)
        else:
            run_git("checkout", "-b", branch, cwd=workdir)
    else:
        run_git("checkout", branch, cwd=workdir)


def pull_rebase(workdir: Path) -> subprocess.CompletedProcess:
    """Pull with rebase."""
    return run_git("pull", "--rebase", cwd=workdir, check=False)


def commit_and_push(workdir: Path, message: str, files: Optional[list[str]] = None) -> None:
    """Stage files, commit, and push."""
    if files:
        for f in files:
            run_git("add", f, cwd=workdir)
    else:
        run_git("add", "-A", cwd=workdir)
    # Check if there are changes to commit
    result = run_git("diff", "--cached", "--quiet", cwd=workdir, check=False)
    if result.returncode != 0:
        run_git("commit", "-m", message, cwd=workdir)
        run_git("push", cwd=workdir, check=False)


def sync_state(state_root: Path) -> str:
    """Pull latest state, return status string."""
    if not is_git_repo(state_root):
        return "no-git"
    result = pull_rebase(state_root)
    if result.returncode == 0:
        return "synced"
    return f"conflict: {result.stderr.strip()}"


def auto_commit_state(state_root: Path, message: str = "pm: update state") -> None:
    """Commit and push PM repo state after mutations. No-op if not a git repo.

    Commits project.yaml and plans/ — everything in the PM repo.
    """
    if not is_git_repo(state_root):
        return
    commit_and_push(state_root, message, files=["project.yaml", "plans/"])
