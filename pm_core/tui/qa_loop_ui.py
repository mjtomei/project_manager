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
    start_qa_background,
    _compute_qa_window_name,
    planner_code_changes_suffix,
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
                app.log_message(f"Focused QA window for {pr_id}")
            else:
                app.log_message(
                    f"QA window for {pr_id} ready (focus suppressed)")
            return

    # No existing window — start a new QA session.  qa_loop will
    # consume any suppress_switch flag at its window-creation step.
    start_qa(app, pr_id)


def _ensure_qa_poll_timer(app) -> None:
    """Start the shared poll timer for a newly registered QA loop.

    Only that timer (``poll_qa_state``) processes a finished run: the
    completion message, lifecycle transition and snapshot cleanup.  The
    TUI otherwise starts it only when some active PR already has a
    workdir, which a PR's first QA run (no workdir yet) does not satisfy,
    so the completion waited for the next 300 s background sync.
    """
    from pm_core.tui.review_loop_ui import _ensure_poll_timer
    _ensure_poll_timer(app)


def start_qa(app, pr_id: str) -> bool | None:
    """Start a QA session for a PR.

    Creates QALoopState, starts background QA thread.
    Called by auto-start and internal callers (fresh_start, loop start).
    Returns False when project.yaml could not be loaded or locked.
    """
    if not app._root:
        app.log_message("No project root")
        return

    try:
        data = store.load(app._root)
    except store.ProjectYamlParseError as e:
        app.log_message(f"Error: {e}")
        return False
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

    # A sign-off REQA return is now being re-verified.
    from pm_core.signoff import clear_return_awaiting
    clear_return_awaiting(app._root, pr_id, "qa")

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
            return False
        app._load_state()
        _log.info("start_qa: transitioned %s to qa status", pr_id)

    state = QALoopState(pr_id=pr_id)

    def on_update(s: QALoopState):
        # Schedule UI update on the main thread
        app.call_from_thread(_on_qa_update, app, s)

    app._qa_loops[pr_id] = state
    _ensure_qa_poll_timer(app)
    app.log_message(f"Starting QA for {pr_id}...")

    start_qa_background(state, app._root, pr, on_update)
    return True


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
        # The new run supersedes it: stop it and drop its snapshot now
        # rather than when its thread winds down.  The new run has none
        # until its scenarios launch, so until then a restart would revive
        # the old run.
        from pm_core import qa_loop
        qa_loop.supersede_run(existing)
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
    _ensure_qa_poll_timer(app)

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
        # Drop scenario keys of an earlier run of this PR.  A run replaced
        # in _qa_loops (z t over a running run, a zz t restart) never
        # reaches the completion unregister below, and nothing polls its
        # keys again, so mid-turn panes stayed "active" for good: the
        # node kept a QA spinner after the new run finished.  Keys this
        # run registered stay: while a queued scenario launches,
        # ``state.scenarios`` holds only that scenario (S36).
        live = {f"qa:{pr_id}:s{sc.index}" for sc in state.scenarios}
        live |= state._ui_tracker_keys
        for key in tracker.tracked_keys():
            if key.startswith(f"qa:{pr_id}:") and key not in live:
                tracker.unregister(key)
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
            state._ui_tracker_keys.add(key)
            tracker.poll(key)

        if not state.running and state.latest_verdict:
            # The result is recorded in project.yaml (transition, note).
            # While the file cannot be loaded, keep the run and its
            # snapshot and process it once it loads (RQ37).
            if _completion_waits_for_project(app, state):
                continue
            if app._qa_loops.get(pr_id) is not state:
                # A retried zz t restart (below) replaced this run.
                if state.qa_workdir:
                    from pm_core import qa_loop
                    qa_loop.clear_resume_file(state.qa_workdir)
                continue
            first_completion = not state._ui_complete_notified
            if first_completion and not _on_qa_complete(app, state):
                # Its writes failed (the file broke after the check):
                # nothing followed, the whole completion is retried.
                continue
            if first_completion and state._ui_pending:
                # A follow-up failed the same way: retried, snapshot kept.
                state._ui_complete_notified = True
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
    app._qa_resume_poll_counter += 1


def _project_load_error(app) -> Exception | None:
    """Why project.yaml cannot be loaded now (conflict markers, plans that
    do not validate, the file missing), or None when it loads."""
    if not app._root:
        return None
    try:
        store.load(app._root)
    except store.ProjectYamlParseError as e:  # incl. invalid plans, missing
        return e
    except Exception:
        return None
    return None


