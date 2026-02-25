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

import re
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from pm_core.paths import configure_logger

_log = configure_logger("pm.monitor_loop")

# Monitor verdicts
VERDICT_READY = "READY"
VERDICT_INPUT_REQUIRED = "INPUT_REQUIRED"
VERDICT_KILLED = "KILLED"

ALL_MONITOR_VERDICTS = (VERDICT_READY, VERDICT_INPUT_REQUIRED)

# How often to check pane content for a verdict (seconds)
_POLL_INTERVAL = 5
# How often to check pane liveness / stop_requested between content polls
_TICK_INTERVAL = 1
# Consecutive stable polls required before accepting verdict
_STABILITY_POLLS = 2
# Minimum seconds after iteration start before accepting verdicts
_VERDICT_GRACE_PERIOD = 30
# Default wait time between iterations (seconds)
DEFAULT_ITERATION_WAIT = 120
# Only scan the tail of captured pane content for verdicts
_VERDICT_TAIL_LINES = 30


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
    cleaned = re.sub(r'[*`]', '', line).strip()
    for verdict in ALL_MONITOR_VERDICTS:
        if cleaned == verdict:
            return verdict
    return None


def _build_prompt_verdict_lines(prompt_text: str) -> set[str]:
    """Build a set of normalized prompt lines that contain verdict keywords."""
    result = set()
    for line in prompt_text.splitlines():
        normalized = line.replace("*", "").replace("`", "").strip()
        if normalized and any(v in normalized for v in ("READY", "INPUT_REQUIRED")):
            result.add(normalized)
    return result


def _is_prompt_line(stripped_line: str, prompt_verdict_lines: set[str]) -> bool:
    """Check if a verdict-containing line comes from the prompt, not Claude."""
    context = stripped_line
    for keyword in ("INPUT_REQUIRED", "READY"):
        context = context.replace(keyword, "")
    context = context.strip(" \t--:().").strip()

    if len(context) > 3:
        stripped_clean = stripped_line.replace("*", "").replace("`", "").strip()
        for pvl in prompt_verdict_lines:
            if context in pvl or stripped_clean in pvl or pvl in stripped_clean:
                return True
    return False


def _extract_verdict_from_content(content: str, prompt_text: str = "",
                                   exclude_verdicts: set[str] | None = None) -> str | None:
    """Check if the tail of captured pane content contains a monitor verdict."""
    lines = content.strip().splitlines()
    tail = lines[-_VERDICT_TAIL_LINES:] if len(lines) > _VERDICT_TAIL_LINES else lines

    prompt_verdict_lines = _build_prompt_verdict_lines(prompt_text) if prompt_text else set()

    for line in reversed(tail):
        stripped = line.strip().strip("*").strip()
        verdict = _match_monitor_verdict(stripped)

        if verdict:
            if exclude_verdicts and verdict in exclude_verdicts:
                continue
            if prompt_verdict_lines and _is_prompt_line(stripped, prompt_verdict_lines):
                _log.info("monitor_loop: SKIPPED prompt verdict line: [%s]", stripped[:100])
                continue
            _log.info("monitor_loop: ACCEPTED verdict line: [%s] (verdict=%s)", stripped[:100], verdict)
            return verdict
    return None


def _get_pm_session() -> str | None:
    """Get the pm tmux session name."""
    from pm_core.cli.helpers import _get_current_pm_session
    return _get_current_pm_session()


def _find_claude_pane(session: str, window_name: str) -> str | None:
    """Find the Claude pane ID in the monitor window (first pane)."""
    from pm_core import tmux as tmux_mod
    win = tmux_mod.find_window_by_name(session, window_name)
    if not win:
        return None
    panes = tmux_mod.get_pane_indices(session, win["index"])
    if panes:
        return panes[0][0]
    return None


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


