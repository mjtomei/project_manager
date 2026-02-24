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
from pm_core.review_loop import (
    ReviewLoopState,
    start_review_loop_background,
    VERDICT_PASS,
    VERDICT_PASS_WITH_SUGGESTIONS,
    VERDICT_NEEDS_WORK,
    VERDICT_INPUT_REQUIRED,
)

_log = configure_logger("pm.tui.review_loop_ui")

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


def handle_confirm_input(app) -> None:
    """Legacy handler — INPUT_REQUIRED no longer requires TUI confirmation.

    The review loop now polls the existing pane for a follow-up verdict
    automatically.  The user interacts directly with Claude in the review
    pane.
    """
    # Check if any loop is actually waiting for input
    for pr_id, state in app._review_loops.items():
        if state.input_required:
            app.log_message(
                f"INPUT_REQUIRED for {pr_id}: interact with Claude in the review pane — "
                f"the loop will pick up the new verdict automatically",
            )
            return
    app.log_message("No review loop is waiting for input")


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

    from pm_core.tui import pr_view
    merge_cmd = f"pr merge --resolve-window --background"
    tdir = _auto_start.get_transcript_dir(app)
    if tdir:
        merge_cmd += f" --transcript {tdir / f'merge-{pr_id}.jsonl'}"
    merge_cmd += f" {pr_id}"
    pr_view.run_command(app, merge_cmd)

    # Reload state — the subprocess modified project.yaml on disk
    # but _run_command_sync doesn't update the in-memory data.
    app._data = store.load(app._root)
    merged_pr = store.get_pr(app._data, pr_id)
    if merged_pr and merged_pr.get("status") == "merged":
        _log.info("auto_merge: %s merged, starting dependents", pr_id)
        # check_and_start is async — schedule it via run_worker
        app.run_worker(_auto_start.check_and_start(app))
    else:
        # Merge failed (conflict) — a resolve window was launched.
        # Mark for idle tracking so _poll_impl_idle discovers the pane
        # and re-attempts the merge after Claude resolves.
        _log.info("auto_merge: %s merge failed, tracking merge window", pr_id)
        app._pending_merge_prs.add(pr_id)


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
            newly_idle.append((pr_id, pr))

    # --- Second pass: merge resolution windows ---
    pending_merges: set[str] = app._pending_merge_prs
    active_merge_keys: set[str] = set()

    for pr_id in list(pending_merges):
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
        active_merge_keys.add(merge_key)
        window_name = f"merge-{_pr_display_id(pr)}"

        # Lazy pane resolution
        if not tracker.is_tracked(merge_key) or tracker.is_gone(merge_key):
            pane_id = _find_impl_pane(session, window_name)
            if pane_id:
                tracker.register(merge_key, pane_id)
            else:
                continue

        tracker.poll(merge_key)

        if tracker.became_idle(merge_key):
            _log.info("merge_idle: merge window idle for %s, re-attempting merge", pr_id)
            app.log_message(f"Merge window idle for {pr_id}, re-attempting merge")

            from pm_core.tui import pr_view
            re_merge_cmd = f"pr merge --resolve-window --background"
            tdir = _auto_start.get_transcript_dir(app)
            if tdir:
                re_merge_cmd += f" --transcript {tdir / f'merge-{pr_id}.jsonl'}"
            re_merge_cmd += f" {pr_id}"
            pr_view.run_command(app, re_merge_cmd)

            # Reload state — subprocess modified project.yaml on disk
            app._data = store.load(app._root)
            merged_pr = store.get_pr(app._data, pr_id)
            if merged_pr and merged_pr.get("status") == "merged":
                _log.info("merge_idle: %s merged after resolution, starting dependents", pr_id)
                pending_merges.discard(pr_id)
                tracker.unregister(merge_key)
                active_merge_keys.discard(merge_key)
                app.run_worker(_auto_start.check_and_start(app))
            # else: still not merged — keep tracking, new window may have been launched

    # Unregister stale merge keys
    for key in tracker.tracked_keys():
        if key.startswith("merge:") and key not in active_merge_keys:
            tracker.unregister(key)

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
