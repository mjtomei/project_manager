"""Pane registry file I/O.

Manages the per-session JSON registry that tracks pm-created tmux panes.
Each session has a registry file in ~/.pm/pane-registry/<session>.json
containing pane IDs, roles, and ordering information.
"""

import json
import logging
from pathlib import Path

from pm_core.paths import configure_logger

_logger = configure_logger("pm.pane_registry")


def _ensure_logging():
    """No-op for backward compatibility. Logging is now auto-configured."""
    pass


def base_session_name(session: str) -> str:
    """Strip grouped-session suffix (~N) to get the base session name."""
    return session.split("~")[0]


def registry_dir() -> Path:
    """Return the directory for pane registry files."""
    from pm_core.paths import pane_registry_dir
    return pane_registry_dir()


def registry_path(session: str) -> Path:
    """Return the registry file path for a session."""
    return registry_dir() / f"{base_session_name(session)}.json"


def load_registry(session: str) -> dict:
    """Load the pane registry for a session."""
    path = registry_path(session)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, ValueError):
            pass
    return {"session": session, "window": "0", "panes": [], "user_modified": False}


def save_registry(session: str, data: dict) -> None:
    """Save the pane registry for a session."""
    registry_path(session).write_text(json.dumps(data, indent=2) + "\n")


def register_pane(session: str, window: str, pane_id: str, role: str, cmd: str) -> None:
    """Register a new pane in the registry."""
    _ensure_logging()
    data = load_registry(session)
    data["window"] = window
    order = max((p["order"] for p in data["panes"]), default=-1) + 1
    data["panes"].append({
        "id": pane_id,
        "role": role,
        "order": order,
        "cmd": cmd,
    })
    save_registry(session, data)
    _logger.info("register_pane: %s role=%s order=%d (total=%d)",
                 pane_id, role, order, len(data["panes"]))


def unregister_pane(session: str, pane_id: str) -> None:
    """Remove a pane from the registry."""
    _ensure_logging()
    data = load_registry(session)
    before = len(data["panes"])
    data["panes"] = [p for p in data["panes"] if p["id"] != pane_id]
    after = len(data["panes"])
    save_registry(session, data)
    _logger.info("unregister_pane: %s removed=%s (before=%d after=%d)",
                 pane_id, before != after, before, after)


def find_live_pane_by_role(session: str, role: str) -> str | None:
    """Find a live pane with the given role, or None if not found.

    Checks both the registry and tmux to ensure the pane actually exists.
    Returns the pane ID if found and alive, None otherwise.
    """
    _ensure_logging()
    from pm_core import tmux as tmux_mod

    data = load_registry(session)
    window = data.get("window", "0")
    _logger.debug("find_live_pane_by_role: session=%s window=%s role=%s", session, window, role)

    # Find pane with this role in registry
    for pane in data.get("panes", []):
        if pane.get("role") == role:
            pane_id = pane.get("id")
            if pane_id:
                # Check if pane is actually alive in tmux (use window from registry)
                live_panes = tmux_mod.get_pane_indices(session, window)
                live_ids = {p[0] for p in live_panes}
                _logger.debug("find_live_pane_by_role: live_ids=%s, checking %s", live_ids, pane_id)
                if pane_id in live_ids:
                    _logger.info("find_live_pane_by_role: %s -> %s (alive)", role, pane_id)
                    return pane_id
                else:
                    _logger.info("find_live_pane_by_role: %s -> %s (dead)", role, pane_id)
    _logger.info("find_live_pane_by_role: %s -> None", role)
    return None


def _reconcile_registry(session: str, window: str,
                        query_session: str | None = None) -> list[str]:
    """Remove registry panes that no longer exist in tmux. Returns removed IDs."""
    _ensure_logging()
    from pm_core import tmux as tmux_mod

    qs = query_session or session
    data = load_registry(session)
    # Always use the registry's window, not the caller's — the caller may
    # have a stale window ID from an old session.
    reg_window = data.get("window", window)
    live_panes = tmux_mod.get_pane_indices(qs, reg_window)
    live_ids = {pid for pid, _ in live_panes}

    # If we got zero live panes but the registry has panes, the window
    # probably doesn't exist (session was killed). Don't wipe the registry.
    if not live_ids and data["panes"]:
        _logger.info("reconcile: no live panes found for %s:%s, skipping "
                     "(window may not exist)", session, reg_window)
        return []

    removed = []
    surviving = []
    for p in data["panes"]:
        if p["id"] in live_ids:
            surviving.append(p)
        else:
            removed.append(p["id"])

    if removed:
        data["panes"] = surviving
        save_registry(session, data)
        _logger.info("reconcile: removed dead panes %s, %d remaining",
                     removed, len(surviving))
    else:
        _logger.debug("reconcile: all %d registry panes still alive", len(data["panes"]))

    return removed
