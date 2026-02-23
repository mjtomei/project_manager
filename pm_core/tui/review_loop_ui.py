"""Review loop UI integration for the TUI.

Manages starting/stopping review loops and updating the TUI display.
Multiple PRs can have loops running simultaneously.

Keybindings:
  z d     — If a loop is running for the selected PR, make this iteration
             the last one.  Otherwise, perform a fresh ``pr done`` (original
             behaviour).
  zz d    — Start a review loop (stops on PASS or PASS_WITH_SUGGESTIONS).
             If a loop is already running, make this iteration the last one.
  zzz d   — Start a strict review loop (stops only on full PASS).
             If a loop is already running, make this iteration the last one.
"""

from pm_core.paths import configure_logger
from pm_core import store
from pm_core.review_loop import (
    ReviewLoopState,
    start_review_loop_background,
    VERDICT_PASS,
    VERDICT_PASS_WITH_SUGGESTIONS,
    VERDICT_NEEDS_WORK,
)

_log = configure_logger("pm.tui.review_loop_ui")

# Icons for review verdicts (used in log line)
VERDICT_ICONS = {
    VERDICT_PASS: "[green bold]✓ PASS[/]",
    VERDICT_PASS_WITH_SUGGESTIONS: "[yellow bold]~ PASS_WITH_SUGGESTIONS[/]",
    VERDICT_NEEDS_WORK: "[red bold]✗ NEEDS_WORK[/]",
    "KILLED": "[red bold]☠ KILLED[/]",
    "TIMEOUT": "[red bold]⏱ TIMEOUT[/]",
    "ERROR": "[red bold]! ERROR[/]",
    "": "[dim]—[/]",
}


def _get_selected_pr(app) -> tuple[str | None, dict | None]:
    """Get the selected PR ID and entry."""
    from pm_core.tui.tech_tree import TechTree

    tree = app.query_one("#tech-tree", TechTree)
    pr_id = tree.selected_pr_id
    if not pr_id:
        return None, None
    pr = store.get_pr(app._data, pr_id)
    return pr_id, pr


# ---------------------------------------------------------------------------
# z d  — fresh done or stop loop
# ---------------------------------------------------------------------------

def stop_loop_or_fresh_done(app) -> None:
    """Handle ``z d``: stop a running loop, or do a fresh done."""
    pr_id, pr = _get_selected_pr(app)
    if not pr_id:
        app.log_message("No PR selected")
        return

    loop = app._review_loops.get(pr_id)
    if loop and loop.running:
        _stop_loop(app, pr_id)
    else:
        # Original z d behaviour: fresh done
        from pm_core.tui import pr_view
        pr_view.done_pr(app, fresh=True)


# ---------------------------------------------------------------------------
# zz d / zzz d  — start or stop loop
# ---------------------------------------------------------------------------

def start_or_stop_loop(app, stop_on_suggestions: bool) -> None:
    """Handle ``zz d`` / ``zzz d``: start loop or stop if one is running."""
    pr_id, pr = _get_selected_pr(app)
    if not pr_id:
        app.log_message("No PR selected")
        return

    loop = app._review_loops.get(pr_id)
    if loop and loop.running:
        _stop_loop(app, pr_id)
        return

    _start_loop(app, pr_id, pr, stop_on_suggestions)


# ---------------------------------------------------------------------------
# Core start / stop
# ---------------------------------------------------------------------------

def _start_loop(app, pr_id: str, pr: dict | None, stop_on_suggestions: bool) -> None:
    """Start a review loop for the given PR."""
    from pm_core import tmux as tmux_mod

    if not pr:
        app.log_message(f"PR {pr_id} not found")
        return

    if not tmux_mod.in_tmux():
        app.log_message("Review loop requires tmux. Use 'pm session' to start.")
        return

    workdir = pr.get("workdir")
    if not workdir:
        app.log_message(f"No workdir for {pr_id}. Start the PR first.")
        return

    # Get pm_root for launching the review window
    pm_root = str(store.find_project_root())

    # Create state
    mode = "strict" if not stop_on_suggestions else "normal"
    state = ReviewLoopState(pr_id=pr_id, stop_on_suggestions=stop_on_suggestions)
    app._review_loops[pr_id] = state

    _log.info("review_loop_ui: starting %s loop for %s", mode, pr_id)
    mode_label = "strict (PASS only)" if not stop_on_suggestions else "normal"
    app.log_message(
        f"[bold]Review loop started[/] for {pr_id} [{mode_label}] loop={state.loop_id} — z d to stop",
        sticky=3,
    )

    # Ensure the poll timer is running
    _ensure_poll_timer(app)

    # Start the background loop
    start_review_loop_background(
        state=state,
        pm_root=pm_root,
        pr_data=pr,
        on_iteration=lambda s: _on_iteration_from_thread(app, s),
        on_complete=lambda s: _on_complete_from_thread(app, s),
    )


