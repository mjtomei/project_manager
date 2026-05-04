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

from pm_core.paths import configure_logger
from pm_core import store
from pm_core.review_loop import (
    ReviewLoopState,
    start_review_loop_background,
    VERDICT_PASS,
    VERDICT_NEEDS_WORK,
    VERDICT_INPUT_REQUIRED,
)

_log = configure_logger("pm.tui.review_loop_ui")

# Icons for review verdicts (used in log line)
VERDICT_ICONS = {
    VERDICT_PASS: "[green bold]✓ PASS[/]",
    VERDICT_NEEDS_WORK: "[red bold]✗ NEEDS_WORK[/]",
    VERDICT_INPUT_REQUIRED: "[red bold]⏸ INPUT_REQUIRED[/]",
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
        # Kill the review window so the running iteration's
        # _poll_for_verdict (which doesn't check stop_requested)
        # detects pane-gone, raises PaneKilledError, and the loop
        # exits at once instead of running to completion.
        from pm_core import tmux as tmux_mod
        from pm_core.cli.helpers import _pr_display_id
        if pr and app._session_name:
            win_name = f"review-{_pr_display_id(pr)}"
            try:
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
                superseded: bool = False) -> None:
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
    """
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
        return

    # Get pm_root for launching the review window
    pm_root = str(store.find_project_root())

    # Create or reuse state
    if resume_state:
        state = resume_state
        state.stop_requested = False
        state._ui_notified_done = False
        state._ui_notified_input = False
        app._review_loops[pr_id] = state
        mode_label = f"resumed at iteration {state.iteration}"
        _log.info("review_loop_ui: resuming loop for %s at iteration %d", pr_id, state.iteration)
    else:
        state = ReviewLoopState(pr_id=pr_id)
        app._review_loops[pr_id] = state
        _log.info("review_loop_ui: starting loop for %s", pr_id)

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

    # Start the background loop
    start_review_loop_background(
        state=state,
        pm_root=pm_root,
        pr_data=pr,
        on_iteration=lambda s: _on_iteration_from_thread(app, s),
        on_complete=lambda s: _on_complete_from_thread(app, s),
        transcript_dir=transcript_dir,
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
    if not _is_active_loop(state):
        # We were superseded by a fresh loop; don't overwrite its
        # 'running' entry with our terminal (often KILLED) verdict.
        _log.debug("review_loop_ui: skipping completion mirror for "
                   "superseded loop_id=%s verdict=%s",
                   state.loop_id, state.latest_verdict)
        return
    _rs.set_action_state(state.pr_id, "review-loop", "done",
                         iteration=state.iteration,
                         verdict=state.latest_verdict)


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
        pr.get("status") in ("in_progress", "in_review", "qa") and pr.get("workdir")
        for pr in (app._data.get("prs") or [])
    )
    qa_running = any(s.running for s in app._qa_loops.values())
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
        elif not state._ui_notified_done:
            state._ui_notified_done = True
            newly_done.append(state)

    # Poll implementation pane idle state (throttled to ~every 5s)
    app._impl_poll_counter += 1
    if app._impl_poll_counter % 5 == 0:
        _poll_impl_idle(app)

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
        if state.latest_verdict == "ERROR" and state.latest_output:
            # Truncate for display but show enough to be useful
            err_text = state.latest_output[:300]
            msg += f"\n  Error: {err_text}"
            from pm_core.paths import command_log_file
            msg += f"\n  See log: {command_log_file()}"
        app.log_message(msg, sticky=10)

        # Auto-start next step: review pass → QA (then QA pass → merge)
        if state.latest_verdict == VERDICT_PASS:
            _maybe_start_qa(app, state.pr_id)

    # Stop the timer if no loops are running AND no active PRs need animation
    # AND watcher is not running
    has_active_prs = any(
        pr.get("status") in ("in_progress", "in_review", "qa") and pr.get("workdir")
        for pr in (app._data.get("prs") or [])
    )
    qa_running = any(s.running for s in app._qa_loops.values())
    watcher_running = app._watcher_manager.is_any_running()
    if not any_running and not has_active_prs and not watcher_running and not qa_running:
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
      the PR is within the target scope.

    If the project-level ``skip_qa`` setting is true, QA is skipped and
    the PR goes straight to merge.

    QA completion is handled by qa_loop_ui which triggers merge on QA PASS.
    """
    from pm_core.tui import auto_start as _auto_start

    sd = getattr(app, '_self_driving_qa', {}).get(pr_id)

    if not sd and not _auto_start.is_enabled(app):
        return

    # Scope to auto-start target's dependency tree (skip for self-driving)
    if not sd:
        target = _auto_start.get_target(app)
        if target:
            prs = app._data.get("prs") or []
            allowed = _auto_start._transitive_deps(prs, target)
            allowed.add(target)
            if pr_id not in allowed:
                return

    # If project has skip_qa enabled, skip QA and go straight to merge.
    # Merge only happens via _maybe_auto_merge (which requires
    # auto-start to be enabled) — manual zz d / zz t do not auto-merge.
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

