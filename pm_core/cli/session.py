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


def _register_tmux_bindings(session_name: str) -> None:
    """Register tmux keybindings and session options for pm.

    Called on both new session creation and reattach so bindings
    survive across sessions (tmux bindings are global).
    Also sets window-size=smallest on all sessions in the group so the
    window fits the smallest connected client (everyone sees the full layout).
    """
    # Window follows the smallest client so all connected users see the
    # full layout without scrolling or clipping.
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
    # Clean up stale hook from earlier versions that used the wrong name
    subprocess.run(tmux_mod._tmux_cmd("set-hook", "-gu", "after-resize-window"),
            check=False)


def _session_start(share_global: bool = False, share_group: str | None = None,
                   start_dir: str | None = None):
    """Start a tmux session with TUI + notes editor.

    If no project exists yet, starts pm guide instead of the TUI so
    the guided workflow can initialize the project inside tmux.

    Args:
        share_global: Make session accessible to all users on the system.
        share_group: Make session accessible to this Unix group.
        start_dir: Compute session tag from this directory instead of cwd.
                   Used when joining another user's shared session.
    """
    _log.info("session_cmd started")
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
                tui_window = tmux_mod.get_window_id(session_name)
            if tui_window:
                pane_registry._respawn_tui(session_name, tui_window)
                pane_registry.rebalance(session_name, tui_window)
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
                tmux_mod.set_session_option(grouped, "window-size", "smallest",
                                            socket_path=socket_path)
                click.echo(f"Attaching to session '{grouped}'...")
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
    pane_registry.save_registry(session_name, {
        "session": session_name, "windows": {},
        "generation": generation,
    })

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
@click.pass_context
def session(ctx, share_global, share_group, start_dir, print_connect):
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
                   start_dir=start_dir)


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
            data = pane_registry.load_registry(session_name)
            for wdata in data.get("windows", {}).values():
                wdata["user_modified"] = False
            pane_registry.save_registry(session_name, data)
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
            click.echo(f"Window width: {width} (threshold: {pane_layout.MOBILE_WIDTH_THRESHOLD})")
        else:
            click.echo(f"Session: {session_name} (not running)")
            click.echo(f"Force flag: {force_flag}")
            click.echo(f"Threshold: {pane_layout.MOBILE_WIDTH_THRESHOLD}")


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

    data = pane_registry.load_registry(session)
    wdata = pane_registry.get_window_data(data, window)
    if not wdata["panes"]:
        click.echo("No panes registered for this session.", err=True)
        raise SystemExit(1)

    wdata["user_modified"] = False
    pane_registry.save_registry(session, data)

    # Unzoom before rebalance so layout applies to all panes
    tmux_mod.unzoom_pane(session, window)
    pane_layout.rebalance(session, window)
    click.echo("Layout rebalanced.")


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
