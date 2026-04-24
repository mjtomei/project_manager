"""Shared pane idle detection for the TUI.

Tracks tmux panes and detects when their visible content stops changing,
indicating that Claude (or whatever process is running) has gone idle.

Thread-safe: the review loop runs in a background thread, while the TUI
poll timer runs on the main thread.
"""

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field

from pm_core import tmux as tmux_mod
from pm_core.paths import configure_logger

_log = configure_logger("pm.pane_idle")

# How long (seconds) content must be unchanged before we consider the pane idle.
DEFAULT_IDLE_THRESHOLD = 30.0

# Gum-style selection UIs show a list of options, one marked with ❯.
# The other options are indented to the same level but without ❯.
# We detect this by looking for a ❯ line with sibling option lines
# above or below it at the same indent level — distinguishing it from
# Claude Code's single input cursor (❯ with a proposed message).
_GUM_SELECTOR_RE = re.compile(r"^\s*❯\s+\S", re.MULTILINE)
_GUM_OPTION_RE = re.compile(r"^\s{2,}\S", re.MULTILINE)


def content_has_interactive_prompt(content: str) -> bool:
    """Return True if pane content shows a Claude interactive selection screen.

    Detects gum-style selection UIs (trust prompt, permission prompt, etc.)
    where Claude is waiting for user input rather than being genuinely idle.

    A gum selection menu has a ❯ on the selected option with other options
    on adjacent lines at similar indentation.  A bare Claude input cursor
    (❯ with a proposed message) does NOT have neighbouring option lines,
    so it won't match.
    """
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if not _GUM_SELECTOR_RE.match(line):
            continue
        # Check if there's at least one sibling option line adjacent
        above = lines[i - 1] if i > 0 else ""
        below = lines[i + 1] if i < len(lines) - 1 else ""
        if _GUM_OPTION_RE.match(above) or _GUM_OPTION_RE.match(below):
            return True
    return False


@dataclass
class PaneIdleState:
    """Per-pane idle tracking state."""

    pane_id: str
    last_content_hash: str = ""
    last_content: str = ""  # raw content for inspection by callers
    last_change_time: float = field(default_factory=time.monotonic)
    idle: bool = False
    gone: bool = False
    idle_notified: bool = False  # True once caller has been told about idle transition
    # Hook-driven idle detection: when session_id is known we can short-
    # circuit hash comparison with the idle_prompt hook event written by
    # pm_core.hook_receiver.
    session_id: str | None = None
    last_hook_ts: float = 0.0


class PaneIdleTracker:
    """Track multiple panes for idle detection.

    Keys are arbitrary strings (typically pr_id).
    """

    def __init__(self, idle_threshold: float = DEFAULT_IDLE_THRESHOLD) -> None:
        self._states: dict[str, PaneIdleState] = {}
        self._lock = threading.Lock()
        self._idle_threshold = idle_threshold

    # -- Registration --

    def register(self, key: str, pane_id: str,
                 session_id: str | None = None) -> None:
        """Start tracking a pane.  Resets state if the pane_id changed."""
        with self._lock:
            existing = self._states.get(key)
            if existing and existing.pane_id == pane_id and not existing.gone:
                # Late-arriving session_id for an already-tracked pane: record it.
                if session_id and not existing.session_id:
                    existing.session_id = session_id
                return  # already tracking this exact pane
            self._states[key] = PaneIdleState(
                pane_id=pane_id, session_id=session_id,
            )

    def unregister(self, key: str) -> None:
        """Stop tracking a pane."""
        with self._lock:
            self._states.pop(key, None)

    # -- Polling (called from timer, does subprocess work) --

    def poll(self, key: str) -> bool:
        """Capture pane content, update idle state, return *is_idle*.

        Performs one ``capture_pane`` + one ``pane_exists`` call per
        invocation.  The subprocess calls run *outside* the lock.

        Returns True if idle, False otherwise (including if key is unknown).
        """
        # Read state under lock
        with self._lock:
            state = self._states.get(key)
            if not state:
                return False
            pane_id = state.pane_id
            session_id = state.session_id
            last_hook_ts = state.last_hook_ts

        # Subprocess calls outside lock
        if not tmux_mod.pane_exists(pane_id):
            with self._lock:
                state = self._states.get(key)
                if state and state.pane_id == pane_id:
                    state.gone = True
                    state.idle = False
            return False

        # Hook-driven fast path: if session_id is known and an idle_prompt
        # event has been written for this session, mark idle immediately.
        hook_event = None
        if session_id:
            try:
                from pm_core import hook_events
                hook_event = hook_events.read_event(session_id)
            except Exception:
                hook_event = None

        content = tmux_mod.capture_pane(pane_id)
        content_hash = hashlib.md5(content.encode()).hexdigest()
        now = time.monotonic()

        # Update state under lock
        with self._lock:
            state = self._states.get(key)
            if not state or state.pane_id != pane_id:
                return False  # re-registered while we were polling

            state.gone = False
            state.last_content = content

            # Consume fresh hook events (idle_prompt / Stop) if present.
            if hook_event:
                ev_ts = float(hook_event.get("timestamp") or 0)
                if ev_ts > state.last_hook_ts:
                    state.last_hook_ts = ev_ts
                    etype = hook_event.get("event_type")
                    if etype == "idle_prompt":
                        state.last_content_hash = content_hash
                        state.last_change_time = now
                        state.idle = True
                        return state.idle
                    if etype == "Stop":
                        state.gone = True
                        state.idle = False
                        return False

            if content_hash != state.last_content_hash:
                state.last_content_hash = content_hash
                state.last_change_time = now
                state.idle = False
                state.idle_notified = False
            elif now - state.last_change_time >= self._idle_threshold:
                state.idle = True

            return state.idle

    # -- Pure reads (safe from render path, zero cost) --

    def is_idle(self, key: str) -> bool:
        """Return cached idle state.  Zero-cost read, no subprocess calls."""
        with self._lock:
            state = self._states.get(key)
            return state.idle if state else False

    def get_content(self, key: str) -> str:
        """Return last captured pane content.  Zero-cost read."""
        with self._lock:
            state = self._states.get(key)
            return state.last_content if state else ""

    def became_idle(self, key: str) -> bool:
        """Return True once when a pane first transitions to idle.

        Subsequent calls return False until the pane becomes active and
        then idle again.  Used to trigger one-shot actions (e.g. auto-
        starting a review loop).
        """
        with self._lock:
            state = self._states.get(key)
            if state and state.idle and not state.idle_notified:
                state.idle_notified = True
                return True
            return False

    def is_gone(self, key: str) -> bool:
        """Return True if the pane has disappeared."""
        with self._lock:
            state = self._states.get(key)
            return state.gone if state else False

    def is_tracked(self, key: str) -> bool:
        """Return True if the key is being tracked."""
        with self._lock:
            return key in self._states

    def tracked_keys(self) -> list[str]:
        """Return a snapshot of all tracked keys."""
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
                state.last_change_time = time.monotonic()
