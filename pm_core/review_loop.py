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

import os
import re
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
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
# Loop outcomes that are NOT agent verdicts.  A failed launch must never be
# reported as PASS/NEEDS_WORK: exhaustion leaves an explicit retryable
# failure instead.
VERDICT_LAUNCH_FAILED = "LAUNCH_FAILED"
VERDICT_HOLD = "HOLD"
VERDICT_CLOSED = "CLOSED"
VERDICT_ERROR = "ERROR"

ALL_VERDICTS = (VERDICT_PASS, VERDICT_NEEDS_WORK, VERDICT_INPUT_REQUIRED)

# Minimum seconds after poll start before accepting verdicts.
# Claude reviews take minutes; verdicts found in the first few seconds are
# almost certainly false positives from prompt text shown in the pane.
_VERDICT_GRACE_PERIOD = 20

# --- Failed-launch retry ---------------------------------------------------
# A review iteration launch that fails before producing a transcript (e.g.
# the old window was removed and container setup then failed) is retried a
# bounded number of times with exponential backoff.  The budget is per
# iteration episode and is persisted on ReviewLoopState so a merge-restart
# resume continues it instead of restarting it.
REVIEW_LAUNCH_MAX_ATTEMPTS = 3
REVIEW_LAUNCH_BACKOFF_BASE = 5.0     # seconds before retry 1
REVIEW_LAUNCH_BACKOFF_MAX = 60.0     # cap for the exponential backoff
REVIEW_LAUNCH_REARM_SECONDS = 60.0   # auto-start cooldown after exhaustion
REVIEW_LAUNCH_CLAIM_TTL = 180.0      # cross-driver launch lease TTL
REVIEW_LAUNCH_CLAIM_WAIT = 15.0      # bounded wait for another owner to go
_LAUNCH_TIMEOUT = 120                # `pm pr review` child timeout
_WINDOW_WAIT = 2.0                   # wait for the tmux window to appear
_LEASE_REFRESH_SECONDS = 30.0        # keepalive while polling a review
_DISCOVERY_GRACE = 2.0               # wait for a starting pane's session id
_ARTIFACT_DIRNAME = "launch-artifacts"


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


