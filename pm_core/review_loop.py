"""Review loop: repeatedly run Claude review until PASS.

The loop launches a visible tmux review window (via ``pm pr review
--fresh --review-loop``) and polls the Claude pane for a verdict via
Claude Code hook events + JSONL transcript.

Verdicts:
  PASS            — No changes needed, code is ready to merge.
  NEEDS_WORK      — Blocking issues found; loop iterates after fixes.
  INPUT_REQUIRED  — Human-guided testing needed before sign-off.

The loop stops on PASS.

When INPUT_REQUIRED is detected, the loop marks the PR as paused and
polls the existing review pane for a follow-up verdict.  The user
interacts directly with Claude in the review pane (e.g. performing
the requested tests and reporting results).  Once Claude emits a new
verdict (PASS or NEEDS_WORK), the loop picks it up automatically and
resumes normal flow — no TUI interaction required.
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
    poll_for_verdict as _poll_for_verdict_shared,
    wait_for_follow_up_verdict as _wait_for_follow_up_shared,
)

_log = configure_logger("pm.review_loop")

# Review verdicts in order of severity
VERDICT_PASS = "PASS"
VERDICT_NEEDS_WORK = "NEEDS_WORK"
VERDICT_INPUT_REQUIRED = "INPUT_REQUIRED"
VERDICT_KILLED = "KILLED"

ALL_VERDICTS = (VERDICT_PASS, VERDICT_NEEDS_WORK, VERDICT_INPUT_REQUIRED)

# Minimum seconds after poll start before accepting verdicts.
# Claude reviews take minutes; verdicts found in the first few seconds are
# almost certainly false positives from prompt text shown in the pane.
_VERDICT_GRACE_PERIOD = 20


@dataclass
class ReviewIteration:
    """Result of a single review iteration."""
    iteration: int
    verdict: str
    output: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


def _generate_loop_id() -> str:
    """Generate a short random loop identifier (4 hex chars)."""
    return secrets.token_hex(2)


@dataclass
class ReviewLoopState:
    """Tracks the state of a running review loop."""
    pr_id: str
    running: bool = False
    stop_requested: bool = False
    iteration: int = 0
    latest_verdict: str = ""
    latest_output: str = ""
    history: list[ReviewIteration] = field(default_factory=list)
    loop_id: str = field(default_factory=_generate_loop_id)
    _ui_notified_done: bool = False
    _ui_notified_input: bool = False
    _transcript_dir: str | None = None
    # INPUT_REQUIRED: set to True while polling for follow-up verdict
    input_required: bool = False


def _match_verdict(line: str) -> str | None:
    """Match a verdict keyword only when it is the entire line content."""
    return match_verdict(line, ALL_VERDICTS)


def parse_review_verdict(output: str) -> str:
    """Extract a review verdict from Claude output.

    Scans from the end of the output upward, looking for verdict keywords.
    Returns the most specific match found.
    """
    lines = output.strip().splitlines()
    # Scan from the end — the verdict is typically at the bottom
    for line in reversed(lines):
        stripped = line.strip().strip("*").strip()
        verdict = _match_verdict(stripped)
        if verdict:
            return verdict
    # If no clear verdict, assume needs work if there's output
    return VERDICT_NEEDS_WORK if output.strip() else VERDICT_PASS


def _compute_review_window_name(pr_data: dict) -> str:
    """Compute the review window name from PR data (matches cli/pr.py)."""
    gh = pr_data.get("gh_pr_number")
    display_id = f"#{gh}" if gh else pr_data.get("id", "???")
    return f"review-{display_id}"


def _launch_review_window(pr_id: str, pm_root: str, iteration: int = 0,
                          loop_id: str = "",
                          transcript: str | None = None) -> None:
    """Launch a review window via ``pm pr review --fresh --review-loop``."""
    cmd = [sys.executable, "-m", "pm_core.wrapper",
           "pr", "review", "--fresh", "--review-loop",
           "--review-iteration", str(iteration)]
    if loop_id:
        cmd.extend(["--review-loop-id", loop_id])
    if transcript:
        cmd.extend(["--transcript", transcript])
    cmd.append(pr_id)
    _log.info("relauncher: pr=%s iteration=%s loop_id=%s cmd=%s",
              pr_id, iteration, loop_id, cmd)
    t0 = time.monotonic()
    result = subprocess.run(cmd, cwd=pm_root, capture_output=True, text=True, timeout=120)
    elapsed = time.monotonic() - t0
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        stdout = result.stdout.strip() if result.stdout else ""
        _log.error("review_loop: launch failed (rc=%d) stderr=%s stdout=%s",
                   result.returncode, stderr[:1000], stdout[:500])
        detail = stderr[:500] or stdout[:500]
        raise RuntimeError(f"Review window launch failed (rc={result.returncode}): {detail}")
    _log.info("relauncher: pr=%s rc=%d elapsed=%.2fs",
              pr_id, result.returncode, elapsed)


def _find_claude_pane(session: str, window_name: str) -> str | None:
    """Find the Claude pane ID in the review window (first pane)."""
    return _find_claude_pane_shared(session, window_name)


def _poll_for_verdict(pane_id: str, transcript_path: str,
                      grace_period: float = 0) -> str | None:
    """Poll a pane for a verdict via Claude Code hook events."""
    return _poll_for_verdict_shared(
        pane_id, transcript_path, verdicts=ALL_VERDICTS,
        grace_period=grace_period, log_prefix="review_loop",
    )


def _get_pm_session() -> str | None:
    """Get the pm tmux session name."""
    return _get_pm_session_shared()


class PaneKilledError(Exception):
    """Raised when the review pane disappears before producing a verdict."""


def _run_claude_review(pr_id: str, pm_root: str, pr_data: dict,
                       transcript: str,
                       iteration: int = 0, loop_id: str = "") -> str:
    """Launch a review window and poll its JSONL transcript for the verdict.

    ``transcript`` is required — it is the path to the per-iteration
    JSONL symlink that ``pm pr review --transcript ...`` writes into,
    and it is how :func:`_poll_for_verdict` recovers the Claude
    session_id and reads assistant output.

    Returns the captured assistant text containing the verdict.
    Raises :class:`PaneKilledError` if the pane disappears before a
    verdict.  Raises :class:`RuntimeError` for setup failures (no tmux
    session, window failed to launch).
    """
    from pm_core import tmux as tmux_mod

    session = _get_pm_session()
    if not session:
        raise RuntimeError("Not in a pm tmux session")
    if not tmux_mod.session_exists(session):
        raise RuntimeError(f"tmux session '{session}' no longer exists")

    window_name = _compute_review_window_name(pr_data)

    _launch_review_window(pr_id, pm_root, iteration=iteration, loop_id=loop_id,
                          transcript=transcript)

    # Wait briefly for the window to appear
    time.sleep(2)

    pane_id = _find_claude_pane(session, window_name)
    if not pane_id:
        raise RuntimeError(f"Review window '{window_name}' not found after launch")

    _log.info("review_loop: polling pane %s in window %s (transcript=%s)",
              pane_id, window_name, transcript)

    content = _poll_for_verdict(pane_id, transcript,
                                 grace_period=_VERDICT_GRACE_PERIOD)
    if content is None:
        raise PaneKilledError(f"Review pane disappeared (window: {window_name})")
    return content


def _wait_for_follow_up_verdict(pr_data: dict,
                                 state: ReviewLoopState) -> str | None:
    """Poll the existing review pane for a follow-up verdict."""
    session = _get_pm_session()
    if not session:
        _log.warning("review_loop: no pm session for follow-up polling")
        return None

    window_name = _compute_review_window_name(pr_data)
    if not getattr(state, "_transcript_dir", None):
        _log.warning("review_loop: no transcript_dir on state; cannot wait for follow-up")
        return None
    iter_transcript = f"{state._transcript_dir}/review-{state.pr_id}-i{state.iteration}.jsonl"
    return _wait_for_follow_up_shared(
        session, window_name, iter_transcript, verdicts=ALL_VERDICTS,
        stop_check=lambda: state.stop_requested, log_prefix="review_loop",
    )


def should_stop(verdict: str) -> bool:
    """Determine if the loop should stop based on the verdict."""
    return verdict == VERDICT_PASS


def run_review_loop_sync(
    state: ReviewLoopState,
    pm_root: str,
    pr_data: dict,
    transcript_dir: str,
    on_iteration: Callable[[ReviewLoopState], None] | None = None,
    max_iterations: int = 10,
) -> ReviewLoopState:
    """Run the review loop synchronously (intended for a background thread).

    ``transcript_dir`` is required: hook-driven verdict polling needs a
    per-iteration JSONL transcript symlink, and the path is embedded in
    the ``pm pr review`` command so Claude writes to a known location.

    Args:
        state: Mutable state object — the caller can read it to track progress.
        pm_root: Path to the pm project root (for running ``pm pr review``).
        pr_data: The PR dict from project data.
        transcript_dir: Directory for per-iteration transcript symlinks.
        on_iteration: Optional callback fired after each iteration completes.
        max_iterations: Safety cap on number of iterations.

    Returns:
        The final state.
    """
    # Stash transcript_dir on state so _on_complete_from_thread can finalize
    state._transcript_dir = transcript_dir
    state.running = True
    state.stop_requested = False

    try:
        while state.iteration < max_iterations:
            if state.stop_requested:
                _log.info("review_loop: stop requested after %d iterations", state.iteration)
                break

            state.iteration += 1
            _log.info("review_loop: iteration %d for %s", state.iteration, state.pr_id)

            iter_transcript = f"{transcript_dir}/review-{state.pr_id}-i{state.iteration}.jsonl"

            try:
                output = _run_claude_review(
                    state.pr_id, pm_root, pr_data,
                    iteration=state.iteration, loop_id=state.loop_id,
                    transcript=iter_transcript,
                )
            except PaneKilledError as e:
                _log.warning("review_loop: pane killed on iteration %d: %s", state.iteration, e)
                state.latest_verdict = VERDICT_KILLED
                state.latest_output = str(e)
                break
            except Exception as e:
                _log.exception("review_loop: review failed on iteration %d", state.iteration)
                state.latest_verdict = "ERROR"
                state.latest_output = str(e)
                break

            verdict = parse_review_verdict(output)
            state.latest_verdict = verdict
            state.latest_output = output

            iteration_result = ReviewIteration(
                iteration=state.iteration,
                verdict=verdict,
                output=output,
            )
            state.history.append(iteration_result)

            _log.info("review_loop: iteration %d verdict=%s", state.iteration, verdict)

            if on_iteration:
                try:
                    on_iteration(state)
                except Exception:
                    _log.exception("review_loop: on_iteration callback failed")

            # Handle INPUT_REQUIRED: poll the existing review pane for a
            # follow-up verdict.  The user interacts with Claude directly
            # in the review pane — no TUI interaction required.
            if verdict == VERDICT_INPUT_REQUIRED:
                _log.info("review_loop: INPUT_REQUIRED — polling for follow-up verdict")
                state.input_required = True
                # Reset UI notification flag so repeated INPUT_REQUIRED
                # rounds within the same loop still show a notification.
                state._ui_notified_input = False

                follow_up_output = _wait_for_follow_up_verdict(pr_data, state)
                state.input_required = False

                if follow_up_output is None:
                    # Pane died or stop requested
                    if state.stop_requested:
                        break
                    state.latest_verdict = VERDICT_KILLED
                    state.latest_output = "Review pane disappeared during INPUT_REQUIRED wait"
                    break

                verdict = parse_review_verdict(follow_up_output)
                # Treat repeated INPUT_REQUIRED as NEEDS_WORK
                if verdict == VERDICT_INPUT_REQUIRED:
                    verdict = VERDICT_NEEDS_WORK
                state.latest_verdict = verdict
                state.latest_output = follow_up_output

                # Record the follow-up as part of this iteration's history
                state.history[-1] = ReviewIteration(
                    iteration=state.iteration,
                    verdict=verdict,
                    output=follow_up_output,
                )
                _log.info("review_loop: follow-up verdict=%s", verdict)

                if on_iteration:
                    try:
                        on_iteration(state)
                    except Exception:
                        _log.exception("review_loop: on_iteration callback failed")

            if should_stop(verdict):
                _log.info("review_loop: stopping — verdict=%s", verdict)
                break

            if state.stop_requested:
                break

        if state.iteration >= max_iterations:
            _log.warning("review_loop: hit max iterations (%d)", max_iterations)

    finally:
        state.running = False

    return state


def start_review_loop_background(
    state: ReviewLoopState,
    pm_root: str,
    pr_data: dict,
    transcript_dir: str,
    on_iteration: Callable[[ReviewLoopState], None] | None = None,
    on_complete: Callable[[ReviewLoopState], None] | None = None,
    max_iterations: int = 10,
) -> threading.Thread:
    """Start the review loop in a background thread.

    ``transcript_dir`` is required (hook-driven verdict polling needs a
    per-iteration JSONL symlink).  Returns the thread so the caller can
    join it if needed.
    """
    def _run():
        run_review_loop_sync(
            state, pm_root, pr_data, transcript_dir,
            on_iteration=on_iteration,
            max_iterations=max_iterations,
        )
        if on_complete:
            try:
                on_complete(state)
            except Exception:
                _log.exception("review_loop: on_complete callback failed")

    thread = threading.Thread(target=_run, daemon=True, name=f"review-loop-{state.pr_id}")
    thread.start()
    return thread
