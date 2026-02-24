"""Background and startup sync operations for the TUI.

All functions take the app instance as the first parameter so they can
access app state and call app methods (log_message, _update_display, etc.).

Sync functions that call blocking I/O (GitHub API, git) run in a thread
via run_in_executor.  To avoid race conditions with user actions that also
read/write project.yaml, the thread operates on a deep copy of the data
and never saves to disk — the main thread reloads and applies results.
"""

import asyncio
import copy

from pm_core.paths import configure_logger
from pm_core import store, guide, pr_sync

_log = configure_logger("pm.tui.sync")


def _kill_merged_pr_windows(app, merged_pr_ids: set[str]) -> None:
    """Kill tmux windows for merged PRs since they're no longer accessible from the TUI."""
    from pm_core import tmux as tmux_mod
    from pm_core.cli.helpers import kill_pr_windows

    if not app._session_name or not merged_pr_ids:
        return
    session = app._session_name
    if not tmux_mod.session_exists(session):
        return

    for pr_id in merged_pr_ids:
        pr = store.get_pr(app._data, pr_id)
        if not pr:
            continue
        killed = kill_pr_windows(session, pr)
        for win_name in killed:
            _log.info("Killed window '%s' for merged %s", win_name, pr_id)


async def background_sync(app) -> None:
    """Pull latest state from git or check guide progress."""
    from pm_core.tui.frame_capture import load_capture_config

    # Reload capture config in case it was updated via CLI
    load_capture_config(app)

    # Check current guide state
    try:
        app._root = store.find_project_root()
        app._data = store.load(app._root)
    except FileNotFoundError:
        app._root = None
        app._data = {}

    # If we're in guide mode, check for state changes
    if app._current_guide_step is not None:
        prs = app._data.get("prs") or []
        if prs:
            # PRs exist now — guide complete, switch to normal view
            if app._data:
                app._update_display()
            app._show_normal_view()
            app.log_message("Guide complete! Showing tech tree.")
        else:
            state, _ = guide.detect_state(app._root)
            if state != app._current_guide_step:
                app._show_guide_view(state)
        return

    # Not in guide mode - do normal sync
    await do_normal_sync(app)


async def do_normal_sync(app, is_manual: bool = False) -> None:
    """Perform normal PR sync to detect merged PRs.

    Args:
        is_manual: True if triggered by user (r key), False for periodic background sync
    """
    from pm_core.tui.widgets import StatusBar

    if not app._root:
        return
    try:
        status_bar = app.query_one("#status-bar", StatusBar)
        project = app._data.get("project", {})
        prs = app._data.get("prs") or []
        status_bar.update_status(project.get("name", "???"), project.get("repo", "???"), "pulling", pr_count=len(prs))

        # Use shorter interval for manual refresh, longer for background
        min_interval = (
            pr_sync.MIN_SYNC_INTERVAL_SECONDS if is_manual
            else pr_sync.MIN_BACKGROUND_SYNC_INTERVAL_SECONDS
        )

        # Run blocking sync in a thread so it doesn't freeze the UI.
        # Use a deep copy so the thread doesn't mutate app._data, and
        # save_state=False to avoid overwriting concurrent user changes.
        data_copy = copy.deepcopy(app._data)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: pr_sync.sync_prs(
                app._root,
                data_copy,
                min_interval_seconds=min_interval,
                save_state=False,
            ))

        # Snapshot PR statuses before reload so we can detect merges that
        # happened outside of sync (e.g. `pm pr merge` for local/vanilla).
        old_statuses = {
            pr["id"]: pr.get("status")
            for pr in (app._data.get("prs") or [])
        }

        # Reload from disk (picks up any concurrent user changes) and
        # apply sync results (merged PRs) on the main thread.
        app._data = store.load(app._root)
        if result.merged_prs:
            for pr in app._data.get("prs") or []:
                if pr["id"] in result.merged_prs:
                    pr["status"] = "merged"
            store.save(app._data, app._root)
            _kill_merged_pr_windows(app, result.merged_prs)
        app._update_display()

        # Detect PRs that became merged — either via sync or via CLI
        # (e.g. `pm pr merge` for local/vanilla backends saves status
        # to disk before triggering a TUI refresh).
        newly_merged = set(result.merged_prs)
        for pr in app._data.get("prs") or []:
            if pr.get("status") == "merged" and old_statuses.get(pr["id"]) != "merged":
                newly_merged.add(pr["id"])

        if newly_merged - set(result.merged_prs):
            _kill_merged_pr_windows(app, newly_merged - set(result.merged_prs))

        # Auto-start ready PRs if enabled (after merged PR detection)
        if newly_merged:
            from pm_core.tui.auto_start import check_and_start
            await check_and_start(app)

        prs = app._data.get("prs") or []

        # Determine sync status message
        if result.was_skipped:
            sync_status = "no-op"
            if is_manual:
                app.log_message("Already up to date")
        elif result.error:
            # "No workdirs" is not really an error - just nothing to sync yet
            if "No workdirs" in result.error:
                sync_status = "no-op"
                _log.debug("PR sync: %s", result.error)
            else:
                sync_status = "error"
                _log.warning("PR sync error: %s", result.error)
                app.log_message(f"Sync error: {result.error}")
        elif result.updated_count > 0:
            sync_status = "synced"
            app.log_message(f"Synced: {result.updated_count} PR(s) merged")
        else:
            sync_status = "synced"
            if is_manual:
                app.log_message("Refreshed")

        status_bar.update_status(project.get("name", "???"), project.get("repo", "???"), sync_status, pr_count=len(prs))

        # Clear log message after 1 second for manual refresh
        if is_manual:
            app.set_timer(1.0, app._clear_log_message)
    except Exception as e:
        _log.exception("Sync error")
        app.log_message(f"Sync error: {e}")


async def startup_github_sync(app) -> None:
    """Perform a full GitHub API sync on startup.

    This fetches actual PR state from GitHub (merged, closed, draft status)
    rather than just checking git merge status.
    """
    if not app._root:
        return

    backend_name = app._data.get("project", {}).get("backend", "vanilla")
    if backend_name != "github":
        return

    try:
        app.log_message("Syncing with GitHub...")
        # Run blocking HTTP call in a thread so it doesn't freeze the UI.
        # Deep copy + save_state=False to avoid racing with user actions.
        data_copy = copy.deepcopy(app._data)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: pr_sync.sync_from_github(app._root, data_copy, save_state=False))

        if result.synced and result.updated_count > 0:
            # Reload from disk and apply ALL status changes on the main thread
            app._data = store.load(app._root)
            changed = False
            newly_merged = set()
            for pr in app._data.get("prs") or []:
                new_status = result.status_updates.get(pr["id"])
                if new_status and pr.get("status") != new_status:
                    if new_status == "merged":
                        newly_merged.add(pr["id"])
                    pr["status"] = new_status
                    changed = True
            if changed:
                store.save(app._data, app._root)
            if newly_merged:
                _kill_merged_pr_windows(app, newly_merged)
            app._update_display()
            app.log_message(f"GitHub sync: {result.updated_count} PR(s) updated")
            # Auto-start ready PRs if enabled
            if newly_merged:
                from pm_core.tui.auto_start import check_and_start
                await check_and_start(app)
        elif result.error:
            _log.warning("GitHub sync error: %s", result.error)
        else:
            app.log_message("GitHub sync: up to date")

        app.set_timer(2.0, app._clear_log_message)
    except Exception as e:
        _log.exception("GitHub sync error")
        app.log_message(f"GitHub sync error: {e}")
        app.set_timer(3.0, app._clear_log_message)
