"""Review loop UI integration for the TUI.

Manages starting/stopping review loops and updating the TUI display.
Multiple PRs can have loops running simultaneously.

Keybindings (mapped to the ``d`` key — "Review" — in the TUI):
  d       — Mark PR as in_review and open review window.
  z d     — If a loop is running for the selected PR, make this iteration
             the last one.  Otherwise, perform a fresh ``pr review``.
  zz d    — Start a review loop (iterates until PASS).
             If a loop is already running, make this iteration the last one.
"""

import os
import time

from rich.markup import escape

from pm_core.paths import configure_logger
from pm_core import store
from pm_core.autostart_state import held_by_text
from pm_core.review_loop import (
    ReviewLoopState,
    next_review_iteration,
    start_review_loop_background,
    _release_lease,
    VERDICT_PASS,
    VERDICT_NEEDS_WORK,
    VERDICT_INPUT_REQUIRED,
    VERDICT_BASE_CONFLICT,
    VERDICT_KILLED,
    VERDICT_LAUNCH_FAILED,
    VERDICT_HOLD,
    VERDICT_CLOSED,
    VERDICT_ERROR,
)

_log = configure_logger("pm.tui.review_loop_ui")

# Icons for review verdicts (used in log line)
VERDICT_ICONS = {
    VERDICT_PASS: "[green bold]✓ PASS[/]",
    VERDICT_NEEDS_WORK: "[red bold]✗ NEEDS_WORK[/]",
    VERDICT_INPUT_REQUIRED: "[red bold]⏸ INPUT_REQUIRED[/]",
    VERDICT_BASE_CONFLICT: "[yellow bold]⇤ BASE_CONFLICT[/]",
    VERDICT_KILLED: "[red bold]☠ KILLED[/]",
    "TIMEOUT": "[red bold]⏱ TIMEOUT[/]",
    VERDICT_ERROR: "[red bold]! ERROR[/]",
    VERDICT_LAUNCH_FAILED: "[red bold]↻ LAUNCH_FAILED[/]",
    VERDICT_HOLD: "[yellow bold]⏸ HOLD[/]",
    VERDICT_CLOSED: "[dim]· CLOSED[/]",
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
# z d  — kill running loop and open a fresh review
# ---------------------------------------------------------------------------

def stop_loop_or_fresh_review(app) -> None:
    """Handle ``z d``: stop any running loop and start a fresh review.

    Used to be "stop loop OR fresh review" — if a loop was running you
    only got the stop, no fresh review.  Now the two are combined:
    any running loop is killed (matching ``zz d``'s supersede path —
    set stop_requested + kill the review window so the running
    iteration's verdict-poll bails) and then ``review_pr(fresh=True)``
    opens a fresh review window for the user.
    """
    pr_id, pr = _get_selected_pr(app)
    if not pr_id:
        app.log_message("No PR selected")
        return

    loop = app._review_loops.get(pr_id)
    if loop and loop.running:
        loop.stop_requested = True
        # Hand the cross-driver launch lease to the fresh loop now; waiting
        # for the old thread to exit would make the new loop's first claim
        # fail against a still-live lease.
        _release_lease(loop)
        # Kill the review window so the running iteration's
        # _poll_for_verdict (which doesn't check stop_requested)
        # detects pane-gone, raises PaneKilledError, and the loop
        # exits at once instead of running to completion.
        from pm_core import tmux as tmux_mod
        from pm_core.cli.helpers import _pr_display_id
        if pr and app._session_name:
            win_name = f"review-{_pr_display_id(pr)}"
            try:
                from pm_core import home_window
                win = tmux_mod.find_window_by_name(app._session_name, win_name)
                if win:
                    home_window.park_if_on(app._session_name, win["id"])
                tmux_mod.kill_window(app._session_name, win_name)
            except Exception:
                _log.debug(
                    "review_loop_ui: kill of review window for z d failed"
                    " for %s", pr_id, exc_info=True)
        _log.info("review_loop_ui: z d killed running loop for %s", pr_id)
        app.log_message(
            f"[bold]Stopped review loop[/] for {pr_id} — opening fresh review")

    from pm_core.tui import pr_view
    pr_view.review_pr(app, fresh=True)


# ---------------------------------------------------------------------------
# zz d  — start or stop loop
# ---------------------------------------------------------------------------

def start_or_stop_loop(app) -> None:
    """Handle ``zz d``: always start a fresh review loop.

    Previously this toggled — pressing ``zz d`` while a loop ran would
    stop it.  That left no way to restart a loop without first
    cancelling, and it wasn't obvious that ``zz d`` cancelled rather
    than restarted.  Behavior now matches ``z d`` (fresh review): if a
    loop is already running for the same PR, we set its
    ``stop_requested`` flag and **kill the review window** so the
    iteration's verdict-poll detects pane-gone and bails immediately
    (rather than running to completion before checking the flag).
    Then a fresh loop starts.

    Cancelling a loop is now done via TUI restart (which sweeps the
    in-memory loop registry on remount) or by Ctrl+C in the loop's
    review pane.
    """
    from pm_core.tui import auto_start as _auto_start

    pr_id, pr = _get_selected_pr(app)
    if not pr_id:
        app.log_message("No PR selected")
        return

    existing = app._review_loops.get(pr_id)
    superseded = bool(existing and existing.running)
    if superseded:
        existing.stop_requested = True
        # Release the old loop's launch lease immediately so the new loop's
        # first claim does not lose to a loop that is already stopping.
        _release_lease(existing)
        # Force the running iteration to terminate now: the
        # _run_claude_review path blocks in _poll_for_verdict (which
        # doesn't check stop_requested) until the pane is gone.
        # Killing the review window makes that poll return None →
        # PaneKilledError → the loop exits.
        from pm_core import tmux as tmux_mod
        from pm_core.cli.helpers import _pr_display_id
        if pr and app._session_name:
            win_name = f"review-{_pr_display_id(pr)}"
            try:
                from pm_core import home_window
                win = tmux_mod.find_window_by_name(app._session_name, win_name)
                if win:
                    home_window.park_if_on(app._session_name, win["id"])
                tmux_mod.kill_window(app._session_name, win_name)
            except Exception:
                _log.debug("review_loop_ui: kill of review window for"
                           " supersede failed for %s", pr_id,
                           exc_info=True)
        _log.info("review_loop_ui: superseding running loop for %s "
                  "with a fresh one", pr_id)

    _start_loop(app, pr_id, pr,
                transcript_dir=str(_auto_start.get_transcript_dir(app)),
                superseded=superseded)


# ---------------------------------------------------------------------------
# Core start / stop
# ---------------------------------------------------------------------------

def _start_loop(app, pr_id: str, pr: dict | None,
                transcript_dir: str,
                resume_state: ReviewLoopState | None = None,
                superseded: bool = False) -> bool:
    """Start a review loop for the given PR.

    ``transcript_dir`` is required — hook-driven verdict polling needs a
    per-iteration JSONL transcript.  Callers resolve it via
    :func:`pm_core.tui.auto_start.get_transcript_dir` which is total
    (lazily synthesises a ``manual-<token>`` run dir when auto-start
    isn't active).

    When *resume_state* is provided, the loop continues from the saved
    iteration count and history instead of starting fresh.  Used by
    breadcrumb restoration after merge-triggered TUI restarts.

    Pass ``superseded=True`` when a previously-running loop for this
    PR was killed to make room for this one — only changes the
    user-visible status message so it's clear this is a fresh restart
    rather than a brand-new launch.

    Returns False when the loop was not started (missing PR/workdir, no
    tmux, unusable transcript dir) so callers that pre-cleared retry state
    can restore it instead of stranding the target.
    """
    from pm_core import tmux as tmux_mod

    if not pr:
        app.log_message(f"PR {pr_id} not found")
        return False

    if not tmux_mod.in_tmux():
        app.log_message("Review loop requires tmux. Use 'pm session' to start.")
        return False

    workdir = pr.get("workdir")
    if not workdir:
        app.log_message(f"No workdir for {pr_id}. Start the PR first.")
        return False

    # A base-conflict return owns the PR: implementation must reconcile the
    # base before any reviewer runs.  (The pre-review gate would refuse the
    # launch anyway; skipping here avoids a wasted loop start/log line.)
    from pm_core import base_check
    if base_check.has_open_return(pr):
        # A stale callback may have written in_review before the return
        # landed.  The base-return completion handoff only polls
        # in_progress PRs, so leaving the status behind would strand the
        # rework: no reviewer runs and nothing ever re-checks the base.
        base_check.ensure_impl_status(app._root, pr_id)
        app.log_message(
            f"{pr_id}: base integration rework pending — review not started",
            force=True)
        _log.info("_start_loop: %s has an open base return; not starting", pr_id)
        return False

    # Ensure the transcript directory exists on disk.  Fail fast here
    # (before launching a podman container + review pane) if creation
    # fails — better than surfacing the error after the pane is up.
    try:
        from pathlib import Path as _Path
        _Path(transcript_dir).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        app.log_message(
            f"[red]Cannot create transcript dir[/] {transcript_dir}: {e}"
        )
        _log.warning("_start_loop: mkdir %s failed: %s", transcript_dir, e)
        return False

    # Get pm_root for launching the review window
    pm_root = str(store.find_project_root())

    # Create or reuse state
    if resume_state:
        state = resume_state
        state.stop_requested = False
        state._ui_notified_done = False
        state._ui_notified_input = False
        # ``_ui_notified_retry`` is deliberately *not* reset here: it is
        # persisted in the breadcrumb so a merge restart mid-episode does
        # not re-announce a retry the user already saw.  It is cleared at
        # each new retry episode's start (``_clear_launch_failure``), and
        # the auto-start re-arm clears it explicitly.
        app._review_loops[pr_id] = state
        _log.info("review_loop_ui: resuming loop for %s at iteration %d", pr_id, state.iteration)
    else:
        # Continue after the PR's existing iteration transcripts so a
        # re-review (base return, sign-off bounce, restart) never
        # overwrites earlier evidence; carry a completed in-memory state's
        # history across the handoff too.
        start_iter = next_review_iteration(transcript_dir, pr_id)
        state = ReviewLoopState(pr_id=pr_id, iteration=start_iter,
                                adopt_in_flight=False)
        old = app._review_loops.get(pr_id)
        if old is not None and not old.running and old.history:
            state.history = list(old.history)
            state.iteration = max(state.iteration, old.iteration)
        app._review_loops[pr_id] = state
        _log.info("review_loop_ui: starting loop for %s at iteration %d",
                  pr_id, state.iteration)

    if superseded:
        msg = (f"[bold]Fresh review loop started[/] for {pr_id} "
               f"loop={state.loop_id}")
    elif resume_state:
        msg = (f"[bold]Review loop resumed[/] for {pr_id} "
               f"at iteration {state.iteration} loop={state.loop_id}")
    else:
        msg = (f"[bold]Review loop started[/] for {pr_id} "
               f"loop={state.loop_id}")
    app.log_message(msg, sticky=3)

    # Ensure the poll timer is running
    _ensure_poll_timer(app)

    # Persist to the shared runtime state so external readers (popup
    # picker, status spinner) can see the loop is active.
    from pm_core import runtime_state as _rs
    _rs.set_action_state(pr_id, "review-loop", "running",
                         iteration=state.iteration,
                         loop_id=state.loop_id)

    # Start the background loop.  Mark it running *synchronously* before the
    # thread is created: the 1 s poll (and a second starter, e.g. the
    # breadcrumb resume after `check_and_start` re-armed the same loop) would
    # otherwise see a non-running loop for a tick, re-announce a stale
    # terminal verdict, or start a duplicate loop thread.
    state.running = True
    try:
        start_review_loop_background(
            state=state,
            pm_root=pm_root,
            pr_data=pr,
            on_iteration=lambda s: _on_iteration_from_thread(app, s),
            on_complete=lambda s: _on_complete_from_thread(app, s),
            transcript_dir=transcript_dir,
        )
    except Exception:
        # The thread never started (e.g. resource exhaustion).  Leaving
        # ``running`` set would make the poller and the auto-start scheduler
        # treat a dead loop as live and never retry it.
        state.running = False
        raise
    return True


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
    from pm_core import runtime_state as _rs
    if not _is_active_loop(state):
        _log.debug("review_loop_ui: skipping iteration mirror for "
                   "superseded loop_id=%s", state.loop_id)
        return
    _rs.set_action_state(state.pr_id, "review-loop", "running",
                         iteration=state.iteration,
                         loop_id=state.loop_id,
                         verdict=state.latest_verdict)


def _on_complete_from_thread(app, state: ReviewLoopState) -> None:
    """Called from the background thread when the loop finishes."""
    _log.info("review_loop_ui: loop complete for %s — verdict=%s iterations=%d",
              state.pr_id, state.latest_verdict, state.iteration)

    # Finalize review transcript symlinks for this loop's iterations.
    # Done before the supersede check because the transcripts are this
    # loop's own work — they need finalizing whether or not we still
    # own the runtime_state entry.
    tdir = getattr(state, '_transcript_dir', None)
    if tdir:
        from pathlib import Path
        from pm_core.claude_launcher import finalize_transcript
        tdir_path = Path(tdir)
        if tdir_path.is_dir():
            for p in tdir_path.iterdir():
                if (p.is_symlink() and p.suffix == ".jsonl"
                        and p.name.startswith(f"review-{state.pr_id}-")):
                    finalize_transcript(p)

    from pm_core import runtime_state as _rs
    # Release this loop's cross-driver launch lease (only if we still hold
    # it; a superseding loop owns its own).
    _release_lease(state)
    if not _is_active_loop(state):
        # We were superseded by a fresh loop; don't overwrite its
        # 'running' entry with our terminal (often KILLED) verdict.
        _log.debug("review_loop_ui: skipping completion mirror for "
                   "superseded loop_id=%s verdict=%s",
                   state.loop_id, state.latest_verdict)
        return
    # ERROR/KILLED/LAUNCH_FAILED/HOLD are runtime failures, not clean
    # completions; record them as state="failed" so the popup spinner can
    # distinguish a successful loop end from a failure and surface the
    # verdict to the user instead of silently dismissing.
    final_state = ("failed"
                   if state.latest_verdict in (
                       VERDICT_ERROR, VERDICT_KILLED, VERDICT_LAUNCH_FAILED,
                       VERDICT_HOLD)
                   else "done")
    extras = {
        "iteration": state.iteration,
        "verdict": state.latest_verdict,
    }
    if state.latest_verdict == VERDICT_LAUNCH_FAILED:
        extras.update(
            retryable=bool(getattr(state, "launch_retryable", False)),
            attempts=int(getattr(state, "launch_attempts", 0) or 0),
            error=getattr(state, "last_launch_error", "") or "",
            artifact=getattr(state, "last_launch_artifact", None),
            retry_ready_at=getattr(state, "retry_ready_at", 0.0) or 0.0,
        )
    elif state.latest_verdict == VERDICT_HOLD:
        # The hold's own message (the trust/permission prompt) — not a stale
        # launch error from an earlier attempt of the same episode.  The
        # artifact and the re-arm deadline belong to that failed attempt,
        # not to a hold, so they are dropped with it.
        extras.update(
            retryable=False,
            error=(state.latest_output
                   or getattr(state, "last_launch_error", "") or ""),
            artifact=None,
            retry_ready_at=None,
        )
    else:
        # A clean (or non-launch-failure) completion must not leave a prior
        # episode's retry evidence in runtime_state, or `pm autostart
        # status` / the runs popup would keep reporting a stale artifact.
        extras.update(retryable=None, attempts=None, error=None,
                      artifact=None, retry_ready_at=None)
    _rs.set_action_state(state.pr_id, "review-loop", final_state, **extras)


def _is_active_loop(state: ReviewLoopState) -> bool:
    """True when the recorded loop_id in runtime_state still matches.

    A loop superseded by ``start_or_stop_loop`` keeps running its
    background thread until it hits a checkpoint, then fires its
    completion callback.  By that time runtime_state holds the new
    loop's loop_id; comparing IDs lets the old callbacks bow out
    instead of clobbering the new entry.
    """
    from pm_core import runtime_state as _rs
    cur = _rs.get_action_state(state.pr_id, "review-loop")
    cur_id = cur.get("loop_id")
    # If nothing's recorded yet, this loop is the only candidate; allow
    # the write so iteration mirrors still work for the very first
    # iteration after a restart.
    return not cur_id or cur_id == state.loop_id


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
        pr.get("status") in ("in_progress", "in_review", "qa", "sign_off") and pr.get("workdir")
        for pr in (app._data.get("prs") or [])
    )
    # A held QA run (waiting for INPUT_REQUIRED follow-up) has
    # ``running=False`` but still needs the poll timer to collect its
    # follow-up and process the reopened result.
    qa_running = any(s.running or s.held for s in app._qa_loops.values())
    if has_active or any(s.running for s in app._review_loops.values()) or qa_running:
        _ensure_poll_timer(app)


