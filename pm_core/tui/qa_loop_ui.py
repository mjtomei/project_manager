"""QA loop UI integration for the TUI.

Parallel to review_loop_ui.py — manages starting/stopping QA loops and
updating the TUI display.

Keybinding variants (set up by app.action_start_qa_on_pr):
  t      — one-shot QA run
  z t    — fresh start (stop running QA, kill old windows, restart)
  zz t   — start/stop QA loop (lenient: PASS or PASS_WITH_SUGGESTIONS)
  zzz t  — start/stop QA loop (strict: only clean PASS)
"""

from pm_core.paths import configure_logger
from pm_core import store
from pm_core.qa_loop import (
    QALoopState,
    VERDICT_PASS,
    VERDICT_NEEDS_WORK,
    VERDICT_INPUT_REQUIRED,
    start_qa_background,
    _compute_qa_window_name,
)
from pm_core.loop_shared import get_pm_session

_log = configure_logger("pm.tui.qa_loop_ui")


def _get_selected_pr(app) -> tuple[str | None, dict | None]:
    """Return (pr_id, pr_dict) for the selected PR, or (None, None)."""
    from pm_core.tui.tech_tree import TechTree
    tree = app.query_one("#tech-tree", TechTree)
    pr_id = tree.selected_pr_id
    if not pr_id or not app._root:
        return None, None
    data = store.load(app._root)
    pr = store.get_pr(data, pr_id)
    return pr_id, pr


# ---------------------------------------------------------------------------
# t — one-shot QA (or focus existing window)
# ---------------------------------------------------------------------------

def focus_or_start_qa(app, pr_id: str) -> None:
    """Focus the existing QA window if it exists, otherwise start a new QA run.

    Called when the user presses plain ``t``.  Unlike ``start_qa`` (used by
    auto-start and internal callers), this never kills stale windows — it
    just focuses the main QA window so the user can inspect its output.
    """
    if not app._root:
        app.log_message("No project root")
        return

    data = store.load(app._root)
    pr = store.get_pr(data, pr_id)
    if not pr:
        app.log_message(f"PR not found: {pr_id}")
        return

    # If the main QA window already exists, just focus it
    from pm_core import tmux as tmux_mod
    session = get_pm_session()
    if session:
        window_name = _compute_qa_window_name(pr)
        win = tmux_mod.find_window_by_name(session, window_name)
        if win:
            tmux_mod.select_window(session, window_name)
            app.log_message(f"Focused QA window for {pr_id}")
            return

    # No existing window — start a new QA session
    start_qa(app, pr_id)


def start_qa(app, pr_id: str) -> None:
    """Start a QA session for a PR.

    Creates QALoopState, starts background QA thread.
    Called by auto-start and internal callers (fresh_start, loop start).
    """
    if not app._root:
        app.log_message("No project root")
        return

    data = store.load(app._root)
    pr = store.get_pr(data, pr_id)
    if not pr:
        app.log_message(f"PR not found: {pr_id}")
        return

    # Check if QA is already running for this PR
    if pr_id in app._qa_loops:
        existing = app._qa_loops[pr_id]
        if existing.running:
            app.log_message(f"QA already running for {pr_id}")
            return

    state = QALoopState(pr_id=pr_id)

    def on_update(s: QALoopState):
        # Schedule UI update on the main thread
        app.call_from_thread(_on_qa_update, app, s)

    app._qa_loops[pr_id] = state
    app.log_message(f"Starting QA for {pr_id}...")

    start_qa_background(state, app._root, pr, on_update)


# ---------------------------------------------------------------------------
# z t — fresh start
# ---------------------------------------------------------------------------

