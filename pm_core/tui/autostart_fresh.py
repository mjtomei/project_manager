"""Explicit "fresh autostart" (``z a``/``z O``/``z A`` / ``pm autostart fresh``).

A PR that reached review may be sent back to implementation by hand: the
user stops the review loop, resumes the *existing* implementation pane with
feedback, and asks auto-start to take the changed PR through review, QA and
sign-off again.  Plain ``autostart add`` is a continuation from the current
phase; it neither rewinds the status nor retires the stopped loop/QA/sign-off
state that would otherwise block (or prematurely advance) the new attempt.

This module implements the explicit workflow reset:

* one atomic ``store.locked_update`` returns the PR to ``in_progress``,
  closes an open sign-off return, invalidates (and archives) the recorded
  sign-off verdict, and writes the ``fresh_autostart`` marker;
* the live implementation session is *adopted*, never killed or relaunched:
  the pane is registered in the idle tracker and the scheduler's
  ``pr start --background`` fast path is a no-op while the window exists;
* the attempt waits for the current implementation turn to complete (a new
  hook event after ``requested_at`` or a structurally complete transcript
  turn), then hands off to the existing ``_auto_review_idle_prs`` path, which
  starts exactly one fresh review.

Historical evidence is preserved: the prior sign-off record is appended to
``signoff_history``, QA notes/captures/transcripts stay, and only the
driver-side symlinks/launch stamps the existing bounce path also retires are
removed.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from pm_core.paths import configure_logger
from pm_core import store
from pm_core.autostart_state import (
    FRESH_KEY, POLICY_STOP, TERMINAL_STATUSES, fresh_awaiting, fresh_marker,
    now_iso,
)

_log = configure_logger("pm.tui.autostart_fresh")

# Statuses a fresh request may rewind.  ``in_progress`` is handled
# separately (idempotent while an attempt is already waiting).
_LATER_STAGES = ("in_review", "qa", "sign_off")

# Terminal verdict written to the old attempt's runtime_state records.  It
# replaces a finished loop/QA verdict so nothing adopts it as current work,
# while ``previous_verdict`` keeps the historical value.
SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _merge_in_progress(app, pr_id: str) -> bool:
    """Whether a merge of *pr_id* is actually in flight."""
    if pr_id in (getattr(app, "_pending_merge_prs", None) or set()):
        return True
    if pr_id in (getattr(app, "_merge_input_required_prs", None) or set()):
        return True
    try:
        from pm_core.tui.review_loop_ui import _merge_window_exists
        return bool(_merge_window_exists(app, pr_id))
    except Exception:
        _log.debug("autostart_fresh: merge-window check failed for %s",
                   pr_id, exc_info=True)
        return False


def _validate(app, pr: dict) -> dict | None:
    """Reject a PR that cannot take a fresh reset (None = allowed)."""
    pr_id = pr.get("id")
    status = pr.get("status")
    if status in TERMINAL_STATUSES:
        return {"error": "terminal_pr",
                "message": f"already {status}: {pr_id}"}
    if not pr.get("workdir"):
        return {"error": "no_workdir",
                "message": f"{pr_id} has no implementation workdir; start it "
                           f"first with `pm pr start {pr_id}`"}
    if status == "in_progress":
        if fresh_awaiting(pr):
            return None  # repeated request: idempotent
        return {"error": "not_later_stage",
                "message": f"{pr_id} is already in implementation; plain "
                           f"`pm autostart add {pr_id}` continues it "
                           f"(fresh autostart returns a reviewed PR to "
                           f"implementation after feedback)"}
    if status not in _LATER_STAGES:
        return {"error": "not_later_stage",
                "message": f"{pr_id} is {status}; fresh autostart applies to "
                           f"in_review / qa / sign_off PRs"}
    if _merge_in_progress(app, pr_id):
        return {"error": "merge_in_progress",
                "message": f"{pr_id} has a merge in flight; finish or resolve "
                           f"it before returning to implementation"}
    return None


# ---------------------------------------------------------------------------
# Atomic reset (project.yaml)
# ---------------------------------------------------------------------------

def reset_pr(root: Path, pr_id: str, source: str,
             policy: str | None = None) -> dict:
    """Return *pr_id* to implementation and arm one fresh attempt.

    The whole transition (status, return closure, sign-off invalidation +
    history, marker) is one ``store.locked_update``.  *policy* is recorded on
    the marker so a TUI restart can restore the target with the same merge
    policy.  Returns ``{"ok", "action", "from_status", ...}``; ``action`` is
    ``fresh_reset`` or ``already_waiting``.
    """
    from pm_core.cli.helpers import _record_status_timestamp

    now = now_iso()
    out: dict = {}

    def _apply(data):
        pr = store.get_pr(data, pr_id)
        if not pr:
            out.update(ok=False, error="unknown_pr",
                       message=f"unknown PR id: {pr_id}")
            return
        status = pr.get("status")
        if status in TERMINAL_STATUSES:
            out.update(ok=False, error="terminal_pr",
                       message=f"{pr_id} is already {status}")
            return
        if status == "in_progress":
            if fresh_awaiting(pr):
                # Repeated request while the attempt is already waiting: keep
                # the attempt (requested_at, handoff baseline) intact, but
                # record an explicitly requested policy so a TUI restart
                # restores the target the user just asked for.
                marker = pr.get(FRESH_KEY)
                if isinstance(marker, dict) and policy \
                        and marker.get("policy") != policy:
                    marker["policy"] = policy
                out.update(ok=True, action="already_waiting",
                           from_status=status)
            else:
                out.update(ok=False, error="not_later_stage",
                           message=f"{pr_id} is already in implementation")
            return
        if status not in _LATER_STAGES:
            out.update(ok=False, error="not_later_stage",
                       message=f"{pr_id} is {status}")
            return

        marker = fresh_marker(pr)
        attempt = int(marker.get("attempt") or 0) + 1

        # A sign-off return still waiting for its (fresh) launch would make
        # the scheduler relaunch the implementation session with --fresh,
        # killing the live pane we must adopt.  Close it; keep the record.
        ret = pr.get("signoff_return")
        if isinstance(ret, dict) and not ret.get("resolved_at"):
            ret["resolved_at"] = now
            ret["awaiting"] = None
            ret["superseded_by_fresh_autostart"] = True

        # A verdict recorded before the feedback verified the old code.
        # Keep it for provenance, but never let it be adopted or merged.
        # A record invalidated by an earlier attempt is already archived;
        # appending it again would only duplicate history.
        sig = pr.get("signoff")
        if isinstance(sig, dict) and sig.get("verdict") \
                and not sig.get("invalidated"):
            hist = pr.get("signoff_history")
            if not isinstance(hist, list):
                hist = []
                pr["signoff_history"] = hist
            hist.append({**sig, "superseded_at": now,
                         "superseded_reason": "fresh-autostart"})
            # Bound the append-only history; the newest 20 are plenty.
            if len(hist) > 20:
                del hist[:-20]
            sig["invalidated"] = ("superseded by fresh autostart "
                                  "(implementation feedback)")
            sig["invalidated_at"] = now

        pr["status"] = "in_progress"
        _record_status_timestamp(pr, "in_progress")
        pr[FRESH_KEY] = {
            "requested_at": now,
            "from_status": status,
            "source": source,
            "attempt": attempt,
            "policy": policy or POLICY_STOP,
            "awaiting_handoff": True,
        }
        out.update(ok=True, action="fresh_reset", from_status=status,
                   attempt=attempt)

    try:
        store.locked_update(root, _apply)
    except (store.StoreLockTimeout, store.ProjectYamlParseError, OSError) as e:
        _log.warning("autostart_fresh: reset %s failed: %s", pr_id, e)
        return {"ok": False, "error": "store_error", "message": str(e)}
    if not out:
        return {"ok": False, "error": "internal",
                "message": f"reset of {pr_id} did not apply"}
    return out


# ---------------------------------------------------------------------------
# Retiring the old attempt's live/in-memory state
# ---------------------------------------------------------------------------

def _review_window_name(pr: dict) -> str:
    from pm_core.cli.helpers import _pr_display_id
    return f"review-{_pr_display_id(pr)}"


def retire_in_memory(app, pr: dict) -> None:
    """Drop the old attempt's loop/QA/sign-off state (evidence is kept).

    Pops the stopped/completed review loop so neither
    ``_auto_start_review_loops`` nor ``_auto_review_idle_prs`` treats the PR
    as already reviewed, stops a live loop/QA run, and writes terminal
    ``runtime_state`` sentinels with a fresh ``loop_id`` so late callbacks
    from the old threads bow out (``review_loop_ui._is_active_loop``).
    """
    from pm_core import runtime_state as _rs
    pr_id = pr["id"]
    now = now_iso()

    loop = app._review_loops.pop(pr_id, None)
    if loop is not None and getattr(loop, "running", False):
        loop.stop_requested = True
    if loop is not None:
        _kill_review_window(app, pr)

    qa = app._qa_loops.pop(pr_id, None)
    if qa is not None and getattr(qa, "running", False):
        qa.stop_requested = True
    (getattr(app, "_self_driving_qa", None) or {}).pop(pr_id, None)

    # A resumed turn fires no hook at its start, so the tracker still holds
    # the *previous* turn's idle flag; left alone, the status row would claim
    # "implementation turn complete; starting fresh review" for the whole
    # wait.  Clear it: the next idle_prompt is this turn's end.  Only the
    # stale idle flag is wrong — a live permission prompt (waiting_for_input)
    # must keep its own status reason.
    tracker = getattr(app, "_pane_idle_tracker", None)
    if tracker is not None:
        try:
            if tracker.is_idle(pr_id):
                tracker.mark_active(pr_id)
        except Exception:
            _log.debug("autostart_fresh: idle reset failed for %s",
                       pr_id, exc_info=True)

    # Sign-off driver bookkeeping (the recorded verdict was invalidated in
    # the atomic reset; the router window/transcript is retired below).
    try:
        from pm_core.tui import signoff_ui
        signoff_ui._acted(app).pop(pr_id, None)
        signoff_ui._launched_at(app).pop(pr_id, None)
    except Exception:
        _log.debug("autostart_fresh: sign-off bookkeeping cleanup failed",
                   exc_info=True)

    (getattr(app, "_pending_merge_prs", None) or set()).discard(pr_id)
    (getattr(app, "_merge_input_required_prs", None) or set()).discard(pr_id)

    try:
        prev = _rs.get_action_state(pr_id, "review-loop") or {}
        if loop is not None or prev:
            _rs.set_action_state(
                pr_id, "review-loop", "done", verdict=SUPERSEDED,
                loop_id=secrets.token_hex(4),
                previous_verdict=prev.get("verdict")
                or getattr(loop, "latest_verdict", "") or "",
                superseded_at=now)
    except Exception:
        _log.debug("autostart_fresh: review-loop sentinel failed for %s",
                   pr_id, exc_info=True)
    try:
        prev = _rs.get_action_state(pr_id, "qa") or {}
        if qa is not None or prev:
            _rs.set_action_state(
                pr_id, "qa", "done", verdict=SUPERSEDED,
                previous_verdict=prev.get("verdict")
                or getattr(qa, "latest_verdict", "") or "",
                superseded_at=now)
    except Exception:
        _log.debug("autostart_fresh: qa sentinel failed for %s",
                   pr_id, exc_info=True)


def _kill_review_window(app, pr: dict) -> None:
    """Kill the PR's review window so a live loop's poll exits promptly."""
    session = getattr(app, "_session_name", None)
    if not session:
        return
    from pm_core import tmux as tmux_mod
    name = _review_window_name(pr)
    try:
        win = tmux_mod.find_window_by_name(session, name)
        if win:
            from pm_core import home_window
            home_window.park_if_on(session, win["id"])
            tmux_mod.kill_window(session, name)
            _log.info("autostart_fresh: killed review window %s", name)
    except Exception:
        _log.debug("autostart_fresh: kill review window %s failed", name,
                   exc_info=True)


def retire_downstream(app, pr: dict) -> None:
    """Retire the old sign-off router run (window + transcript + stamp)."""
    session = getattr(app, "_session_name", None)
    if not session:
        return
    try:
        from pm_core.tui import auto_start as _auto_start
        tdir = _auto_start.get_transcript_dir(app)
    except Exception:
        tdir = None
    if not tdir:
        return
    try:
        from pm_core import signoff as signoff_mod
        signoff_mod.retire_signoff_run(session, pr, Path(tdir))
        _log.info("autostart_fresh: retired sign-off run for %s", pr["id"])
    except Exception:
        _log.debug("autostart_fresh: retire sign-off run for %s failed",
                   pr["id"], exc_info=True)


# ---------------------------------------------------------------------------
# Implementation handoff
# ---------------------------------------------------------------------------

def _impl_transcript(app, pr: dict, tracker) -> str | None:
    """The live implementation pane's transcript path, if resolvable.

    The pane's own start command is preferred over the tracker's registered
    path: a run-dir symlink may have been *finalized* (replaced by a copy)
    when auto-start was disabled, and the copy stops tracking later turns.
    """
    pr_id = pr["id"]
    session = getattr(app, "_session_name", None)
    if session:
        try:
            from pm_core.tui.review_loop_ui import _find_impl_pane
            from pm_core.cli.helpers import _pr_display_id
            from pm_core.claude_launcher import pane_transcript_path
            pane = _find_impl_pane(session, _pr_display_id(pr))
            if pane:
                path = pane_transcript_path(pane, pr.get("workdir"))
                if path:
                    return str(path)
        except Exception:
            _log.debug("autostart_fresh: pane transcript lookup failed for "
                       "%s", pr_id, exc_info=True)
    try:
        if tracker.is_tracked(pr_id):
            path = tracker.get_transcript_path(pr_id)
            if path:
                return path
    except Exception:
        pass
    return None


def _latest_hook_event(transcript: str | None) -> dict | None:
    """The newest hook event for *transcript*'s Claude session, if any."""
    if not transcript:
        return None
    from pm_core import hook_events
    from pm_core.claude_launcher import session_id_from_transcript
    try:
        sid = session_id_from_transcript(transcript)
    except Exception:
        sid = None
    if not sid:
        return None
    return hook_events.read_event(sid)