def _poll_loop_state(app) -> None:
    """Periodic timer callback to update TUI from loop state."""
    try:
        _poll_loop_state_inner(app)
    except SystemExit as e:
        import traceback
        from pm_core.paths import configure_logger
        _log = configure_logger("pm.tui.poll")
        _log.error("_poll_loop_state raised SystemExit(%s):\n%s", e.code, traceback.format_exc())
    except BaseException as e:
        import traceback
        from pm_core.paths import configure_logger
        _log = configure_logger("pm.tui.poll")
        _log.error("_poll_loop_state raised %s:\n%s", type(e).__name__, traceback.format_exc())
        raise


def _retry_backoff_pending(state) -> bool:
    """Whether *state* is sleeping out a failed-launch retry backoff.

    ``next_retry_at`` is set to a future timestamp when a failed launch
    schedules its retry and cleared when an attempt succeeds or a new
    episode starts, so a future value means the next attempt has not been
    launched yet.
    """
    try:
        return float(getattr(state, "next_retry_at", 0.0) or 0.0) > time.time()
    except (TypeError, ValueError):
        return False


def _poll_loop_state_inner(app) -> None:
    """Inner implementation of poll loop state."""
    any_running = False
    newly_done = []

    for pr_id, state in list(app._review_loops.items()):
        if state.running:
            any_running = True
            # Notify user when waiting for input (throttled via _ui_notified flags)
            if state.input_required and not state._ui_notified_input:
                state._ui_notified_input = True
                app.log_message(
                    f"[red bold]⏸ INPUT_REQUIRED[/] for {state.pr_id}: "
                    f"interact with Claude in the review pane",
                    sticky=30,
                )
            # A failed launch that is being retried: surface each new
            # attempt (bounded, so this cannot spam forever).  Gated on a
            # recorded error so a normal first attempt (which also has
            # launch_attempts == 1) is never announced as a retry.  The
            # recorded error belongs to the attempt that just failed, not
            # to the one starting now, so it is labelled as the previous
            # failure rather than reading as this attempt's outcome.
            #
            # While the loop waits out a retry backoff, ``launch_attempts``
            # still names the attempt that just failed and ``next_retry_at``
            # is in the future; the upcoming attempt is ``attempts + 1``.
            # Announce it then rather than waiting to observe the
            # incremented counter: an attempt that starts and fails inside
            # one poll tick (a container launch that dies in milliseconds)
            # would otherwise never be announced — QA saw the final
            # attempt-3 notice silently swallowed on every exhausted episode.
            attempts = int(getattr(state, "launch_attempts", 0) or 0)
            err = (getattr(state, "last_launch_error", "") or "").strip()
            upcoming = (attempts + 1 if _retry_backoff_pending(state)
                        else attempts)
            if upcoming > 1 and err \
                    and upcoming != state._ui_notified_retry:
                state._ui_notified_retry = upcoming
                # ``err`` is the launch child's own stderr: the log line is
                # Rich markup, so escape it — an unescaped ``[podman]`` is
                # swallowed and an unbalanced tag raises MarkupError (which
                # log_message drops), silently hiding the failure.
                msg = (f"[yellow]Review launch retry[/] for {state.pr_id} "
                       f"(attempt {upcoming}; attempt {upcoming - 1} failed: "
                       f"{escape(err[:200])})")
                artifact = getattr(state, "last_launch_artifact", None)
                if artifact:
                    msg += f"\n  Artifact: {escape(str(artifact))}"
                app.log_message(msg, sticky=15)
        elif not state._ui_notified_done:
            state._ui_notified_done = True
            newly_done.append(state)

    # Poll implementation pane idle state (throttled to ~every 5s)
    app._impl_poll_counter += 1
    if app._impl_poll_counter % 5 == 0:
        _poll_impl_idle(app)
        # Sign-off verdicts (auto-start only), same cadence
        from pm_core.tui import signoff_ui
        signoff_ui.advance_all(app)

    # Poll watcher loop state
    from pm_core.tui.watcher_ui import poll_watcher_state
    poll_watcher_state(app)

    # Poll QA loop state
    from pm_core.tui.qa_loop_ui import poll_qa_state
    poll_qa_state(app)

    # Refresh tech tree to update ⟳N markers on PR nodes
    _refresh_tech_tree(app)

    # Announce completed loops and auto-merge passing PRs
    for state in newly_done:
        verdict_icon = VERDICT_ICONS.get(state.latest_verdict, state.latest_verdict)
        msg = (
            f"Review loop done for {state.pr_id}: {verdict_icon} "
            f"({state.iteration} iteration{'s' if state.iteration != 1 else ''})"
        )
        if state.latest_verdict in (VERDICT_ERROR, VERDICT_LAUNCH_FAILED,
                                    VERDICT_HOLD) and state.latest_output:
            # Truncate for display but show enough to be useful.  Escaped:
            # the output is the child's own stderr and this line is Rich
            # markup (see the retry notice above).
            err_text = escape(state.latest_output[:300])
            msg += f"\n  Error: {err_text}"
            # The artifact belongs to a *failed launch attempt*.  A HOLD is
            # the trust/permission prompt the pane sits at (latest_output);
            # attaching an earlier attempt's artifact would point a human at
            # the wrong evidence — the runtime_state mirror and
            # `pm autostart status` already drop it for a hold.
            if state.latest_verdict == VERDICT_LAUNCH_FAILED:
                artifact = getattr(state, "last_launch_artifact", None)
                if artifact:
                    msg += f"\n  Artifact: {escape(str(artifact))}"
            from pm_core.paths import command_log_file
            msg += f"\n  See log: {command_log_file()}"
            if state.latest_verdict == VERDICT_LAUNCH_FAILED:
                if getattr(state, "launch_retryable", False):
                    if _retry_rearm_applies(app, state):
                        msg += ("\n  Will retry automatically; a manual "
                                "'review-loop start' also retries.")
                    else:
                        # Auto-start is not managing this PR (manual loop,
                        # out of scope, disabled, or the episode cap): nothing
                        # will re-arm it, so do not promise an automatic retry.
                        msg += ("\n  Run 'review-loop start' to retry "
                                "(auto-start is not retrying this PR).")
                else:
                    msg += "\n  Needs attention before it can be retried."
        app.log_message(msg, sticky=10)

        # A retryable launch failure must not strand an auto-start target:
        # schedule one scheduler pass after the cooldown.  Cancellation,
        # holds and non-retryable failures never re-arm.
        if state.latest_verdict == VERDICT_LAUNCH_FAILED \
                and getattr(state, "launch_retryable", False):
            _schedule_retry_rearm(app, state)

        # Auto-start next step: review pass → QA (then QA pass → merge)
        if state.latest_verdict == VERDICT_PASS:
            _maybe_start_qa(app, state.pr_id)

    # Stop the timer if no loops are running AND no active PRs need animation
    # AND watcher is not running
    has_active_prs = any(
        pr.get("status") in ("in_progress", "in_review", "qa", "sign_off") and pr.get("workdir")
        for pr in (app._data.get("prs") or [])
    )
    qa_running = any(s.running or s.held for s in app._qa_loops.values())
    watcher_running = app._watcher_manager.is_any_running()
    if not any_running and not has_active_prs and not watcher_running and not qa_running:
        if app._review_loop_timer:
            app._review_loop_timer.stop()
            app._review_loop_timer = None


