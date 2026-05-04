"""Tmux session management for pm."""

import os
import subprocess

from pm_core.paths import configure_logger

_log = configure_logger("pm.tmux")


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


def _run(*args, **kwargs) -> subprocess.CompletedProcess:
    """Run subprocess.run with capture_output=True by default.

    Suppresses tmux's stderr (e.g. "can't find pane: %5") from leaking
    into the TUI terminal when targeting stale pane IDs.
    """
    kwargs.setdefault("capture_output", True)
    return subprocess.run(*args, **kwargs)


def has_tmux() -> bool:
    """Check if tmux is installed."""
    import shutil
    return shutil.which("tmux") is not None


def in_tmux() -> bool:
    """Check if we're currently inside a tmux session."""
    return bool(os.environ.get("TMUX"))


def session_exists(name: str, socket_path: str | None = None) -> bool:
    """Check if a tmux session with the given name exists."""
    result = _run(
        _tmux_cmd("has-session", "-t", name, socket_path=socket_path),
    )
    return result.returncode == 0


def grant_server_access(users: list[str], socket_path: str | None = None) -> None:
    """Grant tmux server-access to a list of users.

    tmux 3.3+ enforces an ACL on socket connections.  Even with 0o777
    file permissions, other UIDs are rejected unless explicitly allowed
    via ``server-access -a <user>``.
    """
    for user in users:
        _run(
            _tmux_cmd("server-access", "-a", user, socket_path=socket_path),
        )


def create_session(name: str, cwd: str, cmd: str, socket_path: str | None = None) -> None:
    """Create a detached tmux session running cmd."""
    _run(
        _tmux_cmd("new-session", "-d", "-s", name, "-n", "main", "-c", cwd, cmd,
                   socket_path=socket_path),
        check=True,
    )


def split_pane(session: str, direction: str, cmd: str,
               window: str | None = None) -> str:
    """Split a pane and run cmd. Returns new pane ID.

    direction: 'h' for horizontal (left/right), 'v' for vertical (top/bottom)
    window: optional tmux window id/name to target. When omitted, splits
        the active pane of the session's active window.
    """
    flag = "-h" if direction == "h" else "-v"
    target = f"{session}:{window}" if window else session
    result = _run(
        _tmux_cmd("split-window", flag, "-t", target, "-P", "-F", "#{pane_id}", cmd),
        text=True,
        check=True,
    )
    return result.stdout.strip()


def send_keys(pane_target: str, keys: str) -> None:
    """Send keys to a tmux pane (followed by Enter)."""
    _run(
        _tmux_cmd("send-keys", "-t", pane_target, keys, "Enter"),
        check=True,
    )


def send_keys_literal(pane_target: str, keys: str) -> None:
    """Send literal keys to a tmux pane (no Enter appended)."""
    _run(
        _tmux_cmd("send-keys", "-t", pane_target, keys),
        check=True,
    )


def attach(name: str, socket_path: str | None = None) -> None:
    """Attach to a tmux session."""
    _run(
        _tmux_cmd("attach-session", "-t", name, socket_path=socket_path),
        check=True,
    )


def kill_session(name: str, socket_path: str | None = None) -> None:
    """Kill a tmux session."""
    _run(
        _tmux_cmd("kill-session", "-t", name, socket_path=socket_path),
    )


def kill_window(session: str, window: str) -> None:
    """Kill a tmux window by index or name."""
    _run(
        _tmux_cmd("kill-window", "-t", f"{session}:{window}"),
    )


