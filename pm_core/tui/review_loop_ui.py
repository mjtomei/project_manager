"""Review loop UI integration for the TUI.

Manages starting/stopping review loops and updating the TUI display.
Multiple PRs can have loops running simultaneously.

Keybindings (mapped to the ``d`` key — "Review" — in the TUI):
  d       — Mark PR as in_review and open review window.
  z d     — If a loop is running for the selected PR, make this iteration
             the last one.  Otherwise, perform a fresh ``pr review``.
  zz d    — Start a review loop (stops on PASS or PASS_WITH_SUGGESTIONS).
             If a loop is already running, make this iteration the last one.
  zzz d   — Start a strict review loop (stops only on full PASS).
             If a loop is already running, make this iteration the last one.
"""

from pm_core.paths import configure_logger
from pm_core import store
from pm_core.loop_shared import (
    extract_verdict_from_content,
    VerdictStabilityTracker,
)
from pm_core.review_loop import (
    ReviewLoopState,
    start_review_loop_background,
    VERDICT_PASS,
    VERDICT_PASS_WITH_SUGGESTIONS,
    VERDICT_NEEDS_WORK,
    VERDICT_INPUT_REQUIRED,
)

_log = configure_logger("pm.tui.review_loop_ui")

# Tracks consecutive polls where MERGED was detected per merge key.
# Uses the same stability mechanism as review/watcher verdict detection.
_merge_verdict_tracker = VerdictStabilityTracker()

