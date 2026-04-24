"""Install pm's Claude Code hooks into ~/.claude/settings.json.

Claude Code fires configured hooks on lifecycle events. We install a
Notification(idle_prompt) hook — fires when Claude finishes its turn
and waits at the prompt — and a Stop hook — fires when a response
ends. Both point at ``python -m pm_core.hook_receiver`` which writes
a file under ~/.pm/hooks/ keyed by session_id.

The installer is idempotent and merges into any existing user hooks.
"""

from __future__ import annotations

import json
import shlex
import shutil
import time
from pathlib import Path

from pm_core.paths import configure_logger

_log = configure_logger("pm.hook_install")

_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
_HOOKS_BASE = Path.home() / ".pm" / "hooks"
# Standalone copy of pm_core/hook_receiver.py lives here so it can be
# invoked without pm_core on sys.path (e.g. from inside a QA container
# that bind-mounts this exact host path back into itself).
RECEIVER_PATH = Path.home() / ".pm" / "hook_receiver.py"
_STALE_SECONDS = 7 * 24 * 60 * 60  # 7 days


class HookConflictError(RuntimeError):
    """Raised when ~/.claude/settings.json already has hooks pm did not install."""


def _hook_command_for(event_type: str) -> str:
    """Build the hook command string.

    Runs the standalone receiver at its host absolute path via ``python3``
    (PATH lookup) so the same command string works on the host and inside
    containers that bind-mount the receiver at the same path.
    """
    return f"python3 {shlex.quote(str(RECEIVER_PATH))} {shlex.quote(event_type)}"


def _install_receiver() -> None:
    """Copy pm_core/hook_receiver.py to RECEIVER_PATH.

    The receiver has no pm_core imports so it runs standalone inside
    containers where pm_core is not available.
    """
    from pm_core import hook_receiver as _receiver_mod
    src = Path(_receiver_mod.__file__)
    try:
        RECEIVER_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, RECEIVER_PATH)
        # chmod so `python3 <path>` works even if a filesystem mount would
        # otherwise treat it as non-executable — execution bit not strictly
        # required when invoked as an argument to python3, but harmless.
        RECEIVER_PATH.chmod(0o644)
    except OSError as e:
        _log.warning("could not copy hook receiver to %s: %s", RECEIVER_PATH, e)


_MANAGED_EVENTS = ("Notification", "Stop")


def _desired_hooks() -> dict:
    """Return the hook config we want present in settings.json."""
    return {
        "Notification": [
            {
                "matcher": "idle_prompt",
                "hooks": [
                    {"type": "command", "command": _hook_command_for("idle_prompt")},
                ],
            }
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
    receiver_str = str(RECEIVER_PATH)
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
            # For Notification we only conflict with idle_prompt
            if event == "Notification" and matcher not in (None, "idle_prompt"):
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
    if not _HOOKS_BASE.exists():
        return
    now = time.time()
    for p in _HOOKS_BASE.glob("*.json"):
        if not p.is_file():
            continue
        try:
            if now - p.stat().st_mtime > _STALE_SECONDS:
                p.unlink()
        except OSError:
            continue


def hooks_already_installed(settings_path: Path | None = None) -> bool:
    """Return True when ~/.claude/settings.json already has pm's hooks."""
    path = settings_path or _SETTINGS_PATH
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    desired = _desired_hooks()
    for event in _MANAGED_EVENTS:
        current = hooks.get(event)
        if not isinstance(current, list):
            return False
        need = desired[event]
        # Require at least one pm-owned entry present with our current command
        if not any(_entry_is_pm(e) for e in current):
            return False
        # And the embedded command must match the current interpreter
        want_cmd = need[0]["hooks"][0]["command"]
        found_cmd = False
        for e in current:
            for h in (e or {}).get("hooks", []) or []:
                if h.get("command") == want_cmd:
                    found_cmd = True
                    break
            if found_cmd:
                break
        if not found_cmd:
            return False
    return True


def ensure_hooks_installed(settings_path: Path | None = None) -> bool:
    """Install Claude Code hooks for verdict/session-end detection.

    Refuses to overwrite any pre-existing Notification(idle_prompt) or
    Stop hook that pm did not install — raises :class:`HookConflictError`
    in that case so the user can resolve the conflict manually.

    Returns True if the settings file was modified. Idempotent.
    """
    path = settings_path or _SETTINGS_PATH
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
        _HOOKS_BASE.mkdir(parents=True, exist_ok=True)
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
