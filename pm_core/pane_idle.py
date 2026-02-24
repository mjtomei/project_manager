"""Shared pane idle detection for the TUI.

Tracks tmux panes and detects when their visible content stops changing,
indicating that Claude (or whatever process is running) has gone idle.

Thread-safe: the review loop runs in a background thread, while the TUI
poll timer runs on the main thread.
"""

import hashlib
import threading
import time
from dataclasses import dataclass, field

from pm_core import tmux as tmux_mod
from pm_core.paths import configure_logger

_log = configure_logger("pm.pane_idle")

# How long (seconds) content must be unchanged before we consider the pane idle.
DEFAULT_IDLE_THRESHOLD = 30.0


@dataclass
class PaneIdleState:
    """Per-pane idle tracking state."""

    pane_id: str
    last_content_hash: str = ""
    last_change_time: float = field(default_factory=time.monotonic)
    idle: bool = False
    gone: bool = False
    idle_notified: bool = False  # True once caller has been told about idle transition


class PaneIdleTracker:
    """Track multiple panes for idle detection.

    Keys are arbitrary strings (typically pr_id).
    """

    def __init__(self, idle_threshold: float = DEFAULT_IDLE_THRESHOLD) -> None:
        self._states: dict[str, PaneIdleState] = {}
        self._lock = threading.Lock()
        self._idle_threshold = idle_threshold

    # -- Registration --

    def register(self, key: str, pane_id: str) -> None:
        """Start tracking a pane.  Resets state if the pane_id changed."""
        with self._lock:
            existing = self._states.get(key)
            if existing and existing.pane_id == pane_id and not existing.gone:
                return  # already tracking this exact pane
            self._states[key] = PaneIdleState(pane_id=pane_id)

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

        # Subprocess calls outside lock
        if not tmux_mod.pane_exists(pane_id):
            with self._lock:
                state = self._states.get(key)
                if state and state.pane_id == pane_id:
                    state.gone = True
                    state.idle = False
            return False

        content = tmux_mod.capture_pane(pane_id)
        content_hash = hashlib.md5(content.encode()).hexdigest()
        now = time.monotonic()

        # Update state under lock
        with self._lock:
            state = self._states.get(key)
            if not state or state.pane_id != pane_id:
                return False  # re-registered while we were polling

            state.gone = False
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
