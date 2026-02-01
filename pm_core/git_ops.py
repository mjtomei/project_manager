"""Git clone, branch, push, pull operations."""

import os
import subprocess
from datetime import datetime
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
    """No-op. Retained for backward compatibility.

    Previously pulled latest state from git. Now state is managed
    via 'pm push' explicitly.
    """
    return "no-op"


def auto_commit_state(state_root: Path, message: str = "pm: update state") -> None:
    """No-op. Retained for backward compatibility.

    Previously auto-committed PM state. Now use 'pm push' to commit and share.
    """
    return


def push_pm_branch(pm_root: Path, backend: str = "vanilla") -> dict:
    """Create a branch with pm/ changes, commit, and optionally push + create PR.

    Works for both internal (pm/ inside repo) and external PM dirs.
    Returns dict with 'branch', 'pr_url' (if github backend), 'error' keys.

    Backend behavior:
      local:   commit on branch locally, no push
      vanilla: commit on branch, push to remote
      github:  commit on branch, push, create PR via gh
    """
    from pm_core.store import is_internal_pm_dir

    internal = is_internal_pm_dir(pm_root)
    # For internal pm dirs, the git repo root is the parent
    # For external pm dirs, the git repo root is pm_root itself
    if internal:
        repo_root = pm_root.parent
        add_path = "pm/"
    else:
        repo_root = pm_root
        add_path = "."

    if not is_git_repo(repo_root):
        return {"error": f"Not a git repo: {repo_root}"}

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    branch_name = f"pm/sync-{timestamp}"

    # Remember current branch
    result = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_root, check=False)
    if result.returncode != 0:
        return {"error": f"Failed to detect current branch: {result.stderr.strip()}"}
    original_branch = result.stdout.strip()

    # Stage pm changes
    run_git("add", add_path, cwd=repo_root, check=False)
    diff_result = run_git("diff", "--cached", "--quiet", cwd=repo_root, check=False)
    if diff_result.returncode == 0:
        # Nothing staged — check for untracked files
        status = run_git("status", "--porcelain", add_path, cwd=repo_root, check=False)
        if not status.stdout.strip():
            return {"error": "No pm changes to push."}
        run_git("add", add_path, cwd=repo_root, check=False)

    # Create branch and commit
    run_git("checkout", "-b", branch_name, cwd=repo_root, check=True)
    run_git("commit", "-m", "pm: update project state", cwd=repo_root, check=True)

    result_info = {"branch": branch_name, "original_branch": original_branch}

    if backend == "local":
        # Local only — no push, just leave branch
        run_git("checkout", original_branch, cwd=repo_root, check=False)

    elif backend == "github":
        # Push and create PR
        push_result = run_git("push", "-u", "origin", branch_name, cwd=repo_root, check=False)
        if push_result.returncode != 0:
            result_info["error"] = f"Push failed: {push_result.stderr.strip()}"
            run_git("checkout", original_branch, cwd=repo_root, check=False)
            return result_info

        import subprocess as sp
        pr_result = sp.run(
            ["gh", "pr", "create",
             "--title", "pm: update project state",
             "--body", "Automated pm state sync.",
             "--head", branch_name],
            cwd=repo_root, capture_output=True, text=True,
        )
        if pr_result.returncode == 0:
            result_info["pr_url"] = pr_result.stdout.strip()
        else:
            result_info["pr_error"] = pr_result.stderr.strip()

        run_git("checkout", original_branch, cwd=repo_root, check=False)
        pull_rebase(repo_root)

    else:
        # vanilla: push to remote, no PR creation
        push_result = run_git("push", "-u", "origin", branch_name, cwd=repo_root, check=False)
        if push_result.returncode != 0:
            result_info["push_error"] = push_result.stderr.strip()
        run_git("checkout", original_branch, cwd=repo_root, check=False)

    return result_info
