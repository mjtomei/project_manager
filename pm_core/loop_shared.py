"""Shared helpers for review_loop and monitor_loop.

Extracts functions that were duplicated between the two loop engines
so both can import from a single source.
"""

import re
import time
from typing import Callable

from pm_core.paths import configure_logger

_log = configure_logger("pm.loop_shared")


def get_pm_session() -> str | None:
    """Get the pm tmux session name."""
    from pm_core.cli.helpers import _get_current_pm_session
    return _get_current_pm_session()


def find_claude_pane(session: str, window_name: str) -> str | None:
    """Find the Claude pane ID in a window (first pane)."""
    from pm_core import tmux as tmux_mod
    win = tmux_mod.find_window_by_name(session, window_name)
    if not win:
        return None
    panes = tmux_mod.get_pane_indices(session, win["index"])
    if panes:
        return panes[0][0]
    return None


def sleep_checking_pane(pane_id: str, seconds: float,
                        tick: float = 1.0,
                        stop_check: Callable[[], bool] | None = None) -> bool:
    """Sleep for *seconds*, checking pane liveness every tick.

    Returns True if the pane is still alive, False if it disappeared.
    If *stop_check* is provided, it is called each tick; if it returns
    True the sleep terminates early (returns True — pane still alive).
    """
    from pm_core import tmux as tmux_mod

    elapsed = 0.0
    while elapsed < seconds:
        time.sleep(tick)
        elapsed += tick
        if stop_check and stop_check():
            return True  # pane alive but stopping
        if not tmux_mod.pane_exists(pane_id):
            return False
    return True


# ---------------------------------------------------------------------------
# Verdict detection helpers (shared by review_loop and monitor_loop)
# ---------------------------------------------------------------------------

# Only scan the tail of captured pane content for verdicts.  The prompt
# itself contains verdict keywords as instructions — scanning the full
# scrollback would match those immediately.
VERDICT_TAIL_LINES = 30

# Consecutive stable polls required before accepting verdict
STABILITY_POLLS = 2


def match_verdict(line: str, verdicts: tuple[str, ...]) -> str | None:
    """Match a verdict keyword when it is the entire line content.

    After stripping markdown formatting (``*``, backticks) and whitespace,
    the line must be exactly one of the verdict keywords.  This rejects all
    incidental mentions — PR titles, table rows, prompt instructions,
    tmux-wrapped fragments, etc.

    Args:
        line: Raw line to check.
        verdicts: Tuple of valid verdict keyword strings.
    """
    cleaned = re.sub(r'[*`]', '', line).strip()
    for verdict in verdicts:
        if cleaned == verdict:
            return verdict
    return None


def build_prompt_verdict_lines(prompt_text: str,
                               keywords: tuple[str, ...]) -> set[str]:
    """Build a set of normalized prompt lines that contain verdict keywords.

    Used to distinguish prompt instructions (which mention verdict keywords)
    from Claude's actual verdict output.  Strips markdown formatting so
    terminal-wrapped lines can be matched against prompt lines.

    Args:
        prompt_text: The full prompt text.
        keywords: Tuple of verdict keyword strings to search for.
    """
    result = set()
    for line in prompt_text.splitlines():
        normalized = line.replace("*", "").replace("`", "").strip()
        if normalized and any(v in normalized for v in keywords):
            result.add(normalized)
    return result


def is_prompt_line(stripped_line: str, prompt_verdict_lines: set[str],
                   keywords: tuple[str, ...]) -> bool:
    """Check if a verdict-containing line comes from the prompt, not Claude.

    Strategy: extract the "context" around the verdict keyword (the
    non-keyword text).  If the context also appears in a prompt line,
    this line is from the prompt.  A standalone keyword like "PASS" or
    "READY" has no context and is always treated as a real verdict.

    Args:
        stripped_line: The line to check (already stripped of outer whitespace).
        prompt_verdict_lines: Set of normalized prompt lines containing verdicts.
        keywords: Tuple of verdict keyword strings to strip when extracting context.
    """
    context = stripped_line
    for keyword in keywords:
        context = context.replace(keyword, "")
    context = context.strip(" \t\u2014-:().").strip()

    if len(context) > 3:
        stripped_clean = stripped_line.replace("*", "").replace("`", "").strip()
        for pvl in prompt_verdict_lines:
            if context in pvl or stripped_clean in pvl or pvl in stripped_clean:
                return True
    return False


def extract_verdict_from_content(
    content: str,
    verdicts: tuple[str, ...],
    keywords: tuple[str, ...],
    prompt_text: str = "",
    exclude_verdicts: set[str] | None = None,
    log_prefix: str = "loop_shared",
) -> str | None:
    """Check if the tail of captured pane content contains a verdict keyword.

    Lines that match the prompt text are skipped — the prompt itself contains
    verdict keywords as instructions.  Only verdicts from Claude's actual
    output are returned.

    Args:
        content: Captured pane content to scan.
        verdicts: Tuple of valid verdict keyword strings.
        keywords: Tuple of keyword strings for prompt line filtering.
        prompt_text: Prompt text for filtering out prompt lines.
        exclude_verdicts: Optional set of verdict strings to skip.
        log_prefix: Prefix for log messages.
    """
    lines = content.strip().splitlines()
    tail = lines[-VERDICT_TAIL_LINES:] if len(lines) > VERDICT_TAIL_LINES else lines

    prompt_verdict_lines = build_prompt_verdict_lines(prompt_text, keywords) if prompt_text else set()
    _log.info("%s: extract_verdict: %d total lines, %d tail lines, %d prompt verdict lines, prompt_text=%d chars",
              log_prefix, len(lines), len(tail), len(prompt_verdict_lines), len(prompt_text))

    for line in reversed(tail):
        stripped = line.strip().strip("*").strip()
        verdict = match_verdict(stripped, verdicts)

        if verdict:
            if exclude_verdicts and verdict in exclude_verdicts:
                continue
            if prompt_verdict_lines and is_prompt_line(stripped, prompt_verdict_lines, keywords):
                _log.info("%s: SKIPPED prompt verdict line: [%s] (verdict=%s)", log_prefix, stripped[:100], verdict)
                continue
            _log.info("%s: ACCEPTED verdict line: [%s] (verdict=%s)", log_prefix, stripped[:100], verdict)
            return verdict
    return None


