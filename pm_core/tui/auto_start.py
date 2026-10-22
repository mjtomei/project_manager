"""Auto-start mode: automatically drive an explicit set of target PRs.

Auto-start is owned by the TUI's session scheduler.  It holds an explicit,
insertion-ordered collection of *targets* (``app._auto_start_targets``).
After each sync cycle / loop callback, ``check_and_start`` launches the
ready PRs in the **union** of the targets' dependency closures (shared
dependencies once), starts review/QA loops for in-scope PRs, and removes
targets that have merged/closed — without touching the other targets.

Adding a target is additive and idempotent; an empty collection means
auto-start is OFF (never "all pending PRs").  The whole-backlog mode is a
separate explicit switch (``autostart all``, ``app._auto_start_all``).

Merge holds: ``app._stop_before_merge`` holds explicit per-PR stop marks;
a ``wait_for_merge`` target (record flag) additionally holds itself and its
whole dependency closure for a manual merge.  Every merge decision and the
status resolve the effective hold through :func:`merge_hold` /
:func:`policy_for` (``autostart_state.merge_holds``) — absent means
auto-merge.

Spec review: a target added with ``review_specs`` (``--review-specs``)
pauses itself and its closure for human approval of the implementation
spec and of the QA spec (:func:`spec_review_required`,
:func:`sync_spec_reviews`).  The pause is the PR's ``spec_pending`` record
— the same one ``pm pr spec-approve`` / ``V`` clear.

Controls: ``O`` (add selected, stop-before-merge), ``A`` (toggle selected as
an auto-merge target), the command bar ``autostart …`` verbs, and the CLI
``pm autostart add/remove/clear/list/status`` which reaches this module via
the session command queue (``--reply`` writes a JSON reply file).  State is
in-memory but preserved across the merge-restart breadcrumb.
"""

import json
import os
import re
import secrets
import sys
import time
from pathlib import Path

from pm_core.paths import configure_logger, pm_home
from pm_core import store, graph
from pm_core import autostart_state
from pm_core.autostart_state import (
    NO_REVIEW_FLAG, POLICY_AUTO, POLICY_STOP, POLICY_WAIT, REPLY_DIR,
    REVIEW_FLAG, REVIEW_KEY, WAIT_KEY,
)
from pm_core.tui._shell import _run_shell_async

_log = configure_logger("pm.tui.auto_start")

_MERGE_RESTART_MARKER = "merge-restart"
_BREADCRUMB_FILE = "autostart-resume.json"
_REPLY_MAX_AGE = 600  # seconds
# How long a "targets +=" / "ON (all …)" confirmation holds the log line
# against the scheduler messages it triggers, so it stays readable.
CONFIRM_HOLD_SECONDS = 3.0


def is_enabled(app) -> bool:
    """Check if auto-start mode is active."""
    return bool(getattr(app, "_auto_start", False))


def _targets(app) -> dict:
    """The live target map (``{pr_id: record}``), defensively typed."""
    t = getattr(app, "_auto_start_targets", None)
    return t if isinstance(t, dict) else {}


def get_targets(app) -> list[str]:
    """Ordered list of auto-start target PR ids."""
    return list(_targets(app))


def is_all_mode(app) -> bool:
    """True only in the explicit whole-backlog mode (``autostart all``)."""
    return getattr(app, "_auto_start_all", False) is True


def managed_ids(app, prs: list[dict] | None = None) -> set[str] | None:
    """PR ids auto-start may act on: the union of target closures.

    Returns None only in explicit all-mode (everything), and an empty set
    when auto-start is off or has no targets.
    """
    if not is_enabled(app):
        return set()
    if is_all_mode(app):
        return None
    if prs is None:
        prs = (app._data or {}).get("prs") or []
    return autostart_state.managed_ids(prs, get_targets(app))


def in_scope(app, pr_id: str, prs: list[dict] | None = None) -> bool:
    """Whether auto-start should drive *pr_id* right now."""
    m = managed_ids(app, prs)
    return m is None or pr_id in m


def _stop_set(app) -> set:
    sbm = getattr(app, "_stop_before_merge", None)
    return sbm if isinstance(sbm, set) else set()


def merge_holds(app, prs: list[dict] | None = None) -> dict[str, dict]:
    """``{pr_id: {explicit, targets}}`` for every PR held for a manual merge.

    Explicit per-PR marks always count; ``wait_for_merge`` targets hold
    their closures only while auto-start is enabled (they are active).
    """
    if prs is None:
        prs = (app._data or {}).get("prs") or []
    targets = _targets(app) if is_enabled(app) else {}
    return autostart_state.merge_holds(prs, targets, _stop_set(app))


def merge_hold(app, pr_id: str, prs: list[dict] | None = None) -> dict | None:
    """Why *pr_id* must not auto-merge (None = auto-merge allowed)."""
    return merge_holds(app, prs).get(pr_id)


def policy_for(app, pr_id: str, prs: list[dict] | None = None) -> str:
    """The *effective* merge policy applied to *pr_id* (the one path used
    by the merge decision, the sign-off driver and status)."""
    return autostart_state.effective_policy(pr_id, merge_holds(app, prs))


def target_policy(app, pr_id: str) -> str:
    """A target's own configured policy (``wait_for_merge`` /
    ``stop_before_merge`` / ``auto_merge``)."""
    return autostart_state.target_policy(
        pr_id, _targets(app).get(pr_id), _stop_set(app))


_UNSET = object()


def spec_review_checker(app, prs: list[dict] | None = None,
                        managed=_UNSET):
    """A ``pr_id -> bool`` predicate for :func:`spec_review_required`.

    The scope and the review closures are computed once, so a pass over
    many PRs (scheduler, poll tick) doesn't recompute them per PR.
    *managed* is a :func:`managed_ids` result the caller already has.
    """
    if not is_enabled(app):
        return lambda pr_id: False
    if prs is None:
        prs = (app._data or {}).get("prs") or []
    if managed is _UNSET:
        managed = managed_ids(app, prs)
    holds = autostart_state.spec_review_holds(prs, _targets(app))
    by_id = {p.get("id"): p for p in prs}
    from pm_core import spec_gen
    global_mode = spec_gen.get_spec_mode()

    def required(pr_id: str) -> bool:
        if managed is not None and pr_id not in managed:
            return False
        if pr_id in holds:
            return True
        pr = by_id.get(pr_id)
        return bool(pr) and spec_gen.pr_spec_mode(
            pr, global_mode=global_mode) == "review"
    return required


def spec_review_required(app, pr_id: str, prs: list[dict] | None = None) -> bool:
    """Whether auto-start must pause *pr_id* for spec approval.

    True for an in-scope PR covered by a ``review_specs`` target, or whose
    own effective spec mode is ``review`` (per-PR ``review_spec`` / global
    ``spec-mode``) — without the gate such an agent, idle while it waits
    for approval, would be taken for finished implementation.
    """
    return spec_review_checker(app, prs)(pr_id)


def _spec_phase_due(app, pr: dict) -> str | None:
    """The spec phase an in-scope PR is about to act on, if its spec is
    already present and still needs approval — else None.

    Completed phases are never revisited: the impl spec only matters while
    the PR is pending/in_progress, the QA spec only until this QA run has
    finished planning (a run past planning, or one whose verdict is
    recorded, is left alone).
    """
    from pm_core import spec_gen
    status = pr.get("status")
    if status in ("pending", "in_progress"):
        phase = "impl"
    elif status == "qa":
        if ((app._data or {}).get("project") or {}).get("skip_qa"):
            return None
        loop = (getattr(app, "_qa_loops", None) or {}).get(pr["id"])
        if loop is not None and (loop.latest_verdict
                                 or not getattr(loop, "planning_phase", True)):
            return None
        if loop is None and recorded_qa_verdict(pr["id"], pr) in QA_HOLD_VERDICTS:
            return None
        phase = "qa"
    else:
        return None
    return phase if spec_gen.needs_spec_approval(pr, phase) else None


