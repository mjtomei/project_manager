"""Reader-side API for Claude Code hook events written by hook_receiver.

Hook events are keyed by Claude session_id; pm consumers wait on the
event file's mtime to learn when Claude has finished a turn
(idle_prompt) or stopped. Much lighter than polling pane content.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from pm_core.paths import configure_logger

_log = configure_logger("pm.hook_events")

_HOOKS_DIR = Path.home() / ".pm" / "hooks"
_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


def hooks_dir() -> Path:
    return _HOOKS_DIR


def event_path(session_id: str) -> Path:
    return _HOOKS_DIR / f"{session_id}.json"


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
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    # Look for our marker in any configured hook command
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            for hook in (entry or {}).get("hooks", []) or []:
                cmd = (hook or {}).get("command", "")
                if "pm_core.hook_receiver" in cmd:
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
