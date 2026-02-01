"""YAML read/write for project.yaml state management."""

import os
import re
from pathlib import Path
from typing import Optional

import yaml


def find_project_root(start: Optional[str] = None) -> Path:
    """Walk up from start (or cwd) to find directory containing project.yaml.

    Looks for pm/project.yaml first (PM dir inside target repo),
    then falls back to project.yaml (standalone PM repo) for backward compat.
    """
    p = Path(start) if start else Path.cwd()
    for d in [p, *p.parents]:
        if (d / "pm" / "project.yaml").exists():
            return d / "pm"
        if (d / "project.yaml").exists():
            return d
    raise FileNotFoundError(
        "No project.yaml found. Either cd into your repo, "
        "use 'pm -C /path/to/pm-dir', or set PM_PROJECT=/path/to/pm-dir"
    )


def is_internal_pm_dir(root: Path) -> bool:
    """Check if the PM dir is inside a target repo (pm/ subdir) vs standalone."""
    return root.name == "pm" and (root.parent / ".git").exists()


def load(root: Optional[Path] = None) -> dict:
    """Load project.yaml from root directory."""
    if root is None:
        root = find_project_root()
    path = root / "project.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def save(data: dict, root: Optional[Path] = None) -> None:
    """Write project.yaml to root directory."""
    if root is None:
        root = find_project_root()
    path = root / "project.yaml"
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def next_plan_id(data: dict) -> str:
    """Generate next plan-NNN id."""
    plans = data.get("plans") or []
    if not plans:
        return "plan-001"
    nums = []
    for p in plans:
        m = re.match(r"plan-(\d+)", p["id"])
        if m:
            nums.append(int(m.group(1)))
    return f"plan-{max(nums) + 1:03d}"


def next_pr_id(data: dict) -> str:
    """Generate next pr-NNN id."""
    prs = data.get("prs") or []
    if not prs:
        return "pr-001"
    nums = []
    for p in prs:
        m = re.match(r"pr-(\d+)", p["id"])
        if m:
            nums.append(int(m.group(1)))
    return f"pr-{max(nums) + 1:03d}"


def get_pr(data: dict, pr_id: str) -> Optional[dict]:
    """Get a PR entry by id."""
    for pr in data.get("prs") or []:
        if pr["id"] == pr_id:
            return pr
    return None


def get_plan(data: dict, plan_id: str) -> Optional[dict]:
    """Get a plan entry by id."""
    for plan in data.get("plans") or []:
        if plan["id"] == plan_id:
            return plan
    return None


def slugify(text: str) -> str:
    """Convert text to branch-name-safe slug."""
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:50]


def init_project(root: Path, name: str, repo: str, base_branch: str = "main",
                  backend: str = "vanilla") -> dict:
    """Create initial project.yaml in a new PM repo.

    The PM repo is separate from the target codebase repo.
    It contains only project.yaml and plans/ — the source of truth
    for project state, owned by PMs. Contributors interact via
    issues or in person, never touching this repo directly.
    """
    data = {
        "project": {
            "name": name,
            "repo": repo,
            "base_branch": base_branch,
            "backend": backend,
        },
        "plans": [],
        "prs": [],
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "plans").mkdir(exist_ok=True)
    save(data, root)
    return data
