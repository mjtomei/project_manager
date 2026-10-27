"""Shared helpers for review_loop, qa_loop, and watcher_loop.

Extracts functions that were duplicated between the loop engines
so all can import from a single source.

This module also hosts the shared *missing-output recovery* machinery used
by every verdict poller (review, watcher, QA planner / refiner / verifier /
finalize, and the QA scenario workers).  A session can end a turn without
the outcome its caller expects — Claude asks a clarifying question, hits a
provider connection loss, or completes the work but writes
``NEEDS_WORK — explanation`` instead of a standalone keyword.  Recovery:

  * bounds the wait (a configurable number of idle turns without an
    outcome, plus an optional wall-clock deadline),
  * asks the *same* session for its own standalone outcome (a completed
    result needing format repair) or to resume the same task after a
    connection loss, and
  * surfaces an explicit :class:`VerdictRecoveryExhausted` failure instead
    of blocking forever.

Recovery never supplies or infers a verdict, never replays completed work
or tests, and defers to a newer hook event (a provider-native retry or
queued input) instead of racing it.
"""

import re
import time
from dataclasses import dataclass
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


# Terminal verdict used when a session never produces an expected outcome
# even after bounded recovery.  Distinct from "ERROR" (launch/runtime
# failures) and "KILLED" (pane died) so the TUI and QA can name the failure.
VERDICT_NO_VERDICT = "NO_VERDICT"

# Recovery defaults (overridable via ~/.pm/settings/*).
DEFAULT_MAX_MISSING = 3             # recovery nudges per session
DEFAULT_SETTLE_SECONDS = 5.0        # wait for a newer idle before nudging
DEFAULT_RESPONSE_TIMEOUT = 3600.0   # nudge -> next idle deadline (0 = off)
# Consecutive "settle deferrals" tolerated before giving up.  A hook refresh
# (a session that keeps re-emitting idle_prompt for the *same* turn — e.g. a
# held-open FakeClaude) must not extend the settle window forever, or the
# poller would never nudge and never exhaust: the very hang this module
# exists to prevent.
DEFAULT_MAX_DEFERRALS = 10


# ---------------------------------------------------------------------------
# Recovery settings
# ---------------------------------------------------------------------------