def hold_spec_if_due(app, pr: dict, prs: list[dict] | None = None,
                     required: bool | None = None) -> bool:
    """Mark *pr*'s present-but-unapproved spec pending when auto-start's
    spec review applies (*required*: a precomputed
    :func:`spec_review_required`), or when its implementation agent was
    launched to wait for pm approval (``spec_gen.IMPL_GATE_KEY``) — that
    agent waits even after the option stops applying.  Returns True when
    it set ``spec_pending``."""
    if not app._root or pr.get("spec_pending"):
        return False
    from pm_core import spec_gen
    if not (pr.get("status") == "in_progress"
            and pr.get(spec_gen.IMPL_GATE_KEY)):
        if required is None:
            required = spec_review_required(app, pr["id"], prs)
        if not required:
            return False
    phase = _spec_phase_due(app, pr)
    if not phase:
        return False
    try:
        marked = spec_gen.mark_spec_pending(app._root, pr["id"], phase, pr=pr)
    except (store.StoreLockTimeout, store.ProjectYamlParseError) as e:
        _log.warning("auto_start: could not hold %s spec of %s: %s",
                     phase, pr["id"], e)
        return False
    if marked:
        label = autostart_state.SPEC_PHASE_LABELS.get(phase, phase)
        _log.info("auto_start: %s spec of %s held for review", phase, pr["id"])
        app.log_message(f"Auto-start: {pr['id']} {label} spec awaiting "
                        f"approval (V / pm pr spec-approve {pr['id']})",
                        force=True)
        app._update_display()
    return marked


def sync_spec_reviews(app, prs: list[dict] | None = None) -> None:
    """Hold every in-scope PR whose next spec step needs approval."""
    if not is_enabled(app) or not app._root:
        return
    if prs is None:
        prs = (app._data or {}).get("prs") or []
    required = spec_review_checker(app, prs)
    for pr in prs:
        if pr.get("id") and pr.get("status") in ("pending", "in_progress", "qa"):
            hold_spec_if_due(app, pr, prs, required=required(pr["id"]))


def _launching(app) -> set:
    s = getattr(app, "_auto_start_launching", None)
    if not isinstance(s, set):
        s = set()
        app._auto_start_launching = s
    return s


def get_transcript_dir(app) -> Path:
    """Return the transcript directory for the current TUI session.

    Total function: callers always receive a usable directory.  Priority:

    1. The active auto-start run dir (``app._auto_start_run_id``) when
       auto-start is active.
    2. A lazily-created ``manual-<token>`` run dir cached on the app as
       ``_manual_transcript_run_id``.  Used for manually-started review
       loops (``zz d``) that never go through auto-start.

    The returned path is always under ``app._root / "transcripts"``.
    The directory itself is created by callers on demand when they
    write files into it.
    """
    run_id = app._auto_start_run_id
    if not run_id:
        run_id = getattr(app, "_manual_transcript_run_id", None)
        if not run_id:
            run_id = f"manual-{secrets.token_hex(3)}"
            app._manual_transcript_run_id = run_id
    root = app._root or pm_home()
    return root / "transcripts" / run_id


def has_merge_restart_marker() -> bool:
    """Check if the merge-restart marker file exists."""
    return (pm_home() / _MERGE_RESTART_MARKER).exists()


def save_breadcrumb(app) -> None:
    """Save state to a breadcrumb file for resumption after restart.

    Called from action_restart when a merge-restart marker is present.
    Always deletes the marker.  Persists auto-start state (if active),
    running review loops, and watcher state.  Writes a breadcrumb whenever
    there is *anything* worth preserving — even a manually-started review
    loop without auto-start.
    """
    marker = pm_home() / _MERGE_RESTART_MARKER
    marker.unlink(missing_ok=True)

    data: dict = {}

    # Persist auto-start state if active: the full target collection
    # (records, in order), explicit all-mode, and the shared run id.
    # A target's wait-for-merge flag rides on its record; explicit stop
    # marks ride on ``stop_before_merge`` below.
    if is_enabled(app):
        data["auto_start"] = True
        data["targets"] = autostart_state.targets_to_breadcrumb(_targets(app))
        data["all_mode"] = is_all_mode(app)
        data["run_id"] = app._auto_start_run_id

    # Persist auto-sequence stop-before-merge set even when auto-start is
    # off — a TUI restart between QA finish and merge shouldn't re-arm
    # auto-merge for an auto-sequence PR.
    stop_before_merge = getattr(app, "_stop_before_merge", None)
    if isinstance(stop_before_merge, set) and stop_before_merge:
        data["stop_before_merge"] = sorted(stop_before_merge)

    # Persist review loop state for running loops
    review_loops = {}
    for pr_id, rstate in app._review_loops.items():
        if not rstate.running:
            continue
        review_loops[pr_id] = {
            "iteration": rstate.iteration,
            "latest_verdict": rstate.latest_verdict,
            "loop_id": rstate.loop_id,
            "input_required": rstate.input_required,
            "_transcript_dir": rstate._transcript_dir,
            "history": [
                {
                    "iteration": h.iteration,
                    "verdict": h.verdict,
                    "timestamp": h.timestamp,
                }
                for h in rstate.history
            ],
        }
    if review_loops:
        data["review_loops"] = review_loops

    # Persist watcher state
    manager = app._watcher_manager
    if manager.is_any_running():
        watchers_data = []
        for info in manager.list_watchers():
            if info["running"]:
                watcher = manager.get_watcher(info["id"])
                if not watcher:
                    continue
                entry = {"type": info["type"]}
                if hasattr(watcher, 'meta_pm_root'):
                    entry["meta_pm_root"] = watcher.meta_pm_root
                if hasattr(watcher, 'auto_start_targets'):
                    entry["auto_start_targets"] = list(watcher.auto_start_targets)
                watchers_data.append(entry)
        if watchers_data:
            data["watchers"] = watchers_data

    if not data:
        _log.debug("save_breadcrumb: nothing to persist, skipping")
        return

    breadcrumb = pm_home() / _BREADCRUMB_FILE
    breadcrumb.write_text(json.dumps(data))
    _log.info("save_breadcrumb: wrote %s", data)


