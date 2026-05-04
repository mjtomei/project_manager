"""Session commands for the pm CLI.

Registers the ``session`` group and all subcommands, plus internal
pane/window management commands and session registry commands.
"""

import functools
import os
import shlex
import subprocess
from pathlib import Path

import click

from pm_core import store, notes, guide
from pm_core import tmux as tmux_mod
from pm_core import pane_layout
from pm_core import pane_registry
from pm_core.claude_launcher import find_editor

from pm_core.cli import cli
from pm_core.cli.helpers import (
    _get_current_pm_session,
    _get_session_name_for_cwd,
    _log,
    _set_share_mode_env,
    state_root,
)


def _share_mode_options(f):
    """Add --global/--group options that set PM_SHARE_MODE when specified.

    Used on both the session group and subcommands (tag, kill) so the
    flags work in either position: ``pm session --global tag`` or
    ``pm session tag --global``.  Only overrides the env var if the
    decorated command's own flags are set, so parent-group values
    propagate through to subcommands that don't specify them.
    """
    @click.option("--global", "share_global", is_flag=True, default=False,
                  help="Target a globally shared session")
    @click.option("--group", "share_group", type=str, default=None,
                  help="Target a group-shared session")
    @functools.wraps(f)
    def wrapper(*args, share_global=False, share_group=None, **kwargs):
        if share_global or share_group:
            _set_share_mode_env(share_global, share_group)
        return f(*args, **kwargs)
    return wrapper


# Shell bodies for the popup bindings.  Query tmux from inside the popup
# shell to resolve session/window — tmux's expansion of #{session_name}
# in display-popup arguments (both shell-command and -e values) is
# unreliable across versions, so we let the popup's shell call tmux
# itself.  The trailing failure handler pauses on launch failure (e.g.
# pm not on PATH) so the popup stays visible long enough to read the
# error instead of vanishing instantly with display-popup -E.
_POPUP_PICKER_BODY = (
    'S=$(tmux display-message -p "#{session_name}");'
    ' W=$(tmux display-message -p "#{window_name}");'
    ' pm _popup-picker "$S" "$W"'
    " || { echo; echo 'pm popup failed (exit '$?').';"
    " read -n 1 -s -r -p 'Press any key to close...'; }"
)
_POPUP_CMD_BODY = (
    'S=$(tmux display-message -p "#{session_name}");'
    ' pm _popup-cmd "$S"'
    " || { echo; echo 'pm popup failed (exit '$?').';"
    " read -n 1 -s -r -p 'Press any key to close...'; }"
)


_POPUP_KINDS = {
    # kind -> (height, body)
    "picker": ("80%", _POPUP_PICKER_BODY),
    "cmd": ("50%", _POPUP_CMD_BODY),
}


def _bind_popups() -> None:
    """Bind prefix+P and prefix+M to dynamic-resolve popup launchers.

    The bindings are static — they invoke ``pm _popup-show <kind>``,
    which resolves the right ``-w`` at trigger time based on the
    smallest attached-client width.  No rebinding on resize, no stale
    state, no tmux-parser quoting fragility.
    """
    subprocess.run(tmux_mod._tmux_cmd("bind-key", "-T", "prefix", "P",
             "run-shell", "pm _popup-show picker"),
            check=False)
    subprocess.run(tmux_mod._tmux_cmd("bind-key", "-T", "prefix", "M",
             "run-shell", "pm _popup-show cmd"),
            check=False)


def _register_tmux_bindings(session_name: str) -> None:
    """Register tmux keybindings and session options for pm.

    Called on both new session creation and reattach so bindings
    survive across sessions (tmux bindings are global).
    For shared sessions (--global/--group), sets window-size=smallest on
    all sessions in the group so the window fits the smallest connected
    client (everyone sees the full layout).
    """
    # Only set window-size=smallest for shared sessions where multiple
    # users may connect simultaneously.  For normal (non-shared) sessions
    # the default tmux window-size is fine and avoids issues with the
    # unattached base session contributing a zero size.
    if os.environ.get("PM_SHARE_MODE"):
        base = session_name.split("~")[0]
        for s in [base] + tmux_mod.list_grouped_sessions(base):
            tmux_mod.set_session_option(s, "window-size", "smallest")

    subprocess.run(tmux_mod._tmux_cmd("bind-key", "-T", "prefix", "R",
             "run-shell 'pm rebalance'"), check=False)
    # Conditionally override pane-switch keys: use pm's mobile-aware
    # switch for pm sessions, fall back to default tmux behavior otherwise.
    # Keyed on the pane registry file existing for the current session.
    registry_dir = pane_registry.registry_dir()
    switch_keys = {
        "o": ("next", "select-pane -t :.+"),
        "Up": ("-U", "select-pane -U"),
        "Down": ("-D", "select-pane -D"),
        "Left": ("-L", "select-pane -L"),
        "Right": ("-R", "select-pane -R"),
    }
    for key, (direction, fallback) in switch_keys.items():
        subprocess.run(tmux_mod._tmux_cmd("bind-key", "-T", "prefix", key,
                 "if-shell",
                 f"s='#{{session_name}}'; test -f {registry_dir}/${{s%%~*}}.json",
                 f"run-shell 'pm _pane-switch #{{session_name}} {direction}'",
                 fallback),
                check=False)
    subprocess.run(tmux_mod._tmux_cmd("set-hook", "-g", "after-kill-pane",
             "run-shell 'pm _pane-closed'"), check=False)
    subprocess.run(tmux_mod._tmux_cmd("set-hook", "-gw", "after-split-window",
             "run-shell 'pm _pane-opened \"#{session_name}\" \"#{window_id}\" \"#{pane_id}\"'"),
            check=False)
    # Auto-rebalance when window resizes (triggered by clients connecting/
    # disconnecting with window-size=smallest, or moving terminal to a different monitor).
    # Uses "window-resized" (fires on any window size change) not
    # "after-resize-window" (only fires after the resize-window command).
    # Note: window-resized is a window hook, so use -gw not -g.
    subprocess.run(tmux_mod._tmux_cmd("set-hook", "-gw", "window-resized",
             "run-shell 'pm _window-resized \"#{session_name}\" \"#{window_id}\"'"),
            check=False)
    # Also rebalance on window switch.  With aggressive-resize on (or when
    # different windows have different pane layouts), tmux defers the
    # resize until the next input event after a switch — panes appear
    # stale until the user presses a key.  Hooking after-select-window
    # forces a rebalance immediately so the new window renders at the
    # current client size.  The _window-resized handler is debounced and
    # no-ops when the size hasn't actually changed, so this is cheap on
    # plain window switches.
    subprocess.run(tmux_mod._tmux_cmd("set-hook", "-gw", "after-select-window",
             "run-shell 'pm _window-resized \"#{session_name}\" \"#{window_id}\"'"),
            check=False)
    # Client-level hooks for the same staleness symptom on cross-session
    # switches and on attach/detach (which can change the smallest-client
    # window size when window-size=smallest is set).  Same handler — the
    # debounce keeps it cheap when nothing actually changed.
    for client_hook in ("client-session-changed", "client-attached",
                        "client-detached"):
        subprocess.run(tmux_mod._tmux_cmd("set-hook", "-g", client_hook,
                 "run-shell 'pm _window-resized \"#{session_name}\" \"#{window_id}\"'"),
                check=False)
    # Clean up stale hook from earlier versions that used the wrong name
    subprocess.run(tmux_mod._tmux_cmd("set-hook", "-gu", "after-resize-window"),
            check=False)

    # Popup bindings: PR action picker (prefix+P) and pm command runner
    # (prefix+M).  Width is resolved dynamically by ``pm _popup-show``
    # at trigger time — see that command and the _bind_popups() helper.
    _bind_popups()


