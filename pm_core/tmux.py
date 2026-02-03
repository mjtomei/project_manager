"""Tmux session management for pm."""

import os
import subprocess


def has_tmux() -> bool:
    """Check if tmux is installed."""
    import shutil
    return shutil.which("tmux") is not None


def in_tmux() -> bool:
    """Check if we're currently inside a tmux session."""
    return bool(os.environ.get("TMUX"))


def session_exists(name: str) -> bool:
    """Check if a tmux session with the given name exists."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", name],
        capture_output=True,
    )
    return result.returncode == 0


def create_session(name: str, cwd: str, cmd: str) -> None:
    """Create a detached tmux session running cmd."""
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", name, "-c", cwd, cmd],
        check=True,
    )


def split_pane(session: str, direction: str, cmd: str) -> str:
    """Split a pane and run cmd. Returns new pane ID.

    direction: 'h' for horizontal (left/right), 'v' for vertical (top/bottom)
    """
    flag = "-h" if direction == "h" else "-v"
    result = subprocess.run(
        ["tmux", "split-window", flag, "-t", session, "-P", "-F", "#{pane_id}", cmd],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def send_keys(pane_target: str, keys: str) -> None:
    """Send keys to a tmux pane."""
    subprocess.run(
        ["tmux", "send-keys", "-t", pane_target, keys, "Enter"],
        check=True,
    )


def attach(name: str) -> None:
    """Attach to a tmux session."""
    subprocess.run(["tmux", "attach-session", "-t", name], check=True)


def kill_session(name: str) -> None:
    """Kill a tmux session."""
    subprocess.run(["tmux", "kill-session", "-t", name], check=False)


def new_window(session: str, name: str, cmd: str, cwd: str) -> None:
    """Create a new tmux window with the given name, running cmd."""
    subprocess.run(
        ["tmux", "new-window", "-t", session, "-n", name, "-c", cwd, cmd],
        check=True,
    )


def split_pane_background(session: str, direction: str, cmd: str) -> str:
    """Split a pane without switching focus. Returns new pane ID.

    Like split_pane but uses -d to keep focus on the current pane.
    direction: 'h' for horizontal (left/right), 'v' for vertical (top/bottom)
    """
    flag = "-h" if direction == "h" else "-v"
    result = subprocess.run(
        ["tmux", "split-window", "-d", flag, "-t", session, "-P", "-F", "#{pane_id}", cmd],
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
    args = ["tmux", "split-window", flag, "-t", pane_id, "-P", "-F", "#{pane_id}", cmd]
    if background:
        args.insert(3, "-d")
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def select_pane(pane_id: str) -> None:
    """Focus a specific pane."""
    subprocess.run(["tmux", "select-pane", "-t", pane_id], check=True)


def resize_pane(pane_id: str, direction: str, size: int) -> None:
    """Resize a pane. direction: 'x' for width, 'y' for height."""
    flag = "-x" if direction == "x" else "-y"
    subprocess.run(
        ["tmux", "resize-pane", "-t", pane_id, flag, str(size)],
        check=True,
    )


def set_hook(session: str, hook_name: str, cmd: str) -> None:
    """Register a tmux hook on a session."""
    subprocess.run(
        ["tmux", "set-hook", "-t", session, hook_name, cmd],
        check=True,
    )


def get_window_size(session: str, window: str = "0") -> tuple[int, int]:
    """Get window dimensions as (width, height)."""
    result = subprocess.run(
        ["tmux", "display", "-t", f"{session}:{window}", "-p",
         "#{window_width} #{window_height}"],
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
        ["tmux", "select-layout", "-t", f"{session}:{window}", layout_string],
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
            ["tmux", "display-message", "-p", "-t", pane, "#{session_name}"],
            capture_output=True, text=True,
        )
    else:
        # Fallback to current client
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_name}"],
            capture_output=True, text=True,
        )
    return result.stdout.strip()


def get_pane_indices(session: str, window: str = "0") -> list[tuple[str, int]]:
    """Get list of (pane_id, pane_index) for all panes in a window."""
    result = subprocess.run(
        ["tmux", "list-panes", "-t", f"{session}:{window}",
         "-F", "#{pane_id} #{pane_index}"],
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
        ["tmux", "list-panes", "-t", f"{session}:{window}",
         "-F", "#{pane_id} #{pane_left} #{pane_top} #{pane_width} #{pane_height}"],
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
    """Get the active window ID for a session."""
    result = subprocess.run(
        ["tmux", "display", "-t", session, "-p", "#{window_id}"],
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def swap_pane(src_pane: str, dst_pane: str) -> None:
    """Swap two panes."""
    subprocess.run(
        ["tmux", "swap-pane", "-s", src_pane, "-t", dst_pane, "-d"],
        check=True,
    )
