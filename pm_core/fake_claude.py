"""Fake Claude session for integration testing.

Writes realistic-looking output and emits a specified verdict so tests can
exercise verdict detection, review loop state machines, and QA loop
transitions without real API calls.

Production verdict detection (``loop_shared.poll_for_verdict``) is
hook-driven: it blocks on an ``idle_prompt`` hook event, then reads the
verdict from Claude's native JSONL transcript — it does *not* scrape pane
content.  So when the fake is given a ``session_id`` (the launcher passes
one for any pane whose verdict a loop will poll) it also:

  * writes a minimal Claude-format ``.jsonl`` transcript whose assistant
    turn contains the fake's full output, and
  * emits (and, while held open, periodically refreshes) the
    ``idle_prompt`` hook event the poller waits on.

Without a ``session_id`` (CLI / unit-test use) it just writes to stdout.
"""

import json
import os
import select
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Verdict catalogue
# ---------------------------------------------------------------------------

# Single-line verdicts: emitted as bare keywords on their own line
SINGLE_LINE_VERDICTS = (
    "PASS",
    "NEEDS_WORK",
    "INPUT_REQUIRED",
    "VERIFIED",
    "READY",             # watcher loop: iteration complete
    "FINALIZE_DONE",     # qa finalize: push + fast-forward succeeded
    "FINALIZE_BLOCKED",  # qa finalize: a prerequisite blocked completion
)

# Block-style verdicts: emitted as START … END pairs
BLOCK_VERDICTS = {
    "FLAGGED": ("FLAGGED_START", "FLAGGED_END"),
    "REFINED_STEPS": ("REFINED_STEPS_START", "REFINED_STEPS_END"),
    "REFINER_REJECT": ("REFINER_REJECT_START", "REFINER_REJECT_END"),
    "QA_PLAN": ("QA_PLAN_START", "QA_PLAN_END"),
}

# Accept both the short name (e.g. "FLAGGED") and the bare end-marker
# (e.g. "FLAGGED_END") as the --verdict argument for block verdicts.
ALL_VERDICTS = (
    list(SINGLE_LINE_VERDICTS)
    + list(BLOCK_VERDICTS.keys())
    + [end for _, end in BLOCK_VERDICTS.values()]
)

# Sentinel "verdict" for non-verdict sessions (impl, watcher, merge): the fake
# writes realistic output but emits no verdict keyword and — like a real
# interactive Claude session — stays open instead of exiting.
NO_VERDICT = "NONE"

# Everything accepted by the --verdict flag, including the no-verdict sentinel.
ALL_VERDICT_CHOICES = ALL_VERDICTS + [NO_VERDICT]

# ---------------------------------------------------------------------------
# Per-session-type verdict constraints
# ---------------------------------------------------------------------------

# Maps each session type to the verdict names that are valid for it.
# Empty tuple means the session type never emits a verdict — the fake runs as
# a no-verdict session (output then stay open). Used to validate fake-claude
# configs and to pick sensible defaults.
#
# Every ``model_config.SESSION_TYPES`` entry appears here. The additional
# entries below the divider are no-verdict interactive sessions outside the
# PR/QA loops (plan, meta, guide, …): they are not model-targetable, they just
# need their own fake-claude session type so they can be faked selectively
# rather than only via the ``_all`` catch-all.
SESSION_TYPE_VERDICTS: dict[str, tuple[str, ...]] = {
    # --- model_config.SESSION_TYPES — PR/QA loop sessions ---
    "impl":            (),   # implementation: no verdict, interactive coding
    "review":          ("PASS", "NEEDS_WORK", "INPUT_REQUIRED"),
    "qa":              ("PASS", "NEEDS_WORK", "INPUT_REQUIRED"),  # generic fallback
    "qa_planning":     ("QA_PLAN",),
    "qa_scenario":     ("PASS", "NEEDS_WORK", "INPUT_REQUIRED"),
    "qa_concretize":   ("REFINED_STEPS", "REFINER_REJECT"),
    "qa_verification": ("VERIFIED", "FLAGGED"),
    "qa_finalize":     ("FINALIZE_DONE", "FINALIZE_BLOCKED"),
    "watcher":         ("READY", "INPUT_REQUIRED"),
    "merge":           (),   # merge conflict: no verdict, interactive
    # --- non-loop interactive sessions: no verdict, fake-claude routing only ---
    "plan":            (),   # pm plan: add / breakdown / review / deps / import
    "meta":            (),   # pm meta: work on pm itself
    "guide":           (),   # pm guide: onboarding / getting-started
    "cluster":         (),   # pm cluster: cross-repo exploration
    "container":       (),   # pm container build session
    "qa_author":       (),   # pm qa: author / debug / launch / standalone
    "qa_regression":   (),   # pm qa regression authoring
    "discuss":         (),   # TUI ad-hoc Claude / discuss panes
    "watcher_review":  (),   # TUI chat-driven watcher-loop review
}


