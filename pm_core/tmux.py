"""Tmux session management for pm."""

import os
import subprocess


def _tmux_cmd(*args: str, socket_path: str | None = None) -> list[str]:
    """Build a tmux command with optional custom socket.

    If socket_path is given, uses it.  Otherwise checks PM_TMUX_SOCKET env var.
    This ensures all tmux calls route to the correct server when using shared
    multi-user sessions.
    """
    cmd = ["tmux"]
    sp = socket_path or os.environ.get("PM_TMUX_SOCKET")
    if sp:
        cmd.extend(["-S", sp])
    cmd.extend(args)
    return cmd


def has_tmux() -> bool:
    """Check if tmux is installed."""
    import shutil
    return shutil.which("tmux") is not None


def in_tmux() -> bool:
    """Check if we're currently inside a tmux session."""
    return bool(os.environ.get("TMUX"))


def session_exists(name: str, socket_path: str | None = None) -> bool:
    """Check if a tmux session with the given name exists."""
    result = subprocess.run(
        _tmux_cmd("has-session", "-t", name, socket_path=socket_path),
        capture_output=True,
    )
    return result.returncode == 0


def create_session(name: str, cwd: str, cmd: str, socket_path: str | None = None) -> None:
    """Create a detached tmux session running cmd."""
    subprocess.run(
        _tmux_cmd("new-session", "-d", "-s", name, "-n", "main", "-c", cwd, cmd,
                   socket_path=socket_path),
        check=True,
    )


