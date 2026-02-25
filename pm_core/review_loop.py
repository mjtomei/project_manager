"""Review loop: repeatedly run Claude review until PASS.

The loop launches a visible tmux review window (via ``pm pr review
--fresh --review-loop``) and polls the Claude pane with
``tmux capture-pane`` to detect the verdict.

Verdicts:
  PASS                 — No changes needed, code is ready to merge.
  PASS_WITH_SUGGESTIONS — Only non-blocking suggestions remain.
  NEEDS_WORK           — Blocking issues found.
  INPUT_REQUIRED       — Human-guided testing needed before sign-off.

The loop stops on PASS always. By default it also stops on
PASS_WITH_SUGGESTIONS; set `stop_on_suggestions=False` to keep going
until full PASS.

When INPUT_REQUIRED is detected, the loop marks the PR as paused and
polls the existing review pane for a follow-up verdict.  The user
interacts directly with Claude in the review pane (e.g. performing
the requested tests and reporting results).  Once Claude emits a new
verdict (PASS, PASS_WITH_SUGGESTIONS, or NEEDS_WORK), the loop picks
it up automatically and resumes normal flow — no TUI interaction
required.
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

_log = configure_logger("pm.review_loop")

# Review verdicts in order of severity
VERDICT_PASS = "PASS"
VERDICT_PASS_WITH_SUGGESTIONS = "PASS_WITH_SUGGESTIONS"
VERDICT_NEEDS_WORK = "NEEDS_WORK"
VERDICT_INPUT_REQUIRED = "INPUT_REQUIRED"
VERDICT_KILLED = "KILLED"

ALL_VERDICTS = (VERDICT_PASS, VERDICT_PASS_WITH_SUGGESTIONS, VERDICT_NEEDS_WORK,
                VERDICT_INPUT_REQUIRED)

# Keywords used for prompt line filtering (all verdict keywords)
_REVIEW_KEYWORDS = ("PASS_WITH_SUGGESTIONS", "INPUT_REQUIRED", "NEEDS_WORK", "PASS")

# How often to check pane content for a verdict (seconds)
_POLL_INTERVAL = 5
# How often to check pane liveness / stop_requested between content polls (seconds)
_TICK_INTERVAL = 1
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
    stop_on_suggestions: bool = True
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


def _regenerate_prompt_text(pm_root: str, pr_id: str, iteration: int = 0,
                            loop_id: str = "") -> str:
    """Regenerate the review prompt text for verdict filtering.

    Used to distinguish prompt instructions (which mention verdict keywords)
    from Claude's actual verdict output.  Returns an empty string on failure.
    """
    try:
        from pathlib import Path
        from pm_core import store
        from pm_core.prompt_gen import generate_review_prompt
        data = store.load(Path(pm_root))
        return generate_review_prompt(
            data, pr_id, review_loop=True,
            review_iteration=iteration, review_loop_id=loop_id,
        )
    except Exception as exc:
        _log.warning("review_loop: could not regenerate prompt text for filtering: %s", exc)
        return ""


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
    _log.info("review_loop: launching review window: %s", cmd)
    subprocess.run(cmd, cwd=pm_root, capture_output=True, text=True, timeout=30)


def _find_claude_pane(session: str, window_name: str) -> str | None:
    """Find the Claude pane ID in the review window (first pane)."""
    return _find_claude_pane_shared(session, window_name)


def _poll_for_verdict(pane_id: str, prompt_text: str = "",
                      exclude_verdicts: set[str] | None = None,
                      grace_period: float = 0) -> str | None:
    """Poll a pane with capture-pane until verdict is stable.

    Delegates to the shared ``poll_for_verdict`` in ``loop_shared``.
    Does NOT check ``stop_requested`` — that is handled between iterations
    by ``run_review_loop_sync`` so the current iteration runs to completion.
    """
    return _poll_for_verdict_shared(
        pane_id, verdicts=ALL_VERDICTS, keywords=_REVIEW_KEYWORDS,
        prompt_text=prompt_text, exclude_verdicts=exclude_verdicts,
        grace_period=grace_period, poll_interval=_POLL_INTERVAL,
        tick_interval=_TICK_INTERVAL, log_prefix="review_loop",
    )


def _extract_verdict_from_content(content: str, prompt_text: str = "",
                                   exclude_verdicts: set[str] | None = None) -> str | None:
    """Check if the tail of captured pane content contains a verdict keyword."""
    return extract_verdict_from_content(
        content, verdicts=ALL_VERDICTS, keywords=_REVIEW_KEYWORDS,
        prompt_text=prompt_text, exclude_verdicts=exclude_verdicts,
        log_prefix="review_loop",
    )


def _get_pm_session() -> str | None:
    """Get the pm tmux session name."""
    return _get_pm_session_shared()


class PaneKilledError(Exception):
    """Raised when the review pane disappears before producing a verdict."""


def _run_claude_review(pr_id: str, pm_root: str, pr_data: dict,
                       iteration: int = 0, loop_id: str = "",
                       transcript: str | None = None) -> str:
    """Launch a review window and poll capture-pane for the verdict.

    Returns the captured pane content containing the verdict.
    Raises PaneKilledError if the pane disappears before a verdict.
    Raises RuntimeError for setup failures (no tmux session, window
    failed to launch).
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

    # Regenerate the prompt text so we can filter out prompt lines from
    # verdict detection.  The prompt contains verdict keywords as
    # instructions which would otherwise cause false matches.
    prompt_text = _regenerate_prompt_text(pm_root, pr_id, iteration, loop_id)

    _log.info("review_loop: prompt_text for filtering: %d chars", len(prompt_text))

    # Wait briefly for the window to appear
    time.sleep(2)

    pane_id = _find_claude_pane(session, window_name)
    if not pane_id:
        raise RuntimeError(f"Review window '{window_name}' not found after launch")

    _log.info("review_loop: polling pane %s in window %s", pane_id, window_name)
    content = _poll_for_verdict(pane_id, prompt_text=prompt_text,
                                 grace_period=_VERDICT_GRACE_PERIOD)
    if content is None:
        raise PaneKilledError(f"Review pane disappeared (window: {window_name})")
    return content


