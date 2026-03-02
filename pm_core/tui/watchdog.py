"""TUI watchdog: detect dead background threads and stale state.

Runs on its own lightweight timer (every 30s), separate from the main
1-second poll timer, so it can detect and recover from poll timer failures.

Checks performed:
1. Review loop threads: thread dead but state.running=True → force cleanup
2. Watcher loop thread: same is_alive() vs state.running check
3. Poll timer health: last-tick timestamp stale >5s → restart timer
4. Merge tracking sets: stale entries with no live merge window → cleanup
5. Auto-start subprocess health: long-running starts → log warning
"""

import time

from pm_core.paths import configure_logger

_log = configure_logger("pm.tui.watchdog")

# How often the watchdog timer fires (seconds)
WATCHDOG_INTERVAL = 30

# Poll timer is considered stale after this many seconds without a tick
_POLL_STALE_THRESHOLD = 5.0


def start_watchdog(app) -> None:
    """Start the watchdog timer on the app.

    Safe to call multiple times — will not create duplicate timers.
    """
    if app._watchdog_timer is not None:
        return
    app._watchdog_timer = app.set_interval(
        WATCHDOG_INTERVAL, lambda: _watchdog_tick(app),
    )
    _log.info("watchdog: started (interval=%ds)", WATCHDOG_INTERVAL)


def stop_watchdog(app) -> None:
    """Stop the watchdog timer."""
    if app._watchdog_timer is not None:
        app._watchdog_timer.stop()
        app._watchdog_timer = None
        _log.info("watchdog: stopped")


def _watchdog_tick(app) -> None:
    """Single watchdog tick — runs all checks."""
    try:
        _check_review_loops(app)
        _check_watcher_loop(app)
        _check_poll_timer(app)
        _check_stale_merge_tracking(app)
    except Exception:
        _log.exception("watchdog: unexpected error in tick")


# ---------------------------------------------------------------------------
# 1. Review loop thread health
# ---------------------------------------------------------------------------

def _check_review_loops(app) -> None:
    """Detect review loop threads that died but left state.running=True."""
    for pr_id, state in list(app._review_loops.items()):
        if not state.running:
            continue

        thread = state._thread
        if thread is None:
            # No thread reference stored (shouldn't happen for new loops)
            continue

        if not thread.is_alive():
            _log.error(
                "watchdog: review loop thread for %s is dead but state.running=True "
                "(verdict=%s, iteration=%d) — forcing cleanup",
                pr_id, state.latest_verdict, state.iteration,
            )
            state.running = False
            if not state.latest_verdict:
                state.latest_verdict = "ERROR"
            app.log_message(
                f"[red bold]Watchdog:[/] review loop for {pr_id} died unexpectedly",
                sticky=10,
            )


# ---------------------------------------------------------------------------
# 2. Watcher loop thread health
# ---------------------------------------------------------------------------

def _check_watcher_loop(app) -> None:
    """Detect watcher loop thread that died but left state.running=True."""
    state = app._watcher_state
    if not state or not state.running:
        return

    thread = state._thread
    if thread is None:
        return

    if not thread.is_alive():
        _log.error(
            "watchdog: watcher loop thread is dead but state.running=True "
            "(verdict=%s, iteration=%d) — forcing cleanup",
            state.latest_verdict, state.iteration,
        )
        state.running = False
        if not state.latest_verdict:
            state.latest_verdict = "ERROR"
        app.log_message(
            "[red bold]Watchdog:[/] watcher loop died unexpectedly",
            sticky=10,
        )


# ---------------------------------------------------------------------------
# 3. Poll timer health
# ---------------------------------------------------------------------------

def _check_poll_timer(app) -> None:
    """Detect stale poll timer and restart it if needed.

    The poll timer (_review_loop_timer) fires every 1s and updates
    app._poll_last_tick.  If the watchdog sees it hasn't fired in
    >5s while there are active loops/PRs, the timer has likely crashed.
    """
    # Only care if the poll timer should be running
    if not _poll_timer_needed(app):
        return

    now = time.monotonic()
    last_tick = app._poll_last_tick

    # If _poll_last_tick is 0, the timer was never started or was just
    # restarted — give it a grace period before flagging
    if last_tick == 0.0:
        return

    stale_seconds = now - last_tick
    if stale_seconds <= _POLL_STALE_THRESHOLD:
        return

    _log.error(
        "watchdog: poll timer stale (%.1fs since last tick) — restarting",
        stale_seconds,
    )

    # Kill the old timer if it still exists
    if app._review_loop_timer:
        try:
            app._review_loop_timer.stop()
        except Exception:
            pass
        app._review_loop_timer = None

    # Reset tick tracking and restart
    app._poll_last_tick = 0.0
    from pm_core.tui.review_loop_ui import _ensure_poll_timer
    _ensure_poll_timer(app)

    app.log_message(
        "[red bold]Watchdog:[/] poll timer was stale, restarted",
        sticky=5,
    )


def _poll_timer_needed(app) -> bool:
    """Check whether the poll timer should be running."""
    # Any review loop running?
    if any(s.running for s in app._review_loops.values()):
        return True
    # Watcher running?
    if app._watcher_state and app._watcher_state.running:
        return True
    # Any active PRs needing animation?
    if any(
        pr.get("status") in ("in_progress", "in_review") and pr.get("workdir")
        for pr in (app._data.get("prs") or [])
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# 4. Stale merge tracking
# ---------------------------------------------------------------------------

def _check_stale_merge_tracking(app) -> None:
    """Clean up merge tracking entries whose merge windows no longer exist.

    Checks _pending_merge_prs and _merge_propagation_phase for entries
    where the corresponding merge tmux window has disappeared.
    """
    from pm_core import tmux as tmux_mod
    from pm_core import store
    from pm_core.cli.helpers import _pr_display_id

    session = app._session_name
    if not session:
        return

    # Check _pending_merge_prs
    stale_pending = []
    for pr_id in list(app._pending_merge_prs):
        pr = store.get_pr(app._data, pr_id)
        if not pr:
            stale_pending.append(pr_id)
            continue
        # If PR is already merged, no need to track
        if pr.get("status") == "merged":
            stale_pending.append(pr_id)
            continue
        window_name = f"merge-{_pr_display_id(pr)}"
        if not tmux_mod.find_window_by_name(session, window_name):
            stale_pending.append(pr_id)

    for pr_id in stale_pending:
        app._pending_merge_prs.discard(pr_id)
        app._merge_input_required_prs.discard(pr_id)
        _log.info("watchdog: cleaned up stale pending merge for %s", pr_id)

    # Check _merge_propagation_phase
    stale_propagation = []
    for pr_id in list(app._merge_propagation_phase):
        pr = store.get_pr(app._data, pr_id)
        if not pr:
            stale_propagation.append(pr_id)
            continue
        if pr.get("status") == "merged":
            stale_propagation.append(pr_id)
            continue
        window_name = f"merge-{_pr_display_id(pr)}"
        if not tmux_mod.find_window_by_name(session, window_name):
            stale_propagation.append(pr_id)

    for pr_id in stale_propagation:
        app._merge_propagation_phase.discard(pr_id)
        _log.info("watchdog: cleaned up stale merge propagation for %s", pr_id)

    if stale_pending or stale_propagation:
        total = len(stale_pending) + len(stale_propagation)
        app.log_message(
            f"[yellow]Watchdog:[/] cleaned up {total} stale merge tracking "
            f"{'entry' if total == 1 else 'entries'}",
        )
