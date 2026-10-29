"""Tmux session management for pm."""

import os
import re
import shlex
import stat
import subprocess
from pathlib import Path

from pm_core.paths import configure_logger, write_env_file

_log = configure_logger("pm.tmux")


def _tmux_cmd(*args: str, socket_path: str | None = None,
              use_env: bool = True) -> list[str]:
    """Build a tmux command with optional custom socket.

    If socket_path is given, uses it.  Otherwise, when *use_env* is true,
    checks PM_TMUX_SOCKET.  This ensures all tmux calls route to the
    session's own server.  ``use_env=False`` with no ``socket_path`` drops
    that override, which is only half of "the default server": the tmux
    *binary* still falls back to the socket named by ``$TMUX`` whenever no
    ``-S`` is given, so callers that mean the user's default server pass
    its socket explicitly (``paths.default_socket_path()``).
    """
    cmd = ["tmux"]
    sp = socket_path
    if sp is None and use_env:
        sp = os.environ.get("PM_TMUX_SOCKET")
    if sp:
        cmd.extend(["-S", sp])
    cmd.extend(args)
    return cmd


def socket_path_from_tmux_env(environ: dict | None = None) -> str | None:
    """Return the private pm socket named by ``$TMUX``, if there is one.

    tmux exposes ``$TMUX`` as ``<socket>,<server-pid>,<session-id>`` inside
    panes, popups and ``run-shell`` commands.  Only sockets under the pm
    socket directory qualify, so commands run inside an ordinary tmux
    session keep targeting the default server.
    """
    env = os.environ if environ is None else environ
    raw = env.get("TMUX")
    if not raw:
        return None
    # The pid and session id are numeric, so the last two commas are the
    # separators even if the socket path itself contains a comma.
    path = raw.rsplit(",", 2)[0]
    if not path:
        return None
    # Imported here rather than at module scope so the value is read when
    # the function runs: callers (and tests) may re-point
    # ``paths.SHARED_SOCKET_DIR``, and a top-level ``from … import`` would
    # freeze the original Path object.
    from pm_core.paths import SHARED_SOCKET_DIR
    if Path(path).parent != SHARED_SOCKET_DIR:
        return None
    return path


def resolve_ambient_socket(environ: dict | None = None) -> str | None:
    """Return the tmux socket the current process should talk to."""
    env = os.environ if environ is None else environ
    return env.get("PM_TMUX_SOCKET") or socket_path_from_tmux_env(env)


def export_ambient_socket(environ: dict | None = None) -> str | None:
    """Resolve the ambient socket and store it in ``PM_TMUX_SOCKET``.

    Called once at CLI/wrapper startup so hooks, popups and subprocesses
    that only inherit ``$TMUX`` still route every ``_tmux_cmd`` call to the
    session's own server.
    """
    env = os.environ if environ is None else environ
    sp = resolve_ambient_socket(env)
    if sp:
        env["PM_TMUX_SOCKET"] = sp
    return sp


def _run(*args, **kwargs) -> subprocess.CompletedProcess:
    """Run subprocess.run with capture_output=True by default.

    Suppresses tmux's stderr (e.g. "can't find pane: %5") from leaking
    into the TUI terminal when targeting stale pane IDs.
    """
    kwargs.setdefault("capture_output", True)
    return subprocess.run(*args, **kwargs)


# ``cd <dir> && `` prefix produced by build_claude_shell_cmd.  It is kept
# outside the env wrapper so pane_start_command parsing (transcript/cwd
# recovery in claude_launcher.pane_transcript_path) still sees it.
_LEADING_CD_RE = re.compile(r"^(cd (?:'[^']*'|\"[^\"]*\"|[^\s;&]+) && )")


def _wrap_cmd_env(cmd: str, env: dict[str, str]) -> tuple[str, str]:
    """Return ``(wrapped_command, env_file_path)`` for a pane command.

    The values are written to a private file that the pane's shell sources
    and deletes before running the real command, so they never appear in the
    command string (logged and kept as ``#{pane_start_command}``).

    ``tmux -e NAME`` is not an option: on tmux 3.2 (the supported floor)
    ``new-window``/``split-window`` resolve a bare name from the server or
    session environment, not the client's, so it would silently drop the
    variable — or worse, inject a different value that happens to be there.
    ``sh -c`` makes the POSIX ``set -a; . file`` prefix work under a
    non-POSIX ``default-shell`` such as fish.
    """
    prefix, path = write_env_file(env)
    m = _LEADING_CD_RE.match(cmd)
    head = m.group(1) if m else ""
    body = cmd[len(head):]
    return f"{head}sh -c {shlex.quote(prefix + body)}", path