async def consume_breadcrumb(app) -> None:
    """Restore auto-start state from a breadcrumb file on startup.

    If the breadcrumb exists, reads it, deletes it (always, even on error),
    restores auto-start fields, and calls check_and_start.
    """
    breadcrumb = pm_home() / _BREADCRUMB_FILE
    if not breadcrumb.exists():
        return

    try:
        data = json.loads(breadcrumb.read_text())
    except Exception as e:
        _log.warning("consume_breadcrumb: failed to read breadcrumb: %s", e)
        return
    finally:
        breadcrumb.unlink(missing_ok=True)

    # Restore auto-start state only if it was active before the restart.
    # Current breadcrumbs carry ``targets`` + ``all_mode``; a legacy
    # single-target breadcrumb (``target: X``) migrates to ``[X]`` and a
    # legacy targetless one to the explicit all-mode it represented.
    targets, all_mode, migrated = autostart_state.targets_from_breadcrumb(data)
    had_auto_start = bool(targets) or all_mode
    run_id = data.get("run_id")
    _log.info("consume_breadcrumb: restoring targets=%s all_mode=%s run_id=%s "
              "migrated_legacy=%s", list(targets), all_mode, run_id, migrated)

    if had_auto_start:
        app._auto_start = True
        app._auto_start_targets = dict(targets)
        app._auto_start_all = all_mode
        app._auto_start_run_id = run_id

        # Recreate transcript directory if needed
        if run_id and app._root:
            tdir = app._root / "transcripts" / run_id
            tdir.mkdir(parents=True, exist_ok=True)
        elif not run_id:
            _ensure_run(app)

    # Restore auto-sequence stop-before-merge set
    sbm = data.get("stop_before_merge")
    if sbm:
        app._stop_before_merge.update(sbm)
        _log.info("consume_breadcrumb: restored stop_before_merge=%s", sbm)

    # Restore review loop state before check_and_start so it sees existing loops
    review_loops_data = data.get("review_loops", {})
    if review_loops_data:
        from pm_core.review_loop import ReviewLoopState, ReviewIteration
        for pr_id, loop_data in review_loops_data.items():
            rstate = ReviewLoopState(
                pr_id=pr_id,
                iteration=loop_data.get("iteration", 0),
                latest_verdict=loop_data.get("latest_verdict", ""),
                loop_id=loop_data.get("loop_id", secrets.token_hex(2)),
                input_required=loop_data.get("input_required", False),
                _transcript_dir=loop_data.get("_transcript_dir"),
            )
            for h in loop_data.get("history", []):
                rstate.history.append(ReviewIteration(
                    iteration=h["iteration"],
                    verdict=h["verdict"],
                    output="",  # not stored in breadcrumb
                    timestamp=h.get("timestamp", ""),
                ))
            app._review_loops[pr_id] = rstate
        _log.info("consume_breadcrumb: restored %d review loop state(s)", len(review_loops_data))

    app._update_display()

    if had_auto_start:
        # Adopt in-flight QA runs (qa_resume.json) into app._qa_loops before
        # the scheduler pass — otherwise _auto_start_qa_loops would see no
        # loop and launch a duplicate before the poll-timer resume scan.
        _adopt_live_qa(app)
        await check_and_start(app)

    # Restart review loops that were running before the restart
    if review_loops_data:
        from pm_core.tui.review_loop_ui import _start_loop
        for pr_id in review_loops_data:
            rstate = app._review_loops.get(pr_id)
            if rstate and not rstate.running:
                pr = store.get_pr(app._data, pr_id)
                if pr and pr.get("status") == "in_review":
                    # Keep the loop's own dir: an in-flight iteration's
                    # transcript lives there, and a manual loop would
                    # otherwise get a fresh ``manual-<hex>`` dir, so an
                    # adopted INPUT_REQUIRED follow-up (and finalize)
                    # would look in the wrong place.
                    tdir = rstate._transcript_dir or get_transcript_dir(app)
                    _start_loop(
                        app, pr_id, pr,
                        transcript_dir=str(tdir),
                        resume_state=rstate,
                    )
                    msg = (f"Review loop resumed for {pr_id} "
                           f"at iteration {rstate.iteration}")
                    _log.info("consume_breadcrumb: %s", msg)
                    app.log_message(msg)

    # Resume watchers (list format, or legacy single-watcher dict)
    watchers_data = data.get("watchers", [])
    watcher_data = data.get("watcher")  # legacy single-watcher breadcrumb
    if not watchers_data and watcher_data:
        watchers_data = [{"type": "auto-start", "meta_pm_root": watcher_data.get("meta_pm_root")}]
    if watchers_data:
        from pm_core.tui import watcher_ui
        tdir = get_transcript_dir(app)
        for wd in watchers_data:
            watcher_ui.start_watcher(
                app,
                transcript_dir=str(tdir),
                meta_pm_root=wd.get("meta_pm_root"),
                watcher_type=wd.get("type", "auto-start"),
            )
        _log.info("consume_breadcrumb: resumed %d watcher(s)", len(watchers_data))

    # Summarise last: the per-loop resume messages above (one of them
    # sticky) would otherwise overwrite this before it is ever painted.
    if had_auto_start:
        desc = "all" if all_mode else ", ".join(targets)
        note = " (migrated legacy breadcrumb)" if migrated else ""
        msg = f"Auto-start: resumed after merge restart → {desc}{note}"
        _log.info("consume_breadcrumb: %s", msg)
        app.log_message(msg, sticky=5)
    elif review_loops_data:
        app.log_message("Resumed review loop state after restart", sticky=5)


def _adopt_live_qa(app) -> None:
    """Adopt resumable QA runs into ``app._qa_loops`` (restart path)."""
    try:
        from pm_core.tui import qa_loop_ui
        qa_loop_ui._resume_incomplete_qa(app)
    except Exception:
        _log.warning("auto_start: QA adoption scan failed", exc_info=True)


def _finalize_all_transcripts(app) -> None:
    """Finalize all transcript symlinks in the current run directory."""
    tdir = get_transcript_dir(app)
    if not tdir or not tdir.is_dir():
        return
    from pm_core.claude_launcher import finalize_transcript
    for p in tdir.iterdir():
        if p.is_symlink() and p.suffix == ".jsonl":
            finalize_transcript(p)


def _disable(app) -> None:
    """Disable auto-start mode (in-memory only) and drop all targets."""
    _finalize_all_transcripts(app)
    # Stop the watcher loop if it's running
    from pm_core.tui import watcher_ui
    if watcher_ui.is_running(app):
        watcher_ui.stop_watcher(app)
    app._auto_start = False
    app._auto_start_targets = {}
    app._auto_start_all = False
    app._auto_start_run_id = None
    app._update_display()


def _ensure_run(app) -> None:
    """Create the shared transcript run dir on first enablement."""
    if app._auto_start_run_id:
        return
    targets = get_targets(app)
    tag = "all" if is_all_mode(app) else (targets[0] if targets else "all")
    run_id = f"autostart-{tag}-{secrets.token_hex(4)}"
    app._auto_start_run_id = run_id
    if app._root:
        tdir = app._root / "transcripts" / run_id
        tdir.mkdir(parents=True, exist_ok=True)
        _log.info("auto_start: created transcript dir %s", tdir)


def _sync_enabled(app) -> None:
    """Recompute the derived ``_auto_start`` flag after a target mutation.

    Enabled iff there is at least one target or explicit all-mode.  Going
    from enabled → empty disables auto-start; it never falls back to
    all-mode.  Also keeps a running auto-start watcher's scope current.
    """
    enabled = bool(_targets(app)) or is_all_mode(app)
    if enabled:
        app._auto_start = True
        _ensure_run(app)
        try:
            w = app._watcher_manager.find_by_type("auto-start")
            if w is not None and hasattr(w, "auto_start_targets"):
                w.auto_start_targets = get_targets(app)
        except Exception:
            _log.debug("auto_start: watcher scope update failed", exc_info=True)
        app._update_display()
    elif is_enabled(app):
        _disable(app)
    else:
        app._update_display()


def _resolve_ids(app, ids: list[str]) -> tuple[list[dict], list[str]]:
    """Resolve ids (``pr-x``, ``#N``, ``N``) against app data, reloading once.

    Returns ``(resolved_prs, unknown_ids)``.
    """
    from pm_core.cli.helpers import _resolve_pr_id

    def attempt(data):
        found, missing = [], []
        for raw in ids:
            pr = _resolve_pr_id(data or {}, raw)
            (found.append(pr) if pr else missing.append(raw))
        return found, missing

    found, missing = attempt(app._data)
    if missing and app._root:
        # Flush pending in-memory writes first so the reload can't clobber
        # un-flushed mutations (same rule as ``TechTreeApp._load_state``).
        wq = getattr(app, "_write_queue", None)
        if wq is not None:
            wq.flush_sync()
        try:
            app._data = store.load(app._root)
        except Exception:
            pass
        else:
            found, missing = attempt(app._data)
    return found, missing