def _retry_rearm_applies(app, state: ReviewLoopState) -> bool:
    """Whether auto-start will re-arm this loop after its cooldown.

    Only auto-start targets re-arm, and only while the episode cap allows
    another one; a manual loop (or one outside the target set) keeps its
    explicit retryable failure for the user.
    """
    from pm_core.tui import auto_start as _auto_start
    try:
        if not _auto_start.is_enabled(app) \
                or not _auto_start.in_scope(app, state.pr_id):
            return False
    except Exception:
        return False
    episodes = int(getattr(state, "retry_episodes", 0) or 0)
    return episodes < _auto_start.MAX_REVIEW_LAUNCH_RETRY_EPISODES


def _schedule_retry_rearm(app, state: ReviewLoopState) -> None:
    """Run one auto-start pass when a retryable launch failure may re-arm.

    The TUI has no periodic auto-start pass; without this a target whose
    review launch exhausted its bounded retries would sit until an
    unrelated event (the original bug).  Only auto-start targets re-arm;
    manual loops keep the explicit failure for the user.
    """
    if not _retry_rearm_applies(app, state):
        return
    from pm_core.tui import auto_start as _auto_start
    set_timer = getattr(app, "set_timer", None)
    if set_timer is None or getattr(app, "_review_retry_timer", None) is not None:
        return
    delay = max(1.0, (getattr(state, "retry_ready_at", 0.0) or 0.0)
                - time.time())

    def _fire():
        app._review_retry_timer = None
        try:
            app.run_worker(_auto_start.check_and_start(app))
        except Exception:
            _log.exception("review_loop_ui: retry re-arm pass failed")

    app._review_retry_timer = set_timer(delay, _fire)


