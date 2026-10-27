"""Install pm's Claude Code hooks into ~/.claude/settings.json.

Claude Code fires configured hooks on lifecycle events.  We install
three entries that all point at the standalone ``hook_receiver.py``
and write a file under ``~/.pm/hooks/`` keyed by session_id:

  * ``Notification[idle_prompt]`` — Claude finished its turn and is
    waiting for the next user message.  Drives verdict detection.
  * ``Notification[permission_prompt]`` — Claude Code is blocked on
    its own tool-approval dialog.  Drives the TUI's "waiting for
    input" indicator.
  * ``Stop`` — fires per-turn.  Retained for future use; readers
    currently ignore it (``pane_exists`` is the authoritative
    session-gone signal).

The installer is idempotent and merges into any existing user hooks.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import time
from pathlib import Path

from pm_core.paths import configure_logger

_log = configure_logger("pm.hook_install")


def _host_home() -> Path:
    """Home dir to embed in settings.json hook commands.

    Inside a pm-managed container, ``~/.claude`` is bind-mounted r/w from
    the host, so any path written into settings.json must be the *host*
    path or the host will fire hooks against a path that doesn't exist
    there. ``container.py`` exports ``PM_HOST_HOME`` for this purpose.
    """
    override = os.environ.get("PM_HOST_HOME")
    if override:
        return Path(override)
    return Path.home()


def _settings_path() -> Path:
    return _host_home() / ".claude" / "settings.json"


def _hooks_base() -> Path:
    return _host_home() / ".pm" / "hooks"


def _receiver_path() -> Path:
    # Standalone copy of pm_core/hook_receiver.py lives here so it can be
    # invoked without pm_core on sys.path (e.g. from inside a QA container
    # that bind-mounts this exact host path back into itself).
    return _host_home() / ".pm" / "hook_receiver.py"


# Module-level constants kept for back-compat with importers/tests.
_SETTINGS_PATH = _settings_path()
_HOOKS_BASE = _hooks_base()
RECEIVER_PATH = _receiver_path()
_STALE_SECONDS = 7 * 24 * 60 * 60  # 7 days


class HookConflictError(RuntimeError):
    """Raised when ~/.claude/settings.json already has hooks pm did not install."""


def _hook_command_for(event_type: str) -> str:
    """Build the hook command string.

    Runs the standalone receiver at its host absolute path via ``python3``
    (PATH lookup) so the same command string works on the host and inside
    containers that bind-mount the receiver at the same path.
    """
    return f"python3 {shlex.quote(str(_receiver_path()))} {shlex.quote(event_type)}"


def _install_receiver() -> None:
    """Copy pm_core/hook_receiver.py to RECEIVER_PATH.

    The receiver has no pm_core imports so it runs standalone inside
    containers where pm_core is not available.
    """
    # When running inside a container, the host's receiver is bind-mounted
    # read-only at this exact path; the host installer is the only writer.
    if os.environ.get("PM_HOST_HOME") and Path(os.environ["PM_HOST_HOME"]) != Path.home():
        return
    from pm_core import hook_receiver as _receiver_mod
    src = Path(_receiver_mod.__file__)
    dest = _receiver_path()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        dest.chmod(0o644)
    except OSError as e:
        _log.warning("could not copy hook receiver to %s: %s", dest, e)


_MANAGED_EVENTS = ("Notification", "Stop")


def _desired_hooks() -> dict:
    """Return the hook config we want present in settings.json.

    ``idle_prompt`` — agent turn ended, waiting for next user message.
    ``permission_prompt`` — Claude Code is about to show its own
        tool-approval dialog; the session is blocked waiting for the
        user to approve or deny.  Used by the TUI/tech-tree to render a
        "waiting for input" indicator distinct from plain idle.
    ``Stop`` — retained for future use (fires per-turn, not session
        exit) but the reader currently ignores it.
    """
    return {
        "Notification": [
            {
                "matcher": "idle_prompt",
                "hooks": [
                    {"type": "command", "command": _hook_command_for("idle_prompt")},
                ],
            },
            {
                "matcher": "permission_prompt",
                "hooks": [
                    {"type": "command", "command": _hook_command_for("permission_prompt")},
                ],
            },
        ],
        "Stop": [
            {
                "hooks": [
                    {"type": "command", "command": _hook_command_for("Stop")},
                ],
            }
        ],
    }


def _entry_is_pm(entry: dict) -> bool:
    receiver_str = str(_receiver_path())
    for hook in (entry or {}).get("hooks", []) or []:
        cmd = (hook or {}).get("command", "")
        # Current format references the standalone receiver path.
        # Also recognise the legacy ``-m pm_core.hook_receiver`` form so
        # installs upgrading from the old command get rewritten cleanly.
        if receiver_str in cmd or "pm_core.hook_receiver" in cmd:
            return True
    return False


def _detect_foreign_hooks(existing_hooks: dict) -> list[str]:
    """Return human-readable descriptions of hooks pm did not install.

    We only care about events pm manages (Notification idle_prompt,
    Stop).  Other events are the user's business and we leave them alone.
    """
    foreign: list[str] = []
    for event in _MANAGED_EVENTS:
        entries = existing_hooks.get(event)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            matcher = entry.get("matcher")
            # For Notification we conflict on the matchers pm manages.
            if event == "Notification" and matcher not in (
                None, "idle_prompt", "permission_prompt",
            ):
                continue
            if _entry_is_pm(entry):
                continue
            for hook in entry.get("hooks", []) or []:
                cmd = (hook or {}).get("command", "")
                label = f"{event}"
                if matcher:
                    label += f"[{matcher}]"
                foreign.append(f"{label}: {cmd or '(no command)'}")
    return foreign


def _sweep_stale_events() -> None:
    base = _hooks_base()
    if not base.exists():
        return
    now = time.time()
    for p in base.glob("*.json"):
        if not p.is_file():
            continue
        try:
            if now - p.stat().st_mtime > _STALE_SECONDS:
                p.unlink()
        except OSError:
            continue


def hooks_already_installed(settings_path: Path | None = None) -> bool:
    """Return True when ~/.claude/settings.json already has pm's hooks."""
    path = settings_path or _settings_path()
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    desired = _desired_hooks()
    for event in _MANAGED_EVENTS:
        current = hooks.get(event)
        if not isinstance(current, list):
            return False
        # Every desired entry's embedded command must be present — this
        # catches added matchers on upgrade (e.g. new permission_prompt).
        for need in desired[event]:
            want_cmd = need["hooks"][0]["command"]
            found = any(
                h.get("command") == want_cmd
                for e in current
                for h in (e or {}).get("hooks", []) or []
            )
            if not found:
                return False
    return True


