"""Entry point wrapper that prefers local pm_core when available.

When running from a directory containing pm_core (e.g., a workdir clone),
this wrapper uses the local version instead of the installed one. This
enables testing changes in PR workdirs without reinstalling.

The wrapper also checks ~/.pm/sessions/ for session overrides, allowing
pm meta sessions to redirect the installation to their working directory.
"""
import os
import sys
from pathlib import Path


def _get_session_tag() -> str | None:
    """Session tag for the current git repository.

    Delegates to ``paths.get_session_tag``: the override and pm_root
    lookups must use exactly the tag ``pm session`` and ``pm meta`` wrote
    them under (tmux-safe repo name, share-mode hash and all).  Importing
    it here is no earlier than before: ``git_ops`` already imports
    ``pm_core.paths`` from the same copy, and ``_run_cli`` purges both
    once another pm_core is chosen.  A hand copy here drifted once
    (review-loop 68bd i1: it left PM_SHARE_MODE out of the hash).
    """
    from pm_core.paths import get_session_tag

    return get_session_tag()


def _find_active_override() -> str | None:
    """Check for an active session override.

    Derives session tag from current git repo and checks for override file.
    """
    return _override_for_tag(_get_session_tag())


def _override_for_tag(session_tag: str | None) -> str | None:
    """Return the override install root for *session_tag*, if one is set."""
    if not session_tag:
        return None

    override_file = Path.home() / ".pm" / "sessions" / session_tag / "override"
    if not override_file.exists():
        return None

    try:
        content = override_file.read_text().strip()
        if content:
            p = Path(content)
            if p.exists() and (p / "pm_core").is_dir():
                return str(p)
    except (OSError, IOError):
        pass
    return None


def find_local_pm_core():
    """Find pm_core in cwd or parent directories."""
    cwd = os.getcwd()
    # Check cwd and up to 3 parent directories
    for _ in range(4):
        candidate = os.path.join(cwd, "pm_core")
        if os.path.isdir(candidate) and os.path.isdir(os.path.join(candidate, "cli")):
            return cwd
        parent = os.path.dirname(cwd)
        if parent == cwd:
            break
        cwd = parent
    return None


def _mark_tmux_session(env: dict) -> None:
    """Set PM_IN_TMUX_SESSION=1 when running under tmux.

    Sub-commands consume this to default to TUI-parity behavior — e.g.
    ``pm pr merge`` enables ``--resolve-window`` so picker / shell-pane
    / command-bar invocations all launch a Claude resolution window
    when a merge needs one. Outside tmux the var stays unset and
    behavior is unchanged.
    """
    if env.get("TMUX"):
        env["PM_IN_TMUX_SESSION"] = "1"


def _mark_tmux_socket(env: dict) -> None:
    """Export the private pm tmux socket when running under one.

    Panes inherit ``PM_TMUX_SOCKET`` from the session environment, but
    ``run-shell`` hooks and ``display-popup`` bodies only reliably inherit
    ``$TMUX``.  Resolving it here — before any pm command runs — makes
    every tmux call inside hooks/popups target the session's own server.
    Ordinary (non-pm) tmux sessions are left alone.

    The socket directory comes from ``paths`` like the session tag does
    (see ``_get_session_tag``; ``_run_cli`` purges it once another pm_core
    is chosen).  The ``$TMUX`` parse repeats
    ``tmux.socket_path_from_tmux_env`` rather than importing it: importing
    ``pm_core.tmux`` configures its ``pm.tmux`` logger, and the purge drops
    modules but not ``logging``'s loggers, so the chosen pm_core would
    inherit a handler set up by the copy it replaced.
    """
    if env.get("PM_TMUX_SOCKET"):
        return
    raw = env.get("TMUX")
    if not raw:
        return
    from pm_core.paths import SHARED_SOCKET_DIR

    path = raw.rsplit(",", 2)[0]
    if path and os.path.dirname(path) == str(SHARED_SOCKET_DIR):
        env["PM_TMUX_SOCKET"] = path


def _is_session_ipc_command(argv: list[str]) -> bool:
    """Return True for hidden commands that drive session-level IPC.

    These are invoked from tmux key bindings or hooks; the launching
    pane's cwd is unreliable for code resolution (it can be any
    workdir clone with stale code). For these we resolve via the
    session's persisted pm_root rather than walking cwd.
    """
    for arg in argv[1:]:
        if arg.startswith("-"):
            continue
        return arg.startswith("_popup") or arg.startswith("_pane") or arg.startswith("_window") or arg in {"_tui", "rebalance"}
    return False


def _ipc_session_tag(argv: list[str]) -> str | None:
    """Best-effort session tag for an IPC invocation.

    _popup-picker / _popup-cmd / _pane-* / _window-* take the tmux
    session name as the first positional argument. Strip the
    grouped-session ~N suffix and the leading 'pm-' prefix to get the
    tag that keys ~/.pm/sessions/<tag>/.
    """
    pos = [a for a in argv[1:] if not a.startswith("-")]
    if len(pos) < 2:
        return None
    session = pos[1]
    # Only a *numeric* ``~N`` is a grouped suffix: a session name derived
    # from a repo directory may contain ``~`` itself, and splitting at the
    # first one would resolve another session's tag.  The shared
    # definition is used, not a copy: ``main`` has already imported
    # ``pm_core.paths`` (through ``_find_active_override``) by now.
    from pm_core.paths import base_session_name

    base = base_session_name(session)
    if base.startswith("pm-"):
        return base[3:]
    return None


