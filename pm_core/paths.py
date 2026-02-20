"""Centralized path management for pm.

All pm-related directories now live under ~/.pm/:
- ~/.pm/pane-registry/  - Pane tracking and logs
- ~/.pm/workdirs/       - PR and meta workdirs
- ~/.pm/sessions/       - Per-session config (overrides, debug, dangerously-skip-permissions)

Session tags are derived from the git repo (GitHub repo name or directory name + hash).
"""

import grp
import hashlib
import pwd
import logging
import os
import shlex
import subprocess
from pathlib import Path

# Cache for session tags to avoid repeated subprocess calls
_session_tag_cache: dict[str, str | None] = {}


def pm_home() -> Path:
    """Return the pm home directory (~/.pm/)."""
    d = Path.home() / ".pm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pane_registry_dir() -> Path:
    """Return the pane registry directory (~/.pm/pane-registry/)."""
    d = pm_home() / "pane-registry"
    d.mkdir(parents=True, exist_ok=True)
    return d


def debug_dir() -> Path:
    """Return the debug/logs directory (~/.pm/debug/).

    Contains per-session log files for debugging.
    """
    d = pm_home() / "debug"
    d.mkdir(parents=True, exist_ok=True)
    return d


def workdirs_base() -> Path:
    """Return the workdirs base directory (~/.pm/workdirs/)."""
    d = pm_home() / "workdirs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sessions_dir() -> Path:
    """Return the sessions directory (~/.pm/sessions/).

    Contains per-session configuration files:
    - {session-tag}/override  - Path to workdir for installation override
    - {session-tag}/debug     - If contains 'true', enable debug logging
    - {session-tag}/dangerously-skip-permissions - If contains 'true', skip Claude permissions
    """
    d = pm_home() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_session_tag(start_path: Path | None = None, use_github_name: bool = True) -> str | None:
    """Generate session tag from the current git repository.

    Format: {repo_name}-{hash} where:
    - repo_name is GitHub repo name (without org/user) or directory name
    - hash is MD5 of the git root path (8 chars)

    Works from any subdirectory of the repo.
    Returns None if not in a git repository.
    Results are cached to avoid repeated subprocess calls.

    Args:
        start_path: Path to start searching from (default: cwd)
        use_github_name: If True, try to get GitHub repo name (requires subprocess).
                        If False, just use directory name (faster, no subprocess).
    """
    from pm_core.git_ops import get_git_root, get_github_repo_name

    share_mode = os.environ.get("PM_SHARE_MODE")
    cache_key = (str(start_path or Path.cwd()), use_github_name, share_mode)
    if cache_key in _session_tag_cache:
        return _session_tag_cache[cache_key]

    git_root = get_git_root(start_path)
    if not git_root:
        _session_tag_cache[cache_key] = None
        return None

    # Get repo name - optionally try GitHub, always fall back to directory name
    if use_github_name:
        repo_name = get_github_repo_name(git_root) or git_root.name
    else:
        repo_name = git_root.name

    # Generate hash from git root path, mixing in share mode when set
    # so --global and --group sessions get distinct tags
    hash_input = str(git_root)
    if share_mode:
        hash_input += "\0" + share_mode
    path_hash = hashlib.md5(hash_input.encode()).hexdigest()[:8]

    tag = f"{repo_name}-{path_hash}"
    _session_tag_cache[cache_key] = tag
    return tag


def session_dir(session_tag: str | None = None) -> Path | None:
    """Get the directory for a specific session's config files.

    If session_tag is None, derives it from the current git repo.
    Returns None if no session can be determined.
    """
    tag = session_tag or get_session_tag()
    if not tag:
        return None
    d = sessions_dir() / tag
    d.mkdir(parents=True, exist_ok=True)
    return d


def debug_enabled(session_tag: str | None = None) -> bool:
    """Check if debug mode is enabled for current session.

    Looks for ~/.pm/sessions/{session-tag}/debug file (just needs to exist).
    """
    sd = session_dir(session_tag)
    if not sd:
        return False
    return (sd / "debug").exists()


