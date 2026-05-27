"""Centralized path management for pm.

All pm-related directories now live under ~/.pm/:
- ~/.pm/pane-registry/  - Pane tracking and logs
- ~/.pm/workdirs/       - PR and meta workdirs
- ~/.pm/sessions/{tag}/captures/{pr-id}/  - QA / bug-fix / regression captures
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


def pm_core_path() -> Path:
    """Return the path to the currently-imported ``pm_core`` package dir.

    This is the source the ``pm`` CLI is actually running from — for an
    editable install (``install.sh --local``) that's the source checkout;
    for a non-editable install it's a site-packages copy.  The repo root
    (the dir containing ``install.sh`` / ``pyproject.toml``) is the
    parent of this path when running from a source checkout.
    """
    import pm_core
    return Path(pm_core.__path__[0])


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


def _resolve_session_tag(start_path: Path | None = None) -> str | None:
    """Resolve the active session tag.

    Only consults the pm-session helper when actually inside a tmux pm
    session — its cwd-based fallback synthesises a bogus
    "pm-<name>-00000000" tag for any cwd, which would silently route
    captures to a fake session dir when run from a non-git cwd.
    """
    pm_sess = None
    try:
        from pm_core import tmux as tmux_mod
        if tmux_mod.in_tmux():
            from pm_core.cli.helpers import _get_pm_session
            pm_sess = _get_pm_session()
    except Exception:
        pm_sess = None
    if pm_sess:
        return pm_sess.removeprefix("pm-")
    return get_session_tag(start_path=start_path)


def captures_dir(pr_id: str,
                 session_tag: str | None = None,
                 start_path: Path | None = None) -> Path | None:
    """Return the captures directory for *pr_id*.

    Single source of truth for captures-path resolution across every
    surface (host orchestrator, scenario container, bug-fix flow
    session, review pane, CLI). Resolution:

    1. The host path ``~/.pm/sessions/<tag>/captures/<pr_id>/`` if it
       already exists. ``tag`` is *session_tag* if supplied, else the
       tmux-derived tag, else the cwd-derived tag.
    2. Otherwise the container bind-mount at
       :data:`CONTAINER_CAPTURES_MOUNT` if it exists (set up by
       :func:`container.create_container`).
    3. Otherwise create and return the host path.

    The ``~/.pm`` path takes precedence so on the host we always land
    in the canonical location; inside a container the host path
    doesn't exist and we fall through to the bind-mount.

    Returns None when no tag can be derived AND the bind-mount isn't
    present.
    """
    if session_tag is None:
        session_tag = _resolve_session_tag(start_path)
    host_path: Path | None = None
    if session_tag:
        host_path = sessions_dir() / session_tag / "captures" / pr_id
        if host_path.is_dir():
            return host_path
    mount = Path(CONTAINER_CAPTURES_MOUNT)
    if mount.is_dir():
        return mount
    if host_path is not None:
        host_path.mkdir(parents=True, exist_ok=True)
        return host_path
    return None


def captures_root(session_tag: str | None = None,
                  start_path: Path | None = None) -> Path | None:
    """Return the host captures *root* (``~/.pm/sessions/<tag>/captures/``).

    This is the directory that holds every per-PR captures dir plus the
    all-PR behavior dashboard (``index.html``). Tag resolution mirrors
    :func:`captures_dir`: *session_tag* if supplied, else the pm-session
    tag, else the cwd/tmux-derived tag. Returns ``None`` when no tag can
    be derived (e.g. not inside a git repo). The directory is created if
    it doesn't exist when a tag is available.
    """
    if session_tag is None:
        session_tag = _resolve_session_tag(start_path)
    if not session_tag:
        return None
    root = sessions_dir() / session_tag / "captures"
    root.mkdir(parents=True, exist_ok=True)
    return root


# Container-internal path where the host's captures_dir is bind-mounted
# during container creation. Workers running in containers reference
# this fixed path; the host filesystem path is invisible to them.
# Namespaced (``/pm-captures`` rather than ``/captures``) to reduce the
# chance of colliding with anything the host repo might already have at
# a top-level ``/captures`` path.
CONTAINER_CAPTURES_MOUNT = "/pm-captures"


def latest_qa_status_path(pr_id: str) -> Path | None:
    """Return the most-recent ``qa_status.json`` for *pr_id*, or None.

    Single source of truth for locating a PR's latest QA status file under
    ``~/.pm/workdirs/qa/<pr_id>-*/qa_status.json`` (a fresh QA run gets a new
    ``<pr_id>-<hex>`` workdir, so several may exist; the newest mtime wins).
    Shared by the auto-sequence QA gate and the sign-off prompt/evidence
    surfaces so they never drift.
    """
    qa_dir = workdirs_base() / "qa"
    if not qa_dir.is_dir():
        return None
    candidates = sorted(qa_dir.glob(f"{pr_id}-*/qa_status.json"),
                        key=lambda p: p.stat().st_mtime if p.exists() else 0)
    return candidates[-1] if candidates else None


def sessions_dir() -> Path:
    """Return the sessions directory (~/.pm/sessions/).

    Contains per-session configuration files:
    - {session-tag}/override  - Path to workdir for installation override
    - {session-tag}/debug     - If contains 'true', enable debug logging
    - {session-tag}/dangerously-skip-permissions - If contains 'true', skip Claude permissions
    - {session-tag}/fake-claude - JSON config to replace Claude with bin/fake-claude
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


