"""Review loop: repeatedly run Claude review until PASS.

The loop runs `claude -p` with a review prompt, parses the verdict, and
either stops or continues based on the result and configuration.

Verdicts:
  PASS                 — No changes needed, code is ready to merge.
  PASS_WITH_SUGGESTIONS — Only non-blocking suggestions remain.
  NEEDS_WORK           — Blocking issues found.

The loop stops on PASS always. By default it also stops on
PASS_WITH_SUGGESTIONS; set `stop_on_suggestions=False` to keep going
until full PASS.
"""

import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from pm_core.paths import configure_logger
from pm_core.claude_launcher import find_claude, _skip_permissions

_log = configure_logger("pm.review_loop")

# Review verdicts in order of severity
VERDICT_PASS = "PASS"
VERDICT_PASS_WITH_SUGGESTIONS = "PASS_WITH_SUGGESTIONS"
VERDICT_NEEDS_WORK = "NEEDS_WORK"

ALL_VERDICTS = (VERDICT_PASS, VERDICT_PASS_WITH_SUGGESTIONS, VERDICT_NEEDS_WORK)


@dataclass
class ReviewIteration:
    """Result of a single review iteration."""
    iteration: int
    verdict: str
    output: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


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
    stop_on_suggestions: bool = True


def parse_review_verdict(output: str) -> str:
    """Extract a review verdict from Claude output.

    Scans from the end of the output upward, looking for verdict keywords.
    Returns the most specific match found.
    """
    lines = output.strip().splitlines()
    # Scan from the end — the verdict is typically at the bottom
    for line in reversed(lines):
        stripped = line.strip().strip("*").strip()
        if "PASS_WITH_SUGGESTIONS" in stripped:
            return VERDICT_PASS_WITH_SUGGESTIONS
        if "NEEDS_WORK" in stripped:
            return VERDICT_NEEDS_WORK
        # Check for standalone PASS (not part of PASS_WITH_SUGGESTIONS)
        if "PASS" in stripped and "PASS_WITH_SUGGESTIONS" not in stripped:
            return VERDICT_PASS
    # If no clear verdict, assume needs work if there's output
    return VERDICT_NEEDS_WORK if output.strip() else VERDICT_PASS


def _run_claude_review(prompt: str, cwd: str) -> str:
    """Run a single `claude -p` review and return stdout."""
    claude = find_claude()
    if not claude:
        raise FileNotFoundError("claude CLI not found")

    cmd = [claude]
    if _skip_permissions():
        cmd.append("--dangerously-skip-permissions")
    cmd.extend(["-p", prompt])

    _log.info("review_loop: running claude -p (cwd=%s)", cwd)
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=600,
    )
    _log.info("review_loop: claude -p exit=%d stdout_len=%d",
              result.returncode, len(result.stdout))
    return result.stdout


def should_stop(verdict: str, stop_on_suggestions: bool = True) -> bool:
    """Determine if the loop should stop based on the verdict."""
    if verdict == VERDICT_PASS:
        return True
    if verdict == VERDICT_PASS_WITH_SUGGESTIONS and stop_on_suggestions:
        return True
    return False


def run_review_loop_sync(
    prompt: str,
    cwd: str,
    state: ReviewLoopState,
    on_iteration: Callable[[ReviewLoopState], None] | None = None,
    max_iterations: int = 10,
) -> ReviewLoopState:
    """Run the review loop synchronously (intended for a background thread).

    Args:
        prompt: The review prompt to pass to `claude -p`.
        cwd: Working directory for the review.
        state: Mutable state object — the caller can read it to track progress.
        on_iteration: Optional callback fired after each iteration completes.
        max_iterations: Safety cap on number of iterations.

    Returns:
        The final state.
    """
    state.running = True
    state.stop_requested = False

    try:
        while state.iteration < max_iterations:
            if state.stop_requested:
                _log.info("review_loop: stop requested after %d iterations", state.iteration)
                break

            state.iteration += 1
            _log.info("review_loop: iteration %d for %s", state.iteration, state.pr_id)

            try:
                output = _run_claude_review(prompt, cwd)
            except subprocess.TimeoutExpired:
                _log.warning("review_loop: claude -p timed out on iteration %d", state.iteration)
                state.latest_verdict = "TIMEOUT"
                state.latest_output = "Review timed out after 10 minutes."
                break
            except Exception as e:
                _log.exception("review_loop: claude -p failed on iteration %d", state.iteration)
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

            if should_stop(verdict, state.stop_on_suggestions):
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
    prompt: str,
    cwd: str,
    state: ReviewLoopState,
    on_iteration: Callable[[ReviewLoopState], None] | None = None,
    on_complete: Callable[[ReviewLoopState], None] | None = None,
    max_iterations: int = 10,
) -> threading.Thread:
    """Start the review loop in a background thread.

    Returns the thread so the caller can join it if needed.
    """
    def _run():
        run_review_loop_sync(
            prompt, cwd, state,
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