def _wait_for_follow_up_verdict(pr_data: dict, prompt_text: str,
                                 state: ReviewLoopState) -> str | None:
    """Poll the existing review pane for a non-INPUT_REQUIRED verdict.

    Delegates to the shared ``wait_for_follow_up_verdict`` in ``loop_shared``.
    """
    session = _get_pm_session()
    if not session:
        _log.warning("review_loop: no pm session for follow-up polling")
        return None

    window_name = _compute_review_window_name(pr_data)
    return _wait_for_follow_up_shared(
        session, window_name, verdicts=ALL_VERDICTS, keywords=_REVIEW_KEYWORDS,
        prompt_text=prompt_text, exclude_verdicts={VERDICT_INPUT_REQUIRED},
        poll_interval=_POLL_INTERVAL, tick_interval=_TICK_INTERVAL,
        stop_check=lambda: state.stop_requested, log_prefix="review_loop",
    )


def should_stop(verdict: str, stop_on_suggestions: bool = True) -> bool:
    """Determine if the loop should stop based on the verdict."""
    if verdict == VERDICT_PASS:
        return True
    if verdict == VERDICT_PASS_WITH_SUGGESTIONS and stop_on_suggestions:
        return True
    return False


def run_review_loop_sync(
    state: ReviewLoopState,
    pm_root: str,
    pr_data: dict,
    on_iteration: Callable[[ReviewLoopState], None] | None = None,
    max_iterations: int = 10,
    transcript_dir: str | None = None,
) -> ReviewLoopState:
    """Run the review loop synchronously (intended for a background thread).

    Args:
        state: Mutable state object — the caller can read it to track progress.
        pm_root: Path to the pm project root (for running ``pm pr review``).
        pr_data: The PR dict from project data.
        on_iteration: Optional callback fired after each iteration completes.
        max_iterations: Safety cap on number of iterations.
        transcript_dir: Directory for transcript symlinks (optional).

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

            # Compute per-iteration transcript path
            iter_transcript = None
            if transcript_dir:
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

                follow_up_prompt = _regenerate_prompt_text(
                    pm_root, state.pr_id, state.iteration, state.loop_id,
                )
                follow_up_output = _wait_for_follow_up_verdict(
                    pr_data, follow_up_prompt, state,
                )
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
    state: ReviewLoopState,
    pm_root: str,
    pr_data: dict,
    on_iteration: Callable[[ReviewLoopState], None] | None = None,
    on_complete: Callable[[ReviewLoopState], None] | None = None,
    max_iterations: int = 10,
    transcript_dir: str | None = None,
) -> threading.Thread:
    """Start the review loop in a background thread.

    Returns the thread so the caller can join it if needed.
    """
    def _run():
        run_review_loop_sync(
            state, pm_root, pr_data,
            on_iteration=on_iteration,
            max_iterations=max_iterations,
            transcript_dir=transcript_dir,
        )
        if on_complete:
            try:
                on_complete(state)
            except Exception:
                _log.exception("review_loop: on_complete callback failed")

    thread = threading.Thread(target=_run, daemon=True, name=f"review-loop-{state.pr_id}")
    thread.start()
    return thread
