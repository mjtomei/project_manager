"""PR action history: one query + presentation model for CLI and pane.

:func:`build_history` turns the action-history journal
(:mod:`pm_core.action_history`), the live runtime mirror
(:mod:`pm_core.runtime_state`), the latest Claude hook events and the
PR's project.yaml record into one JSON-able model (schema
``pm.pr.history/1``).  :func:`render_text` renders that model; ``pm pr
history`` and the PR actions pane both use these two functions, so the
two surfaces cannot disagree.

Reconciliation rules (the journal only says what writers *said*):

* An attempt with no end whose owner process is gone is reported as
  ``interrupted`` with an unknown end time (bounded below by the last
  event seen for it).  A runtime-derived attempt the runtime mirror still
  shows in flight is running whoever opened it.
* An attempt with no end whose parent ended is closed at the parent's end.
* A runtime attempt that re-tracks the pane of the previous attempt, which
  ended ``untracked``, is folded into it (the gap is an ``untracked``
  span): PM merely lost and regained sight of the same run.
* A timer is resolved by its own clear, by its owner attempt ending, or
  by its owner process exiting (``lost``); a ``gate`` timer past its due
  time has simply elapsed, while a ``fires`` timer past due with a live
  owner is reported as overdue.

Nothing here infers durations it has no evidence for: unknown values are
``None`` in JSON and ``unknown`` in text.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pm_core import action_history as _ah
from pm_core import runtime_state as _rs

SCHEMA = "pm.pr.history/1"

_PHASE_LABELS = {
    "start": "running",
    "launching": "launching",
    "planning": "planning",
    "agent": "agent",
    "verdict": "verdict processing",
    "verifying": "verifying",
    "queued": "queued",
    "backoff": "backoff",
    "waiting_human": "waiting on human",
    "untracked": "not tracked",
}

# Spans where PM was not watching the attempt at all: neither execution
# nor waiting as far as PM can tell.
_UNOBSERVED_PHASES = ("untracked",)

_ACTION_ORDER = ("start", "review", "review-loop", "qa", "signoff", "merge")


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def build_history(pr_id: str, *, pr: dict | None = None,
                  now: float | None = None, live: bool = True) -> dict:
    """Assemble the history model for *pr_id*.

    *pr* is the project.yaml record (milestones, derived holds).  *now*
    defaults to the action-history clock.  ``live=False`` skips the
    runtime mirror and hook events (pure journal view, used by tests).
    """
    t_now = _ah.now() if now is None else float(now)
    events = _ah.read_events(pr_id)
    attempts, timers, timer_history = _replay(events)
    aliases = _fold_retracked(attempts, timers)
    _link_children(attempts)
    # A parent was last seen no earlier than any of its descendants.
    for a in sorted(attempts.values(), key=lambda a: a["started_t"],
                    reverse=True):
        p = a.get("_parent_obj")
        if p is not None:
            p["last_seen_t"] = max(p["last_seen_t"], a["last_seen_t"])
    tracked = _runtime_tracked_attempts(pr_id) if live else set()
    _reconcile_attempts(attempts, {aliases.get(i, i) for i in tracked})
    for a in attempts.values():
        _compute_spans(a, t_now)
    roots = [a for a in attempts.values() if not a.get("_parent_obj")]
    for a in attempts.values():
        _compute_concurrency(a)

    timer_rows = _reconcile_timers(timers, attempts, t_now)
    timer_rows["recent"] = (timer_history + timer_rows["recent"])
    _release_terminal_holds(pr or {}, timer_rows)

    runtime = _runtime_actions(pr_id) if live else {}
    for entry in runtime.values():
        a = attempts.get(aliases.get(entry.get("attempt_id"),
                                     entry.get("attempt_id")) or "")
        if (a is not None and a.get("inferred") == "owner-exited"
                and entry.get("state") in _rs.IN_FLIGHT_STATES):
            entry["stale"] = "owner exited"
    current = _current_activity(attempts, timer_rows, t_now, live=live)
    holds = [t for t in timer_rows["active"] if t["due_at"] is None]
    holds += _derived_holds(pr_id, pr or {}, runtime)
    waiting_for = _waiting_for(holds, timer_rows, current, attempts)

    model: dict[str, Any] = {
        "schema": SCHEMA,
        "pr_id": pr_id,
        "title": (pr or {}).get("title"),
        "status": (pr or {}).get("status"),
        "display_id": _display_id(pr or {}, pr_id),
        "generated_at": _ah.iso(t_now),
        "journal": {
            "path": str(_ah.journal_path(pr_id)),
            "exists": _ah.has_journal(pr_id),
            "events": len(events),
            "first_event_at": _ah.iso(events[0]["t"]) if events else None,
        },
        "waiting_for": waiting_for,
        "current": current,
        "timers": {
            "active": [t for t in timer_rows["active"]
                       if t["due_at"] is not None],
            "overdue": timer_rows["overdue"],
            "recent": sorted(timer_rows["recent"],
                             key=lambda r: r.get("resolved_t") or 0,
                             reverse=True)[:20],
        },
        "holds": holds,
        "runtime": runtime,
        "attempts": [_export(a) for a in
                     sorted(roots, key=lambda a: a["started_t"],
                            reverse=True)],
        "milestones": _milestones(pr or {}),
        "missing": _missing_notes(pr or {}, events),
    }
    return model


def _display_id(pr: dict, pr_id: str) -> str:
    gh = pr.get("gh_pr_number")
    return f"#{gh}" if gh else pr_id


def _replay(events: list[dict]):
    attempts: dict[str, dict] = {}
    timers: dict[str, dict] = {}
    timer_history: list[dict] = []
    for ev in events:
        kind = ev.get("kind")
        t = float(ev.get("t") or 0)
        if kind == "attempt_start":
            aid = ev.get("attempt")
            if not aid or aid in attempts:
                continue
            a = {k: v for k, v in ev.items()
                 if k not in ("v", "ts", "t", "kind", "attempt", "pr_id")}
            a.update({"id": aid, "started_t": t, "last_seen_t": t,
                      "phases": [], "ended_t": None, "outcome": None,
                      "verdict": None, "detail": None, "inferred": None,
                      "children": []})
            attempts[aid] = a
        elif kind == "phase":
            a = attempts.get(ev.get("attempt"))
            if not a or a["ended_t"] is not None:
                continue
            a["phases"].append({"phase": ev.get("phase"), "t": t,
                                "detail": ev.get("detail")})
            a["last_seen_t"] = max(a["last_seen_t"], t)
            if ev.get("session_id") and not a.get("session_id"):
                a["session_id"] = ev["session_id"]
        elif kind == "attempt_end":
            a = attempts.get(ev.get("attempt"))
            if not a or a["ended_t"] is not None:
                continue
            a["ended_t"] = t
            a["outcome"] = ev.get("outcome")
            a["verdict"] = ev.get("verdict")
            a["detail"] = ev.get("detail")
            if ev.get("iteration") is not None and a.get("iteration") is None:
                a["iteration"] = ev["iteration"]
            if ev.get("adopted"):
                a["end_adopted"] = True
            a["last_seen_t"] = max(a["last_seen_t"], t)
        elif kind == "timer_arm":
            tid = ev.get("timer")
            if not tid:
                continue
            prev = timers.get(tid)
            if prev and prev.get("cleared") is None:
                timer_history.append(_timer_row(prev, "re-armed", t))
            timers[tid] = {
                "timer": tid, "purpose": ev.get("purpose"),
                "owner_action": ev.get("owner_action"),
                "owner_attempt": ev.get("owner_attempt"),
                "armed_t": float(ev.get("armed_t") or t),
                "due_t": ev.get("due_t"),
                "effect": ev.get("effect") or "gate",
                "expected": ev.get("expected"),
                "owner": ev.get("owner"), "cleared": None,
            }
        elif kind == "timer_clear":
            tm = timers.get(ev.get("timer"))
            if tm and tm.get("cleared") is None:
                tm["cleared"] = {"t": t, "reason": ev.get("reason")}
    return attempts, timers, timer_history


def _fold_retracked(attempts: dict[str, dict],
                    timers: dict[str, dict]) -> dict[str, str]:
    """Fold runtime attempts that re-track a pane into the earlier attempt.

    PM stops watching e.g. the impl pane while a review loop owns the PR
    (that attempt ends ``untracked``) and re-registers the same session
    when the loop ends.  That is the same run seen again, not a new
    attempt, so the later attempt continues the earlier one after an
    ``untracked`` span.  Returns ``{folded id: kept id}``.
    """
    aliases: dict[str, str] = {}
    last: dict[str, dict] = {}  # action -> newest runtime attempt
    for a in sorted(attempts.values(), key=lambda a: a["started_t"]):
        if a.get("source") != "runtime" or a.get("loop_id"):
            continue
        action = a.get("action") or ""
        prev = last.get(action)
        last[action] = a
        if (prev is None or prev["outcome"] != "untracked"
                or not a.get("session_id")
                or a.get("session_id") != prev.get("session_id")
                or a["started_t"] < prev["ended_t"]):
            continue
        prev["phases"] += [
            {"phase": "untracked", "t": prev["ended_t"],
             "detail": "PM not watching the pane"},
            {"phase": "start", "t": a["started_t"],
             "detail": "PM watching the pane again"},
        ] + a["phases"]
        for k in ("ended_t", "outcome", "verdict", "detail", "owner"):
            prev[k] = a.get(k)
        prev["last_seen_t"] = max(prev["last_seen_t"], a["last_seen_t"])
        last[action] = prev
        aliases[a["id"]] = prev["id"]
        del attempts[a["id"]]
    if aliases:
        for a in attempts.values():
            if a.get("parent") in aliases:
                a["parent"] = aliases[a["parent"]]
        for tm in timers.values():
            if tm.get("owner_attempt") in aliases:
                tm["owner_attempt"] = aliases[tm["owner_attempt"]]
    return aliases


def _reconcile_attempts(attempts: dict[str, dict],
                        tracked: set[str]) -> None:
    """Infer the fate of open attempts.

    *tracked* holds the ids of runtime-derived attempts the runtime mirror
    still shows in flight.  Those belong to the mirror, not to the process
    that happened to open them (e.g. a short-lived ``pm pr auto-sequence``
    CLI): whichever process clears the entry ends the attempt, so the
    opener exiting does not interrupt it.  A loop's entry (``loop_id``) is
    the exception: only the loop thread of the process that opened the
    attempt advances or clears it, so a killed owner (e.g. a SIGKILLed
    TUI, which leaves the entry ``running`` until the next TUI's mount
    sweep) interrupts it like any other attempt.
    """
    for a in attempts.values():
        if a["ended_t"] is not None:
            continue
        if a["id"] in tracked and not a.get("loop_id"):
            a["owner_alive"] = True
            continue
        alive = _ah.owner_alive(a.get("owner"))
        a["owner_alive"] = alive
        if alive is False:
            pid = (a.get("owner") or {}).get("pid")
            a["outcome"] = "interrupted"
            a["detail"] = (f"owner process exited or restarted (pid {pid}); "
                           "end time unknown")
            a["inferred"] = "owner-exited"
    # Close children of ended parents at the parent's end (start order, so
    # a closed parent propagates down the tree).  The linked parent also
    # covers iterations attached by loop_id in _link_children.
    for a in sorted(attempts.values(), key=lambda a: a["started_t"]):
        parent = a.get("_parent_obj")
        if not parent or a["ended_t"] is not None:
            continue
        if a.get("inferred") == "owner-exited":
            continue
        if parent["ended_t"] is not None:
            a["ended_t"] = max(parent["ended_t"], a["started_t"])
            a["outcome"] = (parent["outcome"]
                            if parent["outcome"] in ("cancelled", "superseded")
                            else "interrupted")
            a["detail"] = "parent run ended first"
            a["inferred"] = "parent-ended"
        elif parent.get("inferred") == "owner-exited":
            a["outcome"] = "interrupted"
            a["detail"] = parent["detail"]
            a["inferred"] = "owner-exited"


def _link_children(attempts: dict[str, dict]) -> None:
    by_start = sorted(attempts.values(), key=lambda a: a["started_t"])
    for a in by_start:
        parent = attempts.get(a.get("parent") or "")
        if parent is None and a.get("source") != "runtime" and a.get("loop_id"):
            # Iterations journaled without a parent id (e.g. the runtime
            # entry was missing): attach to the loop's runtime attempt.
            cands = [p for p in by_start
                     if p is not a and p.get("source") == "runtime"
                     and p.get("action") == a.get("action")
                     and p.get("loop_id") == a.get("loop_id")
                     and p["started_t"] <= a["started_t"]]
            parent = cands[-1] if cands else None
        if parent is not None and parent is not a:
            a["_parent_obj"] = parent
            parent["children"].append(a)


def _end_or_bound(a: dict, t_now: float) -> tuple[float, bool]:
    """(end time for span math, whether it is known)."""
    if a["ended_t"] is not None:
        return a["ended_t"], True
    if a.get("inferred") == "owner-exited":
        return a["last_seen_t"], False
    return t_now, True  # open and (as far as we know) still running


def _compute_spans(a: dict, t_now: float) -> None:
    end, known = _end_or_bound(a, t_now)
    spans = []
    marks = [{"phase": "start", "t": a["started_t"], "detail": None}]
    marks += a["phases"]
    for i, m in enumerate(marks):
        t0 = m["t"]
        t1 = marks[i + 1]["t"] if i + 1 < len(marks) else end
        if i == 0 and len(marks) > 1 and t1 - t0 < 0.5:
            continue  # immediate first phase; drop the empty "start" span
        spans.append({"phase": m["phase"], "start_t": t0,
                      "end_t": max(t0, t1), "detail": m.get("detail"),
                      "open": (i + 1 == len(marks) and a["ended_t"] is None
                               and known)})
    wait = sum(s["end_t"] - s["start_t"] for s in spans
               if s["phase"] in _ah.WAIT_PHASES)
    exe = sum(s["end_t"] - s["start_t"] for s in spans
              if s["phase"] not in _ah.WAIT_PHASES
              and s["phase"] not in _UNOBSERVED_PHASES)
    a["spans"] = spans
    a["elapsed_s"] = (end - a["started_t"]) if known else None
    a["elapsed_lower_bound_s"] = None if known else end - a["started_t"]
    a["wait_s"] = wait if known else None
    a["exec_s"] = exe if known else None
    a["open"] = a["ended_t"] is None and a.get("inferred") is None


def _compute_concurrency(a: dict) -> None:
    kids = [c for c in a["children"] if c.get("scenario") is not None]
    if len(kids) < 2:
        return
    # Execution intervals: a scenario queued for a concurrency slot is not
    # running yet, so its leading wait does not count as overlap.
    ivs = []
    for c in kids:
        end = c["started_t"] + (c.get("elapsed_s")
                                or c.get("elapsed_lower_bound_s") or 0)
        start = next((sp["start_t"] for sp in c.get("spans", [])
                      if sp["phase"] not in _ah.WAIT_PHASES), end)
        ivs.append((min(start, end), end))
    points = sorted([(s, 1) for s, _ in ivs] + [(e, -1) for _, e in ivs],
                    key=lambda p: (p[0], p[1]))
    depth = best = 0
    for _, d in points:
        depth += d
        best = max(best, depth)
    union = 0.0
    cur_s = cur_e = None
    for s, e in sorted(ivs):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                union += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        union += cur_e - cur_s
    a["scenarios"] = {
        "count": len({c.get("scenario") for c in kids}),
        "attempts": len(kids),
        "wall_s": union,
        "sum_s": sum(e - s for s, e in ivs),
        "max_concurrency": best,
    }


def _timer_row(tm: dict, resolution: str, resolved_t: float | None) -> dict:
    return {
        "timer": tm["timer"], "purpose": tm.get("purpose"),
        "owner_action": tm.get("owner_action"),
        "owner_attempt": tm.get("owner_attempt"),
        "effect": tm.get("effect"), "expected": tm.get("expected"),
        "armed_at": _ah.iso(tm["armed_t"]), "armed_t": tm["armed_t"],
        "due_at": _ah.iso(tm.get("due_t")), "due_t": tm.get("due_t"),
        "resolution": resolution, "resolved_t": resolved_t,
        "resolved_at": _ah.iso(resolved_t),
    }


def _reconcile_timers(timers: dict[str, dict], attempts: dict[str, dict],
                      t_now: float) -> dict:
    active: list[dict] = []
    overdue: list[dict] = []
    recent: list[dict] = []
    for tm in timers.values():
        due = tm.get("due_t")
        if tm.get("cleared"):
            c = tm["cleared"]
            recent.append(_timer_row(tm, c.get("reason") or "cleared",
                                     c["t"]))
            continue
        owner_att = attempts.get(tm.get("owner_attempt") or "")
        if owner_att is not None and owner_att["ended_t"] is not None:
            recent.append(_timer_row(tm, "cancelled (owner ended)",
                                     owner_att["ended_t"]))
            continue
        alive = _ah.owner_alive(tm.get("owner"))
        if alive is False or (owner_att is not None
                              and owner_att.get("inferred") == "owner-exited"):
            recent.append(_timer_row(tm, "lost (owner process exited)",
                                     None))
            continue
        if due is not None and due <= t_now:
            if tm.get("effect") == "gate":
                recent.append(_timer_row(tm, "elapsed", due))
                continue
            row = _timer_row(tm, "overdue", None)
            row["overdue_s"] = t_now - due
            row["remaining_s"] = 0.0
            overdue.append(row)
            continue
        row = _timer_row(tm, "active", None)
        row["remaining_s"] = None if due is None else due - t_now
        row["owner_alive"] = alive
        row["kind"] = "hold" if due is None else "timer"
        active.append(row)
    active.sort(key=lambda r: (r["due_t"] is None, r["due_t"] or 0))
    return {"active": active, "overdue": overdue, "recent": recent}


def _release_terminal_holds(pr: dict, timer_rows: dict) -> None:
    """Resolve journaled holds a merged/closed PR can no longer be in.

    A PR can merge without passing a hold's release point (``g`` runs ``pm
    pr merge``, GitHub merges arrive via sync), so the hold's owner may
    still be alive with the hold uncleared.
    """
    status = pr.get("status")
    if status not in ("merged", "closed"):
        return
    resolved_t = _parse_iso(pr.get("merged_at")) if status == "merged" \
        else None
    still = []
    for row in timer_rows["active"]:
        if row["due_t"] is None:
            timer_rows["recent"].append(
                _timer_row(row, f"released (PR {status})", resolved_t))
        else:
            still.append(row)
    timer_rows["active"] = still


def _runtime_tracked_attempts(pr_id: str) -> set[str]:
    """Attempt ids of the runtime mirror's in-flight entries (raw state:
    the hook-derived status can relabel an entry but not end it)."""
    try:
        return {e["attempt_id"] for e in _rs.get_pr_actions(pr_id).values()
                if isinstance(e, dict) and e.get("attempt_id")
                and e.get("state") in _rs.IN_FLIGHT_STATES}
    except Exception:
        return set()


def _runtime_actions(pr_id: str) -> dict:
    try:
        out = {}
        for action in _rs.get_pr_actions(pr_id):
            entry = _rs.derive_action_status(pr_id, action)
            if entry:
                out[action] = {k: v for k, v in entry.items()
                               if k in ("state", "verdict", "iteration",
                                        "loop_id", "started_at",
                                        "updated_at", "attempt_id")}
        return out
    except Exception:
        return {}


def _hook_event_for(a: dict) -> dict | None:
    sid = a.get("session_id")
    if not sid and a.get("transcript"):
        try:
            from pm_core.claude_launcher import session_id_from_transcript
            sid = session_id_from_transcript(a["transcript"])
        except Exception:
            sid = None
    if not sid:
        return None
    try:
        from pm_core import hook_events
        return hook_events.read_event(sid)
    except Exception:
        return None


def _attempt_name(a: dict) -> str:
    action = a.get("action") or "?"
    if a.get("scenario") is not None:
        name = f"{action} s{a['scenario']}"
        if a.get("retry"):
            name += f" retry {a['retry']}"
        return name
    if a.get("iteration") is not None and a.get("source") != "runtime":
        return f"{action} i{a['iteration']}"
    if a.get("label") and a.get("label") not in ("QA run", "QA resume"):
        return f"{action} {a['label']}"
    if a.get("loop_id") and action in ("review-loop", "qa"):
        return f"{action} (loop {a['loop_id'][:8]})"
    return action


def _current_activity(attempts: dict[str, dict], timer_rows: dict,
                      t_now: float, *,
                      live: bool) -> list[dict]:
    """One row per open leaf attempt: what is happening right now."""
    out = []
    active_by_owner: dict[str, list[dict]] = {}
    for row in timer_rows["active"] + timer_rows["overdue"]:
        if row.get("owner_attempt"):
            active_by_owner.setdefault(row["owner_attempt"], []).append(row)
    for a in sorted(attempts.values(), key=lambda a: a["started_t"]):
        if not a["open"]:
            continue
        if any(c["open"] for c in a["children"]):
            continue
        last = a["phases"][-1] if a["phases"] else None
        ph = last["phase"] if last else "start"
        since = last["t"] if last else a["started_t"]
        row = {"attempt": a["id"], "name": _attempt_name(a),
               "phase": ph, "since": _ah.iso(since),
               "for_s": t_now - since, "state": None, "text": ""}
        if ph == "agent" or (ph == "start" and a.get("session_id")):
            ev = _hook_event_for(a) if live else None
            ev_t = float((ev or {}).get("timestamp") or 0)
            etype = (ev or {}).get("event_type")
            # An event older than the current phase normally belongs to the
            # previous turn (e.g. before a verification follow-up).  Panes
            # PM merely started watching (runtime attempts) or adopted
            # after a restart keep their session's latest state.
            if not (ev_t >= since or a.get("source") == "runtime"
                    or a.get("adopted")):
                ev = None
            if ev and etype == "idle_prompt":
                grace = _gate_timers(a, active_by_owner)
                row["state"] = "turn_finished"
                row["turn_ended_at"] = _ah.iso(ev_t)
                text = (f"agent turn finished at {_clock(ev_t, t_now)} "
                        f"(idle {_dur(t_now - ev_t)})")
                if grace:
                    row["grace_due_at"] = grace[0]["due_at"]
                    row["grace_remaining_s"] = grace[0]["remaining_s"]
                    text += (f"; verdict grace until "
                             f"{_clock(grace[0]['due_t'], t_now)}")
                elif a.get("action") in ("review-loop", "qa"):
                    text += "; no verdict accepted yet — waiting for the next turn"
                row["text"] = text
            elif ev and etype == "permission_prompt":
                row["state"] = "blocked_on_permission"
                row["text"] = (f"agent waiting on a permission prompt since "
                               f"{_clock(ev_t, t_now)} (needs a human)")
            else:
                row["state"] = "agent_working"
                row["text"] = f"agent working for {_dur(t_now - since)}"
        elif ph == "launching":
            row["state"] = "launching"
            row["text"] = f"launching for {_dur(t_now - since)}"
        elif ph == "verdict":
            row["state"] = "processing_verdict"
            row["text"] = f"processing verdict for {_dur(t_now - since)}"
        elif ph == "waiting_human":
            row["state"] = "waiting_human"
            row["text"] = (f"waiting on a human for {_dur(t_now - since)}"
                           + (f": {last['detail']}" if last and last.get("detail")
                              else ""))
        elif ph in ("queued", "backoff"):
            row["state"] = ph
            row["text"] = (f"{_PHASE_LABELS[ph]} for {_dur(t_now - since)}"
                           + (f": {last['detail']}" if last and last.get("detail")
                              else ""))
        elif ph == "start" and a.get("source") == "runtime" and \
                a.get("action") == "review-loop":
            row["state"] = "between_iterations"
            row["text"] = "loop running; next iteration launching"
        else:
            row["state"] = ph
            row["text"] = f"{_PHASE_LABELS.get(ph, ph)} for {_dur(t_now - since)}"
        if a.get("owner_alive") is None and a.get("owner"):
            row["text"] += " (owner liveness unknown)"
        out.append(row)
    return out


def _gate_timers(a: dict, active_by_owner: dict[str, list[dict]]
                 ) -> list[dict]:
    """Active countdown gates owned by *a* or, failing that, its nearest
    ancestor that has one: the QA verdict grace is shared by all scenarios
    and owned by the run, not by each scenario attempt."""
    node: dict | None = a
    while node is not None:
        gates = [r for r in active_by_owner.get(node["id"], [])
                 if r.get("effect") == "gate" and r.get("due_t")]
        if gates:
            return gates
        node = node.get("_parent_obj")
    return []


def _derived_hold(timer: str, purpose: str, owner_action: str, armed,
                  derived: str, expected: str) -> dict:
    """A hold read from project.yaml / runtime state rather than journaled."""
    return {
        "timer": timer, "kind": "hold", "purpose": purpose,
        "owner_action": owner_action, "armed_at": _iso_norm(armed),
        "armed_t": _parse_iso(armed), "due_at": None, "due_t": None,
        "remaining_s": None, "derived": derived, "expected": expected,
    }


def _derived_holds(pr_id: str, pr: dict, runtime: dict) -> list[dict]:
    holds = []
    sp = pr.get("spec_pending")
    if sp:
        sp = sp if isinstance(sp, dict) else {}
        holds.append(_derived_hold(
            "spec-pending", f"{sp.get('phase') or 'spec'} spec awaiting approval",
            "start", sp.get("generated_at"), "project.yaml spec_pending",
            "pm pr spec-approve (or V in the TUI) resumes"))
    qa = runtime.get("qa") or {}
    if qa.get("state") == "done" and qa.get("verdict") == "INPUT_REQUIRED" \
            and pr.get("status") == "qa":
        holds.append(_derived_hold(
            "qa-input-required",
            "QA INPUT_REQUIRED (auto-start will not relaunch QA)",
            "qa", qa.get("updated_at"), "runtime qa verdict",
            "human resolves the QA scenarios and restarts QA"))
    so = pr.get("signoff") or {}
    if isinstance(so, dict) and so.get("verdict") == "SIGNOFF_BLOCKED" \
            and pr.get("status") == "sign_off":
        holds.append(_derived_hold(
            "signoff-blocked", "sign-off BLOCKED (needs a human decision)",
            "signoff", so.get("ts"), "project.yaml signoff record",
            "human records a new sign-off decision"))
    return holds


_NEEDS_HUMAN_STATES = ("waiting_human", "blocked_on_permission")


def _focus_row(current: list[dict]) -> dict | None:
    """The activity row to headline: one needing a human, else the newest."""
    for row in current:
        if row["state"] in _NEEDS_HUMAN_STATES:
            return row
    return current[-1] if current else None


def _waiting_for(holds, timer_rows, current, attempts) -> str:
    if holds:
        return f"human: {holds[0]['purpose']}"
    for row in timer_rows["overdue"]:
        return (f"{row['purpose']} overdue by {_dur(row['overdue_s'])} "
                f"(owner has not acted)")
    row = _focus_row(current)
    if row is not None and row["state"] in _NEEDS_HUMAN_STATES:
        return f"{row['name']}: {row['text']}"
    fires = [r for r in timer_rows["active"]
             if r.get("effect") == "fires" and r.get("due_t")]
    if fires:
        r = fires[0]
        return (f"{r['purpose']} — {_dur(r['remaining_s'])} left "
                f"→ {r.get('expected') or 'owner acts'}")
    if row is not None:
        return f"{row['name']}: {row['text']}"
    if not attempts:
        return "nothing recorded"
    return "nothing (no open attempts or timers)"


def _milestones(pr: dict) -> list[dict]:
    out = []
    for key, label in (("created_at", "created"), ("started_at", "started"),
                       ("reviewed_at", "review"),
                       ("signed_off_at", "sign-off"),
                       ("merged_at", "merged")):
        v = pr.get(key)
        if v:
            out.append({"event": label, "at": _iso_norm(v),
                        "t": _parse_iso(v), "source": f"project.yaml {key}"})
    return out


def _missing_notes(pr: dict, events: list[dict]) -> list[str]:
    notes = []
    if not events:
        notes.append("No recorded action history for this PR. The journal "
                     "starts with the first action run after history "
                     "recording was added; earlier timing is unknown.")
        return notes
    first = float(events[0].get("t") or 0)
    started = _parse_iso(pr.get("started_at")) or _parse_iso(pr.get("created_at"))
    if started is not None and started < first - 60:
        notes.append(f"Actions before {_clock(first, first)} "
                     f"({_ah.iso(first)}) were not recorded; earlier "
                     "milestones come from project.yaml only.")
    return notes


def _export(a: dict) -> dict:
    keep = ("id", "action", "label", "loop_id", "iteration", "scenario",
            "retry", "parent", "source", "resumed", "adopted", "stale",
            "session_id", "outcome", "verdict", "detail", "inferred",
            "elapsed_s", "elapsed_lower_bound_s", "exec_s", "wait_s",
            "open", "scenarios")
    out = {k: a.get(k) for k in keep if a.get(k) is not None}
    # Timing keys are always present: None means unknown, not omitted.
    for k in ("outcome", "elapsed_s", "elapsed_lower_bound_s", "exec_s",
              "wait_s"):
        out.setdefault(k, None)
    out["name"] = _attempt_name(a)
    out["started_at"] = _ah.iso(a["started_t"])
    out["ended_at"] = _ah.iso(a["ended_t"])
    out["started_t"] = a["started_t"]
    out["ended_t"] = a["ended_t"]
    out["phases"] = [{"phase": s["phase"], "start_at": _ah.iso(s["start_t"]),
                      "end_at": _ah.iso(s["end_t"]),
                      "duration_s": s["end_t"] - s["start_t"],
                      "detail": s.get("detail"), "open": s["open"]}
                     for s in a.get("spans", [])]
    out["children"] = [_export(c) for c in
                       sorted(a["children"], key=lambda c: c["started_t"])]
    return out


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _parse_iso(v) -> float | None:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _iso_norm(v) -> str | None:
    t = _parse_iso(v)
    return _ah.iso(t) if t is not None else None


def _dur(s: float | None) -> str:
    if s is None:
        return "unknown"
    s = max(0, int(round(s)))
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m}m{sec:02d}s"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h}h{m:02d}m"
    d, h = divmod(h, 24)
    return f"{d}d{h:02d}h"


def _clock(t: float | None, t_now: float) -> str:
    if t is None:
        return "unknown"
    lt = datetime.fromtimestamp(t)
    if lt.date() == datetime.fromtimestamp(t_now).date():
        return lt.strftime("%H:%M:%S")
    return lt.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------

def render_text(model: dict, *, now: float | None = None) -> list[str]:
    """Render :func:`build_history`'s model as plain text lines."""
    t_now = _parse_iso(model.get("generated_at")) if now is None else now
    if t_now is None:
        t_now = _ah.now()
    lines: list[str] = []
    head = f"History — {model['display_id']}"
    if model["display_id"] != model["pr_id"]:
        head += f" ({model['pr_id']})"
    if model.get("status"):
        head += f"  [{model['status']}]"
    lines.append(head)
    if model.get("title"):
        lines.append(f"  {model['title']}")
    lines.append(f"Waiting for: {model['waiting_for']}")

    lines.append("")
    lines.append("Now")
    if model["current"]:
        for row in model["current"]:
            lines.append(f"  {row['name']:<18} {row['text']}")
    else:
        lines.append("  no action running")
    runtime = model.get("runtime") or {}
    if runtime:
        bits = []
        for action in sorted(runtime, key=_action_key):
            e = runtime[action]
            bit = f"{action}={e.get('state')}"
            if e.get("verdict"):
                # An in-flight entry keeps the previous iteration's/run's
                # verdict until the next one lands; don't pair it with
                # "running" as if it were this run's outcome.
                in_flight = e.get("state") in _rs.IN_FLIGHT_STATES
                bit += (f" (last {e['verdict']})" if in_flight
                        else f" {e['verdict']}")
            if e.get("stale"):
                bit += f" (stale: {e['stale']})"
            bits.append(bit)
        lines.append("  runtime: " + ", ".join(bits))

    lines.append("")
    lines.append("Timers and holds")
    rows = (model["holds"] + model["timers"]["active"]
            + model["timers"]["overdue"])
    if not rows:
        lines.append("  none active")
    for r in rows:
        lines.extend(_render_timer(r, t_now))

    lines.append("")
    lines.append("Attempts (newest first)")
    if not model["attempts"]:
        lines.append("  none recorded")
    for a in model["attempts"]:
        lines.extend(_render_attempt(a, t_now, depth=1))

    recent = model["timers"]["recent"]
    if recent:
        lines.append("")
        lines.append("Recent timers")
        for r in recent[:10]:
            when = (_clock(r["resolved_t"], t_now)
                    if r.get("resolved_t") else "unknown")
            line = f"  {r['purpose']}: {r['resolution']} at {when}"
            armed = f"(armed {_clock(r['armed_t'], t_now)})"
            if len(line) + 1 + len(armed) <= 80:
                lines.append(f"{line} {armed}")
            else:
                lines.extend([line, f"      {armed}"])

    if model["milestones"]:
        lines.append("")
        lines.append("Milestones (project.yaml)")
        lines.append("  " + "   ".join(
            f"{m['event']} {_clock(m['t'], t_now)}" for m in model["milestones"]
            if m.get("t") is not None))

    if model["missing"]:
        lines.append("")
        for note in model["missing"]:
            lines.append(f"Note: {note}")
    return lines


