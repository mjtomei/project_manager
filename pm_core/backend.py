"""Pluggable git hosting backends.

pm needs exactly two things from a hosting backend:
  1. Check if a branch has been merged into base
  2. Generate instructions for Claude on how to finalize a PR

The vanilla backend uses only git. The github backend uses the gh CLI.
New backends (gitea, gitlab, etc.) can be added by subclassing Backend.
"""

from abc import ABC, abstractmethod

from pm_core import git_ops


class Backend(ABC):
    @abstractmethod
    def is_merged(self, workdir: str, branch: str, base_branch: str) -> bool:
        """Check if branch has been merged into base_branch."""
        ...

    @abstractmethod
    def pr_instructions(self, branch: str, title: str, base_branch: str, pr_id: str) -> str:
        """Return instructions for Claude on how to finalize work."""
        ...


class LocalBackend(Backend):
    """Local-only git, no remote. Merge detection uses local refs only."""

    def is_merged(self, workdir, branch, base_branch):
        exists = git_ops.run_git(
            "rev-parse", "--verify", branch, cwd=workdir, check=False,
        )
        if exists.returncode != 0:
            return False
        result = git_ops.run_git(
            "merge-base", "--is-ancestor", branch, base_branch,
            cwd=workdir, check=False,
        )
        return result.returncode == 0

    def pr_instructions(self, branch, title, base_branch, pr_id):
        return (
            f"- Work in the current directory (already on branch {branch})\n"
            f"- When done, commit your changes\n"
            f"- Then tell the human you're done so they can run: pm pr done {pr_id}"
        )


class VanillaBackend(Backend):
    """Vanilla git with a remote. Fetches from origin for merge detection."""

    def is_merged(self, workdir, branch, base_branch):
        git_ops.run_git("fetch", "origin", cwd=workdir, check=False)
        for ref in (branch, f"origin/{branch}"):
            exists = git_ops.run_git(
                "rev-parse", "--verify", ref, cwd=workdir, check=False,
            )
            if exists.returncode != 0:
                continue
            result = git_ops.run_git(
                "merge-base", "--is-ancestor", ref, base_branch,
                cwd=workdir, check=False,
            )
            if result.returncode == 0:
                return True
        return False

    def pr_instructions(self, branch, title, base_branch, pr_id):
        return (
            f"- Work in the current directory (already on branch {branch})\n"
            f"- When done, commit and push your changes:\n"
            f"    git push -u origin {branch}\n"
            f"- Then tell the human you're done so they can run: pm pr done {pr_id}"
        )


class GitHubBackend(Backend):
    def is_merged(self, workdir, branch, base_branch):
        from pm_core import gh_ops
        return gh_ops.is_pr_merged(workdir, branch)

    def pr_instructions(self, branch, title, base_branch, pr_id):
        return (
            f"- Work in the current directory (already on branch {branch})\n"
            f"- When done, commit your changes, push the branch, and create a PR:\n"
            f"    git push -u origin {branch}\n"
            f"    gh pr create --title \"{title}\" --base {base_branch}\n"
            f"- Then tell the human you're done so they can run: pm pr done {pr_id}"
        )


_BACKENDS = {
    "local": LocalBackend,
    "vanilla": VanillaBackend,
    "github": GitHubBackend,
}


def detect_backend(remote_url: str) -> str:
    """Auto-detect backend from remote URL.

    Returns 'local' for local paths, 'github' for github.com URLs,
    'vanilla' for other remote URLs.
    """
    if not remote_url:
        return "local"
    # Check for remote URL patterns first
    if "github.com" in remote_url.lower():
        return "github"
    if "://" in remote_url or remote_url.startswith("git@"):
        return "vanilla"
    # Local paths (absolute, relative, or . )
    from pathlib import Path
    if Path(remote_url).exists():
        return "local"
    return "vanilla"


def get_backend(data: dict) -> Backend:
    """Get backend instance from project config."""
    name = data.get("project", {}).get("backend", "vanilla")
    cls = _BACKENDS.get(name, VanillaBackend)
    return cls()
