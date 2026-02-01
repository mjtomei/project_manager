"""GitHub CLI wrapper for PR operations."""

import json
import shutil
import subprocess
import sys
from typing import Optional


def _check_gh():
    """Check that gh CLI is installed and authenticated. Exit with guidance if not."""
    if not shutil.which("gh"):
        print(
            "Error: The github backend requires the GitHub CLI (gh).\n"
            "Install it: https://cli.github.com\n"
            "Or use --backend vanilla when running pm init.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    result = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            "Error: gh CLI is not authenticated.\n"
            "Run: gh auth login\n"
            "Or use --backend vanilla when running pm init.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def run_gh(*args: str, cwd: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a gh CLI command."""
    _check_gh()
    return subprocess.run(
        ["gh", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def create_pr(workdir: str, title: str, base: str, body: str = "") -> Optional[str]:
    """Create a GitHub PR, return URL."""
    result = run_gh(
        "pr", "create",
        "--title", title,
        "--base", base,
        "--body", body,
        cwd=workdir,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def get_pr_status(workdir: str, branch: str) -> Optional[dict]:
    """Get PR status for a branch. Returns dict with state, url, etc."""
    result = run_gh(
        "pr", "view", branch,
        "--json", "state,url,number,title,mergedAt",
        cwd=workdir,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return json.loads(result.stdout)
    return None


def is_pr_merged(workdir: str, branch: str) -> bool:
    """Check if a PR for this branch is merged."""
    info = get_pr_status(workdir, branch)
    if info:
        return info.get("state") == "MERGED"
    return False


def list_prs(workdir: str, state: str = "open") -> list[dict]:
    """List PRs for the repo."""
    result = run_gh(
        "pr", "list",
        "--state", state,
        "--json", "number,title,headRefName,state,url",
        cwd=workdir,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return json.loads(result.stdout)
    return []
