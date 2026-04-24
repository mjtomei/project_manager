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
import sys
import time
from pathlib import Path

from pm_core.paths import configure_logger

_log = configure_logger("pm.hook_install")

_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
_HOOKS_DIR = Path.home() / ".pm" / "hooks"
_STALE_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _hook_command_for(event_type: str) -> str:
    """Build the hook command string, embedding the current interpreter."""
    python = shlex.quote(sys.executable or "python3")
    return f"{python} -m pm_core.hook_receiver {shlex.quote(event_type)}"


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


def _entry_has_pm_receiver(entry: dict) -> bool:
    for hook in (entry or {}).get("hooks", []) or []:
        cmd = (hook or {}).get("command", "")
        if "pm_core.hook_receiver" in cmd:
            return True
    return False


def _merge_hooks(existing: dict, desired: dict) -> tuple[dict, bool]:
    """Merge *desired* hooks into *existing*. Returns (merged, changed)."""
    merged = dict(existing)
    changed = False
    for event, new_entries in desired.items():
        current = merged.get(event)
        if not isinstance(current, list):
            merged[event] = list(new_entries)
            changed = True
            continue

        kept = [e for e in current if not _entry_has_pm_receiver(e)]
        new_list = kept + list(new_entries)
        # Compare stringified to detect change (simple but sufficient)
        if json.dumps(new_list, sort_keys=True) != json.dumps(current, sort_keys=True):
            merged[event] = new_list
            changed = True
    return merged, changed


def _sweep_stale_events() -> None:
    if not _HOOKS_DIR.exists():
        return
    now = time.time()
    for p in _HOOKS_DIR.iterdir():
        if not p.is_file():
            continue
        try:
            if now - p.stat().st_mtime > _STALE_SECONDS:
                p.unlink()
        except OSError:
            continue


def ensure_hooks_installed(settings_path: Path | None = None) -> bool:
    """Install Claude Code hooks for verdict/session-end detection.

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
    merged_hooks, changed = _merge_hooks(current_hooks, _desired_hooks())

    # Ensure hook dir exists regardless
    try:
        _HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    _sweep_stale_events()

    if not changed:
        return False

    existing["hooks"] = merged_hooks
    try:
        path.write_text(json.dumps(existing, indent=2) + "\n")
    except OSError as e:
        _log.warning("ensure_hooks_installed: write failed for %s: %s", path, e)
        return False
    _log.info("ensure_hooks_installed: hooks now active for all subsequent Claude turns (%s)", path)
    return True