# ---------------------------------------------------------------------------
# Polling helpers (shared by review_loop and monitor_loop)
# ---------------------------------------------------------------------------

def poll_for_verdict(
    pane_id: str,
    verdicts: tuple[str, ...],
    keywords: tuple[str, ...],
    prompt_text: str = "",
    exclude_verdicts: set[str] | None = None,
    grace_period: float = 0,
    poll_interval: float = 5,
    tick_interval: float = 1,
    stop_check: Callable[[], bool] | None = None,
    log_prefix: str = "loop_shared",
) -> str | None:
    """Poll a pane until a verdict is stable.

    Returns the captured pane content when a verdict is found and stable
    for ``STABILITY_POLLS`` consecutive polls.
    Returns None if the pane disappears or stop is requested.

    Args:
        pane_id: tmux pane to poll.
        verdicts: Tuple of valid verdict keyword strings.
        keywords: Tuple of keyword strings for prompt line filtering.
        prompt_text: Prompt text for filtering out prompt lines.
        exclude_verdicts: Optional set of verdict strings to skip.
        grace_period: Seconds to wait before accepting verdicts.
        poll_interval: Seconds between verdict checks.
        tick_interval: Seconds between liveness/stop checks.
        stop_check: Optional callable; if it returns True, polling stops.
        log_prefix: Prefix for log messages.
    """
    from pm_core import tmux as tmux_mod

    last_verdict = None
    stable_count = 0
    poll_start = time.monotonic()

    while True:
        if stop_check and stop_check():
            return None

        if not tmux_mod.pane_exists(pane_id):
            _log.warning("%s: pane %s disappeared", log_prefix, pane_id)
            return None

        in_grace = grace_period > 0 and (time.monotonic() - poll_start) < grace_period

        content = tmux_mod.capture_pane(pane_id, full_scrollback=True)
        if not content.strip():
            if not sleep_checking_pane(pane_id, poll_interval, tick=tick_interval,
                                       stop_check=stop_check):
                return None
            continue

        if in_grace:
            if not sleep_checking_pane(pane_id, poll_interval, tick=tick_interval,
                                       stop_check=stop_check):
                return None
            continue

        verdict = extract_verdict_from_content(
            content, verdicts=verdicts, keywords=keywords,
            prompt_text=prompt_text, exclude_verdicts=exclude_verdicts,
            log_prefix=log_prefix,
        )
        if verdict:
            if verdict == last_verdict:
                stable_count += 1
            else:
                last_verdict = verdict
                stable_count = 1

            if stable_count >= STABILITY_POLLS:
                _log.info("%s: verdict %s stable for %d polls",
                          log_prefix, verdict, stable_count)
                return content
        else:
            last_verdict = None
            stable_count = 0

        if not sleep_checking_pane(pane_id, poll_interval, tick=tick_interval,
                                   stop_check=stop_check):
            return None


def wait_for_follow_up_verdict(
    session: str,
    window_name: str,
    verdicts: tuple[str, ...],
    keywords: tuple[str, ...],
    prompt_text: str = "",
    exclude_verdicts: set[str] | None = None,
    poll_interval: float = 5,
    tick_interval: float = 1,
    stop_check: Callable[[], bool] | None = None,
    log_prefix: str = "loop_shared",
) -> str | None:
    """Poll an existing pane for a follow-up verdict (after INPUT_REQUIRED).

    The user interacts with Claude in the pane; this function polls until
    Claude emits a follow-up verdict.

    Returns the captured pane content when a verdict is found, or None if
    the pane disappeared or stop was requested.

    Args:
        session: tmux session name.
        window_name: tmux window name containing the pane.
        verdicts: Tuple of valid verdict keyword strings.
        keywords: Tuple of keyword strings for prompt line filtering.
        prompt_text: Prompt text for filtering out prompt lines.
        exclude_verdicts: Optional set of verdict strings to skip.
        poll_interval: Seconds between verdict checks.
        tick_interval: Seconds between liveness/stop checks.
        stop_check: Optional callable; if it returns True, polling stops.
        log_prefix: Prefix for log messages.
    """
    from pm_core import tmux as tmux_mod

    last_verdict: str | None = None
    stable_count = 0

    while not (stop_check and stop_check()):
        pane_id = find_claude_pane(session, window_name)
        if not pane_id:
            _log.warning("%s: pane gone during follow-up wait", log_prefix)
            return None

        content = tmux_mod.capture_pane(pane_id, full_scrollback=True)
        if content.strip():
            verdict = extract_verdict_from_content(
                content, verdicts=verdicts, keywords=keywords,
                prompt_text=prompt_text, exclude_verdicts=exclude_verdicts,
                log_prefix=log_prefix,
            )
            if verdict:
                if verdict == last_verdict:
                    stable_count += 1
                else:
                    last_verdict = verdict
                    stable_count = 1
                if stable_count >= STABILITY_POLLS:
                    _log.info("%s: follow-up verdict %s stable",
                              log_prefix, verdict)
                    return content
            else:
                last_verdict = None
                stable_count = 0

        for _ in range(int(poll_interval / tick_interval)):
            if stop_check and stop_check():
                return None
            time.sleep(tick_interval)

    return None
