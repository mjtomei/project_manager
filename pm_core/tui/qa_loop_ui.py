"""QA loop UI integration for the TUI.

Parallel to review_loop_ui.py — manages starting/stopping QA loops and
updating the TUI display.

Keybinding variants (set up by app.action_start_qa_on_pr):
  t      — one-shot QA run
  z t    — fresh start (stop running QA, kill old windows, restart)
  zz t   — start/stop QA loop (lenient: PASS or PASS_WITH_SUGGESTIONS)
  zzz t  — start/stop QA loop (strict: only clean PASS)
"""

from pm_core.paths import configure_logger, get_global_setting_value
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


def _get_qa_pass_count() -> int:
    """Read qa-pass-count from global settings, default 1."""
    val = get_global_setting_value("qa-pass-count", "")
    try:
        return max(1, int(val))
    except ValueError:
        return 1


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

    # Transition status to "qa" if currently in_review
    if pr.get("status") == "in_review":
        def _set_qa(d):
            p = store.get_pr(d, pr_id)
            if p and p.get("status") == "in_review":
                p["status"] = "qa"
        try:
            store.locked_update(app._root, _set_qa)
        except (store.StoreLockTimeout, store.ProjectYamlParseError) as e:
            app.log_message(f"Error: {e}")
            _log.warning("start_qa: %s for %s: %s", type(e).__name__, pr_id, e)
            return
        app._load_state()
        _log.info("start_qa: transitioned %s to qa status", pr_id)

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
    # Clear self-driving state so the fresh start is a one-shot QA
    app._self_driving_qa.pop(pr_id, None)

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
        # Also remove self-driving registration
        app._self_driving_qa.pop(pr_id, None)
        mode = "strict" if strict else "lenient"
        app.log_message(f"[bold]QA loop stopping[/] for {pr_id} (finishing current run)...")
        _log.info("qa_loop_ui: stopping QA loop for %s (mode=%s)", pr_id, mode)
        return

    # Remove stale loop state — run_qa_sync will clean up old windows
    # after capturing which sessions were watching them.
    app._qa_loops.pop(pr_id, None)

    # Register self-driving QA state
    app._self_driving_qa[pr_id] = {
        "strict": strict,
        "pass_count": 0,
        "required_passes": _get_qa_pass_count(),
    }

    # Start a new QA loop
    state = QALoopState(pr_id=pr_id)

    def on_update(s: QALoopState):
        app.call_from_thread(_on_qa_update, app, s)

    app._qa_loops[pr_id] = state

    required = app._self_driving_qa[pr_id]["required_passes"]
    mode_label = "strict (PASS only)" if strict else "lenient"
    passes_label = f", {required} pass{'es' if required > 1 else ''} required" if required > 1 else ""
    app.log_message(
        f"[bold]QA loop started[/] for {pr_id} [{mode_label}{passes_label}] — z t to stop",
        sticky=3,
    )
    _log.info("qa_loop_ui: starting QA loop for %s (mode=%s, passes=%d)",
              pr_id, mode_label, required)

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

    Self-driving mode (zz t / zzz t):
      - PASS (no changes): increment pass_count; if >= required_passes,
        remove from self-driving and trigger merge. Otherwise restart QA.
      - NEEDS_WORK / changes: reset pass_count, transition to in_review,
        and directly start a review loop (independent of auto-start).
      - INPUT_REQUIRED: pause self-driving loop for human input.

    Legacy mode (plain t or auto-start):
      - PASS: trigger auto-merge.
      - NEEDS_WORK: transition to in_review, rely on auto-start.
    """
    if state._ui_complete_notified:
        return

    pr_id = state.pr_id
    verdict = state.latest_verdict
    sd = app._self_driving_qa.get(pr_id)

    _log.info("QA complete for %s: verdict=%s self_driving=%s",
              pr_id, verdict, bool(sd))

    if verdict == VERDICT_PASS:
        # All scenarios passed with no changes
        if sd:
            sd["pass_count"] += 1
            required = sd["required_passes"]
            if sd["pass_count"] >= required:
                app.log_message(
                    f"[green bold]QA PASS[/] for {pr_id} "
                    f"({sd['pass_count']}/{required} consecutive) — ready to merge"
                )
                # Trigger merge BEFORE removing self-driving state so
                # _trigger_auto_merge sees the entry and uses force=True
                # (bypassing auto-start scope checks).
                _trigger_auto_merge(app, pr_id)
                app._self_driving_qa.pop(pr_id, None)
            else:
                app.log_message(
                    f"[green]QA PASS[/] for {pr_id} "
                    f"({sd['pass_count']}/{required} consecutive) — restarting QA"
                )
                _log.info("QA self-driving: %d/%d passes, restarting QA",
                          sd["pass_count"], required)
                start_qa(app, pr_id)
        else:
            # Legacy path — only auto-merge when auto-start is active
            from pm_core.tui import auto_start as _auto_start
            if _auto_start.is_enabled(app):
                app.log_message(f"[green bold]QA PASS[/] for {pr_id} — ready to merge")
                _trigger_auto_merge(app, pr_id)
            else:
                app.log_message(
                    f"[green bold]QA PASS[/] for {pr_id} — "
                    "merge manually or enable auto-start"
                )
    elif verdict == VERDICT_NEEDS_WORK:
        # Issues found or changes committed → back to review
        app.log_message(
            f"[yellow bold]QA NEEDS_WORK[/] for {pr_id} — returning to review"
        )
        _transition_pr_status(app, pr_id, "qa", "in_review")
        # Clear the stale review loop entry from the previous review pass
        app._review_loops.pop(pr_id, None)
        # Reload in-memory state
        if app._root:
            app._data = store.load(app._root)

        if sd:
            # Self-driving: reset pass count and directly start review loop
            sd["pass_count"] = 0
            _log.info("QA self-driving: NEEDS_WORK — starting review loop directly")
            _start_self_driving_review(app, pr_id, sd["strict"])
        else:
            # Legacy: rely on auto-start
            from pm_core.tui import auto_start as _auto_start
            if _auto_start.is_enabled(app):
                app.run_worker(_auto_start.check_and_start(app))
    elif verdict == VERDICT_INPUT_REQUIRED:
        app.log_message(
            f"[red bold]QA INPUT_REQUIRED[/] for {pr_id} — paused for human input"
        )
        if sd:
            _log.info("QA self-driving: INPUT_REQUIRED — loop paused")
    else:
        app.log_message(f"QA finished for {pr_id}: {verdict}")

    # Record QA results as a PR note — do this last so it captures the
    # final state, but log failures loudly since status already transitioned.
    _record_qa_note(app, state)


def _start_self_driving_review(app, pr_id: str, strict: bool) -> None:
    """Start a review loop for a self-driving QA PR (independent of auto-start).

    The z-prefix carries through:
      zz t  (strict=False) → review stop_on_suggestions=True
      zzz t (strict=True)  → review stop_on_suggestions=False
    """
    from pm_core.tui import review_loop_ui

    if not app._root:
        return

    data = store.load(app._root)
    pr = store.get_pr(data, pr_id)
    if not pr:
        _log.warning("_start_self_driving_review: PR %s not found", pr_id)
        return

    stop_on_suggestions = not strict
    _log.info("Self-driving review for %s (stop_on_suggestions=%s)",
              pr_id, stop_on_suggestions)
    review_loop_ui._start_loop(app, pr_id, pr,
                                stop_on_suggestions=stop_on_suggestions)


def _trigger_auto_merge(app, pr_id: str) -> None:
    """Trigger auto-merge after QA passes.

    Works in two modes:
    - Self-driving QA (zz t / zzz t): always triggers merge (independent
      of auto-start) via ``force=True``.
    - Auto-start / legacy: delegates to ``_maybe_auto_merge`` which
      checks auto-start status and scope.
    """
    from pm_core.tui.review_loop_ui import _maybe_auto_merge

    # Self-driving QA operates independently of auto-start — use
    # force=True so _maybe_auto_merge skips the enabled/scope checks.
    sd = getattr(app, '_self_driving_qa', {}).get(pr_id)
    _maybe_auto_merge(app, pr_id, force=bool(sd))


def _transition_pr_status(app, pr_id: str, from_status: str, to_status: str) -> None:
    """Transition PR status if it's currently in the expected state."""
    if not app._root:
        return
    try:
        transitioned = False

        def apply(data):
            nonlocal transitioned
            pr = store.get_pr(data, pr_id)
            if pr and pr.get("status", "") == from_status:
                pr["status"] = to_status
                transitioned = True

        store.locked_update(app._root, apply)
        if transitioned:
            _log.info("Transitioned %s: %s → %s", pr_id, from_status, to_status)
    except store.StoreLockTimeout as e:
        _log.warning("_transition_pr_status: lock timeout for %s: %s", pr_id, e)
    except Exception:
        _log.exception("Failed to transition PR status for %s", pr_id)


