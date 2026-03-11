"""Watcher loop: compatibility wrapper around the new watcher framework.

This module preserves the public API that ``cli/watcher.py``,
``tui/watcher_ui.py``, and ``tui/auto_start.py`` depend on while
delegating to the ``BaseWatcher`` / ``WatcherManager`` framework
under the hood.

Public API preserved:
  - ``WatcherLoopState`` (dataclass)
  - ``WatcherIteration`` (dataclass)
  - ``WATCHER_WINDOW_NAME``
  - ``VERDICT_READY``, ``VERDICT_INPUT_REQUIRED``, ``VERDICT_KILLED``
  - ``ALL_WATCHER_VERDICTS``
  - ``DEFAULT_ITERATION_WAIT``
  - ``PaneKilledError``
  - ``parse_watcher_verdict(output) -> str``
  - ``run_watcher_loop_sync(state, pm_root, ...) -> WatcherLoopState``
  - ``start_watcher_loop_background(state, pm_root, ...) -> Thread``
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from pm_core.paths import configure_logger
from pm_core.watcher_base import (
    WatcherIteration,
    WatcherState,
    PaneKilledError,
    _generate_loop_id,
)
from pm_core.watchers.auto_start_watcher import AutoStartWatcher

_log = configure_logger("pm.watcher_loop")

# --- Public constants (unchanged) ---

VERDICT_READY = "READY"
VERDICT_INPUT_REQUIRED = "INPUT_REQUIRED"
VERDICT_KILLED = "KILLED"

ALL_WATCHER_VERDICTS = (VERDICT_READY, VERDICT_INPUT_REQUIRED)

DEFAULT_ITERATION_WAIT = 120

WATCHER_WINDOW_NAME = "watcher"

# Re-export for consumers
__all__ = [
    "WatcherLoopState", "WatcherIteration", "PaneKilledError",
    "WATCHER_WINDOW_NAME", "VERDICT_READY", "VERDICT_INPUT_REQUIRED",
    "VERDICT_KILLED", "ALL_WATCHER_VERDICTS", "DEFAULT_ITERATION_WAIT",
    "parse_watcher_verdict", "run_watcher_loop_sync",
    "start_watcher_loop_background",
]


@dataclass
class WatcherLoopState:
    """Legacy state dataclass preserved for backwards compatibility.

    The watcher framework internally uses ``WatcherState`` but this
    class keeps the same public fields that existing code expects.
    """
    running: bool = False
    stop_requested: bool = False
    iteration: int = 0
    latest_verdict: str = ""
    latest_summary: str = ""
    history: list[WatcherIteration] = field(default_factory=list)
    loop_id: str = field(default_factory=_generate_loop_id)
    iteration_wait: float = DEFAULT_ITERATION_WAIT
    _ui_notified_done: bool = False
    _ui_notified_input: bool = False
    input_required: bool = False
    _transcript_dir: str | None = None
    auto_start_target: str | None = None
    meta_pm_root: str | None = None


def _sync_state_to_legacy(ws: WatcherState, ls: WatcherLoopState) -> None:
    """Copy WatcherState fields into the legacy WatcherLoopState."""
    ls.running = ws.running
    ls.stop_requested = ws.stop_requested
    ls.iteration = ws.iteration
    ls.latest_verdict = ws.latest_verdict
    ls.latest_summary = ws.latest_summary
    ls.history = ws.history
    ls.input_required = ws.input_required
    ls._transcript_dir = ws._transcript_dir



def parse_watcher_verdict(output: str) -> str:
    """Extract a watcher verdict from Claude output."""
    from pm_core.loop_shared import match_verdict
    lines = output.strip().splitlines()
    for line in reversed(lines):
        stripped = line.strip().strip("*").strip()
        verdict = match_verdict(stripped, ALL_WATCHER_VERDICTS)
        if verdict:
            return verdict
    return VERDICT_READY


def run_watcher_loop_sync(
    state: WatcherLoopState,
    pm_root: str,
    on_iteration: Callable[[WatcherLoopState], None] | None = None,
    max_iterations: int = 0,
    transcript_dir: str | None = None,
) -> WatcherLoopState:
    """Run the watcher loop synchronously.

    Delegates to ``AutoStartWatcher.run_sync()`` while keeping the
    ``WatcherLoopState`` interface for callers.
    """
    watcher = AutoStartWatcher(
        pm_root=pm_root,
        auto_start_target=state.auto_start_target,
        meta_pm_root=state.meta_pm_root,
    )
    # Transfer loop_id and iteration_wait from legacy state
    watcher.state.loop_id = state.loop_id
    watcher.state.iteration_wait = state.iteration_wait

    # Wrap on_iteration to sync state back to legacy object
    def _on_iter(ws: WatcherState) -> None:
        _sync_state_to_legacy(ws, state)
        if on_iteration:
            on_iteration(state)

    # Forward legacy stop_requested into watcher state
    watcher.state.stop_requested = state.stop_requested

    # Run synchronously — the AutoStartWatcher.run_sync handles everything
    watcher.run_sync(
        on_iteration=_on_iter,
        max_iterations=max_iterations,
        transcript_dir=transcript_dir,
    )

    # Final sync
    _sync_state_to_legacy(watcher.state, state)
    return state


def start_watcher_loop_background(
    state: WatcherLoopState,
    pm_root: str,
    on_iteration: Callable[[WatcherLoopState], None] | None = None,
    on_complete: Callable[[WatcherLoopState], None] | None = None,
    max_iterations: int = 0,
    transcript_dir: str | None = None,
) -> threading.Thread:
    """Start the watcher loop in a background thread.

    Delegates to ``AutoStartWatcher.start_background()`` while keeping
    the ``WatcherLoopState`` interface.
    """
    watcher = AutoStartWatcher(
        pm_root=pm_root,
        auto_start_target=state.auto_start_target,
        meta_pm_root=state.meta_pm_root,
    )
    watcher.state.loop_id = state.loop_id
    watcher.state.iteration_wait = state.iteration_wait

    def _on_iter(ws: WatcherState) -> None:
        _sync_state_to_legacy(ws, state)
        if on_iteration:
            on_iteration(state)

    # Link stop_requested: when legacy state is stopped, watcher should stop
    def _run():
        # Periodically check if legacy stop_requested has been set
        import time

        def _check_stop():
            # Wait for run_sync to set running=True before polling
            for _ in range(30):
                if watcher.state.running or state.stop_requested:
                    break
                time.sleep(0.1)
            # Propagate early stop if set before running started
            if state.stop_requested:
                watcher.state.stop_requested = True
                return
            # Propagate legacy stop_requested while watcher is alive
            while watcher.state.running:
                if state.stop_requested:
                    watcher.state.stop_requested = True
                    break
                time.sleep(1)

        import threading as _threading
        stopper = _threading.Thread(target=_check_stop, daemon=True,
                                     name="watcher-stop-bridge")
        stopper.start()

        watcher.run_sync(
            on_iteration=_on_iter,
            max_iterations=max_iterations,
            transcript_dir=transcript_dir,
        )
        _sync_state_to_legacy(watcher.state, state)
        if on_complete:
            try:
                on_complete(state)
            except Exception:
                _log.exception("watcher_loop: on_complete callback failed")

    thread = threading.Thread(target=_run, daemon=True, name="watcher-loop")
    thread.start()

    # Mark state as running immediately (thread is started)
    state.running = True

    return thread