def fresh_start_qa(app, pr_id: str) -> None:
    """Stop running QA (if any) and restart with fresh windows.

    Handles ``z t``.

    Note: old window cleanup is deferred to ``run_qa_sync``'s planning
    phase so it can first capture which sessions are watching the old QA
    window and switch them to the replacement.
    """
    if not app._root:
        app.log_message("No project root")
        return

    data = store.load(app._root)
    pr = store.get_pr(data, pr_id)
    if not pr:
        app.log_message(f"PR not found: {pr_id}")
        return

    # Stop any running QA for this PR
    existing = app._qa_loops.get(pr_id)
    if existing and existing.running:
        existing.stop_requested = True
        _log.info("fresh_start_qa: stopping running QA for %s", pr_id)

    # Remove from loops dict so start_qa doesn't see it as running
    app._qa_loops.pop(pr_id, None)

    # Start fresh — run_qa_sync will clean up old windows after capturing
    # which sessions were watching them (for proper session switching).
    app.log_message(f"Fresh QA start for {pr_id}...")
    start_qa(app, pr_id)


# ---------------------------------------------------------------------------
# zz t / zzz t — QA loop (start or stop)
# ---------------------------------------------------------------------------

def start_or_stop_qa_loop(app, pr_id: str, strict: bool) -> None:
    """Start or stop a QA loop for the given PR.

    ``zz t`` (strict=False): lenient — stop on PASS (accept minor suggestions).
    ``zzz t`` (strict=True): strict — stop only on clean PASS with no changes.

    If a QA loop is already running, this stops it instead.
    """
    if not app._root:
        app.log_message("No project root")
        return

    data = store.load(app._root)
    pr = store.get_pr(data, pr_id)
    if not pr:
        app.log_message(f"PR not found: {pr_id}")
        return

    # If a QA loop is running, stop it
    existing = app._qa_loops.get(pr_id)
    if existing and existing.running:
        existing.stop_requested = True
        mode = "strict" if strict else "lenient"
        app.log_message(f"[bold]QA loop stopping[/] for {pr_id} (finishing current run)...")
        _log.info("qa_loop_ui: stopping QA loop for %s (mode=%s)", pr_id, mode)
        return

    # Remove stale loop state — run_qa_sync will clean up old windows
    # after capturing which sessions were watching them.
    app._qa_loops.pop(pr_id, None)

    # Start a new QA loop
    state = QALoopState(pr_id=pr_id)
    state._qa_loop_mode = True
    state._qa_loop_strict = strict

    def on_update(s: QALoopState):
        app.call_from_thread(_on_qa_update, app, s)

    app._qa_loops[pr_id] = state

    mode_label = "strict (PASS only)" if strict else "lenient"
    app.log_message(
        f"[bold]QA loop started[/] for {pr_id} [{mode_label}] — z t to stop",
        sticky=3,
    )
    _log.info("qa_loop_ui: starting QA loop for %s (mode=%s)", pr_id, mode_label)

    start_qa_background(state, app._root, pr, on_update)


# ---------------------------------------------------------------------------
# Stop (public API for command bar etc.)
# ---------------------------------------------------------------------------

def stop_qa(app, pr_id: str) -> None:
    """Request graceful stop of QA for a PR."""
    state = app._qa_loops.get(pr_id)
    if state and state.running:
        state.stop_requested = True
        app.log_message(f"Stopping QA for {pr_id}...")
    else:
        app.log_message(f"No QA running for {pr_id}")


# ---------------------------------------------------------------------------
# Polling (called from shared poll timer)
# ---------------------------------------------------------------------------

def poll_qa_state(app) -> None:
    """Called from the shared poll timer to update QA state in the TUI."""
    for pr_id, state in list(app._qa_loops.items()):
        if not state.running and state.latest_verdict:
            _on_qa_complete(app, state)
            # Remove completed loops (keep for one poll cycle)
            if state._ui_complete_notified:
                del app._qa_loops[pr_id]
            else:
                state._ui_complete_notified = True


# ---------------------------------------------------------------------------
# Internal callbacks
# ---------------------------------------------------------------------------

def _on_qa_update(app, state: QALoopState) -> None:
    """Handle QA progress update — log to TUI."""
    if state.latest_output:
        app.log_message(f"QA [{state.pr_id}]: {state.latest_output}")