def _refresh_tech_tree(app) -> None:
    """Refresh the tech tree so ⟳N markers and spinners update on PR nodes.

    Only the active node widgets are repainted (not the whole tree), so the
    1 s poll tick no longer pays for a full ~120-node grid render.
    """
    try:
        from pm_core.tui.tech_tree import TechTree
        tree = app.query_one("#tech-tree", TechTree)
        tree.advance_animation()
        tree.refresh_active_nodes()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Auto-QA after passing review
# ---------------------------------------------------------------------------

def _maybe_start_qa(app, pr_id: str) -> None:
    """Transition a PR from in_review → qa and start QA.

    Called when review passes.  Works in two modes:

    - **Self-driving QA** (``zz t``): always transitions,
      independent of auto-start.  The self-driving NEEDS_WORK path starts
      a review loop directly, so the review→QA transition must also be
      independent.
    - **Auto-start mode**: only transitions if auto-start is enabled and
      the PR is within some target's dependency closure.

    If the project-level ``skip_qa`` setting is true, QA is skipped and
    the PR goes straight to sign-off (via ``_maybe_auto_merge``'s gate).

    QA completion is handled by qa_loop_ui which hands a QA PASS to
    sign-off; only a fresh SIGNOFF_MERGE reaches the merge.
    """
    from pm_core.tui import auto_start as _auto_start

    sd = getattr(app, '_self_driving_qa', {}).get(pr_id)

    if not sd and not _auto_start.is_enabled(app):
        return

    # Scope to the union of the auto-start targets' dependency closures
    # (skip for self-driving)
    if not sd and not _auto_start.in_scope(app, pr_id):
        return

    # If project has skip_qa enabled, skip QA.  _maybe_auto_merge (which
    # requires auto-start — manual zz d / zz t do not auto-merge) hands the
    # PR to sign-off: its gate never merges without a fresh SIGNOFF_MERGE.
    project = (app._data or {}).get("project") or {}
    if project.get("skip_qa"):
        _log.info("auto_qa: skip_qa enabled, skipping QA for %s", pr_id)
        app.log_message(f"Auto-start: {pr_id} review passed, skipping QA (skip_qa enabled)")
        _maybe_auto_merge(app, pr_id)
        return

    # Transition PR status to "qa"
    if app._root:
        transitioned = False

        def apply_qa(data):
            nonlocal transitioned
            p = store.get_pr(data, pr_id)
            if p and p.get("status") == "in_review":
                p["status"] = "qa"
                transitioned = True

        try:
            store.locked_update(app._root, apply_qa)
        except (store.StoreLockTimeout, store.ProjectYamlParseError) as e:
            app.log_message(f"Error: {e}")
            _log.warning("auto_qa: %s for %s: %s", type(e).__name__, pr_id, e)
            return
        app._load_state()
        if transitioned:
            _log.info("auto_qa: transitioned %s to qa status", pr_id)
            app.log_message(f"Auto-QA: {pr_id} review passed, starting QA")

            # Start QA loop
            from pm_core.tui import qa_loop_ui
            qa_loop_ui.start_qa(app, pr_id)
        else:
            current = store.get_pr(app._data, pr_id)
            _log.debug("auto_qa: %s not in_review (status=%s), skipping",
                       pr_id, current.get("status") if current else "missing")


# ---------------------------------------------------------------------------
# Auto-merge passing reviews
# ---------------------------------------------------------------------------

def _signoff_gate(app, pr_id: str) -> tuple[str | None, str | None, dict]:
    """``(sha, refusal, pr)`` for *pr_id* re-read from disk.

    *refusal* is :func:`pm_core.signoff.merge_gate_refusal` — the exact
    ``pm pr merge`` sign-off gate (#226) — so auto-start never calls a merge
    that gate would refuse; None means a fresh, still-valid SIGNOFF_MERGE
    at *sha* (the current HEAD).
    """
    from pm_core import signoff as signoff_mod
    try:
        data = store.load(app._root) if app._root else app._data
    except (store.ProjectYamlParseError, OSError):
        data = app._data
    pr = store.get_pr(data or {}, pr_id) or {}
    sha = signoff_mod.head_sha(pr.get("workdir"))
    base_branch = ((data or {}).get("project") or {}).get("base_branch",
                                                         "master")
    return sha, signoff_mod.merge_gate_refusal(pr, sha, base_branch), pr


def _maybe_auto_merge(app, pr_id: str) -> None:
    """Auto-merge a signed-off PR (auto-start only).

    Only runs when auto-start is enabled and the PR is in some target's
    dependency closure.  Manual ``zz d`` / ``zz t``
    never trigger merges — merge is an auto-start-only action.

    Sign-off gate first: without a fresh ``SIGNOFF_MERGE`` on the current
    HEAD nothing merges and nothing claims "waiting for manual merge" — a
    ``qa`` (or skip_qa ``in_review``) PR is handed to the sign-off step
    instead, and a ``sign_off`` PR is left to the sign-off driver
    (``signoff_ui``).

    Then the effective merge hold (``auto_start.merge_hold``: a
    ``wait_for_merge`` target whose closure contains the PR) stops with the
    "waiting for manual merge" line; otherwise runs
    ``pm pr merge --resolve-window --background <pr_id>`` synchronously,
    then triggers ``auto_start.check_and_start()`` to kick off newly-ready
    dependents.  The merge only publishes the signed-off candidate: if the
    PR or base moved it refuses and invalidates the approval, and the
    sign-off driver re-runs sign-off (the hold, if any, applies again to the
    new approval).  Only a post-publish failure to update the main repo
    opens a (recovery) merge window; then ``merge:<pr_id>`` is tracked so
    ``_poll_impl_idle`` finalizes once it reports MERGED.
    """
    from pm_core.tui import auto_start as _auto_start
    if not _auto_start.is_enabled(app):
        return

    # Scope to the union of the targets' dependency closures
    if not _auto_start.in_scope(app, pr_id):
        return

    sha, refusal, pr = _signoff_gate(app, pr_id)
    if refusal:
        status = pr.get("status")
        if status in ("qa", "in_review"):
            from pm_core.tui import signoff_ui
            signoff_ui.start_signoff(app, pr_id)
        elif status == "sign_off" and (pr.get("signoff") or {}).get(
                "verdict") == "SIGNOFF_MERGE":
            # Signed off, yet the gate refuses (e.g. a manual approval whose
            # report.html changed since, or one targeting another base
            # branch): only a human can re-approve.  Stale / invalidated /
            # legacy approvals never get here — the driver re-runs those.
            # The sign-off driver calls here once per (verdict, sha, policy).
            _log.info("auto_merge: %s refused by sign-off gate: %s",
                      pr_id, refusal)
            app.log_message(f"[yellow]Not merging {pr_id}:[/] {refusal}",
                            sticky=30)
        else:
            _log.info("auto_merge: %s has no fresh SIGNOFF_MERGE (status=%s) "
                      "— not merging", pr_id, status)
        return

    # Effective merge hold: a wait-for-merge target needing this PR.  It
    # wins even when an auto-merge target depends on this PR.
    hold = _auto_start.merge_hold(app, pr_id)
    if hold:
        _log.info("auto_merge: %s held (%s) — skipping merge", pr_id,
                  held_by_text(hold))
        # The wait line is printed once per (verdict, sha, policy) and is
        # the user's cue to press g, so force it past a sticky message (e.g.
        # "Review loop done" right before a fast skip_qa sign-off) and hold
        # it against same-frame follow-ons (another target's merge lines).
        tail = ("waiting for manual merge (wait-for-merge: "
                f"{', '.join(hold['targets'])}) — press 'g' to merge")
        app.log_message(
            f"[green bold]✓ {pr_id} signed off[/] (SIGNOFF_MERGE @ {sha[:8]}) "
            f"— {tail}",
            force=True, hold=_auto_start.CONFIRM_HOLD_SECONDS,
        )
        return

    _log.info("auto_merge: %s signed off, merging", pr_id)
    app.log_message(f"Auto-merge: {pr_id} signed off, merging")

    if _attempt_merge(app, pr_id, resolve_window=True):
        _log.info("auto_merge: %s merged, starting dependents", pr_id)
        app.run_worker(_auto_start.check_and_start(app))
    elif refusal := _signoff_gate(app, pr_id)[1]:
        # The gate refused (HEAD / base / report changed since approval):
        # never a conflict to resolve here.  An invalidated approval makes
        # the sign-off driver re-run sign-off against the current base.
        _log.info("auto_merge: %s refused by sign-off gate: %s",
                  pr_id, refusal)
        app.log_message(
            f"[yellow]Merge of {pr_id} refused:[/] {refusal}")
    elif _merge_window_exists(app, pr_id):
        # Published, but updating the main repo failed: a recovery window
        # was launched.  Track it so _poll_impl_idle finalizes on MERGED.
        _log.info("auto_merge: %s published, tracking repo-update window",
                  pr_id)
        app._pending_merge_prs.add(pr_id)
    else:
        _log.info("auto_merge: %s merge failed (see command output)", pr_id)