def new_window(session: str, name: str, cmd: str, cwd: str,
               switch: bool = True) -> None:
    """Create a new tmux window with the given name, running cmd.

    Uses 'session:' format to ensure numeric session names aren't
    interpreted as window indices.  Uses -d to avoid switching the base
    session, then switches only the caller's grouped session.

    Set *switch* to False to create the window without changing the
    active window (useful for background operations like the review loop).
    """
    # Use session: format to explicitly target session, not window index
    target = f"{session}:"
    _run(
        _tmux_cmd("new-window", "-d", "-t", target, "-n", name, "-c", cwd, cmd),
        check=True,
    )
    if switch:
        # Switch only the current grouped session to the new window
        win = find_window_by_name(session, name)
        if win:
            current = current_or_base_session(session)
            _run(
                _tmux_cmd("select-window", "-t", f"{current}:{win['index']}"),
            )


def new_window_get_pane(session: str, name: str, cmd: str, cwd: str,
                        switch: bool = True) -> str | None:
    """Create a new tmux window and return its initial pane ID.

    Like new_window but returns the pane ID so callers can split on it.
    Returns None if the window couldn't be found after creation.

    Set *switch* to False to create the window without changing the
    active window (useful for background operations like the review loop).
    """
    target = f"{session}:"
    _run(
        _tmux_cmd("new-window", "-d", "-t", target, "-n", name, "-c", cwd, cmd),
        check=True,
    )
    win = find_window_by_name(session, name)
    if not win:
        return None
    if switch:
        # Switch the current grouped session to the new window
        current = current_or_base_session(session)
        _run(
            _tmux_cmd("select-window", "-t", f"{current}:{win['index']}"),
        )
    # Discover the pane ID
    panes = get_pane_indices(session, win["index"])
    if panes:
        return panes[0][0]
    return None


def create_window(session: str, cmd: str) -> tuple[str, str]:
    """Create a new window in *session* running *cmd*.

    Returns ``(pane_id, window_id)`` of the newly created window.
    """
    result = _run(
        _tmux_cmd("new-window", "-t", f"{session}:",
                  "-P", "-F", "#{pane_id} #{window_id}", cmd),
        text=True, check=True,
    )
    parts = result.stdout.strip().split()
    return parts[0], parts[1]


def split_pane_background(session: str, direction: str, cmd: str) -> str:
    """Split a pane without switching focus. Returns new pane ID.

    Like split_pane but uses -d to keep focus on the current pane.
    direction: 'h' for horizontal (left/right), 'v' for vertical (top/bottom)
    """
    flag = "-h" if direction == "h" else "-v"
    result = _run(
        _tmux_cmd("split-window", "-d", flag, "-t", session, "-P", "-F", "#{pane_id}", cmd),
        text=True,
        check=True,
    )
    return result.stdout.strip()


def split_pane_at(pane_id: str, direction: str, cmd: str,
                  background: bool = False, cwd: str | None = None) -> str:
    """Split a specific pane. Returns new pane ID.

    direction: 'h' for horizontal (left/right), 'v' for vertical (top/bottom)
    cwd: starting directory for the new pane. Without this, tmux inherits
        the target pane's current /proc cwd, which can drift if the
        target's shell has been chdir'd by a long-running process
        (e.g. Claude Code's persistent Bash tool).
    """
    flag = "-h" if direction == "h" else "-v"
    args = ["split-window", flag, "-t", pane_id, "-P", "-F", "#{pane_id}"]
    if cwd:
        args += ["-c", cwd]
    args.append(cmd)
    if background:
        args.insert(2, "-d")
    result = _run(_tmux_cmd(*args), text=True, check=True)
    return result.stdout.strip()


def select_pane(pane_id: str) -> None:
    """Focus a specific pane."""
    _run(_tmux_cmd("select-pane", "-t", pane_id), check=True)


def resize_pane(pane_id: str, direction: str, size: int) -> None:
    """Resize a pane. direction: 'x' for width, 'y' for height."""
    flag = "-x" if direction == "x" else "-y"
    _run(
        _tmux_cmd("resize-pane", "-t", pane_id, flag, str(size)),
        check=True,
    )


def set_hook(session: str, hook_name: str, cmd: str) -> None:
    """Register a tmux hook on a session."""
    _run(
        _tmux_cmd("set-hook", "-t", session, hook_name, cmd),
        check=True,
    )


