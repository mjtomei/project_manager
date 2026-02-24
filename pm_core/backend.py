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
    def pr_instructions(self, branch: str, title: str, base_branch: str, pr_id: str,
                        gh_pr_url: str | None = None) -> str:
        """Return instructions for Claude on how to finalize work.

        Args:
            branch: The feature branch name
            title: PR title
            base_branch: Target branch (e.g., main)
            pr_id: PM's internal PR ID (e.g., pr-001)
            gh_pr_url: GitHub PR URL if a draft PR was already created
        """
        ...


class LocalBackend(Backend):
    """Local-only git, no remote.

    Merge detection is not automatic — ``is_merged()`` always returns False.
    Use ``pm pr merge`` to merge and mark PRs as merged.
    """

    def is_merged(self, workdir, branch, base_branch):
        # Local backend cannot reliably detect merges via git plumbing
        # (merge-base --is-ancestor gives false positives for rebases).
        # Merges are tracked explicitly via `pm pr merge`.
        return False

    def pr_instructions(self, branch, title, base_branch, pr_id, gh_pr_url=None):
        return (
            f"- You're on branch `{branch}`\n"
            f"- Commit as you go\n"
            f"- When ready for review: press `d` in the TUI or run `pm pr review {pr_id}` from the base pm directory (not from this workdir)\n"
            f"- To merge: run `pm pr merge {pr_id}` from the base pm directory"
        )


class VanillaBackend(Backend):
    """Vanilla git with a remote (non-GitHub).

    Merge detection is not automatic — ``is_merged()`` always returns False.
    Use ``pm pr merge`` to merge and mark PRs as merged.
    """

    def is_merged(self, workdir, branch, base_branch):
        # Vanilla backend cannot reliably detect merges via git plumbing
        # (merge-base --is-ancestor gives false positives for rebases).
        # Merges are tracked explicitly via `pm pr merge`.
        return False

    def pr_instructions(self, branch, title, base_branch, pr_id, gh_pr_url=None):
        return (
            f"- You're on branch `{branch}`\n"
            f"- Commit and push as you go: `git push origin {branch}`\n"
            f"- When ready for review: press `d` in the TUI or run `pm pr review {pr_id}` from the base pm directory (not from this workdir)\n"
            f"- To merge: run `pm pr merge {pr_id}` from the base pm directory"
        )


class GitHubBackend(Backend):
    def is_merged(self, workdir, branch, base_branch):
        from pm_core import gh_ops
        return gh_ops.is_pr_merged(workdir, branch)

    def pr_instructions(self, branch, title, base_branch, pr_id, gh_pr_url=None):
        if gh_pr_url:
            # Draft PR already exists - just push commits
            return (
                f"- You're on branch `{branch}` with a draft PR: {gh_pr_url}\n"
                f"- Commit and push as you go: `git push origin {branch}`\n"
                f"- When ready for review: press `d` in the TUI or run `pm pr review {pr_id}` from the base pm directory (not from this workdir)"
            )
        # Fallback for when draft PR wasn't created (e.g., push failed)
        return (
            f"- You're on branch `{branch}`\n"
            f"- Commit and push as you go: `git push -u origin {branch}`\n"
            f"- Create a PR when ready: `gh pr create --title \"{title}\" --base {base_branch}`\n"
            f"- Then mark it done: press `d` in the TUI or run `pm pr review {pr_id}` from the base pm directory (not from this workdir)"
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