def _record_qa_note(app, state: QALoopState) -> None:
    """Record QA results as a note on the PR."""
    if not app._root:
        _log.warning("Cannot record QA note: no project root")
        return
    try:
        from datetime import datetime, timezone
        summary_parts = []
        for s in state.scenarios:
            v = state.scenario_verdicts.get(s.index, "?")
            summary_parts.append(f"{s.title}: {v}")
        note_text = f"QA {state.latest_verdict}: " + "; ".join(summary_parts)
        if state.qa_workdir:
            note_text += f" (workdir: {state.qa_workdir})"

        def apply(data):
            pr = store.get_pr(data, state.pr_id)
            if not pr:
                _log.warning("Cannot record QA note: PR %s not found", state.pr_id)
                return
            notes = pr.get("notes") or []
            existing_ids = {n["id"] for n in notes}
            note_id = store.generate_note_id(state.pr_id, note_text, existing_ids)
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            notes.append({"id": note_id, "text": note_text,
                           "created_at": now, "last_edited": now})
            pr["notes"] = notes

        store.locked_update(app._root, apply)
    except store.StoreLockTimeout as e:
        _log.warning("_record_qa_note: lock timeout for %s: %s", state.pr_id, e)
    except Exception:
        _log.exception("Failed to record QA note for %s", state.pr_id)
