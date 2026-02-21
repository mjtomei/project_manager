"""Git clone, branch, push, pull operations."""

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from pm_core.paths import log_shell_command


def get_git_root(start_path: Path | None = None) -> Path | None:
    """Find the git repository root from the given path or cwd.

    Walks up the directory tree looking for .git directory.
    """
    path = start_path or Path.cwd()
    path = path.resolve()

    while path != path.parent:
        if (path / ".git").exists():
            return path
        path = path.parent

    # Check root directory too
    if (path / ".git").exists():
        return path
    return None


def get_github_repo_name(git_root: Path) -> str | None:
    """Extract GitHub repo name (without org/user) from git remote.

    Returns None if not a GitHub repo or can't determine name.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=git_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None

        url = result.stdout.strip()
        # Handle various GitHub URL formats:
        # https://github.com/user/repo.git
        # git@github.com:user/repo.git
        # https://github.com/user/repo
        if "github.com" not in url:
            return None

        # Extract repo name from URL
        if url.endswith(".git"):
            url = url[:-4]

        # Get the last path component (repo name)
        repo_name = url.rstrip("/").split("/")[-1]
        # Also handle git@github.com:user/repo format
        if ":" in repo_name:
            repo_name = repo_name.split(":")[-1].split("/")[-1]

        return repo_name if repo_name else None
    except (subprocess.SubprocessError, OSError):
        return None


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
    """Run a git command and return result.

    Logs to TUI log file if running under TUI.
    """
    cmd = ["git", *args]
    log_shell_command(cmd, prefix="git")
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )
    if result.returncode != 0:
        log_shell_command(cmd, prefix="git", returncode=result.returncode)
    return result


def clone(repo_url: str, dest: Path, branch: Optional[str] = None) -> None:
    """Clone a repo to dest.

    Falls back to cloning without --branch if the branch doesn't exist
    (e.g. empty repos or repos where the default branch differs).
    """
    args = ["clone", repo_url, str(dest)]
    if branch:
        args.extend(["--branch", branch])
    result = run_git(*args, check=False)
    if result.returncode != 0:
        if not branch:
            # No fallback available — propagate the error
            run_git(*args)
        # Clean up partial clone directory before retrying
        import shutil
        if dest.exists():
            shutil.rmtree(dest)
        # Retry without --branch (handles empty repos, wrong default branch)
        run_git("clone", repo_url, str(dest))


def checkout_branch(workdir: Path, branch: str, create: bool = False) -> None:
    """Checkout or create a branch.

    Handles repos with no remote (local backend) and empty repos
    gracefully by falling back to local branch operations.
    """
    if create:
        # Check if branch exists locally first
        local_check = run_git("rev-parse", "--verify", branch, cwd=workdir, check=False)
        if local_check.returncode == 0:
            run_git("checkout", branch, cwd=workdir)
            return
        # Check if branch exists on remote (may fail if no remote)
        result = run_git("ls-remote", "--heads", "origin", branch, cwd=workdir, check=False)
        if result.returncode == 0 and result.stdout.strip():
            run_git("fetch", "origin", branch, cwd=workdir)
            run_git("checkout", branch, cwd=workdir)
        else:
            # Create new local branch; use --orphan for empty repos
            create_result = run_git("checkout", "-b", branch, cwd=workdir, check=False)
            if create_result.returncode != 0:
                # May fail if HEAD is invalid (empty repo) — try orphan branch
                run_git("checkout", "--orphan", branch, cwd=workdir, check=False)
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

    if backend == "github":
        # Push and create PR
        push_result = run_git("push", "-u", "origin", branch_name, cwd=repo_root, check=False)
        if push_result.returncode != 0:
            result_info["error"] = f"Push failed: {push_result.stderr.strip()}"
            _checkout_and_restore_pm(repo_root, original_branch, branch_name, add_path)
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

        _checkout_and_restore_pm(repo_root, original_branch, branch_name, add_path)
        pull_rebase(repo_root)

    elif backend == "vanilla":
        # vanilla: push to remote, no PR creation
        push_result = run_git("push", "-u", "origin", branch_name, cwd=repo_root, check=False)
        if push_result.returncode != 0:
            result_info["push_error"] = push_result.stderr.strip()
        _checkout_and_restore_pm(repo_root, original_branch, branch_name, add_path)

    else:
        # local: no push, just leave the commit on the branch
        _checkout_and_restore_pm(repo_root, original_branch, branch_name, add_path)

    return result_info


def _checkout_and_restore_pm(repo_root: Path, original_branch: str, sync_branch: str, add_path: str) -> None:
    """Switch back to original branch and restore pm files from the sync branch.

    When pm/ files are only tracked on the sync branch, checking out the
    original branch removes them from the working tree. We restore them
    so the user can keep working.
    """
    run_git("checkout", original_branch, cwd=repo_root, check=False)
    # Restore pm files from the sync branch into the working tree
    run_git("checkout", sync_branch, "--", add_path, cwd=repo_root, check=False)


def list_remotes(path: Path) -> dict[str, str]:
    """List all git remotes and their URLs.

    Returns a dict mapping remote name to URL (e.g., {'origin': 'git@github.com:...'}).
    Returns empty dict if not a git repo or no remotes exist.
    """
    if not is_git_repo(path):
        return {}

    result = run_git("remote", "-v", cwd=path, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return {}

    remotes = {}
    for line in result.stdout.strip().split("\n"):
        # Format: "origin\tgit@github.com:org/repo.git (fetch)"
        parts = line.split()
        if len(parts) >= 2 and "(fetch)" in line:
            name = parts[0]
            url = parts[1]
            remotes[name] = url
    return remotes


def select_remote(
    remotes: dict[str, str],
    preferred_backend: Optional[str] = None,
) -> dict:
    """Select the best remote from a dict of remotes.

    Selection logic:
    1. If no remotes, return {"selected": None}
    2. If only one remote, return {"selected": (name, url)}
    3. If 'origin' exists and matches preferred_backend (or no preference), prefer it
    4. If any remote matches preferred_backend, prefer the first match
    5. If 'origin' exists, prefer it
    6. Otherwise, return {"ambiguous": [(name, url), ...]} for user selection

    Args:
        remotes: Dict mapping remote name to URL
        preferred_backend: Optional backend to prefer ('github', 'vanilla', 'local')

    Returns:
        Dict with either "selected" key (name, url) tuple or None,
        or "ambiguous" key with list of (name, url) tuples
    """
    if not remotes:
        return {"selected": None}

    # Single remote - easy choice
    if len(remotes) == 1:
        name, url = list(remotes.items())[0]
        return {"selected": (name, url)}

    # Import here to avoid circular import
    from pm_core.backend import detect_backend

    def matches_backend(url: str, backend: str) -> bool:
        """Check if URL matches the preferred backend."""
        if backend == "github":
            return "github.com" in url.lower()
        elif backend == "vanilla":
            # Any remote URL (not local path): known remote protocols or SSH-style URL
            lower_url = url.lower()
            return (
                lower_url.startswith(("http://", "https://", "git://", "ssh://"))
                or url.startswith("git@")
            )
        return True  # 'local' or None matches anything

    # Check if 'origin' exists and matches preferred backend
    if "origin" in remotes:
        origin_url = remotes["origin"]
        if preferred_backend is None or matches_backend(origin_url, preferred_backend):
            return {"selected": ("origin", origin_url)}

    # Look for remotes matching preferred backend
    if preferred_backend:
        matching = [
            (name, url) for name, url in remotes.items()
            if matches_backend(url, preferred_backend)
        ]
        if len(matching) == 1:
            return {"selected": matching[0]}
        if matching:
            # Multiple matches - still ambiguous
            return {"ambiguous": matching}

    # Fall back to origin if it exists (even if backend doesn't match)
    if "origin" in remotes:
        return {"selected": ("origin", remotes["origin"])}

    # Multiple remotes, no clear winner
    return {"ambiguous": list(remotes.items())}