def _scripted_sequence(verdicts) -> list | None:
    """Return the scripted sequence list if *verdicts* is in scripted form.

    Two scripted shapes are accepted:

    * a bare ``list`` of entries (clamp-to-last by default)
    * a ``dict`` with a ``"sequence"`` list (optionally ``"wrap": true``)

    Anything else (a verdict→weight dict without ``"sequence"``) is the
    existing weighted-random form — this function returns ``None``.
    """
    if isinstance(verdicts, list):
        return verdicts
    if isinstance(verdicts, dict) and "sequence" in verdicts:
        seq = verdicts.get("sequence")
        if isinstance(seq, list):
            return seq
    return None


def _scripted_entry_verdict(entry) -> str | None:
    """Pull the verdict name out of a scripted-sequence entry.

    Entries are either bare strings (just the verdict) or dicts carrying
    per-iteration overrides under arbitrary keys plus a required ``"verdict"``.
    Returns ``None`` if the entry is malformed.
    """
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        v = entry.get("verdict")
        return v if isinstance(v, str) else None
    return None


def _scripted_wrap(verdicts) -> bool:
    """Return whether a scripted-sequence config opts into wrap-around.

    Only the dict form (``{"sequence": [...], "wrap": true}``) can request
    wrap; a bare list always clamps to its terminal entry.
    """
    return isinstance(verdicts, dict) and bool(verdicts.get("wrap"))


def validate_session_verdicts(session_type: str, verdicts) -> list[str]:
    """Return a list of error strings for verdicts invalid for *session_type*.

    Accepts three shapes for *verdicts*:

    * dict (verdict → weight) — existing weighted-random form
    * list of entries — scripted sequence (bare verdict strings, or dicts
      carrying per-iteration overrides with a ``"verdict"`` key)
    * dict with ``"sequence"`` list — scripted with optional ``"wrap": true``

    An empty list/dict means "no verdicts" (still valid for no-verdict
    session types).  Raises nothing — callers decide whether to warn or
    hard-error.
    """
    if session_type not in SESSION_TYPE_VERDICTS:
        return [f"Unknown session type {session_type!r}. "
                f"Valid types: {sorted(SESSION_TYPE_VERDICTS)}"]
    allowed = SESSION_TYPE_VERDICTS[session_type]
    errors: list[str] = []

    sequence = _scripted_sequence(verdicts)
    if sequence is not None:
        if not allowed and sequence:
            errors.append(
                f"Session type {session_type!r} never emits a verdict; "
                f"'verdicts' should be omitted or empty."
            )
            return errors
        for i, entry in enumerate(sequence):
            v = _scripted_entry_verdict(entry)
            if v is None:
                errors.append(
                    f"Scripted entry #{i} for {session_type!r} is malformed; "
                    f"expected a verdict string or a dict with a 'verdict' key."
                )
                continue
            if v not in allowed:
                errors.append(
                    f"Verdict {v!r} (scripted entry #{i}) is not valid for "
                    f"session type {session_type!r}. Allowed: {sorted(allowed)}"
                )
        return errors

    if not allowed:
        if verdicts:
            errors.append(
                f"Session type {session_type!r} never emits a verdict; "
                f"'verdicts' should be omitted or empty."
            )
        return errors
    for v in verdicts:
        if v not in allowed:
            errors.append(
                f"Verdict {v!r} is not valid for session type {session_type!r}. "
                f"Allowed: {sorted(allowed)}"
            )
    # Weighted-random form maps verdict → weight; a non-numeric or negative
    # weight passes the name check above but later crashes unhelpfully in
    # _pick_fake_verdict (float() / random.choices), so reject it here.
    if isinstance(verdicts, dict):
        for v, weight in verdicts.items():
            if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                errors.append(
                    f"Weight for verdict {v!r} (session type {session_type!r}) "
                    f"must be a number, got {weight!r}."
                )
            elif weight < 0:
                errors.append(
                    f"Weight for verdict {v!r} (session type {session_type!r}) "
                    f"must be non-negative, got {weight!r}."
                )
    return errors

