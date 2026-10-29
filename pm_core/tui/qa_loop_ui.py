"""QA loop UI integration for the TUI.

Parallel to review_loop_ui.py — manages starting/stopping QA loops and
updating the TUI display.

Keybinding variants (set up by app.action_start_qa_on_pr):
  t      — one-shot QA run
  z t    — fresh start (stop running QA, kill old windows, restart)
  zz t   — start/stop QA loop
"""

from rich.markup import escape

from pm_core.paths import configure_logger, get_global_setting_value
from pm_core import store
from pm_core.qa_loop import (
    QALoopState,
    VERDICT_PASS,
    VERDICT_NEEDS_WORK,
    VERDICT_INPUT_REQUIRED,
    VERDICT_STOPPED,
    start_qa_background,
    _compute_qa_window_name,
    planner_code_changes_suffix,
    input_wait_changes_suffix,
    qa_outcome_detail,
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
                # A direct answer to the user's key must be visible even
                # when a confirmation is holding the log line — e.g. the
                # "QA loop started … — z t to stop" sticky a `zz t` sets
                # just before a second `t` lands (QA s26).  Same rule as
                # the dedup / focus-suppressed replies below.
                app.log_message(f"Focused QA window for {pr_id}", force=True)
            else:
                app.log_message(
                    f"QA window for {pr_id} ready (focus suppressed)",
                    force=True)
            return

    # No existing window — start a new QA session.  qa_loop will
    # consume any suppress_switch flag at its window-creation step.
    start_qa(app, pr_id, focus=True)


def start_qa(app, pr_id: str, *, focus: bool = False) -> None:
    """Start a QA session for a PR.

    Creates QALoopState, starts background QA thread.
    Called by the user starts ``t`` / ``z t`` (with *focus*) and by
    scheduler-driven callers: auto-start, review PASS → QA, sign-off REQA
    and self-driving restarts.  *focus* selects the new QA window; only
    user-initiated starts pass it, so scheduler-driven starts don't pull
    attached clients off the TUI.
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
        if existing.running or existing.held:
            # A user can ask to view a background run before its first window
            # exists. Reuse that worker, but retain the explicit focus request;
            # popup suppression is still consumed at window creation.
            if focus and existing.running:
                existing.focus_on_create = True
            # A direct answer to the user's start must be visible even when
            # an auto-start/setup confirmation is holding the log line —
            # this lands in the gap where the scheduler's "targets +="
            # confirmation is still sticky (QA s22).
            # ``running`` wins over ``held``: the hold's reopen publishes
            # running=True before clearing held, so a run that is actively
            # collecting must not be described as waiting for input.
            if existing.running:
                app.log_message(f"QA already running for {pr_id}", force=True)
            else:
                app.log_message(
                    f"QA for {pr_id} is waiting for input — answer in its "
                    "scenario worker pane; the loop is still watching",
                    force=True)
            return

    if not _enter_qa_status(app, pr, "start_qa"):
        return

    # A sign-off REQA return is now being re-verified.  Consumed only once
    # the run will actually start (a failed status transition must leave it
    # on disk for the reconciler) and mirrored in ``app._data``, or the
    # reconciler re-attempts the claim every 5 s until a reload.
    from pm_core.signoff import clear_return_awaiting
    clear_return_awaiting(app._root, pr_id, "qa")
    _consume_owed_reqa_in_memory(app, pr_id)

    state = QALoopState(pr_id=pr_id, focus_on_create=focus)

    def on_update(s: QALoopState):
        # Schedule UI update on the main thread
        app.call_from_thread(_on_qa_update, app, s)

    app._qa_loops[pr_id] = state
    _ensure_poll_timer(app)
    app.log_message(f"Starting QA for {pr_id}...")

    start_qa_background(state, app._root, pr, on_update)


def discard_qa_state(state: QALoopState | None) -> None:
    """Make a QA run dropped from ``app._qa_loops`` safe to abandon.

    Every path that discards a tracked run must go through this: a
    still-winding-down thread must not rewrite the resume snapshot (a later
    restart scan would resurrect the discarded run), and a *held* run
    (waiting for an INPUT_REQUIRED follow-up) would otherwise keep polling
    its worker panes forever — the hold has no timeout of its own.
    ``superseded`` is marked even when the run has no qa workdir yet
    (superseded during startup, before ``run_qa_sync`` creates one): it
    creates one later and must not snapshot the discarded run.
    """
    if state is None:
        return
    from pm_core import qa_loop
    state.stop_requested = True
    state.superseded = True
    if state.qa_workdir:
        qa_loop.clear_resume_file(state.qa_workdir)


def _enter_qa_status(app, pr: dict, caller: str) -> bool:
    """Transition *pr* to "qa" if it is in_review.

    Returns False (after logging) when project.yaml can't be updated, so
    the caller doesn't start a run whose status never moved.
    """
    if pr.get("status") != "in_review":
        return True
    pr_id = pr["id"]

    def _set_qa(d):
        p = store.get_pr(d, pr_id)
        if p and p.get("status") == "in_review":
            p["status"] = "qa"
    try:
        store.locked_update(app._root, _set_qa)
    except (store.StoreLockTimeout, store.ProjectYamlParseError) as e:
        app.log_message(f"Error: {e}")
        _log.warning("%s: %s for %s: %s", caller, type(e).__name__, pr_id, e)
        return False
    app._load_state()
    _log.info("%s: transitioned %s to qa status", caller, pr_id)
    return True


def _ensure_poll_timer(app) -> None:
    """Arm the shared 1 s poll timer that processes QA completion.

    The timer is otherwise armed only by a display refresh that sees an
    active PR with a workdir, or by a review loop.  A QA start on a PR
    whose workdir QA itself creates would never have its verdict handled
    (no self-driving restart, no lifecycle transition) until some
    unrelated refresh.
    """
    from pm_core.tui.review_loop_ui import _ensure_poll_timer as _ensure
    _ensure(app)


# ---------------------------------------------------------------------------
# Owed sign-off REQA: a durable start, independent of the auto-start switch
# ---------------------------------------------------------------------------
# A SIGNOFF_REQA bounce leaves ``signoff_return.awaiting == "qa"`` on a PR
# that is back at ``qa``: an owed *full* QA run.  The obligation is on disk,
# so it must not live only in one TUI's memory (a restart with auto-start off
# lost it and the PR sat at ``qa`` until someone pressed ``t``), and it must
# not be started over a run another live process drives (S117: the new loop
# retires that run's windows as stale and runs QA twice).

# How long ``arm_owed_reqa`` waits before reconciling: enough for the first
# frame to paint (see that function), short enough that the owed run still
# reads as "at startup".
_OWED_REQA_ARM_DELAY = 0.1


def _is_owed_reqa(pr: dict | None) -> bool:
    """Whether *pr* still owes the full QA run a sign-off REQA asked for.

    Only an **open** return record awaiting ``qa`` on a PR still at ``qa``
    qualifies — a bare ``qa`` status, a cleared/resolved return or a PR that
    moved on is not authorization.
    """
    from pm_core.signoff import open_return, return_awaiting
    if not pr or pr.get("status") != "qa":
        return False
    if return_awaiting(pr) != "qa":
        return False
    return open_return(pr) is not None


def owed_reqa_prs(app, prs: list[dict] | None = None) -> list[dict]:
    """The PRs whose open sign-off return still owes its QA run."""
    if prs is None:
        prs = (getattr(app, "_data", None) or {}).get("prs") or []
    return [pr for pr in prs if _is_owed_reqa(pr)]


def _disk_owed_state(app, pr_id: str) -> bool | None:
    """Whether the PR's *on-disk* return record still owes its QA run.

    ``None`` when the record cannot be read: a caller must not read that as
    "nothing is owed".
    """
    if not getattr(app, "_root", None):
        return None
    try:
        return _is_owed_reqa(store.get_pr(store.load(app._root), pr_id))
    except (store.ProjectYamlParseError, OSError):
        return None


def _owed_reqa_on_disk(app, pr_id: str) -> bool:
    """Whether the PR's return record on disk still owes its QA run."""
    return _disk_owed_state(app, pr_id) is True


def _owed_reqa_deferrals(app) -> dict:
    """``{pr_id: return-record ts}`` of deferrals already reported."""
    d = getattr(app, "_owed_reqa_deferrals", None)
    if not isinstance(d, dict):
        d = {}
        app._owed_reqa_deferrals = d
    return d


def _consume_owed_reqa_in_memory(app, pr_id: str) -> None:
    """Mirror the on-disk consumption of the obligation in this process.

    A QA start clears ``awaiting`` and the claim on disk (``start_qa``, the
    ``zz t`` loop, or another process's start).  The in-memory copy would
    otherwise keep saying the PR is owed, and the ~5 s reconciler would
    re-attempt the claim — a full project.yaml read plus a fsynced rewrite —
    until some other path reloads the state.
    """
    for pr in (getattr(app, "_data", None) or {}).get("prs") or []:
        if pr.get("id") != pr_id:
            continue
        rec = pr.get("signoff_return")
        # Only the hop this start consumed: a return awaiting a different
        # hop is not ours to clear, and clearing it here would hide it from
        # the scheduler until the next reload.
        if isinstance(rec, dict) and rec.get("awaiting") == "qa":
            rec["awaiting"] = None
            rec.pop("launch_claim", None)
        return


def start_owed_reqa(app, pr_id: str) -> bool:
    """Start the full QA a sign-off REQA owes, once across every driver.

    This TUI's poll tick, a restart, another TUI and ``pm pr auto-sequence``
    can all act on the same obligation; a second loop over the first retires
    its windows and duplicates verifier/finalizer panes.  The on-disk launch
    claim picks one winner, and ``start_qa`` clears ``awaiting`` (and the
    claim) as the run actually starts.  Returns whether this call started a
    loop (a start that bailed leaves the obligation for a later tick).
    """
    from pm_core.qa_loop import run_driven_elsewhere
    from pm_core.signoff import claim_return_launch

    if not getattr(app, "_root", None):
        return False
    # Only a *running* loop owns the PR: a finished one lingers in
    # ``_qa_loops`` for a poll tick (and a stopped one indefinitely), and
    # neither should strand the obligation.
    existing = app._qa_loops.get(pr_id)
    if existing is not None and existing.running:
        return False
    if run_driven_elsewhere(pr_id):
        return False
    if not claim_return_launch(app._root, pr_id, "qa", require_status="qa"):
        # Another driver holds the claim — or one already consumed the
        # obligation (its start cleared ``awaiting`` on disk).  The second
        # case must also drop this process's copy: otherwise every ~5 s tick
        # re-reads project.yaml and re-attempts the claim until some other
        # path reloads the state.
        if _disk_owed_state(app, pr_id) is False:
            _consume_owed_reqa_in_memory(app, pr_id)
        _log.info("owed REQA: %s launch claimed elsewhere or no longer owed",
                  pr_id)
        return False
    _log.info("owed REQA: starting the QA run for %s", pr_id)
    start_qa(app, pr_id)
    loop = app._qa_loops.get(pr_id)
    # A start that bailed keeps the obligation on disk (and in ``app._data``);
    # the claim expiry makes the next tick retry it.  A real start consumed
    # both, in ``start_qa``.
    return loop is not None and loop is not existing and loop.running


def reconcile_owed_reqa(app, prs: list[dict] | None = None) -> None:
    """Start the QA runs the project still owes a sign-off REQA.

    Runs from the shared poll tick and at mount, and is deliberately *not*
    gated by ``auto_start.is_enabled``/``in_scope``: a manual sign-off owes
    its re-run, and the obligation has to survive a restart with auto-start
    off.  A run another live process drives is waited out — the record keeps
    the obligation, so the next tick starts it when that run ends.
    """
    from pm_core.qa_loop import run_driven_elsewhere

    owed = owed_reqa_prs(app, prs)
    if not owed:
        return
    deferrals = _owed_reqa_deferrals(app)
    for pr in owed:
        pr_id = pr["id"]
        # A running loop of this process owns the PR (the user's ``t`` /
        # ``zz t``, or a run the resume scan just adopted).  A finished or
        # stopped entry does not: the obligation is still owed.
        loop = app._qa_loops.get(pr_id)
        if loop is not None and loop.running:
            deferrals.pop(pr_id, None)
            continue
        # The return record's ``ts`` names the episode, so the deferral is
        # reported once per bounce rather than every tick.  ``or ""`` keeps a
        # hand-edited record with no ``ts`` reportable at all — keying on
        # None would compare equal to "never reported" and swallow the line.
        ts = (pr.get("signoff_return") or {}).get("ts") or ""
        if run_driven_elsewhere(pr_id):
            if deferrals.get(pr_id) != ts:
                deferrals[pr_id] = ts
                reason = "the QA run another process drives"
                _log.info("owed REQA: %s waits for %s", pr_id, reason)
                app.log_message(escape(
                    f"Sign-off REQA for {pr_id} — QA starts once {reason} ends"),
                    sticky=10)
            continue
        deferrals.pop(pr_id, None)
        start_owed_reqa(app, pr_id)


def arm_owed_reqa(app) -> None:
    """Mount/routing hook: make sure an owed REQA is not left to memory.

    Arms the poll timer so the obligation is retried even when auto-start is
    off and no loop is running to keep the tick alive, then reconciles once
    against the in-memory state (both callers — the mount hook and the
    sign-off hop — reload it immediately before this, so no extra
    project.yaml read is needed).

    The reconcile itself is deferred by a timer tick: actually starting the
    run costs two locked project.yaml rewrites (the claim and the
    ``awaiting`` clear), ~1 s each on a large project, and the mount hook
    runs before the first frame — a restarted TUI with an owed REQA must not
    appear hung while it starts.  The obligation is on disk either way.
    """
    prs = (getattr(app, "_data", None) or {}).get("prs") or []
    if not owed_reqa_prs(app, prs):
        return
    _ensure_poll_timer(app)

    def _reconcile() -> None:
        # The caller's own guard cannot cover a deferred call, and a silent
        # failure here is exactly the bug this hook exists to prevent.
        try:
            reconcile_owed_reqa(app)
        except Exception:
            _log.warning("owed REQA arm: reconcile failed", exc_info=True)

    app.set_timer(_OWED_REQA_ARM_DELAY, _reconcile)


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
    if existing and (existing.running or existing.held):
        existing.stop_requested = True
        _log.info("fresh_start_qa: stopping running/held QA for %s", pr_id)

    # Remove from loops dict so start_qa doesn't see it as running
    app._qa_loops.pop(pr_id, None)
    discard_qa_state(existing)
    # Clear self-driving state so the fresh start is a one-shot QA
    app._self_driving_qa.pop(pr_id, None)

    # Start fresh — run_qa_sync will clean up old windows after capturing
    # which sessions were watching them (for proper session switching).
    app.log_message(f"Fresh QA start for {pr_id}...")
    start_qa(app, pr_id, focus=True)


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

    # If a QA loop is running (or holding for input), stop it
    existing = app._qa_loops.get(pr_id)
    if existing and (existing.running or existing.held):
        from pm_core import qa_loop
        # Persist the stop into the resume snapshot so a TUI restart before
        # the daemon rewrites it still recovers the STOPPED teardown instead
        # of the pre-stop PASS (see qa_loop.mark_stop_requested).
        qa_loop.mark_stop_requested(existing)
        # Also remove self-driving registration
        app._self_driving_qa.pop(pr_id, None)
        app.log_message(f"[bold]QA loop stopping[/] for {pr_id} (finishing current run)...")
        _log.info("qa_loop_ui: stopping QA loop for %s", pr_id)
        return

    # Remove stale loop state — run_qa_sync will clean up old windows
    # after capturing which sessions were watching them.
    discard_qa_state(existing)
    app._qa_loops.pop(pr_id, None)

    # Like start_qa: the first run of a loop on an in_review PR moves it
    # to qa (restarts go through start_qa, which already does this).
    if not _enter_qa_status(app, pr, "qa_loop_ui"):
        return

    # Like start_qa: this loop *is* the full re-run a sign-off REQA owes, so
    # consume the obligation as start_qa would.  This path starts the run
    # without going through start_qa; leaving ``awaiting`` behind would make
    # the owed-REQA reconciler start a second full run once this loop ends.
    from pm_core.signoff import clear_return_awaiting
    clear_return_awaiting(app._root, pr_id, "qa")
    _consume_owed_reqa_in_memory(app, pr_id)

    # Register self-driving QA state
    app._self_driving_qa[pr_id] = {
        "pass_count": 0,
        "required_passes": _get_qa_pass_count(),
    }

    # Start a new QA loop
    state = QALoopState(pr_id=pr_id, focus_on_create=True)

    def on_update(s: QALoopState):
        app.call_from_thread(_on_qa_update, app, s)

    app._qa_loops[pr_id] = state
    _ensure_poll_timer(app)

    required = app._self_driving_qa[pr_id]["required_passes"]
    passes_label = f" ({required} pass{'es' if required > 1 else ''} required)" if required > 1 else ""
    app.log_message(
        f"[bold]QA loop started[/] for {pr_id}{passes_label} — z t to stop",
        sticky=3, force=True,
    )
    _log.info("qa_loop_ui: starting QA loop for %s (passes=%d)", pr_id, required)

    start_qa_background(state, app._root, pr, on_update)


# ---------------------------------------------------------------------------
# Stop (public API for command bar etc.)
# ---------------------------------------------------------------------------

def stop_qa(app, pr_id: str) -> None:
    """Request graceful stop of QA for a PR."""
    state = app._qa_loops.get(pr_id)
    if state and (state.running or state.held):
        from pm_core import qa_loop
        # Persist the stop so a restart before the daemon rewrites its
        # snapshot still recovers the clean STOPPED teardown rather than the
        # pre-stop PASS (see qa_loop.mark_stop_requested).
        qa_loop.mark_stop_requested(state)
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
            first_completion = not state._ui_complete_notified
            _on_qa_complete(app, state)
            # The held watcher can reopen the run (running=True) between the
            # check above and here — _on_qa_complete does file I/O for the
            # note, and a follow-up can arrive at any moment.  A reopened run
            # must keep its state and resume snapshot: falling through would
            # clear the snapshot and mark the completion notified, so the
            # reopened run's eventual verdict would never be processed.
            if state.running:
                continue
            # A held run finalized INPUT_REQUIRED but is still watching its
            # worker panes for a follow-up.  Keep the state tracked and the
            # resume snapshot on disk so a restart can re-adopt the wait; the
            # held watcher resets the completion flags when it reopens.
            # Only an INPUT_REQUIRED result can be held: a crashed/aborted
            # run (ERROR) or any other verdict must take the normal path so
            # the state is not pinned in _qa_loops forever.
            if state.held and state.latest_verdict == VERDICT_INPUT_REQUIRED:
                if first_completion:
                    state._ui_complete_notified = True
                    from pm_core import qa_loop
                    qa_loop.mark_completion_processed(state)
                continue
            # The hold can also reopen the run *between* the two checks
            # above: it publishes running=True before clearing held, so the
            # first check can read the pre-reopen False while the second
            # reads the already-cleared held.  Falling through then would
            # clear the reopened run's snapshot (the follow-up it reopened
            # for is still being collected) and mark its completion
            # notified.  Re-check running after the held branch so every
            # reopen ordering keeps the run.
            if state.running:
                continue
            # The completion has now been processed (note recorded,
            # lifecycle transition done).  Drop the resume snapshot
            # immediately rather than waiting for the tick-2 cleanup
            # below: a PASS that leaves the PR in "qa" (auto-start off)
            # keeps both the snapshot and status=="qa" until tick 2, so a
            # TUI restart in that one-tick gap would let
            # _resume_incomplete_qa re-run _on_qa_complete and record a
            # duplicate QA note.  Clearing here closes that window.
            if first_completion and state.qa_workdir:
                from pm_core import qa_loop
                qa_loop.clear_resume_file(state.qa_workdir)
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
        # After the resume scan, so a run it just adopted is visible in
        # _qa_loops and the owed start waits for it instead of racing it.
        reconcile_owed_reqa(app)
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
        # Not orphaned: another live process (a `pm pr auto-sequence` QA
        # child) is driving it.  Re-checked each scan, so the run is still
        # recovered if that process dies before finishing.
        if qa_loop.resume_owned_elsewhere(rdata):
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

        # A held run finalized INPUT_REQUIRED but was still watching its
        # worker panes.  Keep it tracked and re-spawn the watcher rather
        # than processing it as a finished run: a follow-up that landed
        # during downtime must be collected, and an already-processed
        # result must not be noted/transitioned twice.
        if state.held and state.waiting_for_input:
            state.running = True
            if not state.completion_processed:
                # The held result finalized while the TUI was down and was
                # never recorded.  Note it here, exactly as the live path
                # does when it publishes the held result: the re-spawned
                # watcher sets ``running`` immediately, so the normal
                # completion poll never observes (not running,
                # INPUT_REQUIRED) and the note would otherwise be lost
                # whenever no follow-up ever arrives (stop, PR leaves qa,
                # the user abandons the wait).  Persist the flag so a second
                # restart does not note it again.
                _on_qa_complete(app, state)
                qa_loop.mark_completion_processed(state)
            else:
                app.log_message(
                    f"QA for {pr_id} is waiting for input — still watching "
                    "for a follow-up verdict...")
            state._ui_complete_notified = True

            def _on_update(s, _app=app):
                _app.call_from_thread(_on_qa_update, _app, s)

            app._qa_loops[pr_id] = state
            _log.info("Re-adopting held QA run for %s (waiting=%s, "
                      "processed=%s)", pr_id,
                      sorted(state.waiting_for_input),
                      state.completion_processed)
            qa_loop.resume_qa_background(state, app._root, pr, _on_update)
            continue

        if overall:
            # Completed during downtime — process and clear the snapshot.
            # A snapshot whose result the TUI already noted (a held run that
            # ended its hold without a follow-up: stop, PR left qa, last
            # attempt dropped) must not be noted/transitioned a second time.
            state.running = False
            # A stop that landed while the (blocking) finalize pane was
            # polling left the pre-finalize PASS on disk: the daemon converts
            # it to the terminal STOPPED teardown, but it was interrupted
            # first.  Record the same verdict the live loop would have, and
            # keep the status pane agreeing with it.
            state.latest_verdict = qa_loop.recovered_overall_verdict(
                state, overall)
            if state.latest_verdict != overall:
                _log.info("Recovered QA for %s was stopped during finalize — "
                          "reporting %s instead of %s", pr_id,
                          state.latest_verdict, overall)
                if state.qa_workdir:
                    qa_loop.set_status_overall(state.qa_workdir,
                                               state.latest_verdict)
            _log.info("Recovered completed QA from disk: %s → %s (processed=%s)",
                      pr_id, state.latest_verdict, state.completion_processed)
            if not state.completion_processed:
                _on_qa_complete(app, state)
            # Mirror the verdict into runtime_state, exactly as the live
            # completion path in ``poll_qa_state`` does.  A recovered run is
            # not tracked in ``app._qa_loops``, so that path never sees it;
            # without this record ``recorded_qa_verdict`` returns None and
            # auto-start relaunches QA for a run the user stopped (STOPPED is
            # a ``QA_HOLD_VERDICTS`` entry precisely so it does not).  It
            # also keeps the popup's ``[done VERDICT]`` in step for the other
            # recovered verdicts.
            try:
                from pm_core import runtime_state as _rs
                _rs.set_action_state(pr_id, "qa", "done",
                                     verdict=state.latest_verdict)
            except Exception:
                _log.debug("runtime_state qa verdict mirror failed for a "
                           "recovered run", exc_info=True)
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
        # Escape: the log line renders markup, which would swallow the
        # "[pr-…]" prefix and bracketed parts like "[finalize: …]".
        app.log_message(escape(f"QA [{state.pr_id}]: {state.latest_output}"))


def _on_qa_complete(app, state: QALoopState) -> None:
    """Handle QA completion — trigger appropriate lifecycle transition.

    Self-driving mode (zz t):
      - PASS (no changes): increment pass_count; if >= required_passes,
        clear self-driving state and defer to auto-start (sign-off, then
        merge per policy) or the user — manual ``zz t`` does NOT trigger
        sign-off or a merge itself.  Otherwise restart QA.
      - NEEDS_WORK / changes: reset pass_count, transition to in_review,
        and directly start a review loop (independent of auto-start).
      - INPUT_REQUIRED: the run is held — the loop keeps watching the
        scenario worker panes for a follow-up verdict (pr-2c67d50) and
        resumes this self-driving loop when one lands, so it is not
        "paused" unless the hold ends without a follow-up (stop, or the
        PR leaving qa).
      - STOPPED: a user stop that left no QA result (no plan, no
        scenario verdict, or a stop while the finalizer was running) —
        clean teardown, no lifecycle transition and no QA note.

    Legacy mode (plain t or auto-start):
      - PASS: hand off to the sign-off step when auto-start is enabled
        (only a fresh SIGNOFF_MERGE then reaches the merge / manual-merge
        wait).
      - NEEDS_WORK: transition to in_review, rely on auto-start.
    """
    if state._ui_complete_notified:
        return
    # The held watcher can clear ``latest_verdict`` (reopening the run) while
    # this call is being set up; a completion with no verdict has nothing to
    # record, and noting it would write a bogus "QA : ..." note.
    if not state.latest_verdict:
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
                if _owed_reqa_on_disk(app, pr_id):
                    # This loop's run began before sign-off bounced the PR
                    # (a later ``start_qa`` restart would have consumed the
                    # obligation), so its PASS verified the code sign-off
                    # judged.  Handing off would drop the owed full re-run;
                    # ending the loop leaves it to the owed-REQA reconciler.
                    app.log_message(
                        f"[green]QA PASS[/] for {pr_id} "
                        f"({sd['pass_count']}/{required} consecutive) — the "
                        "owed sign-off re-run has not run yet")
                elif _auto_start.in_scope(app, pr_id):
                    app.log_message(
                        f"[green bold]QA PASS[/] for {pr_id} "
                        f"({sd['pass_count']}/{required} consecutive) — "
                        "handing off to sign-off"
                    )
                    _trigger_signoff(app, pr_id)
                else:
                    app.log_message(
                        f"[green bold]QA PASS[/] for {pr_id} "
                        f"({sd['pass_count']}/{required} consecutive) — "
                        "press i to sign off"
                    )
            else:
                # Override any sticky line, then hold the pass count against
                # start_qa's same-frame "Starting QA for ...".
                from pm_core.tui import auto_start as _auto_start
                app.log_message(
                    f"[green]QA PASS[/] for {pr_id} "
                    f"({sd['pass_count']}/{required} consecutive) — restarting QA",
                    force=True, hold=_auto_start.CONFIRM_HOLD_SECONDS,
                )
                _log.info("QA self-driving: %d/%d passes, restarting QA",
                          sd["pass_count"], required)
                start_qa(app, pr_id)
        else:
            # Legacy path — sign-off hand-off only when auto-start is active
            from pm_core.tui import auto_start as _auto_start
            if _owed_reqa_on_disk(app, pr_id):
                # A run that was already in flight when sign-off sent the PR
                # back verified the code the router judged, not the rework.
                # Handing the PR to sign-off on its PASS would supersede the
                # full re-run the bounce owes (the owed run clears
                # ``awaiting`` as it starts, so this only ever catches a
                # pre-return run).
                app.log_message(
                    f"[green]QA PASS[/] for {pr_id} — the owed sign-off "
                    "re-run has not run yet")
            elif _auto_start.in_scope(app, pr_id):
                app.log_message(
                    f"[green bold]QA PASS[/] for {pr_id} — handing off to sign-off")
                _trigger_signoff(app, pr_id)
            else:
                app.log_message(
                    f"[green bold]QA PASS[/] for {pr_id} — press i to sign off"
                )
    elif verdict == VERDICT_NEEDS_WORK:
        # Issues found or changes committed → back to review.  Override any
        # sticky line and hold against the same-frame "Review loop started".
        from pm_core.tui import auto_start as _auto_start
        app.log_message(
            f"[yellow bold]QA NEEDS_WORK[/] for {pr_id} — returning to review",
            force=True, hold=_auto_start.CONFIRM_HOLD_SECONDS,
        )
        _transition_pr_status(app, pr_id, "qa", "in_review")
        # Clear the stale review loop entry from the previous review pass
        app._review_loops.pop(pr_id, None)
        # Reload in-memory state and repaint, so the tree shows in_review
        # even when nothing else (auto-start, a review loop) refreshes it.
        # Not _load_state(): its scheduler hook would duplicate the
        # check_and_start below.  Preserve its flush-before-reload invariant
        # so a debouncing navigation write isn't replaced by stale disk state.
        if app._root:
            wq = getattr(app, "_write_queue", None)
            if wq is not None:
                wq.flush_sync()
            try:
                app._data = store.load(app._root)
            except store.ProjectYamlParseError:
                pass  # keep existing app._data
            else:
                app._update_display()

        if sd:
            # Self-driving: reset pass count and directly start review loop
            sd["pass_count"] = 0
            _log.info("QA self-driving: NEEDS_WORK — starting review loop directly")
            _start_self_driving_review(app, pr_id)
        else:
            # Legacy: rely on auto-start
            if _auto_start.is_enabled(app):
                app.run_worker(_auto_start.check_and_start(app))
    elif verdict == VERDICT_INPUT_REQUIRED:
        if state.held:
            app.log_message(
                f"[red bold]QA INPUT_REQUIRED[/] for {pr_id} — waiting for "
                "input in the scenario worker pane (still watching for a "
                "follow-up verdict)"
            )
        else:
            app.log_message(
                f"[red bold]QA INPUT_REQUIRED[/] for {pr_id} — paused for human input"
            )
        if sd:
            # A held run is not paused: it keeps watching the worker pane and
            # resumes the self-driving loop when the follow-up lands.
            _log.info(
                "QA self-driving: INPUT_REQUIRED — %s",
                "holding the run for a follow-up verdict" if state.held
                else "loop paused")
    elif verdict == VERDICT_STOPPED:
        # The user stopped the run before it produced a QA result (during
        # planning, before any scenario reported, or while the finalizer
        # was running).  This is a clean teardown, not a QA result: no
        # lifecycle transition, no INPUT_REQUIRED surface, and no QA note
        # on the PR.
        app.log_message(f"QA stopped for {pr_id} — no verdict recorded")
        return
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


def _trigger_signoff(app, pr_id: str) -> None:
    """Hand a QA-passed PR to the sign-off step (auto-start only).

    Never merges: the sign-off driver (``signoff_ui``) routes the router's
    verdict, and only a fresh SIGNOFF_MERGE reaches ``_maybe_auto_merge``.
    ``start_signoff`` re-checks auto-start status and scope.
    """
    from pm_core.tui import signoff_ui
    signoff_ui.start_signoff(app, pr_id)


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
        note_text = f"QA {state.latest_verdict}: " + qa_outcome_detail(state)
        # Tell the next review session why QA bounced an all-PASS run.
        note_text += planner_code_changes_suffix(state)
        # ... or why a follow-up PASS after an INPUT_REQUIRED wait still
        # needs review (the PR head moved while the scenario waited).
        note_text += input_wait_changes_suffix(state)
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