def _schedule_rebalance(session_name: str) -> None:
    """Spawn a background process to rebalance all windows after a short delay.

    Used on session reconnect: ``attach()`` blocks, so we schedule the
    rebalance beforehand.  The delay gives the client time to attach and
    the window to resize before we recompute the layout.
    """
    import sys
    windows = tmux_mod.list_windows(session_name)
    if not windows:
        return
    window_ids = [w["id"] for w in windows]
    # Build a Python one-liner that rebalances every window
    rebalance_calls = "; ".join(
        f"rebalance({session_name!r}, {wid!r})" for wid in window_ids
    )
    subprocess.Popen(
        [sys.executable, "-c",
         "import time; time.sleep(0.5); "
         "from pm_core.pane_layout import rebalance; "
         + rebalance_calls],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _log.info("scheduled background rebalance for %d window(s)", len(window_ids))


def _session_start(share_global: bool = False, share_group: str | None = None,
                   start_dir: str | None = None,
                   disconnect_others: bool = False):
    """Start a tmux session with TUI + notes editor.

    If no project exists yet, starts pm guide instead of the TUI so
    the guided workflow can initialize the project inside tmux.

    Args:
        share_global: Make session accessible to all users on the system.
        share_group: Make session accessible to this Unix group.
        start_dir: Compute session tag from this directory instead of cwd.
                   Used when joining another user's shared session.
        disconnect_others: Detach all other clients from the session group
                          before attaching.
    """
    _log.info("session_cmd started")
    # Install Claude Code hooks so idle_prompt / Stop events can drive
    # pm's verdict detection without pane polling.  Conflicts with
    # existing third-party hooks abort the session so the user can
    # resolve the conflict rather than having pm silently step on it.
    from pm_core.hook_install import ensure_hooks_installed, HookConflictError
    try:
        ensure_hooks_installed()
    except HookConflictError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    if not tmux_mod.has_tmux():
        click.echo("tmux is required for 'pm session'. Install it first.", err=True)
        raise SystemExit(1)

    is_shared = share_global or share_group is not None

    # Set PM_SHARE_MODE so get_session_tag produces distinct hashes per mode
    _set_share_mode_env(share_global, share_group)

    # Validate group exists before doing anything else
    if share_group:
        import grp as _grp
        try:
            _grp.getgrnam(share_group)
        except KeyError:
            click.echo(f"Unix group '{share_group}' does not exist.", err=True)
            raise SystemExit(1)

    # Compute socket path for shared sessions
    socket_path: str | None = None
    if is_shared:
        from pm_core.paths import get_session_tag, shared_socket_path, ensure_shared_socket_dir
        tag = get_session_tag(start_path=Path(start_dir) if start_dir else None)
        if not tag:
            click.echo("Cannot determine session tag (not in a git repo?).", err=True)
            raise SystemExit(1)
        ensure_shared_socket_dir()
        socket_path = str(shared_socket_path(tag))
        # Set env var so _tmux_cmd() in all subsequent calls (split_pane,
        # get_window_id, rebalance, etc.) routes to the shared server.
        os.environ["PM_TMUX_SOCKET"] = socket_path

    # Check if project exists
    try:
        root = state_root()
        data = store.load(root)
        has_project = True
    except (FileNotFoundError, SystemExit):
        root = None
        data = None
        has_project = False

    # Generate session name with path hash (uses helper to ensure consistency)
    # Use the repo directory (parent of pm/) as the working directory
    if root and store.is_internal_pm_dir(root):
        cwd = str(root.parent)
    else:
        cwd = str(root) if root else str(Path.cwd())

    if start_dir:
        # When joining another user's session, compute session name from their directory
        from pm_core.paths import get_session_tag
        tag = get_session_tag(start_path=Path(start_dir))
        if tag:
            session_name = f"pm-{tag}"
        else:
            click.echo(f"Cannot determine session from directory '{start_dir}'.", err=True)
            raise SystemExit(1)
    else:
        # Prefer the actual tmux session if we're already inside one (e.g. meta
        # workdirs whose git-root hash differs from the session they belong to).
        session_name = _get_current_pm_session() or _get_session_name_for_cwd()

    expected_root = root or (Path.cwd() / "pm")
    notes_path = expected_root / notes.NOTES_FILENAME

    _log.info("checking if session exists: %s (socket=%s)", session_name, socket_path)
    if tmux_mod.session_exists(session_name, socket_path=socket_path):
        # Check if the session has the expected panes
        live_panes = tmux_mod.get_pane_indices(session_name)
        registry = pane_registry.load_registry(session_name)
        all_registered = [p for _, p in pane_registry._iter_all_panes(registry)]

        # Find which registered panes are still alive
        live_pane_ids = {p[0] for p in live_panes}
        roles_alive = {p["role"] for p in all_registered if p["id"] in live_pane_ids}

        _log.info("session exists: %s", session_name)
        _log.info("roles_alive: %s", roles_alive)

        # If TUI is missing, respawn it rather than killing the session
        if "tui" not in roles_alive:
            _log.info("TUI missing, respawning in existing session")
            click.echo("TUI pane missing — respawning...")
            # Find the window where TUI was registered (or fall back to first window)
            tui_window = None
            for wid, wdata in registry.get("windows", {}).items():
                for p in wdata.get("panes", []):
                    if p.get("role") == "tui":
                        tui_window = wid
                        break
                if tui_window:
                    break
            if not tui_window:
                # Fall back to window named 'main' (or first window) rather
                # than the active window, which may be a QA/work window.
                main_win = tmux_mod.find_window_by_name(session_name, "main")
                if main_win:
                    tui_window = main_win["id"]
                else:
                    all_wins = tmux_mod.list_windows(session_name)
                    if all_wins:
                        tui_window = all_wins[0]["id"]
            if tui_window:
                pane_layout._respawn_tui(session_name, tui_window)
                pane_layout.rebalance(session_name, tui_window)
            else:
                _log.warning("TUI respawn failed — no windows found in session")
                click.echo("Could not respawn TUI (no windows). "
                           "Kill the session manually and re-run pm session.",
                           err=True)

        if tmux_mod.session_exists(session_name, socket_path=socket_path):
            _log.info("TUI present, finding/creating grouped session")
            _register_tmux_bindings(session_name)
            # Reuse an unattached grouped session, or create a new one
            grouped = tmux_mod.find_unattached_grouped_session(
                session_name, socket_path=socket_path)
            if grouped:
                _log.info("reusing unattached grouped session: %s", grouped)
                click.echo(f"Attaching to session '{grouped}'...")
            else:
                grouped = tmux_mod.next_grouped_session_name(
                    session_name, socket_path=socket_path)
                _log.info("creating new grouped session: %s", grouped)
                tmux_mod.create_grouped_session(session_name, grouped,
                                                socket_path=socket_path)
                if os.environ.get("PM_SHARE_MODE"):
                    tmux_mod.set_session_option(grouped, "window-size", "smallest",
                                                socket_path=socket_path)
                click.echo(f"Attaching to session '{grouped}'...")
            # Disconnect other clients if requested (before attaching so
            # window-size recalculates based only on our terminal).
            if disconnect_others:
                clients = tmux_mod.list_clients_in_group(
                    session_name, socket_path=socket_path)
                if clients:
                    _log.info("disconnecting %d other client(s)", len(clients))
                    for c in clients:
                        _log.info("detaching client %s (session %s)",
                                  c["tty"], c["session"])
                        tmux_mod.detach_client(c["tty"],
                                               socket_path=socket_path)
                    click.echo(f"Disconnected {len(clients)} other client(s).")

            # Schedule a background rebalance so the layout adapts to
            # the new client's terminal size on reconnect.  attach()
            # blocks, so we spawn a background process beforehand that
            # waits for the client to attach and then rebalances.
            _schedule_rebalance(session_name)
            tmux_mod.attach(grouped, socket_path=socket_path)
            return

    # If --dir was specified, the session must already exist (we're joining, not creating)
    if start_dir:
        click.echo(f"No shared session '{session_name}' found to join.", err=True)
        click.echo("The session owner must start it first.", err=True)
        raise SystemExit(1)

    _log.info("session does not exist or was killed, creating new session")
    editor = find_editor()

    # Clear stale pane registry and bump generation to invalidate old EXIT traps
    import time as _time
    generation = str(int(_time.time()))
    pane_registry.locked_read_modify_write(
        pane_registry.registry_path(session_name),
        lambda _old: {"session": session_name, "windows": {}, "generation": generation},
    )

    # Always create session with TUI in the left pane
    _log.info("creating tmux session: %s cwd=%s socket=%s", session_name, cwd, socket_path)
    click.echo(f"Creating tmux session '{session_name}'...")
    # For shared sessions, set PM_TMUX_SOCKET in the initial command so the TUI
    # process inherits it immediately (set-environment only affects new processes)
    tui_cmd = "pm _tui"
    tui_env_prefix = ""
    if socket_path:
        tui_env_prefix += f"PM_TMUX_SOCKET={shlex.quote(socket_path)} "
    share_mode = os.environ.get("PM_SHARE_MODE")
    if share_mode:
        tui_env_prefix += f"PM_SHARE_MODE={shlex.quote(share_mode)} "
    if tui_env_prefix:
        tui_cmd = f"{tui_env_prefix}pm _tui"
    tmux_mod.create_session(session_name, cwd, tui_cmd, socket_path=socket_path)

    # Set socket permissions and grant tmux server-access for shared sessions
    if is_shared and socket_path:
        from pm_core.paths import set_shared_socket_permissions, get_share_users
        try:
            set_shared_socket_permissions(Path(socket_path), group_name=share_group)
            users = get_share_users(group_name=share_group)
            if users:
                tmux_mod.grant_server_access(users, socket_path=socket_path)
            mode_desc = f"group '{share_group}'" if share_group else "all users"
            click.echo(f"Session shared with {mode_desc}.")
        except (PermissionError, OSError) as e:
            click.echo(f"Warning: Could not set socket permissions: {e}", err=True)

    # Forward key environment variables into the tmux session
    for env_key in ("PM_PROJECT", "EDITOR", "PATH"):
        val = os.environ.get(env_key)
        if val:
            tmux_mod.set_environment(session_name, env_key, val,
                                     socket_path=socket_path)

    # For shared sessions, set PM_TMUX_SOCKET so all pm commands inside
    # the session automatically route to the correct tmux server
    if socket_path:
        tmux_mod.set_environment(session_name, "PM_TMUX_SOCKET", socket_path,
                                 socket_path=socket_path)

    # Propagate PM_SHARE_MODE so subprocesses (rebalance, pane-switch, etc.)
    # compute the same session tag as the parent
    if share_mode:
        tmux_mod.set_environment(session_name, "PM_SHARE_MODE", share_mode,
                                 socket_path=socket_path)

    # Get the TUI pane ID and window ID
    _pane_lines = subprocess.run(
        tmux_mod._tmux_cmd("list-panes", "-t", session_name, "-F", "#{pane_id}",
                            socket_path=socket_path),
        capture_output=True, text=True,
    ).stdout.strip().splitlines()
    if not _pane_lines:
        click.echo("Failed to detect TUI pane after session creation.", err=True)
        raise SystemExit(1)
    tui_pane = _pane_lines[0]
    window_id = tmux_mod.get_window_id(session_name)
    _log.info("created tui_pane=%s window_id=%s", tui_pane, window_id)

    # Register TUI pane in layout registry
    pane_registry.register_pane(session_name, window_id, tui_pane, "tui", "pm _tui")

    def _wrap(cmd: str) -> str:
        """Wrap a pane command in bash with an EXIT trap for rebalancing."""
        escaped = cmd.replace("'", "'\\''")
        return (f"bash -c 'trap \"pm _pane-exited {session_name} {window_id} {generation} $TMUX_PANE\" EXIT; "
                f"{escaped}'")

    # Only auto-start the notes pane when the guide will NOT auto-launch.
    # Having both the guide and notes panes open overwhelms the initial layout.
    if not guide.needs_guide(root):
        _log.info("guide will not auto-launch, creating notes pane")
        notes.ensure_notes_file(root)
        notes_pane = tmux_mod.split_pane(session_name, "h", _wrap(f"pm notes {notes_path}"))
        pane_registry.register_pane(session_name, window_id, notes_pane, "notes", "pm notes")
        _log.info("created notes_pane=%s", notes_pane)
    else:
        _log.info("guide will auto-launch, skipping notes pane")

    # Apply initial balanced layout
    pane_layout.rebalance(session_name, window_id)
    _log.info("rebalanced layout, attaching to session")

    # If mobile mode, start zoomed into TUI
    if pane_layout.is_mobile(session_name, window_id):
        _log.info("mobile mode detected, zooming TUI pane")
        tmux_mod.zoom_pane(tui_pane)

    _register_tmux_bindings(session_name)

    # Create a grouped session so we never attach directly to the base
    grouped = f"{session_name}~1"
    tmux_mod.create_grouped_session(session_name, grouped, socket_path=socket_path)
    if os.environ.get("PM_SHARE_MODE"):
        tmux_mod.set_session_option(grouped, "window-size", "smallest",
                                    socket_path=socket_path)
    tmux_mod.attach(grouped, socket_path=socket_path)


@cli.group(invoke_without_command=True)
@click.option("--global", "share_global", is_flag=True, default=False,
              help="Share session with all users on the system")
@click.option("--group", "share_group", type=str, default=None,
              help="Share session with a Unix group")
@click.option("--dir", "start_dir", type=click.Path(exists=True, file_okay=False),
              default=None, help="Project directory (for joining another user's session)")
@click.option("--print-connect", is_flag=True, default=False,
              help="Print the tmux command others can use to connect (no pm required)")
@click.option("--disconnect-others", "-d", is_flag=True, default=False,
              help="Detach all other clients before attaching (reclaim window sizing)")
@click.pass_context
def session(ctx, share_global, share_group, start_dir, print_connect, disconnect_others):
    """Manage tmux sessions for pm.

    Without a subcommand, starts or attaches to the pm session.

    Use --global or --group to create a session accessible by other users.
    Other users join with the same flag plus --dir pointing to the original
    user's project directory.
    """
    # Propagate --global/--group to env when explicitly set so
    # subcommands (tag, kill, etc.) inherit the flags.  When neither
    # flag is given, leave the env var untouched — it may already be
    # inherited from the tmux session environment inside shared sessions.
    if share_global or share_group:
        _set_share_mode_env(share_global, share_group)
    if ctx.invoked_subcommand is not None:
        return
    if print_connect:
        # Check PM_TMUX_SOCKET (set inside shared sessions) or compute from flags
        sp = os.environ.get("PM_TMUX_SOCKET")
        if not sp and (share_global or share_group):
            from pm_core.paths import get_session_tag, shared_socket_path
            tag = get_session_tag(start_path=Path(start_dir) if start_dir else None)
            if tag:
                sp = str(shared_socket_path(tag))
        if sp:
            click.echo(f"tmux -S {sp} attach")
        else:
            click.echo("Not in a shared session and no --global/--group given.", err=True)
            raise SystemExit(1)
        return
    if start_dir and not (share_global or share_group):
        click.echo("--dir requires --global or --group", err=True)
        raise SystemExit(1)
    if share_global and share_group:
        click.echo("--global and --group are mutually exclusive", err=True)
        raise SystemExit(1)
    _session_start(share_global=share_global, share_group=share_group,
                   start_dir=start_dir, disconnect_others=disconnect_others)


@session.command("name")
def session_name_cmd():
    """Print the computed session name for the current directory."""
    click.echo(_get_session_name_for_cwd())

@session.command("tag")
@_share_mode_options
def session_tag_cmd():
    """Print the computed session tag for the current directory."""
    from pm_core.paths import get_session_tag
    click.echo(get_session_tag())


@session.command("kill")
@_share_mode_options
@click.option("--dir", "start_dir", type=click.Path(exists=True, file_okay=False),
              default=None, help="Project directory of the shared session")
def session_kill(start_dir):
    """Kill the pm tmux session for this project."""
    if not tmux_mod.has_tmux():
        click.echo("tmux is not installed.", err=True)
        raise SystemExit(1)

    is_shared = bool(os.environ.get("PM_SHARE_MODE"))
    socket_path: str | None = None
    if is_shared:
        from pm_core.paths import get_session_tag, shared_socket_path
        tag = get_session_tag(start_path=Path(start_dir) if start_dir else None)
        if tag:
            socket_path = str(shared_socket_path(tag))

    if start_dir:
        from pm_core.paths import get_session_tag
        tag = get_session_tag(start_path=Path(start_dir))
        session_name = f"pm-{tag}" if tag else _get_session_name_for_cwd()
    else:
        session_name = _get_session_name_for_cwd()

    if not tmux_mod.session_exists(session_name, socket_path=socket_path):
        click.echo(f"No session '{session_name}' found.", err=True)
        raise SystemExit(1)

    # Kill grouped sessions first, then the base
    for g in tmux_mod.list_grouped_sessions(session_name, socket_path=socket_path):
        tmux_mod.kill_session(g, socket_path=socket_path)
    tmux_mod.kill_session(session_name, socket_path=socket_path)
    pane_layout.set_force_mobile(session_name, False)

    # Clean up containers and push proxies belonging to this session
    session_tag = session_name.removeprefix("pm-")
    if session_tag:
        from pm_core.container import cleanup_session_containers
        from pm_core.push_proxy import stop_session_proxies
        n_containers = cleanup_session_containers(session_tag)
        n_proxies = stop_session_proxies(session_tag)
        if n_containers or n_proxies:
            _log.info("Session kill cleanup: %d container(s), %d proxy(ies)",
                      n_containers, n_proxies)

    # Clean up shared socket file
    if socket_path:
        try:
            Path(socket_path).unlink(missing_ok=True)
        except OSError:
            pass

    click.echo(f"Killed session '{session_name}'.")


@session.command("mobile")
@click.option("--force/--no-force", default=None, help="Force mobile mode on/off")
def session_mobile(force: bool | None):
    """Show or toggle mobile mode for the current session.

    Mobile mode auto-zooms the active pane on every pane switch,
    making the tool usable on narrow terminals (< 120 cols).
    """
    session_name = _get_session_name_for_cwd()

    if force is not None:
        pane_layout.set_force_mobile(session_name, force)
        state = "enabled" if force else "disabled"
        click.echo(f"Mobile mode force-{state} for '{session_name}'.")
        # Trigger rebalance if in tmux
        if tmux_mod.in_tmux():
            window = tmux_mod.get_window_id(session_name)
            all_windows = tmux_mod.list_windows(session_name)
            if not force:
                # Exiting mobile: unzoom all windows
                for w in all_windows:
                    tmux_mod.unzoom_pane(session_name, w["index"])
            else:
                # Entering mobile: unzoom current window before rebalance
                tmux_mod.unzoom_pane(session_name, window)

            def _reset_all_user_modified(raw):
                data = pane_registry._prepare_registry_data(raw, session_name)
                for wdata in data.get("windows", {}).values():
                    wdata["user_modified"] = False
                return data

            pane_registry.locked_read_modify_write(
                pane_registry.registry_path(session_name), _reset_all_user_modified)
            pane_layout.rebalance(session_name, window)
            if force:
                # Entering mobile: zoom active pane on every window
                for w in all_windows:
                    if not tmux_mod.is_zoomed(session_name, w["index"]):
                        tmux_mod.zoom_pane(f"{session_name}:{w['index']}")
    else:
        # Show status
        force_flag = pane_layout.mobile_flag_path(session_name).exists()
        if tmux_mod.session_exists(session_name):
            window = tmux_mod.get_window_id(session_name)
            width, _ = tmux_mod.get_window_size(session_name, window)
            mobile = pane_layout.is_mobile(session_name, window)
            click.echo(f"Session: {session_name}")
            click.echo(f"Mobile active: {mobile}")
            click.echo(f"Force flag: {force_flag}")
            click.echo(f"Window width: {width} (threshold: {pane_layout._get_mobile_width_threshold()})")
        else:
            click.echo(f"Session: {session_name} (not running)")
            click.echo(f"Force flag: {force_flag}")
            click.echo(f"Threshold: {pane_layout._get_mobile_width_threshold()}")


# --- Internal pane/window commands ---

@cli.command("_pane-exited", hidden=True)
@click.argument("session")
@click.argument("window")
@click.argument("generation")
@click.argument("pane_id", default="")
def pane_exited_cmd(session: str, window: str, generation: str, pane_id: str):
    """Internal: handle pane exit — unregister and rebalance."""
    pane_layout.handle_pane_exited(session, window, generation, pane_id)


@cli.command("_pane-closed", hidden=True)
def pane_closed_cmd():
    """Internal: handle pane close from global tmux hook."""
    pane_layout.handle_any_pane_closed()


@cli.command("_pane-opened", hidden=True)
@click.argument("session")
@click.argument("window")
@click.argument("pane_id")
def pane_opened_cmd(session: str, window: str, pane_id: str):
    """Internal: handle tmux after-split-window hook."""
    pane_layout.handle_pane_opened(session, window, pane_id)


@cli.command("_popup-show", hidden=True)
@click.argument("kind")
def popup_show_cmd(kind: str):
    """Internal: launch a popup picking width by smallest attached client.

    Resolves popup width dynamically based on the smallest attached
    client in the current tmux session's group: 95% (always fits)
    when below the mobile-width threshold, fixed 80 cols otherwise.
    Then invokes ``tmux display-popup -E -w <width> -h <height> <body>``
    via subprocess, where each arg is passed as one argv element so we
    sidestep tmux's parser-quoting issues that the previous
    if-shell-with-nested-display-popup approach hit.
    """
    if kind not in _POPUP_KINDS:
        _log.warning("_popup-show: unknown kind %r", kind)
        return
    height, body = _POPUP_KINDS[kind]

    # Width is the *calling client's* current window width.  run-shell
    # from a bind-key inherits the calling client's $TMUX context, so
    # ``tmux display-message -p "#{window_width}"`` reports what we
    # need — the actual size of the window we are about to overlay,
    # not some min/max across the group.
    result = subprocess.run(
        tmux_mod._tmux_cmd("display-message", "-p", "#{window_width}"),
        capture_output=True, text=True, check=False,
    )
    win_width: int | None = None
    if result.returncode == 0 and result.stdout.strip().isdigit():
        win_width = int(result.stdout.strip())
    threshold = pane_layout._get_mobile_width_threshold()
    if win_width is not None and win_width < threshold:
        width = "95%"
    else:
        width = "80"

    # Resolve the launching pane's cwd so the popup's shell starts where
    # the user is, not in tmux's server-side default. Without -d the
    # popup's cwd can land outside any git repo, which makes
    # find_project_root() fail with a misleading 'No project.yaml found'.
    cwd_result = subprocess.run(
        tmux_mod._tmux_cmd("display-message", "-p", "#{pane_current_path}"),
        capture_output=True, text=True, check=False,
    )
    pane_cwd = cwd_result.stdout.strip() if cwd_result.returncode == 0 else ""

    _log.info("_popup-show: kind=%s window_width=%s threshold=%d -> width=%s cwd=%r",
              kind, win_width, threshold, width, pane_cwd)
    popup_cmd = ["display-popup", "-E", "-w", width, "-h", height]
    if pane_cwd:
        popup_cmd[2:2] = ["-d", pane_cwd]
    popup_cmd.append(body)
    subprocess.run(
        tmux_mod._tmux_cmd(*popup_cmd),
        check=False,
    )


@cli.command("_window-resized", hidden=True)
@click.argument("session")
@click.argument("window")
def window_resized_cmd(session: str, window: str):
    """Internal: handle tmux window resize — debounce and rebalance."""
    import time

    _log.info("_window-resized: ENTERED session=%s window=%s pid=%d", session, window, os.getpid())

    base = pane_registry.base_session_name(session)
    data = pane_registry.load_registry(base)
    wdata = pane_registry.get_window_data(data, window)
    if not wdata["panes"]:
        _log.info("_window-resized: no panes in registry for %s window %s, exiting", base, window)
        return

    _log.info("_window-resized: %d panes in window %s, debouncing...", len(wdata["panes"]), window)

    # Debounce: write our PID, sleep, then only proceed if we're still
    # the latest resize event.  This avoids N rebalances during a drag.
    debounce_file = pane_registry.registry_dir() / f"{base}.resize"
    my_id = str(os.getpid())
    debounce_file.write_text(my_id)
    time.sleep(0.15)
    try:
        current_id = debounce_file.read_text()
        if current_id != my_id:
            _log.info("_window-resized: debounce lost (pid %s != %s), exiting", my_id, current_id)
            return  # A newer resize event superseded us
    except FileNotFoundError:
        _log.info("_window-resized: debounce file gone, exiting")
        return

    _log.info("_window-resized: debounce won, rebalancing %s:%s", session, window)
    tmux_mod.unzoom_pane(session, window)
    result = pane_layout.rebalance(session, window)
    _log.info("_window-resized: rebalance returned %s", result)


@cli.command("_pane-switch", hidden=True,
             context_settings={"ignore_unknown_options": True})
@click.argument("session")
@click.argument("direction")
def pane_switch_cmd(session: str, direction: str):
    """Internal: switch pane with mobile-aware zoom.

    direction is 'next' or a tmux flag like '-U', '-D', '-L', '-R'.
    """
    window = tmux_mod.get_window_id(session)

    # Unzoom first so select-pane can reach other panes
    tmux_mod.unzoom_pane(session, window)

    if direction == "next":
        subprocess.run(
            tmux_mod._tmux_cmd("select-pane", "-t", f"{session}:{window}.+"),
            check=False,
        )
    else:
        subprocess.run(
            tmux_mod._tmux_cmd("select-pane", "-t", f"{session}:{window}", direction),
            check=False,
        )

    # If mobile, zoom the newly focused pane
    if pane_layout.is_mobile(session, window):
        result = subprocess.run(
            tmux_mod._tmux_cmd("display", "-t", f"{session}:{window}", "-p", "#{pane_id}"),
            capture_output=True, text=True,
        )
        active = result.stdout.strip()
        if active:
            tmux_mod.zoom_pane(active)


@cli.command("rebalance")
def rebalance_cmd():
    """Re-enable auto-balanced layout and rebalance panes.

    Use this after manually resizing panes to switch back to
    automatic layout management.
    """
    if not tmux_mod.in_tmux():
        click.echo("Must be run from within a tmux session.", err=True)
        raise SystemExit(1)

    session = tmux_mod.get_session_name()
    window = tmux_mod.get_window_id(session)

    # Check for panes (read-only) then reset user_modified under lock
    data = pane_registry.load_registry(session)
    wdata = pane_registry.get_window_data(data, window)
    if not wdata["panes"]:
        click.echo("No panes registered for this session.", err=True)
        raise SystemExit(1)

    def _reset_user_modified(raw):
        d = pane_registry._prepare_registry_data(raw, session)
        wd = pane_registry.get_window_data(d, window)
        wd["user_modified"] = False
        return d

    pane_registry.locked_read_modify_write(
        pane_registry.registry_path(session), _reset_user_modified)

    # Unzoom before rebalance so layout applies to all panes
    tmux_mod.unzoom_pane(session, window)
    pane_layout.rebalance(session, window)
    click.echo("Layout rebalanced.")


# --- Popup commands ---

# All available actions.  Each entry is (action_label, pm_command_template).
# Templates use {pr_id} for the internal PR ID.
# Commands prefixed with "tui:" are routed through the TUI command bar.
_ALL_ACTIONS: list[tuple[str, str]] = [
    ("start", "pr start {pr_id}"),
    ("edit", "tui:edit {pr_id}"),
    ("review", "pr review {pr_id}"),
    ("qa", "tui:pr qa {pr_id}"),
    ("merge", "pr merge --resolve-window {pr_id}"),
]

# Modifier-key (z / zz) variants for actions that support fresh / loop.
# Mirrors the TUI's z/zz chord behavior: ``z s`` = fresh start,
# ``z d`` = fresh review, ``zz d`` = review loop,
# ``z t`` = fresh qa, ``zz t`` = qa loop.
_MODIFIED_ACTION_CMDS: dict[tuple[str, str], str] = {
    ("z",  "start"):  "pr start --fresh {pr_id}",
    ("z",  "review"): "pr review --fresh {pr_id}",
    ("zz", "review"): "tui:review-loop start {pr_id}",
    ("z",  "qa"):     "tui:pr qa fresh {pr_id}",
    ("zz", "qa"):     "tui:pr qa loop {pr_id}",
}

# Map action labels to tmux window name patterns.
# ``None`` means the action doesn't open its own tmux window — it's a
# *shortcut-only* action.  Such actions don't appear as rows in the
# picker; their status (when meaningful) is folded into a list row's
# annotation via ``_SHORTCUT_FOLD_INTO``.
_ACTION_WINDOW_PATTERNS: dict[str, str | None] = {
    "start": "{display_id}",
    "edit": None,
    "review": "review-{display_id}",
    "review-loop": "review-{display_id}",  # used only via z d/zz d chord
    "qa": "qa-{display_id}",
    "merge": "merge-{display_id}",
}

# Actions that get their own row in the picker.  Shortcut-only actions
# (edit, review-loop) are reachable via their `--expect` keys but don't
# clutter the list with an extra row.
_LIST_ACTIONS: set[str] = {"start", "review", "qa", "merge"}

# Shortcut-only actions whose runtime status should be displayed on a
# list row alongside another action.  ``review-loop`` shares the
# ``review-{display_id}`` window, so its `[loop iN]` badge lives on the
# review row.  Edit isn't here because the edit pane opens in the
# current window and there's nothing meaningful to display.
_SHORTCUT_FOLD_INTO: dict[str, str] = {
    "review-loop": "review",
}

# Terminal statuses — PRs in these states have no actions.
_TERMINAL_STATUSES = {"merged", "closed"}

# Map status to the action label representing the current phase.
_STATUS_PHASE: dict[str, str] = {
    "in_progress": "start",
    "in_review": "review",
    "qa": "qa",
}


def _actions_for_status(status: str) -> list[tuple[str, str]]:
    """Return (action_label, command_template) pairs for a PR status.

    All actions are returned for non-terminal statuses.
    """
    if status in _TERMINAL_STATUSES:
        return []
    return list(_ALL_ACTIONS)


def _status_phase(status: str) -> str | None:
    """Return the action label representing the current phase for a status."""
    return _STATUS_PHASE.get(status)


def _current_window_pr_id(window_name: str) -> str | None:
    """Extract PR display ID from a window name."""
    import re
    m = re.match(
        r'^(?:review-|merge-|qa-)?(#\d+|pr-[a-zA-Z0-9]+)(?:-s\d+)?$',
        window_name,
    )
    return m.group(1) if m else None


def _current_window_phase(window_name: str) -> str | None:
    """Map a window name's prefix to a picker action label.

    Drives the ●-marker in the picker so it reflects the user's current
    context rather than the PR's status.  Returns 'start' for an
    unprefixed PR window (the implementation pane), 'review' for
    ``review-…``, 'qa' for ``qa-…``, 'merge' for ``merge-…``, or None
    if the window isn't a PR window.
    """
    if _current_window_pr_id(window_name) is None:
        return None
    if window_name.startswith("review-"):
        return "review"
    if window_name.startswith("qa-"):
        return "qa"
    if window_name.startswith("merge-"):
        return "merge"
    return "start"


def _format_action_status(pr_id: str, action: str) -> str:
    """Return a short status badge for an action, or '' when nothing useful.

    Reads the persisted runtime state and cross-references the latest
    hook event for the action's pane (when applicable) so the badge
    reflects the same idle/waiting/working signals the TUI uses.
    """
    try:
        from pm_core import runtime_state as _rs
        entry = _rs.derive_action_status(pr_id, action)
    except Exception:
        return ""
    if not entry:
        return ""
    state = entry.get("state")
    if action == "review-loop":
        if state == "running":
            it = entry.get("iteration")
            return f" [loop i{it}]" if it else " [loop]"
        if state == "done":
            it = entry.get("iteration")
            v = entry.get("verdict")
            return (f" [done i{it} {v}]" if it and v
                    else f" [done {v}]" if v
                    else " [done]")
        if state == "failed":
            return " [failed]"
        return ""
    # start / qa / review / merge: hook-event-derived states from
    # derive_action_status (live), plus terminal verdict states written
    # by the qa / review completion paths.  Stale/dead entries are
    # cleared (not flagged) by the TUI-mount sweep and pane_idle's
    # pane-gone path, so we never need to render a "no longer alive"
    # badge — absence of an entry is the signal, and [open] from the
    # live tmux window list is authoritative.
    if state == "idle":
        return " [idle]"
    if state == "waiting":
        return " [wait]"
    if state == "running":
        return " [working]"
    if state == "done":
        v = entry.get("verdict")
        return f" [done {v}]" if v else " [done]"
    if state == "failed":
        return " [failed]"
    return ""


def _build_picker_lines(
    prs: list[dict],
    current_pr_display: str | None,
    open_windows: set[str] | None = None,
    current_phase: str | None = None,
) -> list[tuple[str, str, str]]:
    """Build display lines for the action-based PR picker.

    Only shows actions for the PR matching `current_pr_display`.
    Returns list of (display_line, pm_command, pr_display_id) tuples.
    pm_command is empty for non-selectable header lines.

    If `open_windows` is provided (set of tmux window names), actions
    whose windows are already open are annotated with ``[open]``.
    """
    from pm_core.cli.helpers import _pr_display_id

    if not current_pr_display:
        return []

    # Find the PR matching the current window
    pr = None
    display_id = None
    for p in prs:
        did = _pr_display_id(p)
        if did == current_pr_display:
            pr = p
            display_id = did
            break

    if not pr:
        return []

    status = pr.get("status", "")
    actions = _actions_for_status(status)
    if not actions:
        return []

    lines: list[tuple[str, str, str]] = []
    title = pr.get("title", "")
    max_title = 40
    short_title = (title[:max_title - 1] + "…") if len(title) > max_title else title

    lines.append((f"  {display_id}  ({status})  {short_title}", "", display_id))

    # Phase indicator reflects the *current window* (where the user is),
    # not the PR's status — e.g. sitting in the impl window of an
    # in_review PR should highlight 'start', not 'review'.
    phase = current_phase if current_phase is not None else _status_phase(status)
    # Actions without their own tmux window (edit, review-loop) are
    # shortcut-only — they don't get a row in the picker; their status
    # (where meaningful) is folded into a related list action's row.
    fold_status: dict[str, str] = {}
    for label, host in _SHORTCUT_FOLD_INTO.items():
        tag = _format_action_status(pr["id"], label)
        if tag:
            fold_status[host] = fold_status.get(host, "") + tag
    for label, cmd_template in actions:
        if label not in _LIST_ACTIONS:
            continue  # shortcut-only; status (if any) folded in above
        cmd = cmd_template.format(pr_id=pr["id"])
        indicator = "●" if label == phase else " "

        # Check if this action's window is open
        open_tag = ""
        if open_windows is not None:
            pattern = _ACTION_WINDOW_PATTERNS.get(label)
            if pattern:
                win_name = pattern.format(display_id=display_id)
                # qa windows can have scenario suffixes (qa-#158-s1)
                if label == "qa":
                    if any(w == win_name or w.startswith(win_name + "-")
                           for w in open_windows):
                        open_tag = " [open]"
                elif win_name in open_windows:
                    open_tag = " [open]"

        # Live status from the shared runtime-state file (loop iteration,
        # idle/waiting derived from the latest hook event, etc.).
        status_tag = _format_action_status(pr["id"], label)
        # Fold in any shortcut-only actions whose status belongs here
        # (e.g. review-loop's '[loop i3]' lives on the review row since
        # review-loop iterations run in the review window).
        status_tag += fold_status.get(label, "")

        lines.append((f"  {indicator} {label:<18s}"
                      f"{open_tag}{status_tag}", cmd, display_id))

    return lines


def _fzf_supports_no_input() -> bool:
    """Whether the installed fzf accepts ``--no-input`` (fzf 0.59+).

    Cached on the module so we don't fork a subprocess every time the
    picker re-launches fzf during chord-state transitions.
    """
    cached = getattr(_fzf_supports_no_input, "_cached", None)
    if cached is not None:
        return cached
    try:
        out = subprocess.run(
            ["fzf", "--version"], capture_output=True, text=True,
            timeout=2,
        ).stdout
        # fzf --version prints e.g. "0.59.0 (...)".  Compare numerically
        # against the (major, minor) tuple where --no-input landed.
        version = out.split()[0] if out.split() else ""
        parts = version.split(".")
        major = int(parts[0]) if parts and parts[0].isdigit() else 0
        minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        supported = (major, minor) >= (0, 59)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        supported = False
    _fzf_supports_no_input._cached = supported  # type: ignore[attr-defined]
    return supported


def _parse_tui_action(tui_cmd: str) -> tuple[str | None, str | None, bool]:
    """Best-effort: extract (pr_id, picker_action, fresh) from a tui: cmd.

    ``fresh`` indicates the action will kill+recreate its target window
    (review-loop iteration, ``pr qa fresh``, ``pr qa loop``).  The
    spinner uses this to wait for a window-id transition rather than
    just window appearance, so a stale-window snapshot doesn't trigger
    an immediate switch to the about-to-be-killed window.
    """
    parts = shlex.split(tui_cmd) if tui_cmd else []
    if not parts:
        return None, None, False
    if parts[0] == "review-loop":
        rest = [t for t in parts[1:] if t not in ("start", "stop")]
        # Every review-loop iteration recreates the review window.
        return (rest[0] if rest else None), "review-loop", True
    if len(parts) >= 2 and parts[0] == "pr" and parts[1] == "qa":
        rest = parts[2:]
        mode = None
        if rest and rest[0] in ("fresh", "loop"):
            mode = rest[0]
            rest = rest[1:]
        return (rest[0] if rest else None), "qa", mode in ("fresh", "loop")
    if parts[0] == "edit":
        return (parts[1] if len(parts) >= 2 else None), "edit", False
    return None, None, False


def _wait_for_tui_command(session: str, tui_cmd: str,
                          tick_s: float = 0.15) -> None:
    """Show a spinner while a queued TUI command transitions states.

    Polls the shared runtime-state file and the tmux window list and
    exits when the target window appears.  No timeout — long-running
    launches stay visible until they complete.  The user can press
    ``q`` or ``Esc`` at any time to dismiss the spinner *without*
    cancelling the queued command (the TUI continues to handle it
    once it picks the entry up off the queue).
    """
    import select
    import sys
    import termios
    import tty

    from pm_core import runtime_state as _rs

    pr_id, action, fresh = _parse_tui_action(tui_cmd)
    if not pr_id or not action:
        return
    # 'edit' opens in the current window — there's no window-appearance
    # signal to wait for and the launch is effectively instant.  Skip
    # the spinner entirely so the popup closes without a visible flash.
    if action == "edit":
        return
    try:
        root = state_root()
        data = store.load(root)
        from pm_core.cli.helpers import _pr_display_id
        display_id = None
        for p in data.get("prs") or []:
            if p.get("id") == pr_id:
                display_id = _pr_display_id(p)
                break
    except Exception:
        display_id = None
    pattern = _ACTION_WINDOW_PATTERNS.get(action)
    target_window = pattern.format(display_id=display_id) if (
        pattern and display_id) else None

    def _find_target_window_ids() -> list[str]:
        """Return all tmux window ids whose name matches the target.

        For most actions this is at most one window; for ``qa`` the
        target name is a prefix (e.g. ``qa-#158`` matches ``qa-#158-s1``,
        ``qa-#158-s2``), so multiple ids can be live simultaneously.
        """
        if not target_window:
            return []
        try:
            wins = tmux_mod.list_windows(session)
        except Exception:
            return []
        ids: list[str] = []
        for w in wins:
            name = w.get("name", "")
            wid = w.get("id")
            if not wid:
                continue
            if action == "qa":
                if name == target_window or name.startswith(target_window + "-"):
                    ids.append(wid)
            elif name == target_window:
                ids.append(wid)
        return ids

    def _first_target_window_id() -> str | None:
        ids = _find_target_window_ids()
        return ids[0] if ids else None

    # For fresh-mode actions (review-loop, qa fresh/loop) the target
    # window(s) may currently exist but are about to be killed and
    # recreated.  Snapshot the *set* of initial window-ids so we can
    # distinguish a freshly created window (id not in the snapshot)
    # from a doomed sibling that simply hasn't been killed yet.  For
    # QA in particular, multiple scenario windows match the prefix and
    # they get killed one at a time — without the set we'd switch to
    # the next-still-alive sibling instead of waiting for the rebuild.
    initial_window_ids: set[str] = (
        set(_find_target_window_ids()) if fresh else set()
    )
    saw_disappear = False

    # Print a header line so the popup clearly shows what's happening
    # underneath the picker.  The spinner below uses \r to overwrite a
    # single line; this header stays put.
    if fresh:
        click.echo(f"\n── starting fresh: {action} for {pr_id} ──")
    else:
        click.echo(f"\n── starting: {action} for {pr_id} ──")

    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    i = 0

    # ANSI escapes used to keep the spinner line clean:
    #   \x1b[K  — erase from cursor to end of line (avoids leftover
    #             characters when a shorter label replaces a longer
    #             one, e.g. 'running…' over 'rebuilding window…')
    #   \x1b[?25l / \x1b[?25h — hide / show the terminal cursor so it
    #             doesn't sit on top of the last character of the line
    CLR_EOL = "\x1b[K"
    HIDE_CURSOR = "\x1b[?25l"
    SHOW_CURSOR = "\x1b[?25h"
    click.echo(HIDE_CURSOR, nl=False)

    # Put stdin in cbreak mode so we can poll for q/Esc keypresses
    # without waiting for Enter.  Restore in finally so the popup shell
    # isn't left in a broken state if anything raises.
    fd = sys.stdin.fileno()
    try:
        old_attrs = termios.tcgetattr(fd)
    except termios.error:
        old_attrs = None
    if old_attrs is not None:
        try:
            tty.setcbreak(fd)
        except termios.error:
            old_attrs = None
    try:
        while True:
            entry = _rs.get_action_state(pr_id, action)
            cur_state = entry.get("state") if entry else None
            cur_window_ids = _find_target_window_ids()
            if fresh and initial_window_ids:
                # Wait for *all* original windows to be killed and a new
                # one with the same name to appear.  A "new" window is
                # one whose id is not in the initial set; for QA this
                # avoids switching to a still-alive sibling scenario
                # (e.g. qa-#158-s2) when only s1 has been killed.
                new_ids = [i for i in cur_window_ids
                           if i not in initial_window_ids]
                if not cur_window_ids:
                    saw_disappear = True
                    window_open = False
                elif new_ids:
                    window_open = True
                    # Prefer switching to a freshly created window so we
                    # never land on a doomed sibling.
                    cur_window_id = new_ids[0]
                else:
                    window_open = False
            else:
                window_open = bool(cur_window_ids)
                cur_window_id = cur_window_ids[0] if cur_window_ids else None
            # Terminal-state short-circuit: if the action has reached a
            # terminal state (done/failed) without producing the expected
            # tmux window — review-loop in particular has no persistent
            # window between iterations — exit the spinner instead of
            # spinning forever.  Failures get surfaced via _wait_dismiss
            # so the user sees the verdict before the popup closes;
            # successes dismiss as today.
            if cur_state in ("done", "failed") and not window_open:
                verdict = (entry.get("verdict") if entry else "") or ""
                failed = cur_state == "failed" or verdict in ("ERROR", "KILLED")
                # Restore terminal *before* writing final lines / waiting
                # for keypress so cbreak/cursor state doesn't leak.
                if old_attrs is not None:
                    try:
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
                    except termios.error:
                        pass
                    old_attrs = None
                click.echo(SHOW_CURSOR, nl=False)
                if failed:
                    suffix = f" ({verdict})" if verdict else ""
                    click.echo(f"\r✗ {action}: failed{suffix}{CLR_EOL}")
                    _wait_dismiss()
                else:
                    suffix = f" ({verdict})" if verdict else ""
                    click.echo(f"\r✓ {action}: done{suffix}{CLR_EOL}")
                return
            if window_open:
                # Switch the invoking session to the target window
                # unless the user pre-emptively suppressed it.  Doing
                # the switch here keeps review and review-loop
                # consistent: review's switch is performed by the
                # 'pm pr review' subprocess, but review-loop iterations
                # don't switch on first start, so we drive it from the
                # popup.  qa keeps its own focus_or_start_qa switch
                # path — and owns its own suppress_switch consume —
                # so we leave the flag in place for action == "qa".
                if action != "qa":
                    try:
                        suppressed = _rs.consume_suppress_switch(pr_id, action)
                    except Exception:
                        suppressed = False
                    if not suppressed:
                        try:
                            tmux_mod.select_window(session, target_window)
                        except Exception:
                            pass
                click.echo(
                    f"\r✓ {action}: window {target_window} is open"
                    f"{CLR_EOL}")
                return
            spin = frames[i % len(frames)]
            if fresh and initial_window_ids and not saw_disappear:
                label = "rebuilding window"
            elif cur_state == "failed":
                v = (entry.get("verdict") if entry else "") or ""
                label = f"failed ({v})" if v else "failed"
            else:
                label = cur_state or "queued"
            click.echo(f"\r{spin} {action}: {label}…{CLR_EOL}", nl=False)

            # Wait up to tick_s for a keypress.  q/Esc → close the
            # popup immediately *without* cancelling the queued command
            # (the TUI continues processing it).  Other keys are
            # ignored.  We exit the whole popup process here so tmux's
            # ``display-popup -E`` tears the overlay down right away.
            r, _, _ = select.select([sys.stdin], [], [], tick_s)
            if r:
                try:
                    ch = sys.stdin.read(1)
                except OSError:
                    ch = ""
                if ch in ("q", "Q", "\x1b"):  # Esc
                    # Tell the TUI to skip its window-switch for this
                    # action — the user explicitly dismissed; don't
                    # steal focus when the launch eventually completes.
                    try:
                        _rs.request_suppress_switch(pr_id, action)
                    except Exception:
                        pass
                    if old_attrs is not None:
                        try:
                            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
                        except termios.error:
                            pass
                    raise SystemExit(0)
            i += 1
    except KeyboardInterrupt:
        return
    finally:
        if old_attrs is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
            except termios.error:
                pass
        click.echo(SHOW_CURSOR)


def _wait_dismiss(prompt: str = "\nPress q/Esc/Enter to close...") -> None:
    """Block until the user presses q, Q, Esc, Enter, or sends EOF/Ctrl+C.

    Replaces ``input()`` for popup error/info screens — ``input()`` only
    accepts Enter, so users pressing q or Esc to dismiss the popup felt
    stuck.  Falls back to ``input()`` if stdin isn't a tty (e.g. tests).
    """
    import sys
    try:
        if not sys.stdin.isatty():
            try:
                input(prompt)
            except (EOFError, KeyboardInterrupt):
                pass
            return
        click.echo(prompt, nl=False)
        sys.stdout.flush()
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while True:
                ch = sys.stdin.read(1)
                if not ch:
                    break  # EOF
                if ch in ("q", "Q", "\r", "\n", "\x1b", "\x03", "\x04"):
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        click.echo("")
    except (KeyboardInterrupt, Exception):
        pass


def _run_picker_command(cmd: str, session: str) -> None:
    """Execute a picker command — either direct CLI or routed through TUI."""
    import sys

    if cmd.startswith("tui:"):
        # Route through the TUI's SIGUSR2 + queue-file IPC.  Focus-
        # independent: doesn't depend on tmux send-keys timing, can't
        # be eaten by whichever widget has focus, and supports queuing
        # multiple commands across concurrent picker invocations.
        from pm_core.cli.helpers import trigger_tui_command
        tui_cmd = cmd[4:]
        base = pane_registry.base_session_name(session)
        if not trigger_tui_command(base, tui_cmd):
            click.echo("Could not reach the TUI (no pidfile or signal failed).")
            _wait_dismiss()
            return
        # Brief progress display: poll runtime_state for the action to
        # transition out of 'queued' / into 'running'.  Exits early on
        # state transition or when the target window appears.
        _wait_for_tui_command(base, tui_cmd)
    else:
        # Run pm command directly. Capture stdout/stderr so we can re-emit
        # them ourselves — display-popup -E's raw-mode TTY mangles bytes
        # streamed by the child, leaving the user staring at an empty
        # popup when something fails.
        full_cmd = [sys.executable, "-m", "pm_core.wrapper"] + shlex.split(cmd)
        result = subprocess.run(full_cmd, text=True, capture_output=True)
        if result.stdout:
            click.echo(result.stdout, nl=False)
        if result.returncode != 0:
            err = (result.stderr or "").strip()
            if err:
                click.echo(f"pm error: {err}", err=True)
            _wait_dismiss()
        elif result.stderr:
            # Even on success some commands print informational lines to
            # stderr; surface them so they don't vanish.
            click.echo(result.stderr, nl=False, err=True)


@cli.command("_popup-picker", hidden=True)
@click.argument("session")
@click.argument("window_name", default="")
def popup_picker_cmd(session: str, window_name: str):
    """Internal: action-based PR picker for tmux popup.

    Lists all active PRs with available actions (start, review, qa, merge,
    review-loop) based on PR status.  Selecting an action runs the
    corresponding pm command.
    """
    import shutil
    import sys

    def _pause_and_exit(code: int = 0):
        # display-popup -E closes when the command exits, so wait for Enter
        # whenever we have a message the user needs to read.
        _wait_dismiss()
        raise SystemExit(code)

    base = pane_registry.base_session_name(session)
    rp = pane_registry.registry_path(base)
    _log.info("popup-picker invoked: session=%r window=%r base=%r registry_path=%s exists=%s HOME=%r module=%s",
              session, window_name, base, rp, rp.exists(),
              os.environ.get("HOME"), __file__)
    if not rp.exists():
        click.echo("Not a pm session.")
        _pause_and_exit(1)

    try:
        root = state_root()
        data = store.load(root)
    except FileNotFoundError:
        click.echo("No project.yaml found.")
        _pause_and_exit(1)

    prs = data.get("prs") or []
    current_pr = _current_window_pr_id(window_name)

    # Gather open windows to annotate the picker
    open_windows = {w["name"] for w in tmux_mod.list_windows(base)}

    from pm_core.cli.helpers import _pr_display_id

    # Build the navigation list: PRs that the user has at least one
    # open window for.  The invoking window's PR (if any) is included
    # as the "home" position for the 0 key.  When the picker is opened
    # from a non-PR window (current_pr is None), home_pr is None and
    # navigation cycles through whichever PRs have live windows.
    def _pr_has_open_window(pr: dict) -> bool:
        did = _pr_display_id(pr)
        for pat in _ACTION_WINDOW_PATTERNS.values():
            if pat and pat.format(display_id=did) in open_windows:
                return True
        return False

    home_pr = current_pr  # may be None when invoked from a non-PR window
    nav_pr_ids: list[str] = []
    seen: set[str] = set()
    for p in prs:
        did = _pr_display_id(p)
        if did and (_pr_has_open_window(p) or did == home_pr):
            if did not in seen:
                nav_pr_ids.append(did)
                seen.add(did)
    if home_pr and home_pr not in seen:
        nav_pr_ids.insert(0, home_pr)

    if not nav_pr_ids:
        click.echo("PR Actions (prefix+P)")
        click.echo("No PR windows open." if not home_pr
                   else "Switch to a PR window to use this picker.")
        _pause_and_exit(0)

    try:
        nav_index = nav_pr_ids.index(home_pr) if home_pr else 0
    except ValueError:
        nav_index = 0

    invoking_phase = _current_window_phase(window_name)

    def _resolve_for(pr_disp: str):
        """Return (lines, picked_pr, label_to_cmd) for the given PR."""
        picked = next(
            (p for p in prs if _pr_display_id(p) == pr_disp), None)
        label_to_cmd: dict[str, str] = {}
        if picked is not None:
            for lbl, tpl in _actions_for_status(picked.get("status", "")):
                label_to_cmd[lbl] = tpl.format(pr_id=picked["id"])
        # Phase indicator only meaningful for the invoking PR — when
        # navigating to a different PR the user isn't "in" any of its
        # phases.  Pass "" (not None) so _build_picker_lines treats it
        # as "no phase" rather than falling back to status-derived.
        phase = invoking_phase if pr_disp == home_pr else ""
        pr_lines = _build_picker_lines(
            prs, pr_disp, open_windows, current_phase=phase)
        return pr_lines, picked, label_to_cmd

    current_pr = nav_pr_ids[nav_index]
    lines, _picked_pr, _label_to_cmd = _resolve_for(current_pr)

    if not lines:
        click.echo(f"PR Actions — {current_pr}")
        click.echo("No actions available (PR is merged or closed).")
        _pause_and_exit(0)

    has_fzf = shutil.which("fzf") is not None

    # Shortcut keys: press a key to immediately run an action.
    # Ordered to match _ALL_ACTIONS display order.
    # Note: q is reserved for quitting the picker (mapped to fzf abort
    # below), so qa uses 'a'.
    _SHORTCUT_KEYS = {
        "s": "start",
        "e": "edit",
        "d": "review",
        "t": "qa",
        "g": "merge",
    }
    if has_fzf:
        fzf_input_lines = [display for display, _, _ in lines]

        shortcut_hint = "  ".join(
            f"{key}={label}" for key, label in _SHORTCUT_KEYS.items()
        )
        chord_hint = "z s/d/t: fresh   zz d/t: loop"
        multi_pr = len(nav_pr_ids) > 1
        if multi_pr:
            nav_hint = ("h/l: prev/next PR   0: home" if home_pr
                        else "h/l: prev/next PR")
        else:
            nav_hint = ""

        # fzf 0.59+ supports --no-input which hides the entire input
        # box, so unrecognized keystrokes don't echo anywhere in the
        # popup.  Detect support up-front so we can fall back to the
        # older --disabled + --prompt= combo on older versions (which
        # still echoes typed characters into the prompt area).
        no_input_supported = _fzf_supports_no_input()

        # Chord state-machine: each iteration re-launches fzf with a
        # header reflecting the current chord state (none / 'z' / 'zz')
        # so the chord UI lives in the same picker pane.  q/Esc inside
        # a chord state aborts that fzf invocation, and we go back to
        # the main state on the next loop iteration; q/Esc in the main
        # state exits the popup.
        # Belt-and-suspenders: bind every alphanumeric key not in the
        # current --expect set to fzf's ``ignore`` action so unsupported
        # letters (e.g. j/k/h/l/i…) never echo anywhere — even on fzf
        # versions that don't honor --no-input or where --disabled
        # leaves the input box's character echo enabled.  q is bound
        # to abort separately so it always quits the (sub-)picker.
        import string
        def _make_fzf_cmd(header: str, expect: list[str]) -> list[str]:
            expect_set = set(expect)
            binds = ["q:abort"]
            for ch in string.ascii_lowercase + string.ascii_uppercase + string.digits:
                if ch != "q" and ch not in expect_set:
                    binds.append(f"{ch}:ignore")
            cmd = ["fzf", "--ansi", "--no-sort", "--reverse",
                   f"--header={header}",
                   "--header-first",
                   "--pointer=>",
                   "--no-info",
                   f"--bind={','.join(binds)}",
                   # --height inhibits fzf's alt-screen mode so the
                   # picker contents stay visible after fzf exits and
                   # the spinner renders below them in the same pane.
                   "--height=100%",
                   f"--expect={','.join(expect)}"]
            if no_input_supported:
                cmd.append("--no-input")
            else:
                cmd.extend(["--disabled", "--prompt="])
            return cmd

        cmd_to_run: str | None = None
        chord_state = "main"  # 'main' | 'z' | 'zz'
        while True:
            if chord_state == "main":
                pr_pos = (f"  ({nav_index + 1}/{len(nav_pr_ids)})"
                          if multi_pr else "")
                header_lines = [f"PR Actions — {current_pr}{pr_pos}",
                                f"q/Esc: quit  {shortcut_hint}",
                                chord_hint]
                if nav_hint:
                    header_lines.append(nav_hint)
                header = "\n".join(header_lines)
                expect = list(_SHORTCUT_KEYS.keys()) + ["z"]
                if multi_pr:
                    expect += ["h", "l", "left", "right"]
                    if home_pr:
                        expect.append("0")
            elif chord_state == "z":
                header = (f"z — fresh start for {current_pr}\n"
                          f"s=fresh impl   d=fresh review   t=fresh qa   "
                          f"z again for loop   q/Esc cancels")
                expect = ["z", "s", "d", "t"]
            else:  # 'zz'
                header = (f"zz — loop for {current_pr}\n"
                          f"d=review-loop   t=qa-loop   "
                          f"q/Esc cancels")
                expect = ["d", "t"]

            fzf_cmd = _make_fzf_cmd(header, expect)
            proc = subprocess.Popen(
                fzf_cmd,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True,
            )
            stdout, _ = proc.communicate(input="\n".join(fzf_input_lines))

            if proc.returncode != 0:
                # fzf aborted (q/Esc).  In a chord state, that means
                # "cancel chord, go back to main".  In main, it
                # dismisses the popup.
                if chord_state == "main":
                    raise SystemExit(0)
                chord_state = "main"
                continue

            out_lines = stdout.strip().split("\n")
            pressed_key = out_lines[0] if out_lines else ""
            selected = out_lines[1] if len(out_lines) > 1 else ""

            if chord_state == "main":
                if multi_pr and pressed_key in ("h", "left"):
                    nav_index = (nav_index - 1) % len(nav_pr_ids)
                    current_pr = nav_pr_ids[nav_index]
                    lines, _picked_pr, _label_to_cmd = _resolve_for(current_pr)
                    fzf_input_lines = [d for d, _, _ in lines]
                    continue
                if multi_pr and pressed_key in ("l", "right"):
                    nav_index = (nav_index + 1) % len(nav_pr_ids)
                    current_pr = nav_pr_ids[nav_index]
                    lines, _picked_pr, _label_to_cmd = _resolve_for(current_pr)
                    fzf_input_lines = [d for d, _, _ in lines]
                    continue
                if multi_pr and home_pr and pressed_key == "0":
                    nav_index = nav_pr_ids.index(home_pr)
                    current_pr = nav_pr_ids[nav_index]
                    lines, _picked_pr, _label_to_cmd = _resolve_for(current_pr)
                    fzf_input_lines = [d for d, _, _ in lines]
                    continue
                if pressed_key == "z":
                    chord_state = "z"
                    continue
                if pressed_key in _SHORTCUT_KEYS:
                    cmd_to_run = _label_to_cmd.get(
                        _SHORTCUT_KEYS[pressed_key])
                    break
                if selected:
                    for display, cmd, _ in lines:
                        if display == selected:
                            cmd_to_run = cmd or None
                            break
                    break
                # No actionable input — bail.
                break

            # In a chord state — resolve to a modified command.
            if chord_state == "z" and pressed_key == "z":
                chord_state = "zz"
                continue
            if pressed_key in ("s", "d", "t"):
                action_label = _SHORTCUT_KEYS.get(pressed_key)
                if action_label and _picked_pr is not None:
                    template = _MODIFIED_ACTION_CMDS.get(
                        (chord_state, action_label))
                    if template:
                        cmd_to_run = template.format(
                            pr_id=_picked_pr["id"])
                    else:
                        cmd_to_run = _label_to_cmd.get(action_label)
                break
            # Unrecognized key in chord — return to main.
            chord_state = "main"
            continue

        if cmd_to_run:
            _run_picker_command(cmd_to_run, session)
        # Always exit the popup process explicitly after dispatching —
        # display-popup -E ties the overlay to this process's lifetime,
        # so an explicit exit (with stdout flush) ensures the overlay
        # closes promptly after the spinner switches windows.
        try:
            sys.stdout.flush()
        except Exception:
            pass
        raise SystemExit(0)
    else:
        # Fallback: numbered list with shortcut keys
        click.echo("Tip: install fzf for a better experience"
                    " (brew install fzf / apt install fzf)\n")
        click.echo(f"PR Actions — {current_pr}\n")

        numbered: list[tuple[int, str]] = []  # (num, command)
        num = 0
        for display, cmd, _ in lines:
            if not cmd:
                click.echo(display)
            else:
                num += 1
                numbered.append((num, cmd))
                click.echo(f"  {num}) {display.strip()}")

        if not numbered:
            raise SystemExit(0)

        shortcut_hint = "  ".join(
            f"{key}={label}" for key, label in _SHORTCUT_KEYS.items()
        )
        click.echo(f"\nShortcuts: {shortcut_hint}")
        try:
            choice = input(f"Select [1-{num}] or shortcut key: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit(0)

        # Check if it's a shortcut key
        if choice in _SHORTCUT_KEYS:
            target_label = _SHORTCUT_KEYS[choice]
            cmd = _label_to_cmd.get(target_label)
            if cmd:
                _run_picker_command(cmd, session)
        else:
            try:
                choice_num = int(choice)
            except ValueError:
                raise SystemExit(0)

            for n, cmd in numbered:
                if n == choice_num:
                    _run_picker_command(cmd, session)
                    break


@cli.command("_popup-cmd", hidden=True)
@click.argument("session")
def popup_cmd_cmd(session: str):
    """Internal: pm command prompt for tmux popup."""
    import sys

    base = pane_registry.base_session_name(session)
    rp = pane_registry.registry_path(base)
    _log.info("popup-cmd invoked: session=%r base=%r registry_path=%s exists=%s HOME=%r module=%s",
              session, base, rp, rp.exists(),
              os.environ.get("HOME"), __file__)
    if not rp.exists():
        click.echo("Not a pm session.")
        _wait_dismiss()
        raise SystemExit(1)

    try:
        cmd = input("pm> ").strip()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(0)

    if not cmd:
        raise SystemExit(0)

    # Route TUI-dependent commands through the TUI command bar
    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        click.echo(f"Invalid command syntax: {e}")
        _wait_dismiss()
        raise SystemExit(1)
    _cmd_norm = cmd.replace("review loop", "review-loop")
    if (_cmd_norm.startswith("pr qa")
            or _cmd_norm.startswith("review-loop")):
        _run_picker_command(f"tui:{_cmd_norm}", session)
        return

    full_cmd = [sys.executable, "-m", "pm_core.wrapper"] + parts

    rc = _run_with_abort_keys(full_cmd)

    if rc == _ABORTED_BY_USER:
        # User pressed Esc/Ctrl+C — close popup immediately, no error wait.
        return
    if rc != 0:
        # Keep popup open so user can see error
        _wait_dismiss()


_ABORTED_BY_USER = -999


def _run_with_abort_keys(cmd: list[str]) -> int:
    """Run *cmd* inheriting stdout/stderr, but watch the popup pty for
    Esc / Ctrl+C and terminate the child when either is pressed.

    The child is spawned in its own session with ``stdin=DEVNULL`` so the
    parent owns the pty input.  Returns the child's exit code, or
    ``_ABORTED_BY_USER`` if the user dismissed the popup mid-run.
    """
    import signal
    import sys

    if not sys.stdin.isatty():
        # Tests / non-interactive: just run it.
        return subprocess.run(cmd, text=True).returncode

    import select
    import termios
    import tty

    proc = subprocess.Popen(
        cmd, text=True,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    aborted = False
    try:
        tty.setcbreak(fd)
        # Disable ISIG so Ctrl+C arrives as the byte 0x03 we can intercept
        # and forward, instead of raising KeyboardInterrupt in this process.
        new_attrs = termios.tcgetattr(fd)
        new_attrs[3] &= ~termios.ISIG  # lflags
        termios.tcsetattr(fd, termios.TCSANOW, new_attrs)
        while True:
            if proc.poll() is not None:
                break
            try:
                r, _, _ = select.select([fd], [], [], 0.1)
            except (InterruptedError, OSError):
                continue
            if not r:
                continue
            try:
                ch = os.read(fd, 1)
            except OSError:
                continue
            if not ch:
                continue
            if ch in (b"\x1b", b"\x03"):  # Esc, Ctrl+C
                aborted = True
                try:
                    os.killpg(proc.pid, signal.SIGINT)
                except (ProcessLookupError, PermissionError):
                    pass
                # Give the child a moment to exit on SIGINT, then escalate.
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        pass
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            pass
                        proc.wait()
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)

    if aborted:
        return _ABORTED_BY_USER
    return proc.returncode if proc.returncode is not None else 0


# --- Session registry commands ---

@cli.command("_save-session", hidden=True)
@click.argument("session_key")
@click.argument("session_id")
@click.argument("pm_root")
def save_session_cmd(session_key: str, session_id: str, pm_root: str):
    """Internal: save a session ID to the registry."""
    from pm_core.claude_launcher import save_session
    try:
        save_session(Path(pm_root), session_key, session_id)
    except Exception:
        pass  # Best effort


@cli.command("_clear-session", hidden=True)
@click.argument("session_key")
@click.argument("pm_root")
def clear_session_cmd(session_key: str, pm_root: str):
    """Internal: clear a stale session from the registry.

    Called when claude --resume fails (e.g., session no longer exists).
    This prevents infinite loops trying to resume a non-existent session.
    """
    from pm_core.claude_launcher import clear_session
    try:
        clear_session(Path(pm_root), session_key)
        click.echo(f"Cleared stale session: {session_key}", err=True)
    except Exception:
        pass  # Best effort
