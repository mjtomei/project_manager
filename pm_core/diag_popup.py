"""Window-attached persistent Claude popup.

Each tmux window can have a long-lived host-side Claude session in a
separate detached tmux session named ``pm-diag-<base>-<window_short>``.
The popup binding (prefix /) attaches to that session via
``tmux display-popup -E``; dismissing the popup detaches the popup's
client without killing the diag session, so the next press resurfaces
the same conversation.

State is recorded at ``~/.pm/sessions/<tag>/diag-panes.json`` mapping
``window-id`` → ``{"name": "<diag-session-name>"}``. tmux is the source
of truth for whether a session is alive; the file is informational and
used for cleanup on window-close.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pm_core import pane_registry
from pm_core import tmux as tmux_mod
from pm_core.paths import configure_logger, session_dir

_log = configure_logger("pm.diag_popup")


def _state_path(tag: str) -> Path | None:
    sd = session_dir(tag)
    if sd is None:
        return None
    return sd / "diag-panes.json"


def _load_state(tag: str) -> dict:
    p = _state_path(tag)
    if p is None or not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(tag: str, state: dict) -> None:
    p = _state_path(tag)
    if p is None:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2) + "\n")


def diag_session_name(base_session: str, window_id: str) -> str:
    """Compute the diag tmux session name for a (pm-session, window-id) pair.

    ``window_id`` is the tmux ``#{window_id}`` (e.g. ``@7``) — stable for
    the lifetime of the window. We strip the leading ``@`` to keep the
    session name tmux-friendly.
    """
    base = pane_registry.base_session_name(base_session)
    short = window_id.lstrip("@")
    return f"{base}-diag-{short}"


def session_tag_from_pm_session(session: str) -> str | None:
    """Recover the pm session tag from a tmux session name.

    pm sessions are named ``pm-<tag>``. Returns None if the session name
    doesn't match that pattern (e.g. user-named sessions).
    """
    base = pane_registry.base_session_name(session)
    if base.startswith("pm-"):
        return base[3:]
    return None


def record_diag_session(tag: str, window_id: str, name: str) -> None:
    """Record that a diag session exists for *window_id*."""
    state = _load_state(tag)
    state[window_id] = {"name": name}
    _save_state(tag, state)
    _log.info("recorded diag session: tag=%s window=%s name=%s",
              tag, window_id, name)


def forget_diag_session(tag: str, window_id: str) -> str | None:
    """Drop *window_id* from the state map; return the recorded name (if any)."""
    state = _load_state(tag)
    entry = state.pop(window_id, None)
    _save_state(tag, state)
    if entry:
        _log.info("forgot diag session: tag=%s window=%s name=%s",
                  tag, window_id, entry.get("name"))
        return entry.get("name")
    return None


def resolve_host_cwd(tag: str | None) -> str:
    """Pick a sensible host cwd for the diag Claude session.

    Prefers the session's persisted pm_root (the host's project dir),
    falls back to ``$HOME``. Used to avoid launching the host-side
    session in a container-internal path that doesn't exist on the host.
    """
    if tag:
        from pm_core.paths import get_session_pm_root
        root = get_session_pm_root(tag)
        if root and root.exists():
            return str(root)
    return os.environ.get("HOME") or "/"


def build_diag_prompt(pm_session: str, window_id: str) -> str:
    """Build the system prompt for the diag Claude session."""
    from pm_core.prompt_gen import tui_section
    return f"""\
## Window-attached diagnostic Claude session

You are running **outside any container** with full host access — \
host filesystem, host tmux, and any binaries the user has on PATH.

This session is attached to pm tmux session `{pm_session}`, window \
`{window_id}`. It is summoned as a tmux popup via `prefix /` and \
dismissed with Esc; the conversation persists across dismissals \
because this tmux session keeps running in the background.

Use this session for ad-hoc diagnostics that need host-level access:
- Inspect tmux state (`tmux list-sessions`, `tmux list-panes`).
- Read files outside the workdir bind-mount.
- Run host commands that aren't available inside pm's containerized \
panes.

{tui_section(pm_session)}

The user will tell you what they need."""


def ensure_diag_session(pm_session: str, window_id: str) -> str:
    """Ensure a diag tmux session exists for (pm_session, window_id).

    Returns the diag session name. Creates the session running Claude if
    it doesn't already exist; otherwise returns the existing name.
    """
    name = diag_session_name(pm_session, window_id)
    if tmux_mod.session_exists(name):
        _log.info("diag session already exists: %s", name)
        return name

    from pm_core.claude_launcher import find_claude, build_claude_shell_cmd

    tag = session_tag_from_pm_session(pm_session)
    cwd = resolve_host_cwd(tag)

    claude = find_claude()
    if not claude:
        # Fall back to a session that displays a clear error so the user
        # knows what went wrong when the popup attaches.
        cmd = ("echo 'Claude CLI not found on the host. Install claude or"
               " add it to PATH, then retry.'; "
               "read -n 1 -s -r -p 'Press any key to close...'")
    else:
        prompt = build_diag_prompt(pm_session, window_id)
        cmd = build_claude_shell_cmd(
            prompt=prompt,
            session_tag=tag,
            cwd=cwd,
        )

    tmux_mod.create_session(name, cwd, cmd)
    _log.info("created diag session: %s (cwd=%s)", name, cwd)

    if tag:
        record_diag_session(tag, window_id, name)
    return name


def kill_diag_session_for_window(pm_session: str, window_id: str) -> None:
    """Kill the diag session bound to (pm_session, window_id), if any.

    Called by the ``window-unlinked`` tmux hook so closing a pm window
    terminates its diag session and cleans up the state map. Idempotent.
    """
    tag = session_tag_from_pm_session(pm_session)
    name = diag_session_name(pm_session, window_id)
    if tmux_mod.session_exists(name):
        try:
            tmux_mod.kill_session(name)
            _log.info("killed diag session %s", name)
        except Exception:
            _log.exception("failed killing diag session %s", name)
    if tag:
        forget_diag_session(tag, window_id)