def set_debug(session_tag: str, enabled: bool = True) -> None:
    """Enable or disable debug mode for a session."""
    sd = session_dir(session_tag)
    if sd:
        debug_file = sd / "debug"
        if enabled:
            debug_file.touch()
        elif debug_file.exists():
            debug_file.unlink()


def skip_permissions_enabled(session_tag: str | None = None) -> bool:
    """Check if dangerously-skip-permissions mode is enabled for current session.

    Looks for ~/.pm/sessions/{session-tag}/dangerously-skip-permissions
    file containing exactly 'true'.
    """
    sd = session_dir(session_tag)
    if not sd:
        return False
    skip_file = sd / "dangerously-skip-permissions"
    if not skip_file.exists():
        return False
    try:
        return skip_file.read_text().strip() == "true"
    except (OSError, IOError):
        return False


def set_skip_permissions(session_tag: str, enabled: bool = True) -> None:
    """Enable or disable dangerously-skip-permissions mode for a session."""
    sd = session_dir(session_tag)
    if sd:
        skip_file = sd / "dangerously-skip-permissions"
        if enabled:
            skip_file.write_text("true\n")
        elif skip_file.exists():
            skip_file.unlink()


def configure_logger(name: str, log_file: str | None = None, max_bytes: int = 10_000_000) -> logging.Logger:
    """Configure a logger that always writes to file with rotation.

    Args:
        name: Logger name (e.g., "pm.tui")
        log_file: Optional filename override. If None, uses session-based log file
                  in ~/.pm/debug/{session-tag}.log
        max_bytes: Maximum log file size before rotation (default 10MB, ~100k lines)

    Returns:
        Configured logger instance
    """
    from logging.handlers import RotatingFileHandler

    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers
    if logger.handlers:
        return logger

    # Use session-based log file in debug dir
    log_path = command_log_file()
    handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=1,  # Keep one backup file
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
    ))
    logger.addHandler(handler)
    logger.propagate = False

    # Debug level when debug mode enabled, INFO otherwise (still logs commands)
    if debug_enabled():
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    return logger


def get_override_path(session_tag: str | None = None) -> Path | None:
    """Get the override installation path for a session, or None if not set.

    If session_tag is None, derives it from the current git repo.
    """
    sd = session_dir(session_tag)
    if not sd:
        return None
    override_file = sd / "override"
    if override_file.exists():
        content = override_file.read_text().strip()
        if content:
            p = Path(content)
            if p.exists() and (p / "pm_core").is_dir():
                return p
    return None


def set_override_path(session_tag: str, workdir: Path) -> None:
    """Set the override installation path for a session."""
    sd = session_dir(session_tag)
    if sd:
        (sd / "override").write_text(str(workdir) + "\n")


def get_global_setting(name: str) -> bool:
    """Check if a global pm setting is enabled.

    Settings are stored as files in ~/.pm/settings/.
    A setting is enabled if its file exists and contains 'true'.
    """
    f = pm_home() / "settings" / name
    if not f.exists():
        return False
    try:
        return f.read_text().strip() == "true"
    except (OSError, IOError):
        return False


def set_global_setting(name: str, enabled: bool) -> None:
    """Enable or disable a global pm setting."""
    d = pm_home() / "settings"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    if enabled:
        f.write_text("true\n")
    elif f.exists():
        f.unlink()


def clear_session(session_tag: str) -> None:
    """Remove all config files for a session."""
    sd = sessions_dir() / session_tag
    if sd.exists():
        import shutil
        shutil.rmtree(sd)


def command_log_file(session_tag: str | None = None) -> Path:
    """Get the path to the command log file for a session.

    All pm commands log their shell executions here.
    Located at ~/.pm/debug/{session-tag}.log

    If session_tag is None, derives it from the current git repo.
    Falls back to 'default.log' if not in a git repo.
    """
    # Use fast version (no subprocess) to avoid issues during import
    tag = session_tag or get_session_tag(use_github_name=False) or "default"
    return debug_dir() / f"{tag}.log"


