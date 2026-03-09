"""Base watcher framework: abstract class and shared state for all watchers.

Every watcher in the system inherits from ``BaseWatcher``, which provides:

- A shared polling loop with configurable interval
- Common tmux pane management (creating/reusing watcher panes, capturing output)
- State persistence (iterations, verdicts, history)
- User interaction mechanisms (INPUT_REQUIRED escalation)
- Shared verdict/action vocabulary

Each concrete watcher implements domain-specific logic via four methods:

- ``generate_prompt(iteration)`` — produce the Claude prompt for this iteration
- ``build_launch_cmd(iteration)`` — return the CLI command to launch the tmux window
- ``parse_verdict(output)`` — extract a verdict from Claude's output
- ``on_verdict(verdict, output)`` — handle a verdict (logging, state updates)
"""

import secrets
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from pm_core.paths import configure_logger
from pm_core.loop_shared import (
    get_pm_session,
    find_claude_pane,
    poll_for_verdict as _poll_for_verdict_shared,
    wait_for_follow_up_verdict as _wait_for_follow_up_shared,
)

_log = configure_logger("pm.watcher_base")

# Max history entries to keep (watchers run indefinitely, so cap memory)
_MAX_HISTORY = 50


def _generate_loop_id() -> str:
    """Generate a short random loop identifier (4 hex chars)."""
    return secrets.token_hex(2)


@dataclass
class WatcherIteration:
    """Result of a single watcher iteration."""
    iteration: int
    verdict: str
    summary: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class WatcherState:
    """Shared state for all watchers.

    Replaces the old ``WatcherLoopState`` with a generic version that
    carries a ``watcher_id`` so the manager and TUI can differentiate
    between watcher types.
    """
    watcher_id: str = ""
    watcher_type: str = ""
    display_name: str = ""
    running: bool = False
    stop_requested: bool = False
    iteration: int = 0
    latest_verdict: str = ""
    latest_summary: str = ""
    history: list[WatcherIteration] = field(default_factory=list)
    loop_id: str = field(default_factory=_generate_loop_id)
    iteration_wait: float = 120.0
    input_required: bool = False
    _ui_notified_done: bool = False
    _ui_notified_input: bool = False
    _transcript_dir: str | None = None


class PaneKilledError(Exception):
    """Raised when the watcher pane disappears before producing a verdict."""


