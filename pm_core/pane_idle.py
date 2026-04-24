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
from dataclasses import dataclass, field

from pm_core import tmux as tmux_mod
from pm_core.claude_launcher import session_id_from_transcript
from pm_core.paths import configure_logger

_log = configure_logger("pm.pane_idle")


@dataclass
class PaneIdleState:
    """Per-pane idle tracking state (hook-event driven)."""

    pane_id: str
    transcript_path: str
    session_id: str
    last_hook_ts: float = 0.0
    last_content: str = ""  # captured on idle transition so callers can render
    idle: bool = False
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

    def unregister(self, key: str) -> None:
        with self._lock:
            self._states.pop(key, None)

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
                elif etype == "Stop":
                    # Stop alone is ambiguous (fires per-turn, not only
                    # at session end), so we don't flip state on it —
                    # idle_prompt is authoritative.  If the pane is
                    # actually gone, ``pane_exists`` will flag it above.
                    pass
            return state.idle

    # -- Pure reads --

    def is_idle(self, key: str) -> bool:
        with self._lock:
            state = self._states.get(key)
            return state.idle if state else False

    def get_content(self, key: str) -> str:
        """Return the cached transcript-derived content (empty by default).

        Kept for API compatibility with the previous hash-based tracker;
        callers that need the assistant's text should read the
        transcript directly via
        :func:`pm_core.verdict_transcript.read_latest_assistant_text`.
        """
        with self._lock:
            state = self._states.get(key)
            return state.last_content if state else ""

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
                state.gone = False
                state.idle_notified = False
                state.last_hook_ts = time.time()