def _on_qa_complete(app, state: QALoopState) -> None:
    """Handle QA completion — trigger appropriate lifecycle transition.

    In loop mode (zz t / zzz t), a non-passing verdict restarts the loop
    instead of just transitioning status.
    """
    if state._ui_complete_notified:
        return

    pr_id = state.pr_id
    verdict = state.latest_verdict
    is_loop = getattr(state, "_qa_loop_mode", False)
    is_strict = getattr(state, "_qa_loop_strict", False)

    _log.info("QA complete for %s: verdict=%s changes=%s loop=%s strict=%s",
              pr_id, verdict, state.made_changes, is_loop, is_strict)

    if verdict == VERDICT_PASS and not state.made_changes:
        # All scenarios passed with no changes → ready to merge
        app.log_message(f"[green bold]QA PASS[/] for {pr_id} — ready to merge")
        _trigger_auto_merge(app, pr_id)
    elif verdict == VERDICT_NEEDS_WORK or state.made_changes:
        # Issues found or changes committed → back to review
        app.log_message(
            f"[yellow bold]QA NEEDS_WORK[/] for {pr_id} — returning to review"
        )
        _transition_pr_status(app, pr_id, "qa", "in_review")
        # Clear the stale review loop entry from the previous review pass
        # so _auto_start_review_loops can start a fresh one.
        app._review_loops.pop(pr_id, None)
        # Reload in-memory state so auto-start sees the new status,
        # then trigger check_and_start to restart the review loop.
        if app._root:
            app._data = store.load(app._root)
        from pm_core.tui import auto_start as _auto_start
        if _auto_start.is_enabled(app):
            app.run_worker(_auto_start.check_and_start(app))

        # In loop mode, re-queue QA after review completes
        # (auto-start handles the review→QA transition automatically)
        if is_loop:
            _log.info("QA loop: NEEDS_WORK — review loop will re-trigger QA via auto-start")
    elif verdict == VERDICT_INPUT_REQUIRED:
        app.log_message(
            f"[red bold]QA INPUT_REQUIRED[/] for {pr_id} — paused for human input"
        )
        if is_loop:
            _log.info("QA loop: INPUT_REQUIRED — loop paused, awaiting human input")
    else:
        app.log_message(f"QA finished for {pr_id}: {verdict}")

    # Record QA results as a PR note
    _record_qa_note(app, state)


def _trigger_auto_merge(app, pr_id: str) -> None:
    """Trigger auto-merge after QA passes, if auto-start is enabled."""
    from pm_core.tui.review_loop_ui import _maybe_auto_merge
    # _maybe_auto_merge checks auto-start status and scope internally
    _maybe_auto_merge(app, pr_id)


def _transition_pr_status(app, pr_id: str, from_status: str, to_status: str) -> None:
    """Transition PR status if it's currently in the expected state."""
    if not app._root:
        return
    try:
        data = store.load(app._root)
        pr = store.get_pr(data, pr_id)
        if not pr:
            return
        current = pr.get("status", "")
        if current == from_status:
            pr["status"] = to_status
            store.save(data, app._root)
            _log.info("Transitioned %s: %s → %s", pr_id, from_status, to_status)
    except Exception:
        _log.exception("Failed to transition PR status for %s", pr_id)


def _record_qa_note(app, state: QALoopState) -> None:
    """Record QA results as a note on the PR."""
    if not app._root:
        return
    try:
        from datetime import datetime, timezone
        data = store.load(app._root)
        pr = store.get_pr(data, state.pr_id)
        if not pr:
            return
        summary_parts = []
        for s in state.scenarios:
            v = state.scenario_verdicts.get(s.index, "?")
            summary_parts.append(f"{s.title}: {v}")
        note_text = f"QA {state.latest_verdict}: " + "; ".join(summary_parts)
        if state.made_changes:
            note_text += " [changes committed]"
        notes = pr.get("notes") or []
        existing_ids = {n["id"] for n in notes}
        note_id = store.generate_note_id(state.pr_id, note_text, existing_ids)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        notes.append({"id": note_id, "text": note_text,
                       "created_at": now, "last_edited": now})
        pr["notes"] = notes
        store.save(data, app._root)
    except Exception:
        _log.exception("Failed to record QA note for %s", state.pr_id)