# ---------------------------------------------------------------------------
# Merge attempt (initial auto-merge after review passes)
# ---------------------------------------------------------------------------

def _attempt_merge(app, pr_id: str, *, resolve_window: bool = False,
                    propagation_only: bool = False) -> bool:
    """Run ``pm pr merge --background`` and return True if merged.

    Args:
        resolve_window: If True, pass ``--resolve-window`` so a Claude
            recovery window opens when updating the main repo fails after
            publication (the merge itself never resolves conflicts).  Used
            by ``_maybe_auto_merge`` for the initial merge attempt.
            Verdict-detected finalization and idle fallback pass False
            to prevent cascading windows.
        propagation_only: If True, pass ``--propagation-only``: only
            finalize a merge already in the published base (update the
            main repo, mark merged); never publishes.
    """
    from pm_core.tui import auto_start as _auto_start
    from pm_core.tui import pr_view

    # Pass the flag explicitly in both directions — the in-tmux env-var
    # default would otherwise flip resolve_window=False back on.
    merge_cmd = "pr merge"
    merge_cmd += " --resolve-window" if resolve_window else " --no-resolve-window"
    if propagation_only:
        merge_cmd += " --propagation-only"
    merge_cmd += " --background"
    tdir = _auto_start.get_transcript_dir(app)
    if tdir:
        merge_cmd += f" --transcript {tdir / f'merge-{pr_id}.jsonl'}"
    merge_cmd += f" {pr_id}"
    pr_view.run_command(app, merge_cmd)

    # Reload state — subprocess modified project.yaml on disk
    try:
        app._data = store.load(app._root)
    except store.ProjectYamlParseError as e:
        _log.warning("_attempt_auto_merge: corrupt YAML after merge cmd: %s", e)
        return False
    merged_pr = store.get_pr(app._data, pr_id)
    return bool(merged_pr and merged_pr.get("status") == "merged")


def _merge_window_exists(app, pr_id: str) -> bool:
    """Whether the PR's (post-merge recovery) merge window is open."""
    from pm_core import tmux as tmux_mod
    from pm_core.cli.helpers import _pr_display_id
    session = getattr(app, "_session_name", None)
    pr = store.get_pr(app._data or {}, pr_id)
    if not session or not pr:
        return False
    try:
        return bool(tmux_mod.find_window_by_name(
            session, f"merge-{_pr_display_id(pr)}"))
    except Exception:
        return False


def _on_merge_success(app, pr_id: str, merge_key: str, tracker,
                      pending_merges: set, active_merge_keys: set) -> None:
    """Clean up tracking state and kick off dependents after a successful merge.

    Shared by MERGED verdict detection and idle-based fallback.
    """
    from pm_core.tui import auto_start as _auto_start

    pending_merges.discard(pr_id)
    tracker.unregister(merge_key)
    active_merge_keys.discard(merge_key)
    # check_and_start returns early if auto-start is off
    app.run_worker(_auto_start.check_and_start(app))


# ---------------------------------------------------------------------------
# Merge window management
# ---------------------------------------------------------------------------

def _kill_merge_window(app, pr_id: str) -> None:
    """Kill the merge tmux window for a PR.

    Uses the PR's display ID to find and kill the merge window.
    """
    from pm_core import tmux as tmux_mod
    from pm_core.cli.helpers import _pr_display_id

    session = app._session_name
    if not session:
        return

    pr = store.get_pr(app._data, pr_id)
    if not pr:
        return

    display_id = _pr_display_id(pr)
    window_name = f"merge-{display_id}"
    win = tmux_mod.find_window_by_name(session, window_name)
    if win:
        from pm_core import home_window
        home_window.park_if_on(session, win["id"])
        tmux_mod.kill_window(session, window_name)
        _log.info("killed merge window %s for %s", window_name, pr_id)


# ---------------------------------------------------------------------------
# Merge verdict finalization
# ---------------------------------------------------------------------------

def _finalize_detected_merge(app, pr_id: str, merge_key: str,
                             tracker, pending_merges: set,
                             active_merge_keys: set) -> None:
    """Finalize a merge after a recovery window reported MERGED.

    Merge windows only exist after the merge was published (updating the
    main repo failed), so MERGED means the checkout is updated: kill the
    window and run ``pm pr merge --propagation-only`` (no new window),
    which verifies the PR is in the published base before finalizing — a
    window can never get unapproved code recorded as merged.
    """
    from pm_core.tui import auto_start as _auto_start

    app._merge_input_required_prs.discard(pr_id)
    _kill_merge_window(app, pr_id)
    tracker.unregister(merge_key)
    active_merge_keys.discard(merge_key)

    _log.info("merge_verdict: MERGED for %s, finalizing", pr_id)
    if _attempt_merge(app, pr_id, propagation_only=True, resolve_window=False):
        _log.info("merge_verdict: %s fully merged", pr_id)
        app.log_message(f"[green bold]✓ Merged[/] {pr_id}")
    else:
        _log.warning("merge_verdict: finalizing %s failed", pr_id)
        app.log_message(
            f"[yellow]Warning:[/] finalizing {pr_id} failed — run "
            f"'pm pr merge --propagation-only {pr_id}' manually",
            sticky=30,
        )
    pending_merges.discard(pr_id)
    # check_and_start returns early if auto-start is off or merge failed
    app.run_worker(_auto_start.check_and_start(app))


def _handle_merge_input_required(app, pr_id: str, merge_key: str) -> None:
    """Handle INPUT_REQUIRED verdict from a merge window.

    Marks the PR as needing human input to update the main repo after a
    published merge.  The user should interact with Claude directly in the
    merge window pane.  Once fixed, Claude outputs MERGED and normal
    verdict detection finalizes.
    """
    # Track which PRs have merge input_required (for TUI display)
    app._merge_input_required_prs.add(pr_id)

    # Reset the verdict tracker so we can detect MERGED after the user helps

    app.log_message(
        f"[red bold]⏸ Merge INPUT_REQUIRED[/] for {pr_id}: "
        f"interact with Claude in the merge window to resolve",
        sticky=30,
    )


# ---------------------------------------------------------------------------
# Implementation pane idle polling
# ---------------------------------------------------------------------------

def _find_impl_pane(session: str, window_name: str) -> str | None:
    """Find the first pane ID in an implementation window."""
    from pm_core import tmux as tmux_mod
    win = tmux_mod.find_window_by_name(session, window_name)
    if not win:
        return None
    panes = tmux_mod.get_pane_indices(session, win["index"])
    if panes:
        return panes[0][0]
    return None


