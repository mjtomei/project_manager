"""Sync pm/ state across clones by fetching from remote and merging."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from pm_core import git_ops, store

_log = logging.getLogger("pm.pm_sync")

# Minimum interval between remote fetches (seconds)
MIN_PM_SYNC_INTERVAL = 30

# Status progression for merge conflict resolution
_STATUS_ORDER = {
    "pending": 0,
    "in_progress": 1,
    "in_review": 2,
    "merged": 3,
    "closed": 4,  # closed always wins
}


def _should_sync(data: dict, force: bool = False) -> bool:
    """Check if enough time has passed since the last pm sync."""
    if force:
        return True
    ts_str = data.get("project", {}).get("last_pm_sync")
    if not ts_str:
        return True
    try:
        last_sync = datetime.fromisoformat(ts_str)
        if last_sync.tzinfo is None:
            last_sync = last_sync.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last_sync).total_seconds()
        return elapsed >= MIN_PM_SYNC_INTERVAL
    except (ValueError, TypeError):
        return True


def _set_sync_timestamp(data: dict) -> None:
    """Record when the last pm sync happened."""
    if "project" not in data:
        data["project"] = {}
    data["project"]["last_pm_sync"] = datetime.now(timezone.utc).isoformat()


def fetch_remote_state(pm_root: Path, data: dict) -> Optional[dict]:
    """Fetch project.yaml from the remote base branch without modifying the working tree.

    Returns parsed dict, or None on any failure.
    """
    internal = store.is_internal_pm_dir(pm_root)
    repo_root = pm_root.parent if internal else pm_root
    base_branch = data.get("project", {}).get("base_branch", "main")
    backend = data.get("project", {}).get("backend", "vanilla")

    # Determine the ref and file path to read
    if internal:
        yaml_path = "pm/project.yaml"
    else:
        yaml_path = "project.yaml"

    if backend == "local":
        # No remote — read from the local base branch
        ref = base_branch
    else:
        # Fetch latest from remote first
        fetch_result = git_ops.run_git(
            "fetch", "origin", base_branch,
            cwd=repo_root, check=False,
        )
        if fetch_result.returncode != 0:
            _log.debug("git fetch failed: %s", fetch_result.stderr.strip())
            # Try reading stale ref anyway — better than nothing
        ref = f"origin/{base_branch}"

    # Read file content from the ref
    result = git_ops.run_git(
        "show", f"{ref}:{yaml_path}",
        cwd=repo_root, check=False,
    )
    if result.returncode != 0:
        _log.debug("git show %s:%s failed: %s", ref, yaml_path, result.stderr.strip())
        return None

    try:
        parsed = yaml.safe_load(result.stdout)
        if not isinstance(parsed, dict):
            _log.debug("Remote project.yaml is not a dict: %s", type(parsed))
            return None
        return parsed
    except yaml.YAMLError as e:
        _log.warning("Failed to parse remote project.yaml: %s", e)
        return None


def _merge_field(local_val, remote_val, prefer: str = "local"):
    """Merge a single field, preferring non-None values."""
    if prefer == "remote":
        return remote_val if remote_val is not None else local_val
    return local_val if local_val is not None else remote_val


def _higher_status(a: str, b: str) -> str:
    """Return the more-advanced status between a and b."""
    return a if _STATUS_ORDER.get(a, 0) >= _STATUS_ORDER.get(b, 0) else b


def _merge_pr(local_pr: dict, remote_pr: dict) -> dict:
    """Merge two versions of the same PR entry (same id)."""
    merged = dict(remote_pr)  # start with remote as base

    # Status: prefer more advanced
    merged["status"] = _higher_status(
        local_pr.get("status", "pending"),
        remote_pr.get("status", "pending"),
    )

    # Local-machine-specific fields: prefer local
    for field in ("workdir", "agent_machine"):
        merged[field] = _merge_field(
            local_pr.get(field), remote_pr.get(field), prefer="local"
        )

    # GitHub fields: prefer non-None
    for field in ("gh_pr", "gh_pr_number"):
        merged[field] = _merge_field(
            local_pr.get(field), remote_pr.get(field), prefer="remote"
        )

    # depends_on: union of both lists
    local_deps = set(local_pr.get("depends_on") or [])
    remote_deps = set(remote_pr.get("depends_on") or [])
    merged["depends_on"] = sorted(local_deps | remote_deps)

    return merged


def _merge_plan(local_plan: dict, remote_plan: dict) -> dict:
    """Merge two versions of the same plan entry (same id)."""
    merged = dict(remote_plan)  # prefer remote for canonical fields
    # Prefer local for status if it's more advanced (e.g., user marked accepted)
    local_status = local_plan.get("status", "draft")
    remote_status = remote_plan.get("status", "draft")
    plan_order = {"draft": 0, "in_progress": 1, "in_review": 2, "accepted": 3, "rejected": 4}
    if plan_order.get(local_status, 0) > plan_order.get(remote_status, 0):
        merged["status"] = local_status
    return merged


def merge_project_data(local: dict, remote: dict) -> dict:
    """Merge local and remote project.yaml data.

    Strategy:
    - PRs: union by id, merge shared entries field-by-field
    - Plans: union by id, merge shared entries
    - Project metadata: per-field preferences
    """
    merged = {}

    # --- Project metadata ---
    local_proj = local.get("project", {})
    remote_proj = remote.get("project", {})
    merged_proj = dict(remote_proj)  # remote is canonical for most fields

    # Local-preference fields
    for field in ("active_pr", "guide_deps_reviewed", "last_pm_sync"):
        if field in local_proj:
            merged_proj[field] = local_proj[field]

    # Timestamp fields: prefer more recent
    for field in ("last_pr_sync",):
        local_ts = local_proj.get(field)
        remote_ts = remote_proj.get(field)
        if local_ts and remote_ts:
            try:
                if datetime.fromisoformat(local_ts) > datetime.fromisoformat(remote_ts):
                    merged_proj[field] = local_ts
                else:
                    merged_proj[field] = remote_ts
            except (ValueError, TypeError):
                merged_proj[field] = local_ts or remote_ts
        else:
            merged_proj[field] = local_ts or remote_ts

    merged["project"] = merged_proj

    # --- Plans ---
    local_plans = {p["id"]: p for p in (local.get("plans") or [])}
    remote_plans = {p["id"]: p for p in (remote.get("plans") or [])}
    all_plan_ids = list(dict.fromkeys(
        list(remote_plans.keys()) + list(local_plans.keys())
    ))
    merged_plans = []
    for pid in all_plan_ids:
        if pid in local_plans and pid in remote_plans:
            merged_plans.append(_merge_plan(local_plans[pid], remote_plans[pid]))
        elif pid in remote_plans:
            merged_plans.append(remote_plans[pid])
        else:
            merged_plans.append(local_plans[pid])
    merged["plans"] = merged_plans

    # --- PRs ---
    local_prs = {p["id"]: p for p in (local.get("prs") or [])}
    remote_prs = {p["id"]: p for p in (remote.get("prs") or [])}
    # Preserve order: remote PRs first, then local-only PRs
    all_pr_ids = list(dict.fromkeys(
        list(remote_prs.keys()) + list(local_prs.keys())
    ))
    merged_prs = []
    for pr_id in all_pr_ids:
        if pr_id in local_prs and pr_id in remote_prs:
            merged_prs.append(_merge_pr(local_prs[pr_id], remote_prs[pr_id]))
        elif pr_id in remote_prs:
            merged_prs.append(remote_prs[pr_id])
        else:
            merged_prs.append(local_prs[pr_id])
    merged["prs"] = merged_prs

    return merged


def sync_pm_state(
    pm_root: Path,
    data: dict,
    force: bool = False,
) -> tuple[dict, bool]:
    """Fetch latest state from remote and merge with local.

    Args:
        pm_root: Path to the pm/ directory
        data: Current local project data
        force: If True, ignore throttle interval

    Returns:
        Tuple of (merged_data, changed). If changed is True, the caller
        should save the merged data.
    """
    if not _should_sync(data, force):
        _log.debug("pm sync throttled")
        return data, False

    remote = fetch_remote_state(pm_root, data)
    _set_sync_timestamp(data)

    if remote is None:
        _log.debug("No remote state available")
        return data, False

    # Quick check: if remote and local are identical, skip merge
    if remote == data:
        return data, False

    merged = merge_project_data(data, remote)
    # Preserve our sync timestamp
    _set_sync_timestamp(merged)

    return merged, True


def sync_plan_files(
    pm_root: Path,
    data: dict,
) -> int:
    """Pull missing plan files from the remote base branch.

    Returns the number of files synced.
    """
    internal = store.is_internal_pm_dir(pm_root)
    repo_root = pm_root.parent if internal else pm_root
    base_branch = data.get("project", {}).get("base_branch", "main")
    backend = data.get("project", {}).get("backend", "vanilla")

    ref = base_branch if backend == "local" else f"origin/{base_branch}"
    prefix = "pm/" if internal else ""

    synced = 0
    for plan in data.get("plans") or []:
        plan_file = plan.get("file")
        if not plan_file:
            continue

        local_path = pm_root / plan_file
        if local_path.exists():
            continue

        # Try to fetch from remote
        result = git_ops.run_git(
            "show", f"{ref}:{prefix}{plan_file}",
            cwd=repo_root, check=False,
        )
        if result.returncode == 0 and result.stdout:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(result.stdout)
            synced += 1
            _log.info("Synced plan file: %s", plan_file)

    return synced
