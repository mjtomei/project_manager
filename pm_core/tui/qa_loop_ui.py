"""QA loop UI integration for the TUI.

Parallel to review_loop_ui.py — manages starting/stopping QA loops and
updating the TUI display.

Keybinding variants (set up by app.action_start_qa_on_pr):
  t      — one-shot QA run
  z t    — fresh start (stop running QA, kill old windows, restart)
  zz t   — start/stop QA loop
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
    try:
        data = store.load(app._root)
    except store.ProjectYamlParseError:
        return None, None
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

    try:
        data = store.load(app._root)
    except store.ProjectYamlParseError as e:
        app.log_message(f"Error: {e}")
        return
    pr = store.get_pr(data, pr_id)
    if not pr:
        app.log_message(f"PR not found: {pr_id}")
        return

    # If the main QA window already exists, just focus it.  Honor a
    # popup-spinner-dismissed suppress_switch flag so q/Esc in the
    # picker doesn't have its qa run still steal focus.  When the
    # window doesn't exist yet, leave the flag in place — qa_loop's
    # first-time-creation path consumes it before its own select_window
    # call so the suppression survives the start → run path.
    from pm_core import tmux as tmux_mod
    from pm_core import runtime_state as _rs
    session = get_pm_session()
    if session:
        window_name = _compute_qa_window_name(pr)
        win = tmux_mod.find_window_by_name(session, window_name)
        if win:
            suppress = _rs.consume_suppress_switch(pr_id, "qa")
            if not suppress:
                tmux_mod.select_window(session, window_name)
                app.log_message(f"Focused QA window for {pr_id}")
            else:
                app.log_message(
                    f"QA window for {pr_id} ready (focus suppressed)")
            return

    # No existing window — start a new QA session.  qa_loop will
    # consume any suppress_switch flag at its window-creation step.
    start_qa(app, pr_id)


def start_qa(app, pr_id: str) -> None:
    """Start a QA session for a PR.

    Creates QALoopState, starts background QA thread.
    Called by auto-start and internal callers (fresh_start, loop start).
    """
    if not app._root:
        app.log_message("No project root")
        return

    try:
        data = store.load(app._root)
    except store.ProjectYamlParseError as e:
        app.log_message(f"Error: {e}")
        return
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

    try:
        data = store.load(app._root)
    except store.ProjectYamlParseError as e:
        app.log_message(f"Error: {e}")
        return
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
# zz t — QA loop (start or stop)
# ---------------------------------------------------------------------------

def start_or_stop_qa_loop(app, pr_id: str) -> None:
    """Start or stop a QA loop for the given PR.

    If a QA loop is already running, this stops it instead.
    """
    if not app._root:
        app.log_message("No project root")
        return

    try:
        data = store.load(app._root)
    except store.ProjectYamlParseError as e:
        app.log_message(f"Error: {e}")
        return
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
        app.log_message(f"[bold]QA loop stopping[/] for {pr_id} (finishing current run)...")
        _log.info("qa_loop_ui: stopping QA loop for %s", pr_id)
        return

    # Remove stale loop state — run_qa_sync will clean up old windows
    # after capturing which sessions were watching them.
    app._qa_loops.pop(pr_id, None)

    # Register self-driving QA state
    app._self_driving_qa[pr_id] = {
        "pass_count": 0,
        "required_passes": _get_qa_pass_count(),
    }

    # Start a new QA loop
    state = QALoopState(pr_id=pr_id)

    def on_update(s: QALoopState):
        app.call_from_thread(_on_qa_update, app, s)

    app._qa_loops[pr_id] = state

    required = app._self_driving_qa[pr_id]["required_passes"]
    passes_label = f" ({required} pass{'es' if required > 1 else ''} required)" if required > 1 else ""
    app.log_message(
        f"[bold]QA loop started[/] for {pr_id}{passes_label} — z t to stop",
        sticky=3,
    )
    _log.info("qa_loop_ui: starting QA loop for %s (passes=%d)", pr_id, required)

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
    tracker = app._pane_idle_tracker
    for pr_id, state in list(app._qa_loops.items()):
        # Wire each scenario pane into the idle tracker so the tech tree
        # can animate a spinner while QA is active.  Mirrors the lazy
        # registration used by review_loop_ui._poll_impl_idle.
        for sc in list(state.scenarios):
            if not sc.pane_id or not sc.transcript_path:
                continue
            key = f"qa:{pr_id}:s{sc.index}"
            if not tracker.is_tracked(key) or tracker.is_gone(key):
                try:
                    tracker.register(key, sc.pane_id, sc.transcript_path)
                except ValueError:
                    continue
            tracker.poll(key)

        if not state.running and state.latest_verdict:
            _on_qa_complete(app, state)
            # Remove completed loops (keep for one poll cycle)
            if state._ui_complete_notified:
                # Drop tracker entries for this PR's QA panes so the
                # spinner stops and tracked_keys() doesn't grow.
                for sc in state.scenarios:
                    tracker.unregister(f"qa:{pr_id}:s{sc.index}")
                # Record the verdict in runtime_state so the popup
                # picker shows [done VERDICT] on the qa row across
                # picker invocations.  Written *after* the unregister
                # calls above, since unregister clears the qa entry
                # via _runtime_mirror_clear.
                try:
                    from pm_core import runtime_state as _rs
                    _rs.set_action_state(pr_id, "qa", "done",
                                         verdict=state.latest_verdict)
                except Exception:
                    _log.debug("runtime_state qa verdict mirror failed",
                               exc_info=True)
                # Completion processed — drop the resume snapshot so a
                # later restart doesn't re-process this finished run.
                if state.qa_workdir:
                    from pm_core import qa_loop
                    qa_loop.clear_resume_file(state.qa_workdir)
                del app._qa_loops[pr_id]
            else:
                state._ui_complete_notified = True

    # --- Restart recovery: resume runs whose daemon thread died ---
    # New orphans can only appear from a TUI restart, and recovery is not
    # latency-sensitive (QA runs take minutes), so throttle the disk scan to
    # ~every 5s instead of every 1s poll tick — it would otherwise stat every
    # historical QA workdir each second, forever, even when idle. Runs on the
    # first tick (counter starts at 0) so startup recovery isn't delayed.
    app._qa_resume_poll_counter = getattr(app, "_qa_resume_poll_counter", 0)
    if app._qa_resume_poll_counter % 5 == 0:
        _resume_incomplete_qa(app)
    app._qa_resume_poll_counter += 1


def _resume_incomplete_qa(app) -> None:
    """Resume or finish QA runs orphaned by a TUI restart.

    The verdict-collection orchestration (run_qa_sync) runs in a daemon
    thread inside the TUI process.  A TUI restart kills that thread and
    empties ``app._qa_loops``; the scenario tmux windows keep running but
    nobody collects verdicts, computes the overall result, or drives the
    lifecycle transition.

    Each in-progress run leaves a ``qa_resume.json`` snapshot in its QA
    workdir.  This scans for snapshots not tracked in memory and either:

    * re-spawns the orchestration loop (``resume_qa_background``) when the
      run is still incomplete (no ``overall`` in qa_status.json), or
    * feeds the completed-but-unprocessed result straight through
      ``_on_qa_complete`` when the daemon finished writing the verdict but
      the TUI died before processing it.

    The snapshot is removed once the run has been handled, so it is not
    re-processed on a subsequent restart.

    Limitation: self-driving QA state (``app._self_driving_qa``) lives only
    in memory and is *not* persisted, so a resumed run drives its lifecycle
    transition through the legacy/auto-start path in ``_on_qa_complete``
    (verdict collection and the PASS→merge / NEEDS_WORK→in_review transition
    still happen — only consecutive-pass counting and the direct
    self-driving review restart are lost across the restart). Accepted: the
    core goal is verdict survival, and auto-start (if enabled) still drives
    the loop forward.
    """
    import json
    from pathlib import Path
    from pm_core import qa_loop

    qa_root = Path.home() / ".pm" / "workdirs" / "qa"
    if not qa_root.is_dir():
        return

    if not hasattr(app, "_resumed_qa_pr_ids"):
        app._resumed_qa_pr_ids = set()

    # Defer the (relatively expensive) project load until a candidate is
    # actually found — this runs on the ~1s poll tick.
    project_data = None

    for resume_file in qa_root.glob("*/qa_resume.json"):
        try:
            rdata = json.loads(resume_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        pr_id = rdata.get("pr_id", "")
        if not pr_id:
            continue
        if pr_id in app._qa_loops or pr_id in app._resumed_qa_pr_ids:
            continue

        # Only resume PRs still in QA — skip (and forget) ones that have
        # already moved on.
        if not app._root:
            continue
        if project_data is None:
            project_data = store.load(app._root)
        pr = store.get_pr(project_data, pr_id)
        if not pr or pr.get("status") != "qa":
            # The PR has left QA, so this snapshot can never be validly
            # resumed (resume requires status == "qa").  Drop it so it
            # doesn't linger on disk or get mistakenly picked up if the
            # PR ever returns to QA under a different loop_id.
            app._resumed_qa_pr_ids.add(pr_id)
            qa_loop.clear_resume_file(resume_file.parent)
            continue

        # Is the run already complete (daemon wrote overall, TUI died
        # before processing)?  Read the display status file.
        overall = ""
        try:
            sdata = json.loads((resume_file.parent / "qa_status.json").read_text())
            overall = sdata.get("overall", "")
        except (json.JSONDecodeError, OSError):
            overall = ""

        state = qa_loop.build_resume_state(rdata)
        app._resumed_qa_pr_ids.add(pr_id)

        if overall:
            # Completed during downtime — process and clear the snapshot.
            state.running = False
            state.latest_verdict = overall
            _log.info("Recovered completed QA from disk: %s → %s", pr_id, overall)
            _on_qa_complete(app, state)
            state._ui_complete_notified = True
            if state.qa_workdir:
                qa_loop.clear_resume_file(state.qa_workdir)
            continue

        # Still in progress — re-spawn the orchestration loop.
        def _on_update(s, _app=app):
            _app.call_from_thread(_on_qa_update, _app, s)

        app._qa_loops[pr_id] = state
        app.log_message(f"Resuming QA for {pr_id} after restart...")
        _log.info("Resuming incomplete QA from disk: %s", pr_id)
        qa_loop.resume_qa_background(state, app._root, pr, _on_update)


# ---------------------------------------------------------------------------
# Internal callbacks
# ---------------------------------------------------------------------------

def _on_qa_update(app, state: QALoopState) -> None:
    """Handle QA progress update — log to TUI."""
    if state.latest_output:
        app.log_message(f"QA [{state.pr_id}]: {state.latest_output}")


def _on_qa_complete(app, state: QALoopState) -> None:
    """Handle QA completion — trigger appropriate lifecycle transition.

    Self-driving mode (zz t):
      - PASS (no changes): increment pass_count; if >= required_passes,
        clear self-driving state and defer to auto-start (or the user)
        for merge — manual ``zz t`` does NOT trigger a merge itself.
        Otherwise restart QA.
      - NEEDS_WORK / changes: reset pass_count, transition to in_review,
        and directly start a review loop (independent of auto-start).
      - INPUT_REQUIRED: pause self-driving loop for human input.

    Legacy mode (plain t or auto-start):
      - PASS: trigger auto-merge when auto-start is enabled.
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
                # Manual zz t does NOT auto-merge.  Clear self-driving
                # state and defer to auto-start (if active) or the user.
                app._self_driving_qa.pop(pr_id, None)
                from pm_core.tui import auto_start as _auto_start
                if _auto_start.is_enabled(app):
                    app.log_message(
                        f"[green bold]QA PASS[/] for {pr_id} "
                        f"({sd['pass_count']}/{required} consecutive) — ready to merge"
                    )
                    _trigger_auto_merge(app, pr_id)
                else:
                    app.log_message(
                        f"[green bold]QA PASS[/] for {pr_id} "
                        f"({sd['pass_count']}/{required} consecutive) — "
                        "merge manually or enable auto-start"
                    )
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
            try:
                app._data = store.load(app._root)
            except store.ProjectYamlParseError:
                pass  # keep existing app._data

        if sd:
            # Self-driving: reset pass count and directly start review loop
            sd["pass_count"] = 0
            _log.info("QA self-driving: NEEDS_WORK — starting review loop directly")
            _start_self_driving_review(app, pr_id)
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