def _watch_untracked_trust(app, pane_id: str, workdir: str | None,
                           seen: set[str]) -> None:
    """Trust-watch a Claude pane the idle tracker could not register.

    After a TUI restart, the transcript symlinks of panes an earlier TUI
    launched live in that TUI's run dir, so the tracker (and the trust
    watch it runs) skips them.  A pane left at the workspace-trust dialog
    would then sit there forever.  Recover the session's transcript from
    the pane's start command and run a bounded watch on it: accept an
    approved workdir by cursor (the per-pane attempt budget spans
    restarts), else report once after the grace.
    """
    from pm_core.claude_launcher import (
        WorkspacePromptWatch, pane_transcript_path,
    )
    # Kept on the app across polls; created lazily so tests and callers
    # that never hit an orphan pane need no setup.
    if not hasattr(app, "_untracked_trust_watches"):
        app._untracked_trust_watches = {}
        app._untracked_trust_reported = set()
    watches = app._untracked_trust_watches
    seen.add(pane_id)
    if pane_id not in watches:
        # Resolved once per pane: None (no session id in its command)
        # and finished watches stay cached, so the steady state after a
        # restart costs no tmux call per tick.
        transcript = pane_transcript_path(pane_id, workdir)
        watches[pane_id] = transcript and WorkspacePromptWatch(
            pane_id, workdir=workdir, transcript_path=transcript)
    watch = watches[pane_id]
    if watch is None:
        return
    msg = watch.check()
    if msg and pane_id not in app._untracked_trust_reported:
        app._untracked_trust_reported.add(pane_id)
        # Skip a pane another watch in this TUI already reported (e.g. a
        # review pane whose loop ended in the trust ERROR).
        if not watch.reported_elsewhere:
            app.log_message(f"[red]{msg}[/]", sticky=30)


def _prune_untracked_trust(app, seen: set[str]) -> None:
    """Drop orphan trust watches for panes that are gone or now tracked."""
    watches = getattr(app, "_untracked_trust_watches", None) or {}
    for pane_id in list(watches):
        if pane_id not in seen:
            watches.pop(pane_id, None)
            app._untracked_trust_reported.discard(pane_id)


def _shared_impl_transcript(app, pr_id: str) -> str | None:
    """Find an ``impl-<pr>.jsonl`` link another driver already wrote.

    The restarted TUI's run dir is empty, but the project's ``transcripts/``
    tree keeps the links written by the auto-start run
    (``transcripts/<run>/``) and by the CLI driver
    (``transcripts/auto-sequence/<pr>/``).  Registering from one of them lets
    the base-rework catch-up keep watching the session the previous TUI (or
    the gate's relaunch) actually launched.  Newest link wins so a
    ``share_impl_transcript`` refresh is preferred over a stale copy.

    Best effort: returns ``None`` when no usable link exists.
    """
    import glob

    from pm_core.paths import pm_home

    root = app._root or pm_home()
    base = root / "transcripts"
    if not base.is_dir():
        return None
    name = f"impl-{pr_id}.jsonl"
    best: str | None = None
    best_mtime = -1.0
    for pattern in (f"*/{name}", f"*/*/{name}"):
        try:
            candidates = glob.glob(str(base / pattern))
        except OSError:  # pragma: no cover - best effort
            continue
        for p in candidates:
            try:
                # lstat: a refreshed link is rewritten, so its own mtime is
                # the freshness signal (getmtime would follow the shared
                # target and make every link look identical).
                mtime = os.lstat(p).st_mtime
            except OSError:
                continue
            if mtime > best_mtime:
                best, best_mtime = p, mtime
    return best


