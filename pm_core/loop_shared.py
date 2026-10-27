"""Shared helpers for review_loop, qa_loop, and watcher_loop.

Extracts functions that were duplicated between the loop engines
so all can import from a single source.
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


# ---------------------------------------------------------------------------
# Verdict detection helpers (shared by review_loop and watcher_loop)
# ---------------------------------------------------------------------------

# Only scan the tail of captured pane content for verdicts / markers.
# The prompt itself contains keywords as instructions — scanning the full
# scrollback would match those immediately.
VERDICT_TAIL_LINES = 30



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



def extract_between_markers(content: str, start_marker: str,
                            end_marker: str,
                            require_end: bool = True) -> str | None:
    """Extract text between the last START/END marker pair in *content*.

    Scans from the bottom so that prompt-template examples (which appear
    earlier in the content) are skipped in favour of the real output.

    When *require_end* is False and the end marker is missing, extracts
    everything after the last start marker to the end of content.

    Returns None if no valid start marker is found.
    """
    lines = content.strip().splitlines()
    last_start = -1
    last_end = -1
    for i, line in enumerate(lines):
        # Strip markdown formatting AND leading non-alphanumeric characters
        # (e.g. the '●' bullet Claude Code sometimes prefixes to output lines).
        cleaned = re.sub(r'[*`]', '', line).strip()
        cleaned = re.sub(r'^[^\w]+', '', cleaned).strip()
        if cleaned == start_marker:
            last_start = i
        elif cleaned == end_marker:
            last_end = i
    if last_start < 0:
        return None
    if last_end > last_start:
        end = last_end
    elif not require_end:
        end = len(lines)
    else:
        return None
    extracted = "\n".join(
        line.strip() for line in lines[last_start + 1:end]
    ).strip()
    return extracted if extracted else None


# ---------------------------------------------------------------------------
# Polling helpers (shared by review_loop and watcher_loop)
# ---------------------------------------------------------------------------

def poll_for_verdict(
    pane_id: str,
    transcript_path: str,
    verdicts: tuple[str, ...],
    *,
    grace_period: float = 0,
    wait_timeout: float = 15,
    stop_check: Callable[[], bool] | None = None,
    log_prefix: str = "loop_shared",
    workdir: str | None = None,
) -> str | None:
    """Block until Claude signals idle, then extract a verdict from the
    JSONL transcript.

    Returns the assistant text of the turn that carried the verdict, or
    ``None`` when the pane disappears / ``stop_check`` fires.  The text
    comes from the verdict turn rather than the transcript tail so a
    ``/loop`` wakeup or Monitor postscript after the verdict cannot hide
    markers from downstream parsers (e.g. :func:`extract_between_markers`).

    Hook-driven only — requires *transcript_path* so we can recover the
    Claude ``session_id`` via the symlink target and read the assistant
    output from the JSONL.  No pane-capture fallback for verdicts; the
    pane is only captured, until the first idle event, to catch a session
    stuck at the workspace-trust prompt (*workdir* is the host workdir the
    session was launched for).  Raises
    :class:`~pm_core.claude_launcher.WorkspaceTrustBlocked` when it stays
    there past the grace period.
    """
    from pm_core import tmux as tmux_mod
    from pm_core import hook_events
    from pm_core.claude_launcher import (
        WorkspacePromptWatch, WorkspaceTrustBlocked, session_id_from_transcript,
    )
    from pm_core.verdict_transcript import find_verdict_turn

    session_id = session_id_from_transcript(transcript_path)
    if not session_id:
        raise RuntimeError(
            f"poll_for_verdict: could not recover session_id from "
            f"transcript={transcript_path!r}"
        )

    _log.info("%s: poll_for_verdict (hook+jsonl) — pane_id=%s, "
              "transcript=%s, session_id=%s, verdicts=%s, grace=%.0fs",
              log_prefix, pane_id, transcript_path, session_id, verdicts,
              grace_period)

    poll_start = time.monotonic()
    hook_baseline = time.time()
    trust_watch: WorkspacePromptWatch | None = WorkspacePromptWatch(
        pane_id, workdir, transcript_path=transcript_path)

    while True:
        if stop_check and stop_check():
            return None

        if not tmux_mod.pane_exists(pane_id):
            _log.warning("%s: pane %s disappeared", log_prefix, pane_id)
            return None

        if trust_watch is not None:
            blocked = trust_watch.check()
            if blocked:
                _log.warning("%s: %s", log_prefix, blocked)
                raise WorkspaceTrustBlocked(blocked)

        # Stop fires every turn, not only at session exit — listening to
        # it caused false "session gone" returns.  pane_exists is the
        # authoritative session-gone signal; we only consume idle_prompt.
        ev = hook_events.wait_for_event(
            session_id,
            event_types={"idle_prompt"},
            timeout=wait_timeout,
            newer_than=hook_baseline,
            stop_check=stop_check,
        )
        if stop_check and stop_check():
            return None
        if ev is None:
            continue

        # An idle turn means the session is past any startup dialog.
        trust_watch = None
        hook_baseline = float(ev.get("timestamp") or hook_baseline)
        if grace_period > 0 and (time.monotonic() - poll_start) < grace_period:
            continue

        hit = find_verdict_turn(transcript_path, verdicts)
        if hit:
            _log.info("%s: hook-driven verdict %s (session_id=%s)",
                      log_prefix, hit.verdict, session_id)
            # Return the verdict turn's text, not the tail: a /loop wakeup
            # or Monitor postscript after the verdict must not hide the
            # output downstream parsers (markers, reasons) need.
            return hit.text or hit.verdict


def wait_for_follow_up_verdict(
    session: str,
    window_name: str,
    transcript_path: str,
    verdicts: tuple[str, ...],
    *,
    wait_timeout: float = 15,
    stop_check: Callable[[], bool] | None = None,
    log_prefix: str = "loop_shared",
) -> str | None:
    """Block for the next hook-driven idle on an existing pane and return
    the assistant text of the follow-up turn (or ``None``).

    Only a verdict emitted *after* this call counts as the follow-up: the
    task-scoped scan crosses non-task wakeups, so without that baseline a
    ``/loop`` tick or Monitor postscript arriving while the caller waits for
    a human answer would re-return the INPUT_REQUIRED / flagged verdict that
    prompted the call (pr-8efa789).

    Hook-driven only — requires *transcript_path*.
    """
    from pm_core import hook_events
    from pm_core.claude_launcher import session_id_from_transcript
    from pm_core.verdict_transcript import find_verdict_turn

    session_id = session_id_from_transcript(transcript_path)
    if not session_id:
        _log.warning("%s: could not recover session_id from transcript=%s",
                     log_prefix, transcript_path)
        return None

    hook_baseline = time.time()
    # Snapshot the verdict that prompted the call (if any) so a wakeup
    # postscript cannot re-deliver it as the follow-up.  The transcript only
    # grows, so a genuinely new verdict sits at a later line.
    baseline_hit = find_verdict_turn(transcript_path, verdicts)
    baseline_line = baseline_hit.line_index if baseline_hit else -1

    while not (stop_check and stop_check()):
        pane_id = find_claude_pane(session, window_name)
        if not pane_id:
            _log.warning("%s: pane gone during follow-up wait", log_prefix)
            return None

        ev = hook_events.wait_for_event(
            session_id,
            event_types={"idle_prompt"},
            timeout=wait_timeout,
            newer_than=hook_baseline,
            stop_check=stop_check,
        )
        if stop_check and stop_check():
            return None
        if ev is None:
            continue
        hook_baseline = float(ev.get("timestamp") or hook_baseline)

        hit = find_verdict_turn(transcript_path, verdicts)
        if hit and hit.line_index > baseline_line:
            _log.info("%s: hook-driven follow-up verdict %s",
                      log_prefix, hit.verdict)
            return hit.text or hit.verdict

    return None
