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


class VanillaBackend(Backend):
    def is_merged(self, workdir, branch, base_branch):
        # Fetch latest state from remote
        git_ops.run_git("fetch", "origin", cwd=workdir, check=False)
        result = git_ops.run_git(
            "branch", "-r", "--merged", f"origin/{base_branch}",
            cwd=workdir, check=False,
        )
        if result.returncode != 0:
            return False
        merged = [b.strip() for b in result.stdout.splitlines()]
        return f"origin/{branch}" in merged

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
    "vanilla": VanillaBackend,
    "github": GitHubBackend,
}


def detect_backend(remote_url: str) -> str:
    """Auto-detect backend from remote URL."""
    if not remote_url:
        return "vanilla"
    if "github.com" in remote_url.lower():
        return "github"
    return "vanilla"


def get_backend(data: dict) -> Backend:
    """Get backend instance from project config."""
    name = data.get("project", {}).get("backend", "vanilla")
    cls = _BACKENDS.get(name, VanillaBackend)
    return cls()
