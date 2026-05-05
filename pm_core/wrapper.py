"""Entry point wrapper that prefers local pm_core when available.

When running from a directory containing pm_core (e.g., a workdir clone),
this wrapper uses the local version instead of the installed one. This
enables testing changes in PR workdirs without reinstalling.

The wrapper also checks ~/.pm/sessions/ for session overrides, allowing
pm meta sessions to redirect the installation to their working directory.
"""
import hashlib
import os
import sys
from pathlib import Path


def _get_session_tag() -> str | None:
    """Generate session tag from current git repository."""
    from pm_core.git_ops import get_git_root, get_github_repo_name

    git_root = get_git_root()
    if not git_root:
        return None

    repo_name = get_github_repo_name(git_root) or git_root.name
    path_hash = hashlib.md5(str(git_root).encode()).hexdigest()[:8]

    return f"{repo_name}-{path_hash}"


def _find_active_override() -> str | None:
    """Check for an active session override.

    Derives session tag from current git repo and checks for override file.
    """
    session_tag = _get_session_tag()
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
    base = session.split("~", 1)[0]
    if base.startswith("pm-"):
        return base[3:]
    return None


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
    is_ipc = _is_session_ipc_command(sys.argv)

    selected_root: str | None = None
    chosen_via: str = "installed"

    override_root = _find_active_override()
    if override_root:
        selected_root = override_root
        chosen_via = "override"
    else:
        # Resolve session tag — IPC commands carry it in argv, others
        # fall back to deriving it from cwd (same as the override path).
        tag = _ipc_session_tag(sys.argv) if is_ipc else _get_session_tag()
        pm_root_root = _pm_core_from_pm_root(tag)
        if pm_root_root:
            selected_root = pm_root_root
            chosen_via = "pm_root"
        elif not is_ipc:
            local_root = find_local_pm_core()
            if local_root:
                selected_root = local_root
                chosen_via = "cwd_walk"

    try:
        from pm_core.paths import configure_logger
        _log = configure_logger("pm.wrapper")
        _log.info(
            "wrapper: argv0=%s selected_root=%s chosen_via=%s is_ipc=%s",
            sys.argv[0], selected_root, chosen_via, is_ipc,
        )
    except Exception:
        pass

    if selected_root and selected_root not in sys.path:
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