def _poll_impl_idle(app) -> None:
    """Poll implementation panes for idle detection.

    For each in_progress/in_review PR with a workdir, find its tmux
    implementation window pane and poll it via the idle tracker.
    Skip PRs that have a running review loop (they have their own spinner).

    When auto-start is enabled and an in_progress PR newly goes idle,
    automatically transition it to in_review and start a review loop.
    """
    from pm_core.cli.helpers import _pr_display_id
    from pm_core.tui import auto_start as _auto_start

    session = app._session_name
    if not session:
        return

    tracker = app._pane_idle_tracker
    active_pr_ids: set[str] = set()
    # (pr_id, pr, resume_review_loop) triples
    newly_idle: list[tuple[str, dict, bool]] = []
    untracked_seen: set[str] = set()

    for pr in (app._data.get("prs") or []):
        pr_id = pr.get("id", "")
        status = pr.get("status", "")
        if status not in ("in_progress", "in_review"):
            continue
        if not pr.get("workdir"):
            continue

        # Skip PRs with running review loops (they manage their own state)
        loop = app._review_loops.get(pr_id)
        if loop and loop.running:
            continue

        active_pr_ids.add(pr_id)
        window_name = _pr_display_id(pr)

        # Lazy pane resolution: register if not yet tracked or pane gone.
        # Hook-driven tracking requires the transcript path launched by
        # ``pm pr start --transcript``; skip PRs without one (e.g. manual
        # launches) — they won't auto-advance but also won't misfire.
        if not tracker.is_tracked(pr_id) or tracker.is_gone(pr_id):
            pane_id = _find_impl_pane(session, window_name)
            if not pane_id:
                continue
            tdir = _auto_start.get_transcript_dir(app)
            if not tdir:
                continue
            impl_transcript = str(tdir / f"impl-{pr_id}.jsonl")
            if not os.path.lexists(impl_transcript):
                # A TUI restart starts a fresh transcript run dir with no
                # links in it, so a pane launched by an earlier TUI/auto-start
                # run has nothing to register here.  An open base return then
                # has no launcher and no completion check at all unless a CLI
                # tick happens to run — the stranding R6 forbids.  Fall back
                # to the link another driver already wrote; it names the live
                # session (``share_impl_transcript`` re-points it on relaunch,
                # and a stale link's idle turn is still rejected by
                # ``impl_completion``'s post-relaunch guard).
                impl_transcript = (_shared_impl_transcript(app, pr_id)
                                   or impl_transcript)
            try:
                tracker.register(pr_id, pane_id, impl_transcript)
            except ValueError:
                # Symlink not yet created — try again next tick.  It never
                # will be for a pane an earlier TUI launched: still watch
                # that one for the trust dialog.
                _watch_untracked_trust(app, pane_id, pr.get("workdir"),
                                       untracked_seen)
                continue

        tracker.poll(pr_id)

        # Detect newly-idle in_progress PRs for auto-review
        if status == "in_progress" and tracker.is_idle(pr_id):
            from pm_core.signoff import return_awaiting
            from pm_core import base_check
            base_ret = base_check.open_return(pr)
            if return_awaiting(pr) == "impl" or (
                    base_ret is not None
                    and base_check.return_awaiting(pr) == "impl"):
                # Sent back but the rework session has not launched yet: an
                # idle (old) session is not finished work.
                if base_ret is not None:
                    # Not gated on auto-start: ``check_and_start`` only drives
                    # in-scope PRs, so for a manual loop this poll is the only
                    # driver of the relaunch.  A claim that is still held (the
                    # gate's own ``pm pr start``) or was released by a failed
                    # launch must therefore be retried later, so leave the
                    # idle state unconsumed instead of marking it active (no
                    # later hook event would undo that).
                    _catch_up_base_impl(app, pr_id)
                    _log.debug("impl_idle: %s base rework launch pending",
                               pr_id)
                else:
                    _log.info("impl_idle: %s awaiting sign-off rework launch",
                              pr_id)
                    tracker.mark_active(pr_id)
                continue
            if base_ret is not None:
                # A base-conflict return: an idle turn is not completion.
                # The integration re-check runs off the event loop; the idle
                # event is left unconsumed so a settle/background job can
                # surface before the handoff.
                ok, why, resume = _base_completion_tick(app, pr_id, pr, tracker)
                if not ok:
                    _log.debug("impl_idle: %s base rework pending: %s",
                               pr_id, why)
                    continue
                tracker.became_idle(pr_id)  # consume the verified idle
                newly_idle.append((pr_id, pr, resume))
                continue
            if tracker.became_idle(pr_id):
                if pr.get("spec_pending"):
                    # Spec generation paused for user input (ambiguity
                    # resolution).  The session is waiting, not done.
                    _log.info("impl_idle: %s idle but spec_pending, resetting", pr_id)
                    tracker.mark_active(pr_id)
                else:
                    newly_idle.append((pr_id, pr, False))

    # --- Second pass: post-publish repo-update (merge) windows ---
    # Discover merge windows for ALL in_review / sign_off PRs, not just
    # _pending_merge_prs.  This ensures MERGED verdict detection works
    # whether auto-start is enabled or not.
    pending_merges: set[str] = app._pending_merge_prs
    merge_pr_candidates: set[str] = set(pending_merges)

    for pr in (app._data.get("prs") or []):
        # A published merge whose main-repo update window is still open
        # leaves the PR in sign_off (finalize marks it merged).
        if pr.get("status") in ("in_review", "sign_off"):
            merge_pr_candidates.add(pr["id"])

    active_merge_keys: set[str] = set()

    for pr_id in list(merge_pr_candidates):
        pr = store.get_pr(app._data, pr_id)
        if not pr:
            pending_merges.discard(pr_id)
            continue
        # If already merged (e.g. manual resolution), stop tracking
        if pr.get("status") == "merged":
            pending_merges.discard(pr_id)
            merge_key = f"merge:{pr_id}"
            tracker.unregister(merge_key)
            continue

        merge_key = f"merge:{pr_id}"
        window_name = f"merge-{_pr_display_id(pr)}"

        # Lazy pane resolution — requires the merge transcript launched
        # by ``pm pr merge --resolve-window --transcript``.
        if not tracker.is_tracked(merge_key) or tracker.is_gone(merge_key):
            pane_id = _find_impl_pane(session, window_name)
            if not pane_id:
                continue
            tdir = _auto_start.get_transcript_dir(app)
            if not tdir:
                continue
            merge_transcript = str(tdir / f"merge-{pr_id}.jsonl")
            try:
                tracker.register(merge_key, pane_id, merge_transcript)
            except ValueError:
                continue

        active_merge_keys.add(merge_key)
        tracker.poll(merge_key)

        # --- Primary: check for MERGED or INPUT_REQUIRED verdict ---
        merge_transcript_path = tracker.get_transcript_path(merge_key)
        if merge_transcript_path:
            from pm_core.verdict_transcript import extract_verdict_from_transcript
            verdict = extract_verdict_from_transcript(
                merge_transcript_path, ("MERGED", "INPUT_REQUIRED"),
            )
            if verdict == "MERGED":
                _log.info("merge_verdict: MERGED detected for %s", pr_id)
                app.log_message(f"MERGED detected for {pr_id}, finalizing merge")
                _finalize_detected_merge(app, pr_id, merge_key, tracker,
                                         pending_merges, active_merge_keys)
                continue
            if verdict == "INPUT_REQUIRED":
                _log.info("merge_verdict: INPUT_REQUIRED detected for %s", pr_id)
                _handle_merge_input_required(app, pr_id, merge_key)
                continue

        # --- Fallback: idle detection (for _pending_merge_prs entries only) ---
        if pr_id not in pending_merges:
            continue

        if tracker.became_idle(merge_key):
            _log.info("merge_idle: merge window idle for %s, re-attempting merge", pr_id)
            app.log_message(f"Merge window idle for {pr_id}, re-attempting merge")

            # The merge was already published; only finalize it.
            if _attempt_merge(app, pr_id, resolve_window=False,
                              propagation_only=True):
                _log.info("merge_idle: %s merged after resolution, starting dependents", pr_id)
                _on_merge_success(app, pr_id, merge_key, tracker,
                                  pending_merges, active_merge_keys)
            # else: still not merged — keep tracking

    # --- Third pass: non-loop review windows ---
    # Track the review pane for in_review PRs that don't have a running
    # review loop, so the picker shows [working]/[idle]/[wait] and we
    # can pick up the review verdict from the transcript.
    active_review_keys: set[str] = set()
    for pr in (app._data.get("prs") or []):
        if pr.get("status") != "in_review":
            continue
        pr_id = pr.get("id", "")
        if not pr_id:
            continue
        loop = app._review_loops.get(pr_id)
        if loop and loop.running:
            continue  # loop iterations own the review window's transcript

        review_key = f"review:{pr_id}"
        window_name = f"review-{_pr_display_id(pr)}"

        if not tracker.is_tracked(review_key) or tracker.is_gone(review_key):
            pane_id = _find_impl_pane(session, window_name)
            if not pane_id:
                continue
            tdir = _auto_start.get_transcript_dir(app)
            if not tdir:
                continue
            review_transcript = str(tdir / f"review-{pr_id}.jsonl")
            try:
                tracker.register(review_key, pane_id, review_transcript)
            except ValueError:
                # e.g. a review-loop pane left in flight across a TUI
                # restart: the loop is gone but the pane may be at the
                # trust dialog.
                _watch_untracked_trust(app, pane_id, pr.get("workdir"),
                                       untracked_seen)
                continue

        active_review_keys.add(review_key)
        tracker.poll(review_key)

        # --- Mirror the review verdict ---
        review_transcript_path = tracker.get_transcript_path(review_key)
        if review_transcript_path:
            from pm_core.verdict_transcript import extract_verdict_from_transcript
            verdict = extract_verdict_from_transcript(
                review_transcript_path,
                ("LGTM", "NEEDS_WORK", "INPUT_REQUIRED"),
            )
            if verdict:
                from pm_core import runtime_state as _rs
                cur = _rs.get_action_state(pr_id, "review") or {}
                if cur.get("verdict") != verdict or cur.get("state") != "done":
                    try:
                        _rs.set_action_state(pr_id, "review", "done",
                                             verdict=verdict)
                    except Exception:
                        _log.debug("runtime_state review verdict mirror failed",
                                   exc_info=True)

    # Unregister stale merge keys and clean up verdict stability state
    for key in tracker.tracked_keys():
        if key.startswith("merge:") and key not in active_merge_keys:
            tracker.unregister(key)

    # Unregister stale review keys
    for key in tracker.tracked_keys():
        if key.startswith("review:") and key not in active_review_keys:
            tracker.unregister(key)

    # Unregister PRs no longer active.  ``qa:`` keys belong to
    # qa_loop_ui.poll_qa_state, which unregisters them when the run ends;
    # dropping them here would re-register a fresh state (and a fresh
    # workspace-trust watch with a reset accept budget) on every QA poll.
    for key in tracker.tracked_keys():
        if (not key.startswith("merge:")
                and not key.startswith("review:")
                and not key.startswith("qa:")
                and key not in active_pr_ids):
            tracker.unregister(key)

    _prune_untracked_trust(app, untracked_seen)

    # Auto-start review for newly-idle implementation PRs
    started: set[str] = set()
    if newly_idle and _auto_start.is_enabled(app):
        started = _auto_review_idle_prs(app, newly_idle)
    # A TUI review loop that was interrupted by a base-conflict return
    # resumes even without auto-start (manual ``zz d`` semantics); a
    # one-shot ``z d`` stays manual.
    for pr_id, _pr, resume in newly_idle:
        if resume and pr_id not in started:
            _resume_returned_loop(app, pr_id)


# How often the TUI re-runs the (network) base completion check for a
# returned PR whose pane is idle.  Between checks the cheap quiescence
# checks run inline.
BASE_CHECK_POLL_SECONDS = 15.0

# How often the TUI re-attempts a base rework relaunch whose claim is still
# held (the gate's own ``pm pr start`` is running) or was released by a
# failed launch.  Each attempt takes the project.yaml lock, so this is not
# retried on every 5 s poll tick.
BASE_LAUNCH_RETRY_SECONDS = 15.0


