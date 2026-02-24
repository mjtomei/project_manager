"""Review loop: repeatedly run Claude review until PASS.

The loop launches a visible tmux review window (via ``pm pr review
--fresh --review-loop``) and polls the Claude pane with
``tmux capture-pane`` to detect the verdict.

Verdicts:
  PASS                 — No changes needed, code is ready to merge.
  PASS_WITH_SUGGESTIONS — Only non-blocking suggestions remain.
  NEEDS_WORK           — Blocking issues found.

The loop stops on PASS always. By default it also stops on
PASS_WITH_SUGGESTIONS; set `stop_on_suggestions=False` to keep going
until full PASS.
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

_log = configure_logger("pm.review_loop")

# Review verdicts in order of severity
VERDICT_PASS = "PASS"
VERDICT_PASS_WITH_SUGGESTIONS = "PASS_WITH_SUGGESTIONS"
VERDICT_NEEDS_WORK = "NEEDS_WORK"
VERDICT_KILLED = "KILLED"

ALL_VERDICTS = (VERDICT_PASS, VERDICT_PASS_WITH_SUGGESTIONS, VERDICT_NEEDS_WORK)

# Regex patterns for verdict detection.  Use lookahead/lookbehind instead of
# \b to avoid matching substrings like "PASSWORD" or "PASS" inside "[PASS/FAIL]".
# Check PASS_WITH_SUGGESTIONS before PASS since PASS is a prefix.
_VERDICT_PATTERNS = [
    (re.compile(r'(?<!\w)PASS_WITH_SUGGESTIONS(?!\w)'), VERDICT_PASS_WITH_SUGGESTIONS),
    (re.compile(r'(?<!\w)NEEDS_WORK(?!\w)'), VERDICT_NEEDS_WORK),
    (re.compile(r'(?<!\w)PASS(?!_WITH_SUGGESTIONS|/|\w)'), VERDICT_PASS),
]

# How often to check pane content for a verdict (seconds)
_POLL_INTERVAL = 5
# How often to check pane liveness / stop_requested between content polls (seconds)
_TICK_INTERVAL = 1
# Number of consecutive stable polls required before accepting verdict
_STABILITY_POLLS = 2


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
    _transcript_dir: str | None = None


def _match_verdict(line: str) -> str | None:
    """Match a verdict keyword in a line using word-boundary regex."""
    for pattern, verdict in _VERDICT_PATTERNS:
        if pattern.search(line):
            return verdict
    return None


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
    _log.info("review_loop: launching review window: %s", cmd)
    subprocess.run(cmd, cwd=pm_root, capture_output=True, text=True, timeout=30)


def _find_claude_pane(session: str, window_name: str) -> str | None:
    """Find the Claude pane ID in the review window (first pane)."""
    from pm_core import tmux as tmux_mod
    win = tmux_mod.find_window_by_name(session, window_name)
    if not win:
        return None
    panes = tmux_mod.get_pane_indices(session, win["index"])
    if panes:
        return panes[0][0]
    return None


def _sleep_checking_pane(pane_id: str, seconds: float) -> bool:
    """Sleep for *seconds*, checking pane liveness every tick.

    Returns True if the pane is still alive, False if it disappeared.
    """
    from pm_core import tmux as tmux_mod

    elapsed = 0.0
    while elapsed < seconds:
        time.sleep(_TICK_INTERVAL)
        elapsed += _TICK_INTERVAL
        if not tmux_mod.pane_exists(pane_id):
            return False
    return True


def _poll_for_verdict(pane_id: str, prompt_text: str = "") -> str | None:
    """Poll a pane with capture-pane until verdict is stable.

    Returns the captured pane content when a verdict is found and stable
    for ``_STABILITY_POLLS`` consecutive polls.
    Returns None if the pane disappears (user closed window, Claude crashed).

    Does NOT check ``stop_requested`` — that is handled between iterations
    by ``run_review_loop_sync`` so the current iteration runs to completion.
    """
    from pm_core import tmux as tmux_mod

    last_verdict = None
    stable_count = 0

    while True:
        if not tmux_mod.pane_exists(pane_id):
            _log.warning("review_loop: pane %s disappeared", pane_id)
            return None

        content = tmux_mod.capture_pane(pane_id, full_scrollback=True)
        if not content.strip():
            if not _sleep_checking_pane(pane_id, _POLL_INTERVAL):
                _log.warning("review_loop: pane %s gone during sleep", pane_id)
                return None
            continue

        verdict = _extract_verdict_from_content(content, prompt_text)
        if verdict:
            if verdict == last_verdict:
                stable_count += 1
            else:
                last_verdict = verdict
                stable_count = 1

            if stable_count >= _STABILITY_POLLS:
                _log.info("review_loop: verdict %s stable for %d polls", verdict, stable_count)
                return content
        else:
            last_verdict = None
            stable_count = 0

        if not _sleep_checking_pane(pane_id, _POLL_INTERVAL):
            _log.warning("review_loop: pane %s gone during sleep", pane_id)
            return None


# Only scan the tail of captured pane content for verdicts.  The prompt
# itself contains verdict keywords as instructions — scanning the full
# scrollback would match those immediately.  30 lines is enough to catch
# Claude's verdict output without reaching back into the prompt.
_VERDICT_TAIL_LINES = 30


def _build_prompt_verdict_lines(prompt_text: str) -> set[str]:
    """Build a set of normalized prompt lines that contain verdict keywords.

    Used to distinguish prompt instructions (which mention verdict keywords)
    from Claude's actual verdict output.  Strips markdown formatting so
    terminal-wrapped lines can be matched against prompt lines.
    """
    result = set()
    for line in prompt_text.splitlines():
        normalized = line.replace("*", "").replace("`", "").strip()
        if normalized and any(v in normalized for v in ("PASS", "NEEDS_WORK")):
            result.add(normalized)
    return result


def _is_prompt_line(stripped_line: str, prompt_verdict_lines: set[str]) -> bool:
    """Check if a verdict-containing line comes from the prompt, not Claude.

    Strategy: extract the "context" around the verdict keyword (the
    non-keyword text).  If the context also appears in a prompt line,
    this line is from the prompt.  A standalone keyword like "PASS" or
    "NEEDS_WORK" has no context and is always treated as a real verdict.
    """
    # Extract context — text around the verdict keyword
    context = stripped_line
    for keyword in ("PASS_WITH_SUGGESTIONS", "NEEDS_WORK", "PASS"):
        context = context.replace(keyword, "")
    context = context.strip(" \t—-:().").strip()

    # If there's meaningful context (more than just punctuation/whitespace),
    # check if it appears in any prompt verdict line.
    if len(context) > 3:
        # Also strip markdown from the pane line for matching
        stripped_clean = stripped_line.replace("*", "").replace("`", "").strip()
        for pvl in prompt_verdict_lines:
            if context in pvl or stripped_clean in pvl or pvl in stripped_clean:
                return True

    # No meaningful context — standalone keyword = real verdict
    return False


def _extract_verdict_from_content(content: str, prompt_text: str = "") -> str | None:
    """Check if the tail of captured pane content contains a verdict keyword.

    Lines that match the prompt text are skipped — the prompt itself contains
    verdict keywords as instructions.  Only verdicts from Claude's actual
    output are returned.
    """
    lines = content.strip().splitlines()
    tail = lines[-_VERDICT_TAIL_LINES:] if len(lines) > _VERDICT_TAIL_LINES else lines

    prompt_verdict_lines = _build_prompt_verdict_lines(prompt_text) if prompt_text else set()
    _log.info("review_loop: extract_verdict: %d total lines, %d tail lines, %d prompt verdict lines, prompt_text=%d chars",
              len(lines), len(tail), len(prompt_verdict_lines), len(prompt_text))

    for line in reversed(tail):
        stripped = line.strip().strip("*").strip()
        verdict = _match_verdict(stripped)

        if verdict:
            if prompt_verdict_lines and _is_prompt_line(stripped, prompt_verdict_lines):
                _log.info("review_loop: SKIPPED prompt verdict line: [%s] (verdict=%s)", stripped[:100], verdict)
                continue
            _log.info("review_loop: ACCEPTED verdict line: [%s] (verdict=%s)", stripped[:100], verdict)
            return verdict
    return None


def _get_pm_session() -> str | None:
    """Get the pm tmux session name."""
    from pm_core.cli.helpers import _get_current_pm_session
    return _get_current_pm_session()


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

    # Generate the prompt text so we can filter out prompt lines from
    # verdict detection.  The prompt contains verdict keywords as
    # instructions which would otherwise cause false matches.
    # We load project data from pm_root and regenerate the same prompt
    # that was sent to Claude, so this adapts to any prompt changes.
    prompt_text = ""
    try:
        from pathlib import Path
        from pm_core import store
        from pm_core.prompt_gen import generate_review_prompt
        data = store.load(Path(pm_root))
        prompt_text = generate_review_prompt(
            data, pr_id, review_loop=True,
            review_iteration=iteration, review_loop_id=loop_id,
        )
    except Exception as exc:
        _log.warning("review_loop: could not generate prompt text for filtering: %s", exc)

    _log.info("review_loop: prompt_text for filtering: %d chars", len(prompt_text))

    # Wait briefly for the window to appear
    time.sleep(2)

    pane_id = _find_claude_pane(session, window_name)
    if not pane_id:
        raise RuntimeError(f"Review window '{window_name}' not found after launch")

    _log.info("review_loop: polling pane %s in window %s", pane_id, window_name)
    content = _poll_for_verdict(pane_id, prompt_text=prompt_text)
    if content is None:
        raise PaneKilledError(f"Review pane disappeared (window: {window_name})")
    return content


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