# ---------------------------------------------------------------------------
# Default placeholder bodies for block verdicts
# ---------------------------------------------------------------------------

_DEFAULT_BODIES = {
    "FLAGGED": "Step 1: FAILED — expected output not produced.",
    "REFINED_STEPS": "1. Build the project\n2. Run the test suite\n3. Verify output",
    "REFINER_REJECT": "Scenario rejected: steps depend on an unavailable fixture.",
    "QA_PLAN": (
        "SCENARIO 1: Basic functionality\n"
        "STEPS:\n"
        "  1. Launch the application\n"
        "  2. Verify startup output\n"
        "END_SCENARIO"
    ),
}

# ---------------------------------------------------------------------------
# Preamble lines (simulates realistic Claude prose)
# ---------------------------------------------------------------------------

_PREAMBLE_LINES = [
    "I'll review the changes carefully.",
    "Looking at the diff and the surrounding context…",
    "The implementation looks clean and well-structured.",
    "Checking edge cases and error handling…",
    "The tests cover the main scenarios adequately.",
    "Reviewing the interface contracts between modules…",
    "No obvious security issues spotted in the new code.",
    "The commit messages are descriptive and follow conventions.",
    "Dependencies are pinned to reasonable version ranges.",
    "Overall the approach is sound and consistent with the codebase style.",
]


def _resolve_block_name(verdict: str) -> str | None:
    """Return the canonical block name for *verdict*, or None if not a block verdict."""
    upper = verdict.upper()
    if upper in BLOCK_VERDICTS:
        return upper
    # Accept "FLAGGED_END" as meaning "FLAGGED", etc.
    for name, (_, end) in BLOCK_VERDICTS.items():
        if upper == end:
            return name
    return None


def _write(text: str, stream: bool = False, char_delay: float = 0.015) -> None:
    """Write *text* to stdout, optionally character-by-character."""
    if not stream:
        sys.stdout.write(text)
        sys.stdout.flush()
        return
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(char_delay)


# Lines used when auto-generating body content (--body-lines).
_BODY_LINES = [
    "Examining the test harness configuration…",
    "The module boundaries look well-defined.",
    "Tracing execution through the happy path.",
    "Checking that error paths are covered.",
    "Inspecting the fixture data for completeness.",
    "Verifying the state machine transitions.",
    "Reviewing the concurrency model for races.",
    "Confirming the logging output is structured.",
    "Checking the cleanup path after failures.",
    "Validating the schema against the examples.",
]


# Interval (seconds) at which the idle hook is refreshed while a session is
# held open.  A poller with a grace period only acts on an event *newer* than
# its grace window, so a single emission would never satisfy it — see
# ``loop_shared.poll_for_verdict``.
_HOOK_REFRESH = 2.0


def _claude_transcript_path(session_id: str) -> Path:
    """Compute Claude's native transcript path for the current cwd + session.

    Mirrors ``claude_launcher._claude_project_dir`` — Claude Code stores
    transcripts under ``~/.claude/projects/<mangled-cwd>/<session-id>.jsonl``
    with ``/`` and ``.`` in the path replaced by ``-``.  The fake runs in the
    pane's cwd, which is the cwd pm passed to ``build_claude_shell_cmd``, so
    the launcher-side ``transcript_path_for`` resolves to the same file.
    (``verdict_transcript._read_transcript_text`` additionally globs by
    session-id, so minor cwd drift is tolerated.)
    """
    mangled = os.getcwd().replace("/", "-").replace(".", "-")
    return Path.home() / ".claude" / "projects" / mangled / f"{session_id}.jsonl"