def get_window_size(session: str, window: str = "0") -> tuple[int, int]:
    """Get window dimensions as (width, height)."""
    result = _run(
        _tmux_cmd("display", "-t", f"{session}:{window}", "-p",
                   "#{window_width} #{window_height}"),
        text=True,
    )
    if result.returncode != 0:
        return (0, 0)
    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return (0, 0)
    return (int(parts[0]), int(parts[1]))


def apply_layout(session: str, window: str, layout_string: str) -> bool:
    """Apply a custom layout string via tmux select-layout. Returns True on success."""
    result = _run(
        _tmux_cmd("select-layout", "-t", f"{session}:{window}", layout_string),
        text=True,
    )
    if result.returncode != 0:
        _log.warning(
            "tmux select-layout failed: %s", result.stderr.strip())
        return False
    refresh_client(session, window)
    return True


def get_session_name() -> str:
    """Get the current tmux session name (must be called from within tmux).

    Uses $TMUX_PANE to target the specific pane, which is more reliable
    than display-message without a target (which uses "current client"
    and can return wrong session in background processes).
    """
    pane = os.environ.get("TMUX_PANE")
    if pane:
        # Target the specific pane to get accurate session name
        result = _run(
            _tmux_cmd("display-message", "-p", "-t", pane, "#{session_name}"),
            text=True,
        )
    else:
        # Fallback to current client
        result = _run(
            _tmux_cmd("display-message", "-p", "#{session_name}"),
            text=True,
        )
    return result.stdout.strip()


