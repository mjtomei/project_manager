"""Monitor loop: observe auto-start sessions and fix issues autonomously.

The monitor loop launches a Claude session in a tmux window that periodically
scans all active panes, checks for errors or stuck processes, and attempts
corrective actions.  It works similarly to the review loop but with only two
verdicts:

Verdicts:
  READY            -- All issues handled, wait for next iteration.
  INPUT_REQUIRED   -- Needs human input or wants to surface something.

The loop pauses on INPUT_REQUIRED (user interacts with Claude in the
monitor pane) and resumes when the user provides direction.  Between
READY iterations there is a configurable wait time.
"""

import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from pm_core.paths import configure_logger
from pm_core.loop_shared import (
    get_pm_session as _get_pm_session_shared,
    find_claude_pane as _find_claude_pane_shared,
    match_verdict,
    extract_verdict_from_content,
    poll_for_verdict as _poll_for_verdict_shared,
    wait_for_follow_up_verdict as _wait_for_follow_up_shared,
)

_log = configure_logger("pm.monitor_loop")

# Monitor verdicts
VERDICT_READY = "READY"
VERDICT_INPUT_REQUIRED = "INPUT_REQUIRED"
VERDICT_KILLED = "KILLED"

ALL_MONITOR_VERDICTS = (VERDICT_READY, VERDICT_INPUT_REQUIRED)

# Keywords used for prompt line filtering (all verdict keywords)
_MONITOR_KEYWORDS = ("INPUT_REQUIRED", "READY")

# How often to check pane content for a verdict (seconds)
_POLL_INTERVAL = 5
# How often to check pane liveness / stop_requested between content polls
_TICK_INTERVAL = 1
# Minimum seconds after iteration start before accepting verdicts
_VERDICT_GRACE_PERIOD = 30
# Default wait time between iterations (seconds)
DEFAULT_ITERATION_WAIT = 120
# Max history entries to keep (monitor runs indefinitely, so cap memory)
_MAX_HISTORY = 50


@dataclass
class MonitorIteration:
    """Result of a single monitor iteration."""
    iteration: int
    verdict: str
    summary: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


def _generate_loop_id() -> str:
    """Generate a short random loop identifier (4 hex chars)."""
    return secrets.token_hex(2)


@dataclass
class MonitorLoopState:
    """Tracks the state of a running monitor loop."""
    running: bool = False
    stop_requested: bool = False
    iteration: int = 0
    latest_verdict: str = ""
    latest_summary: str = ""
    history: list[MonitorIteration] = field(default_factory=list)
    loop_id: str = field(default_factory=_generate_loop_id)
    iteration_wait: float = DEFAULT_ITERATION_WAIT
    _ui_notified_done: bool = False
    _ui_notified_input: bool = False
    # INPUT_REQUIRED: set to True while polling for follow-up verdict
    input_required: bool = False
    _transcript_dir: str | None = None


def _match_monitor_verdict(line: str) -> str | None:
    """Match a monitor verdict keyword when it is the entire line content."""
    return match_verdict(line, ALL_MONITOR_VERDICTS)


def _extract_verdict_from_content(content: str, prompt_text: str = "",
                                   exclude_verdicts: set[str] | None = None) -> str | None:
    """Check if the tail of captured pane content contains a monitor verdict."""
    return extract_verdict_from_content(
        content, verdicts=ALL_MONITOR_VERDICTS, keywords=_MONITOR_KEYWORDS,
        prompt_text=prompt_text, exclude_verdicts=exclude_verdicts,
        log_prefix="monitor_loop",
    )


def _get_pm_session() -> str | None:
    """Get the pm tmux session name."""
    return _get_pm_session_shared()


def _find_claude_pane(session: str, window_name: str) -> str | None:
    """Find the Claude pane ID in the monitor window (first pane)."""
    return _find_claude_pane_shared(session, window_name)


MONITOR_WINDOW_NAME = "monitor"


def _launch_monitor_window(pm_root: str, iteration: int = 0,
                            loop_id: str = "",
                            transcript: str | None = None) -> None:
    """Launch the monitor window via ``pm pr start``-style Claude session."""
    cmd = [sys.executable, "-m", "pm_core.wrapper",
           "monitor", "--iteration", str(iteration)]
    if loop_id:
        cmd.extend(["--loop-id", loop_id])
    if transcript:
        cmd.extend(["--transcript", transcript])
    _log.info("monitor_loop: launching monitor window: %s", cmd)
    subprocess.run(cmd, cwd=pm_root, capture_output=True, text=True, timeout=30)