class BaseWatcher(ABC):
    """Abstract base class for all watchers.

    Subclasses must define class-level attributes and implement the four
    abstract methods.  The shared loop engine in ``run_sync`` handles
    iteration management, verdict polling, INPUT_REQUIRED handling, and
    inter-iteration waiting.
    """

    # --- Class-level configuration (override in subclasses) ---
    WATCHER_TYPE: str = ""          # e.g. "auto-start"
    DISPLAY_NAME: str = ""          # e.g. "Auto-Start Watcher"
    WINDOW_NAME: str = ""           # tmux window name
    DEFAULT_INTERVAL: float = 120   # seconds between iterations
    VERDICTS: tuple[str, ...] = ("READY", "INPUT_REQUIRED")
    KEYWORDS: tuple[str, ...] = ("READY", "INPUT_REQUIRED")

    # Polling configuration
    POLL_INTERVAL: float = 5        # seconds between verdict checks
    TICK_INTERVAL: float = 1        # seconds between liveness checks
    VERDICT_GRACE_PERIOD: float = 30  # min seconds before accepting verdicts

    def __init__(self, pm_root: str, state: WatcherState | None = None):
        self.pm_root = pm_root
        if state is None:
            state = WatcherState(
                watcher_id=f"{self.WATCHER_TYPE}-{_generate_loop_id()}",
                watcher_type=self.WATCHER_TYPE,
                display_name=self.DISPLAY_NAME,
                iteration_wait=self.DEFAULT_INTERVAL,
            )
        self.state = state

    # --- Abstract methods (implement in subclasses) ---

    @abstractmethod
    def generate_prompt(self, iteration: int) -> str:
        """Generate the Claude prompt for this iteration."""

    @abstractmethod
    def build_launch_cmd(self, iteration: int,
                         transcript: str | None = None) -> list[str]:
        """Return the shell command to launch the watcher tmux window."""

    @abstractmethod
    def parse_verdict(self, output: str) -> str:
        """Extract a verdict from Claude output."""

    def on_verdict(self, verdict: str, output: str) -> None:
        """Handle a verdict after each iteration (optional override)."""

    def should_continue(self, verdict: str) -> bool:
        """Return True to continue the loop after this verdict."""
        return verdict == "READY"

    # --- Shared loop engine ---

    def _launch_window(self, iteration: int,
                       transcript: str | None = None) -> None:
        """Launch the watcher tmux window via subprocess."""
        cmd = self.build_launch_cmd(iteration, transcript=transcript)
        _log.info("watcher[%s]: launching window: %s", self.WATCHER_TYPE, cmd)
        result = subprocess.run(
            cmd, cwd=self.pm_root, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else ""
            stdout = result.stdout.strip() if result.stdout else ""
            detail = stderr[:500] or stdout[:500]
            raise RuntimeError(
                f"Watcher window launch failed (rc={result.returncode}): {detail}"
            )

    def _poll_for_verdict(self, pane_id: str, prompt_text: str = "",
                          exclude_verdicts: set[str] | None = None,
                          grace_period: float = 0) -> str | None:
        """Poll pane until a verdict is stable."""
        return _poll_for_verdict_shared(
            pane_id,
            verdicts=self.VERDICTS,
            keywords=self.KEYWORDS,
            prompt_text=prompt_text,
            exclude_verdicts=exclude_verdicts,
            grace_period=grace_period,
            poll_interval=self.POLL_INTERVAL,
            tick_interval=self.TICK_INTERVAL,
            stop_check=lambda: self.state.stop_requested,
            log_prefix=f"watcher[{self.WATCHER_TYPE}]",
        )

    def _wait_for_follow_up(self, prompt_text: str) -> str | None:
        """Poll for a follow-up verdict after INPUT_REQUIRED."""
        session = get_pm_session()
        if not session:
            return None
        return _wait_for_follow_up_shared(
            session, self.WINDOW_NAME,
            verdicts=self.VERDICTS,
            keywords=self.KEYWORDS,
            prompt_text=prompt_text,
            exclude_verdicts={"INPUT_REQUIRED"},
            poll_interval=self.POLL_INTERVAL,
            tick_interval=self.TICK_INTERVAL,
            stop_check=lambda: self.state.stop_requested,
            log_prefix=f"watcher[{self.WATCHER_TYPE}]",
        )

    def _run_iteration(self, iteration: int,
                       transcript: str | None = None) -> str:
        """Launch a window, poll for verdict, return output content."""
        from pm_core import tmux as tmux_mod

        session = get_pm_session()
        if not session:
            raise RuntimeError("Not in a pm tmux session")
        if not tmux_mod.session_exists(session):
            raise RuntimeError(f"tmux session '{session}' no longer exists")

        self._launch_window(iteration, transcript=transcript)

        prompt_text = self.generate_prompt(iteration)
        _log.info("watcher[%s]: prompt_text for filtering: %d chars",
                  self.WATCHER_TYPE, len(prompt_text))

        time.sleep(2)

        pane_id = find_claude_pane(session, self.WINDOW_NAME)
        if not pane_id:
            raise RuntimeError(
                f"Window '{self.WINDOW_NAME}' not found after launch"
            )

        _log.info("watcher[%s]: polling pane %s in window %s",
                  self.WATCHER_TYPE, pane_id, self.WINDOW_NAME)

        content = self._poll_for_verdict(
            pane_id, prompt_text=prompt_text,
            grace_period=self.VERDICT_GRACE_PERIOD,
        )
        if content is None:
            if self.state.stop_requested:
                raise PaneKilledError("Watcher stopped by user")
            raise PaneKilledError(
                f"Pane disappeared (window: {self.WINDOW_NAME})"
            )
        return content

    def run_sync(
        self,
        on_iteration: Callable[[WatcherState], None] | None = None,
        max_iterations: int = 0,
        transcript_dir: str | None = None,
    ) -> WatcherState:
        """Run the watcher loop synchronously (for a background thread).

        Args:
            on_iteration: Callback fired after each iteration.
            max_iterations: Safety cap (0 = unlimited).
            transcript_dir: Directory for transcript symlinks.

        Returns:
            The final state.
        """
        state = self.state
        state._transcript_dir = transcript_dir
        state.running = True
        state.stop_requested = False

        try:
            while max_iterations == 0 or state.iteration < max_iterations:
                if state.stop_requested:
                    _log.info("watcher[%s]: stop requested after %d iterations",
                              self.WATCHER_TYPE, state.iteration)
                    break

                state.iteration += 1
                _log.info("watcher[%s]: iteration %d",
                          self.WATCHER_TYPE, state.iteration)

                iter_transcript = None
                if transcript_dir:
                    iter_transcript = (
                        f"{transcript_dir}/{self.WATCHER_TYPE}-i{state.iteration}.jsonl"
                    )

                try:
                    output = self._run_iteration(
                        state.iteration, transcript=iter_transcript,
                    )
                except PaneKilledError as e:
                    _log.warning("watcher[%s]: pane killed on iteration %d: %s",
                                 self.WATCHER_TYPE, state.iteration, e)
                    state.latest_verdict = "KILLED"
                    state.latest_summary = str(e)
                    break
                except Exception as e:
                    _log.exception("watcher[%s]: iteration %d failed",
                                   self.WATCHER_TYPE, state.iteration)
                    state.latest_verdict = "ERROR"
                    state.latest_summary = str(e)
                    break

                verdict = self.parse_verdict(output)
                state.latest_verdict = verdict
                state.latest_summary = output[-500:] if len(output) > 500 else output

                iteration_result = WatcherIteration(
                    iteration=state.iteration,
                    verdict=verdict,
                    summary=state.latest_summary,
                )
                state.history.append(iteration_result)
                if len(state.history) > _MAX_HISTORY:
                    state.history = state.history[-_MAX_HISTORY:]

                _log.info("watcher[%s]: iteration %d verdict=%s",
                          self.WATCHER_TYPE, state.iteration, verdict)

                self.on_verdict(verdict, output)

                if on_iteration:
                    try:
                        on_iteration(state)
                    except Exception:
                        _log.exception("watcher[%s]: on_iteration callback failed",
                                       self.WATCHER_TYPE)

                # Handle INPUT_REQUIRED
                if verdict == "INPUT_REQUIRED":
                    self._handle_input_required(on_iteration)

                if state.stop_requested:
                    break

                # Wait before next iteration if continuing
                if self.should_continue(state.latest_verdict):
                    _log.info("watcher[%s]: waiting %ds before next iteration",
                              self.WATCHER_TYPE, state.iteration_wait)
                    wait_start = time.monotonic()
                    while time.monotonic() - wait_start < state.iteration_wait:
                        if state.stop_requested:
                            break
                        time.sleep(self.TICK_INTERVAL)
                else:
                    break

        finally:
            state.running = False

        return state

    def _handle_input_required(
        self,
        on_iteration: Callable[[WatcherState], None] | None = None,
    ) -> None:
        """Handle INPUT_REQUIRED: poll for follow-up verdict."""
        state = self.state
        _log.info("watcher[%s]: INPUT_REQUIRED -- polling for follow-up",
                  self.WATCHER_TYPE)
        state.input_required = True
        state._ui_notified_input = False

        prompt_text = self.generate_prompt(state.iteration)
        follow_up_output = self._wait_for_follow_up(prompt_text)
        state.input_required = False

        if follow_up_output is None:
            if state.stop_requested:
                return
            state.latest_verdict = "KILLED"
            state.latest_summary = "Pane disappeared during INPUT_REQUIRED wait"
            return

        verdict = self.parse_verdict(follow_up_output)
        # Treat repeated INPUT_REQUIRED as READY (continue loop)
        if verdict == "INPUT_REQUIRED":
            verdict = "READY"
        state.latest_verdict = verdict
        state.latest_summary = (
            follow_up_output[-500:] if len(follow_up_output) > 500
            else follow_up_output
        )

        state.history[-1] = WatcherIteration(
            iteration=state.iteration,
            verdict=verdict,
            summary=state.latest_summary,
        )
        _log.info("watcher[%s]: follow-up verdict=%s",
                  self.WATCHER_TYPE, verdict)

        self.on_verdict(verdict, follow_up_output)

        if on_iteration:
            try:
                on_iteration(state)
            except Exception:
                _log.exception("watcher[%s]: on_iteration callback failed",
                               self.WATCHER_TYPE)

    def start_background(
        self,
        on_iteration: Callable[[WatcherState], None] | None = None,
        on_complete: Callable[[WatcherState], None] | None = None,
        max_iterations: int = 0,
        transcript_dir: str | None = None,
    ) -> threading.Thread:
        """Start the watcher loop in a background thread."""
        def _run():
            self.run_sync(
                on_iteration=on_iteration,
                max_iterations=max_iterations,
                transcript_dir=transcript_dir,
            )
            if on_complete:
                try:
                    on_complete(self.state)
                except Exception:
                    _log.exception("watcher[%s]: on_complete callback failed",
                                   self.WATCHER_TYPE)

        thread = threading.Thread(
            target=_run, daemon=True,
            name=f"watcher-{self.WATCHER_TYPE}",
        )
        thread.start()
        return thread