def split_pane(session: str, direction: str, cmd: str) -> str:
    """Split a pane and run cmd. Returns new pane ID.

    direction: 'h' for horizontal (left/right), 'v' for vertical (top/bottom)
    """
    flag = "-h" if direction == "h" else "-v"
    result = subprocess.run(
        _tmux_cmd("split-window", flag, "-t", session, "-P", "-F", "#{pane_id}", cmd),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def send_keys(pane_target: str, keys: str) -> None:
    """Send keys to a tmux pane (followed by Enter)."""
    subprocess.run(
        _tmux_cmd("send-keys", "-t", pane_target, keys, "Enter"),
        check=True,
    )


def send_keys_literal(pane_target: str, keys: str) -> None:
    """Send literal keys to a tmux pane (no Enter appended)."""
    subprocess.run(
        _tmux_cmd("send-keys", "-t", pane_target, keys),
        check=True,
    )


def attach(name: str, socket_path: str | None = None) -> None:
    """Attach to a tmux session."""
    subprocess.run(
        _tmux_cmd("attach-session", "-t", name, socket_path=socket_path),
        check=True,
    )


def kill_session(name: str, socket_path: str | None = None) -> None:
    """Kill a tmux session."""
    subprocess.run(
        _tmux_cmd("kill-session", "-t", name, socket_path=socket_path),
        check=False,
    )


def kill_window(session: str, window: str) -> None:
    """Kill a tmux window by index or name."""
    subprocess.run(
        _tmux_cmd("kill-window", "-t", f"{session}:{window}"),
        check=False,
    )


def new_window(session: str, name: str, cmd: str, cwd: str) -> None:
    """Create a new tmux window with the given name, running cmd.

    Uses 'session:' format to ensure numeric session names aren't
    interpreted as window indices.  Uses -d to avoid switching the base
    session, then switches only the caller's grouped session.
    """
    # Use session: format to explicitly target session, not window index
    target = f"{session}:"
    subprocess.run(
        _tmux_cmd("new-window", "-d", "-t", target, "-n", name, "-c", cwd, cmd),
        check=True,
    )
    # Switch only the current grouped session to the new window
    win = find_window_by_name(session, name)
    if win:
        current = current_or_base_session(session)
        subprocess.run(
            _tmux_cmd("select-window", "-t", f"{current}:{win['index']}"),
            capture_output=True,
        )


def split_pane_background(session: str, direction: str, cmd: str) -> str:
    """Split a pane without switching focus. Returns new pane ID.

    Like split_pane but uses -d to keep focus on the current pane.
    direction: 'h' for horizontal (left/right), 'v' for vertical (top/bottom)
    """
    flag = "-h" if direction == "h" else "-v"
    result = subprocess.run(
        _tmux_cmd("split-window", "-d", flag, "-t", session, "-P", "-F", "#{pane_id}", cmd),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def split_pane_at(pane_id: str, direction: str, cmd: str, background: bool = False) -> str:
    """Split a specific pane. Returns new pane ID.

    direction: 'h' for horizontal (left/right), 'v' for vertical (top/bottom)
    """
    flag = "-h" if direction == "h" else "-v"
    args = ["split-window", flag, "-t", pane_id, "-P", "-F", "#{pane_id}", cmd]
    if background:
        args.insert(2, "-d")
    result = subprocess.run(_tmux_cmd(*args), capture_output=True, text=True, check=True)
    return result.stdout.strip()


def select_pane(pane_id: str) -> None:
    """Focus a specific pane."""
    subprocess.run(_tmux_cmd("select-pane", "-t", pane_id), check=True)


def resize_pane(pane_id: str, direction: str, size: int) -> None:
    """Resize a pane. direction: 'x' for width, 'y' for height."""
    flag = "-x" if direction == "x" else "-y"
    subprocess.run(
        _tmux_cmd("resize-pane", "-t", pane_id, flag, str(size)),
        check=True,
    )


def set_hook(session: str, hook_name: str, cmd: str) -> None:
    """Register a tmux hook on a session."""
    subprocess.run(
        _tmux_cmd("set-hook", "-t", session, hook_name, cmd),
        check=True,
    )


def get_window_size(session: str, window: str = "0") -> tuple[int, int]:
    """Get window dimensions as (width, height)."""
    result = subprocess.run(
        _tmux_cmd("display", "-t", f"{session}:{window}", "-p",
                   "#{window_width} #{window_height}"),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return (0, 0)
    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return (0, 0)
    return (int(parts[0]), int(parts[1]))


def apply_layout(session: str, window: str, layout_string: str) -> bool:
    """Apply a custom layout string via tmux select-layout. Returns True on success."""
    import logging
    result = subprocess.run(
        _tmux_cmd("select-layout", "-t", f"{session}:{window}", layout_string),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        logging.getLogger("pm.pane_layout").warning(
            "tmux select-layout failed: %s", result.stderr.strip())
    return result.returncode == 0


def get_session_name() -> str:
    """Get the current tmux session name (must be called from within tmux).

    Uses $TMUX_PANE to target the specific pane, which is more reliable
    than display-message without a target (which uses "current client"
    and can return wrong session in background processes).
    """
    pane = os.environ.get("TMUX_PANE")
    if pane:
        # Target the specific pane to get accurate session name
        result = subprocess.run(
            _tmux_cmd("display-message", "-p", "-t", pane, "#{session_name}"),
            capture_output=True, text=True,
        )
    else:
        # Fallback to current client
        result = subprocess.run(
            _tmux_cmd("display-message", "-p", "#{session_name}"),
            capture_output=True, text=True,
        )
    return result.stdout.strip()


def get_pane_indices(session: str, window: str = "0") -> list[tuple[str, int]]:
    """Get list of (pane_id, pane_index) for all panes in a window."""
    result = subprocess.run(
        _tmux_cmd("list-panes", "-t", f"{session}:{window}",
                   "-F", "#{pane_id} #{pane_index}"),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    pairs = []
    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) == 2:
            pairs.append((parts[0], int(parts[1])))
    return pairs


def get_pane_geometries(session: str, window: str = "0") -> list[tuple[str, int, int, int, int]]:
    """Get pane geometries as list of (pane_id, x, y, width, height)."""
    result = subprocess.run(
        _tmux_cmd("list-panes", "-t", f"{session}:{window}",
                   "-F", "#{pane_id} #{pane_left} #{pane_top} #{pane_width} #{pane_height}"),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    geoms = []
    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) == 5:
            geoms.append((parts[0], int(parts[1]), int(parts[2]),
                          int(parts[3]), int(parts[4])))
    return geoms


def get_window_id(session: str) -> str:
    """Get the active window ID for a session.

    Automatically targets the current grouped session so the returned
    window matches what the user actually sees.
    """
    target = current_or_base_session(session)
    result = subprocess.run(
        _tmux_cmd("display", "-t", target, "-p", "#{window_id}"),
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def swap_pane(src_pane: str, dst_pane: str) -> None:
    """Swap two panes."""
    subprocess.run(
        _tmux_cmd("swap-pane", "-s", src_pane, "-t", dst_pane, "-d"),
        check=True,
    )


def list_windows(session: str) -> list[dict]:
    """List windows in a session. Returns list of {id, index, name}."""
    result = subprocess.run(
        _tmux_cmd("list-windows", "-t", session, "-F",
                   "#{window_id} #{window_index} #{window_name}"),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    windows = []
    for line in result.stdout.strip().splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 3:
            windows.append({"id": parts[0], "index": parts[1], "name": parts[2]})
    return windows


def find_window_by_name(session: str, name: str) -> dict | None:
    """Find a window by name. Returns {id, index, name} or None."""
    for w in list_windows(session):
        if w["name"] == name:
            return w
    return None


def select_window(session: str, window: str) -> bool:
    """Select (switch to) a window by index or name. Returns True on success.

    Targets the current grouped session so only the caller's terminal switches.
    """
    target = current_or_base_session(session)
    result = subprocess.run(
        _tmux_cmd("select-window", "-t", f"{target}:{window}"),
        capture_output=True,
    )
    return result.returncode == 0


def zoom_pane(pane_id: str) -> None:
    """Zoom (maximize) a pane within its window."""
    subprocess.run(_tmux_cmd("resize-pane", "-t", pane_id, "-Z"), check=False)


def is_zoomed(session: str, window: str = "0") -> bool:
    """Check if the active pane in a window is currently zoomed."""
    result = subprocess.run(
        _tmux_cmd("display", "-t", f"{session}:{window}", "-p",
                   "#{window_zoomed_flag}"),
        capture_output=True, text=True,
    )
    return result.stdout.strip() == "1"


def unzoom_pane(session: str, window: str = "0") -> None:
    """Unzoom the window if it's currently zoomed."""
    if is_zoomed(session, window):
        # Toggle zoom off by zooming the active pane again
        subprocess.run(
            _tmux_cmd("resize-pane", "-t", f"{session}:{window}", "-Z"),
            check=False,
        )


def select_pane_smart(pane_id: str, session: str, window: str) -> None:
    """Focus a pane, auto-zooming it in mobile mode."""
    from pm_core import pane_layout
    select_pane(pane_id)
    if pane_layout.is_mobile(session, window):
        zoom_pane(pane_id)


def set_session_option(session: str, option: str, value: str) -> None:
    """Set a tmux session option."""
    subprocess.run(
        ["tmux", "set-option", "-t", session, option, value],
        check=False,
    )


def current_or_base_session(base: str) -> str:
    """Return the best session to target for query operations.

    Priority:
    1. Current session (from $TMUX_PANE) if it's in the same group
    2. Any attached grouped session (user is watching it)
    3. The base session as fallback
    """
    if in_tmux():
        current = get_session_name()
        if current == base or current.startswith(base + "~"):
            return current
    # Current pane is in a different group (or not in tmux).
    # The base session may have no clients; prefer an attached grouped session.
    for name in list_grouped_sessions(base):
        result = subprocess.run(
            _tmux_cmd("display-message", "-t", name, "-p", "#{session_attached}"),
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip() != "0":
            return name
    return base



def create_grouped_session(base: str, name: str, socket_path: str | None = None) -> None:
    """Create a grouped session sharing windows with the base session."""
    subprocess.run(
        _tmux_cmd("new-session", "-d", "-t", base, "-s", name,
                   socket_path=socket_path),
        check=True,
    )


def list_grouped_sessions(base: str, socket_path: str | None = None) -> list[str]:
    """List grouped sessions matching base~*, sorted by suffix number."""
    result = subprocess.run(
        _tmux_cmd("list-sessions", "-F", "#{session_name}",
                   socket_path=socket_path),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    prefix = base + "~"
    grouped = []
    for line in result.stdout.strip().splitlines():
        if line.startswith(prefix):
            grouped.append(line)
    grouped.sort(key=lambda s: int(s.split("~")[1]) if s.split("~")[1].isdigit() else 0)
    return grouped


def find_unattached_grouped_session(base: str, socket_path: str | None = None) -> str | None:
    """Find the earliest grouped session with no clients attached."""
    for name in list_grouped_sessions(base, socket_path=socket_path):
        result = subprocess.run(
            _tmux_cmd("display-message", "-t", name, "-p", "#{session_attached}",
                       socket_path=socket_path),
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip() == "0":
            return name
    return None


def next_grouped_session_name(base: str, socket_path: str | None = None) -> str:
    """Return the next grouped session name (base~{max+1})."""
    existing = list_grouped_sessions(base, socket_path=socket_path)
    if not existing:
        return f"{base}~1"
    max_n = 0
    for name in existing:
        suffix = name.split("~")[1]
        if suffix.isdigit():
            max_n = max(max_n, int(suffix))
    return f"{base}~{max_n + 1}"


def set_environment(session: str, key: str, value: str, socket_path: str | None = None) -> None:
    """Set an environment variable in a tmux session."""
    subprocess.run(
        _tmux_cmd("set-environment", "-t", session, key, value,
                   socket_path=socket_path),
        check=False,
    )