def fake_claude_config(session_tag: str | None = None) -> dict | None:
    """Return the raw fake-claude config dict for the current session, or None.

    Looks for ``~/.pm/sessions/{session-tag}/fake-claude`` containing JSON in
    the per-session-type format::

        {
          "_defaults": {"preamble": 3, "delay": 0.5},
          "review":          {"verdicts": {"PASS": 70, "NEEDS_WORK": 20, "INPUT_REQUIRED": 10}},
          "qa_scenario":     {"verdicts": {"PASS": 80, "NEEDS_WORK": 15, "INPUT_REQUIRED": 5}},
          "qa_verification": {"verdicts": {"VERIFIED": 80, "FLAGGED": 20}},
          "qa_planning":     {"verdicts": {"QA_PLAN": 100}}
        }

    Top-level keys are session types (``model_config.SESSION_TYPES``) plus the
    special ``"_defaults"`` key for shared preamble/delay/body parameters.
    Session types absent from the file are NOT faked — they use real Claude.

    Returns the raw dict.  Use ``fake_claude_config_for_type()`` to get the
    fully-merged config for a specific session type.
    """
    import json
    sd = session_dir(session_tag)
    if not sd:
        return None
    f = sd / "fake-claude"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except (OSError, IOError, json.JSONDecodeError):
        return None


def fake_claude_config_for_type(
    session_type: str | None,
    session_tag: str | None = None,
) -> dict | None:
    """Return the merged fake-claude config for *session_type*, or None.

    Merges ``_defaults`` with the per-type entry and returns a flat dict
    suitable for ``_fake_claude_args()``.

    The special ``_all`` key turns on "fake everything" mode: any session
    type without its own entry — and any call with no *session_type* at all —
    falls back to ``_all`` (its ``verdicts``, if any, are ignored).  Explicit
    per-type entries still win over ``_all``.

    ``_all`` is a no-verdict session by default, *except* for verdict-producing
    session types (``review``, ``qa_finalize``, … — anything with a non-empty
    entry in ``SESSION_TYPE_VERDICTS``).  Routing such a type through the
    no-verdict catch-all would launch the no-verdict mock, which never emits a
    verdict and hangs the verdict poller forever; so a catch-all'd
    verdict-producing session is given its default (first/happy-path) verdict
    instead.  To force a genuinely no-verdict session for such a type, give it
    an explicit per-type entry with empty ``verdicts``.

    Returns None when:

    - no fake-claude config file exists, or
    - *session_type* has no entry and there is no ``_all`` catch-all.
    """
    raw = fake_claude_config(session_tag)
    if raw is None:
        return None
    type_config = raw.get(session_type) if session_type else None
    if type_config is not None and not isinstance(type_config, dict):
        # A hand-edited file may carry a malformed per-type entry; treat a
        # non-dict as absent rather than crashing the launcher downstream.
        type_config = None
    if type_config is None:
        all_config = raw.get("_all")
        if all_config is None:
            return None
        # Tolerate a malformed (non-dict) ``_all`` from a hand-edited file —
        # ``set_fake_claude_config`` rejects it, but a directly-written file
        # should not crash the launcher on ``.items()``.
        if not isinstance(all_config, dict):
            all_config = {}
        # Catch-all is a no-verdict session by default — strip any stray
        # verdicts.
        type_config = {k: v for k, v in all_config.items() if k != "verdicts"}
        # ...but a verdict-producing session type routed through the catch-all
        # with no verdict would launch the no-verdict mock and hang the verdict
        # poller forever. Give it its default (happy-path) verdict instead.
        from pm_core.fake_claude import SESSION_TYPE_VERDICTS
        allowed = SESSION_TYPE_VERDICTS.get(session_type or "", ())
        if allowed:
            type_config["verdicts"] = {allowed[0]: 1}
    defaults = raw.get("_defaults", {})
    if not isinstance(defaults, dict):
        defaults = {}
    merged = {**defaults, **type_config}
    return merged