def _poll_for_verdict(pane_id: str, prompt_text: str = "",
                      exclude_verdicts: set[str] | None = None,
                      grace_period: float = 0,
                      state: MonitorLoopState | None = None) -> str | None:
    """Poll a pane until a verdict is stable.

    Delegates to the shared ``poll_for_verdict`` in ``loop_shared``.
    """
    return _poll_for_verdict_shared(
        pane_id, verdicts=ALL_MONITOR_VERDICTS, keywords=_MONITOR_KEYWORDS,
        prompt_text=prompt_text, exclude_verdicts=exclude_verdicts,
        grace_period=grace_period, poll_interval=_POLL_INTERVAL,
        tick_interval=_TICK_INTERVAL,
        stop_check=lambda: state.stop_requested if state else False,
        log_prefix="monitor_loop",
    )


class PaneKilledError(Exception):
    """Raised when the monitor pane disappears before producing a verdict."""


def _regenerate_prompt_text(pm_root: str, iteration: int = 0,
                             loop_id: str = "") -> str:
    """Regenerate the monitor prompt text for verdict filtering."""
    try:
        from pathlib import Path
        from pm_core import store
        from pm_core.prompt_gen import generate_monitor_prompt
        data = store.load(Path(pm_root))
        return generate_monitor_prompt(
            data, iteration=iteration, loop_id=loop_id,
        )
    except Exception as exc:
        _log.warning("monitor_loop: could not regenerate prompt text: %s", exc)
        return ""


def _run_monitor_iteration(pm_root: str, iteration: int = 0,
                            loop_id: str = "",
                            transcript: str | None = None,
                            state: MonitorLoopState | None = None) -> str:
    """Launch a monitor window and poll for the verdict.

    Returns the captured pane content containing the verdict.
    Raises PaneKilledError if the pane disappears.
    """
    from pm_core import tmux as tmux_mod

    session = _get_pm_session()
    if not session:
        raise RuntimeError("Not in a pm tmux session")
    if not tmux_mod.session_exists(session):
        raise RuntimeError(f"tmux session '{session}' no longer exists")

    _launch_monitor_window(pm_root, iteration=iteration, loop_id=loop_id,
                            transcript=transcript)

    prompt_text = _regenerate_prompt_text(pm_root, iteration, loop_id)
    _log.info("monitor_loop: prompt_text for filtering: %d chars", len(prompt_text))

    time.sleep(2)

    pane_id = _find_claude_pane(session, MONITOR_WINDOW_NAME)
    if not pane_id:
        raise RuntimeError(f"Monitor window '{MONITOR_WINDOW_NAME}' not found after launch")

    _log.info("monitor_loop: polling pane %s in window %s", pane_id, MONITOR_WINDOW_NAME)
    content = _poll_for_verdict(pane_id, prompt_text=prompt_text,
                                 grace_period=_VERDICT_GRACE_PERIOD,
                                 state=state)
    if content is None:
        if state and state.stop_requested:
            raise PaneKilledError("Monitor stopped by user")
        raise PaneKilledError(f"Monitor pane disappeared (window: {MONITOR_WINDOW_NAME})")
    return content


def _wait_for_follow_up_verdict(prompt_text: str,
                                 state: MonitorLoopState) -> str | None:
    """Poll the existing monitor pane for a non-INPUT_REQUIRED verdict.

    Delegates to the shared ``wait_for_follow_up_verdict`` in ``loop_shared``.
    """
    session = _get_pm_session()
    if not session:
        return None

    return _wait_for_follow_up_shared(
        session, MONITOR_WINDOW_NAME,
        verdicts=ALL_MONITOR_VERDICTS, keywords=_MONITOR_KEYWORDS,
        prompt_text=prompt_text, exclude_verdicts={VERDICT_INPUT_REQUIRED},
        poll_interval=_POLL_INTERVAL, tick_interval=_TICK_INTERVAL,
        stop_check=lambda: state.stop_requested, log_prefix="monitor_loop",
    )


def parse_monitor_verdict(output: str) -> str:
    """Extract a monitor verdict from Claude output."""
    lines = output.strip().splitlines()
    for line in reversed(lines):
        stripped = line.strip().strip("*").strip()
        verdict = _match_monitor_verdict(stripped)
        if verdict:
            return verdict
    # No clear verdict found — default to READY (continue monitoring)
    return VERDICT_READY