def _action_key(action: str):
    try:
        return (_ACTION_ORDER.index(action), action)
    except ValueError:
        return (len(_ACTION_ORDER), action)


def _render_timer(r: dict, t_now: float) -> list[str]:
    armed = _clock(r.get("armed_t"), t_now) if r.get("armed_t") else "unknown"
    if r.get("due_t") is None:
        timing = f"armed {armed}, no countdown"
    elif r.get("resolution") == "overdue":
        timing = (f"armed {armed}, due {_clock(r['due_t'], t_now)}, "
                  f"overdue by {_dur(r.get('overdue_s'))}")
    else:
        timing = (f"armed {armed}, due {_clock(r['due_t'], t_now)}, "
                  f"{_dur(r.get('remaining_s'))} left")
    owner = r.get("owner_action") or "?"
    src = f" [{r['derived']}]" if r.get("derived") else ""
    out = [f"  {r.get('purpose')} ({owner}){src}", f"      {timing}"]
    if r.get("expected"):
        out.append(f"      → {r['expected']}")
    return out


def _render_attempt(a: dict, t_now: float, depth: int) -> list[str]:
    ind = "  " * depth
    start = _clock(a["started_t"], t_now)
    if a.get("ended_t") is not None:
        end = _clock(a["ended_t"], t_now)
    elif a.get("open"):
        end = "now"
    else:
        end = "unknown"
    if a.get("elapsed_s") is not None:
        dur = _dur(a["elapsed_s"])
    elif (a.get("elapsed_lower_bound_s") or 0) >= 1:
        dur = f">{_dur(a['elapsed_lower_bound_s'])}"
    else:
        dur = "unknown"
    outcome = a.get("outcome") or ("running" if a.get("open") else "unknown")
    if a.get("verdict"):
        outcome += f" {a['verdict']}"
    name = a["name"]
    flags = [f for f in ("resumed", "adopted", "stale") if a.get(f)]
    if flags:
        name += f" ({', '.join(flags)})"
    line = f"{ind}{start} → {end}  {dur:>7}  {name}  {outcome}"
    out = [line]
    sub = ind + "    "
    if a.get("detail") and outcome.split()[0] != "done":
        out.append(f"{sub}{a['detail']}")
    phases = [p for p in a.get("phases", []) if p["phase"] != "start"]
    if phases and a.get("exec_s") is not None:
        split = f"exec {_dur(a['exec_s'])}"
        if a.get("wait_s"):
            split += f", wait {_dur(a['wait_s'])}"
        parts = [f"{_PHASE_LABELS.get(p['phase'], p['phase'])} "
                 f"{_dur(p['duration_s'])}" for p in a["phases"]]
        out.extend(_wrap_phases(f"{sub}{split}  [", parts, sub + "  "))
    sc = a.get("scenarios")
    if sc and sc["sum_s"] >= 1:
        out.append(f"{sub}scenarios: {sc['count']} ({sc['attempts']} attempts), "
                   f"wall {_dur(sc['wall_s'])}, up to {sc['max_concurrency']} "
                   f"at once")
        out.append(f"{sub}  summed scenario time {_dur(sc['sum_s'])} "
                   f"(not wall-clock)")
    for c in a.get("children", []):
        out.extend(_render_attempt(c, t_now, depth + 1))
    return out