def set_fake_claude_config(session_tag: str, config: dict) -> None:
    """Write fake-claude config JSON to ``~/.pm/sessions/{tag}/fake-claude``.

    Validates that every session-type entry only contains verdicts that are
    valid for that session type.  Raises ``ValueError`` listing all problems
    so callers can surface them before writing.
    """
    import json
    from pm_core.fake_claude import validate_session_verdicts

    errors: list[str] = []
    for key, value in config.items():
        if key == "_all":
            # Catch-all "fake everything" entry — a no-verdict session, so it
            # must not carry verdicts (they would be silently ignored).
            if not isinstance(value, dict):
                errors.append(
                    f"'_all' must be a dict, got {type(value).__name__}."
                )
            elif value.get("verdicts"):
                errors.append(
                    "'_all' is a no-verdict catch-all; remove its 'verdicts'."
                )
            continue
        if key.startswith("_"):
            # _defaults — shared preamble/delay/body params, merged into every
            # resolved config, so it too must be a dict (a non-dict would crash
            # the {**defaults, ...} merge in fake_claude_config_for_type).
            if not isinstance(value, dict):
                errors.append(
                    f"{key!r} must be a dict, got {type(value).__name__}."
                )
            continue  # not a session-type entry — no verdict validation
        if not isinstance(value, dict):
            errors.append(f"Config entry {key!r} must be a dict, got {type(value).__name__}")
            continue
        verdicts = value.get("verdicts", {})
        errors.extend(validate_session_verdicts(key, verdicts))

    if errors:
        raise ValueError(
            "Invalid fake-claude config:\n" + "\n".join(f"  \u2022 {e}" for e in errors)
        )

    sd = session_dir(session_tag)
    if sd:
        (sd / "fake-claude").write_text(json.dumps(config, indent=2) + "\n")
        # Re-declaring the config resets scripted-sequence cursors: the
        # sidecar is stale state for the *previous* config, and a fresh
        # config should start its sequences at slot 0 (otherwise a shorter
        # new sequence resumes mid-stream, silently mis-modelling iteration
        # order — the exact flakiness scripted sequences exist to avoid).
        state = sd / "fake-claude.state"
        if state.exists():
            state.unlink()


def clear_fake_claude(session_tag: str) -> None:
    """Remove the fake-claude config file (and scripted-cursor sidecar) for a session."""
    sd = session_dir(session_tag)
    if sd:
        for name in ("fake-claude", "fake-claude.state"):
            f = sd / name
            if f.exists():
                f.unlink()