def _epoch(iso: str | None) -> float:
    if not iso:
        return 0.0
    try:
        from pm_core.signoff import parse_ts
        return parse_ts(iso).timestamp()
    except (TypeError, ValueError):
        return 0.0


def handoff_ready(app, pr: dict, tracker) -> bool:
    """Whether the current implementation turn has completed.

    The transcript's newest turn is the authoritative signal, fenced against
    the old attempt: ``complete`` (the newest record is an assistant message
    with no pending tool) means the turn is over, which covers "already
    completed before autostart was enabled" and a restarted TUI (no hook
    needed).  ``in_progress`` means a newer turn is still running, so a hook
    event — which can only belong to an earlier turn — must not advance.

    Only when the transcript is missing/unreadable does a **new**
    ``idle_prompt``/``Stop`` hook event whose timestamp is after
    ``fresh_autostart.requested_at`` count as the handoff (old events cannot).
    """
    if not fresh_awaiting(pr):
        return False
    if pr.get("spec_pending"):
        # The existing spec gate owns the next step; do not advance.
        return False
    from pm_core.signoff import return_awaiting
    if return_awaiting(pr) == "impl":
        # A (racing) sign-off bounce still expects a fresh impl launch; an
        # idle old session is not finished rework.
        return False
    pr_id = pr["id"]
    try:
        if tracker.is_gone(pr_id):
            return False
    except Exception:
        pass

    transcript = _impl_transcript(app, pr, tracker)
    if transcript:
        from pm_core.verdict_transcript import latest_turn_state
        # The transcript's structure is authoritative: "complete" means the
        # newest record is an assistant message with no pending tool, i.e.
        # the turn is over.  Do not additionally require the hook tracker's
        # idle flag — it can be stale (no turn-start hook) or miss the event
        # when ``Stop`` is written after ``idle_prompt``.
        state = latest_turn_state(transcript)
        if state == "complete":
            return True
        if state == "in_progress":
            # The user already started another turn (e.g. typed a follow-up
            # after the previous turn's ``idle_prompt`` fired).  A hook event
            # still on disk belongs to that earlier turn; advancing now would
            # launch the review over in-flight work.
            return False

    # Transcript missing/unreadable: fall back to the newest hook event,
    # fenced against the old attempt by ``requested_at``.
    since = _epoch(fresh_marker(pr).get("requested_at"))
    event = _latest_hook_event(transcript)
    if event:
        try:
            ts = float(event.get("timestamp") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        if ts > since and event.get("event_type") in ("idle_prompt", "Stop"):
            return True
    return False


def consume_handoff(app, pr_id: str) -> None:
    """Mark the fresh attempt's handoff seen (called when review starts)."""
    if not getattr(app, "_root", None):
        return
    now = now_iso()

    def _apply(data):
        pr = store.get_pr(data, pr_id)
        marker = (pr or {}).get(FRESH_KEY)
        if isinstance(marker, dict) and marker.get("awaiting_handoff"):
            marker["awaiting_handoff"] = False
            marker["handoff_at"] = now
            marker["review_started_at"] = now

    try:
        store.locked_update(app._root, _apply)
    except Exception:
        _log.debug("autostart_fresh: consume handoff for %s failed",
                   pr_id, exc_info=True)


def resume_pending(app) -> list[str]:
    """Re-arm fresh attempts left waiting by a previous TUI process.

    Auto-start targets are in-memory and a plain TUI restart drops them, but
    an explicit fresh reset is a user request that must survive the restart:
    its marker is on the PR and the implementation session is still live.
    Re-add each in-progress, still-awaiting PR as a target with the policy
    recorded on the marker.  Returns the resumed PR ids.
    """
    if not getattr(app, "_root", None):
        return []
    try:
        data = store.load(app._root)
    except Exception:
        _log.debug("autostart_fresh: resume scan failed", exc_info=True)
        return []
    from pm_core.autostart_state import POLICIES
    from pm_core.tui.auto_start import add_targets, get_targets
    resumed = []
    for pr in data.get("prs") or []:
        if pr.get("status") != "in_progress" or not fresh_awaiting(pr):
            continue
        pr_id = pr["id"]
        if pr_id in get_targets(app):
            continue
        policy = fresh_marker(pr).get("policy") or POLICY_STOP
        if policy not in POLICIES:
            policy = POLICY_STOP
        try:
            add_targets(app, [pr_id], policy=policy, source="resume",
                        confirm=f"Auto-start: resumed fresh attempt for "
                                f"{pr_id} (waiting for its implementation "
                                f"handoff)")
        except Exception:
            _log.warning("autostart_fresh: resume of %s failed", pr_id,
                         exc_info=True)
            continue
        resumed.append(pr_id)
    if resumed:
        try:
            from pm_core.tui.review_loop_ui import _ensure_poll_timer
            _ensure_poll_timer(app)
        except Exception:
            _log.debug("autostart_fresh: resume timer arm failed",
                       exc_info=True)
        _log.info("autostart_fresh: resumed %s", resumed)
    return resumed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def fresh_start(app, ids: list[str], policy: str | None = None,
                source: str = "command",
                default_policy: str | None = POLICY_STOP) -> dict:
    """``z a``/``z O``/``z A`` / ``pm autostart fresh ID...``: reset, adopt,
    wait, review.

    Validation is all-or-nothing (unknown / terminal / no-workdir /
    not-a-later-stage / merge-in-flight reject the whole command before
    anything changes).  Each valid PR is reset atomically, the old attempt's
    live state is retired, the PR is added as an auto-start target (policy
    preserved for an existing target), and the handoff is either started
    immediately (turn already complete) or awaited.
    """
    if not getattr(app, "_root", None):
        return {"ok": False, "error": "no_project",
                "message": "no project root", "changes": []}
    if not ids:
        return {"ok": False, "error": "usage", "message": "no PR ids given",
                "changes": []}

    # Flush pending in-memory edits before reading/updating project.yaml.
    wq = getattr(app, "_write_queue", None)
    if wq is not None:
        try:
            wq.flush_sync()
        except Exception:
            _log.debug("autostart_fresh: write-queue flush failed",
                       exc_info=True)

    from pm_core.tui.auto_start import _resolve_ids
    found, missing = _resolve_ids(app, ids)
    if missing:
        return {"ok": False, "error": "unknown_pr",
                "message": f"unknown PR id(s): {', '.join(missing)}",
                "invalid": missing, "changes": []}

    prs: list[dict] = []
    seen: set[str] = set()
    for pr in found:
        if pr["id"] not in seen:
            seen.add(pr["id"])
            prs.append(pr)

    errors = []
    for pr in prs:
        err = _validate(app, pr)
        if err:
            errors.append((pr["id"], err))
    if errors:
        first = errors[0][1]
        return {"ok": False, "error": first["error"],
                "message": first["message"],
                "invalid": [pid for pid, _ in errors], "changes": []}

    from pm_core.tui.auto_start import get_targets, target_policy
    changes: list[dict] = []
    reset_prs: list[dict] = []
    failed: list[dict] = []
    for pr in prs:
        pr_id = pr["id"]
        # Record the policy the target will actually use: an explicit flag,
        # else an existing target's own policy, else the new-target default.
        effective = policy
        if effective is None:
            effective = (target_policy(app, pr_id)
                         if pr_id in get_targets(app) else default_policy)
        result = reset_pr(app._root, pr_id, source, policy=effective)
        if not result.get("ok"):
            failed.append({"pr_id": pr["id"], **result})
            continue
        changes.append({"pr_id": pr["id"], "action": result["action"],
                        "from_status": result.get("from_status")})
        if result["action"] == "fresh_reset":
            reset_prs.append(pr)

    if not changes:
        first = failed[0] if failed else {
            "error": "internal", "message": "nothing was reset"}
        return {**first, "ok": False, "changes": []}

    # Retire the old attempt's live work before adding the target: the
    # scheduler pass add_targets triggers must not see a stale loop/window.
    for pr in reset_prs:
        try:
            retire_downstream(app, pr)
        except Exception:
            _log.warning("autostart_fresh: downstream retirement failed for %s",
                         pr["id"], exc_info=True)
        try:
            retire_in_memory(app, pr)
        except Exception:
            _log.warning("autostart_fresh: in-memory retirement failed for %s",
                         pr["id"], exc_info=True)

    from pm_core.tui.auto_start import CONFIRM_HOLD_SECONDS, add_targets
    ids_ok = [c["pr_id"] for c in changes]
    if reset_prs:
        confirm = ("Auto-start: fresh run for "
                   + ", ".join(ids_ok)
                   + " — returned to implementation after feedback")
    else:
        confirm = ("Auto-start: "
                   + ", ".join(ids_ok)
                   + " already waiting for its implementation turn")
    add = add_targets(app, ids_ok, policy=policy,
                      default_policy=default_policy, source=source,
                      confirm=confirm)
    if not add.get("ok"):
        return {**add, "changes": changes}

    # Pick up the reset target set / PR rows before the handoff decision.
    try:
        app._data = store.load(app._root)
    except Exception:
        _log.debug("autostart_fresh: reload after reset failed",
                   exc_info=True)
    if callable(getattr(app, "_update_display", None)):
        app._update_display()

    tracker = getattr(app, "_pane_idle_tracker", None)
    handoffs: dict[str, str] = {}
    for change in changes:
        pr_id = change["pr_id"]
        pr = store.get_pr(app._data, pr_id) or next(
            (p for p in prs if p["id"] == pr_id), None)
        if not pr:
            continue
        if change["action"] == "already_waiting":
            handoffs[pr_id] = "already_waiting"
            continue
        if tracker is not None and handoff_ready(app, pr, tracker):
            try:
                from pm_core.tui.review_loop_ui import _auto_review_idle_prs
                _auto_review_idle_prs(app, [(pr_id, pr)])
                # Only claim the review started if the status actually moved
                # (the launch can bail out — e.g. no tmux, no workdir).
                try:
                    after = store.get_pr(store.load(app._root), pr_id) or pr
                except Exception:
                    after = pr
                handoffs[pr_id] = ("review_started"
                                   if after.get("status") == "in_review"
                                   else "waiting")
            except Exception:
                # The poll timer retries the same handoff; a failed launch
                # must not lose the attempt.
                _log.warning("autostart_fresh: immediate review launch "
                             "failed for %s", pr_id, exc_info=True)
                handoffs[pr_id] = "waiting"
        else:
            handoffs[pr_id] = "waiting"

    # Arm the shared poll timer: the old loop may have been the only reason
    # it was running, and the handoff is detected there.
    try:
        from pm_core.tui.review_loop_ui import _ensure_poll_timer
        _ensure_poll_timer(app)
    except Exception:
        _log.debug("autostart_fresh: poll timer arm failed", exc_info=True)

    parts = []
    for pr_id, state in handoffs.items():
        if state == "review_started":
            parts.append(f"{pr_id}: implementation turn complete, "
                         f"fresh review started")
        elif state == "waiting":
            parts.append(f"{pr_id}: waiting for the current implementation "
                         f"turn")
        else:
            parts.append(f"{pr_id}: already waiting for its implementation "
                         f"turn")
    message = "Auto-start fresh: " + "; ".join(parts) if parts else confirm
    try:
        app.log_message(message, force=True, hold=CONFIRM_HOLD_SECONDS)
    except TypeError:
        app.log_message(message)

    result = {"ok": True, "changes": changes, "handoff": handoffs,
              "message": message}
    if failed:
        result["failed"] = failed
    return result