def _maybe_auto_merge(app, pr_id: str) -> None:
    """Auto-merge a PR after a passing review/QA.

    Only runs when auto-start is enabled and the PR is in the active
    auto-start target's dependency tree.  Manual ``zz d`` / ``zz t``
    never trigger merges — merge is an auto-start-only action.

    Runs ``pm pr merge --resolve-window --background <pr_id>``
    synchronously, then triggers ``auto_start.check_and_start()`` to
    kick off newly-ready dependents.  If the merge fails (conflict),
    ``--resolve-window`` causes a Claude merge-resolution window to open;
    we register ``merge:<pr_id>`` in the idle tracker so
    ``_poll_impl_idle`` can detect when it finishes and re-attempt.
    """
    from pm_core.tui import auto_start as _auto_start
    if not _auto_start.is_enabled(app):
        return

    # Scope to auto-start target's dependency tree
    target = _auto_start.get_target(app)
    if target:
        prs = app._data.get("prs") or []
        allowed = _auto_start._transitive_deps(prs, target)
        allowed.add(target)
        if pr_id not in allowed:
            return

    # Auto-sequence keypress: stop before merge.
    if pr_id in getattr(app, "_stop_before_merge", set()):
        _log.info("auto_merge: %s in stop_before_merge — skipping merge", pr_id)
        app.log_message(
            f"[green bold]✓ {pr_id} ready to merge[/] "
            f"(auto-sequence armed — press 'g' to merge)"
        )
        return

    _log.info("auto_merge: review passed for %s, merging", pr_id)
    app.log_message(f"Auto-merge: {pr_id} review passed, merging")

    if _attempt_merge(app, pr_id, resolve_window=True):
        _log.info("auto_merge: %s merged, starting dependents", pr_id)
        app.run_worker(_auto_start.check_and_start(app))
    else:
        # Merge failed (conflict) — a resolve window was launched.
        # Mark for idle tracking so _poll_impl_idle discovers the pane
        # and re-attempts the merge after Claude resolves.
        _log.info("auto_merge: %s merge failed, tracking merge window", pr_id)
        app._pending_merge_prs.add(pr_id)


# ---------------------------------------------------------------------------
# Merge attempt (initial auto-merge after review passes)
# ---------------------------------------------------------------------------

