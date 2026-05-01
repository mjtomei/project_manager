"""Cleanup hook for the rc-server background daemon.

When the rc-driver pane (or its whole tmux window) goes away, the
FastAPI daemon we started in ``pm_core.cli.rc.start_cmd`` would otherwise
linger forever holding its port.  ``maybe_kill_server`` is invoked from
``pane_layout.handle_pane_exited`` after the registry has been
reconciled; it tears down the daemon when no rc-driver pane survives in
the affected window.
"""

from __future__ import annotations

import os
import signal

from pm_core import pane_registry


def maybe_kill_server(session: str, window: str) -> None:
    """Terminate the rc-server for *window* if no rc-driver pane remains.

    Reads the registry to find the rc-server entry recorded by
    ``pm rc start``.  If it exists and there is no live pane with role
    ``rc-driver`` in the same window, the daemon is sent SIGTERM and
    the registry entry is removed.  Best-effort: missing PID, dead PID,
    and missing entry all silently no-op.
    """
    data = pane_registry.load_registry(session)
    servers = (data.get("rc_servers") or {})
    info = servers.get(window)
    if not info:
        return

    wdata = data.get("windows", {}).get(window) or {"panes": []}
    has_driver = any(p.get("role") == "rc-driver" for p in wdata.get("panes", []))
    if has_driver:
        return

    pid = info.get("pid")
    if isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    # Drop the rc-server entry so future starts don't see stale state
    def modifier(raw):
        d = pane_registry._prepare_registry_data(raw, session)
        s = d.get("rc_servers") or {}
        if window in s:
            s.pop(window)
            d["rc_servers"] = s
            return d
        return None

    pane_registry.locked_read_modify_write(
        pane_registry.registry_path(session), modifier
    )
