"""WatcherManager: single orchestrator for all registered watchers.

Manages the lifecycle of watcher instances, provides a unified view
of all watcher states for the TUI, and deduplicates user notifications.
"""

import threading
from typing import Callable

from pm_core.paths import configure_logger
from pm_core.watcher_base import BaseWatcher, WatcherState

_log = configure_logger("pm.watcher_manager")


class WatcherManager:
    """Manages all registered watchers.

    Thread-safe: all access to internal dicts is guarded by a lock since
    watchers run in background threads while the TUI polls from the main
    thread.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._watchers: dict[str, BaseWatcher] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._on_iteration_callbacks: dict[str, Callable] = {}
        self._on_complete_callbacks: dict[str, Callable] = {}

    def register(self, watcher: BaseWatcher) -> None:
        """Register a watcher instance."""
        with self._lock:
            wid = watcher.state.watcher_id
            if wid in self._watchers:
                _log.warning("watcher_manager: replacing existing watcher %s", wid)
            self._watchers[wid] = watcher
            _log.info("watcher_manager: registered %s (%s)",
                      wid, watcher.WATCHER_TYPE)

    def unregister(self, watcher_id: str) -> None:
        """Unregister a watcher (stops it first if running)."""
        with self._lock:
            watcher = self._watchers.get(watcher_id)
            if not watcher:
                return
            if watcher.state.running:
                watcher.state.stop_requested = True
            self._watchers.pop(watcher_id, None)
            self._threads.pop(watcher_id, None)
            _log.info("watcher_manager: unregistered %s", watcher_id)

    def start(
        self,
        watcher_id: str,
        on_iteration: Callable[[WatcherState], None] | None = None,
        on_complete: Callable[[WatcherState], None] | None = None,
        transcript_dir: str | None = None,
    ) -> bool:
        """Start a registered watcher. Returns True if started."""
        with self._lock:
            watcher = self._watchers.get(watcher_id)
            if not watcher:
                _log.warning("watcher_manager: cannot start unknown watcher %s",
                             watcher_id)
                return False
            if watcher.state.running:
                _log.info("watcher_manager: %s already running", watcher_id)
                return False

            def _on_complete_wrapper(state: WatcherState) -> None:
                if on_complete:
                    on_complete(state)

            # Set running eagerly so rapid toggle doesn't create duplicates
            watcher.state.running = True

            thread = watcher.start_background(
                on_iteration=on_iteration,
                on_complete=_on_complete_wrapper,
                transcript_dir=transcript_dir,
            )
            self._threads[watcher_id] = thread
            _log.info("watcher_manager: started %s", watcher_id)
            return True

    def stop(self, watcher_id: str) -> bool:
        """Request graceful stop for a watcher. Returns True if stop requested."""
        with self._lock:
            watcher = self._watchers.get(watcher_id)
            if not watcher or not watcher.state.running:
                return False
            watcher.state.stop_requested = True
            _log.info("watcher_manager: stop requested for %s", watcher_id)
            return True

    def stop_all(self) -> None:
        """Request graceful stop for all running watchers."""
        with self._lock:
            for watcher in self._watchers.values():
                if watcher.state.running:
                    watcher.state.stop_requested = True
            _log.info("watcher_manager: stop_all requested")

    def get_watcher(self, watcher_id: str) -> BaseWatcher | None:
        """Get a watcher instance by ID."""
        with self._lock:
            return self._watchers.get(watcher_id)

    def get_state(self, watcher_id: str) -> WatcherState | None:
        """Get a watcher's state by ID."""
        with self._lock:
            watcher = self._watchers.get(watcher_id)
            return watcher.state if watcher else None

    def find_by_type(self, watcher_type: str) -> BaseWatcher | None:
        """Find the first watcher with the given type."""
        with self._lock:
            for watcher in self._watchers.values():
                if watcher.WATCHER_TYPE == watcher_type:
                    return watcher
            return None

    def find_state_by_type(self, watcher_type: str) -> WatcherState | None:
        """Find the first watcher state with the given type."""
        watcher = self.find_by_type(watcher_type)
        return watcher.state if watcher else None

    def list_watchers(self) -> list[dict]:
        """Return a list of watcher status dicts for display.

        Each dict contains: id, type, display_name, running, verdict,
        iteration, input_required, window_name.
        """
        with self._lock:
            result = []
            for wid, watcher in self._watchers.items():
                s = watcher.state
                result.append({
                    "id": wid,
                    "type": watcher.WATCHER_TYPE,
                    "display_name": watcher.DISPLAY_NAME,
                    "running": s.running,
                    "verdict": s.latest_verdict,
                    "iteration": s.iteration,
                    "input_required": s.input_required,
                    "window_name": watcher.WINDOW_NAME,
                })
            return result

    def is_any_running(self) -> bool:
        """Check if any watcher is currently running."""
        with self._lock:
            return any(w.state.running for w in self._watchers.values())

    def any_input_required(self) -> bool:
        """Check if any running watcher needs user input."""
        with self._lock:
            return any(
                w.state.running and w.state.input_required
                for w in self._watchers.values()
            )

