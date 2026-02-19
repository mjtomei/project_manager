"""Background and startup sync operations for the TUI.

All functions take the app instance as the first parameter so they can
access app state and call app methods (log_message, _update_display, etc.).
"""

from pm_core.paths import configure_logger
from pm_core import store, guide, pr_sync
from pm_core.tui.pane_ops import GUIDE_SETUP_STEPS

_log = configure_logger("pm.tui.sync")


async def background_sync(app) -> None:
    """Pull latest state from git or check guide progress."""
    from pm_core.tui.frame_capture import load_capture_config

    # Reload capture config in case it was updated via CLI
    load_capture_config(app)

    # If guide was dismissed, do normal sync
    if app._guide_dismissed:
        await do_normal_sync(app)
        return

    # Check current guide state
    try:
        app._root = store.find_project_root()
        app._data = store.load(app._root)
    except FileNotFoundError:
        app._root = None
        app._data = {}

    state, _ = guide.resolve_guide_step(app._root)

    # If we're in guide mode, check for state changes
    if app._current_guide_step is not None:
        if state not in GUIDE_SETUP_STEPS:
            # Guide is complete, switch to normal view
            if app._data:
                app._update_display()
            app._show_normal_view(from_guide=True)
            app.log_message("Guide complete! Showing tech tree.")
        elif state != app._current_guide_step:
            # Step changed, update the guide view
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

        # Perform PR sync to detect merged PRs
        result = pr_sync.sync_prs(
            app._root,
            app._data,
            min_interval_seconds=min_interval,
        )

        # Reload data after sync
        app._data = store.load(app._root)
        app._update_display()

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
        result = pr_sync.sync_from_github(app._root, app._data, save_state=True)

        if result.synced and result.updated_count > 0:
            # Reload data after sync
            app._data = store.load(app._root)
            app._update_display()
            app.log_message(f"GitHub sync: {result.updated_count} PR(s) updated")
        elif result.error:
            _log.warning("GitHub sync error: %s", result.error)
        else:
            app.log_message("GitHub sync: up to date")

        app.set_timer(2.0, app._clear_log_message)
    except Exception as e:
        _log.exception("GitHub sync error")
        app.log_message(f"GitHub sync error: {e}")
        app.set_timer(3.0, app._clear_log_message)