def add_targets(app, ids: list[str], policy: str | None = None,
                default_policy: str | None = POLICY_STOP,
                source: str = "command", confirm: str | None = None,
                review_specs: bool | None = None) -> dict:
    """Add targets (additive, idempotent, all-or-nothing validation).

    *policy*: ``stop_before_merge`` / ``auto_merge`` / ``wait_for_merge``
    to set explicitly, or None to keep an existing target's policy; a *new*
    target then gets *default_policy* (None = leave the stop set untouched,
    i.e. the ``A``-key semantics).  Setting a policy replaces that target's
    own previous one (its stop mark / wait flag); marks on other PRs are
    never touched.  The policy is in place before the scheduler pass this
    queues, so a wait target's dependencies are held before any starts.
    Never touches other targets and never enables all-mode.

    *review_specs*: True/False sets/clears the target's spec-review
    option (``--review-specs`` / ``--no-review-specs``); None keeps it
    (new targets: off).  Clearing it never approves a spec that is
    already pending.

    *confirm* replaces the "targets +=" log-line confirmation (e.g. the
    ``O`` key's "Auto-sequence armed …"); it gets the same hold.
    """
    if not ids:
        return {"ok": False, "error": "usage", "message": "no PR ids given",
                "changes": []}
    found, missing = _resolve_ids(app, ids)
    if missing:
        return {"ok": False, "error": "unknown_pr",
                "message": f"unknown PR id(s): {', '.join(missing)}",
                "invalid": missing, "changes": []}
    closed = [p["id"] for p in found
              if p.get("status") in autostart_state.TERMINAL_STATUSES]
    if closed:
        return {"ok": False, "error": "terminal_pr",
                "message": f"already merged/closed: {', '.join(closed)}",
                "invalid": closed, "changes": []}

    if policy is not None and policy not in autostart_state.POLICIES:
        return {"ok": False, "error": "usage",
                "message": f"unknown merge policy {policy!r}", "changes": []}

    targets = _targets(app)
    if not isinstance(getattr(app, "_auto_start_targets", None), dict):
        app._auto_start_targets = targets
    sbm = app._stop_before_merge
    held_before = set(merge_holds(app))
    changes = []
    for pr in found:
        pr_id = pr["id"]
        is_new = pr_id not in targets
        if is_new:
            targets[pr_id] = autostart_state.make_target_record(source)
        previous = target_policy(app, pr_id)
        rec = targets[pr_id]
        prev_review = autostart_state.is_review_target(rec)
        if review_specs is True:
            rec[REVIEW_KEY] = True
        elif review_specs is False:
            rec.pop(REVIEW_KEY, None)
        cur_review = autostart_state.is_review_target(rec)
        effective = policy or (default_policy if is_new else None)
        if effective == POLICY_WAIT:
            rec[WAIT_KEY] = True
            sbm.discard(pr_id)
        elif effective == POLICY_STOP:
            rec.pop(WAIT_KEY, None)
            sbm.add(pr_id)
        elif effective == POLICY_AUTO:
            rec.pop(WAIT_KEY, None)
            sbm.discard(pr_id)
        current = target_policy(app, pr_id)
        if is_new:
            action = "added"
        elif current != previous:
            # Re-add with a flag that flips the policy: report the change
            # rather than "unchanged" (which reads as a refusal).
            action = "policy_changed"
        elif cur_review != prev_review:
            action = "options_changed"
        else:
            action = "unchanged"
        change = {"pr_id": pr_id, "action": action, "policy": current}
        if action == "policy_changed":
            change["previous_policy"] = previous
        # Only reported when in use, so default changes keep their shape.
        if cur_review or cur_review != prev_review:
            change["review_specs"] = cur_review
        if not is_new and cur_review != prev_review:
            change["previous_review_specs"] = prev_review
        changes.append(change)
        _log.info("auto_start: target %s %s policy=%s review_specs=%s "
                  "source=%s", pr_id, "added" if is_new else "re-armed",
                  current, cur_review, source)
    _sync_enabled(app)
    released = sorted(held_before - set(merge_holds(app)))
    if released:
        _log.info("auto_start: released merge holds on %s", released)
    refresh_qa_spec_review(app)

    def _label(c: dict) -> str:
        rv = ["review-specs"] if c.get("review_specs") else []
        if c["action"] == "policy_changed":
            now = [c["policy"].replace("_", "-")] + rv
            return f"{c['pr_id']} (now {', '.join(now)})"
        if c["action"] == "options_changed":
            return f"{c['pr_id']} (now {', '.join(rv) or 'no review-specs'})"
        opts = {POLICY_STOP: ["stop"],
                POLICY_WAIT: ["wait-for-merge + deps"]}.get(c["policy"], [])
        opts = opts + rv
        pol = f" ({', '.join(opts)})" if opts else ""
        already = " (already a target)" if c["action"] == "unchanged" else ""
        return f"{c['pr_id']}{pol}{already}"
    summary = ", ".join(_label(c) for c in changes)
    # hold: check_and_start's "starting <pr>" / review-loop messages land
    # in the same frame and would overwrite this before it ever paints.
    if confirm is None:
        confirm = f"Auto-start: targets += {summary} ({len(targets)} total)"
    if released:
        confirm += f"; released merge hold on {', '.join(released)}"
    app.log_message(confirm, force=True, hold=CONFIRM_HOLD_SECONDS)
    app.run_worker(check_and_start(app))
    result = {"ok": True, "changes": changes}
    if released:
        result["released"] = released
    return result


def remove_targets(app, ids: list[str]) -> dict:
    """Remove targets.  Never kills windows/loops; keeps stop marks.

    Unknown ids reject the whole command; a valid PR that isn't a target
    is reported as ``not_target``.  PRs still needed by another target
    stay in scope (scope is the union of the remaining closures).  A
    removed ``wait_for_merge`` target releases only the holds it caused:
    explicit marks and holds from other wait targets remain (``released``
    in the result lists PRs no longer held).
    """
    if not ids:
        return {"ok": False, "error": "usage", "message": "no PR ids given",
                "changes": []}
    found, missing = _resolve_ids(app, ids)
    if missing:
        return {"ok": False, "error": "unknown_pr",
                "message": f"unknown PR id(s): {', '.join(missing)}",
                "invalid": missing, "changes": []}
    targets = _targets(app)
    held_before = set(merge_holds(app))
    changes = []
    for pr in found:
        pr_id = pr["id"]
        if pr_id in targets:
            targets.pop(pr_id)
            changes.append({"pr_id": pr_id, "action": "removed"})
        else:
            changes.append({"pr_id": pr_id, "action": "not_target"})
    removed = [c["pr_id"] for c in changes if c["action"] == "removed"]
    _log.info("auto_start: remove %s → removed=%s remaining=%s",
              ids, removed, list(targets))
    _sync_enabled(app)
    released = sorted(held_before - set(merge_holds(app)))
    refresh_qa_spec_review(app)
    # hold: a racing ``g`` merge's spinner frames would overwrite this
    # within 0.1s (QA s18), like "targets +=" above.
    if removed:
        rest = f"{len(targets)} remaining" if targets else "auto-start OFF"
        rel = (f"; released merge hold on {', '.join(released)}"
               if released else "")
        app.log_message(
            f"Auto-start: removed {', '.join(removed)} ({rest}){rel}",
            force=True, hold=CONFIRM_HOLD_SECONDS)
    else:
        app.log_message(f"Auto-start: {', '.join(ids)} not a target",
                        force=True, hold=CONFIRM_HOLD_SECONDS)
    result = {"ok": True, "changes": changes}
    if released:
        result["released"] = released
    return result


def clear_targets(app) -> dict:
    """Remove every target and leave all-mode → auto-start OFF."""
    removed = get_targets(app)
    was = is_enabled(app)
    if was:
        _disable(app)
    else:
        app._auto_start_targets = {}
        app._auto_start_all = False
    app.log_message("Auto-start: OFF" if was else "Auto-start: already off",
                    force=True, hold=CONFIRM_HOLD_SECONDS)
    _log.info("auto_start: cleared targets=%s", removed)
    return {"ok": True,
            "changes": [{"pr_id": r, "action": "removed"} for r in removed]}


def enable_all(app) -> dict:
    """Explicit whole-backlog mode (the legacy targetless auto-start)."""
    app._auto_start_all = True
    _sync_enabled(app)
    app.log_message("Auto-start: ON (all ready PRs — explicit backlog mode)",
                    force=True, hold=CONFIRM_HOLD_SECONDS)
    _log.info("auto_start: all-mode enabled")
    app.run_worker(check_and_start(app))
    return {"ok": True, "changes": [{"pr_id": None, "action": "all_mode"}]}