def _start_self_driving_review(app, pr_id: str) -> None:
    """Start a review loop for a self-driving QA PR (independent of auto-start)."""
    from pm_core.tui import review_loop_ui, auto_start as _auto_start

    if not app._root:
        return

    try:
        data = store.load(app._root)
    except store.ProjectYamlParseError as e:
        _log.warning("_start_self_driving_review: %s", e)
        return
    pr = store.get_pr(data, pr_id)
    if not pr:
        _log.warning("_start_self_driving_review: PR %s not found", pr_id)
        return

    _log.info("Self-driving review for %s", pr_id)
    review_loop_ui._start_loop(
        app, pr_id, pr,
        transcript_dir=str(_auto_start.get_transcript_dir(app)),
    )


def _trigger_auto_merge(app, pr_id: str) -> None:
    """Trigger auto-merge after QA passes.

    Only called when auto-start is active — merge is never triggered by
    a manual ``zz t`` run.  Delegates to ``_maybe_auto_merge`` which
    re-checks auto-start status and scope.
    """
    from pm_core.tui.review_loop_ui import _maybe_auto_merge
    _maybe_auto_merge(app, pr_id)


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
    except (store.StoreLockTimeout, store.ProjectYamlParseError) as e:
        _log.warning("_transition_pr_status: %s for %s: %s", type(e).__name__, pr_id, e)
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
    except (store.StoreLockTimeout, store.ProjectYamlParseError) as e:
        _log.warning("_record_qa_note: %s for %s: %s", type(e).__name__, state.pr_id, e)
    except Exception:
        _log.exception("Failed to record QA note for %s", state.pr_id)