def _run_with_env(args: list[str], env: dict[str, str] | None,
                  **kwargs) -> subprocess.CompletedProcess:
    """Run a tmux command whose last argument is the pane's shell command.

    When *env* is given, the command is wrapped so the new pane receives the
    values through its environment (see ``_wrap_cmd_env``).
    """
    path: str | None = None
    if env:
        args = list(args)
        args[-1], path = _wrap_cmd_env(args[-1], env)
    try:
        return _run(args, **kwargs)
    except BaseException:
        # tmux never created the pane, so nothing will source the file.
        if path is not None:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise


def has_tmux() -> bool:
    """Check if tmux is installed."""
    import shutil
    return shutil.which("tmux") is not None


def in_tmux() -> bool:
    """Check if we're currently inside a tmux session."""
    return bool(os.environ.get("TMUX"))


def session_exists(name: str, socket_path: str | None = None,
                   use_env: bool = True) -> bool:
    """Check if a tmux session with the given name exists.

    With ``socket_path=None, use_env=False`` this queries the default
    server explicitly, which is how legacy pre-isolation sessions are
    detected.  The default server's socket is passed as ``-S`` because
    tmux would otherwise follow ``$TMUX`` and reach the private server
    this process happens to run on.
    """
    if socket_path is None and not use_env:
        from pm_core.paths import default_socket_path
        socket_path = str(default_socket_path())
    result = _run(
        _tmux_cmd("has-session", "-t", name, socket_path=socket_path),
    )
    return result.returncode == 0


def server_alive(socket_path: str) -> bool:
    """Return True when a tmux server answers on *socket_path*.

    Tells a stale socket file (server gone, safe to unlink) from a live
    one whose session set simply no longer contains the name being looked
    for: a live server can still host grouped sessions after its base
    session was killed elsewhere, and removing its socket would strand it.

    An unprobeable socket (tmux cannot be run) counts as alive, so nothing
    is ever deleted on a guess.
    """
    try:
        result = _run(
            _tmux_cmd("list-sessions", "-F", "#{session_name}",
                      socket_path=socket_path),
            text=True,
        )
    except OSError:
        return True
    return result.returncode == 0


def find_session_server(session_name: str) -> tuple[str | None, bool]:
    """Return ``(socket_path, is_private)`` for the server hosting a session.

    Single source of truth for "which tmux server is this pm session on":
    the per-session socket is checked first, then the user's default server
    (legacy pre-isolation sessions).  The private check runs first so a
    live private session is never shadowed by a same-named legacy one.

    The default server's socket is returned explicitly rather than as
    ``None``: with no ``-S`` the tmux binary follows ``$TMUX``, which from
    inside a pm pane names that session's private server.

    Returns ``(None, False)`` when the session is running on neither
    server, or when tmux cannot be run at all (callers degrade to "no
    session" instead of crashing).  ``session_name`` may carry a
    grouped-session ``~N`` suffix.
    """
    from pm_core.paths import default_socket_path, session_socket_path

    # Same rule as pane_registry.base_session_name; kept inline because
    # tmux.py is the lower-level module and should not depend on the
    # registry.
    base = session_name.split("~", 1)[0]
    try:
        if base.startswith("pm-"):
            sock = str(session_socket_path(base.removeprefix("pm-")))
            if session_exists(base, socket_path=sock):
                return sock, True
        if session_exists(base, use_env=False):
            return str(default_socket_path()), False
    except OSError:
        # tmux is not installed or not executable; no server can host it.
        return None, False
    return None, False


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


def create_session(name: str, cwd: str, cmd: str, socket_path: str | None = None,
                   env: dict[str, str] | None = None) -> None:
    """Create a detached tmux session running cmd.

    *env* is exported into the new session's panes through a private file
    (see ``_wrap_cmd_env``).
    """
    _run_with_env(
        _tmux_cmd("new-session", "-d", "-s", name, "-n", "main", "-c", cwd,
                  cmd, socket_path=socket_path),
        env,
        check=True,
    )