async def toggle(app, selected_pr_id: str | None = None) -> None:
    """``A`` key: toggle the selected PR as an auto-merge target.

    - Selected PR not a target → add it (additive; other targets kept).
      New targets get no stop-before-merge mark (explicit ``A`` keeps the
      existing auto-merge semantics); an existing stop mark is kept.
    - Selected PR already a target → remove it (others keep running).
    - No PR selected → turn auto-start off if on, else "No PR selected"
      (no implicit whole-backlog mode — use ``autostart all``).
    """
    if not selected_pr_id:
        if is_enabled(app):
            clear_targets(app)
        else:
            app.log_message("No PR selected (use 'autostart all' for the "
                            "whole backlog)", force=True)
        return
    if selected_pr_id in _targets(app):
        remove_targets(app, [selected_pr_id])
        return
    result = add_targets(app, [selected_pr_id], policy=None,
                         default_policy=None, source="key:A")
    if not result["ok"]:
        app.log_message(f"Auto-start: {result['message']}")


async def auto_sequence_for_pr(app, pr_id: str) -> None:
    """``O`` key: add *pr_id* as a stop-before-merge target and nudge.

    Additive: other targets (and their policies) are untouched.  Repeating
    ``O`` on the same PR re-arms the stop mark and re-runs the scheduler.
    """
    # The armed line is the held confirmation itself: logged separately
    # after "targets +=" (forced, unheld) it only lasted as long as some
    # earlier hold, so a second O inside the first O's hold had it
    # replaced by its own deferred "starting <pr>" ~0.1s later.
    result = add_targets(
        app, [pr_id], policy=POLICY_STOP, source="key:O",
        confirm=f"Auto-sequence armed for {pr_id} (will stop before merge)")
    if not result["ok"]:
        app.log_message(f"Auto-sequence: {result['message']}")


def refresh_qa_spec_review(app) -> None:
    """Push the current spec-review requirement into the running QA loops
    (read by the QA thread's scenario-launch gate).  Called on target
    changes and every QA poll tick (restart, spec-mode changes).  Finished
    loops linger for their verdicts; skipping them keeps an idle tick from
    recomputing the closures."""
    loops = [(pr_id, state) for pr_id, state
             in list((getattr(app, "_qa_loops", None) or {}).items())
             if getattr(state, "running", False)]
    if not loops:
        return
    required = spec_review_checker(app)
    for pr_id, state in loops:
        if hasattr(state, "spec_review"):
            state.spec_review = required(pr_id)


def on_state_loaded(app, old_statuses: dict,
                    old_deps: dict | None = None,
                    old_spec: dict | None = None) -> None:
    """Kick a scheduler pass when a reload shows an in-scope PR newly
    merged/closed (manual ``g``, CLI merge, another session), or an
    in-scope PR's ``depends_on`` changed (``pm pr edit --depends-on``).

    The auto-merge path and sync already call ``check_and_start``; a merge
    seen only through a state reload would otherwise leave a completed
    target in the set and its dependents unstarted until some other event.
    Likewise a graph edit that pulls a ready prerequisite into a target's
    closure would leave it "ready; starts on next scheduler pass" forever.
    And a spec approval (``pm pr spec-approve`` / ``V`` clears
    ``spec_pending``; *old_spec* maps pr id → its pending phase) must
    start the PR or QA run that was waiting on it.
    """
    if not old_statuses or not is_enabled(app):
        return
    prs = (app._data or {}).get("prs") or []
    terminal = autostart_state.TERMINAL_STATUSES
    newly = [p["id"] for p in prs
             if p.get("id") in old_statuses
             and p.get("status") in terminal
             and old_statuses.get(p["id"]) not in terminal]
    regraphed = [] if old_deps is None else [
        p["id"] for p in prs
        if p.get("id") in old_deps
        and list(p.get("depends_on") or []) != old_deps[p["id"]]]
    # spec_pending is cleared by an approval or by a regeneration that
    # needs no review (``pm pr spec --regenerate`` / reject in prompt
    # mode); only the former records spec_approved for the pending phase.
    cleared = [] if old_spec is None else [
        p for p in prs
        if old_spec.get(p.get("id")) and not p.get("spec_pending")]
    approved = [p["id"] for p in cleared
                if _approved_since(p, old_spec[p["id"]])]
    regenerated = [p["id"] for p in cleared if p["id"] not in approved]
    if not newly and not regraphed and not cleared:
        return
    managed = managed_ids(app, prs)
    if managed is not None and not any(
            i in managed for i in newly + regraphed + approved + regenerated):
        return
    _log.info("auto_start: reload saw %s merged/closed, %s deps changed, "
              "%s spec approved, %s spec regenerated, scheduling pass",
              newly, regraphed, approved, regenerated)
    # Replace the forced "spec awaiting approval" line: a PR approved
    # mid-implementation just resumes in its pane, so no "starting" line
    # would follow to supersede it.  A regenerated spec was not approved;
    # the pass re-holds it if review still applies.
    shown = [i for i in approved if managed is None or i in managed]
    if shown:
        app.log_message(f"Auto-start: {', '.join(shown)} spec approved — "
                        f"continuing", force=True)
    shown = [i for i in regenerated if managed is None or i in managed]
    if shown:
        app.log_message(f"Auto-start: {', '.join(shown)} spec regenerated — "
                        f"not approved", force=True)
    app.run_worker(check_and_start(app))


def _approved_since(pr: dict, old_pending) -> bool:
    """Whether *pr*'s cleared spec_pending was cleared by an approval.

    *old_pending* is the pending phase before the reload (``True`` when
    only its presence is known).  A phaseless record can't have been
    approved (``approve_spec`` ignores it), and an older approval of
    another phase must not read as this one's.
    """
    from pm_core import spec_gen
    return (isinstance(old_pending, str)
            and spec_gen.is_spec_approved(pr, old_pending))


def _prune_completed_targets(app, prs: list[dict]) -> None:
    """Remove targets whose PR merged/closed/vanished; leave the rest."""
    targets = _targets(app)
    # No PR data at all means "not loaded", not "every target vanished".
    if not targets or not prs:
        return
    pr_map = {p.get("id"): p for p in prs}
    done = []
    for t in list(targets):
        pr = pr_map.get(t)
        status = (pr or {}).get("status")
        if pr is None or status in autostart_state.TERMINAL_STATUSES:
            targets.pop(t, None)
            done.append((t, status or "missing"))
    if not done:
        return
    for t, status in done:
        _log.info("auto_start: target %s %s, removed (%d remaining)",
                  t, status, len(targets))
    turn_off = not targets and not is_all_mode(app)
    rest = ("all targets complete — auto-start OFF" if turn_off
            else f"{len(targets)} remaining")
    # One line, held: a TUI ``g`` merge prunes here from the reload its own
    # merge triggers, while the "Merging <pr>..." spinner repaints every
    # 0.1s and the merge's result line follows — unheld (or followed by a
    # separate "OFF" line) this never painted.
    app.log_message(
        "Auto-start: " + ", ".join(f"target {t} {s}" for t, s in done)
        + f" — removed ({rest})", force=True, hold=CONFIRM_HOLD_SECONDS)
    if turn_off:
        _disable(app)
    else:
        _sync_enabled(app)  # refresh ◎ markers / AUTO ×N and watcher scope