def run_monitor_loop_sync(
    state: MonitorLoopState,
    pm_root: str,
    on_iteration: Callable[[MonitorLoopState], None] | None = None,
    max_iterations: int = 0,
    transcript_dir: str | None = None,
) -> MonitorLoopState:
    """Run the monitor loop synchronously (intended for a background thread).

    Args:
        state: Mutable state object.
        pm_root: Path to the pm project root.
        on_iteration: Optional callback fired after each iteration.
        max_iterations: Safety cap (0 = unlimited).
        transcript_dir: Directory for transcript symlinks.

    Returns:
        The final state.
    """
    state._transcript_dir = transcript_dir
    state.running = True
    state.stop_requested = False

    try:
        while max_iterations == 0 or state.iteration < max_iterations:
            if state.stop_requested:
                _log.info("monitor_loop: stop requested after %d iterations", state.iteration)
                break

            state.iteration += 1
            _log.info("monitor_loop: iteration %d", state.iteration)

            iter_transcript = None
            if transcript_dir:
                iter_transcript = f"{transcript_dir}/monitor-i{state.iteration}.jsonl"

            try:
                output = _run_monitor_iteration(
                    pm_root,
                    iteration=state.iteration,
                    loop_id=state.loop_id,
                    transcript=iter_transcript,
                    state=state,
                )
            except PaneKilledError as e:
                _log.warning("monitor_loop: pane killed on iteration %d: %s", state.iteration, e)
                state.latest_verdict = VERDICT_KILLED
                state.latest_summary = str(e)
                break
            except Exception as e:
                _log.exception("monitor_loop: iteration %d failed", state.iteration)
                state.latest_verdict = "ERROR"
                state.latest_summary = str(e)
                break

            verdict = parse_monitor_verdict(output)
            state.latest_verdict = verdict
            state.latest_summary = output[-500:] if len(output) > 500 else output

            iteration_result = MonitorIteration(
                iteration=state.iteration,
                verdict=verdict,
                summary=state.latest_summary,
            )
            state.history.append(iteration_result)
            # Cap history to prevent unbounded memory growth
            if len(state.history) > _MAX_HISTORY:
                state.history = state.history[-_MAX_HISTORY:]

            _log.info("monitor_loop: iteration %d verdict=%s", state.iteration, verdict)

            if on_iteration:
                try:
                    on_iteration(state)
                except Exception:
                    _log.exception("monitor_loop: on_iteration callback failed")

            # Handle INPUT_REQUIRED
            if verdict == VERDICT_INPUT_REQUIRED:
                _log.info("monitor_loop: INPUT_REQUIRED -- polling for follow-up")
                state.input_required = True
                state._ui_notified_input = False

                follow_up_prompt = _regenerate_prompt_text(
                    pm_root, state.iteration, state.loop_id,
                )
                follow_up_output = _wait_for_follow_up_verdict(
                    follow_up_prompt, state,
                )
                state.input_required = False

                if follow_up_output is None:
                    if state.stop_requested:
                        break
                    state.latest_verdict = VERDICT_KILLED
                    state.latest_summary = "Monitor pane disappeared during INPUT_REQUIRED wait"
                    break

                verdict = parse_monitor_verdict(follow_up_output)
                # Treat repeated INPUT_REQUIRED as READY (continue loop)
                if verdict == VERDICT_INPUT_REQUIRED:
                    verdict = VERDICT_READY
                state.latest_verdict = verdict
                state.latest_summary = follow_up_output[-500:] if len(follow_up_output) > 500 else follow_up_output

                state.history[-1] = MonitorIteration(
                    iteration=state.iteration,
                    verdict=verdict,
                    summary=state.latest_summary,
                )
                _log.info("monitor_loop: follow-up verdict=%s", verdict)

                if on_iteration:
                    try:
                        on_iteration(state)
                    except Exception:
                        _log.exception("monitor_loop: on_iteration callback failed")

            if state.stop_requested:
                break

            # READY verdict: wait before next iteration
            if verdict == VERDICT_READY:
                _log.info("monitor_loop: waiting %ds before next iteration",
                          state.iteration_wait)
                wait_start = time.monotonic()
                while time.monotonic() - wait_start < state.iteration_wait:
                    if state.stop_requested:
                        break
                    time.sleep(_TICK_INTERVAL)

    finally:
        state.running = False

    return state


def start_monitor_loop_background(
    state: MonitorLoopState,
    pm_root: str,
    on_iteration: Callable[[MonitorLoopState], None] | None = None,
    on_complete: Callable[[MonitorLoopState], None] | None = None,
    max_iterations: int = 0,
    transcript_dir: str | None = None,
) -> threading.Thread:
    """Start the monitor loop in a background thread.

    Returns the thread so the caller can join it if needed.
    """
    def _run():
        run_monitor_loop_sync(
            state, pm_root,
            on_iteration=on_iteration,
            max_iterations=max_iterations,
            transcript_dir=transcript_dir,
        )
        if on_complete:
            try:
                on_complete(state)
            except Exception:
                _log.exception("monitor_loop: on_complete callback failed")

    thread = threading.Thread(target=_run, daemon=True, name="monitor-loop")
    thread.start()
    return thread
