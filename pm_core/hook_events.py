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

_HOOKS_BASE = Path.home() / ".pm" / "hooks"
_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


def _current_session_tag() -> str | None:
    try:
        from pm_core.paths import get_session_tag
        return get_session_tag(use_github_name=False)
    except Exception:
        return None


def hooks_dir(session_tag: str | None = None) -> Path:
    tag = session_tag or _current_session_tag()
    return _HOOKS_BASE / tag if tag else _HOOKS_BASE / "_notag"


def event_path(session_id: str, session_tag: str | None = None) -> Path:
    return hooks_dir(session_tag) / f"{session_id}.json"


def read_event(session_id: str, session_tag: str | None = None) -> dict | None:
    path = event_path(session_id, session_tag)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def clear_event(session_id: str, session_tag: str | None = None) -> None:
    path = event_path(session_id, session_tag)
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
    session_tag: str | None = None,
) -> dict | None:
    """Wait up to *timeout* seconds for a matching hook event.

    Returns the event dict when one is found with:
      - event_type in *event_types*
      - timestamp > newer_than

    Returns None on timeout or when stop_check() returns True.
    """
    deadline = time.monotonic() + max(0.0, timeout)
    path = event_path(session_id, session_tag)
    while True:
        if stop_check and stop_check():
            return None
        try:
            if path.exists():
                data = read_event(session_id, session_tag)
                if data and data.get("event_type") in event_types:
                    ts = float(data.get("timestamp") or 0)
                    if ts > newer_than:
                        return data
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(tick)
