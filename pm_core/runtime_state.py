"""Shared on-disk runtime state for PR actions.

Both the TUI process and short-lived CLI/popup processes need to know
what each action (start, review, review-loop, qa, etc.) is doing for a
given PR.  In-process state (``app._review_loops``, ``PaneIdleTracker``)
is the source of truth; this module mirrors transitions to per-PR JSON
files so external readers (popup picker, status spinner after a queued
``tui:`` command, etc.) can observe them.

Storage layout: ``~/.pm/runtime/{pr_id}.json`` — one file per PR keeps
writes localized and avoids whole-file lock contention.

Schema (v1)::

    {
      "pr_id": "pr-2d0588a",
      "actions": {
        "review-loop": {
          "state": "running",
          "started_at": "2026-05-03T18:00:00Z",
          "updated_at": "2026-05-03T18:01:23Z",
          "iteration": 3,
          "loop_id": "abcd1234"
        },
        "start": {
          "state": "running",
          "pane_id": "%42",
          "session_id": "..."
        }
      }
    }

Valid ``state`` values:

* ``queued``    — externally enqueued, TUI hasn't picked it up yet
* ``launching`` — TUI is starting the action's pane
* ``running``   — pane / loop is alive and active
* ``idle``      — pane alive, Claude turn ended (idle_prompt fired)
* ``waiting``   — pane alive, Claude blocked on permission_prompt
* ``done``      — finished cleanly
* ``failed``    — error during launch / execution

Pane disappearances and stale-entry sweeps clear the entry entirely
rather than recording an explicit "gone" state — the live tmux window
list and pane-existence checks are the authoritative liveness signals.

Writers should call :func:`set_action_state` for every transition; the
function takes a flock around the read-modify-write so concurrent
writers (e.g. background loop iteration vs. main-thread TUI command)
don't lose updates.
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pm_core.paths import configure_logger, pm_home

_log = configure_logger("pm.runtime_state")

VALID_STATES = {
    "queued", "launching", "running", "idle", "waiting",
    "done", "failed",
}


def _runtime_dir() -> Path:
    d = pm_home() / "runtime"
    d.mkdir(parents=True, exist_ok=True)
    return d


def runtime_path(pr_id: str) -> Path:
    safe = pr_id.replace("/", "_").replace("\\", "_")
    return _runtime_dir() / f"{safe}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_locked(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return json.loads(f.read() or "{}")
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except (OSError, json.JSONDecodeError) as e:
        _log.debug("runtime_state: read %s failed: %s", path, e)
        return {}


def get_pr_actions(pr_id: str) -> dict[str, dict]:
    data = _read_locked(runtime_path(pr_id))
    actions = data.get("actions")
    return actions if isinstance(actions, dict) else {}


def get_action_state(pr_id: str, action: str) -> dict:
    return get_pr_actions(pr_id).get(action, {}) or {}


IN_FLIGHT_STATES = {"queued", "launching", "running", "idle", "waiting"}

# Actions whose attempts are journaled by their owner rather than derived
# from runtime transitions: the ``qa`` entry is driven by per-scenario pane
# registration, so a derived attempt would start at the first scenario
# pane instead of at planning (``qa_loop`` journals the run itself).
_UNJOURNALED_ACTIONS = {"qa"}


def _pane_alive(pane_id: str | None) -> bool:
    if not pane_id:
        return False
    try:
        from pm_core import tmux as tmux_mod
        return bool(tmux_mod.pane_exists(pane_id))
    except Exception:
        return False


def _journal_transition(pr_id: str, action: str, cur: dict,
                        state: str | None, extras: dict, clearing: bool,
                        history_outcome: str | None,
                        history_reason: str | None) -> None:
    """Mirror one runtime transition into the action-history journal.

    Called under the runtime file's lock so concurrent writers agree on
    a single attempt id, which is stored in the entry as ``attempt_id``.
    Mutates *cur* (the entry about to be written) only to set/drop that
    field.  Never raises.
    """
    if action in _UNJOURNALED_ACTIONS:
        return
    try:
        from pm_core import action_history as _ah
        prior = cur.get("state")
        prior_attempt = cur.get("attempt_id")
        in_flight = prior in IN_FLIGHT_STATES and bool(prior_attempt)
        if clearing:
            if in_flight:
                if history_reason:
                    _ah.end_attempt(pr_id, prior_attempt, "interrupted",
                                    detail=history_reason)
                elif _pane_alive(cur.get("pane_id")):
                    # The pane still exists; PM merely stopped watching it
                    # (e.g. the PR moved on to review).
                    _ah.end_attempt(
                        pr_id, prior_attempt, "untracked",
                        detail="pane still open; PM stopped tracking it")
                else:
                    _ah.end_attempt(
                        pr_id, prior_attempt, "vanished",
                        detail="pane gone or no longer tracked")
            return
        if state in ("queued", "launching", "running"):
            def _identity(d: dict) -> str | None:
                return d.get("loop_id") or d.get("session_id")
            new_ident = _identity(extras) if extras else None
            old_ident = _identity(cur)
            if in_flight and not (new_ident and old_ident
                                  and new_ident != old_ident):
                return  # same attempt, still going
            if in_flight:
                _ah.end_attempt(pr_id, prior_attempt, "superseded",
                                detail="replaced by a new run")
            fields = {k: extras.get(k) for k in
                      ("loop_id", "session_id", "pane_id")
                      if extras.get(k) is not None}
            cur["attempt_id"] = _ah.start_attempt(pr_id, action,
                                                  source="runtime", **fields)
        elif state in ("done", "failed"):
            if in_flight:
                _ah.end_attempt(pr_id, prior_attempt,
                                history_outcome or state,
                                verdict=extras.get("verdict"),
                                iteration=extras.get("iteration"))
    except Exception:
        _log.debug("runtime_state: journal %s/%s failed", pr_id, action,
                   exc_info=True)


def set_action_state(pr_id: str, action: str, state: str | None,
                     *, history_outcome: str | None = None,
                     history_reason: str | None = None,
                     **extras: Any) -> None:
    """Record an action transition.

    Pass ``state=None`` together with no extras to clear the action
    entry.  Extra fields are merged into the action dict; pass
    ``None`` for a field to drop it from the persisted dict.

    Transitions are also journaled as action attempts
    (:mod:`pm_core.action_history`).  *history_outcome* overrides the
    recorded outcome of a ``done``/``failed`` transition (e.g.
    ``cancelled``); *history_reason* marks a clear as an interruption
    (e.g. a TUI-restart sweep) rather than a vanished pane.
    """
    if state is not None and state not in VALID_STATES:
        _log.warning("runtime_state: unknown state %r for %s/%s",
                     state, pr_id, action)
    path = runtime_path(pr_id)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    prior_state_for_log: str | None = None
    new_state_for_log: str | None = None
    try:
        with os.fdopen(fd, "r+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.seek(0)
                raw = f.read()
                data = json.loads(raw) if raw else {}
                if not isinstance(data, dict):
                    data = {}
                data["pr_id"] = pr_id
                actions = data.setdefault("actions", {})
                if not isinstance(actions, dict):
                    actions = {}
                    data["actions"] = actions
                if state is None and not extras:
                    prior_state_for_log = (actions.get(action) or {}).get("state")
                    prior_entry = actions.get(action)
                    if isinstance(prior_entry, dict):
                        _journal_transition(pr_id, action, prior_entry,
                                            None, {}, True, history_outcome,
                                            history_reason)
                    actions.pop(action, None)
                else:
                    cur = actions.get(action) or {}
                    if not isinstance(cur, dict):
                        cur = {}
                    prior_state_for_log = cur.get("state")
                    if state is not None:
                        _journal_transition(pr_id, action, cur, state,
                                            extras, False, history_outcome,
                                            history_reason)
                        prior_state = cur.get("state")
                        # A fresh launch of this action invalidates any
                        # suppress_switch flag set by a prior, now-orphaned
                        # invocation: the flag's meaning is "the user
                        # dismissed the *current* invocation's popup", and
                        # a new invocation has just begun. Detect by
                        # transitioning into launching/running from a state
                        # other than launching/running.
                        if (state in ("launching", "running")
                                and prior_state not in ("launching", "running")
                                and "suppress_switch" not in extras
                                and cur.get("suppress_switch")):
                            cur.pop("suppress_switch", None)
                        cur["state"] = state
                        new_state_for_log = state
                        cur.setdefault("started_at", _now_iso())
                    for k, v in extras.items():
                        if v is None:
                            cur.pop(k, None)
                        else:
                            cur[k] = v
                    # Drop the action entry entirely when the resulting
                    # dict carries no meaningful fields — e.g. a bare
                    # consume_suppress_switch on a never-recorded action
                    # would otherwise leave an empty {updated_at} stub.
                    meaningful = {k for k in cur
                                  if k not in ("updated_at", "started_at")}
                    if state is None and not meaningful:
                        actions.pop(action, None)
                    else:
                        cur["updated_at"] = _now_iso()
                        actions[action] = cur
                f.seek(0)
                f.truncate()
                json.dump(data, f, indent=2, sort_keys=True)
                # Flush Python's buffer to the kernel *before* releasing
                # the lock so a reader that grabs LOCK_SH the moment we
                # release sees the new bytes, not whatever was on disk
                # from the previous write.
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError as e:
        _log.debug("runtime_state: write %s failed: %s", path, e)
        return
    # Log only genuine transitions: state actually changed.  Skip no-op
    # writes (e.g. consume_suppress_switch on a missing entry, repeat
    # 'running' heartbeats) so the log stays signal-rich.
    if state is not None and new_state_for_log != prior_state_for_log:
        verdict = extras.get("verdict") if extras else None
        _log.info(
            "set_action_state: pr=%s action=%s from=%s to=%s verdict=%s",
            pr_id, action, prior_state_for_log, new_state_for_log, verdict,
        )
    # Kick the home window on any real transition (or on entry/exit),
    # not on no-op heartbeat writes. Hash-diff in the home loop makes
    # a redundant kick free, but skipping the no-ops keeps log noise
    # down and avoids waking the loop for nothing.
    if (state is None and prior_state_for_log is not None) or (
            state is not None and new_state_for_log != prior_state_for_log):
        try:
            from pm_core.home_window import refresh_home
            refresh_home()
        except Exception:
            _log.debug("set_action_state: refresh_home failed",
                       exc_info=True)


def clear_action(pr_id: str, action: str, *,
                 history_reason: str | None = None) -> None:
    set_action_state(pr_id, action, None, history_reason=history_reason)


def sweep_stale_states(reason: str = "tui-restart") -> int:
    """Reset any in-flight action states across all PRs.

    Called by the TUI on mount: a fresh TUI process can't own panes or
    loops recorded by a previous one, so leaving entries at
    ``running``/``launching``/``queued``/``idle``/``waiting`` would
    cause the picker to display loops and idle indicators that don't
    correspond to anything live.  We delete such entries entirely.
    Terminal states (``done`` / ``failed``) are left untouched so
    post-mortem info — e.g. last review-loop verdict — survives restart.

    Returns the number of action entries that were cleared.
    """
    runtime_dir = _runtime_dir()
    swept = 0
    try:
        files = list(runtime_dir.iterdir())
    except OSError:
        return 0
    for path in files:
        if not path.is_file() or path.suffix != ".json":
            continue
        try:
            data = _read_locked(path)
        except Exception:
            continue
        actions = data.get("actions") or {}
        if not isinstance(actions, dict):
            continue
        targets = [a for a, e in actions.items()
                   if isinstance(e, dict)
                   and e.get("state") in IN_FLIGHT_STATES]
        if not targets:
            continue
        pr_id = data.get("pr_id") or path.stem
        for action in targets:
            try:
                clear_action(pr_id, action,
                             history_reason=f"swept on {reason}")
                swept += 1
            except Exception:
                _log.debug("runtime_state: sweep failed for %s/%s",
                           pr_id, action, exc_info=True)
    if swept:
        _log.info("runtime_state: swept %d stale entries (%s)",
                  swept, reason)
    return swept


def request_suppress_switch(pr_id: str, action: str) -> None:
    """Mark *(pr_id, action)*'s pending TUI window-switch as cancelled.

    Used when the user dismisses the popup spinner with q/Esc — the
    queued command continues to run but the TUI should not steal focus
    to the action's window.  Writing only the flag (state=None, extras
    set) leaves any other recorded fields alone.
    """
    set_action_state(pr_id, action, None, suppress_switch=True)


def consume_suppress_switch(pr_id: str, action: str) -> bool:
    """Read and atomically clear the suppress-switch flag.

    Returns True when the flag was set (and is now cleared); the
    caller should skip its window-switch.  Returns False when no flag
    was present, in which case the caller proceeds normally.
    """
    entry = get_action_state(pr_id, action)
    if not entry.get("suppress_switch"):
        return False
    set_action_state(pr_id, action, None, suppress_switch=None)
    _log.info("consume_suppress_switch: pr=%s action=%s consumed=True",
              pr_id, action)
    return True


def _hook_state_for(session_id: str) -> str | None:
    """Return ``idle``/``waiting`` for the latest hook event, or None."""
    if not session_id:
        return None
    try:
        from pm_core import hook_events
        ev = hook_events.read_event(session_id)
    except Exception:
        return None
    if not ev:
        return None
    etype = ev.get("event_type")
    if etype == "idle_prompt":
        return "idle"
    if etype == "permission_prompt":
        return "waiting"
    return None


def derive_action_status(pr_id: str, action: str) -> dict:
    """Combine the persisted entry with the latest hook event.

    For pane-backed actions (``start``, ``review``, ``merge``) the
    persisted entry records ``session_id``; we cross-reference
    :func:`pm_core.hook_events.read_event` so callers see fresh
    idle/waiting state without the writer having to record every hook
    transition.

    QA is special: the entry holds a ``panes`` dict keyed by scenario
    subkey (e.g. ``s1``), each value containing its own ``session_id``.
    We aggregate the worst state across all live scenarios so the
    picker shows [working] when *any* scenario is active and only
    flips to [idle] when *all* scenarios have gone idle.  Terminal
    entries (``state=done`` with a ``verdict``) are returned as-is so
    the [done VERDICT] badge survives picker invocations.
    """
    entry = dict(get_action_state(pr_id, action))
    if not entry:
        return {}
    if action == "qa":
        if entry.get("state") == "done" and entry.get("verdict"):
            return entry
        panes = entry.get("panes") or {}
        if not panes:
            return entry
        # Worst-state aggregation: any working ⇒ working; else any
        # waiting ⇒ waiting; else if everyone idle ⇒ idle.
        any_working = False
        any_waiting = False
        any_idle = False
        for p in panes.values():
            if not isinstance(p, dict):
                continue
            sub = _hook_state_for(p.get("session_id", ""))
            if sub == "idle":
                any_idle = True
            elif sub == "waiting":
                any_waiting = True
            else:
                # No event yet, or non-idle/non-waiting event — treat as
                # active.  The pane is registered (we wouldn't have a
                # session_id otherwise) and we have no positive idle/
                # waiting signal, so default to running.
                any_working = True
        if any_working:
            entry["state"] = "running"
        elif any_waiting:
            entry["state"] = "waiting"
        elif any_idle:
            entry["state"] = "idle"
        return entry
    sub = _hook_state_for(entry.get("session_id", ""))
    if sub:
        entry["state"] = sub
    return entry
