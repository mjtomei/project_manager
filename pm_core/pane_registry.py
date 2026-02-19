"""Pane registry file I/O.

Manages the per-session JSON registry that tracks pm-created tmux panes.
Each session has a registry file in ~/.pm/pane-registry/<session>.json
containing per-window pane IDs, roles, and ordering information.
"""

import json
import subprocess
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


def _get_window_data(data: dict, window: str) -> dict:
    """Return the window entry for *window*, creating it if absent."""
    windows = data.setdefault("windows", {})
    if window not in windows:
        windows[window] = {"panes": [], "user_modified": False}
    return windows[window]


def _iter_all_panes(data: dict):
    """Yield ``(window_id, pane_dict)`` across every window in the registry."""
    for window_id, wdata in data.get("windows", {}).items():
        for pane in wdata.get("panes", []):
            yield window_id, pane


def load_registry(session: str) -> dict:
    """Load the pane registry for a session.

    Automatically migrates the old single-window format to the new
    multi-window format on read.
    """
    path = registry_path(session)
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, ValueError):
            data = None
        if data is not None:
            # Migrate old flat format → multi-window
            if "panes" in data and "windows" not in data:
                window = data.pop("window", "0")
                panes = data.pop("panes", [])
                user_modified = data.pop("user_modified", False)
                data["windows"] = {
                    window: {"panes": panes, "user_modified": user_modified},
                }
            return data
    return {"session": session, "windows": {}, "generation": ""}


def save_registry(session: str, data: dict) -> None:
    """Save the pane registry for a session."""
    registry_path(session).write_text(json.dumps(data, indent=2) + "\n")


def register_pane(session: str, window: str, pane_id: str, role: str, cmd: str) -> None:
    """Register a new pane in the registry."""
    _ensure_logging()
    data = load_registry(session)
    wdata = _get_window_data(data, window)
    order = max((p["order"] for p in wdata["panes"]), default=-1) + 1
    wdata["panes"].append({
        "id": pane_id,
        "role": role,
        "order": order,
        "cmd": cmd,
    })
    save_registry(session, data)
    _logger.info("register_pane: %s role=%s window=%s order=%d (total=%d)",
                 pane_id, role, window, order, len(wdata["panes"]))


def unregister_pane(session: str, pane_id: str) -> None:
    """Remove a pane from the registry (searches all windows)."""
    _ensure_logging()
    data = load_registry(session)
    found = False
    for window_id, wdata in data.get("windows", {}).items():
        before = len(wdata["panes"])
        wdata["panes"] = [p for p in wdata["panes"] if p["id"] != pane_id]
        if len(wdata["panes"]) < before:
            found = True
            _logger.info("unregister_pane: %s removed from window %s", pane_id, window_id)
    save_registry(session, data)
    if not found:
        _logger.info("unregister_pane: %s not found in any window", pane_id)


def kill_and_unregister(session: str, pane_id: str) -> None:
    """Kill a tmux pane and remove it from the registry."""
    from pm_core import tmux as tmux_mod
    subprocess.run(tmux_mod._tmux_cmd("kill-pane", "-t", pane_id), check=False)
    unregister_pane(session, pane_id)


def find_live_pane_by_role(session: str, role: str,
                           window: str | None = None) -> str | None:
    """Find a live pane with the given role, or None if not found.

    Checks both the registry and tmux to ensure the pane actually exists.
    When *window* is given, only that window is searched; otherwise all
    windows are searched.
    Returns the pane ID if found and alive, None otherwise.
    """
    _ensure_logging()
    from pm_core import tmux as tmux_mod

    data = load_registry(session)

    if window:
        windows_to_search = {window: _get_window_data(data, window)}
    else:
        windows_to_search = data.get("windows", {})

    _logger.debug("find_live_pane_by_role: session=%s windows=%s role=%s",
                  session, list(windows_to_search), role)

    for win_id, wdata in windows_to_search.items():
        for pane in wdata.get("panes", []):
            if pane.get("role") == role:
                pane_id = pane.get("id")
                if pane_id:
                    live_panes = tmux_mod.get_pane_indices(session, win_id)
                    live_ids = {p[0] for p in live_panes}
                    _logger.debug("find_live_pane_by_role: window=%s live_ids=%s, checking %s",
                                  win_id, live_ids, pane_id)
                    if pane_id in live_ids:
                        _logger.info("find_live_pane_by_role: %s -> %s (alive in %s)",
                                     role, pane_id, win_id)
                        return pane_id
                    else:
                        _logger.info("find_live_pane_by_role: %s -> %s (dead in %s)",
                                     role, pane_id, win_id)
    _logger.info("find_live_pane_by_role: %s -> None", role)
    return None


def _reconcile_registry(session: str, window: str,
                        query_session: str | None = None) -> list[str]:
    """Remove registry panes that no longer exist in tmux. Returns removed IDs.

    Only reconciles the specified *window*.  If the window becomes empty
    its entry is removed from the registry.
    """
    _ensure_logging()
    from pm_core import tmux as tmux_mod

    qs = query_session or session
    data = load_registry(session)
    wdata = _get_window_data(data, window)
    live_panes = tmux_mod.get_pane_indices(qs, window)
    live_ids = {pid for pid, _ in live_panes}

    # If we got zero live panes but the window has panes, the window
    # probably doesn't exist (session was killed). Don't wipe.
    if not live_ids and wdata["panes"]:
        _logger.info("reconcile: no live panes found for %s:%s, skipping "
                     "(window may not exist)", session, window)
        return []

    removed = []
    surviving = []
    for p in wdata["panes"]:
        if p["id"] in live_ids:
            surviving.append(p)
        else:
            removed.append(p["id"])

    if removed:
        wdata["panes"] = surviving
        # Remove empty window entry
        if not surviving:
            data["windows"].pop(window, None)
        save_registry(session, data)
        _logger.info("reconcile: removed dead panes %s from window %s, %d remaining",
                     removed, window, len(surviving))
    else:
        _logger.debug("reconcile: all %d registry panes still alive in window %s",
                     len(wdata["panes"]), window)

    return removed