def fake_github_dir(session_tag: str | None = None) -> "Path | None":
    """Return ``~/.pm/sessions/{tag}/fake-github/`` for the session, or None.

    Does NOT create the directory (so it is cheap to probe on every ``run_gh``
    call). The out-of-process fake-github lives here — a ``state.json`` holding
    the serialized PR registry / scripted responses plus a ``remote.git/``
    backing repo. Mirrors the per-session ``fake-claude`` config gate.
    """
    tag = session_tag or get_session_tag()
    if not tag:
        return None
    return sessions_dir() / tag / "fake-github"


def fake_github_active(session_tag: str | None = None) -> bool:
    """True if an out-of-process fake-github is installed for the session.

    Consulted by ``gh_ops.run_gh`` (when no in-process transport is installed)
    to route ``gh`` commands to the fake instead of the real GitHub API.
    """
    d = fake_github_dir(session_tag)
    return bool(d and (d / "state.json").exists())


def clear_fake_github(session_tag: str | None = None) -> None:
    """Remove the out-of-process fake-github state for a session."""
    import shutil
    d = fake_github_dir(session_tag)
    if d and d.exists():
        shutil.rmtree(d)


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
    # Derive short source tag from logger name for easy grep filtering.
    # "pm.tui.app" -> "tui.app", "pm.qa_loop" -> "qa_loop"
    source = name.removeprefix("pm.")
    handler.setFormatter(logging.Formatter(
        f"%(asctime)s %(levelname)-5s [{source}] %(message)s", datefmt="%H:%M:%S"
    ))
    logger.addHandler(handler)
    logger.propagate = False

    # Debug level when debug mode enabled, INFO otherwise (still logs commands)
    if debug_enabled():
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    return logger


def set_session_pm_root(session_tag: str, root: Path) -> None:
    """Persist the project root for a session.

    Stored at ~/.pm/sessions/{session-tag}/pm_root so popup commands can
    resolve the root without depending on the launching pane's cwd.
    """
    sd = session_dir(session_tag)
    if sd:
        (sd / "pm_root").write_text(str(root) + "\n")


def get_session_pm_root(session_tag: str | None = None) -> Path | None:
    """Read the persisted project root for a session, if any.

    Returns None if the file is missing, empty, or the path no longer
    exists on disk (so callers fall back to cwd-based resolution).
    """
    sd = session_dir(session_tag)
    if not sd:
        return None
    f = sd / "pm_root"
    if not f.exists():
        return None
    try:
        content = f.read_text().strip()
    except (OSError, IOError):
        return None
    if not content:
        return None
    p = Path(content)
    return p if p.exists() else None


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


def has_global_setting(name: str) -> bool:
    """Check if a global pm setting has been explicitly configured (on or off).

    Returns True if the setting file exists (regardless of value).
    Returns False if the setting has never been set.
    """
    return (pm_home() / "settings" / name).exists()


def set_global_setting(name: str, enabled: bool) -> None:
    """Enable or disable a global pm setting."""
    d = pm_home() / "settings"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    if enabled:
        f.write_text("true\n")
    else:
        f.write_text("false\n")


def get_global_setting_value(name: str, default: str = "") -> str:
    """Read a global setting's raw string value.

    Returns *default* if the file doesn't exist or can't be read.
    """
    f = pm_home() / "settings" / name
    try:
        return f.read_text().strip()
    except (FileNotFoundError, OSError):
        return default


def set_global_setting_value(name: str, value: str) -> None:
    """Write a raw string value for a global setting."""
    d = pm_home() / "settings"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(value + "\n")


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
                entry = f"{timestamp} INFO  [{prefix}] done: {cmd_str}\n"
            else:
                entry = f"{timestamp} WARN  [{prefix}] failed (rc={returncode}): {cmd_str}\n"
        else:
            entry = f"{timestamp} INFO  [{prefix}] {cmd_str}\n"

        with open(log_file, "a") as f:
            f.write(entry)
    except (OSError, IOError):
        pass  # Silently fail if we can't write to log


def bench_cache_dir() -> Path:
    """Return the bench exercise cache directory (~/.cache/pm-bench/)."""
    d = Path.home() / ".cache" / "pm-bench"
    d.mkdir(parents=True, exist_ok=True)
    return d


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