# Icons for review verdicts (used in log line)
VERDICT_ICONS = {
    VERDICT_PASS: "[green bold]✓ PASS[/]",
    VERDICT_PASS_WITH_SUGGESTIONS: "[yellow bold]~ PASS_WITH_SUGGESTIONS[/]",
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

def _start_loop(app, pr_id: str, pr: dict | None, stop_on_suggestions: bool,
                transcript_dir: str | None = None) -> None:
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


def _on_complete_from_thread(app, state: ReviewLoopState) -> None:
    """Called from the background thread when the loop finishes."""
    _log.info("review_loop_ui: loop complete for %s — verdict=%s iterations=%d",
              state.pr_id, state.latest_verdict, state.iteration)

    # Finalize review transcript symlinks for this loop's iterations
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

    # Refresh tech tree to update ⟳N markers on PR nodes
    _refresh_tech_tree(app)

    # Announce completed loops and auto-merge passing PRs
    for state in newly_done:
        verdict_icon = VERDICT_ICONS.get(state.latest_verdict, state.latest_verdict)
        app.log_message(
            f"Review loop done for {state.pr_id}: {verdict_icon} "
            f"({state.iteration} iteration{'s' if state.iteration != 1 else ''})",
            sticky=10,
        )

        # Auto-merge passing PRs when auto-start is enabled
        if state.latest_verdict in (VERDICT_PASS, VERDICT_PASS_WITH_SUGGESTIONS):
            _maybe_auto_merge(app, state.pr_id)

    # Stop the timer if no loops are running AND no active PRs need animation
    # AND watcher is not running
    has_active_prs = any(
        pr.get("status") in ("in_progress", "in_review") and pr.get("workdir")
        for pr in (app._data.get("prs") or [])
    )
    watcher_running = app._watcher_state and app._watcher_state.running
    if not any_running and not has_active_prs and not watcher_running:
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
# Auto-merge passing reviews
# ---------------------------------------------------------------------------

def _maybe_auto_merge(app, pr_id: str) -> None:
    """Auto-merge a PR after a passing review, if auto-start is enabled.

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

    merge_cmd = "pr merge"
    if resolve_window:
        merge_cmd += " --resolve-window"
    if propagation_only:
        merge_cmd += " --propagation-only"
    merge_cmd += " --background"
    tdir = _auto_start.get_transcript_dir(app)
    if tdir:
        merge_cmd += f" --transcript {tdir / f'merge-{pr_id}.jsonl'}"
    merge_cmd += f" {pr_id}"
    pr_view.run_command(app, merge_cmd)

    # Reload state — subprocess modified project.yaml on disk
    app._data = store.load(app._root)
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
    _merge_verdict_tracker.reset(merge_key)
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
    _merge_verdict_tracker.reset(merge_key)

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
    _merge_verdict_tracker.reset(merge_key)

    app.log_message(
        f"[red bold]⏸ Merge INPUT_REQUIRED[/] for {pr_id}: "
        f"interact with Claude in the merge window to resolve",
        sticky=30,
    )


# ---------------------------------------------------------------------------
# Implementation pane idle polling
# ---------------------------------------------------------------------------

def _find_impl_pane(session: str, window_name: str) -> str | None:
    """Find the Claude pane in an implementation/merge window.

    Delegates to :func:`pm_core.loop_shared.find_claude_pane` which
    checks the pane registry first, then falls back to ``panes[0][0]``
    with a warning for unregistered windows.
    """
    from pm_core.loop_shared import find_claude_pane
    return find_claude_pane(session, window_name)


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

        # Lazy pane resolution: register if not yet tracked or pane gone
        if not tracker.is_tracked(pr_id) or tracker.is_gone(pr_id):
            pane_id = _find_impl_pane(session, window_name)
            if pane_id:
                tracker.register(pr_id, pane_id)
            else:
                continue  # window not found, skip

        tracker.poll(pr_id)

        # Detect newly-idle in_progress PRs for auto-review
        if status == "in_progress" and tracker.became_idle(pr_id):
            # Check if Claude is on an interactive selection screen (trust
            # prompt, permission prompt, etc.) — that's not "done".
            from pm_core.pane_idle import content_has_interactive_prompt
            content = tracker.get_content(pr_id)
            if content_has_interactive_prompt(content):
                _log.info("impl_idle: %s idle but showing interactive prompt, resetting", pr_id)
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
            _merge_verdict_tracker.reset(merge_key)
            continue

        merge_key = f"merge:{pr_id}"
        window_name = f"merge-{_pr_display_id(pr)}"

        # Lazy pane resolution
        if not tracker.is_tracked(merge_key) or tracker.is_gone(merge_key):
            pane_id = _find_impl_pane(session, window_name)
            if pane_id:
                tracker.register(merge_key, pane_id)
            else:
                continue

        active_merge_keys.add(merge_key)
        tracker.poll(merge_key)

        # --- Primary: check for MERGED or INPUT_REQUIRED verdict ---
        merge_content = tracker.get_content(merge_key)
        if merge_content:
            verdict = extract_verdict_from_content(
                merge_content,
                verdicts=("MERGED", "INPUT_REQUIRED"),
                keywords=("MERGED", "INPUT_REQUIRED"),
                log_prefix="merge_verdict",
            )
            if _merge_verdict_tracker.update(merge_key, verdict):
                if verdict == "MERGED":
                    _log.info("merge_verdict: MERGED detected for %s (stable)", pr_id)
                    app.log_message(f"MERGED detected for {pr_id}, finalizing merge")
                    _finalize_detected_merge(app, pr_id, merge_key, tracker,
                                             pending_merges, active_merge_keys)
                elif verdict == "INPUT_REQUIRED":
                    _log.info("merge_verdict: INPUT_REQUIRED detected for %s (stable)", pr_id)
                    _handle_merge_input_required(app, pr_id, merge_key)
                continue

        # --- Fallback: idle detection (for _pending_merge_prs entries only) ---
        if pr_id not in pending_merges:
            continue

        if tracker.became_idle(merge_key):
            # Check for interactive prompt before treating as idle
            from pm_core.pane_idle import content_has_interactive_prompt
            merge_content = tracker.get_content(merge_key)
            if content_has_interactive_prompt(merge_content):
                _log.info("merge_idle: %s idle but showing interactive prompt, resetting", pr_id)
                tracker.mark_active(merge_key)
                continue

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

    # Unregister stale merge keys and clean up verdict stability state
    for key in tracker.tracked_keys():
        if key.startswith("merge:") and key not in active_merge_keys:
            tracker.unregister(key)
            _merge_verdict_tracker.reset(key)

    # Unregister PRs no longer active
    for key in tracker.tracked_keys():
        if not key.startswith("merge:") and key not in active_pr_ids:
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
        app._data = store.load(app._root)
        updated_pr = store.get_pr(app._data, pr_id)
        if updated_pr and updated_pr.get("status") == "in_review":
            # Start a review loop (same as _auto_start_review_loops)
            loop = app._review_loops.get(pr_id)
            if not loop:
                _start_loop(app, pr_id, updated_pr, stop_on_suggestions=False,
                             transcript_dir=str(tdir) if tdir else None)
