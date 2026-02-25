"""PR sync logic for detecting merged PRs.

This module provides the core sync functionality used by:
- TUI refresh (r key)
- TUI periodic background sync (every 5 minutes)
- CLI commands (before pr-related operations)

It tracks the last sync timestamp to avoid excessive API calls.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pm_core import store, git_ops, graph
from pm_core.backend import get_backend

_log = logging.getLogger("pm.pr_sync")


def _trigger_tui_refresh() -> None:
    """Send refresh key to TUI pane if running in a pm session."""
    try:
        import subprocess
        import hashlib

        # Get current working directory to compute session name
        cwd = Path.cwd()

        # Find the pm root to get repo_id
        try:
            root = store.find_project_root()
            data = store.load(root, validate=False)
            repo_id = data.get("project", {}).get("repo_id", "")
            name = data.get("project", {}).get("name", "unknown")
            if repo_id:
                session_hash = repo_id[:8]
            else:
                session_hash = hashlib.sha256(str(root).encode()).hexdigest()[:8]
            session_name = f"pm-{name}-{session_hash}"
        except Exception:
            return

        # Find TUI pane in the session
        from pm_core.tmux import _tmux_cmd
        result = subprocess.run(
            _tmux_cmd("list-panes", "-t", session_name, "-F", "#{pane_id}:#{pane_current_command}"),
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return

        for line in result.stdout.strip().split("\n"):
            if ":pm" in line or ":python" in line:
                pane_id = line.split(":")[0]
                subprocess.run(
                    _tmux_cmd("send-keys", "-t", f"{session_name}:{pane_id}", "R"),
                    check=False, timeout=5
                )
                _log.debug("Sent refresh to TUI pane %s", pane_id)
                break
    except Exception as e:
        _log.debug("Could not trigger TUI refresh: %s", e)


# Minimum interval between syncs (in seconds)
# For manual refresh, we use a shorter interval
MIN_SYNC_INTERVAL_SECONDS = 60  # 1 minute for manual triggers
MIN_BACKGROUND_SYNC_INTERVAL_SECONDS = 300  # 5 minutes for background sync


class SyncResult:
    """Result of a PR sync operation."""

    def __init__(
        self,
        synced: bool,
        updated_count: int = 0,
        merged_prs: Optional[list[str]] = None,
        closed_prs: Optional[list[str]] = None,
        ready_prs: Optional[list[dict]] = None,
        error: Optional[str] = None,
        skipped_reason: Optional[str] = None,
        status_updates: Optional[dict[str, str]] = None,
    ):
        self.synced = synced
        self.updated_count = updated_count
        self.merged_prs = merged_prs or []
        self.closed_prs = closed_prs or []
        self.ready_prs = ready_prs or []
        self.error = error
        self.skipped_reason = skipped_reason
        self.status_updates = status_updates or {}

    @property
    def was_skipped(self) -> bool:
        return self.skipped_reason is not None


def get_last_sync_timestamp(data: dict) -> Optional[datetime]:
    """Get the last PR sync timestamp from project metadata."""
    ts_str = data.get("project", {}).get("last_pr_sync")
    if ts_str:
        try:
            return datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            return None
    return None


def set_last_sync_timestamp(data: dict, timestamp: datetime) -> None:
    """Set the last PR sync timestamp in project metadata."""
    if "project" not in data:
        data["project"] = {}
    data["project"]["last_pr_sync"] = timestamp.isoformat()


def should_sync(
    data: dict,
    min_interval_seconds: int = MIN_SYNC_INTERVAL_SECONDS,
    force: bool = False,
) -> tuple[bool, Optional[str]]:
    """Check if we should perform a sync based on timestamp.

    Returns:
        Tuple of (should_sync, reason_if_skipped)
    """
    if force:
        return True, None

    last_sync = get_last_sync_timestamp(data)
    if last_sync is None:
        return True, None

    now = datetime.now(timezone.utc)
    # Ensure last_sync is timezone-aware
    if last_sync.tzinfo is None:
        last_sync = last_sync.replace(tzinfo=timezone.utc)

    elapsed = (now - last_sync).total_seconds()
    if elapsed < min_interval_seconds:
        return False, f"synced {int(elapsed)}s ago (min interval: {min_interval_seconds}s)"

    return True, None


def find_workdir(data: dict) -> Optional[str]:
    """Find an existing workdir to use for merge checks.

    Returns the path to a valid git workdir, or None if none found.
    """
    prs = data.get("prs") or []

    # First check PR workdirs
    for p in prs:
        wd = p.get("workdir")
        if wd and Path(wd).exists() and git_ops.is_git_repo(wd):
            return wd

    # Fall back to workdirs base directory
    # Uses same naming convention as cli._workdirs_dir(): <name>-<repo_id[:8]>
    # The 8-char prefix of repo_id (root commit hash) ensures uniqueness
    from pm_core.paths import workdirs_base as get_workdirs_base
    project = data.get("project", {})
    name = project.get("name", "unknown")
    repo_id = project.get("repo_id")
    base = get_workdirs_base()
    if repo_id:
        workdirs_base = base / f"{name}-{repo_id[:8]}"
    else:
        workdirs_base = base / name

    if workdirs_base.exists():
        for d in workdirs_base.iterdir():
            if d.is_dir() and git_ops.is_git_repo(d):
                return str(d)

    return None


def sync_prs(
    root: Path,
    data: Optional[dict] = None,
    min_interval_seconds: int = MIN_SYNC_INTERVAL_SECONDS,
    force: bool = False,
    save_state: bool = True,
) -> SyncResult:
    """Check for merged PRs and update their status.

    Args:
        root: Path to PM project root
        data: Project data (if None, will be loaded from root)
        min_interval_seconds: Minimum seconds between syncs
        force: If True, ignore the minimum interval
        save_state: If True, save changes to project.yaml

    Returns:
        SyncResult with sync outcome details
    """
    if data is None:
        data = store.load(root)

    # Check if we should sync
    do_sync, skip_reason = should_sync(data, min_interval_seconds, force)
    if not do_sync:
        _log.debug("Skipping sync: %s", skip_reason)
        return SyncResult(synced=False, skipped_reason=skip_reason)

    # Find a workdir to use for checking
    target_workdir = find_workdir(data)
    if not target_workdir:
        _log.debug("No workdirs found for sync")
        return SyncResult(
            synced=False,
            error="No workdirs found. Run 'pm pr start' on a PR first."
        )

    prs = data.get("prs") or []
    base_branch = data.get("project", {}).get("base_branch", "master")
    backend_name = data.get("project", {}).get("backend", "vanilla")
    backend = get_backend(data)

    updated = 0
    merged_prs = []

    # Only the github backend can reliably auto-detect merges (via API).
    # Local/vanilla backends rely on `pm pr merge` for explicit tracking.
    if backend_name == "github":
        for pr_entry in prs:
            if pr_entry.get("status") not in ("in_review", "in_progress"):
                continue

            branch = pr_entry.get("branch", "")
            if not branch:
                continue

            # Prefer PR's own workdir if it exists
            wd = pr_entry.get("workdir")
            check_dir = wd if (wd and Path(wd).exists()) else target_workdir

            try:
                if backend.is_merged(str(check_dir), branch, base_branch):
                    from datetime import datetime as _dt, timezone as _tz
                    pr_entry["status"] = "merged"
                    pr_entry["merged_at"] = _dt.now(_tz.utc).isoformat()
                    merged_prs.append(pr_entry["id"])
                    updated += 1
                    _log.info("PR %s detected as merged", pr_entry["id"])
            except Exception as e:
                _log.warning("Error checking merge status for %s: %s", pr_entry["id"], e)

    # Update timestamp
    set_last_sync_timestamp(data, datetime.now(timezone.utc))

    # Save if requested and there were changes
    if save_state:
        store.save(data, root)

    # Get ready PRs
    ready = graph.ready_prs(prs)

    return SyncResult(
        synced=True,
        updated_count=updated,
        merged_prs=merged_prs,
        ready_prs=ready,
    )


def sync_prs_quiet(
    root: Path,
    data: Optional[dict] = None,
    min_interval_seconds: int = MIN_SYNC_INTERVAL_SECONDS,
    force: bool = False,
) -> tuple[dict, SyncResult]:
    """Sync PRs and return updated data without saving.

    This is useful for CLI commands that want to sync before displaying
    data but handle saving themselves.

    Returns:
        Tuple of (updated_data, SyncResult)
    """
    if data is None:
        data = store.load(root)

    result = sync_prs(root, data, min_interval_seconds, force, save_state=False)
    return data, result


def sync_from_github(
    root: Path,
    data: Optional[dict] = None,
    save_state: bool = True,
) -> SyncResult:
    """Fetch and update PR statuses directly from GitHub API.

    This does a full sync using the GitHub API (via gh CLI) to get
    accurate PR state including:
    - MERGED → merged
    - CLOSED → closed
    - OPEN + draft → in_progress
    - OPEN + ready → in_review

    Only works with the GitHub backend and PRs that have gh_pr_number set.

    Args:
        root: Path to PM project root
        data: Project data (if None, will be loaded from root)
        save_state: If True, save changes to project.yaml

    Returns:
        SyncResult with sync outcome details
    """
    import subprocess
    import json

    if data is None:
        data = store.load(root)

    backend_name = data.get("project", {}).get("backend", "vanilla")
    if backend_name != "github":
        return SyncResult(
            synced=False,
            error="GitHub sync only works with the GitHub backend"
        )

    prs = data.get("prs") or []
    updated = 0
    merged_prs = []
    closed_prs = []
    status_updates: dict[str, str] = {}

    for pr_entry in prs:
        gh_pr_number = pr_entry.get("gh_pr_number")
        if not gh_pr_number:
            continue

        pr_id = pr_entry["id"]
        old_status = pr_entry.get("status", "pending")

        try:
            result = subprocess.run(
                ["gh", "pr", "view", str(gh_pr_number), "--json", "state,isDraft,mergedAt"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                _log.warning("Could not fetch GitHub PR #%s for %s", gh_pr_number, pr_id)
                continue

            info = json.loads(result.stdout)
            gh_state = info.get("state")
            is_draft = info.get("isDraft", False)
            merged_at = info.get("mergedAt")

            # Determine new status
            if gh_state == "MERGED" or merged_at:
                new_status = "merged"
            elif gh_state == "CLOSED":
                new_status = "closed"
            elif gh_state == "OPEN":
                new_status = "in_progress" if is_draft else "in_review"
            else:
                _log.warning("Unknown GitHub state '%s' for %s", gh_state, pr_id)
                continue

            if new_status != old_status:
                pr_entry["status"] = new_status
                updated += 1
                status_updates[pr_id] = new_status
                _log.info("PR %s: %s → %s (from GitHub)", pr_id, old_status, new_status)
                if new_status == "merged":
                    merged_prs.append(pr_id)
                elif new_status == "closed":
                    closed_prs.append(pr_id)

        except subprocess.TimeoutExpired:
            _log.warning("Timeout fetching GitHub PR #%s for %s", gh_pr_number, pr_id)
        except Exception as e:
            _log.warning("Error fetching GitHub status for %s: %s", pr_id, e)

    # Update timestamp
    set_last_sync_timestamp(data, datetime.now(timezone.utc))

    if save_state and updated:
        store.save(data, root)

    # Closed PRs keep status "closed" in the yaml but are not auto-removed.
    # This avoids losing PRs that were auto-closed by GitHub (e.g. when a
    # base branch is deleted) but may be reopened or retargeted.

    return SyncResult(
        synced=True,
        updated_count=updated,
        merged_prs=merged_prs,
        closed_prs=closed_prs,
        status_updates=status_updates,
    )