async def check_and_start(app) -> None:
    """Advance every in-scope PR one scheduler step.

    Scope is the union of the target closures (or everything in explicit
    all-mode).  Launches ready PRs (pending with deps merged, plus
    restartable in_progress PRs — ``pm pr start --background`` no-ops when
    the window exists), each at most once even across concurrent passes
    (``_auto_start_launching``), then starts review/QA loops.  Scope is
    re-checked after every ``await`` so a removal that lands mid-pass takes
    effect.  Completed targets are removed individually.
    """
    if not is_enabled(app):
        return
    if not app._root:
        return

    prs = app._data.get("prs") or []

    _prune_completed_targets(app, prs)
    if not is_enabled(app):
        return

    # Drop merged PRs from stop_before_merge — once merged, the entry
    # has done its job and shouldn't linger across future auto-start runs.
    sbm = getattr(app, "_stop_before_merge", set())
    if sbm:
        merged = {pr["id"] for pr in (app._data.get("prs") or [])
                  if pr.get("status") == "merged"}
        sbm.intersection_update(
            {pr["id"] for pr in (app._data.get("prs") or [])} - merged
        )

    # Hold already-present, unapproved specs before anything starts.
    sync_spec_reviews(app, prs)

    # Collect PRs that should be started: pending with all deps merged,
    # plus in_progress PRs (whose window may have been killed).
    ready = graph.ready_prs(prs)
    merged_ids = {pr["id"] for pr in prs if pr.get("status") == "merged"}
    for pr in prs:
        if pr.get("status") != "in_progress":
            continue
        deps = pr.get("depends_on") or []
        if all(d in merged_ids for d in deps):
            ready.append(pr)

    launching = _launching(app)
    started = False
    seen: set[str] = set()
    for pr in ready:
        pr_id = pr["id"]
        if pr_id in seen:
            continue
        seen.add(pr_id)
        # Re-evaluated every iteration: a CLI remove/add or another
        # callback may have changed the target set during an await.
        if not is_enabled(app) or not in_scope(app, pr_id):
            continue
        if pr_id in launching:
            _log.info("auto_start: %s launch already in flight, skipping", pr_id)
            continue
        if pr.get("spec_pending"):
            # Waiting for approval (pm pr start refuses any pending spec);
            # an in_progress agent waiting on it keeps its window.
            _log.debug("auto_start: %s spec pending, not starting", pr_id)
            continue
        launching.add(pr_id)
        if pr.get("status") == "pending":
            _log.info("auto_start: starting ready PR %s", pr_id)
            # Forced past sticky messages, but not past the "targets +="
            # confirmation's hold: then it's deferred until the hold ends.
            held = time.monotonic() < getattr(app, "_log_hold_until", 0.0)
            app.log_message(f"Auto-start: starting {pr_id}", force=not held)
        else:
            # ``pm pr start --background`` no-ops when the window exists.
            _log.info("auto_start: ensuring impl window for in_progress PR %s",
                      pr_id)
        try:
            # A sign-off IMPL return whose fresh session never launched
            # (e.g. TUI restart right after the hop) must relaunch the agent:
            # the old, idle impl window would otherwise be adopted as is.
            # Read from disk: ``prs`` predates this pass's awaits, and a
            # rework launch that finished meanwhile cleared the mark — a
            # second --fresh would kill that new session.
            if pr.get("status") == "in_progress" \
                    and _awaiting_on_disk(app, pr_id, "impl"):
                # One launcher: a concurrent `pm pr auto-sequence` tick (or
                # our own sign-off hop) may already be relaunching it, and a
                # second --fresh would kill that session.
                from pm_core.signoff import claim_return_launch
                if not claim_return_launch(app._root, pr_id, "impl"):
                    _log.info("auto_start: %s rework launch already "
                              "claimed, skipping", pr_id)
                    _recheck_after_claim(app)
                    continue
                if await _start_pr_quiet(app, pr_id, fresh=True) is False:
                    # Nothing launched (e.g. the impl spec went pending):
                    # the next pass must not wait out our claim.
                    from pm_core.signoff import release_return_launch
                    release_return_launch(app._root, pr_id, "impl")
            else:
                await _start_pr_quiet(app, pr_id)
            started = True
        except Exception as e:
            _log.exception("auto_start: failed to start %s", pr_id)
            app.log_message(f"Auto-start error: {e}")
        finally:
            launching.discard(pr_id)

    if started:
        # Reload state after starting PRs
        app._load_state()
        prs = app._data.get("prs") or []

    if not is_enabled(app):
        return
    # Also start review loops for in_review PRs without active loops
    _auto_start_review_loops(app, prs)

    # Start QA for qa-status PRs without active QA loops
    _auto_start_qa_loops(app, prs)

    # Drive sign-off: QA-passed PRs -> sign_off, sign_off PRs one step
    from pm_core.tui import signoff_ui
    signoff_ui.advance_all(app, prs)


def _auto_start_review_loops(app, prs: list[dict] | None = None) -> None:
    """Start review loops for in-scope in_review PRs without one."""
    if not is_enabled(app):
        return

    if prs is None:
        prs = app._data.get("prs") or []

    for pr in prs:
        if pr.get("status") != "in_review":
            continue
        pr_id = pr["id"]
        if not in_scope(app, pr_id, prs):
            continue
        # Skip if a review loop is already running or completed for this PR
        loop = app._review_loops.get(pr_id)
        if loop:
            continue
        # Skip if no workdir (shouldn't happen for in_review, but guard)
        if not pr.get("workdir"):
            continue
        # A sign-off REVIEW return still waiting for its launch (TUI
        # restart after the hop): the loop's --fresh launch would kill one
        # a concurrent `pm pr auto-sequence` tick is starting, so take the
        # return's launch claim first (as the impl catch-up does).
        if _awaiting_on_disk(app, pr_id, "review"):
            from pm_core.signoff import claim_return_launch
            if not claim_return_launch(app._root, pr_id, "review"):
                _log.info("auto_start: %s review return launch already "
                          "claimed, skipping", pr_id)
                _recheck_after_claim(app)
                continue
        _log.info("auto_start: starting review loop for %s", pr_id)
        app.log_message(f"Auto-start: review loop for {pr_id}")
        from pm_core.tui.review_loop_ui import _start_loop
        tdir = get_transcript_dir(app)
        _start_loop(app, pr_id, pr, transcript_dir=str(tdir))


QA_HOLD_VERDICTS = ("PASS", "INPUT_REQUIRED")


def recorded_qa_verdict(pr_id: str, pr: dict | None = None) -> str | None:
    """Verdict of the PR's last *finished* QA run (runtime_state), or None.

    With *pr*, a run that finished before the PR's open sign-off return is
    ignored: it verified the code sign-off sent back, not the rework (whose
    QA run records nothing until its first scenario launches).
    """
    try:
        from pm_core import runtime_state as _rs
        rec = _rs.get_action_state(pr_id, "qa") or {}
    except Exception:
        return None
    if rec.get("state") != "done":
        return None
    if pr is not None and _predates_open_return(rec.get("updated_at"), pr):
        return None
    return rec.get("verdict") or None


def _predates_open_return(at: str | None, pr: dict) -> bool:
    from pm_core.signoff import open_return, parse_ts
    ts = (open_return(pr) or {}).get("ts")
    if not ts:
        return False
    try:
        return not at or parse_ts(at) < parse_ts(ts)
    except (TypeError, ValueError):
        return False


def _auto_start_qa_loops(app, prs: list[dict] | None = None) -> None:
    """Start QA loops for in-scope qa-status PRs without one running.

    Skipped entirely when the project-level ``skip_qa`` setting is true.
    """
    if not is_enabled(app):
        return

    project = (app._data or {}).get("project") or {}
    if project.get("skip_qa"):
        return

    if prs is None:
        prs = app._data.get("prs") or []

    for pr in prs:
        if pr.get("status") != "qa":
            continue
        pr_id = pr["id"]
        if not in_scope(app, pr_id, prs):
            continue
        # Skip if QA is already running or just completed (awaiting
        # poll_qa_state processing).  Without the latest_verdict check,
        # a sync-triggered check_and_start could race with poll_qa_state
        # and restart QA before the completion handler runs.
        qa_loop = app._qa_loops.get(pr_id)
        if qa_loop and (qa_loop.running or qa_loop.latest_verdict):
            continue
        # A finished run leaves _qa_loops one tick after completion; its
        # verdict is recorded in runtime_state.  PASS is handed to sign-off
        # (signoff_ui.advance_all) and INPUT_REQUIRED waits for a human —
        # re-running QA on every later scheduler pass (or restart) would
        # only duplicate finished work.
        # Any real QA start (review→qa, ``t``) overwrites this record.
        recorded = recorded_qa_verdict(pr_id, pr)
        from pm_core.signoff import return_awaiting
        if recorded in QA_HOLD_VERDICTS and return_awaiting(pr) != "qa":
            _log.debug("auto_start: %s QA already ended %s, not relaunching",
                       pr_id, recorded)
            continue
        # An already-present QA spec awaiting approval: the run (and its
        # scenario launch) waits for approval, which re-runs this pass.
        if autostart_state.pending_spec_phase(pr) == "qa":
            _log.debug("auto_start: %s QA spec pending, not starting QA", pr_id)
            continue
        # Skip if no workdir
        if not pr.get("workdir"):
            continue
        _log.info("auto_start: starting QA loop for %s", pr_id)
        app.log_message(f"Auto-start: QA for {pr_id}")
        from pm_core.tui import qa_loop_ui
        qa_loop_ui.start_qa(app, pr_id)