def log_shell_command(cmd: list[str] | str, prefix: str = "shell", returncode: int | None = None) -> None:
    """Log a shell command to the central command log.

    All pm shell commands (git, gh, etc.) are logged here for debugging.
    The TUI and CLI commands share the same log file.

    Args:
        cmd: Command list or string to log
        prefix: Prefix for the log entry (e.g., "shell", "git", "gh")
        returncode: If provided, logs as completion with return code
    """
    log_file = command_log_file()
    cmd_str = shlex.join(cmd) if isinstance(cmd, list) else cmd

    try:
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")

        if returncode is not None:
            if returncode == 0:
                entry = f"{timestamp} INFO  {prefix} done: {cmd_str}\n"
            else:
                entry = f"{timestamp} WARN  {prefix} failed (rc={returncode}): {cmd_str}\n"
        else:
            entry = f"{timestamp} INFO  {prefix}: {cmd_str}\n"

        with open(log_file, "a") as f:
            f.write(entry)
    except (OSError, IOError):
        pass  # Silently fail if we can't write to log


SHARED_SOCKET_DIR = Path("/tmp/pm-sessions")


def shared_socket_path(session_tag: str) -> Path:
    """Return the deterministic socket path for a shared session.

    Both the creating user and joining users compute the same path
    from the session tag, so they find each other's tmux server.
    """
    return SHARED_SOCKET_DIR / f"pm-{session_tag}"


def ensure_shared_socket_dir() -> None:
    """Create /tmp/pm-sessions/ with sticky world-writable permissions.

    Uses 1777 (sticky + rwx for all) so any user can create sockets
    but only the owner can delete their own.
    """
    SHARED_SOCKET_DIR.mkdir(mode=0o1777, parents=True, exist_ok=True)
    # Ensure permissions are correct even if directory already existed
    SHARED_SOCKET_DIR.chmod(0o1777)


def set_shared_socket_permissions(socket_path: Path, group_name: str | None = None) -> None:
    """Set permissions on a tmux socket for multi-user access.

    Args:
        socket_path: Path to the tmux socket file
        group_name: Unix group name for group-shared mode.
                    If None, sets world-accessible permissions (global mode).
    """
    if group_name:
        # Validate group first (raises KeyError if invalid)
        gid = grp.getgrnam(group_name).gr_gid
        try:
            os.chown(str(socket_path), -1, gid)
            # chown succeeded — restrict to owner+group
            socket_path.chmod(0o770)
        except (PermissionError, OSError):
            # chown requires root or membership in the target group.
            # Fall back to world-accessible and rely on tmux server-access
            # grants (tmux 3.3+) for actual access control.
            socket_path.chmod(0o777)
    else:
        socket_path.chmod(0o777)


def get_share_users(group_name: str | None = None) -> list[str]:
    """Return usernames that should be granted tmux server-access.

    Args:
        group_name: If given, return members of that Unix group.
                    If None (global mode), return all regular users (UID >= 1000).
    """
    current_user = os.getenv("USER", "")
    if group_name:
        members = grp.getgrnam(group_name).gr_mem
        return [u for u in members if u != current_user]
    # Global mode: all regular (non-system) users
    # UID 65534 is conventionally 'nobody', so cap at 60000
    return [
        pw.pw_name for pw in pwd.getpwall()
        if 1000 <= pw.pw_uid < 60000 and pw.pw_name != current_user
    ]


def run_shell_logged(cmd: list[str], prefix: str = "shell", **kwargs) -> subprocess.CompletedProcess:
    """Run a shell command with logging to command log.

    This is a convenience wrapper that logs the command before execution
    and the result after.

    Args:
        cmd: Command list to run
        prefix: Prefix for log entries
        **kwargs: Passed to subprocess.run

    Returns:
        CompletedProcess result
    """
    log_shell_command(cmd, prefix)
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        log_shell_command(cmd, prefix, result.returncode)
    return result