def _stop_loop(app, pr_id: str) -> None:
    """Request graceful stop of a running loop."""
    loop = app._review_loops.get(pr_id)
    if not loop or not loop.running:
        app.log_message(f"No review loop running for {pr_id}")
        return

    _log.info("review_loop_ui: stopping loop for %s", pr_id)
    loop.stop_requested = True
    app.log_message(f"[bold]Review loop stopping[/] for {pr_id} (finishing current iteration)...")


def stop_loop_for_pr(app, pr_id: str) -> None:
    """Public API: stop a loop for a specific PR (used by command bar)."""
    _stop_loop(app, pr_id)


# ---------------------------------------------------------------------------
# Background thread callbacks
# ---------------------------------------------------------------------------

def _on_iteration_from_thread(app, state: ReviewLoopState) -> None:
    """Called from the background thread after each iteration."""
    _log.info("review_loop_ui: iteration %d verdict=%s for %s",
              state.iteration, state.latest_verdict, state.pr_id)


def _on_complete_from_thread(app, state: ReviewLoopState) -> None:
    """Called from the background thread when the loop finishes."""
    _log.info("review_loop_ui: loop complete for %s — verdict=%s iterations=%d",
              state.pr_id, state.latest_verdict, state.iteration)


# ---------------------------------------------------------------------------
# Periodic poll timer (shared across all loops)
# ---------------------------------------------------------------------------

def _ensure_poll_timer(app) -> None:
    """Start the poll timer if not already running."""
    if not app._review_loop_timer:
        app._review_loop_timer = app.set_interval(1.0, lambda: _poll_loop_state(app))


def ensure_animation_timer(app) -> None:
    """Start the poll timer if there are active PRs that need animation.

    Called after PR status changes (start, done, sync) to ensure
    the spinner animation runs for in_progress/in_review PRs.
    """
    has_active = any(
        pr.get("status") in ("in_progress", "in_review") and pr.get("workdir")
        for pr in (app._data.get("prs") or [])
    )
    if has_active or any(s.running for s in app._review_loops.values()):
        _ensure_poll_timer(app)


def _poll_loop_state(app) -> None:
    """Periodic timer callback to update TUI from loop state."""
    any_running = False
    newly_done = []

    for pr_id, state in list(app._review_loops.items()):
        if state.running:
            any_running = True
        elif not state._ui_notified_done:
            state._ui_notified_done = True
            newly_done.append(state)

    # Refresh tech tree to update ⟳N markers on PR nodes
    _refresh_tech_tree(app)

    # Announce completed loops
    for state in newly_done:
        verdict_icon = VERDICT_ICONS.get(state.latest_verdict, state.latest_verdict)
        app.log_message(
            f"Review loop done for {state.pr_id}: {verdict_icon} "
            f"({state.iteration} iteration{'s' if state.iteration != 1 else ''})",
            sticky=10,
        )

    # Stop the timer if no loops are running AND no active PRs need animation
    has_active_prs = any(
        pr.get("status") in ("in_progress", "in_review") and pr.get("workdir")
        for pr in (app._data.get("prs") or [])
    )
    if not any_running and not has_active_prs:
        if app._review_loop_timer:
            app._review_loop_timer.stop()
            app._review_loop_timer = None


def _refresh_tech_tree(app) -> None:
    """Refresh the tech tree so ⟳N markers and spinners update on PR nodes."""
    try:
        from pm_core.tui.tech_tree import TechTree
        tree = app.query_one("#tech-tree", TechTree)
        tree.advance_animation()
        tree.refresh()
    except Exception:
        pass