class ReviewLaunchError(RuntimeError):
    """An authorized review iteration launch failed before a verdict.

    ``retryable`` distinguishes a transient setup/teardown failure (retry)
    from an environment/auth/prompt problem (stop and surface it).  The
    complete child output lives in *artifact*; ``str(exc)`` is the concise
    UI error.
    """

    def __init__(self, message: str, *, returncode: int | None = None,
                 stderr: str = "", stdout: str = "",
                 artifact: str | None = None, retryable: bool = True,
                 reason: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout
        self.artifact = artifact
        self.retryable = retryable
        self.reason = reason


class ReviewHoldError(RuntimeError):
    """The review pane is held at a permission/auth/trust prompt.

    Not retryable: the launch itself succeeded, and a retry would only sit
    at the same prompt again.  A human must clear the hold.
    """


class ReviewClosedError(RuntimeError):
    """The PR merged/closed while its review launch was being retried."""


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
    _ui_notified_retry: int = 0
    _transcript_dir: str | None = None
    # INPUT_REQUIRED: set to True while polling for follow-up verdict
    input_required: bool = False
    # Failed-launch retry episode (persisted in the breadcrumb).
    retry_iteration: int = 0
    launch_attempts: int = 0
    next_retry_at: float = 0.0
    last_launch_error: str = ""
    last_launch_artifact: str | None = None
    launch_retryable: bool = False
    retry_episodes: int = 0
    retry_ready_at: float = 0.0
    # Last iteration's session, so a retry can tell the historical window
    # from a live attempt.
    last_session_id: str = ""
    # True once *this* loop has launched the current iteration.  Only then
    # may pre-retry rediscovery adopt a transcript/verdict it finds: before
    # that, any existing transcript belongs to an earlier loop run.
    iteration_attempted: bool = False
    # Session id of the iteration's transcript symlink *before* this loop
    # first attempted the iteration.  The transcript dir outlives a loop,
    # so after a failed launch that symlink can still point at an earlier
    # run's iteration N; adopting its verdict would fabricate one.  Only a
    # session id different from this one can be this loop's own attempt.
    stale_session_id: str = ""


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


def _as_text(value) -> str:
    """Decode a subprocess capture that may be bytes (TimeoutExpired)."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def _concise_launch_detail(stderr: str, stdout: str) -> str:
    """The shortest actionable line of a failed launch's output."""
    text = (stderr or stdout or "").strip()
    if not text:
        return "no output from the launch command"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    detail = lines[-1] if lines else text.strip()
    if len(detail) > 300:
        detail = detail[:297] + "..."
    return detail


def _write_launch_artifact(*, transcript: str | None, pr_id: str,
                           iteration: int, loop_id: str, attempt: int,
                           cmd: list[str], returncode: int | None,
                           stdout: str, stderr: str,
                           workdir: str | None = None,
                           note: str = "") -> str | None:
    """Persist a failed launch attempt's complete output.

    Lives next to the iteration transcript so it travels with the loop's
    run dir.  The full (untruncated) stderr is the actionable artifact; the
    failed attempt's prompt file is copied too when it still exists (a
    container-setup failure skips the command's trailing ``rm -f``).
    """
    if not transcript:
        return None
    try:
        adir = Path(transcript).parent / _ARTIFACT_DIRNAME
        adir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        base = f"review-{pr_id}-i{iteration}-attempt{attempt}-{stamp}"
        path = adir / f"{base}.log"
        parts = [
            f"timestamp: {datetime.now().isoformat()}",
            f"pr: {pr_id}",
            f"iteration: {iteration}",
            f"loop_id: {loop_id}",
            f"attempt: {attempt}",
            f"returncode: {returncode}",
            f"cmd: {cmd}",
        ]
        if note:
            parts.append(f"note: {note}")
        sid = None
        try:
            from pm_core.claude_launcher import session_id_from_transcript
            sid = session_id_from_transcript(transcript)
        except Exception:
            sid = None
        if sid:
            parts.append(f"session_id: {sid}")
        if workdir and sid:
            prompt_file = Path(workdir) / "pm" / "prompts" / f"pm_prompt_{sid}.txt"
            if prompt_file.exists():
                try:
                    prompt_copy = adir / f"{base}.prompt.txt"
                    prompt_copy.write_text(
                        prompt_file.read_text(encoding="utf-8", errors="replace"),
                        encoding="utf-8")
                    parts.append(f"prompt: {prompt_file}")
                    parts.append(f"prompt_copy: {prompt_copy}")
                except OSError:
                    parts.append(f"prompt: {prompt_file} (copy failed)")
        parts.append("")
        parts.append(f"--- stderr ({len(stderr)} bytes) ---")
        parts.append(stderr)
        parts.append("")
        parts.append(f"--- stdout ({len(stdout)} bytes) ---")
        parts.append(stdout)
        path.write_text("\n".join(parts), encoding="utf-8")
        return str(path)
    except OSError as e:
        _log.warning("review_loop: could not write launch artifact: %s", e)
        return None


def _launch_review_window(pr_id: str, pm_root: str, iteration: int = 0,
                          loop_id: str = "",
                          transcript: str | None = None,
                          attempt: int = 1,
                          workdir: str | None = None) -> list[str]:
    """Launch a review window via ``pm pr review --fresh --review-loop``.

    Returns the command that was run (for the failure artifact).  Raises
    :class:`ReviewLaunchError` on failure, retaining the child's complete
    output in an artifact and raising a concise message.
    """
    cmd = [sys.executable, "-m", "pm_core.wrapper",
           "pr", "review", "--fresh", "--review-loop",
           "--review-iteration", str(iteration)]
    if loop_id:
        cmd.extend(["--review-loop-id", loop_id])
    if transcript:
        cmd.extend(["--transcript", transcript])
    cmd.append(pr_id)
    _log.info("relauncher: pr=%s iteration=%s loop_id=%s attempt=%s cmd=%s",
              pr_id, iteration, loop_id, attempt, cmd)
    t0 = time.monotonic()
    try:
        result = subprocess.run(cmd, cwd=pm_root, capture_output=True,
                                text=True, timeout=_LAUNCH_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        stderr = _as_text(getattr(e, "stderr", ""))
        stdout = _as_text(getattr(e, "stdout", ""))
        artifact = _write_launch_artifact(
            transcript=transcript, pr_id=pr_id, iteration=iteration,
            loop_id=loop_id, attempt=attempt, cmd=cmd, returncode=None,
            stdout=stdout, stderr=stderr, workdir=workdir,
            note=f"launch timed out after {_LAUNCH_TIMEOUT}s")
        detail = _concise_launch_detail(stderr, stdout)
        msg = (f"Review window launch timed out after {_LAUNCH_TIMEOUT}s: "
               f"{detail}")
        if artifact:
            msg += f" (artifact: {artifact})"
        _log.error("review_loop: %s", msg)
        raise ReviewLaunchError(msg, returncode=None, stderr=stderr,
                                stdout=stdout, artifact=artifact,
                                retryable=True, reason="timeout") from e
    elapsed = time.monotonic() - t0
    if result.returncode != 0:
        stderr = _as_text(result.stderr).strip()
        stdout = _as_text(result.stdout).strip()
        _log.error("review_loop: launch failed (rc=%d) stderr=%s stdout=%s",
                   result.returncode, stderr[:1000], stdout[:500])
        artifact = _write_launch_artifact(
            transcript=transcript, pr_id=pr_id, iteration=iteration,
            loop_id=loop_id, attempt=attempt, cmd=cmd,
            returncode=result.returncode, stdout=stdout, stderr=stderr,
            workdir=workdir)
        detail = _concise_launch_detail(stderr, stdout)
        msg = f"Review window launch failed (rc={result.returncode}): {detail}"
        if artifact:
            msg += f" (artifact: {artifact})"
        # Consider both streams: a child can report the real error on
        # stdout while stderr carries only warnings.
        reason = ("auth" if _looks_like_auth_failure(f"{stderr}\n{stdout}")
                  else "launch")
        raise ReviewLaunchError(
            msg, returncode=result.returncode, stderr=stderr, stdout=stdout,
            artifact=artifact, retryable=(reason != "auth"), reason=reason)
    _log.info("relauncher: pr=%s rc=%d elapsed=%.2fs",
              pr_id, result.returncode, elapsed)
    return cmd


# Auth/trust failures are not retryable.  Deliberately excludes generic
# filesystem/socket errors like "permission denied": a container teardown or
# mount that fails that way is exactly the transient launch failure this
# retry exists to recover, and treating it as an auth hold would strand the
# target again.  A bare "401"/"403" is likewise not enough: any 3-digit token
# in arbitrary child stderr (a pid, a port, an id) would match, and a
# misclassified transient failure is a stranded target.  The HTTP codes only
# count with auth/HTTP context around them.
_AUTH_FAILURE_RE = re.compile(
    r"unauthori[sz]ed|not logged in|authentication failed|invalid api key|"
    r"\bforbidden\b|"
    r"\b(?:http(?:/\d(?:\.\d)?)?|api|auth|authentication|status(?:\s+code)?|"
    r"response)[^\n]{0,20}?\b(?:401|403)\b|"
    r"\b(?:401|403)\b\s*(?:unauthorized|forbidden)\b|"
    r"workspace trust|trust prompt",
    re.IGNORECASE)


def _looks_like_auth_failure(text: str) -> bool:
    """Whether a launch failure is an auth/trust hold rather than transient."""
    return bool(_AUTH_FAILURE_RE.search(text or ""))


def _find_claude_pane(session: str, window_name: str) -> str | None:
    """Find the Claude pane ID in the review window (first pane)."""
    return _find_claude_pane_shared(session, window_name)


def _find_review_claude_pane(session: str, window_name: str,
                             workdir: str | None = None) -> str | None:
    """Find the review window's Claude pane (not its diff shell).

    The shared first-pane helper can return the diff pane; prefer the pane
    whose start command carries a ``--session-id`` (host launch) or is a
    container ``exec`` (the Claude pane).  Falls back to the shared helper
    so mocked callers/tests keep working.
    """
    from pm_core import tmux as tmux_mod
    try:
        from pm_core.claude_launcher import pane_transcript_path
    except Exception:  # pragma: no cover - import cycle safety
        pane_transcript_path = None

    win = None
    try:
        win = tmux_mod.find_window_by_name(session, window_name)
    except Exception:
        win = None
    if win and pane_transcript_path is not None:
        try:
            panes = tmux_mod.get_pane_indices(session, win["index"])
        except Exception:
            panes = []
        for pane_id, _idx in panes:
            try:
                if pane_transcript_path(pane_id, workdir):
                    return pane_id
            except Exception:
                continue
        if panes:
            return panes[0][0]
    return _find_claude_pane(session, window_name)


def _poll_for_verdict(pane_id: str, transcript_path: str,
                      grace_period: float = 0,
                      workdir: str | None = None,
                      stop_check: Callable[[], bool] | None = None) -> str | None:
    """Poll a pane for a verdict via Claude Code hook events."""
    return _poll_for_verdict_shared(
        pane_id, transcript_path, verdicts=ALL_VERDICTS,
        grace_period=grace_period, log_prefix="review_loop",
        workdir=workdir, stop_check=stop_check,
    )


def _get_pm_session() -> str | None:
    """Get the pm tmux session name."""
    return _get_pm_session_shared()


class PaneKilledError(Exception):
    """Raised when the review pane disappears before producing a verdict."""


def _verdict_output_if_present(transcript: str | None) -> str | None:
    """The verdict output already present in *transcript*, or None."""
    if not transcript:
        return None
    try:
        from pm_core.verdict_transcript import (
            extract_verdict_from_transcript, read_latest_assistant_text,
        )
        verdict = extract_verdict_from_transcript(transcript, ALL_VERDICTS)
        if verdict:
            return read_latest_assistant_text(transcript) or verdict
    except Exception:
        _log.debug("review_loop: verdict read from %s failed", transcript,
                   exc_info=True)
    return None


def _transcript_session_id(transcript: str | None) -> str | None:
    """Session id of an existing transcript symlink, or None."""
    if not transcript or not os.path.lexists(transcript):
        return None
    try:
        from pm_core.claude_launcher import session_id_from_transcript
        return session_id_from_transcript(transcript)
    except Exception:
        return None


def _landed_verdict(transcript: str | None) -> str | None:
    """The verdict already recorded for an *idle* pane's transcript, or None.

    The poller only wakes on idle events newer than its own start, so a
    verdict that landed between discovery and the poll would otherwise be
    waited on forever (there is no further idle event to wake it).  Only an
    idle session counts: a still-running review's latest assistant turn is
    not a verdict.
    """
    session_id = _transcript_session_id(transcript)
    if not session_id:
        return None
    try:
        from pm_core import hook_events
        ev = hook_events.read_event(session_id)
    except Exception:
        _log.debug("review_loop: hook event read failed for %s",
                   transcript, exc_info=True)
        return None
    if not ev or ev.get("event_type") != "idle_prompt":
        return None
    return _verdict_output_if_present(transcript)


@dataclass
class AttemptDiscovery:
    """What rediscovery found for an iteration before (re)launching."""
    kind: str  # verdict | adopt | other_owner | pending | launch
    output: str | None = None
    pane_id: str | None = None
    transcript: str | None = None
    reason: str = ""
    owner: str = ""
    # Session id of the transcript/verdict this discovery read.  The caller
    # records it as the iteration's session so the *next* iteration treats a
    # still-live pane running it as historical (replaced, not adopted again).
    session_id: str = ""


def _lease_owner(state: ReviewLoopState) -> str:
    return f"loop:{state.loop_id}"


def review_loop_owns_launch(pr_id: str) -> str:
    """Owner of a live *native loop* launch lease for *pr_id*, or "".

    Other drivers (``pm pr auto-sequence``) call this before launching a
    review iteration: a live loop lease means the loop owns that launch
    (including its bounded retries), so a second launch would duplicate or
    kill it.
    """
    try:
        from pm_core import runtime_state as _rs
        lease = _rs.get_action_lease(pr_id, "review-loop",
                                     REVIEW_LAUNCH_CLAIM_TTL)
    except Exception:
        return ""
    owner = (lease or {}).get("owner") or ""
    return owner if owner.startswith("loop:") else ""


def _other_loop_owner(state: ReviewLoopState) -> str:
    """The owner of a live launch lease held by a *different* loop, or ""."""
    try:
        from pm_core import runtime_state as _rs
        lease = _rs.get_action_lease(state.pr_id, "review-loop",
                                     REVIEW_LAUNCH_CLAIM_TTL)
    except Exception:
        return ""
    owner = (lease or {}).get("owner") or ""
    if owner.startswith("loop:") and owner != _lease_owner(state):
        return owner
    return ""


def _is_historical_session(state: ReviewLoopState, transcript_dir: str,
                           iteration: int, session_id: str | None) -> bool:
    """Whether *session_id* belongs to an already-finished iteration."""
    if not session_id:
        return False
    if getattr(state, "last_session_id", "") == session_id:
        return True
    if getattr(state, "stale_session_id", "") == session_id:
        # The symlink that was already there when this loop first attempted
        # the iteration: an earlier run's session, never this attempt.
        return True
    try:
        from pm_core.claude_launcher import session_id_from_transcript
        pattern = re.compile(
            rf"^review-{re.escape(state.pr_id)}-i(\d+)\.jsonl$")
        for p in Path(transcript_dir).glob(f"review-{state.pr_id}-i*.jsonl"):
            m = pattern.match(p.name)
            if not m:
                continue
            if int(m.group(1)) < iteration \
                    and session_id_from_transcript(p) == session_id:
                return True
    except Exception:
        _log.debug("review_loop: historical-session scan failed", exc_info=True)
    return False


def _discover_iteration(state: ReviewLoopState, pr_data: dict,
                        transcript_dir: str, iteration: int,
                        *, allow_recovery: bool = True) -> AttemptDiscovery:
    """Rediscover this iteration's live attempt before launching again.

    Looks for an already-landed verdict, a live pane/transcript that is
    this attempt (possibly recovered) or another driver's review, another
    native loop's lease, and the historical window that a fresh launch is
    meant to replace.  Never launches anything itself.

    ``allow_recovery`` must be False for the *first* attempt of an
    iteration this loop has not launched yet: the transcript dir is shared
    across loops (``manual-<token>`` lives for the whole TUI session), so
    an existing ``review-<pr>-i<N>.jsonl`` symlink may be a previous run's
    iteration N.  Adopting its verdict would fabricate a verdict for a
    review that never ran.  The same reasoning applies *after* a failed
    attempt: the symlink is only this attempt's when its session id is not
    the one that was already there when the episode started
    (``state.stale_session_id``) — a launch that fails before the child
    writes the symlink leaves the older one in place.
    """
    pr_id = state.pr_id
    workdir = pr_data.get("workdir")
    our_transcript = f"{transcript_dir}/review-{pr_id}-i{iteration}.jsonl"
    our_sid = None
    if allow_recovery:
        our_sid = _transcript_session_id(our_transcript)
        if our_sid and our_sid == getattr(state, "stale_session_id", ""):
            our_sid = None
    if our_sid:
        output = _verdict_output_if_present(our_transcript)
        if output:
            return AttemptDiscovery("verdict", output=output,
                                    session_id=our_sid)

    other = _other_loop_owner(state)
    session = _get_pm_session()
    if not session:
        return AttemptDiscovery("launch")

    window_name = _compute_review_window_name(pr_data)
    pane_id = _find_review_claude_pane(session, window_name, workdir)
    if not pane_id:
        if other:
            return AttemptDiscovery("other_owner", owner=other)
        return AttemptDiscovery("launch")

    pane_transcript = None
    pane_sid = None
    try:
        from pm_core.claude_launcher import (
            pane_transcript_path, session_id_from_transcript,
        )
        pt = pane_transcript_path(pane_id, workdir)
        if pt:
            pane_transcript = str(pt)
            pane_sid = session_id_from_transcript(pt)
    except Exception:
        _log.debug("review_loop: pane transcript discovery failed",
                   exc_info=True)

    if our_sid:
        if pane_sid == our_sid:
            # Our failed attempt's session is alive: adopt it.
            return AttemptDiscovery("adopt", pane_id=pane_id,
                                    transcript=our_transcript,
                                    session_id=our_sid)
        if pane_sid:
            # A different session is live in the window.  If another loop
            # owns it, stand down; otherwise another driver launched this
            # review — adopt its verdict rather than kill it.
            if other:
                return AttemptDiscovery("other_owner", owner=other,
                                        pane_id=pane_id,
                                        transcript=pane_transcript)
            if _is_historical_session(state, transcript_dir, iteration,
                                      pane_sid):
                # A failed launch can leave the *previous* iteration's window
                # live (e.g. its removal failed) after the child already wrote
                # this iteration's transcript symlink.  That window's verdict
                # belongs to an earlier iteration: replace it with the fresh
                # launch, never adopt it as this iteration's.
                return AttemptDiscovery("launch")
            output = _verdict_output_if_present(pane_transcript)
            if output:
                return AttemptDiscovery("verdict", output=output,
                                        session_id=pane_sid)
            return AttemptDiscovery("adopt", pane_id=pane_id,
                                    transcript=pane_transcript,
                                    session_id=pane_sid)
        # Pane is still starting (no session id visible yet).  If Claude has
        # begun writing our transcript, adopt it; otherwise wait a bounded
        # grace for the session to expose itself before replacing the pane.
        try:
            transcript_live = Path(our_transcript).resolve().exists()
        except OSError:
            transcript_live = False
        if transcript_live:
            return AttemptDiscovery("adopt", pane_id=pane_id,
                                    transcript=our_transcript,
                                    session_id=our_sid)
        return AttemptDiscovery("pending", pane_id=pane_id,
                                transcript=our_transcript,
                                reason="pane has no session id yet")

    # No transcript of ours for this iteration.
    if other:
        return AttemptDiscovery("other_owner", owner=other, pane_id=pane_id,
                                transcript=pane_transcript)
    if pane_sid and _is_historical_session(state, transcript_dir, iteration,
                                           pane_sid):
        # The previous iteration's window: a fresh launch replaces it.
        return AttemptDiscovery("launch")
    if allow_recovery and pane_sid and pane_transcript:
        # This loop has already launched this iteration, so a live session
        # that is not one of our historical windows is either our own
        # recovered attempt (it produced no transcript symlink yet) or
        # another driver's launch for the same iteration — e.g. a sign-off
        # route racing a scheduled retry.  Adopt it instead of killing it
        # with another ``--fresh`` launch.
        output = _verdict_output_if_present(pane_transcript)
        if output:
            return AttemptDiscovery("verdict", output=output,
                                    session_id=pane_sid)
        return AttemptDiscovery("adopt", pane_id=pane_id,
                                transcript=pane_transcript,
                                session_id=pane_sid)
    if allow_recovery and not pane_sid:
        # A live pane that has not exposed a session id yet may be a
        # just-started recovery or another driver's launch; give it the
        # same bounded grace the "our attempt" path uses instead of killing
        # it with a second ``--fresh``.  The caller replaces it if the
        # session never appears.
        return AttemptDiscovery("pending", pane_id=pane_id,
                                transcript=pane_transcript,
                                reason="pane has no session id yet")
    # Unknown pane (e.g. a user-opened review window) on the first attempt
    # of an iteration this loop has not launched: keep the loop's existing
    # --fresh replacement semantics.
    return AttemptDiscovery("launch")


def _lease_keepalive(state: ReviewLoopState) -> Callable[[], bool]:
    """A ``stop_check`` that refreshes the loop's launch lease.

    Long reviews outlive the lease TTL; refreshing keeps other drivers from
    treating the loop as dead.  Always returns False (never stops the poll).
    """
    from pm_core import runtime_state as _rs
    last = {"t": time.monotonic()}

    def _check() -> bool:
        if state.stop_requested:
            # A stopping loop must not re-take a lease the superseding loop
            # has just claimed (or is about to claim).
            return False
        now = time.monotonic()
        if now - last["t"] >= _LEASE_REFRESH_SECONDS:
            last["t"] = now
            try:
                _rs.claim_action_lease(
                    state.pr_id, "review-loop", _lease_owner(state),
                    REVIEW_LAUNCH_CLAIM_TTL, state="running",
                    iteration=state.iteration, loop_id=state.loop_id)
            except Exception:
                _log.debug("review_loop: lease refresh failed", exc_info=True)
        return False

    return _check


def _run_claude_review(pr_id: str, pm_root: str, pr_data: dict,
                       transcript: str,
                       iteration: int = 0, loop_id: str = "",
                       attempt: int = 1,
                       attempt_info: dict | None = None,
                       state: ReviewLoopState | None = None) -> str:
    """Launch a review window and poll its JSONL transcript for the verdict.

    ``transcript`` is required — it is the path to the per-iteration
    JSONL symlink that ``pm pr review --transcript ...`` writes into,
    and it is how :func:`_poll_for_verdict` recovers the Claude
    session_id and reads assistant output.

    Returns the captured assistant text containing the verdict.
    Raises :class:`PaneKilledError` if the pane disappears before a
    verdict.  Raises :class:`ReviewLaunchError` when the launch itself
    failed (with the full child output in an artifact), and
    :class:`ReviewHoldError` for a permission/auth/trust hold.
    """
    from pm_core import tmux as tmux_mod

    session = _get_pm_session()
    if not session:
        raise ReviewLaunchError("Not in a pm tmux session",
                                retryable=False, reason="environment")
    if not tmux_mod.session_exists(session):
        raise ReviewLaunchError(f"tmux session '{session}' no longer exists",
                                retryable=False, reason="environment")

    window_name = _compute_review_window_name(pr_data)
    workdir = pr_data.get("workdir")

    cmd = _launch_review_window(
        pr_id, pm_root, iteration=iteration, loop_id=loop_id,
        transcript=transcript, attempt=attempt, workdir=workdir) or []

    # Wait briefly for the window to appear
    time.sleep(_WINDOW_WAIT)

    pane_id = _find_review_claude_pane(session, window_name, workdir)
    if not pane_id:
        artifact = _write_launch_artifact(
            transcript=transcript, pr_id=pr_id, iteration=iteration,
            loop_id=loop_id, attempt=attempt, cmd=cmd, returncode=None,
            stdout="", stderr="", workdir=workdir,
            note=f"window '{window_name}' not found after launch")
        msg = f"Review window '{window_name}' not found after launch"
        if artifact:
            msg += f" (artifact: {artifact})"
        raise ReviewLaunchError(msg, retryable=True, reason="window",
                                artifact=artifact)

    from pm_core.claude_launcher import (
        session_id_from_transcript, WorkspaceTrustBlocked,
    )
    session_id = session_id_from_transcript(transcript) if transcript else None
    if not session_id:
        artifact = _write_launch_artifact(
            transcript=transcript, pr_id=pr_id, iteration=iteration,
            loop_id=loop_id, attempt=attempt, cmd=cmd, returncode=None,
            stdout="", stderr="", workdir=workdir,
            note="launch produced no transcript session id")
        msg = "Review window launched but produced no transcript session id"
        if artifact:
            msg += f" (artifact: {artifact})"
        raise ReviewLaunchError(msg, retryable=True, reason="transcript",
                                artifact=artifact)

    if attempt_info is not None:
        attempt_info["pane_id"] = pane_id
        attempt_info["session_id"] = session_id

    _log.info("review_loop: polling pane %s in window %s (transcript=%s)",
              pane_id, window_name, transcript)

    stop_check = _lease_keepalive(state) if state is not None else None
    try:
        content = _poll_for_verdict(pane_id, transcript,
                                     grace_period=_VERDICT_GRACE_PERIOD,
                                     workdir=workdir,
                                     stop_check=stop_check)
    except WorkspaceTrustBlocked as e:
        raise ReviewHoldError(str(e)) from e
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
    if not transcript_dir:
        return None
    from pm_core.claude_launcher import session_id_from_transcript

    discovery = _discover_iteration(
        state, pr_data, transcript_dir, state.iteration,
        allow_recovery=(state.iteration_attempted
                        or state.launch_attempts > 0))
    if discovery.kind == "verdict":
        # Record whose verdict this was so a later iteration replaces (rather
        # than re-adopts) a still-live pane running that session.
        if discovery.session_id:
            state.last_session_id = discovery.session_id
        return discovery.output
    # A restart handoff trusts its own iteration transcript even when the
    # pane has not exposed its session id yet: poll it (the retry path,
    # which must avoid killing a starting session, treats "pending"
    # differently).
    if discovery.kind not in ("adopt", "pending") or not discovery.pane_id \
            or not discovery.transcript:
        return None

    _log.info("review_loop: adopting in-flight iteration %d for %s "
              "(pane %s, transcript=%s)", state.iteration, state.pr_id,
              discovery.pane_id, discovery.transcript)
    session_id = session_id_from_transcript(discovery.transcript)
    if not session_id:
        # The poller needs the session id; without one, relaunch the
        # iteration instead of raising a terminal error from inside it.
        return None
    # The verdict may have landed between the breadcrumb write and now;
    # the poller only wakes on idle events newer than its start.
    output = _landed_verdict(discovery.transcript)
    if output:
        return output
    state.last_session_id = session_id

    from pm_core.claude_launcher import WorkspaceTrustBlocked
    try:
        content = _poll_for_verdict(discovery.pane_id, discovery.transcript,
                                     workdir=pr_data.get("workdir"),
                                     stop_check=_lease_keepalive(state))
    except WorkspaceTrustBlocked as e:
        raise ReviewHoldError(str(e)) from e
    if content is None:
        raise PaneKilledError(
            f"Review pane disappeared (window: "
            f"{_compute_review_window_name(pr_data)})")
    return content


# ---------------------------------------------------------------------------
# Bounded retry of a failed authorized review launch
# ---------------------------------------------------------------------------

def _release_lease(state: ReviewLoopState) -> None:
    """Release this loop's cross-driver launch lease (idempotent)."""
    try:
        from pm_core import runtime_state as _rs
        _rs.release_action_lease(state.pr_id, "review-loop",
                                 _lease_owner(state))
    except Exception:
        _log.debug("review_loop: lease release failed", exc_info=True)


def _wait_for_claim(state: ReviewLoopState, pm_root: str | None,
                    iteration: int) -> bool:
    """Wait (bounded) for another loop's launch lease to expire/release."""
    deadline = time.monotonic() + REVIEW_LAUNCH_CLAIM_WAIT
    while time.monotonic() < deadline:
        if state.stop_requested:
            return False
        _interruptible_sleep(2.0, state, pm_root)
        if state.stop_requested:
            return False
        if _claim_launch(state, iteration, state.launch_attempts + 1):
            return True
    return False


def _claim_launch(state: ReviewLoopState, iteration: int, attempt: int) -> bool:
    """Take the cross-driver launch lease for this attempt (one owner)."""
    try:
        from pm_core import runtime_state as _rs
        if _rs.claim_action_lease(
                state.pr_id, "review-loop", _lease_owner(state),
                REVIEW_LAUNCH_CLAIM_TTL, state="running",
                iteration=iteration, loop_id=state.loop_id,
                launch_attempt=attempt):
            return True
    except Exception:
        _log.debug("review_loop: claim launch lease failed", exc_info=True)
        # Fail open: a broken runtime_state must not block reviews.
        return True
    # Lost the claim — but that is only another loop's business when one is
    # actually live.  An unwritable/corrupt runtime file also yields False,
    # and standing down for it would strand the target this fix exists for.
    if _other_loop_owner(state):
        return False
    _log.debug("review_loop: launch lease unavailable for %s; proceeding",
               state.pr_id)
    return True


def _pr_is_terminal(pr_id: str, pm_root: str | None) -> bool:
    """Whether the PR merged/closed (stop retrying, never resurrect it)."""
    if not pm_root:
        return False
    try:
        from pm_core import store
        data = store.load(Path(pm_root))
        pr = store.get_pr(data, pr_id)
    except Exception:
        return False
    return (pr or {}).get("status") in ("merged", "closed")


def _interruptible_sleep(seconds: float, state: ReviewLoopState,
                         pm_root: str | None = None) -> None:
    """Sleep in small chunks, waking on cancellation or PR closure."""
    end = time.monotonic() + max(0.0, float(seconds))
    next_terminal_check = 0.0
    while True:
        if state.stop_requested:
            return
        now = time.monotonic()
        if now >= end:
            return
        if pm_root and now >= next_terminal_check:
            next_terminal_check = now + 2.0
            if _pr_is_terminal(state.pr_id, pm_root):
                return
        time.sleep(min(0.25, end - now))


def _reset_launch_retry(state: ReviewLoopState) -> None:
    """A launch succeeded: clear the episode and its retry metadata."""
    state.launch_attempts = 0
    state.next_retry_at = 0.0
    state.last_launch_error = ""
    state.last_launch_artifact = None
    state.launch_retryable = False
    state.retry_episodes = 0
    state.retry_ready_at = 0.0
    # The TUI announces each retry attempt once, keyed on the attempt
    # number; without this a *later* iteration's attempt 2 would look
    # already-announced and be silently swallowed.
    state._ui_notified_retry = 0


def _run_iteration_with_retry(state: ReviewLoopState, pm_root: str,
                              pr_data: dict, transcript_dir: str,
                              iteration: int) -> str:
    """Run (or adopt) one review iteration, retrying failed launches.

    Only a genuine launch failure is retried; a pane that disappears
    (cancellation/closure), a hold, a real verdict and a merged/closed PR
    all stop the retry.  The iteration number is never advanced by a retry.
    """
    pr_id = state.pr_id
    transcript = f"{transcript_dir}/review-{pr_id}-i{iteration}.jsonl"

    if state.retry_iteration != iteration:
        # A different iteration: start a fresh episode.  Nothing of ours
        # exists for it yet, so rediscovery must not adopt an older run's
        # transcript for this iteration number.
        state.retry_iteration = iteration
        state.launch_attempts = 0
        state.next_retry_at = 0.0
        state.last_launch_error = ""
        state.last_launch_artifact = None
        state.launch_retryable = False
        state.iteration_attempted = False
        # Snapshot the transcript symlink *before* any attempt: if the
        # launch fails before the child replaces it, rediscovery must not
        # mistake an earlier run's iteration-N transcript for this attempt.
        state.stale_session_id = _transcript_session_id(transcript) or ""

    # A merge-restart may land mid-backoff: honour the remaining delay.
    if state.next_retry_at > time.time():
        _interruptible_sleep(state.next_retry_at - time.time(), state, pm_root)

    pending_checks = 0
    while True:
        if state.stop_requested:
            raise PaneKilledError("Review loop stopped during launch retry")
        if _pr_is_terminal(pr_id, pm_root):
            raise ReviewClosedError(
                f"PR {pr_id} merged/closed during review launch")

        # Claim before discovery so a concurrent driver sees this loop owns
        # the launch for the whole discover -> launch window.
        next_attempt = state.launch_attempts + 1
        if not _claim_launch(state, iteration, next_attempt):
            if not _wait_for_claim(state, pm_root, iteration):
                if _pr_is_terminal(pr_id, pm_root):
                    raise ReviewClosedError(
                        f"PR {pr_id} merged/closed during review launch")
                _log.info("review_loop: %s launch is owned by another loop; "
                          "standing down", pr_id)
                raise ReviewLaunchError(
                    "Review launch owned by another loop",
                    retryable=False, reason="superseded")

        discovery = _discover_iteration(state, pr_data, transcript_dir,
                                        iteration,
                                        allow_recovery=(
                                            state.iteration_attempted
                                            or state.launch_attempts > 0))
        # Remember whose session this iteration resolved to: the *next*
        # iteration must treat a still-live pane running it as historical
        # (replaced by ``--fresh``), never adopt its verdict a second time.
        if discovery.kind in ("verdict", "adopt") and discovery.session_id:
            state.last_session_id = discovery.session_id
        if discovery.kind == "verdict":
            _reset_launch_retry(state)
            return discovery.output
        if discovery.kind == "adopt":
            from pm_core.claude_launcher import WorkspaceTrustBlocked
            # Discovery ran a moment ago; the adopted pane may have landed
            # its verdict since.  The poller only wakes on idle events newer
            # than its own start, so re-read it here rather than wait for an
            # event that already fired.
            output = _landed_verdict(discovery.transcript)
            if output:
                _reset_launch_retry(state)
                return output
            # No grace period: the adopted session was launched before this
            # poll, so the startup-false-positive window the grace protects
            # against has already passed (``_adopt_in_flight_review`` makes
            # the same call).  With a grace, an idle event arriving inside
            # it is discarded and the poll waits for a *second* event that
            # an idle session never emits — the loop would hang until the
            # pane died.
            try:
                content = _poll_for_verdict(
                    discovery.pane_id, discovery.transcript,
                    workdir=pr_data.get("workdir"),
                    stop_check=_lease_keepalive(state))
            except WorkspaceTrustBlocked as e:
                raise ReviewHoldError(str(e)) from e
            if content is None:
                raise PaneKilledError(
                    "Review pane disappeared during launch retry")
            _reset_launch_retry(state)
            return content
        if discovery.kind == "other_owner":
            # Another native loop owns this PR: never launch over it.
            _log.info("review_loop: %s launch owned by %s; standing down",
                      pr_id, discovery.owner)
            raise ReviewLaunchError(
                f"Review launch owned by another loop ({discovery.owner})",
                retryable=False, reason="superseded")
        if discovery.kind == "pending":
            pending_checks += 1
            if pending_checks > 3:
                # A pane that never exposes a Claude session is half-created
                # debris: replace it with a fresh launch.
                _log.info("review_loop: %s iteration %d pane never exposed a "
                          "session; replacing it", pr_id, iteration)
                discovery = AttemptDiscovery("launch")
            else:
                _log.debug("review_loop: %s iteration %d %s; waiting %.0fs",
                           pr_id, iteration,
                           discovery.reason or "pane not ready yet",
                           _DISCOVERY_GRACE)
                _interruptible_sleep(_DISCOVERY_GRACE, state, pm_root)
                continue

        # kind == "launch"
        if state.launch_attempts >= REVIEW_LAUNCH_MAX_ATTEMPTS:
            raise ReviewLaunchError(
                state.last_launch_error or "Review launch failed",
                retryable=True, reason="exhausted",
                artifact=state.last_launch_artifact)

        attempt = next_attempt
        state.launch_attempts = attempt
        # From here on a transcript/verdict for this iteration may be ours:
        # rediscovery may adopt it instead of launching a duplicate.
        state.iteration_attempted = True

        info: dict = {}
        try:
            output = _run_claude_review(
                pr_id, pm_root, pr_data, iteration=iteration,
                loop_id=state.loop_id, transcript=transcript,
                attempt=attempt, attempt_info=info, state=state)
        except ReviewHoldError:
            raise
        except ReviewLaunchError as e:
            state.last_launch_error = str(e)
            state.last_launch_artifact = e.artifact
            state.launch_retryable = e.retryable
            if not e.retryable:
                raise
            if attempt >= REVIEW_LAUNCH_MAX_ATTEMPTS:
                raise
            delay = min(
                REVIEW_LAUNCH_BACKOFF_MAX,
                REVIEW_LAUNCH_BACKOFF_BASE * (2 ** (attempt - 1)))
            state.next_retry_at = time.time() + delay
            _log.warning(
                "review_loop: launch attempt %d/%d failed for %s (%s); "
                "retrying in %.0fs", attempt, REVIEW_LAUNCH_MAX_ATTEMPTS,
                pr_id, e.reason or "launch", delay)
            _interruptible_sleep(delay, state, pm_root)
            continue

        state.last_session_id = info.get("session_id") or state.last_session_id
        _reset_launch_retry(state)
        return output


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
    # The INPUT_REQUIRED wait can last minutes while the user interacts in
    # the pane; keep refreshing the launch lease so another driver does not
    # treat the loop as dead and relaunch over the live session.
    keepalive = _lease_keepalive(state)

    def _stop() -> bool:
        return state.stop_requested or keepalive()

    return _wait_for_follow_up_shared(
        session, window_name, iter_transcript, verdicts=ALL_VERDICTS,
        stop_check=_stop, log_prefix="review_loop",
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

    last_done = state.history[-1].iteration if state.history else 0
    adopt = state.iteration > last_done

    try:
        while state.iteration < max_iterations or adopt:
            if state.stop_requested:
                _log.info("review_loop: stop requested after %d iterations", state.iteration)
                break

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
                    output = _run_iteration_with_retry(
                        state, pm_root, pr_data, transcript_dir,
                        state.iteration,
                    )
            except PaneKilledError as e:
                _log.warning("review_loop: pane killed on iteration %d: %s", state.iteration, e)
                state.latest_verdict = VERDICT_KILLED
                state.latest_output = str(e)
                break
            except ReviewClosedError as e:
                _log.info("review_loop: %s", e)
                state.latest_verdict = VERDICT_CLOSED
                state.latest_output = str(e)
                break
            except ReviewHoldError as e:
                _log.warning("review_loop: review launch held on iteration %d: %s",
                             state.iteration, e)
                state.latest_verdict = VERDICT_HOLD
                state.latest_output = str(e)
                state.launch_retryable = False
                break
            except ReviewLaunchError as e:
                # A genuine failed authorized launch.  Never fabricate an
                # agent verdict: surface an explicit, retryable failure with
                # the complete child output retained in its artifact.
                _log.error("review_loop: review launch failed on iteration %d: %s",
                           state.iteration, e)
                state.latest_verdict = VERDICT_LAUNCH_FAILED
                state.latest_output = str(e)
                state.launch_retryable = e.retryable
                state.last_launch_error = str(e)
                state.last_launch_artifact = e.artifact
                if e.retryable:
                    state.retry_ready_at = time.time() + REVIEW_LAUNCH_REARM_SECONDS
                break
            except Exception as e:
                _log.exception("review_loop: review failed on iteration %d", state.iteration)
                state.latest_verdict = VERDICT_ERROR
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
        _release_lease(state)

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