def _base_completion_tick(app, pr_id: str, pr: dict,
                          tracker) -> tuple[bool, str, bool]:
    """Evaluate a base-return handoff without blocking the event loop.

    Cheap quiescence checks run inline; the integration re-check (a fetch)
    runs in a worker thread and its result is consumed on a later tick.  The
    idle event is not consumed until the result says the rework genuinely
    finished — an idle notification while edits/background tests are still
    unfinished must not launch a review writer.
    """
    from pm_core import base_check
    from pm_core.tui import auto_start as _auto_start
    from pathlib import Path

    if not app._root:
        # Every check below (and ``impl_completion``) resolves the project
        # root; without one there is nothing to verify against.  Report it
        # rather than letting a ``None`` reach ``store.load``.
        return False, "no project root", False
    checks = getattr(app, "_base_completion_checks", None)
    if checks is None:
        checks = {}
        app._base_completion_checks = checks
    # A cached result only belongs to the return episode that produced it;
    # a new return (new ``ts``) must be checked afresh.
    ret = base_check.open_return(pr)
    episode = (ret or {}).get("ts")
    st = checks.get(pr_id) or {}
    if st.get("episode") != episode:
        st = {}
    now = time.monotonic()
    if st.get("in_flight"):
        return False, "checking base integration", False
    idle_since = tracker.idle_since(pr_id)
    if st.get("at") and now - float(st["at"]) < BASE_CHECK_POLL_SECONDS:
        # The cached verdict belongs to the idle turn it was computed for: a
        # later hook event means the implementation did more work, so the
        # verdict (and its clean workdir/HEAD) must be re-checked rather than
        # reused to start a reviewer beside a fresh turn.
        if st.get("idle_since") == idle_since:
            return (bool(st.get("ok")), st.get("reason", ""),
                    bool(st.get("resume_loop")))
        st = {}
    if idle_since is None:
        return False, "not idle", False
    if time.time() - idle_since < base_check.IDLE_SETTLE_SECONDS:
        return False, "letting the implementation settle", False
    workdir = pr.get("workdir")
    if not workdir or not Path(workdir).is_dir():
        # The git helpers run with this as their cwd; an empty *or deleted*
        # one raises (``FileNotFoundError``) rather than reporting "no
        # workdir", and this tick runs inside the shared poll timer — the
        # exception would break QA/sign-off polling for every PR too.
        return False, "no PR workdir", False
    op = base_check.git_op_in_progress(workdir)
    if op:
        return False, f"{op} still in progress", False
    if base_check.tracked_dirty(workdir):
        return False, "uncommitted edits remain", False

    # Keep the last logged verdict across the in-flight marker: the 5 s poll
    # must not re-log an unchanged reason (a new episode or a new idle turn
    # reset ``st``, so a fresh verdict is logged again).
    logged = st.get("logged_reason")
    checks[pr_id] = {**st, "in_flight": True, "started": now,
                     "episode": episode}

    def _run():
        ok, reason, resume = False, "", False
        try:
            res = base_check.impl_completion(
                app._root, pr_id, pr, idle_since=idle_since,
                transcript_dir=_auto_start.get_transcript_dir(app))
            ok, reason, resume = res.complete, res.reason, res.resume_loop
        except Exception as e:
            _log.warning("base completion check for %s failed: %s", pr_id, e)
            reason = f"completion check failed: {e}"
        if not ok and reason != logged:
            # One INFO line per distinct verdict, so an operator can see why
            # the handoff is waiting without the poll spamming the log.
            _log.info("impl_idle: %s base rework not complete: %s",
                      pr_id, reason)
        checks[pr_id] = {"in_flight": False, "at": time.monotonic(),
                         "episode": episode, "idle_since": idle_since,
                         "ok": ok, "reason": reason, "resume_loop": resume,
                         "logged_reason": reason}

    try:
        app.run_worker(_run, thread=True, exclusive=False,
                       group=f"base-check-{pr_id}")
    except Exception as e:
        # Never leave the entry in flight: every later tick would report
        # "checking base integration" and the handoff would stall until a
        # restart.  Record the failure (throttled like a real check) instead.
        _log.warning("impl_idle: could not start the base check for %s: %s",
                     pr_id, e)
        checks[pr_id] = {"in_flight": False, "at": time.monotonic(),
                         "episode": episode, "idle_since": idle_since,
                         "ok": False,
                         "reason": f"could not start the base check: {e}",
                         "resume_loop": False,
                         "logged_reason": f"could not start the base check: {e}"}
    return False, "checking base integration", False


def _catch_up_base_impl(app, pr_id: str) -> bool:
    """Relaunch a base-return rework session that no other driver claimed.

    Returns True when this call took the launch claim (a relaunch is now in
    flight).  A claim still held belongs to another launcher (the gate's own
    ``pm pr start``, which runs inside a subprocess); a claim that was
    released means that launcher failed and kept ``awaiting`` for a retry
    (``release_impl_claim``).  The idle poll is the *only* driver for a
    manual TUI session, so the caller must leave the idle state unconsumed
    when this returns False: no later hook event follows an idle old session
    to re-trigger the catch-up, and the PR would sit with no launcher and no
    completion check.

    Throttled per PR: each attempt that reaches ``claim_impl_launch`` takes
    the project.yaml lock and rewrites the (large) file.
    """
    from pm_core import base_check
    from pm_core.tui import auto_start as _auto_start

    if not app._root:
        return False
    attempts = getattr(app, "_base_launch_attempts", None)
    if not isinstance(attempts, dict):
        attempts = {}
        app._base_launch_attempts = attempts
    now = time.monotonic()
    if now - float(attempts.get(pr_id) or 0.0) < BASE_LAUNCH_RETRY_SECONDS:
        return False
    attempts[pr_id] = now
    if not base_check.claim_impl_launch(app._root, pr_id):
        return False
    tdir = _auto_start.get_transcript_dir(app)

    async def _run():
        import asyncio
        ok, detail = await asyncio.to_thread(
            base_check.launch_impl, app._root, pr_id, tdir)
        if not ok:
            app.log_message(f"{pr_id}: base rework relaunch failed: {detail}")
            return
        _log.info("impl_idle: relaunched base rework for %s", pr_id)
        # ``pm pr start`` cleared ``awaiting`` on disk.  This relaunch runs
        # in-process, so nothing else refreshes the TUI's snapshot: without
        # this the next idle tick re-enters the awaiting branch with the
        # stale marker and never reaches the completion check.
        app._load_state()

    app.run_worker(_run())
    return True


def _resume_returned_loop(app, pr_id: str) -> None:
    """Restart a TUI review loop after its base-conflict rework finished."""
    from pm_core.tui import pr_view
    from pm_core.tui import auto_start as _auto_start
    from pm_core import base_check

    if not app._root:
        return
    try:
        app._data = store.load(app._root)
    except store.ProjectYamlParseError:
        return
    pr = store.get_pr(app._data, pr_id)
    if not pr or pr.get("status") != "in_progress":
        return
    if base_check.has_open_return(pr):
        return
    # A concurrent start (the user's ``d``, a scheduler pass) may already own
    # the PR: a second loop would be a second reviewer writer on one PR.
    loop = app._review_loops.get(pr_id)
    if loop and loop.running:
        _log.info("resume_returned_loop: %s already has a running loop", pr_id)
        return
    app.log_message(f"Base rework complete for {pr_id} — resuming review loop")
    pr_view.run_command(app, f"pr review --no-window {pr_id}")
    try:
        app._data = store.load(app._root)
    except store.ProjectYamlParseError:
        return
    updated = store.get_pr(app._data, pr_id)
    if updated and updated.get("status") == "in_review":
        _start_loop(app, pr_id, updated,
                    transcript_dir=str(_auto_start.get_transcript_dir(app)))


def _auto_review_idle_prs(app, newly_idle: list[tuple[str, dict, bool]]) -> set[str]:
    """Transition newly-idle in_progress PRs to in_review and start review loops.

    Only called when auto-start is enabled. Scopes to the union of the
    auto-start targets' dependency closures.
    """
    from pm_core.tui import auto_start as _auto_start
    from pm_core.tui import pr_view

    prs = app._data.get("prs") or []
    tdir = _auto_start.get_transcript_dir(app)
    started: set[str] = set()

    for entry in newly_idle:
        # Only the PR is needed here: the resume flag on the third element is
        # consumed by the caller's ``_resume_returned_loop`` pass.
        pr_id = entry[0]
        # Scope to the union of the targets' dependency closures
        if not _auto_start.in_scope(app, pr_id, prs):
            continue

        _log.info("auto_review: impl idle for %s, transitioning to in_review", pr_id)
        app.log_message(f"Auto-review: {pr_id} implementation idle, starting review")

        # Run `pm pr review --no-window <pr_id>` synchronously to transition
        # status only.  The review loop started below launches iteration 1's
        # window itself (with --fresh); opening one here too would start a
        # throwaway Claude session that the loop kills ~0.2s later.
        review_cmd = f"pr review --no-window {pr_id}"
        pr_view.run_command(app, review_cmd)

        # Reload state — subprocess modified project.yaml on disk
        # but _run_command_sync doesn't update in-memory data.
        try:
            app._data = store.load(app._root)
        except store.ProjectYamlParseError as e:
            _log.warning("_auto_start_single: corrupt YAML after review cmd: %s", e)
            return started
        updated_pr = store.get_pr(app._data, pr_id)
        if updated_pr and updated_pr.get("status") == "in_review":
            # Start a review loop (same as _auto_start_review_loops)
            loop = app._review_loops.get(pr_id)
            if not loop:
                _start_loop(app, pr_id, updated_pr,
                             transcript_dir=str(tdir))
                started.add(pr_id)
    return started