def _sleep_checking_pane(pane_id: str, seconds: float,
                          state: MonitorLoopState | None = None) -> bool:
    """Sleep for *seconds*, checking pane liveness every tick.

    Returns True if the pane is still alive, False if it disappeared.
    Also checks state.stop_requested if state is provided.
    """
    from pm_core import tmux as tmux_mod

    elapsed = 0.0
    while elapsed < seconds:
        time.sleep(_TICK_INTERVAL)
        elapsed += _TICK_INTERVAL
        if state and state.stop_requested:
            return True  # pane alive but stopping
        if not tmux_mod.pane_exists(pane_id):
            return False
    return True


def _poll_for_verdict(pane_id: str, prompt_text: str = "",
                      exclude_verdicts: set[str] | None = None,
                      grace_period: float = 0,
                      state: MonitorLoopState | None = None) -> str | None:
    """Poll a pane until a verdict is stable.

    Returns the captured pane content when a verdict is found.
    Returns None if the pane disappears or stop is requested.
    """
    from pm_core import tmux as tmux_mod

    last_verdict = None
    stable_count = 0
    poll_start = time.monotonic()

    while True:
        if state and state.stop_requested:
            return None

        if not tmux_mod.pane_exists(pane_id):
            _log.warning("monitor_loop: pane %s disappeared", pane_id)
            return None

        in_grace = grace_period > 0 and (time.monotonic() - poll_start) < grace_period

        content = tmux_mod.capture_pane(pane_id, full_scrollback=True)
        if not content.strip():
            if not _sleep_checking_pane(pane_id, _POLL_INTERVAL, state):
                return None
            continue

        if in_grace:
            if not _sleep_checking_pane(pane_id, _POLL_INTERVAL, state):
                return None
            continue

        verdict = _extract_verdict_from_content(content, prompt_text,
                                                 exclude_verdicts=exclude_verdicts)
        if verdict:
            if verdict == last_verdict:
                stable_count += 1
            else:
                last_verdict = verdict
                stable_count = 1

            if stable_count >= _STABILITY_POLLS:
                _log.info("monitor_loop: verdict %s stable for %d polls", verdict, stable_count)
                return content
        else:
            last_verdict = None
            stable_count = 0

        if not _sleep_checking_pane(pane_id, _POLL_INTERVAL, state):
            return None


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

    Used after INPUT_REQUIRED is detected. The user interacts with Claude
    in the monitor pane. Returns content when a follow-up verdict is found.
    """
    from pm_core import tmux as tmux_mod

    session = _get_pm_session()
    if not session:
        return None

    last_verdict: str | None = None
    stable_count = 0

    while not state.stop_requested:
        pane_id = _find_claude_pane(session, MONITOR_WINDOW_NAME)
        if not pane_id:
            _log.warning("monitor_loop: monitor pane gone during INPUT_REQUIRED wait")
            return None

        content = tmux_mod.capture_pane(pane_id, full_scrollback=True)
        if content.strip():
            verdict = _extract_verdict_from_content(
                content, prompt_text,
                exclude_verdicts={VERDICT_INPUT_REQUIRED},
            )
            if verdict:
                if verdict == last_verdict:
                    stable_count += 1
                else:
                    last_verdict = verdict
                    stable_count = 1
                if stable_count >= _STABILITY_POLLS:
                    _log.info("monitor_loop: follow-up verdict %s stable", verdict)
                    return content
            else:
                last_verdict = None
                stable_count = 0

        for _ in range(int(_POLL_INTERVAL / _TICK_INTERVAL)):
            if state.stop_requested:
                return None
            time.sleep(_TICK_INTERVAL)

    return None


def parse_monitor_verdict(output: str) -> str:
    """Extract a monitor verdict from Claude output."""
    lines = output.strip().splitlines()
    for line in reversed(lines):
        stripped = line.strip().strip("*").strip()
        verdict = _match_monitor_verdict(stripped)
        if verdict:
            return verdict
    return VERDICT_READY if output.strip() else VERDICT_READY


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
