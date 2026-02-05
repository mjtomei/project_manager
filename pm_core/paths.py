"""Centralized path management for pm.

All pm-related directories now live under ~/.pm/:
- ~/.pm/pane-registry/  - Pane tracking and logs
- ~/.pm/workdirs/       - PR and meta workdirs
- ~/.pm/sessions/       - Per-session config (overrides, debug, dangerously-skip-permissions)

Session-specific files use PM_SESSION env var to identify the current session.
"""

import logging
import os
from pathlib import Path


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


def workdirs_base() -> Path:
    """Return the workdirs base directory (~/.pm/workdirs/)."""
    d = pm_home() / "workdirs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sessions_dir() -> Path:
    """Return the sessions directory (~/.pm/sessions/).

    Contains per-session configuration files:
    - {session-tag}/override  - Path to workdir for installation override
    - {session-tag}/debug     - If exists, enable debug logging
    - {session-tag}/dangerously-skip-permissions - If exists, skip Claude permissions
    """
    d = pm_home() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_session_tag() -> str | None:
    """Get the current session tag from PM_SESSION env var."""
    return os.environ.get("PM_SESSION")


def session_dir(session_tag: str | None = None) -> Path | None:
    """Get the directory for a specific session's config files.

    If session_tag is None, uses get_session_tag() to find current session.
    Returns None if no session is active.
    """
    tag = session_tag or get_session_tag()
    if not tag:
        return None
    d = sessions_dir() / tag
    d.mkdir(parents=True, exist_ok=True)
    return d


def debug_enabled() -> bool:
    """Check if debug mode is enabled for current session.

    Looks for ~/.pm/sessions/{session-tag}/debug file.
    """
    sd = session_dir()
    if sd:
        return (sd / "debug").exists()
    return False


def set_debug(session_tag: str, enabled: bool = True) -> None:
    """Enable or disable debug mode for a session."""
    sd = session_dir(session_tag)
    if sd:
        debug_file = sd / "debug"
        if enabled:
            debug_file.touch()
        elif debug_file.exists():
            debug_file.unlink()


def skip_permissions_enabled() -> bool:
    """Check if dangerously-skip-permissions mode is enabled for current session.

    Looks for ~/.pm/sessions/{session-tag}/dangerously-skip-permissions file.
    """
    sd = session_dir()
    if sd:
        return (sd / "dangerously-skip-permissions").exists()
    return False


def set_skip_permissions(session_tag: str, enabled: bool = True) -> None:
    """Enable or disable dangerously-skip-permissions mode for a session."""
    sd = session_dir(session_tag)
    if sd:
        skip_file = sd / "dangerously-skip-permissions"
        if enabled:
            skip_file.touch()
        elif skip_file.exists():
            skip_file.unlink()


def configure_logger(name: str, log_file: str) -> logging.Logger:
    """Configure a logger that only writes to file when debug is enabled.

    Args:
        name: Logger name (e.g., "pm.tui")
        log_file: Filename within pane_registry_dir (e.g., "tui.log")

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    if debug_enabled():
        log_path = pane_registry_dir() / log_file
        handler = logging.FileHandler(log_path)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    else:
        # No handlers = no output, but set level to avoid "no handler" warnings
        logger.addHandler(logging.NullHandler())
        logger.setLevel(logging.WARNING)

    return logger


def get_override_path(session_tag: str | None = None) -> Path | None:
    """Get the override installation path for a session, or None if not set.

    If session_tag is None, uses get_session_tag() to find current session.
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


def clear_session(session_tag: str) -> None:
    """Remove all config files for a session."""
    sd = sessions_dir() / session_tag
    if sd.exists():
        import shutil
        shutil.rmtree(sd)


# Legacy compatibility - keep old function names working
def active_overrides_dir() -> Path:
    """Deprecated: use sessions_dir() instead."""
    return sessions_dir()


def get_active_override(session_tag: str) -> Path | None:
    """Deprecated: use get_override_path() instead."""
    return get_override_path(session_tag)


def set_active_override(session_tag: str, workdir: Path) -> None:
    """Deprecated: use set_override_path() instead."""
    set_override_path(session_tag, workdir)


def clear_active_override(session_tag: str) -> None:
    """Deprecated: use clear_session() instead."""
    sd = sessions_dir() / session_tag
    override_file = sd / "override"
    if override_file.exists():
        override_file.unlink()
    # Clean up empty session dir
    if sd.exists() and not any(sd.iterdir()):
        sd.rmdir()
