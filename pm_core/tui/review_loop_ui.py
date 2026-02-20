"""Review loop UI integration for the TUI.

Manages starting/stopping the review loop and updating the TUI display
with loop status and verdicts.
"""

from pm_core.paths import configure_logger
from pm_core import store, prompt_gen
from pm_core.review_loop import (
    ReviewLoopState,
    start_review_loop_background,
    VERDICT_PASS,
    VERDICT_PASS_WITH_SUGGESTIONS,
    VERDICT_NEEDS_WORK,
)

_log = configure_logger("pm.tui.review_loop_ui")

# Icons for review verdicts
VERDICT_ICONS = {
    VERDICT_PASS: "[green bold]✓ PASS[/]",
    VERDICT_PASS_WITH_SUGGESTIONS: "[yellow bold]~ PASS_WITH_SUGGESTIONS[/]",
    VERDICT_NEEDS_WORK: "[red bold]✗ NEEDS_WORK[/]",
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


def toggle_review_loop(app) -> None:
    """Start or stop the review loop for the selected PR.

    If a loop is already running, stops it. Otherwise starts a new one.
    """
    if app._review_loop_state and app._review_loop_state.running:
        stop_review_loop(app)
        return

    start_review_loop(app)


def start_review_loop(app) -> None:
    """Start a review loop for the selected PR."""
    pr_id, pr = _get_selected_pr(app)
    if not pr_id:
        app.log_message("No PR selected")
        return

    if not pr:
        app.log_message(f"PR {pr_id} not found")
        return

    workdir = pr.get("workdir")
    if not workdir:
        app.log_message(f"No workdir for {pr_id}. Start the PR first.")
        return

    # Stop existing loop if running
    if app._review_loop_state and app._review_loop_state.running:
        app._review_loop_state.stop_requested = True
        _log.info("review_loop_ui: stopping existing loop before starting new one")

    # Generate review prompt
    review_prompt = prompt_gen.generate_review_prompt(app._data, pr_id)

    # Create state
    state = ReviewLoopState(pr_id=pr_id)
    app._review_loop_state = state

    _log.info("review_loop_ui: starting loop for %s", pr_id)
    app.log_message(f"[bold]Review loop started[/] for {pr_id} — z d to stop", sticky=3)

    # Update the status bar to show loop indicator
    _update_loop_display(app)

    # Start a periodic timer to poll loop state and update TUI
    if app._review_loop_timer:
        app._review_loop_timer.stop()
    app._review_loop_timer = app.set_interval(1.0, lambda: _poll_loop_state(app))

    # Start the background loop
    start_review_loop_background(
        prompt=review_prompt,
        cwd=workdir,
        state=state,
        on_iteration=lambda s: _on_iteration_from_thread(app, s),
        on_complete=lambda s: _on_complete_from_thread(app, s),
    )


def stop_review_loop(app) -> None:
    """Stop the running review loop."""
    if not app._review_loop_state:
        app.log_message("No review loop running")
        return

    if not app._review_loop_state.running:
        app.log_message("Review loop already stopped")
        return

    _log.info("review_loop_ui: stopping loop for %s", app._review_loop_state.pr_id)
    app._review_loop_state.stop_requested = True
    app.log_message("[bold]Review loop stopping...[/]")


def _on_iteration_from_thread(app, state: ReviewLoopState) -> None:
    """Called from the background thread after each iteration.

    We can't touch Textual widgets from a thread, so we just log.
    The periodic timer (_poll_loop_state) handles UI updates.
    """
    _log.info("review_loop_ui: iteration %d verdict=%s for %s",
              state.iteration, state.latest_verdict, state.pr_id)


def _on_complete_from_thread(app, state: ReviewLoopState) -> None:
    """Called from the background thread when the loop finishes."""
    _log.info("review_loop_ui: loop complete for %s — verdict=%s iterations=%d",
              state.pr_id, state.latest_verdict, state.iteration)


def _poll_loop_state(app) -> None:
    """Periodic timer callback to update TUI from loop state."""
    state = app._review_loop_state
    if not state:
        if app._review_loop_timer:
            app._review_loop_timer.stop()
            app._review_loop_timer = None
        return

    _update_loop_display(app)

    # If loop has finished, clean up the timer
    if not state.running:
        if app._review_loop_timer:
            app._review_loop_timer.stop()
            app._review_loop_timer = None

        verdict_icon = VERDICT_ICONS.get(state.latest_verdict, state.latest_verdict)
        app.log_message(
            f"Review loop done: {verdict_icon} "
            f"({state.iteration} iteration{'s' if state.iteration != 1 else ''})",
            sticky=10,
        )


def _update_loop_display(app) -> None:
    """Update the status bar / log line to reflect review loop state."""
    state = app._review_loop_state
    if not state:
        return

    verdict_icon = VERDICT_ICONS.get(state.latest_verdict, state.latest_verdict)

    if state.running:
        if state.iteration == 0:
            msg = f"[bold cyan]⟳ Review loop[/] {state.pr_id} — starting..."
        else:
            msg = (
                f"[bold cyan]⟳ Review loop[/] {state.pr_id} "
                f"— iter {state.iteration} {verdict_icon}"
            )
        app.log_message(msg, capture=False)
    # When not running, _poll_loop_state handles the final message