def _completion_waits_for_project(app, state: QALoopState) -> bool:
    """True while a finished run's result cannot be recorded yet.

    A completion writes its lifecycle transition and QA note to
    project.yaml.  Processing it while the file cannot be loaded lost both:
    the writes only logged a warning and the snapshot was cleared right
    after, so nothing retried (RQ37).  Wait instead, saying so once per
    reason, and retry follow-ups that failed in between.
    """
    err = _project_load_error(app)
    if err is not None:
        reason = str(err)
        if state._ui_wait_reason != reason:
            state._ui_wait_reason = reason
            verdict = state.latest_verdict
            _log.warning("QA %s for %s: result kept until project.yaml "
                         "loads again: %s", verdict, state.pr_id, reason)
            app.log_message(escape(
                f"QA {verdict} for {state.pr_id} — waiting for project.yaml "
                f"to load to record it: {reason}"))
        return True
    if state._ui_wait_reason is not None:
        state._ui_wait_reason = None
        _log.info("QA %s for %s: project.yaml loads again — recording the "
                  "result", state.latest_verdict, state.pr_id)
    if state._ui_pending:
        state._ui_pending[:] = [f for f in state._ui_pending if f() is False]
        if state._ui_pending:
            return True
    return False


def _follow_up(state: QALoopState, action) -> None:
    """Run a completion follow-up; keep it for a retry when it reports
    (False) that project.yaml could not be loaded."""
    if action() is False:
        state._ui_pending.append(action)


def _record_completion(app, state: QALoopState) -> bool:
    """Write the run's result to project.yaml: the NEEDS_WORK → in_review
    transition and the QA note, each once.  False when one could not be
    written; nothing that depends on the result runs before both are."""
    done = state._ui_writes_done
    if (state.latest_verdict == VERDICT_NEEDS_WORK
            and "transition" not in done):
        if not _transition_pr_status(app, state.pr_id, "qa", "in_review"):
            return False
        done.add("transition")
    if "note" not in done:
        if not _record_qa_note(app, state):
            return False
        done.add("note")
    # The snapshot may outlive this for a pending follow-up: say which
    # clone's project.yaml holds the result, so only this session's TUI
    # re-processes it (S49).
    if state.qa_workdir:
        from pm_core import qa_loop
        qa_loop.mark_result_recorded(state.qa_workdir, state.loop_id)
    return True


def _reload_tree(app) -> bool:
    """Reload and repaint, so the tree shows a status change now rather
    than at the next 300 s background sync.  False on an unloadable file."""
    if not app._root:
        return True
    try:
        app._data = store.load(app._root)
    except store.ProjectYamlParseError:
        return False  # keep existing app._data
    app._update_display()
    return True


def _drop_superseded(pr_id, snaps, live_workdirs) -> None:
    """Drop this session's snapshots of *pr_id* that a newer run of it
    superseded (finished or not, so a later restart cannot revive a stale
    run) unless something still drives them: an in-memory loop here or a
    live process elsewhere.  Their status, verdicts and transcripts stay."""
    from pm_core import qa_loop
    for resume_file, rdata, _overall in snaps:
        if (str(resume_file.parent) not in live_workdirs
                and str(rdata.get("qa_workdir")) not in live_workdirs
                and not qa_loop.resume_owned_elsewhere(rdata)):
            _log.info("Dropping superseded QA resume snapshot for %s: %s",
                      pr_id, resume_file.parent)
            qa_loop.clear_resume_file(resume_file.parent)


_NO_STAMP = object()