def ensure_hooks_installed(settings_path: Path | None = None) -> bool:
    """Install Claude Code hooks for verdict/session-end detection.

    Refuses to overwrite any pre-existing Notification(idle_prompt) or
    Stop hook that pm did not install — raises :class:`HookConflictError`
    in that case so the user can resolve the conflict manually.

    Returns True if the settings file was modified. Idempotent.
    """
    path = settings_path or _settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _log.warning("ensure_hooks_installed: cannot create %s: %s", path.parent, e)
        return False

    existing: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict):
                existing = loaded
        except (json.JSONDecodeError, OSError) as e:
            _log.warning("ensure_hooks_installed: could not parse %s: %s", path, e)
            return False

    current_hooks = existing.get("hooks") if isinstance(existing.get("hooks"), dict) else {}

    # Guard against foreign hooks pm did not install.
    foreign = _detect_foreign_hooks(current_hooks)
    if foreign:
        raise HookConflictError(
            "Refusing to install pm's Claude Code hooks: "
            f"{path} already contains hooks pm did not install:\n  - "
            + "\n  - ".join(foreign)
            + "\nRemove these entries (or migrate them) and re-run pm."
        )

    # Ensure hook dir exists and the standalone receiver is up to date
    # before we reference its path in settings.json.
    try:
        _hooks_base().mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    _install_receiver()
    _sweep_stale_events()

    desired = _desired_hooks()
    # Fast path: our hooks are already present and up to date.
    if hooks_already_installed(path):
        return False

    merged_hooks = dict(current_hooks)
    for event, entries in desired.items():
        merged_hooks[event] = list(entries)

    existing["hooks"] = merged_hooks
    try:
        path.write_text(json.dumps(existing, indent=2) + "\n")
    except OSError as e:
        _log.warning("ensure_hooks_installed: write failed for %s: %s", path, e)
        return False
    _log.info("ensure_hooks_installed: hooks now active for all subsequent Claude turns (%s)", path)
    return True