def _write_fake_transcript(session_id: str, assistant_text: str) -> None:
    """Write a minimal Claude-format JSONL transcript for *session_id*.

    Production verdict detection (``poll_for_verdict`` →
    ``extract_verdict_from_transcript``) reads Claude's native JSONL
    transcript, not pane content — so a faithful fake must produce one.  Two
    records: a user turn (the latest-turn boundary marker) and an assistant
    turn whose text content is the fake's full stdout output.
    """
    try:
        path = _claude_transcript_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {"type": "user", "sessionId": session_id,
             "message": {"role": "user", "content": "<fake-claude prompt>"}},
            {"type": "assistant", "sessionId": session_id,
             "message": {"role": "assistant",
                         "content": [{"type": "text", "text": assistant_text}]}},
        ]
        path.write_text("".join(json.dumps(r) + "\n" for r in records))
    except OSError:
        pass


def _emit_idle_hook(session_id: str) -> None:
    """Write an ``idle_prompt`` hook event for *session_id*.

    Real Claude triggers ``~/.claude/settings.json`` hooks that record turn
    boundaries under ``~/.pm/hooks/<session-id>.json``; ``poll_for_verdict``
    blocks on that event before reading the transcript.  The fake writes the
    event itself, reusing ``hook_receiver``'s atomic writer so the format
    cannot drift.
    """
    try:
        from pm_core.hook_receiver import _write_event
        _write_event(session_id, {
            "event_type": "idle_prompt",
            "timestamp": time.time(),
            "session_id": session_id,
            "matcher": "",
            "cwd": os.getcwd(),
        })
    except Exception:
        pass


def _hold_open(hold: float | None, session_id: str | None = None) -> None:
    """Keep the process alive after the session's output.

    A real Claude session does not exit when it finishes a turn — it stays
    open in its pane waiting for the next input, and the loop kills the pane
    once it has read the verdict.  The fake mimics that:

    - ``hold is None``  — stay open until stdin EOF (the pane's tty closes
      when the window is killed).  Default for live tmux launches.
    - ``hold >= 0``     — stay open that many seconds, then exit.  Bounded
      form for tests.  ``hold == 0`` exits immediately.

    When *session_id* is set the idle hook is (re-)emitted on entry and every
    ``_HOOK_REFRESH`` seconds while held open, so a poller with a grace
    period eventually observes an event newer than its grace window.  With no
    *session_id* there is nothing to refresh — the original simple wait.
    """
    if not session_id:
        if hold is None:
            try:
                sys.stdin.read()
            except (KeyboardInterrupt, OSError):
                pass
        elif hold > 0:
            time.sleep(hold)
        return

    # session_id set — refresh the idle hook while held open.
    if hold is not None:
        deadline = time.monotonic() + max(0.0, hold)
        while True:
            _emit_idle_hook(session_id)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(_HOOK_REFRESH, remaining))
    else:
        while True:
            _emit_idle_hook(session_id)
            try:
                ready, _, _ = select.select([sys.stdin], [], [], _HOOK_REFRESH)
            except (OSError, ValueError):
                # stdin not selectable (closed / not a real fd) — fall back
                # to a single blocking read, then exit.
                try:
                    sys.stdin.read()
                except (KeyboardInterrupt, OSError):
                    pass
                return
            if ready:
                return