def _session_tag(argv: list[str], is_ipc: bool) -> str | None:
    """Resolve the session tag from argv (IPC) or cwd (everything else).

    For IPC commands invoked from tmux key bindings the launching pane's
    cwd is unreliable, so we prefer the session name carried in argv.
    But not every IPC command takes a session arg (e.g. ``pm _tui``,
    ``pm rebalance``) — for those, and for all non-IPC commands, fall
    back to deriving the tag from the current git root.

    Returns None only when neither path yields a tag (e.g. ``pm`` run
    outside any git repo). Callers must handle that case explicitly.
    """
    tag = _ipc_session_tag(argv) if is_ipc else None
    if tag is None:
        tag = _get_session_tag()
    return tag


def _pm_core_from_pm_root(session_tag: str | None) -> str | None:
    """Resolve the pm_core source dir from a session's persisted pm_root.

    pm_root points at the project's pm/ dir. For pm-source-tracking
    repos the pm_core source lives at <pm_root>/../pm_core, so we use
    <pm_root>/.. as the import root. For ordinary user repos that
    only have pm/ (no pm_core source) this returns None and the
    caller falls through to the installed pm_core.
    """
    if not session_tag:
        return None
    pm_root_file = Path.home() / ".pm" / "sessions" / session_tag / "pm_root"
    if not pm_root_file.exists():
        return None
    try:
        content = pm_root_file.read_text().strip()
    except (OSError, IOError):
        return None
    if not content:
        return None
    pm_root = Path(content)
    parent = pm_root.parent
    if (parent / "pm_core" / "cli").is_dir():
        return str(parent)
    return None


def main():
    """Entry point that prefers session-aware pm_core resolution.

    Priority order:
    1. Active session override (from ~/.pm/sessions/<tag>/override)
       — explicit redirect, used by ``pm meta`` and QA loops.
    2. Session pm_root (from ~/.pm/sessions/<tag>/pm_root) — the
       pm_core that started this session is the right code to run for
       IPC commands and for any command from inside the session's
       scope.
    3. Local pm_core walked from cwd (non-IPC commands only) — legacy
       fallback for ad-hoc invocations from a workdir clone.
    4. Installed pm_core.
    """
    _mark_tmux_session(os.environ)
    _mark_tmux_socket(os.environ)
    is_ipc = _is_session_ipc_command(sys.argv)

    selected_root: str | None = None
    chosen_via: str = "installed"

    override_root = _find_active_override()
    if override_root:
        selected_root = override_root
        chosen_via = "override"
    else:
        tag = _session_tag(sys.argv, is_ipc)
        pm_root_root = _pm_core_from_pm_root(tag)
        if pm_root_root:
            selected_root = pm_root_root
            chosen_via = "pm_root"
        elif not is_ipc:
            local_root = find_local_pm_core()
            if local_root:
                selected_root = local_root
                chosen_via = "cwd_walk"

    _log_resolution(
        "wrapper: argv0=%s selected_root=%s chosen_via=%s is_ipc=%s",
        sys.argv[0], selected_root, chosen_via, is_ipc,
    )
    return _run_cli(selected_root)


def main_for_session(session_tag: str):
    """Entry point for commands dispatched from a session's tmux popups.

    The prefix+P picker and prefix+M runner run their child pm command
    in the popup's cwd, which is often a PR workdir clone carrying
    unmerged pm_core code.  Those commands must run the *session's* pm,
    so resolution is keyed only on *session_tag* (taken from the tmux
    session name) and never on cwd:

    1. Session override for *session_tag*.
    2. Session pm_root for *session_tag*.
    3. The dispatcher's own pm_core (already first on sys.path).

    Only reached through ``pm_core.cli.session._session_pm_argv``;
    every other invocation goes through :func:`main`.
    """
    _mark_tmux_session(os.environ)
    _mark_tmux_socket(os.environ)

    selected_root: str | None = None
    chosen_via: str = "dispatcher"

    override_root = _override_for_tag(session_tag)
    if override_root:
        selected_root = override_root
        chosen_via = "override"
    else:
        pm_root_root = _pm_core_from_pm_root(session_tag)
        if pm_root_root:
            selected_root = pm_root_root
            chosen_via = "pm_root"

    _log_resolution(
        "wrapper: argv0=%s selected_root=%s chosen_via=%s session_tag=%s",
        sys.argv[0], selected_root, chosen_via, session_tag,
    )
    return _run_cli(selected_root, front=True)


def _log_resolution(fmt: str, *args) -> None:
    try:
        from pm_core.paths import configure_logger
        _log = configure_logger("pm.wrapper")
        _log.info(fmt, *args)
    except Exception:
        pass


def _run_cli(selected_root: str | None, front: bool = False):
    """Put *selected_root* on sys.path (if given) and run the CLI.

    By default a root already on sys.path is left where it is; with
    *front* it is moved ahead of everything else (e.g. a PYTHONPATH
    entry carrying another pm_core).
    """
    if selected_root and (selected_root not in sys.path
                          or (front and sys.path[0] != selected_root)):
        sys.path.insert(0, selected_root)
        to_remove = [k for k in sys.modules
                     if k == 'pm_core' or k.startswith('pm_core.')]
        for k in to_remove:
            del sys.modules[k]

    # Now import and run the real CLI
    from pm_core.cli import main as cli_main
    return cli_main()


if __name__ == '__main__':
    sys.exit(main())