def _recheck_after_claim(app) -> None:
    """Run one more scheduler pass once a skipped return claim can expire.

    The claim's holder may have died before launching (e.g. a TUI restart
    right after the hop it performed).  The TUI has no periodic auto-start
    pass, so without this a stranded claim would stall the PR until some
    unrelated event; with it the expired claim is taken over.  One pending
    re-check covers every PR.
    """
    set_timer = getattr(app, "set_timer", None)
    if set_timer is None or getattr(app, "_return_claim_recheck", False):
        return
    from pm_core.signoff import RETURN_LAUNCH_CLAIM_SECONDS

    def _fire():
        app._return_claim_recheck = False
        app.run_worker(check_and_start(app))

    app._return_claim_recheck = True
    set_timer(RETURN_LAUNCH_CLAIM_SECONDS + 5, _fire)


def _awaiting_on_disk(app, pr_id: str, hop: str) -> bool:
    """Whether the PR's sign-off return to *hop* still waits for its launch."""
    from pm_core.signoff import return_awaiting
    try:
        pr = store.get_pr(store.load(app._root), pr_id)
    except Exception:
        _log.debug("auto_start: reload for %s failed", pr_id, exc_info=True)
        return False
    return return_awaiting(pr) == hop


async def _start_pr_quiet(app, pr_id: str, fresh: bool = False) -> bool:
    """Start a PR without changing TUI focus; False when ``pr start`` failed.

    Runs ``pm pr start --background <pr_id>`` as a subprocess. The
    ``--background`` flag tells ``pr start`` to create the tmux window
    without switching focus.  Unlike the interactive start_pr in pr_view,
    this doesn't use the inflight guard or spinner since auto-start can
    overlap with user actions.  *fresh* adds ``--fresh`` (kill + relaunch
    an existing impl window — used by the sign-off impl bounce).
    """
    import asyncio

    # ``pr start`` makes the PR the active_pr; a scheduler-driven start must
    # not drag the user's tree cursor onto it.
    quiet = getattr(app, "_quiet_activations", None)
    if isinstance(quiet, dict):
        quiet[pr_id] = time.monotonic() + 120

    cmd = [sys.executable, "-m", "pm_core.wrapper", "pr", "start", "--background"]
    if fresh:
        cmd.append("--fresh")
    if spec_review_required(app, pr_id):
        # Review-mode spec prompt that waits for pm-recorded approval.
        cmd.append("--review-spec")
    tdir = get_transcript_dir(app)
    if tdir:
        cmd.extend(["--transcript", str(tdir / f"impl-{pr_id}.jsonl")])
    cmd.append(pr_id)
    cwd = str(app._root) if app._root else None

    proc = await _run_shell_async(
        cmd, cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

    if proc.returncode != 0:
        stderr_text = stderr.decode() if stderr else ""
        _log.warning("auto_start: pm pr start %s failed: %s", pr_id, stderr_text[:200])
        if isinstance(quiet, dict):
            quiet.pop(pr_id, None)
        return False
    _log.info("auto_start: pm pr start %s succeeded", pr_id)
    return True


# ---------------------------------------------------------------------------
# Structured status (shared by the runs popup and ``pm autostart status``)
# ---------------------------------------------------------------------------

def collect_status_inputs(app) -> dict:
    """Gather live scheduler/worker/tmux/verdict evidence for build_status.

    Runs on the TUI event loop.  Cost: one ``tmux list-windows`` plus one
    ``git rev-parse`` per in-scope sign-off/pending-merge PR — no model
    calls.
    """
    from pm_core import tmux as tmux_mod

    prs = (app._data or {}).get("prs") or []
    enabled = is_enabled(app)
    managed = managed_ids(app, prs)

    def scoped(pr_id: str) -> bool:
        return managed is None or pr_id in managed

    windows: dict[str, str] = {}
    session = getattr(app, "_session_name", None)
    if session and enabled:
        try:
            windows = {w["name"]: w["id"] for w in tmux_mod.list_windows(session)}
        except Exception:
            _log.debug("collect_status_inputs: list_windows failed", exc_info=True)

    review_loops = {pid: autostart_state.review_progress_input(st)
                    for pid, st in (app._review_loops or {}).items() if scoped(pid)}
    qa_loops = {pid: autostart_state.qa_progress_input(st)
                for pid, st in (app._qa_loops or {}).items() if scoped(pid)}
    # A finished QA run is dropped from _qa_loops after one poll tick; its
    # verdict survives in runtime_state (qa action ``done``).  Report that
    # recorded verdict rather than claiming the PR is merely queued.
    for pr in prs:
        pr_id = pr.get("id")
        if (pr.get("status") == "qa" and pr_id not in qa_loops
                and pr_id and scoped(pr_id)):
            verdict = recorded_qa_verdict(pr_id, pr)
            if verdict:
                qa_loops[pr_id] = {"running": False, "verdict": verdict,
                                   "recorded": True}

    impl_idle: dict[str, str] = {}
    tracker = getattr(app, "_pane_idle_tracker", None)
    pending_merge = set(getattr(app, "_pending_merge_prs", set()) or ())
    signoff_info: dict[str, dict] = {}
    for pr in prs:
        pr_id = pr.get("id")
        if not pr_id or not scoped(pr_id):
            continue
        status = pr.get("status")
        if status == "in_progress" and tracker is not None:
            try:
                if tracker.is_tracked(pr_id):
                    impl_idle[pr_id] = (
                        "waiting" if tracker.is_waiting_for_input(pr_id)
                        else "idle" if tracker.is_idle(pr_id) else "active")
            except Exception:
                pass
        # Sign-off record freshness needs a ``git rev-parse``; only look
        # where it matters (QA passed, sign-off step, or a pending merge).
        qa_passed = (status == "qa"
                     and (qa_loops.get(pr_id) or {}).get("verdict") == "PASS")
        if qa_passed or status == "sign_off" or pr_id in pending_merge:
            from pm_core import signoff as _signoff
            rec = pr.get("signoff") or {}
            sha = _signoff.head_sha(pr.get("workdir"))
            fresh = _signoff.fresh_recorded_verdict(pr, sha)
            signoff_info[pr_id] = {"verdict": rec.get("verdict"),
                                   "fresh": fresh is not None}
            if fresh is None and rec.get("verdict"):
                signoff_info[pr_id]["stale_reason"] = \
                    _signoff.stale_reason(rec)

    from pm_core import spec_gen
    spec_reviews: dict[str, dict] = {}
    review_modes: set[str] = set()
    global_mode = spec_gen.get_spec_mode()
    for pr in prs:
        pr_id = pr.get("id")
        if not pr_id or not scoped(pr_id):
            continue
        phase = autostart_state.pending_spec_phase(pr)
        if phase:
            loc = spec_gen.spec_location(pr, phase)
            spec_reviews[pr_id] = {"path": str(loc) if loc else None}
        if enabled and spec_gen.pr_spec_mode(
                pr, global_mode=global_mode) == "review":
            review_modes.add(pr_id)

    project = (app._data or {}).get("project") or {}
    return {
        "prs": prs,
        "targets": dict(_targets(app)) if enabled else {},
        "all_mode": is_all_mode(app),
        "enabled": enabled,
        "run_id": app._auto_start_run_id,
        "owner": {"session": session, "pid": os.getpid()},
        "stop_before_merge": set(getattr(app, "_stop_before_merge", set()) or ()),
        "review_loops": review_loops,
        "qa_loops": qa_loops,
        "pending_merge": pending_merge,
        "merge_input_required": set(getattr(app, "_merge_input_required_prs", set()) or ()),
        "launching": set(_launching(app)),
        "impl_idle": impl_idle,
        "windows": windows,
        "signoff": signoff_info,
        "skip_qa": bool(project.get("skip_qa")),
        "spec_reviews": spec_reviews,
        "spec_review_modes": review_modes,
    }


def build_status(app) -> dict:
    """The ``pm.autostart.status/1`` dict for this TUI."""
    return autostart_state.build_status(collect_status_inputs(app))


# ---------------------------------------------------------------------------
# Command handling (command bar + ``pm autostart`` CLI via the cmd queue)
# ---------------------------------------------------------------------------

USAGE = ("autostart add PR_ID... [--stop-before-merge|--auto-merge|"
         "--wait-for-merge] [--review-specs|--no-review-specs] | "
         "remove PR_ID... | list | status | clear | all")

# Flag → policy (the inverse of ``autostart_state.POLICY_FLAGS``).
_FLAG_POLICIES = {flag: p for p, flag in autostart_state.POLICY_FLAGS.items()}


def reply_dir() -> Path:
    return pm_home() / REPLY_DIR


def write_reply(reply_id: str, payload: dict) -> Path | None:
    """Atomically write a CLI reply file; prunes stale replies."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", reply_id or ""):
        _log.warning("auto_start: refusing bad reply id %r", reply_id)
        return None
    d = reply_dir()
    d.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for old in d.glob("*.json"):
        try:
            if now - old.stat().st_mtime > _REPLY_MAX_AGE:
                old.unlink()
        except OSError:
            pass
    path = d / f"{reply_id}.json"
    tmp = d / f".{reply_id}.tmp"
    tmp.write_text(json.dumps(payload, default=sorted))
    os.replace(tmp, path)
    return path


def handle_command(app, args: list[str]) -> dict:
    """Dispatch ``autostart <verb> …`` (tokens after ``autostart``).

    Verbs: ``add``/``target`` IDS, ``remove``/``rm`` IDS, ``clear``/``off``,
    ``all``, ``list``, ``status``; bare ``autostart`` turns auto-start off
    when on and prints usage when off (it no longer enables the whole
    backlog).  Flags: ``--stop-before-merge`` / ``--auto-merge`` /
    ``--wait-for-merge`` (``add`` only; at most one distinct policy — a
    contradiction rejects the whole command before any change),
    ``--review-specs`` / ``--no-review-specs`` (``add`` only; composes with
    a policy, the two contradict each other),
    ``--reply ID`` (CLI: write the JSON reply file).  Returns the result.
    """
    reply_id = None
    policies: list[str] = []
    review_flags: list[str] = []
    rest: list[str] = []
    it = iter(args)
    for tok in it:
        if tok == "--reply":
            reply_id = next(it, None)
        elif tok in _FLAG_POLICIES:
            if _FLAG_POLICIES[tok] not in policies:
                policies.append(_FLAG_POLICIES[tok])
        elif tok in (REVIEW_FLAG, NO_REVIEW_FLAG):
            if tok not in review_flags:
                review_flags.append(tok)
        else:
            rest.append(tok)
    verb = rest[0] if rest else ""
    ids = rest[1:]
    source = "cli" if reply_id else "command"
    open_popup = False

    try:
        if len(policies) > 1:
            result = {"ok": False, "error": "conflicting_flags",
                      "message": "conflicting merge policies: "
                      + ", ".join(autostart_state.POLICY_FLAGS[p]
                                  for p in policies),
                      "changes": []}
        elif len(review_flags) > 1:
            result = {"ok": False, "error": "conflicting_flags",
                      "message": f"conflicting flags: {REVIEW_FLAG}, "
                      f"{NO_REVIEW_FLAG}", "changes": []}
        elif (policies or review_flags) and verb not in ("add", "target"):
            result = {"ok": False, "error": "usage",
                      "message": f"target option flags only apply to add; "
                      f"usage: {USAGE}", "changes": []}
        else:
            review = ({REVIEW_FLAG: True, NO_REVIEW_FLAG: False}
                      [review_flags[0]] if review_flags else None)
            result, open_popup = _dispatch(
                app, verb, ids, policies[0] if policies else None, source,
                bool(reply_id), review)
    except Exception as e:
        # Never leave a CLI caller waiting for a reply that will not come
        # (it would misreport the failure as owner_timeout).
        _log.exception("auto_start: command %r failed", args)
        result = {"ok": False, "error": "internal",
                  "message": f"auto-start command failed: {e}", "changes": []}

    if not result.get("ok"):
        app.log_message(f"Auto-start: {result.get('message')}", force=True)
    _log.info("auto_start: command %r → ok=%s error=%s", args,
              result.get("ok"), result.get("error"))

    if reply_id:
        payload = dict(result)
        try:
            payload["status"] = build_status(app)
        except Exception as e:
            _log.exception("auto_start: build_status failed")
            payload["status"] = None
            payload.setdefault("message", f"status failed: {e}")
        write_reply(reply_id, payload)
    elif open_popup:
        open_runs_popup(app)
    return result


def _dispatch(app, verb: str, ids: list[str], policy: str | None,
              source: str, has_reply: bool,
              review_specs: bool | None = None) -> tuple[dict, bool]:
    """Apply one ``autostart`` verb; returns ``(result, open_popup)``."""
    open_popup = False
    if verb == "":
        if is_enabled(app):
            result = clear_targets(app)
        else:
            result = {"ok": False, "error": "usage",
                      "message": f"auto-start is off; usage: {USAGE}",
                      "changes": []}
    elif verb in ("add", "target"):
        if not ids:
            result = {"ok": False, "error": "usage",
                      "message": f"no PR ids given; usage: {USAGE}",
                      "changes": []}
        else:
            result = add_targets(app, ids, policy=policy, source=source,
                                 review_specs=review_specs)
    elif verb in ("remove", "rm"):
        result = remove_targets(app, ids)
    elif verb in ("clear", "off"):
        result = clear_targets(app)
    elif verb == "all":
        result = enable_all(app)
    elif verb in ("list", "status"):
        result = {"ok": True, "changes": []}
        if not has_reply:
            if verb == "status":
                open_popup = True
            else:
                app.log_message(_list_summary(app), force=True)
    else:
        result = {"ok": False, "error": "usage",
                  "message": f"unknown verb {verb!r}; usage: {USAGE}",
                  "changes": []}
    return result, open_popup


def _list_summary(app) -> str:
    """One log line for command-bar ``autostart list``."""
    if not is_enabled(app):
        return "Auto-start: off (no targets)"
    if is_all_mode(app):
        return "Auto-start: all ready PRs (backlog mode)"
    marks = {POLICY_STOP: "stop", POLICY_WAIT: "wait-for-merge"}
    parts = []
    for t in get_targets(app):
        opts = [marks[p] for p in (target_policy(app, t),) if p in marks]
        if autostart_state.is_review_target(_targets(app).get(t)):
            opts.append("review-specs")
        parts.append(f"{t} ({', '.join(opts)})" if opts else t)
    return f"Auto-start targets: {', '.join(parts)}"


def open_runs_popup(app) -> None:
    from pm_core.tui.screens import AutoRunsScreen
    if any(isinstance(s, AutoRunsScreen) for s in app.screen_stack):
        return
    app.push_screen(AutoRunsScreen())
