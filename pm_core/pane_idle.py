"""Pane idle detection backed entirely by Claude Code hook events.

Tracks tmux panes that are running a Claude session; "idle" means the
session has emitted an ``idle_prompt`` hook event (i.e. Claude's turn
is over and it is waiting for the next user message).  The TUI polls
this tracker on its timer; pane liveness is verified via
``tmux.pane_exists`` but the *content* is never scraped.

Every ``register`` caller must supply a ``transcript_path`` — either a
symlink created by ``build_claude_shell_cmd(transcript=...)`` or a
direct path computed via
``claude_launcher.transcript_path_for(cwd, session_id)``.  The
session_id is recovered from that path so callers don't have to thread
the UUID through subprocess boundaries.

Thread-safe: the review loop runs in a background thread while the
TUI poll timer runs on the main thread.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from pm_core import tmux as tmux_mod
from pm_core.claude_launcher import session_id_from_transcript
from pm_core.paths import configure_logger

_log = configure_logger("pm.pane_idle")


@dataclass
class PaneIdleState:
    """Per-pane state derived from Claude Code hook events.

    Three orthogonal flags:

    * ``idle`` — the agent emitted ``idle_prompt`` (turn ended, waiting
      for the next user message).
    * ``waiting_for_input`` — the agent emitted ``permission_prompt``
      (Claude Code is showing its own tool-approval dialog and is
      blocked until the user responds).  This is a distinct "the user
      needs to do something *right now*" state that the TUI renders
      differently from plain idle.
    * ``gone`` — the tmux pane disappeared (session exited / crashed).

    ``idle`` and ``waiting_for_input`` are mutually exclusive: the
    latest hook event wins.  Subprocess-level prompts (gum, fzf, git
    rebase -i) do not fire any hook and therefore don't flip either
    flag — they're only visible in the pane content.
    """

    pane_id: str
    transcript_path: str
    session_id: str
    last_hook_ts: float = 0.0
    idle: bool = False
    waiting_for_input: bool = False
    gone: bool = False
    idle_notified: bool = False


class PaneIdleTracker:
    """Track multiple panes for hook-driven idle detection.

    Keys are arbitrary strings (typically pr_id).
    """

    def __init__(self) -> None:
        self._states: dict[str, PaneIdleState] = {}
        self._lock = threading.Lock()

    # -- Registration --

    def register(self, key: str, pane_id: str,
                 transcript_path: str) -> None:
        """Start tracking a pane.

        *transcript_path* must resolve to a Claude session_id (either a
        pm-generated symlink or a direct JSONL path with a UUID name).
        Raises ValueError when no session_id can be recovered — callers
        that don't have one should not register a pane here.
        """
        session_id = session_id_from_transcript(transcript_path)
        if not session_id:
            raise ValueError(
                f"PaneIdleTracker.register: no session_id recoverable "
                f"from transcript_path={transcript_path!r}"
            )
        with self._lock:
            existing = self._states.get(key)
            if (existing and existing.pane_id == pane_id and not existing.gone
                    and existing.session_id == session_id):
                return
            self._states[key] = PaneIdleState(
                pane_id=pane_id,
                transcript_path=str(transcript_path),
                session_id=session_id,
            )
        _runtime_mirror_register(key, pane_id, session_id)

    def unregister(self, key: str) -> None:
        with self._lock:
            self._states.pop(key, None)
        _runtime_mirror_clear(key)

    # -- Polling (called from timer) --

    def poll(self, key: str) -> bool:
        """Check hook events + pane liveness.  Returns *is_idle*."""
        from pm_core import hook_events

        with self._lock:
            state = self._states.get(key)
            if not state:
                return False
            pane_id = state.pane_id
            session_id = state.session_id
            last_hook_ts = state.last_hook_ts

        if not tmux_mod.pane_exists(pane_id):
            with self._lock:
                state = self._states.get(key)
                if state and state.pane_id == pane_id:
                    state.gone = True
                    state.idle = False
            _runtime_mirror_clear(key)
            return False

        event = hook_events.read_event(session_id)
        if not event:
            with self._lock:
                state = self._states.get(key)
                return bool(state and state.idle)

        ev_ts = float(event.get("timestamp") or 0)
        with self._lock:
            state = self._states.get(key)
            if not state or state.pane_id != pane_id:
                return False
            state.gone = False
            if ev_ts > state.last_hook_ts:
                state.last_hook_ts = ev_ts
                etype = event.get("event_type")
                if etype == "idle_prompt":
                    if not state.idle:
                        state.idle_notified = False
                    state.idle = True
                    state.waiting_for_input = False
                elif etype == "permission_prompt":
                    # Agent is blocked on Claude Code's tool-approval
                    # dialog.  Flag as waiting for input and clear the
                    # idle flag so the TUI renders a distinct indicator.
                    state.waiting_for_input = True
                    state.idle = False
                    state.idle_notified = False
                elif etype == "Stop":
                    # Stop fires per-turn (not only at session end), so
                    # we don't flip state on it.  pane_exists is the
                    # authoritative session-gone signal.
                    pass
            return state.idle

    # -- Pure reads --

    def is_idle(self, key: str) -> bool:
        with self._lock:
            state = self._states.get(key)
            return state.idle if state else False

    def is_waiting_for_input(self, key: str) -> bool:
        """Return True when the agent is blocked on Claude's permission dialog.

        Distinct from :meth:`is_idle` — ``is_idle`` means "turn done,
        waiting for next user prompt"; ``is_waiting_for_input`` means
        "turn in progress but blocked on a tool-approval decision".
        TUI renderers should surface this as a separate indicator so
        users know to respond in the pane.
        """
        with self._lock:
            state = self._states.get(key)
            return state.waiting_for_input if state else False

    def get_transcript_path(self, key: str) -> str | None:
        """Return the transcript path registered for *key*, or None.

        Callers can use this to read the JSONL directly
        (e.g. :func:`pm_core.verdict_transcript.extract_verdict_from_transcript`)
        without reaching into the tracker's internal state map.
        """
        with self._lock:
            state = self._states.get(key)
            return state.transcript_path if state else None

    def became_idle(self, key: str) -> bool:
        with self._lock:
            state = self._states.get(key)
            if state and state.idle and not state.idle_notified:
                state.idle_notified = True
                return True
            return False

    def is_gone(self, key: str) -> bool:
        with self._lock:
            state = self._states.get(key)
            return state.gone if state else False

    def is_tracked(self, key: str) -> bool:
        with self._lock:
            return key in self._states

    def tracked_keys(self) -> list[str]:
        with self._lock:
            return list(self._states.keys())

    def mark_active(self, key: str) -> None:
        """Force-reset to active (e.g. when new work starts)."""
        with self._lock:
            state = self._states.get(key)
            if state:
                state.idle = False
                state.waiting_for_input = False
                state.gone = False
                state.idle_notified = False
                state.last_hook_ts = time.time()


# ---------------------------------------------------------------------------
# runtime_state mirror
# ---------------------------------------------------------------------------

# Tracker key conventions:
# * bare ``pr_id`` (e.g. ``pr-2d0588a``) — implementation pane
#   (picker's ``start`` action).
# * ``qa:<pr_id>:s<N>`` — QA scenario pane (set by
#   :mod:`pm_core.tui.qa_loop_ui`).  Mirrored as the picker's ``qa`` action.
# * ``merge:<pr_id>`` — merge resolution window; not mirrored (the
#   picker has no per-merge runtime state to display).
# External readers (popup picker, status spinner) want to know which
# PR/action a pane belongs to so they can resolve idle/working via
# :func:`hook_events.read_event`.

def _runtime_target(key: str) -> tuple[str, str] | None:
    """Map a tracker key to (pr_id, action), or None when unknown."""
    if key.startswith("qa:"):
        rest = key[3:]
        pr_part = rest.split(":s", 1)[0]
        return pr_part, "qa"
    if key.startswith("pr-") or key.startswith("#"):
        return key, "start"
    return None


def _runtime_mirror_register(key: str, pane_id: str, session_id: str) -> None:
    target = _runtime_target(key)
    if not target:
        return
    pr_id, action = target
    try:
        from pm_core import runtime_state as _rs
        _rs.set_action_state(pr_id, action, "running",
                             pane_id=pane_id, session_id=session_id)
    except Exception:
        _log.debug("runtime_state mirror_register failed for %s", key,
                   exc_info=True)


def _runtime_mirror_clear(key: str) -> None:
    target = _runtime_target(key)
    if not target:
        return
    pr_id, action = target
    try:
        from pm_core import runtime_state as _rs
        _rs.clear_action(pr_id, action)
    except Exception:
        _log.debug("runtime_state mirror_clear failed for %s", key,
                   exc_info=True)