def split_pane(session: str, direction: str, cmd: str,
               window: str | None = None,
               env: dict[str, str] | None = None) -> str:
    """Split a pane and run cmd. Returns new pane ID.

    direction: 'h' for horizontal (left/right), 'v' for vertical (top/bottom)
    window: optional tmux window id/name to target. When omitted, splits
        the active pane of the session's active window.
    env: environment variables for the new pane, exported via a private
        file (see ``_wrap_cmd_env``).
    """
    flag = "-h" if direction == "h" else "-v"
    target = f"{session}:{window}" if window else session
    result = _run_with_env(
        _tmux_cmd("split-window", flag, "-t", target, "-P", "-F",
                  "#{pane_id}", cmd),
        env,
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
    _log.info("kill_window: session=%s window=%s", session, window)
    _run(
        _tmux_cmd("kill-window", "-t", f"{session}:{window}"),
    )


def new_window(session: str, name: str, cmd: str, cwd: str,
               switch: bool = True,
               env: dict[str, str] | None = None) -> None:
    """Create a new tmux window with the given name, running cmd.

    Uses 'session:' format to ensure numeric session names aren't
    interpreted as window indices.  Uses -d to avoid switching the base
    session, then switches only the caller's grouped session.

    Set *switch* to False to create the window without changing the
    active window (useful for background operations like the review loop).
    *env* is exported into the new pane through a private file (see
    ``_wrap_cmd_env``).
    """
    # Use session: format to explicitly target session, not window index
    target = f"{session}:"
    _run_with_env(
        _tmux_cmd("new-window", "-d", "-t", target, "-n", name, "-c", cwd,
                  cmd),
        env,
        check=True,
    )
    win = find_window_by_name(session, name)
    _log.info("new_window: session=%s name=%s id=%s index=%s switch=%s",
              session, name,
              (win or {}).get("id"), (win or {}).get("index"), switch)
    if switch and win:
        current = current_or_base_session(session)
        result = _run(
            _tmux_cmd("select-window", "-t", f"{current}:{win['index']}"),
        )
        _log.info("new_window: select-window target=%s:%s rc=%d",
                  current, win["index"], result.returncode)


def new_window_get_pane(session: str, name: str, cmd: str, cwd: str,
                        switch: bool = True,
                        env: dict[str, str] | None = None) -> str | None:
    """Create a new tmux window and return its initial pane ID.

    Like new_window but returns the pane ID so callers can split on it.
    Returns None if the window couldn't be found after creation.

    Set *switch* to False to create the window without changing the
    active window (useful for background operations like the review loop).
    *env* is exported into the new pane through a private file (see
    ``_wrap_cmd_env``).
    """
    target = f"{session}:"
    _run_with_env(
        _tmux_cmd("new-window", "-d", "-t", target, "-n", name, "-c", cwd,
                  cmd),
        env,
        check=True,
    )
    win = find_window_by_name(session, name)
    _log.info("new_window_get_pane: session=%s name=%s id=%s index=%s switch=%s",
              session, name,
              (win or {}).get("id"), (win or {}).get("index"), switch)
    if not win:
        return None
    if switch:
        # Switch the current grouped session to the new window
        current = current_or_base_session(session)
        result = _run(
            _tmux_cmd("select-window", "-t", f"{current}:{win['index']}"),
        )
        _log.info("new_window_get_pane: select-window target=%s:%s rc=%d",
                  current, win["index"], result.returncode)
    # Discover the pane ID
    panes = get_pane_indices(session, win["index"])
    if panes:
        return panes[0][0]
    return None


def create_window(session: str, cmd: str,
                  env: dict[str, str] | None = None) -> tuple[str, str]:
    """Create a new window in *session* running *cmd*.

    Returns ``(pane_id, window_id)`` of the newly created window.
    *env* is exported into the new pane through a private file (see
    ``_wrap_cmd_env``).
    """
    result = _run_with_env(
        _tmux_cmd("new-window", "-t", f"{session}:",
                  "-P", "-F", "#{pane_id} #{window_id}", cmd),
        env,
        text=True, check=True,
    )
    parts = result.stdout.strip().split()
    return parts[0], parts[1]


def split_pane_background(session: str, direction: str, cmd: str,
                          env: dict[str, str] | None = None) -> str:
    """Split a pane without switching focus. Returns new pane ID.

    Like split_pane but uses -d to keep focus on the current pane.
    direction: 'h' for horizontal (left/right), 'v' for vertical (top/bottom)
    *env* is exported into the new pane through a private file (see
    ``_wrap_cmd_env``).
    """
    flag = "-h" if direction == "h" else "-v"
    result = _run_with_env(
        _tmux_cmd("split-window", "-d", flag, "-t", session, "-P", "-F",
                  "#{pane_id}", cmd),
        env,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def split_pane_at(pane_id: str, direction: str, cmd: str,
                  background: bool = False, cwd: str | None = None,
                  env: dict[str, str] | None = None) -> str:
    """Split a specific pane. Returns new pane ID.

    direction: 'h' for horizontal (left/right), 'v' for vertical (top/bottom)
    cwd: starting directory for the new pane. Without this, tmux inherits
        the target pane's current /proc cwd, which can drift if the
        target's shell has been chdir'd by a long-running process
        (e.g. Claude Code's persistent Bash tool).
    *env* is exported into the new pane through a private file (see
    ``_wrap_cmd_env``).
    """
    flag = "-h" if direction == "h" else "-v"
    args = ["split-window", flag, "-t", pane_id, "-P", "-F", "#{pane_id}"]
    if cwd:
        args += ["-c", cwd]
    args.append(cmd)
    if background:
        args.insert(2, "-d")
    result = _run_with_env(_tmux_cmd(*args), env, text=True, check=True)
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


# Set by the popup dispatchers to the session of the client that opened
# the popup; read by get_session_name().
POPUP_SESSION_ENV = "PM_POPUP_SESSION"


def get_session_name() -> str:
    """Get the current tmux session name (must be called from within tmux).

    Uses $TMUX_PANE to target the specific pane, which is more reliable
    than display-message without a target (which uses "current client"
    and can return wrong session in background processes).

    Popups have no pane, so the popup dispatchers (prefix+P / prefix+M)
    export the opening client's session as $PM_POPUP_SESSION; without
    it, "current client" is whichever client was active last, which is
    another client's session when two clients use popups at once.
    """
    pane = os.environ.get("TMUX_PANE")
    popup_session = os.environ.get(POPUP_SESSION_ENV)
    # The variable is inherited by anything the popup spawns, so only
    # trust it while that session still exists ("=" = exact name match).
    if not pane and popup_session and session_exists(f"={popup_session}"):
        return popup_session
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
    """Select (switch to) a window by index or name. Returns True on success.

    Targets the current grouped session so only the caller's terminal switches.
    """
    target = current_or_base_session(session)
    result = _run(
        _tmux_cmd("select-window", "-t", f"{target}:{window}"),
    )
    _log.info("select_window: target=%s:%s rc=%d",
              target, window, result.returncode)
    return result.returncode == 0


def select_window_in_session(session: str, window: str) -> bool:
    """Select a window in a specific (grouped) session, not the calling client's.

    Used by cross-session park: a kill in session A may need to park session B
    on the home window before tmux processes the kill.
    """
    result = _run(
        _tmux_cmd("select-window", "-t", f"{session}:{window}"),
    )
    _log.info("select_window_in_session: target=%s:%s rc=%d",
              session, window, result.returncode)
    return result.returncode == 0


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


def get_pane_option(pane_id: str, name: str) -> str | None:
    """Return a pane-scoped (user) option's value, or None if unset/gone."""
    result = _run(_tmux_cmd("show-options", "-p", "-q", "-v", "-t",
                            pane_id, name), text=True)
    value = result.stdout.strip() if result.returncode == 0 else ""
    return value or None


def set_pane_option(pane_id: str, name: str, value: str) -> None:
    """Set a pane-scoped (user) option; silently ignores a gone pane."""
    _run(_tmux_cmd("set-option", "-p", "-t", pane_id, name, value))


def pane_start_command(pane_id: str) -> str:
    """Return the command a pane was started with, or "" if it is gone."""
    result = _run(_tmux_cmd("display-message", "-p", "-t", pane_id,
                            "#{pane_start_command}"), text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


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


def pane_window_id(pane_id: str,
                   socket_path: str | None = None) -> str | None:
    """Return the window ID (e.g. ``@1``) that contains *pane_id*, or ``None``."""
    result = _run(
        _tmux_cmd("display", "-t", pane_id, "-p", "#{window_id}",
                  socket_path=socket_path),
        text=True,
    )
    return result.stdout.strip() or None


def attached_group_active_windows(base: str, socket_path: str | None = None) -> dict[str, str]:
    """Map attached sessions in a group to active windows in one tmux query.

    Used by the popup picker to show which windows a *collaborator* is
    currently viewing.  An unattached session (e.g. the base session when
    the TUI runs in grouped sessions) has an "active window" in tmux's
    bookkeeping but no client focusing it, so it is omitted.  Returns an
    empty map on any tmux error.

    The separator must be printable: tmux rewrites control characters in
    format output to ``_`` when the server runs under a non-UTF-8 locale
    (``LC_ALL=C``), which silently turned a tab-separated query into one
    unparsable field.  The session name comes last (``maxsplit=2``) so it
    may itself contain the separator.
    """
    result = _run(
        _tmux_cmd("list-sessions", "-F",
                  "#{session_attached}|#{window_id}|#{session_name}",
                  socket_path=socket_path),
        text=True,
    )
    if result.returncode != 0:
        return {}
    active = {}
    for line in result.stdout.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        attached, wid, name = parts
        if (name == base or name.startswith(base + "~")) and attached.isdigit():
            if int(attached) > 0 and wid:
                active[name] = wid
    return active


def sessions_on_window(base: str, window_id: str,
                       socket_path: str | None = None) -> list[str]:
    """Return all sessions in the group (base + grouped) whose active window matches *window_id*.

    Used by the review loop to determine which sessions need to be
    switched to the replacement window after the old one is killed, and by
    ``detach_current_client`` to find the sessions whose clients are
    looking at a given window.
    """
    candidates = [base] + list_grouped_sessions(base, socket_path=socket_path)
    _log.info("sessions_on_window: base=%s window_id=%s candidates=%s", base, window_id, candidates)
    result = []
    for name in candidates:
        r = _run(
            _tmux_cmd("display", "-t", name, "-p", "#{window_id}",
                      socket_path=socket_path),
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
    """Switch the given sessions to the named window.

    Used after killing and recreating a window (review, watcher, etc.)
    to move sessions that were watching the old window to the new one.

    ``select-window`` alone does NOT update tmux's client tracking.
    ``switch-client`` to the same session is a visible no-op but
    triggers tmux to recalculate the window size for the correct display.
    """
    _log.info("switch_sessions_to_window: sessions=%s session=%s window_name=%s",
               sessions, session, window_name)
    if not sessions:
        _log.info("switch_sessions_to_window: no sessions, returning")
        return
    win = find_window_by_name(session, window_name)
    if not win:
        _log.warning("switch_sessions_to_window: window '%s' not found!", window_name)
        return
    _log.info("switch_sessions_to_window: found window %s (index=%s)", win["id"], win["index"])

    # Map session names → client TTYs for switch-client.
    client_map: dict[str, str] = {}
    r = _run(
        _tmux_cmd("list-clients", "-F", "#{session_name} #{client_tty}"),
        text=True,
    )
    if r.returncode == 0:
        for line in r.stdout.strip().splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                client_map[parts[0]] = parts[1]
    _log.info("switch_sessions_to_window: client_map=%s", client_map)

    for sess_name in sessions:
        sel_r = _run(
            _tmux_cmd("select-window", "-t", f"{sess_name}:{win['index']}"),
        )
        _log.info("switch_sessions_to_window: select-window -t %s:%s → rc=%d",
                   sess_name, win["index"], sel_r.returncode)
        client_tty = client_map.get(sess_name)
        if client_tty:
            sw_r = _run(
                _tmux_cmd("switch-client", "-t", sess_name, "-c", client_tty),
            )
            _log.info("switch_sessions_to_window: switch-client -t %s -c %s → rc=%d",
                       sess_name, client_tty, sw_r.returncode)
        else:
            _log.warning("switch_sessions_to_window: no client_tty for %s, skipping switch-client", sess_name)


def set_environment(session: str, key: str, value: str, socket_path: str | None = None) -> None:
    """Set an environment variable in a tmux session."""
    _run(
        _tmux_cmd("set-environment", "-t", session, key, value,
                   socket_path=socket_path),
    )


def get_session_environment(session: str, key: str,
                            socket_path: str | None = None) -> str | None:
    """Return *key* from a tmux session's environment, or ``None``.

    ``None`` covers both "the variable is not set" (tmux reports that as a
    non-zero exit) and "the session/server cannot be queried", so callers
    treat an unknown value the same as an absent one.
    """
    try:
        result = _run(
            _tmux_cmd("show-environment", "-t", session, key,
                      socket_path=socket_path),
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    # Output is ``KEY=value``; tmux prints ``-KEY`` for a variable marked
    # for removal, which counts as unset.
    line = result.stdout.strip()
    prefix = f"{key}="
    return line[len(prefix):] if line.startswith(prefix) else None


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


def set_global_environment(key: str, value: str,
                           socket_path: str | None = None) -> None:
    """Set a variable in the server's global environment.

    ``run-shell`` hooks and popups inherit the server environment; setting
    PM_TMUX_SOCKET there makes the routing contract explicit rather than
    relying solely on ``$TMUX`` being present.
    """
    _run(
        _tmux_cmd("set-environment", "-g", key, value,
                  socket_path=socket_path),
    )


def _int_or_zero(value: str) -> int:
    """Parse a tmux numeric format field, tolerating empty/garbage output."""
    try:
        return int(value or 0)
    except ValueError:
        return 0


def detach_current_client(socket_path: str | None = None) -> bool:
    """Detach the client that is viewing the current pane's window.

    ``detach-client`` with no target detaches the most recently active
    client on the *server*, which is how a QA session once detached the
    user from an unrelated pm session (pr-073910f).  Resolve the client
    precisely instead:

    1. Find the current pane's window from ``$TMUX_PANE``.
    2. Keep clients attached to the base/grouped sessions whose active
       window is that window.
    3. Detach the most recently active one by TTY.

    Returns True when a client was detached.  Never issues a bare
    ``detach-client``.  Returns False (rather than raising) when tmux
    cannot be run: ``quit_app`` calls this from the TUI's key handler, and
    a missing/unexecutable tmux must degrade to "nothing to detach" like
    every other probe in this module.
    """
    try:
        return _detach_current_client(socket_path)
    except OSError:
        _log.warning("detach_current_client: tmux cannot be run; "
                     "leaving clients attached")
        return False


def _detach_current_client(socket_path: str | None) -> bool:
    """Implementation of :func:`detach_current_client` (may raise OSError)."""
    pane = os.environ.get("TMUX_PANE")
    if not pane:
        return False

    pane_win = pane_window_id(pane, socket_path=socket_path) or ""

    session_r = _run(
        _tmux_cmd("display-message", "-p", "-t", pane, "#{session_name}",
                  socket_path=socket_path),
        text=True,
    )
    session = session_r.stdout.strip() if session_r.returncode == 0 else ""
    if not session:
        return False
    base = session.split("~", 1)[0]
    grouped = list_grouped_sessions(base, socket_path=socket_path)
    group = {base} | set(grouped)
    # Clients viewing the TUI's window: the group's sessions whose active
    # window is that window (a grouped session has its own current window,
    # so this is per session, not per client).  With no resolvable pane
    # window, any session in the group counts.
    viewing = (set(sessions_on_window(base, pane_win, socket_path=socket_path))
               if pane_win else group)

    result = _run(
        _tmux_cmd("list-clients", "-F",
                  "#{client_tty}|#{client_activity}|#{client_created}"
                  "|#{client_session}",
                  socket_path=socket_path),
        text=True,
    )
    candidates: list[tuple[int, int, str]] = []
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            parts = line.split("|", 3)
            if len(parts) != 4:
                continue
            tty, activity, created, client_session = parts
            if client_session not in viewing:
                continue
            candidates.append((_int_or_zero(activity),
                               _int_or_zero(created), tty))

    if candidates:
        tty = max(candidates)[2]
        detached = _run(_tmux_cmd("detach-client", "-t", tty,
                                  socket_path=socket_path), text=True)
        if detached.returncode == 0:
            _log.info(
                "detach_current_client: detached %s (session %s, window %s)",
                tty, session, pane_win)
            return True
        # Report failure rather than claiming a detach that did not happen
        # (the client may have exited between list-clients and
        # detach-client).  ``quit_app`` uses the result only for logging.
        _log.warning("detach_current_client: detach of %s failed: %s",
                     tty, detached.stderr)
        return False

    # No client currently views the TUI's window (e.g. a stale window id).
    # Detach the client attached to the group's session instead of using
    # the server-wide default.
    for name in [session, *grouped]:
        att = _run(
            _tmux_cmd("display-message", "-t", name, "-p",
                      "#{session_attached}", socket_path=socket_path),
            text=True,
        )
        if att.returncode == 0 and att.stdout.strip() not in ("", "0"):
            detached = _run(_tmux_cmd("detach-client", "-s", name,
                                      socket_path=socket_path), text=True)
            if detached.returncode == 0:
                _log.info("detach_current_client: detached client of %s", name)
                return True
            _log.warning("detach_current_client: detach of %s failed: %s",
                         name, detached.stderr)

    _log.info("detach_current_client: no attached client for %s", session)
    return False


def list_pm_sessions() -> list[dict]:
    """List pm sessions across every pm tmux server.

    Scans the per-session sockets under ``/tmp/pm-sessions/`` plus the
    default server (legacy pre-isolation sessions).  Grouped sessions are
    collapsed into their base session; ``attached`` is the sum of clients
    across the group.  Unreadable/stale sockets are skipped.

    Each row: ``{"name", "socket", "attached", "shared"}`` where ``socket``
    is None for sessions on the default server and ``shared`` is true when
    the socket is group/world accessible (``--global``/``--group``
    sessions chmod it; private servers are 0600).
    """
    from pm_core.paths import SHARED_SOCKET_DIR, default_socket_path

    def is_shared(sock: Path | None) -> bool:
        if sock is None:
            return False
        try:
            # lstat for the same reason as the scan below: never read a
            # symlink's target as if it were this entry's mode.
            return bool(sock.lstat().st_mode & 0o077)
        except OSError:
            return False

    rows: list[dict] = []
    seen: set[tuple[str | None, str]] = set()

    def collect(socket_path: str | None) -> None:
        """Collect one server; ``socket_path=None`` means the default one."""
        # Address the default server explicitly: tmux would otherwise
        # follow $TMUX and list the private server this process runs on.
        cmd_socket = socket_path or str(default_socket_path())
        try:
            result = _run(
                _tmux_cmd("list-sessions", "-F",
                          "#{session_name}|#{session_attached}",
                          socket_path=cmd_socket),
                text=True,
            )
        except OSError:
            # tmux missing/unexecutable: nothing to report, and discovery
            # must degrade rather than crash (see find_session_server).
            _log.debug("list_pm_sessions: tmux cannot run, skipping %s",
                       cmd_socket)
            return
        if result.returncode != 0:
            # Stale socket (server exited), another user's socket, or no
            # default server running: not fatal, just nothing to report.
            _log.debug("list_pm_sessions: skipping %s: %s",
                       cmd_socket, result.stderr.strip())
            return
        groups: dict[str, int] = {}
        for line in result.stdout.splitlines():
            name, sep, attached = line.rpartition("|")
            if not sep or not name.startswith("pm-"):
                continue
            base = name.split("~", 1)[0]
            groups[base] = groups.get(base, 0) + _int_or_zero(attached)
        shared = is_shared(Path(socket_path) if socket_path else None)
        for base, attached in sorted(groups.items()):
            key = (socket_path, base)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"name": base, "socket": socket_path,
                         "attached": attached, "shared": shared})

    try:
        sockets = sorted(SHARED_SOCKET_DIR.glob("pm-*"))
    except OSError:
        sockets = []
    for sock in sockets:
        # lstat, not is_socket(): the socket directory is world-writable, so
        # a symlink another user plants there must not be followed — it
        # would make their target look like one of our servers.
        try:
            mode = sock.lstat().st_mode
        except OSError:
            _log.debug("list_pm_sessions: skipping unreadable %s", sock)
            continue
        if not stat.S_ISSOCK(mode):
            _log.debug("list_pm_sessions: skipping non-socket %s", sock)
            continue
        collect(str(sock))

    collect(None)
    return rows
