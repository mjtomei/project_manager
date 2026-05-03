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


def set_action_state(pr_id: str, action: str, state: str | None,
                     **extras: Any) -> None:
    """Record an action transition.

    Pass ``state=None`` together with no extras to clear the action
    entry.  Extra fields are merged into the action dict; pass
    ``None`` for a field to drop it from the persisted dict.
    """
    if state is not None and state not in VALID_STATES:
        _log.warning("runtime_state: unknown state %r for %s/%s",
                     state, pr_id, action)
    path = runtime_path(pr_id)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
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
                    actions.pop(action, None)
                else:
                    cur = actions.get(action) or {}
                    if not isinstance(cur, dict):
                        cur = {}
                    if state is not None:
                        cur["state"] = state
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


def clear_action(pr_id: str, action: str) -> None:
    set_action_state(pr_id, action, None)


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
    in_flight = {"queued", "launching", "running", "idle", "waiting"}
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
                   if isinstance(e, dict) and e.get("state") in in_flight]
        if not targets:
            continue
        pr_id = data.get("pr_id") or path.stem
        for action in targets:
            try:
                clear_action(pr_id, action)
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