def _attempt_merge(app, pr_id: str, *, resolve_window: bool = False,
                    propagation_only: bool = False) -> bool:
    """Run ``pm pr merge --background`` and return True if merged.

    Args:
        resolve_window: If True, pass ``--resolve-window`` so a Claude
            merge-resolution window opens on conflict.  Used by
            ``_maybe_auto_merge`` for the initial merge attempt.
            Verdict-detected finalization and idle fallback pass False
            to prevent cascading windows.
        propagation_only: If True, pass ``--propagation-only`` to skip
            the workdir merge and go straight to the pull-into-repo-dir
            step (step 2 of two-step merge).
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
        tmux_mod.kill_window(session, window_name)
        _log.info("killed merge window %s for %s", window_name, pr_id)


# ---------------------------------------------------------------------------
# Merge verdict finalization
# ---------------------------------------------------------------------------

def _finalize_detected_merge(app, pr_id: str, merge_key: str,
                             tracker, pending_merges: set,
                             active_merge_keys: set) -> None:
    """Finalize a merge after MERGED verdict is detected from the pane.

    Two-phase logic:
    - Step 1 MERGED (not in _merge_propagation_phase): Kill current merge
      window, attempt propagation (--propagation-only --resolve-window).
      If that succeeds immediately, clean up. Otherwise add to propagation
      phase for step 2.
    - Step 2 MERGED (in _merge_propagation_phase): Kill current merge
      window, attempt propagation (--propagation-only, no resolve window).
      Clean up regardless.
    """
    # Clear merge input_required state if it was set
    app._merge_input_required_prs.discard(pr_id)

    # Kill the current merge window and clean up tracker state
    _kill_merge_window(app, pr_id)
    tracker.unregister(merge_key)
    active_merge_keys.discard(merge_key)

    in_propagation = pr_id in app._merge_propagation_phase

    if not in_propagation:
        # Step 1 just completed — attempt propagation with resolve_window
        _log.info("merge_verdict: step 1 MERGED for %s, attempting propagation", pr_id)
        app.log_message(f"Step 1 merged for {pr_id}, propagating to repo dir")

        if _attempt_merge(app, pr_id, propagation_only=True, resolve_window=True):
            # Propagation succeeded immediately
            _log.info("merge_verdict: %s propagation succeeded, fully merged", pr_id)
            app.log_message(f"[green bold]✓ Merged[/] {pr_id} (conflict resolved by Claude)")
            pending_merges.discard(pr_id)
            from pm_core.tui import auto_start as _auto_start
            app.run_worker(_auto_start.check_and_start(app))
        else:
            # Propagation failed — a resolve window was launched (step 2)
            _log.info("merge_verdict: %s propagation needs resolution (step 2)", pr_id)
            app._merge_propagation_phase.add(pr_id)
            # Keep in pending_merges so idle tracker picks up the new window
    else:
        # Step 2 just completed — attempt propagation WITHOUT resolve_window
        _log.info("merge_verdict: step 2 MERGED for %s, finalizing propagation", pr_id)
        app.log_message(f"Step 2 merged for {pr_id}, finalizing")

        if _attempt_merge(app, pr_id, propagation_only=True, resolve_window=False):
            _log.info("merge_verdict: %s fully merged after step 2", pr_id)
            app.log_message(f"[green bold]✓ Merged[/] {pr_id} (conflict resolved by Claude)")
        else:
            _log.warning("merge_verdict: propagation failed for %s after step 2 MERGED", pr_id)
            app.log_message(
                f"[yellow]Warning:[/] propagation failed for {pr_id} — "
                f"run 'pm pr merge --propagation-only {pr_id}' manually",
                sticky=30,
            )

        # Clean up regardless
        app._merge_propagation_phase.discard(pr_id)
        pending_merges.discard(pr_id)
        # check_and_start returns early if auto-start is off or merge failed
        from pm_core.tui import auto_start as _auto_start
        app.run_worker(_auto_start.check_and_start(app))


def _handle_merge_input_required(app, pr_id: str, merge_key: str) -> None:
    """Handle INPUT_REQUIRED verdict from a merge window.

    Marks the PR as needing human input for merge resolution.  The user
    should interact with Claude directly in the merge window pane.
    After the user helps resolve, Claude will output MERGED and normal
    verdict detection will finalize.
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
    newly_idle: list[tuple[str, dict]] = []  # (pr_id, pr) pairs

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
            try:
                tracker.register(pr_id, pane_id, impl_transcript)
            except ValueError:
                # Symlink not yet created — try again next tick.
                continue

        tracker.poll(pr_id)

        # Detect newly-idle in_progress PRs for auto-review
        if status == "in_progress" and tracker.became_idle(pr_id):
            if pr.get("spec_pending"):
                # Spec generation paused for user input (ambiguity
                # resolution).  The session is waiting, not done.
                _log.info("impl_idle: %s idle but spec_pending, resetting", pr_id)
                tracker.mark_active(pr_id)
            else:
                newly_idle.append((pr_id, pr))

    # --- Second pass: merge resolution windows ---
    # Discover merge windows for ALL in_review PRs, not just
    # _pending_merge_prs.  This ensures MERGED verdict detection works
    # whether auto-start is enabled or not.
    pending_merges: set[str] = app._pending_merge_prs
    merge_pr_candidates: set[str] = set(pending_merges)

    for pr in (app._data.get("prs") or []):
        if pr.get("status") == "in_review":
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

            prop_only = pr_id in app._merge_propagation_phase
            if _attempt_merge(app, pr_id, resolve_window=False,
                              propagation_only=prop_only):
                _log.info("merge_idle: %s merged after resolution, starting dependents", pr_id)
                app._merge_propagation_phase.discard(pr_id)
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

    # Unregister PRs no longer active
    for key in tracker.tracked_keys():
        if (not key.startswith("merge:")
                and not key.startswith("review:")
                and key not in active_pr_ids):
            tracker.unregister(key)

    # Auto-start review for newly-idle implementation PRs
    if newly_idle and _auto_start.is_enabled(app):
        _auto_review_idle_prs(app, newly_idle)


def _auto_review_idle_prs(app, newly_idle: list[tuple[str, dict]]) -> None:
    """Transition newly-idle in_progress PRs to in_review and start review loops.

    Only called when auto-start is enabled. Scopes to the auto-start
    target's dependency tree when a target is set.
    """
    from pm_core.tui import auto_start as _auto_start
    from pm_core.tui import pr_view

    target = _auto_start.get_target(app)
    prs = app._data.get("prs") or []

    # Scope to target's dependency tree
    if target:
        allowed = _auto_start._transitive_deps(prs, target)
        allowed.add(target)
    else:
        allowed = None

    tdir = _auto_start.get_transcript_dir(app)

    for pr_id, pr in newly_idle:
        if allowed is not None and pr_id not in allowed:
            continue

        _log.info("auto_review: impl idle for %s, transitioning to in_review", pr_id)
        app.log_message(f"Auto-review: {pr_id} implementation idle, starting review")

        # Run `pm pr review --background <pr_id>` synchronously to
        # transition status and open the review window without stealing focus
        review_cmd = f"pr review --background {pr_id}"
        pr_view.run_command(app, review_cmd)

        # Reload state — subprocess modified project.yaml on disk
        # but _run_command_sync doesn't update in-memory data.
        try:
            app._data = store.load(app._root)
        except store.ProjectYamlParseError as e:
            _log.warning("_auto_start_single: corrupt YAML after review cmd: %s", e)
            return
        updated_pr = store.get_pr(app._data, pr_id)
        if updated_pr and updated_pr.get("status") == "in_review":
            # Start a review loop (same as _auto_start_review_loops)
            loop = app._review_loops.get(pr_id)
            if not loop:
                _start_loop(app, pr_id, updated_pr,
                             transcript_dir=str(tdir))