def _wrap_phases(head: str, parts: list[str], cont: str,
                 width: int = 80) -> list[str]:
    """``head`` + ``parts`` joined by `` · `` and closed with ``]``,
    wrapped at *width* with continuation lines indented by *cont*."""
    lines: list[str] = []
    cur = head
    for i, part in enumerate(parts):
        piece = part + ("]" if i == len(parts) - 1 else " ·")
        sep = "" if cur in (head, cont) else " "
        if cur not in (head, cont) and len(cur) + 1 + len(piece) > width:
            lines.append(cur)
            cur, sep = cont, ""
        cur += sep + piece
    lines.append(cur)
    return lines


_BADGE_STATES = {
    "turn_finished": "turn done",
    "agent_working": "working",
    "processing_verdict": "verdict",
    "launching": "launching",
    "waiting_human": "needs human",
    "blocked_on_permission": "permission prompt",
    "queued": "queued",
    "backoff": "backoff",
    "between_iterations": "next launch",
}


def summary_badge(model: dict, width: int = 36) -> str:
    """Short status for the History row in the actions pane."""
    if model.get("holds"):
        text = "hold: " + (model["holds"][0].get("purpose") or "")
    elif model["timers"].get("overdue"):
        text = "overdue: " + (model["timers"]["overdue"][0].get("purpose") or "")
    elif model.get("current"):
        row = _focus_row(model["current"])
        text = f"{row['name']}: {_BADGE_STATES.get(row['state'], row['state'])}"
        left = [t["remaining_s"] for t in model["timers"]["active"]
                if t.get("owner_attempt") == row["attempt"]
                and t.get("remaining_s") is not None]
        if not left and row.get("grace_remaining_s") is not None:
            left = [row["grace_remaining_s"]]  # inherited shared grace
        if left:
            text += f", {_dur(left[0])} left"
    elif model.get("attempts"):
        n = len(model["attempts"])
        return f" [{n} run{'s' if n != 1 else ''}]"
    else:
        return " [no history]"
    if len(text) > width:
        text = text[:width - 1] + "…"
    return f" [{text}]"