def run_fake_claude(
    verdict: str | None,
    preamble: int = 3,
    preamble_delay: float = 0.0,
    delay: float = 0.0,
    body: str | None = None,
    body_lines: int = 0,
    body_batch: int = 1,
    body_delay: float = 0.0,
    stream: bool = False,
    char_delay: float = 0.015,
    hold: float | None = None,
    session_id: str | None = None,
) -> None:
    """Execute the fake Claude session.

    Output sequence:
      1. *preamble* filler lines, with *preamble_delay* between each.
      2. *body_lines* generated lines, emitted *body_batch* at a time
         with *body_delay* between batches.  Useful for testing that the
         verdict poller does not prematurely accept keywords from earlier
         output while new content is still arriving.
      3. Sleep *delay* seconds (simulates overall session duration).
      4. The verdict block — skipped for no-verdict sessions.

    Args:
        verdict: Verdict keyword to emit.  ``None`` or ``"NONE"`` runs a
            no-verdict session (impl/watcher/merge): output but no verdict,
            and the process stays open per *hold* instead of exiting.
        preamble: Number of filler prose lines before the generated body.
        preamble_delay: Seconds to sleep between each preamble line.
        delay: Seconds to sleep immediately before writing the verdict.
        body: Custom text between _START/_END markers (block verdicts only).
        body_lines: Number of extra generated lines to emit before the verdict.
        body_batch: Lines per emission batch; *body_delay* is applied after
            each full batch.  Default 1 (one line, then pause).
        body_delay: Seconds to sleep between each *body_batch* chunk.
        stream: Write output character-by-character to simulate streaming.
        char_delay: Per-character sleep when *stream* is True (default 0.015 s).
        hold: How long to stay open after the output — see
            :func:`_hold_open`.  ``None`` (default) stays open until the pane
            closes; a number stays open that many seconds then exits.
            Applies to no-verdict sessions always, and to verdict sessions
            whenever *session_id* is set (so the poller has a live pane).
        session_id: Claude session id.  When set, the fake also writes a
            Claude-format JSONL transcript and emits the ``idle_prompt`` hook
            event — the inputs production verdict detection actually reads —
            and stays open afterwards so the poller can observe them.  When
            ``None`` the fake only writes to stdout (CLI / unit-test use).
    """
    no_verdict = verdict is None or verdict.upper() == NO_VERDICT
    upper = "" if no_verdict else verdict.upper()
    # Accumulate every byte written to stdout so the same text can be replayed
    # into the JSONL transcript as the assistant turn's content.
    captured: list[str] = []

    def _w(text: str) -> None:
        captured.append(text)
        _write(text, stream=stream, char_delay=char_delay)

    # 1. Preamble lines
    for i in range(preamble):
        line = _PREAMBLE_LINES[i % len(_PREAMBLE_LINES)]
        _w(line + "\n")
        if preamble_delay > 0 and i < preamble - 1:
            time.sleep(preamble_delay)

    # 2. Generated body lines (batched, with inter-batch delay)
    if body_lines > 0:
        batch_size = max(1, body_batch)
        for i in range(body_lines):
            line = _BODY_LINES[i % len(_BODY_LINES)]
            _w(line + "\n")
            # Sleep after each full batch (but not after the very last line)
            if body_delay > 0 and ((i + 1) % batch_size == 0) and (i + 1) < body_lines:
                time.sleep(body_delay)

    # 3. Pre-verdict delay
    if delay > 0:
        time.sleep(delay)

    # 4. Verdict block — skipped entirely for no-verdict sessions.
    if not no_verdict:
        if upper in SINGLE_LINE_VERDICTS:
            _w("\n" + upper + "\n")
        else:
            block_name = _resolve_block_name(upper)
            if block_name is None:
                # Unknown verdict — emit as-is (best-effort).
                _w("\n" + upper + "\n")
            else:
                start_marker, end_marker = BLOCK_VERDICTS[block_name]
                body_text = (body if body is not None
                             else _DEFAULT_BODIES.get(block_name, ""))
                _w("\n" + start_marker + "\n")
                if body_text:
                    _w(body_text.rstrip("\n") + "\n")
                _w(end_marker + "\n")

    # 5. Transcript — written once the full output is known, so the polling
    #    loop reads a complete assistant turn.  Only when a session_id was
    #    provided (i.e. launched in a pane whose verdict a loop will poll).
    if session_id:
        _write_fake_transcript(session_id, "".join(captured))

    # 6. Stay open like a real Claude session:
    #    - no-verdict sessions always stay open (they never exit on their own);
    #    - verdict sessions stay open when a session_id was provided, so the
    #      poller has a live pane and a refreshed hook to detect against —
    #      the loop kills the pane once it has read the verdict.
    #    Without a session_id a verdict session exits immediately (CLI /
    #    unit-test use), preserving the original drop-in behaviour.
    if no_verdict or session_id:
        _hold_open(hold, session_id=session_id)