def _project_file_stamp(root) -> tuple | None:
    """Identity of *root*'s project.yaml (changes on any save or pull)."""
    from pathlib import Path
    if not root:
        return None
    try:
        st = (Path(root) / "project.yaml").stat()
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


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

    # Defer the (relatively expensive) project load until a snapshot of a
    # PR not tracked here is found — this runs on the ~1s poll tick.
    project_data = None

    # A fresh start (z t) stops the old loop without processing its
    # completion, so its snapshot outlives it next to the new run's.  Only
    # the newest run per PR is a candidate.  Runs of a PR number their
    # scenarios on from the earlier runs' launched ones
    # (_next_scenario_offset), so the run's first scenario index orders
    # them.  Not the highest: queued scenarios get no workdir, so an older
    # run's queued tail can exceed a newer run's numbers.  A run whose
    # planner produced no scenarios uses the start index it was given.  Nor
    # mtime: a late write from a stopped run, or an older orphan, may be
    # newer.  Ties (runs started together) prefer unfinished, then the
    # newest snapshot.
    def _mtime(p):
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    def _overall(qa_dir):
        try:
            sdata = json.loads((qa_dir / "qa_status.json").read_text())
            return sdata.get("overall", "")
        except (json.JSONDecodeError, OSError):
            return ""

    def _run_order(rdata):
        idx = [s["index"] for s in rdata.get("scenarios") or []
               if isinstance(s, dict) and isinstance(s.get("index"), int)]
        if idx:
            return min(idx)
        start = rdata.get("scenario_start")
        return start if isinstance(start, int) else 0

    by_pr: dict[str, list] = {}
    for resume_file in qa_root.glob("*/qa_resume.json"):
        try:
            rdata = json.loads(resume_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        pr_id = rdata.get("pr_id", "")
        if pr_id:
            by_pr.setdefault(pr_id, []).append(
                (resume_file, rdata, _overall(resume_file.parent)))
    # ~/.pm/workdirs/qa is shared by every project under ~/.pm.  Another
    # project's runs are its own TUI's to resume or drop: treating its PR
    # as "left QA" here deleted a live run's snapshot as soon as its TUI
    # died, so that TUI's restart had nothing to resume (S39).  Foreign
    # ids are remembered: another project's snapshot can outlive many scans
    # (its run is live, or its TUI never comes back), and each would
    # otherwise reload this project.  They are forgotten whenever
    # project.yaml changes, so a PR pulled or added after its snapshot was
    # first seen becomes eligible on the next scan.
    stamp = _project_file_stamp(app._root)
    if (not hasattr(app, "_foreign_qa_pr_ids")
            or getattr(app, "_foreign_qa_stamp", None) != stamp):
        app._foreign_qa_pr_ids = set()
        app._foreign_qa_stamp = stamp
    foreign = app._foreign_qa_pr_ids
    by_pr = {k: v for k, v in by_pr.items() if k not in foreign}

    def _load_project():
        # An unloadable project.yaml must not escape: the poll tick
        # re-raises, which kills the TUI and every QA loop it drives (S41).
        # A conflicted git pull leaves conflict markers or plan references
        # that do not validate, and a checkout unlinks the file before
        # rewriting it.  Retry on the next scan.
        try:
            return store.load(app._root)
        except (store.ProjectYamlParseError, OSError) as e:
            # A missing file has no stamp (None): compare against a
            # sentinel, or a fresh TUI never logs that skip (S44).
            if getattr(app, "_resume_parse_error_stamp", _NO_STAMP) != stamp:
                app._resume_parse_error_stamp = stamp
                _log.warning("QA resume scan skipped until project.yaml "
                             "loads again: %s", e)
            return None

    known = set(app._qa_loops) | app._resumed_qa_pr_ids
    if set(by_pr) - known:
        if not app._root:
            return
        project_data = _load_project()
        if project_data is None:
            return
        known |= {p.get("id") for p in project_data.get("prs") or []}
        foreign.update(set(by_pr) - known)
        by_pr = {k: v for k, v in by_pr.items() if k in known}

    live_workdirs = {str(s.qa_workdir) for s in app._qa_loops.values()
                     if getattr(s, "qa_workdir", None)}

    def _shown_status(pr_id):
        for p in (app._data or {}).get("prs") or []:
            if p.get("id") == pr_id:
                return p.get("status")
        return None
    # Runs of one PR from two clones (two pm sessions) are independent:
    # neither supersedes the other, whichever started later.  Ordering and
    # the superseded drop apply within one session's runs, and only this
    # session's are dropped here: another clone's older runs are its own
    # TUI's to drop.  Dropping them on liveness lost a clone's run as soon
    # as its TUI died, so its restart had nothing to resume (S43).
    candidates = []
    own_prs = set()
    for pr_id, snaps in by_pr.items():
        by_session: dict = {}
        for snap in snaps:
            tag = snap[1].get("session_tag")
            key = tag if qa_loop.launched_elsewhere(tag) else None
            by_session.setdefault(key, []).append(snap)
        if None in by_session:
            own_prs.add(pr_id)
        for key, group in by_session.items():
            group.sort(key=lambda s: (-_run_order(s[1]), bool(s[2]),
                                      -_mtime(s[0])))
            candidates.append(group[0])
            if key is not None:
                continue
            _drop_superseded(pr_id, group[1:], live_workdirs)

    for resume_file, rdata, overall in candidates:
        pr_id = rdata["pr_id"]
        if pr_id in app._qa_loops or pr_id in app._resumed_qa_pr_ids:
            continue
        # Not orphaned: another live process (a `pm pr auto-sequence` QA
        # child) is driving it.  Re-checked each scan, so the run is still
        # recovered if that process dies before finishing.
        if qa_loop.resume_owned_elsewhere(rdata):
            continue

        # A finished run whose result another clone's TUI already recorded
        # (in its own project.yaml) and kept for a pending follow-up is that
        # TUI's to finish, even when this session launched the run: this
        # project.yaml lacks that note, so recovering it here recorded the
        # run a second time (S49).  Recorded here, it is processed here
        # (the note is deduplicated), wherever it was launched.
        recorded_by = rdata.get("result_recorded_by") if overall else None
        if recorded_by and qa_loop.launched_elsewhere(recorded_by):
            foreign.add(pr_id)
            continue
        ours = (not qa_loop.launched_elsewhere(rdata.get("session_tag"))
                or bool(recorded_by))

        # Only resume PRs still in QA — skip (and forget) ones that have
        # already moved on.
        if not app._root:
            continue
        if project_data is None:
            project_data = _load_project()
            if project_data is None:
                return
        pr = store.get_pr(project_data, pr_id)
        if not pr or pr.get("status") != "qa":
            # A run launched from another clone (its own pm session) may
            # be in QA in that clone's project.yaml but not in this one
            # yet: dropping its snapshot would leave nothing to resume (as
            # in S39), whether or not that session is still up — a pull
            # can still bring the PR here in QA and this TUI then adopts
            # it.  Only this session's own runs are cleaned up here.
            # Leave it until this project.yaml changes.
            if not ours:
                foreign.add(pr_id)
                continue
            # The PR has left QA, so this snapshot can never be validly
            # resumed (resume requires status == "qa").  Drop it so it
            # doesn't linger on disk or get mistakenly picked up if the
            # PR ever returns to QA under a different loop_id.
            app._resumed_qa_pr_ids.add(pr_id)
            qa_loop.clear_resume_file(resume_file.parent)
            continue

        # This clone QA'd the PR alongside the other clone's run (its own
        # run of it is resumable, or ended after that run started): that run
        # is the other clone's to resume, not an orphan to adopt here, also
        # after this TUI restarts (S43).  Adopted are runs of a PR that
        # reached QA here by a pull or an edit (S41), and runs started after
        # this clone's own QA of the PR was over.
        if not ours and (
                pr_id in own_prs or qa_loop.run_overlaps_own_run(
                    pr_id, (qa_loop.read_run_record(resume_file.parent)
                            or {}).get("started_at"))):
            continue

        # The ownership check above read the snapshot earlier; another TUI
        # may have adopted the run since.  Claim it atomically (S41).
        claimed = qa_loop.claim_resume_file(resume_file.parent,
                                            rdata.get("loop_id"))
        if claimed is None:
            continue
        rdata = claimed

        # A PR that reached project.yaml (or reached QA in it) by a git pull
        # or an edit outside pm, neither of which signals a reload, is not in
        # the tree yet or is shown at its old status; reload now rather than
        # at the next 300 s background sync (S41, S42).
        if _shown_status(pr_id) != pr.get("status"):
            app._load_state()

        # Is the run already complete (daemon wrote overall, TUI died
        # before processing)?  *overall* comes from the display status file.
        state = qa_loop.build_resume_state(rdata)
        app._resumed_qa_pr_ids.add(pr_id)

        if overall:
            # Completed during downtime — process and clear the snapshot.
            state.running = False
            state.latest_verdict = overall
            _log.info("Recovered completed QA from disk: %s → %s", pr_id, overall)
            recorded = _on_qa_complete(app, state)
            if not recorded or state._ui_pending:
                # The file broke since the scan loaded it: the poll timer
                # retries (the whole completion, or a failed follow-up)
                # and then clears the snapshot.
                state._ui_complete_notified = recorded
                app._qa_loops[pr_id] = state
                _ensure_qa_poll_timer(app)
                continue
            state._ui_complete_notified = True
            try:
                from pm_core import runtime_state as _rs
                _rs.set_action_state(pr_id, "qa", "done", verdict=overall)
            except Exception:
                _log.debug("runtime_state qa verdict mirror failed",
                           exc_info=True)
            if state.qa_workdir:
                qa_loop.clear_resume_file(state.qa_workdir)
            continue

        # Still in progress — re-spawn the orchestration loop.
        def _on_update(s, _app=app):
            _app.call_from_thread(_on_qa_update, _app, s)

        app._qa_loops[pr_id] = state
        _ensure_qa_poll_timer(app)
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


def _on_qa_complete(app, state: QALoopState) -> bool:
    """Handle QA completion — trigger appropriate lifecycle transition.

    Self-driving mode (zz t):
      - PASS (no changes): increment pass_count; if >= required_passes,
        clear self-driving state and defer to auto-start (sign-off, then
        merge per policy) or the user — manual ``zz t`` does NOT trigger
        sign-off or a merge itself.  Otherwise restart QA.
      - NEEDS_WORK / changes: reset pass_count, transition to in_review,
        and directly start a review loop (independent of auto-start).
      - INPUT_REQUIRED: pause self-driving loop for human input.

    Legacy mode (plain t or auto-start):
      - PASS: hand off to the sign-off step when auto-start is enabled
        (only a fresh SIGNOFF_MERGE then reaches the merge / O stop).
      - NEEDS_WORK: transition to in_review, rely on auto-start.

    The result (transition, QA note) is written first, and nothing that
    depends on it runs until both writes took: False when one failed
    because project.yaml could not be loaded or locked, and the caller
    retries the whole completion (RQ37).  A follow-up that hits the same
    failure afterwards is kept in ``state._ui_pending`` for a retry.
    """
    if state._ui_complete_notified:
        return True

    pr_id = state.pr_id
    verdict = state.latest_verdict
    sd = app._self_driving_qa.get(pr_id)

    if not _record_completion(app, state):
        return False

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
                if _auto_start.in_scope(app, pr_id):
                    app.log_message(
                        f"[green bold]QA PASS[/] for {pr_id} "
                        f"({sd['pass_count']}/{required} consecutive) — "
                        "handing off to sign-off"
                    )
                    _follow_up(state, lambda: _trigger_signoff(app, pr_id))
                else:
                    app.log_message(
                        f"[green bold]QA PASS[/] for {pr_id} "
                        f"({sd['pass_count']}/{required} consecutive) — "
                        "press i to sign off"
                    )
            else:
                # Hold the line: start_qa's own messages in this same frame
                # would otherwise replace it before it is ever painted.  Force
                # it too, or a sticky line (e.g. another PR's review loop)
                # still showing would drop it unseen.
                from pm_core.tui import auto_start as _auto_start
                app.log_message(
                    f"[green]QA PASS[/] for {pr_id} "
                    f"({sd['pass_count']}/{required} consecutive) — restarting QA",
                    force=True, hold=_auto_start.CONFIRM_HOLD_SECONDS,
                )
                _log.info("QA self-driving: %d/%d passes, restarting QA",
                          sd["pass_count"], required)
                _follow_up(state, lambda: start_qa(app, pr_id))
        else:
            # Legacy path — sign-off hand-off only when auto-start is active
            from pm_core.tui import auto_start as _auto_start
            if _auto_start.in_scope(app, pr_id):
                app.log_message(
                    f"[green bold]QA PASS[/] for {pr_id} — handing off to sign-off")
                _follow_up(state, lambda: _trigger_signoff(app, pr_id))
            else:
                app.log_message(
                    f"[green bold]QA PASS[/] for {pr_id} — press i to sign off"
                )
    elif verdict == VERDICT_NEEDS_WORK:
        # Issues found or changes committed → back to review.  Held and
        # forced like the restart line: the self-driving review loop's
        # sticky "Review loop started" lands in this same frame and would
        # otherwise replace it before it is ever painted (S28).
        from pm_core.tui import auto_start as _auto_start
        app.log_message(
            f"[yellow bold]QA NEEDS_WORK[/] for {pr_id} — returning to review",
            force=True, hold=_auto_start.CONFIRM_HOLD_SECONDS,
        )
        # (The qa → in_review transition was written above.)
        # Clear the stale review loop entry from the previous review pass
        app._review_loops.pop(pr_id, None)
        # Reload in-memory state and repaint, so the tech tree shows
        # in_review now rather than at the next 300 s background sync.
        _follow_up(state, lambda: _reload_tree(app))

        if sd:
            # Self-driving: reset pass count and directly start review loop
            sd["pass_count"] = 0
            _log.info("QA self-driving: NEEDS_WORK — starting review loop directly")
            _follow_up(state, lambda: _start_self_driving_review(app, pr_id))
        else:
            # Legacy: rely on auto-start
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

    return True


def _start_self_driving_review(app, pr_id: str) -> bool | None:
    """Start a review loop for a self-driving QA PR (independent of auto-start).

    Returns False when project.yaml could not be loaded (retry)."""
    from pm_core.tui import review_loop_ui, auto_start as _auto_start

    if not app._root:
        return

    try:
        data = store.load(app._root)
    except store.ProjectYamlParseError as e:
        _log.warning("_start_self_driving_review: %s", e)
        return False
    pr = store.get_pr(data, pr_id)
    if not pr:
        _log.warning("_start_self_driving_review: PR %s not found", pr_id)
        return

    _log.info("Self-driving review for %s", pr_id)
    review_loop_ui._start_loop(
        app, pr_id, pr,
        transcript_dir=str(_auto_start.get_transcript_dir(app)),
    )


def _trigger_signoff(app, pr_id: str) -> bool | None:
    """Hand a QA-passed PR to the sign-off step (auto-start only).

    Never merges: the sign-off driver (``signoff_ui``) routes the router's
    verdict, and only a fresh SIGNOFF_MERGE reaches ``_maybe_auto_merge``.
    ``start_signoff`` re-checks auto-start status and scope.
    """
    from pm_core.tui import signoff_ui
    return signoff_ui.start_signoff(app, pr_id)


def _transition_pr_status(app, pr_id: str, from_status: str, to_status: str) -> bool:
    """Transition PR status if it's currently in the expected state.

    False when project.yaml could not be loaded or locked (worth a retry).
    """
    if not app._root:
        return True
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
        return False
    except Exception:
        _log.exception("Failed to transition PR status for %s", pr_id)
    return True


def _record_qa_note(app, state: QALoopState) -> bool:
    """Record QA results as a note on the PR.

    False when project.yaml could not be loaded or locked (worth a retry).
    """
    if not app._root:
        _log.warning("Cannot record QA note: no project root")
        return True
    try:
        from datetime import datetime, timezone
        note_text = f"QA {state.latest_verdict}: " + qa_outcome_detail(state)
        # Tell the next review session why QA bounced an all-PASS run.
        note_text += planner_code_changes_suffix(state)
        if state.qa_workdir:
            note_text += f" (workdir: {state.qa_workdir})"

        def apply(data):
            pr = store.get_pr(data, state.pr_id)
            if not pr:
                _log.warning("Cannot record QA note: PR %s not found", state.pr_id)
                return
            notes = pr.get("notes") or []
            run_tail = f" (workdir: {state.qa_workdir})"
            if state.qa_workdir and any(
                    (n.get("text") or "").startswith(
                        f"QA {state.latest_verdict}: ")
                    and (n.get("text") or "").endswith(run_tail)
                    for n in notes):
                # This run's note is already there (its workdir names the
                # run): a TUI restart re-processed a completion whose
                # snapshot was kept for a pending follow-up.  The summary
                # is rebuilt from the snapshot, so match the run, not it.
                _log.info("QA note for %s already recorded", state.pr_id)
                return
            existing_ids = {n["id"] for n in notes}
            note_id = store.generate_note_id(state.pr_id, note_text, existing_ids)
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            notes.append({"id": note_id, "text": note_text,
                           "created_at": now, "last_edited": now})
            pr["notes"] = notes

        store.locked_update(app._root, apply)
    except (store.StoreLockTimeout, store.ProjectYamlParseError) as e:
        _log.warning("_record_qa_note: %s for %s: %s", type(e).__name__, state.pr_id, e)
        return False
    except Exception:
        _log.exception("Failed to record QA note for %s", state.pr_id)
    return True
