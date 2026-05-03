"""Reader-side API for Claude Code hook events written by hook_receiver.

Hook events are keyed by Claude session_id; pm consumers wait on the
event file's mtime to learn when Claude has finished a turn
(idle_prompt) or stopped. Much lighter than polling pane content.

Events live in a flat directory ``~/.pm/hooks/{session_id}.json`` —
UUID session_ids prevent collision across concurrent pm sessions, and
a flat layout guarantees the writer (which may run inside a container
with cwd=/workspace) and the reader (on the host) agree on the path.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from pm_core.paths import configure_logger

_log = configure_logger("pm.hook_events")

_HOOKS_BASE = Path.home() / ".pm" / "hooks"
_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


def hooks_dir() -> Path:
    return _HOOKS_BASE


def event_path(session_id: str) -> Path:
    return _HOOKS_BASE / f"{session_id}.json"


def read_event(session_id: str) -> dict | None:
    path = event_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def clear_event(session_id: str) -> None:
    path = event_path(session_id)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        _log.debug("clear_event: failed to remove %s", path)


def hooks_available() -> bool:
    """Return True if ~/.claude/settings.json has pm hooks installed."""
    if not _SETTINGS_PATH.exists():
        return False
    try:
        data = json.loads(_SETTINGS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            for hook in (entry or {}).get("hooks", []) or []:
                cmd = (hook or {}).get("command", "")
                # Recognise both the current standalone-receiver form
                # (``python3 /.../.pm/hook_receiver.py ...``) and the
                # legacy ``-m pm_core.hook_receiver`` form.
                if "hook_receiver" in cmd:
                    return True
    return False


def wait_for_event(
    session_id: str,
    event_types: set[str],
    timeout: float,
    newer_than: float = 0.0,
    tick: float = 0.2,
    stop_check: Callable[[], bool] | None = None,
) -> dict | None:
    """Wait up to *timeout* seconds for a matching hook event.

    Returns the event dict when one is found with:
      - event_type in *event_types*
      - timestamp > newer_than

    Returns None on timeout or when stop_check() returns True.
    """
    deadline = time.monotonic() + max(0.0, timeout)
    path = event_path(session_id)
    while True:
        if stop_check and stop_check():
            return None
        try:
            if path.exists():
                data = read_event(session_id)
                if data and data.get("event_type") in event_types:
                    ts = float(data.get("timestamp") or 0)
                    if ts > newer_than:
                        return data
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(tick)