def get_pane_indices(session: str, window: str = "0") -> list[tuple[str, int]]:
    """Get list of (pane_id, pane_index) for all panes in a window."""
    result = _run(
        _tmux_cmd("list-panes", "-t", f"{session}:{window}",
                   "-F", "#{pane_id} #{pane_index}"),
        text=True,
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
    result = _run(
        _tmux_cmd("list-panes", "-t", f"{session}:{window}",
                   "-F", "#{pane_id} #{pane_left} #{pane_top} #{pane_width} #{pane_height}"),
        text=True,
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
    result = _run(
        _tmux_cmd("display", "-t", target, "-p", "#{window_id}"),
        text=True,
    )
    return result.stdout.strip()


def swap_pane(src_pane: str, dst_pane: str) -> None:
    """Swap two panes."""
    _run(
        _tmux_cmd("swap-pane", "-s", src_pane, "-t", dst_pane, "-d"),
        check=True,
    )


def list_windows(session: str) -> list[dict]:
    """List windows in a session. Returns list of {id, index, name}."""
    result = _run(
        _tmux_cmd("list-windows", "-t", session, "-F",
                   "#{window_id} #{window_index} #{window_name}"),
        text=True,
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
    """Refocus *window* and bring along all sessions co-viewing it.

    Thin wrapper around :func:`focus_window` for legacy call sites. New code
    should call ``focus_window`` directly so an originating session and a
    pre-captured co-viewer list can be threaded through.
    """
    return focus_window(session, window)


def focus_window(
    base: str,
    window: str,
    origin_session: str | None = None,
    co_viewers: list[str] | None = None,
) -> bool:
    """Switch *window* into view for the originating session and co-viewers.

    Resolves the target window inside *base* (a name, index, or ``@id``),
    then identifies which sessions in the group are currently watching the
    same window as *origin_session* and switches all of them together. This
    replaces the older split between ``select_window`` (one session) and
    ``switch_sessions_to_window`` (a pre-captured list).

    Parameters
    ----------
    base:
        The base pm session (e.g. ``pm-foo-c5a1006b``). All grouped sessions
        considered for co-viewer detection must belong to this group.
    window:
        Window id (``@N``), numeric index, or window name.
    origin_session:
        The session that initiated the refocus. Captured at command-launch
        time so async flows refocus the correct user instead of whoever the
        TUI happens to be focused on at the moment of the call. Defaults to
        ``$PM_ORIGIN_SESSION`` (set by the TUI when spawning subprocesses),
        then falls back to :func:`current_or_base_session` for legacy calls.
    co_viewers:
        Pre-captured list of session names. When provided, skips the
        co-viewer lookup — used by review/watcher/qa flows that snapshot the
        old window's viewers *before* killing it. Must include the origin
        session if it should be switched.

    Coordination note: pr-291e891 introduces a richer action-context
    structure for TUI operations. When that lands, the env-var transport
    here can be replaced by passing the action context explicitly.
    """
    window = str(window)
    win_id, win_index = _resolve_window_target(base, window)
    if not win_index:
        _log.warning("focus_window: window %r not found in %s", window, base)
        return False

    if co_viewers is None:
        if origin_session is None:
            origin_session = os.environ.get("PM_ORIGIN_SESSION") or None
        if origin_session is None:
            origin_session = current_or_base_session(base)

        # Find the window the origin session is currently viewing, then all
        # sessions in the group viewing the same window.
        cur_id = _current_window_id(origin_session)
        if cur_id:
            sessions = sessions_on_window(base, cur_id)
            if origin_session not in sessions:
                sessions.append(origin_session)
        else:
            sessions = [origin_session]
    else:
        sessions = list(co_viewers)

    _log.info("focus_window: base=%s window=%s origin=%s sessions=%s",
               base, window, origin_session, sessions)
    if not sessions:
        return False

    client_map = _list_clients_by_session()
    any_ok = False
    for sess in sessions:
        sel = _run(_tmux_cmd("select-window", "-t", f"{sess}:{win_index}"))
        if sel.returncode == 0:
            any_ok = True
        client_tty = client_map.get(sess)
        if client_tty:
            _run(_tmux_cmd("switch-client", "-t", sess, "-c", client_tty))
    return any_ok


def _resolve_window_target(base: str, window: str) -> tuple[str, str]:
    """Resolve *window* (name, index, or @id) into (id, index-or-id-token).

    Returns ("", "") if the window cannot be found. The second element is a
    token suitable for ``select-window -t base:<token>`` — id, numeric
    index, or name; if a name was passed we resolve to its index so each
    co-viewing session targets the same window even if their MRU differs.
    """
    if window.startswith("@"):
        return window, window
    if window.isdigit():
        return window, window
    win = find_window_by_name(base, window)
    if not win:
        return "", ""
    return win["id"], win["index"]


def _current_window_id(session: str) -> str:
    """Return the active window id for *session*, or "" on error."""
    r = _run(
        _tmux_cmd("display-message", "-t", session, "-p", "#{window_id}"),
        text=True,
    )
    if r.returncode != 0:
        return ""
    return r.stdout.strip()


def most_recent_client_session(base: str) -> str:
    """Return the session of the most-recently-active attached client in *base*'s group.

    Used to identify which co-viewing tmux client just sent input to a
    shared pane (e.g. the TUI). With grouped sessions, every attached
    client is delivered the same keystrokes, so the calling Python
    process cannot tell who typed via ``$TMUX_PANE`` alone — that env is
    fixed at process launch. Tmux does track ``#{client_activity}`` per
    client, so the client with the highest activity timestamp is the one
    whose input arrived most recently. Limited to clients whose session
    matches *base* or ``base~*`` so we ignore unrelated tmux clients.

    Returns "" if no eligible client is found.
    """
    r = _run(
        _tmux_cmd("list-clients", "-F", "#{client_activity} #{client_session}"),
        text=True,
    )
    if r.returncode != 0:
        return ""
    best_ts = -1
    best_sess = ""
    for line in r.stdout.strip().splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        ts_str, sess = parts
        if sess != base and not sess.startswith(base + "~"):
            continue
        try:
            ts = int(ts_str)
        except ValueError:
            continue
        if ts > best_ts:
            best_ts = ts
            best_sess = sess
    return best_sess


def _list_clients_by_session() -> dict[str, str]:
    """Return ``{session_name: client_tty}`` for all attached clients."""
    r = _run(
        _tmux_cmd("list-clients", "-F", "#{session_name} #{client_tty}"),
        text=True,
    )
    out: dict[str, str] = {}
    if r.returncode == 0:
        for line in r.stdout.strip().splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                out[parts[0]] = parts[1]
    return out


def refresh_client(session: str, window: str = "") -> None:
    """Force tmux to repaint all clients attached to a session.

    Fixes visual artifacts (ghost prompt bars, stale content at wrong
    offsets) that appear after select-layout changes pane dimensions.
    The window parameter is unused — refresh-client targets a client
    (TTY or session name), not a session:window pair.
    """
    _run(
        _tmux_cmd("refresh-client", "-t", session),
    )


def zoom_pane(pane_id: str) -> None:
    """Zoom (maximize) a pane within its window."""
    _run(_tmux_cmd("resize-pane", "-t", pane_id, "-Z"))


def is_zoomed(session: str, window: str = "0") -> bool:
    """Check if the active pane in a window is currently zoomed."""
    result = _run(
        _tmux_cmd("display", "-t", f"{session}:{window}", "-p",
                   "#{window_zoomed_flag}"),
        text=True,
    )
    return result.stdout.strip() == "1"


def unzoom_pane(session: str, window: str = "0") -> None:
    """Unzoom the window if it's currently zoomed."""
    if is_zoomed(session, window):
        # Toggle zoom off by zooming the active pane again
        _run(
            _tmux_cmd("resize-pane", "-t", f"{session}:{window}", "-Z"),
        )


def select_pane_smart(pane_id: str, session: str, window: str) -> None:
    """Focus a pane, auto-zooming it in mobile mode."""
    from pm_core import pane_layout
    select_pane(pane_id)
    if pane_layout.is_mobile(session, window):
        zoom_pane(pane_id)


def set_session_option(session: str, option: str, value: str, socket_path: str | None = None) -> None:
    """Set a tmux session option."""
    _run(
        _tmux_cmd("set-option", "-t", session, option, value, socket_path=socket_path),
    )


def set_shared_window_size(session: str, window: str) -> None:
    """For shared sessions, set per-window window-size to smallest.

    New tmux windows inherit ``window-size=latest`` by default, which
    overrides the session-level ``smallest`` setting.  This helper
    explicitly sets ``window-size=smallest`` on the window so that it
    fits the smallest connected client in multi-user sessions.

    No-op when ``PM_SHARE_MODE`` is not set (i.e. non-shared sessions).
    """
    if os.environ.get("PM_SHARE_MODE"):
        _run(
            _tmux_cmd(
                "set-window-option", "-t", f"{session}:{window}",
                "window-size", "smallest",
            ),
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
        if current and (current == base or current.startswith(base + "~")):
            # Only return current if it has attached clients — otherwise
            # fall through to find an attached grouped session.
            result = _run(
                _tmux_cmd("display-message", "-t", current, "-p", "#{session_attached}"),
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip() != "0":
                return current
    # Current pane is in a different group (or not in tmux).
    # The base session may have no clients; prefer an attached grouped session.
    for name in list_grouped_sessions(base):
        result = _run(
            _tmux_cmd("display-message", "-t", name, "-p", "#{session_attached}"),
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip() != "0":
            return name
    return base



def create_grouped_session(base: str, name: str, socket_path: str | None = None) -> None:
    """Create a grouped session sharing windows with the base session."""
    _run(
        _tmux_cmd("new-session", "-d", "-t", base, "-s", name,
                   socket_path=socket_path),
        check=True,
    )


def list_grouped_sessions(base: str, socket_path: str | None = None) -> list[str]:
    """List grouped sessions matching base~*, sorted by suffix number."""
    result = _run(
        _tmux_cmd("list-sessions", "-F", "#{session_name}",
                   socket_path=socket_path),
        text=True,
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
        result = _run(
            _tmux_cmd("display-message", "-t", name, "-p", "#{session_attached}",
                       socket_path=socket_path),
            text=True,
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


def capture_pane(pane_id: str, full_scrollback: bool = False) -> str:
    """Capture the contents of a tmux pane.

    Returns the pane text, or empty string if the pane doesn't exist.
    """
    args = ["capture-pane", "-p", "-t", pane_id]
    if full_scrollback:
        args.extend(["-S", "-"])
    result = _run(_tmux_cmd(*args), text=True)
    return result.stdout if result.returncode == 0 else ""


def pane_exists(pane_id: str) -> bool:
    """Check if a tmux pane still exists.

    Uses ``list-panes`` which reliably returns non-zero for invalid
    targets (``display -p`` returns 0 with empty output instead).
    """
    result = _run(
        _tmux_cmd("list-panes", "-t", pane_id),
        text=True,
    )
    return result.returncode == 0


def pane_window_id(pane_id: str) -> str | None:
    """Return the window ID (e.g. ``@1``) that contains *pane_id*, or ``None``."""
    result = _run(
        _tmux_cmd("display", "-t", pane_id, "-p", "#{window_id}"),
        text=True,
    )
    return result.stdout.strip() or None


def sessions_on_window(base: str, window_id: str) -> list[str]:
    """Return all sessions in the group (base + grouped) whose active window matches *window_id*.

    Used by the review loop to determine which sessions need to be
    switched to the replacement window after the old one is killed.
    """
    candidates = [base] + list_grouped_sessions(base)
    _log.info("sessions_on_window: base=%s window_id=%s candidates=%s", base, window_id, candidates)
    result = []
    for name in candidates:
        r = _run(
            _tmux_cmd("display", "-t", name, "-p", "#{window_id}"),
            text=True,
        )
        cur_wid = r.stdout.strip() if r.returncode == 0 else f"<err:{r.returncode}>"
        _log.info("sessions_on_window:   %s → current_window_id=%s match=%s",
                   name, cur_wid, cur_wid == window_id)
        if r.returncode == 0 and cur_wid == window_id:
            result.append(name)
    _log.info("sessions_on_window: result=%s", result)
    return result


def switch_sessions_to_window(sessions: list[str], session: str, window_name: str) -> None:
    """Switch *sessions* to *window_name* in *session*'s group.

    Thin wrapper around :func:`focus_window` for legacy call sites that
    have already snapshotted the co-viewer list (e.g. before killing and
    recreating a window).
    """
    if not sessions:
        return
    focus_window(session, window_name, co_viewers=sessions)


def set_environment(session: str, key: str, value: str, socket_path: str | None = None) -> None:
    """Set an environment variable in a tmux session."""
    _run(
        _tmux_cmd("set-environment", "-t", session, key, value,
                   socket_path=socket_path),
    )


def list_clients_in_group(base: str, socket_path: str | None = None) -> list[dict]:
    """List all clients attached to any session in the group (base + base~*).

    Returns list of dicts with keys: tty, session.
    """
    result = _run(
        _tmux_cmd("list-clients", "-F", "#{client_tty} #{session_name}",
                   socket_path=socket_path),
        text=True,
    )
    if result.returncode != 0:
        return []
    group_sessions = {base} | set(list_grouped_sessions(base, socket_path=socket_path))
    clients = []
    for line in result.stdout.strip().splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1] in group_sessions:
            clients.append({"tty": parts[0], "session": parts[1]})
    return clients


def detach_client(tty: str, socket_path: str | None = None) -> None:
    """Detach a tmux client by its TTY."""
    _run(
        _tmux_cmd("detach-client", "-t", tty, socket_path=socket_path),
    )