def _setting_int(name: str, default: int) -> int:
    from pm_core.paths import get_global_setting_value
    raw = get_global_setting_value(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        _log.warning("ignoring invalid %s=%r (want an integer)", name, raw)
        return default


def _setting_float(name: str, default: float) -> float:
    from pm_core.paths import get_global_setting_value
    raw = get_global_setting_value(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        _log.warning("ignoring invalid %s=%r (want a number)", name, raw)
        return default


def recovery_max_attempts() -> int:
    """Recovery nudges allowed per session (``<= 0`` disables recovery)."""
    return _setting_int("verdict-recovery-max-attempts", DEFAULT_MAX_MISSING)


def recovery_settle_seconds() -> float:
    """Seconds to wait for a newer idle before sending a recovery nudge."""
    return max(0.0, _setting_float(
        "verdict-recovery-settle-seconds", DEFAULT_SETTLE_SECONDS))


def recovery_response_timeout() -> float:
    """Seconds from a nudge to the next idle before declaring exhaustion.

    ``<= 0`` disables the check (a session that keeps working emits no idle
    and is not considered missing output).
    """
    return _setting_float(
        "verdict-recovery-response-timeout", DEFAULT_RESPONSE_TIMEOUT)


# ---------------------------------------------------------------------------
# Recovery exception + message builders
# ---------------------------------------------------------------------------

class VerdictRecoveryExhausted(RuntimeError):
    """Raised when a session never produces an expected verdict/marker.

    Callers catch this and surface a terminal ``NO_VERDICT`` state (review /
    watcher), an ``INPUT_REQUIRED`` scenario/planner result (QA), or a
    verification failure — never a silent hang.
    """

    def __init__(self, message: str, *, attempts: int = 0,
                 last_output: str = "", reason: str = "no_verdict",
                 session_id: str = "", pane_id: str = "",
                 verdicts: tuple[str, ...] = ()):
        """*reason* is one of ``no_output``, ``no_verdict``,
        ``no_progress`` (a session that kept re-announcing the same turn),
        ``overall_timeout`` or ``no_response``."""
        super().__init__(message)
        self.attempts = attempts
        self.last_output = last_output
        self.reason = reason
        self.session_id = session_id
        self.pane_id = pane_id
        self.verdicts = verdicts


def _expected_outcomes(verdicts: tuple[str, ...]) -> str:
    return " / ".join(v for v in verdicts if v) or "the expected outcome"


# A turn that ended on a provider/transport error (rather than completing
# the task) must be *resumed*, not asked to re-emit an outcome.  Claude Code
# surfaces these as a short assistant line such as "API Error: Connection
# lost" / "Request failed: network error".  Match only line-leading forms so
# a genuine review discussing network-error handling is not misclassified.
_PROVIDER_ERROR_RE = re.compile(
    r"(?i)^\W*(?:api error|request failed|connection (?:lost|error|reset|"
    r"refused)|network error|socket hang up|econnreset|etimedout|"
    r"server (?:error|unavailable)|overloaded|"
    r"error\s*:\s*(?:socket hang up|connection (?:lost|reset|refused)|"
    r"network error|api error|econnreset|etimedout))\b"
)


def _looks_like_provider_error(text: str) -> bool:
    return any(_PROVIDER_ERROR_RE.match(line) for line in text.splitlines())


def build_outcome_request(verdicts: tuple[str, ...]) -> str:
    """Message asking only for the agent's own standalone outcome.

    Used when a turn *completed* but its output lacks a standalone verdict
    (e.g. ``NEEDS_WORK — explanation``).  It lists the allowed vocabulary
    but never supplies or infers a verdict, and it never asks the agent to
    redo work or replay tests.
    """
    outcomes = _expected_outcomes(verdicts)
    return (
        "Your last turn ended without a standalone outcome line. Re-emit "
        "only your own conclusion from the work already completed: exactly "
        f"one of {outcomes}, alone on its own line, with no other text on "
        "that line. Do not redo work, re-run tests, or restate evidence. If "
        "you have not finished, continue the task instead."
    )


def build_resume_request() -> str:
    """Message resuming the same task after a turn that produced no output.

    Covers provider connection loss and other empty turns.  It deliberately
    does *not* replay the original prompt (which risks duplicating completed
    work); the session still holds that prompt in its context.
    """
    return (
        "Your previous turn ended without any output (for example a "
        "provider connection loss). Resume the same task in this session "
        "from where you left off: keep partial edits, evidence and any "
        "queued input, and do not restart completed work or repeat "
        "completed tests. When the task is complete, emit your required "
        "outcome as instructed."
    )


def build_block_outcome_request(
    blocks: tuple[tuple[str, str], ...],
) -> str:
    """Outcome request for block-marker roles (planner, refiner).

    *blocks* is a sequence of ``(START, END)`` marker pairs.  The agent is
    asked to re-emit its own completed result wrapped in one of the blocks,
    or to continue if it has not finished.
    """
    rendered = " or ".join(f"{start} ... {end}" for start, end in blocks)
    return (
        "Your last turn ended without the required outcome block. Re-emit "
        "your own completed result from the work already done, wrapped in "
        f"{rendered} (each marker alone on its own line). Do not redo work, "
        "re-run tests, or restate evidence. If you have not finished, "
        "continue the task instead."
    )


def build_block_resume_request(
    blocks: tuple[tuple[str, str], ...],
) -> str:
    """Resume request for block-marker roles (planner, refiner).

    Like :func:`build_resume_request`, but names the blocks the role must
    emit when it finishes — a connection-loss resume for the planner or
    refiner otherwise leaves the agent guessing what "your required
    outcome" means.
    """
    rendered = " or ".join(f"{start} ... {end}" for start, end in blocks)
    return (
        "Your previous turn ended without any output (for example a "
        "provider connection loss). Resume the same task in this session "
        "from where you left off: keep partial edits, evidence and any "
        "queued input, and do not restart completed work or repeat "
        f"completed tests. When the task is complete, emit your own result "
        f"wrapped in {rendered} (each marker alone on its own line)."
    )


@dataclass
class RecoveryResult:
    """Outcome of one :meth:`MissingOutputRecovery.handle` call."""
    # "deferred" | "nudged" | "stopped" | "completed"
    status: str
    event: dict | None = None       # newer idle event when deferred


class MissingOutputRecovery:
    """Bounded recovery for one polling session.

    The poller calls :meth:`handle` once per idle turn that did **not**
    produce the expected outcome.  A newer idle event that lands during the
    settle window (a provider-native retry, a queued user message) defers
    the nudge and resets the attempt counter, so recovery never races a
    native one.  After *max_attempts* nudges, :class:`VerdictRecoveryExhausted`
    is raised.
    """

    def __init__(
        self,
        *,
        session_id: str,
        pane_id: str,
        verdicts: tuple[str, ...],
        send: Callable[[str], None],
        max_attempts: int = DEFAULT_MAX_MISSING,
        settle_seconds: float = DEFAULT_SETTLE_SECONDS,
        response_timeout: float | None = DEFAULT_RESPONSE_TIMEOUT,
        max_deferrals: int | None = None,
        resume_request: str | Callable[[], str] | None = None,
        outcome_request: str | Callable[[], str] | None = None,
        log_prefix: str = "loop_shared",
    ):
        self.session_id = session_id
        self.pane_id = pane_id
        self.verdicts = tuple(verdicts)
        self._send = send
        self.max_attempts = max(0, int(max_attempts))
        self.settle_seconds = max(0.0, float(settle_seconds))
        self.response_timeout = response_timeout
        self.max_deferrals = (DEFAULT_MAX_DEFERRALS if max_deferrals is None
                              else max(0, int(max_deferrals)))
        self._resume_request = resume_request
        self._outcome_request = outcome_request
        self.log_prefix = log_prefix
        self.attempts = 0
        self.deferrals = 0
        self.last_output = ""
        self.last_kind = ""
        self._last_nudge_ts: float | None = None
        # Latest assistant text observed by this tracker.  A newer idle
        # event whose turn text is unchanged is a hook *refresh*, not new
        # activity — it must not reset the recovery budget.
        self._seen_text: str | None = None

    @property
    def enabled(self) -> bool:
        return self.max_attempts > 0

    def reset(self) -> None:
        """Newer activity was seen — the session is making progress again."""
        self.attempts = 0
        self.deferrals = 0
        self._last_nudge_ts = None

    # -- classification -----------------------------------------------------

    def classify(self, transcript_path: str) -> str:
        """Return ``"no_output"`` or ``"no_verdict"`` for the latest turn.

        ``no_output`` (no assistant text at all, or a turn that ended on a
        provider/transport error) is treated as a possible connection loss
        and resumed; ``no_verdict`` means the agent completed a turn but did
        not emit a standalone outcome.
        """
        from pm_core.verdict_transcript import read_latest_assistant_text
        text = read_latest_assistant_text(transcript_path) or ""
        self.last_output = text
        if not text.strip():
            return "no_output"
        if _looks_like_provider_error(text):
            # The turn died on a transport/provider error — resume the same
            # task rather than demanding an outcome it never computed.
            return "no_output"
        return "no_verdict"

    # -- messages -----------------------------------------------------------

    def _message(self, kind: str) -> str:
        override = (self._resume_request if kind == "no_output"
                    else self._outcome_request)
        if override is None:
            if kind == "no_output":
                return build_resume_request()
            return build_outcome_request(self.verdicts)
        return override() if callable(override) else override

    # -- main entry point ---------------------------------------------------

    def handle(self, transcript_path: str, ev_ts: float, *,
               wait_for_newer: Callable[[float, float], dict | None]
               | None = None,
               stop_check: Callable[[], bool] | None = None,
               verdict_check: Callable[[], bool] | None = None
               ) -> RecoveryResult:
        """Handle one idle turn that produced no expected outcome.

        *wait_for_newer(timeout, newer_than)* may block up to the settle
        window looking for a newer idle event.  When omitted, a non-blocking
        hook read is used (for tick-based loops).

        A newer event whose transcript text actually changed is a genuine
        new turn (provider-native retry / queued input): it defers and
        resets the budget.  A newer event that re-announces the *same* turn
        (a hook refresh) is counted against *max_deferrals* instead, so a
        session that keeps refreshing cannot defer forever.

        *verdict_check* is re-evaluated immediately before a nudge.  The
        caller's first verdict scan runs when the idle hook fires, which can
        precede the transcript write (or a completed turn can land during
        the settle window), so a completed outcome must never be nudged: it
        returns ``RecoveryResult("completed")`` instead.

        Returns ``RecoveryResult("deferred", event)`` when a newer event
        landed (do not nudge; process that turn instead),
        ``RecoveryResult("stopped")`` when *stop_check* fired (the caller
        should return its "stopped" result),
        ``RecoveryResult("completed")`` when *verdict_check* now finds the
        expected outcome, or ``RecoveryResult("nudged")`` after sending a
        recovery request.  Raises :class:`VerdictRecoveryExhausted` once the
        budget runs out.
        """
        kind = self.classify(transcript_path)
        self.last_kind = kind
        text = self.last_output
        # Did the transcript advance since the previous recovery decision?
        # (The caller may have consumed a newer turn before calling us.)
        advanced = self._seen_text is not None and text != self._seen_text
        self._seen_text = text

        # Let a provider-native retry / queued input land before nudging.
        if self.settle_seconds > 0:
            if wait_for_newer is not None:
                newer = wait_for_newer(self.settle_seconds, ev_ts)
            else:
                newer = self._newer_event(ev_ts)
            if newer is not None:
                if not advanced:
                    # Re-read: the newer turn may have been written while we
                    # waited (a genuine turn) or not (a hook refresh).
                    from pm_core.verdict_transcript import (
                        read_latest_assistant_text,
                    )
                    after = read_latest_assistant_text(transcript_path) or ""
                    advanced = after != text
                    if advanced:
                        self._seen_text = after
                if advanced:
                    self.reset()
                    _log.info("%s: newer turn during settle — deferring "
                              "recovery (session %s)", self.log_prefix,
                              self.session_id)
                    return RecoveryResult("deferred", newer)
                # Same turn re-announced (hook refresh): no new output to
                # process, so this is a no-progress deferral.
                self.deferrals += 1
                if self.max_deferrals and self.deferrals > self.max_deferrals:
                    raise self.exhausted("no_progress")
                _log.debug("%s: idle hook refresh without new output "
                           "(deferral %d/%d, session %s)", self.log_prefix,
                           self.deferrals, self.max_deferrals,
                           self.session_id)
                return RecoveryResult("deferred", newer)

        if stop_check is not None and stop_check():
            # The caller asked us to stop (possibly while we waited for a
            # newer turn) — do not nudge a session that is being torn down.
            return RecoveryResult("stopped")

        # Never nudge a completed outcome.  The caller's verdict scan runs
        # when the idle hook fires, which can race the transcript write; the
        # turn may also have completed during the settle window.
        if verdict_check is not None and verdict_check():
            _log.info("%s: outcome landed during recovery settle — not "
                      "nudging (session %s)", self.log_prefix,
                      self.session_id)
            return RecoveryResult("completed")

        if self.attempts >= self.max_attempts:
            raise self.exhausted(kind)

        self.attempts += 1
        message = self._message(kind)
        _log.warning("%s: idle turn without outcome (%s) — recovery request "
                     "%d/%d (session %s)", self.log_prefix, kind,
                     self.attempts, self.max_attempts, self.session_id)
        try:
            self._send(message)
        except Exception:
            # A dead pane / closed stdin must not crash the loop: the
            # poller's next pane_exists check reports the real failure.
            _log.warning("%s: recovery request could not be delivered",
                         self.log_prefix, exc_info=True)
        self._last_nudge_ts = time.monotonic()
        return RecoveryResult("nudged")

    def check_response(self) -> None:
        """Raise when a recovery nudge has gone unanswered too long.

        Called by pollers when their event wait times out.  A session that
        is actively working emits no idle event, so the default timeout is
        generous and ``<= 0`` disables the check entirely.
        """
        if not self.response_timeout or self.response_timeout <= 0:
            return
        if self._last_nudge_ts is None:
            return
        if time.monotonic() - self._last_nudge_ts >= self.response_timeout:
            raise self.exhausted("no_response")

    def exhausted(self, reason: str) -> VerdictRecoveryExhausted:
        """Build the exhaustion error for *reason*."""
        if reason == "overall_timeout":
            detail = "the overall poll deadline elapsed"
        elif reason == "no_response":
            detail = (f"no new turn arrived within "
                      f"{float(self.response_timeout):.0f}s after recovery "
                      f"attempt {self.attempts}")
        elif reason == "no_output":
            detail = (f"the session idled {self.attempts} time(s) without any "
                      f"output; recovery attempts are exhausted")
        elif reason == "no_progress":
            detail = (f"the session re-announced its idle turn {self.deferrals} "
                      f"time(s) without producing new output or a standalone "
                      f"outcome; recovery made no progress")
        else:
            detail = (f"the session idled {self.attempts} time(s) without a "
                      f"standalone outcome; recovery attempts are exhausted")
        pane_note = (f"pane {self.pane_id}" if self.pane_id
                     else "the session's pane")
        return VerdictRecoveryExhausted(
            f"{self.log_prefix}: session {self.session_id} produced no "
            f"expected outcome ({_expected_outcomes(self.verdicts)}): "
            f"{detail}. {pane_note.capitalize()} was left open for "
            f"inspection.",
            attempts=self.attempts,
            last_output=self.last_output,
            reason=reason,
            session_id=self.session_id,
            pane_id=self.pane_id,
            verdicts=self.verdicts,
        )

    def _newer_event(self, ev_ts: float) -> dict | None:
        """Non-blocking read of a newer *turn boundary* for tick-based loops.

        Only ``idle_prompt`` counts, matching the blocking
        ``hook_events.wait_for_event(event_types={"idle_prompt"})`` path.
        The event file holds just the latest hook event, so a ``Stop`` /
        ``permission_prompt`` write for the same turn would otherwise look
        like a new turn: the tick loop would defer (and close its
        no-verdict episode) without nudging, and it only re-opens an
        episode on a fresh ``idle_prompt``.
        """
        from pm_core import hook_events
        ev = hook_events.read_event(self.session_id)
        if (ev and ev.get("event_type") == "idle_prompt"
                and float(ev.get("timestamp") or 0) > ev_ts):
            return ev
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
    max_missing: int | None = None,
    overall_timeout: float | None = None,
    response_timeout: float | None = None,
    resume_request: str | Callable[[], str] | None = None,
    outcome_request: str | Callable[[], str] | None = None,
    retry_prompt: str | Callable[[], str] | None = None,
    send: Callable[[str], None] | None = None,
) -> str | None:
    """Block until Claude signals idle, then extract a verdict from the
    JSONL transcript.

    Returns the assistant text from the latest turn when a verdict is
    found, or ``None`` when the pane disappears / ``stop_check`` fires.
    Callers can pass the returned string to downstream parsers (e.g.
    :func:`extract_between_markers`) or to
    :func:`pm_core.verdict_transcript.extract_verdict_from_transcript`
    for pure verdict detection.

    Hook-driven only — requires *transcript_path* so we can recover the
    Claude ``session_id`` via the symlink target and read the assistant
    output from the JSONL.  No pane-capture fallback for verdicts; the
    pane is only captured, until the first idle event, to catch a session
    stuck at the workspace-trust prompt (*workdir* is the host workdir the
    session was launched for).  Raises
    :class:`~pm_core.claude_launcher.WorkspaceTrustBlocked` when it stays
    there past the grace period.

    Missing-output recovery (bounded, see :class:`MissingOutputRecovery`):
    an idle turn without a matching verdict asks the same session for its
    own standalone outcome (or to resume after an empty/connection-loss
    turn) up to *max_missing* times, then raises
    :class:`VerdictRecoveryExhausted`.  ``max_missing=None`` reads the
    ``verdict-recovery-max-attempts`` setting (default 3); ``<= 0`` disables
    recovery (legacy unbounded behaviour).  *overall_timeout* optionally
    bounds the whole poll; *response_timeout* bounds the wait for the next
    idle after a nudge (``<= 0`` disables).  *retry_prompt* overrides the
    resume request with the caller's original prompt; *send* overrides how
    a recovery message reaches the session (default: tmux ``send-keys``).
    """
    from pm_core import tmux as tmux_mod
    from pm_core import hook_events
    from pm_core.claude_launcher import (
        WorkspacePromptWatch, WorkspaceTrustBlocked, session_id_from_transcript,
    )
    from pm_core.verdict_transcript import (
        extract_verdict_from_transcript,
        read_latest_assistant_text,
    )

    session_id = session_id_from_transcript(transcript_path)
    if not session_id:
        raise RuntimeError(
            f"poll_for_verdict: could not recover session_id from "
            f"transcript={transcript_path!r}"
        )

    if max_missing is None:
        max_missing = recovery_max_attempts()
    if response_timeout is None:
        response_timeout = recovery_response_timeout()

    if send is None:
        def _send_message(message: str) -> None:
            tmux_mod.send_keys(pane_id, message)
        send = _send_message

    recovery = MissingOutputRecovery(
        session_id=session_id,
        pane_id=pane_id,
        verdicts=verdicts,
        send=send,
        max_attempts=max_missing,
        settle_seconds=recovery_settle_seconds(),
        response_timeout=response_timeout,
        resume_request=retry_prompt or resume_request,
        outcome_request=outcome_request,
        log_prefix=log_prefix,
    )

    _log.info("%s: poll_for_verdict (hook+jsonl) — pane_id=%s, "
              "transcript=%s, session_id=%s, verdicts=%s, grace=%.0fs, "
              "max_missing=%d",
              log_prefix, pane_id, transcript_path, session_id, verdicts,
              grace_period, recovery.max_attempts)

    poll_start = time.monotonic()
    deadline = (poll_start + overall_timeout) if overall_timeout else None
    hook_baseline = time.time()
    trust_watch: WorkspacePromptWatch | None = WorkspacePromptWatch(
        pane_id, workdir, transcript_path=transcript_path)
    ev: dict | None = None

    def _wait_newer(timeout: float, newer_than: float) -> dict | None:
        return hook_events.wait_for_event(
            session_id,
            event_types={"idle_prompt"},
            timeout=timeout,
            newer_than=newer_than,
            stop_check=stop_check,
        )

    while True:
        if stop_check and stop_check():
            return None

        if deadline is not None and time.monotonic() >= deadline:
            raise recovery.exhausted("overall_timeout")

        if not tmux_mod.pane_exists(pane_id):
            _log.warning("%s: pane %s disappeared", log_prefix, pane_id)
            return None

        if trust_watch is not None:
            blocked = trust_watch.check()
            if blocked:
                _log.warning("%s: %s", log_prefix, blocked)
                raise WorkspaceTrustBlocked(blocked)

        if ev is None:
            timeout = wait_timeout
            if deadline is not None:
                timeout = max(0.0, min(timeout,
                                       deadline - time.monotonic()))
            # Stop fires every turn, not only at session exit — listening to
            # it caused false "session gone" returns.  pane_exists is the
            # authoritative session-gone signal; we only consume idle_prompt.
            ev = hook_events.wait_for_event(
                session_id,
                event_types={"idle_prompt"},
                timeout=timeout,
                newer_than=hook_baseline,
                stop_check=stop_check,
            )
            if stop_check and stop_check():
                return None
            if ev is None:
                recovery.check_response()
                continue

            # An idle turn means the session is past any startup dialog.
            trust_watch = None
            hook_baseline = float(ev.get("timestamp") or hook_baseline)
            if grace_period > 0 and (
                    time.monotonic() - poll_start) < grace_period:
                ev = None
                continue

        verdict = extract_verdict_from_transcript(transcript_path, verdicts)
        if verdict:
            _log.info("%s: hook-driven verdict %s (session_id=%s)",
                      log_prefix, verdict, session_id)
            return read_latest_assistant_text(transcript_path) or verdict

        if not recovery.enabled:
            # Legacy behaviour: keep waiting for a later idle turn.
            ev = None
            continue

        result = recovery.handle(
            transcript_path,
            float(ev.get("timestamp") or hook_baseline),
            wait_for_newer=_wait_newer,
            stop_check=stop_check,
            verdict_check=lambda: bool(
                extract_verdict_from_transcript(transcript_path, verdicts)),
        )
        if result.status == "stopped":
            # stop_check fired while we waited out the settle window; do not
            # nudge a session that is being torn down.
            return None
        if result.status == "completed":
            # The verdict was flushed after the idle hook fired (or landed
            # during the settle window): never nudge a completed outcome.
            verdict = extract_verdict_from_transcript(transcript_path, verdicts)
            if verdict:
                _log.info("%s: hook-driven verdict %s (session_id=%s)",
                          log_prefix, verdict, session_id)
                return read_latest_assistant_text(transcript_path) or verdict
            # The transcript changed between the two scans; wait for the
            # next idle turn rather than nudging.
            ev = None
            continue
        if result.status == "deferred" and result.event is not None:
            # Process the newer turn in this same iteration instead of
            # re-waiting for an event we already consumed.
            ev = result.event
            hook_baseline = float(ev.get("timestamp") or hook_baseline)
        else:
            ev = None


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

    Hook-driven only — requires *transcript_path*.

    This wait is an intentional human interaction after ``INPUT_REQUIRED``
    (the user works in the pane), so it is deliberately **not** bounded by
    missing-output recovery: a genuine ``INPUT_REQUIRED`` is not a failure
    to produce an expected verdict.
    """
    from pm_core import hook_events
    from pm_core.claude_launcher import session_id_from_transcript
    from pm_core.verdict_transcript import (
        extract_verdict_from_transcript,
        read_latest_assistant_text,
    )

    session_id = session_id_from_transcript(transcript_path)
    if not session_id:
        _log.warning("%s: could not recover session_id from transcript=%s",
                     log_prefix, transcript_path)
        return None

    hook_baseline = time.time()

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

        verdict = extract_verdict_from_transcript(transcript_path, verdicts)
        if verdict:
            _log.info("%s: hook-driven follow-up verdict %s", log_prefix, verdict)
            return read_latest_assistant_text(transcript_path) or verdict

    return None
