"""QA loop UI integration for the TUI.

Parallel to review_loop_ui.py — manages starting/stopping QA loops and
updating the TUI display.
"""

from pm_core.paths import configure_logger
from pm_core import store
from pm_core.qa_loop import (
    QALoopState,
    QAScenario,
    VERDICT_PASS,
    VERDICT_NEEDS_WORK,
    VERDICT_INPUT_REQUIRED,
    start_qa_background,
)

_log = configure_logger("pm.tui.qa_loop_ui")


def start_qa(app, pr_id: str) -> None:
    """Start a QA session for a PR.

    Creates QALoopState, starts background QA thread.
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


def stop_qa(app, pr_id: str) -> None:
    """Request graceful stop of QA for a PR."""
    state = app._qa_loops.get(pr_id)
    if state and state.running:
        state.stop_requested = True
        app.log_message(f"Stopping QA for {pr_id}...")
    else:
        app.log_message(f"No QA running for {pr_id}")


def poll_qa_state(app) -> None:
    """Called from the shared poll timer to update QA state in the TUI."""
    for pr_id, state in list(app._qa_loops.items()):
        if not state.running and state.latest_verdict:
            _on_qa_complete(app, state)
            # Remove completed loops (keep for one poll cycle)
            if hasattr(state, "_ui_complete_notified"):
                del app._qa_loops[pr_id]
            else:
                state._ui_complete_notified = True


def _on_qa_update(app, state: QALoopState) -> None:
    """Handle QA progress update — log to TUI."""
    if state.latest_output:
        app.log_message(f"QA [{state.pr_id}]: {state.latest_output}")


def _on_qa_complete(app, state: QALoopState) -> None:
    """Handle QA completion — trigger appropriate lifecycle transition."""
    if hasattr(state, "_ui_complete_notified"):
        return

    pr_id = state.pr_id
    verdict = state.latest_verdict

    _log.info("QA complete for %s: verdict=%s changes=%s",
              pr_id, verdict, state.made_changes)

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
    elif verdict == VERDICT_INPUT_REQUIRED:
        app.log_message(
            f"[red bold]QA INPUT_REQUIRED[/] for {pr_id} — paused for human input"
        )
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
            store.save(app._root, data)
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
        store.save(app._root, data)
    except Exception:
        _log.exception("Failed to record QA note for %s", state.pr_id)
