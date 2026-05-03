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
* ``gone``      — pane disappeared / loop stopped without explicit done

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
    "done", "failed", "gone",
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
                    cur["updated_at"] = _now_iso()
                    for k, v in extras.items():
                        if v is None:
                            cur.pop(k, None)
                        else:
                            cur[k] = v
                    actions[action] = cur
                f.seek(0)
                f.truncate()
                json.dump(data, f, indent=2, sort_keys=True)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError as e:
        _log.debug("runtime_state: write %s failed: %s", path, e)


def clear_action(pr_id: str, action: str) -> None:
    set_action_state(pr_id, action, None)


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


def derive_action_status(pr_id: str, action: str) -> dict:
    """Combine the persisted entry with the latest hook event.

    For pane-backed actions (``start``, ``qa``) the persisted entry
    records ``session_id``; we cross-reference
    :func:`pm_core.hook_events.read_event` so callers see fresh
    idle/waiting state without the writer having to record every hook
    transition.
    """
    entry = dict(get_action_state(pr_id, action))
    if not entry:
        return {}
    sid = entry.get("session_id")
    if sid:
        try:
            from pm_core import hook_events
            ev = hook_events.read_event(sid)
        except Exception:
            ev = None
        if ev:
            etype = ev.get("event_type")
            if etype == "idle_prompt":
                entry["state"] = "idle"
            elif etype == "permission_prompt":
                entry["state"] = "waiting"
    return entry
