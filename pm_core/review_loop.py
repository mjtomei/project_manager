"""Review loop: repeatedly run Claude review until PASS.

The loop launches a visible tmux review window (via ``pm pr review
--fresh --review-loop``) and polls the Claude pane for a verdict via
Claude Code hook events + JSONL transcript.

Verdicts:
  PASS            — No changes needed, code is ready to merge.
  NEEDS_WORK      — Blocking issues found; loop iterates after fixes.
  INPUT_REQUIRED  — Human-guided testing needed before sign-off.

The loop stops on PASS.

When INPUT_REQUIRED is detected, the loop marks the PR as waiting and
polls the existing review pane for a follow-up verdict.  The user
interacts directly with Claude in the review pane (e.g. performing
the requested tests and reporting results).  Once the user answers, the
wait is resolved (``input_required`` clears) while Claude works on the
follow-up; once Claude emits a new verdict (PASS or NEEDS_WORK), the loop
picks it up automatically and resumes normal flow — no TUI interaction
required.  A follow-up that ends INPUT_REQUIRED again is a new question:
the loop waits again on the same pane.
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

# How often the INPUT_REQUIRED wait re-checks the transcript for the user's
# answer between idle hook events, so status clears promptly.
_FOLLOW_UP_POLL = 2.0


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
    # INPUT_REQUIRED: True while the review pane waits on the human — set
    # when the verdict lands, cleared once the user answers in the pane (the
    # follow-up is then Claude's work) or a new iteration takes over.
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
                      grace_period: float = 0,
                      workdir: str | None = None) -> str | None:
    """Poll a pane for a verdict via Claude Code hook events."""
    return _poll_for_verdict_shared(
        pane_id, transcript_path, verdicts=ALL_VERDICTS,
        grace_period=grace_period, log_prefix="review_loop",
        workdir=workdir,
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
                                 grace_period=_VERDICT_GRACE_PERIOD,
                                 workdir=pr_data.get("workdir"))
    if content is None:
        raise PaneKilledError(f"Review pane disappeared (window: {window_name})")
    return content


def _adopt_in_flight_review(state: ReviewLoopState, pr_data: dict,
                            transcript_dir: str | None) -> str | None:
    """Collect the verdict of an iteration that was in flight at a TUI restart.

    A resumed loop (breadcrumb restore) whose counter was bumped but has
    no history entry for that iteration still has a live review window
    running it.  Poll that pane instead of relaunching (``--fresh`` would
    kill it and start the next iteration).  Returns the verdict output,
    ``None`` when there is nothing to adopt (no window / transcript), and
    raises :class:`PaneKilledError` if the adopted pane dies first.
    """
    import os
    from pm_core import hook_events
    from pm_core.claude_launcher import session_id_from_transcript
    from pm_core.verdict_transcript import (
        extract_verdict_from_transcript,
        read_latest_assistant_text,
    )

    session = _get_pm_session()
    if not session or not transcript_dir:
        return None
    window_name = _compute_review_window_name(pr_data)
    pane_id = _find_claude_pane(session, window_name)
    transcript = _iteration_transcript(state, transcript_dir)
    if not pane_id or not os.path.lexists(transcript):
        return None
    session_id = session_id_from_transcript(transcript)
    if not session_id:
        return None

    _log.info("review_loop: adopting in-flight iteration %d for %s "
              "(pane %s, transcript=%s)", state.iteration, state.pr_id,
              pane_id, transcript)
    # The verdict may have landed between the breadcrumb write and now;
    # the poller only wakes on idle events newer than its start.
    ev = hook_events.read_event(session_id)
    if ev and ev.get("event_type") == "idle_prompt":
        verdict = extract_verdict_from_transcript(transcript, ALL_VERDICTS)
        if verdict:
            return read_latest_assistant_text(transcript) or verdict

    content = _poll_for_verdict(pane_id, transcript,
                                 workdir=pr_data.get("workdir"))
    if content is None:
        raise PaneKilledError(f"Review pane disappeared (window: {window_name})")
    return content


def _iteration_transcript(state: ReviewLoopState,
                          transcript_dir: str | None = None) -> str:
    tdir = transcript_dir or state._transcript_dir
    return f"{tdir}/review-{state.pr_id}-i{state.iteration}.jsonl"


def _adoptable_wait_transcript(state: ReviewLoopState, pr_data: dict,
                               transcript_dir: str | None) -> str | None:
    """Transcript of an INPUT_REQUIRED wait still live after a TUI restart.

    Returns None when the review pane or its transcript is gone — then
    nobody can answer that question any more.
    """
    import os
    session = _get_pm_session()
    if not session or not transcript_dir:
        return None
    if not _find_claude_pane(session, _compute_review_window_name(pr_data)):
        return None
    transcript = _iteration_transcript(state, transcript_dir)
    return transcript if os.path.lexists(transcript) else None


def _wait_for_follow_up_verdict(pr_data: dict, state: ReviewLoopState,
                                transcript: str | None = None) -> str | None:
    """Wait in the existing review pane for the follow-up to INPUT_REQUIRED.

    Returns the assistant text of the follow-up turn once an idle turn
    carries a verdict: PASS / NEEDS_WORK, or INPUT_REQUIRED asked *after*
    the user answered (a new question).  An idle event for the same,
    still-unanswered INPUT_REQUIRED turn is ignored.  Returns None when
    the pane disappears or a stop is requested.

    Keeps ``state.input_required`` in step with the pane: False once a
    human prompt lands in the transcript (Claude is working on the
    follow-up), True again if Claude goes idle after that answer without
    a verdict (it asked something in prose).
    """
    from pm_core import hook_events
    from pm_core.claude_launcher import session_id_from_transcript
    from pm_core.verdict_transcript import (
        HumanResponseWatch,
        extract_verdict_from_transcript,
        read_latest_assistant_text,
    )

    session = _get_pm_session()
    if not session:
        _log.warning("review_loop: no pm session for follow-up polling")
        return None
    if transcript is None:
        if not getattr(state, "_transcript_dir", None):
            _log.warning("review_loop: no transcript_dir on state; cannot wait for follow-up")
            return None
        transcript = _iteration_transcript(state)
    session_id = session_id_from_transcript(transcript)
    if not session_id:
        _log.warning("review_loop: could not recover session_id from transcript=%s",
                     transcript)
        return None

    window_name = _compute_review_window_name(pr_data)
    watch = HumanResponseWatch(transcript, VERDICT_INPUT_REQUIRED)
    state.input_required = watch.answered_at is None
    # Start from the current idle event, not from now: after a TUI restart
    # the answer and the follow-up verdict may both have landed in the gap,
    # and Claude won't idle again.  An idle older than the answer (e.g. the
    # question's own) is ignored below.
    hook_baseline = 0.0
    stop_check = lambda: state.stop_requested  # noqa: E731

    while not stop_check():
        if not _find_claude_pane(session, window_name):
            _log.warning("review_loop: pane gone during follow-up wait")
            return None
        ev = hook_events.wait_for_event(
            session_id, event_types={"idle_prompt"}, timeout=_FOLLOW_UP_POLL,
            newer_than=hook_baseline, stop_check=stop_check,
        )
        if stop_check():
            return None
        answered_at = watch.poll()
        if ev is None:
            if answered_at is not None and state.input_required:
                _log.info("review_loop: %s answered INPUT_REQUIRED — "
                          "follow-up running", state.pr_id)
                state.input_required = False
            continue
        idle_at = float(ev.get("timestamp") or 0) or time.time()
        hook_baseline = idle_at
        verdict = extract_verdict_from_transcript(transcript, ALL_VERDICTS)
        if verdict in (VERDICT_PASS, VERDICT_NEEDS_WORK):
            _log.info("review_loop: hook-driven follow-up verdict %s", verdict)
            return read_latest_assistant_text(transcript) or verdict
        if answered_at is None or idle_at < answered_at:
            # Still the unanswered question (or an idle from before the
            # answer while Claude now works on it).
            state.input_required = answered_at is None
            continue
        if verdict == VERDICT_INPUT_REQUIRED:
            _log.info("review_loop: follow-up asked INPUT_REQUIRED again")
            return read_latest_assistant_text(transcript) or verdict
        _log.info("review_loop: %s idle after the answer without a verdict — "
                  "waiting on the user again", state.pr_id)
        watch.rearm()
        state.input_required = True
        state._ui_notified_input = False
    return None


def _await_input_resolution(state: ReviewLoopState, pr_data: dict,
                            on_iteration: Callable[[ReviewLoopState], None] | None,
                            transcript: str | None = None) -> str | None:
    """Hold the loop on an INPUT_REQUIRED iteration until its follow-up
    verdict is PASS or NEEDS_WORK; returns it, or None (pane gone / stop).

    A follow-up that is INPUT_REQUIRED again is a new question for the
    user — record it and keep waiting on the same pane rather than
    relaunching (which would kill the pane and drop the question).
    """
    while True:
        state.input_required = True
        # Reset so each INPUT_REQUIRED round shows a notification.
        state._ui_notified_input = False
        follow_up_output = _wait_for_follow_up_verdict(pr_data, state, transcript)
        state.input_required = False
        if follow_up_output is None:
            return None

        verdict = parse_review_verdict(follow_up_output)
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

        if verdict != VERDICT_INPUT_REQUIRED:
            return verdict


def should_stop(verdict: str) -> bool:
    """Determine if the loop should stop based on the verdict."""
    return verdict == VERDICT_PASS


def run_review_loop_sync(
    state: ReviewLoopState,
    pm_root: str,
    pr_data: dict,
    transcript_dir: str,
    on_iteration: Callable[[ReviewLoopState], None] | None = None,
    max_iterations: int = 50,
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
    # A resumed loop's in-flight iteration was launched under the saved
    # transcript dir, which may differ from the caller's (manual runs).
    saved_transcript_dir = state._transcript_dir or transcript_dir
    # Stash transcript_dir on state so _on_complete_from_thread can finalize
    state._transcript_dir = transcript_dir
    state.running = True
    state.stop_requested = False

    last = state.history[-1] if state.history else None
    last_done = last.iteration if last else 0
    adopt = state.iteration > last_done
    # A restart during an INPUT_REQUIRED wait: the verdict is recorded but
    # its follow-up is still pending in the same review pane.
    adopt_wait = bool(last and last.iteration == state.iteration
                      and last.verdict == VERDICT_INPUT_REQUIRED)
    if not adopt_wait:
        # Whatever was restored, no human question is pending now.
        state.input_required = False

    try:
        while state.iteration < max_iterations or adopt or adopt_wait:
            if state.stop_requested:
                _log.info("review_loop: stop requested after %d iterations", state.iteration)
                break

            wait_transcript = None
            if adopt_wait:
                adopt_wait = False
                wait_transcript = _adoptable_wait_transcript(
                    state, pr_data, saved_transcript_dir)
                if wait_transcript is None:
                    _log.info("review_loop: INPUT_REQUIRED wait for %s "
                              "iteration %d has no live pane; continuing",
                              state.pr_id, state.iteration)
                    state.input_required = False
                    continue
                _log.info("review_loop: adopting INPUT_REQUIRED wait for %s "
                          "iteration %d (transcript=%s)", state.pr_id,
                          state.iteration, wait_transcript)
                verdict = VERDICT_INPUT_REQUIRED
            else:
                # A new or adopted in-flight iteration owns the work now.
                state.input_required = False
                try:
                    output = None
                    if adopt:
                        adopt = False
                        output = _adopt_in_flight_review(
                            state, pr_data, saved_transcript_dir)
                        if output is None:
                            # Nothing live to adopt — rerun the same iteration.
                            state.iteration -= 1
                    if output is None:
                        state.iteration += 1
                        _log.info("review_loop: iteration %d for %s", state.iteration, state.pr_id)
                        iter_transcript = f"{transcript_dir}/review-{state.pr_id}-i{state.iteration}.jsonl"
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
                verdict = _await_input_resolution(
                    state, pr_data, on_iteration, wait_transcript)
                if verdict is None:
                    # Pane died or stop requested
                    if state.stop_requested:
                        break
                    state.latest_verdict = VERDICT_KILLED
                    state.latest_output = "Review pane disappeared during INPUT_REQUIRED wait"
                    break

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
    max_iterations: int = 50,
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
