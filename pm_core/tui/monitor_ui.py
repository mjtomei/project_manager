"""Monitor loop UI integration for the TUI.

Manages starting/stopping the autonomous monitor loop and updating
the TUI display.  The monitor runs alongside auto-start and watches
all active tmux panes for issues.

Only one monitor loop can run at a time (unlike review loops which
are per-PR).
"""

from pm_core.paths import configure_logger
from pm_core import store
from pm_core.monitor_loop import (
    MonitorLoopState,
    start_monitor_loop_background,
    VERDICT_READY,
    VERDICT_INPUT_REQUIRED,
)

_log = configure_logger("pm.tui.monitor_ui")

# Icons for monitor verdicts (used in log line)
MONITOR_VERDICT_ICONS = {
    VERDICT_READY: "[green bold]OK READY[/]",
    VERDICT_INPUT_REQUIRED: "[red bold]!! INPUT_REQUIRED[/]",
    "KILLED": "[red bold]X KILLED[/]",
    "ERROR": "[red bold]! ERROR[/]",
    "": "[dim]--[/]",
}


# ---------------------------------------------------------------------------
# Start / stop
# ---------------------------------------------------------------------------

def start_monitor(app, transcript_dir: str | None = None) -> None:
    """Start the monitor loop."""
    from pm_core import tmux as tmux_mod

    if not tmux_mod.in_tmux():
        app.log_message("Monitor requires tmux.")
        return

    # Don't start if already running
    if app._monitor_state and app._monitor_state.running:
        app.log_message("Monitor is already running.")
        return

    pm_root = str(store.find_project_root())

    state = MonitorLoopState()
    app._monitor_state = state

    _log.info("monitor_ui: starting monitor loop=%s", state.loop_id)
    app.log_message(
        "[bold]Monitor started[/] -- watching for issues",
        sticky=3,
    )

    # Ensure the poll timer is running (shared with review loops)
    from pm_core.tui.review_loop_ui import _ensure_poll_timer
    _ensure_poll_timer(app)

    start_monitor_loop_background(
        state=state,
        pm_root=pm_root,
        on_iteration=lambda s: _on_iteration_from_thread(app, s),
        on_complete=lambda s: _on_complete_from_thread(app, s),
        transcript_dir=transcript_dir,
    )


def stop_monitor(app) -> None:
    """Request graceful stop of the monitor loop."""
    state = app._monitor_state
    if not state or not state.running:
        app.log_message("No monitor loop running.")
        return

    _log.info("monitor_ui: stopping monitor loop")
    state.stop_requested = True
    app.log_message("[bold]Monitor stopping[/] (finishing current iteration)...")


def is_running(app) -> bool:
    """Check if the monitor loop is running."""
    state = app._monitor_state
    return bool(state and state.running)


# ---------------------------------------------------------------------------
# Background thread callbacks
# ---------------------------------------------------------------------------

def _on_iteration_from_thread(app, state: MonitorLoopState) -> None:
    """Called from the background thread after each iteration."""
    _log.info("monitor_ui: iteration %d verdict=%s",
              state.iteration, state.latest_verdict)


def _on_complete_from_thread(app, state: MonitorLoopState) -> None:
    """Called from the background thread when the loop finishes."""
    _log.info("monitor_ui: loop complete -- verdict=%s iterations=%d",
              state.latest_verdict, state.iteration)

    # Finalize transcripts
    tdir = getattr(state, '_transcript_dir', None)
    if tdir:
        from pathlib import Path
        from pm_core.claude_launcher import finalize_transcript
        tdir_path = Path(tdir)
        if tdir_path.is_dir():
            for p in tdir_path.iterdir():
                if (p.is_symlink() and p.suffix == ".jsonl"
                        and p.name.startswith("monitor-")):
                    finalize_transcript(p)


# ---------------------------------------------------------------------------
# Poll timer integration (called from _poll_loop_state)
# ---------------------------------------------------------------------------

def poll_monitor_state(app) -> None:
    """Check monitor state and notify user as needed.

    Called from the shared 1-second poll timer in review_loop_ui.
    """
    state = app._monitor_state
    if not state:
        return

    if state.running:
        # Notify when waiting for input
        if state.input_required and not state._ui_notified_input:
            state._ui_notified_input = True
            app.log_message(
                "[red bold]!! Monitor INPUT_REQUIRED[/]: "
                "check the monitor pane for details",
                sticky=30,
            )
    elif not state._ui_notified_done:
        state._ui_notified_done = True
        verdict_icon = MONITOR_VERDICT_ICONS.get(state.latest_verdict, state.latest_verdict)
        app.log_message(
            f"Monitor stopped: {verdict_icon} "
            f"({state.iteration} iteration{'s' if state.iteration != 1 else ''})",
            sticky=10,
        )
