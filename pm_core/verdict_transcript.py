"""JSONL transcript-based verdict extraction.

Replaces pane-scraping verdict detection.  Walks a Claude Code
transcript (``~/.claude/projects/<mangled>/<session-id>.jsonl``) in
reverse and returns the verdict keyword emitted in the current task
scope — the latest assistant turn, or an earlier turn when only
non-task wakeups separate it from the tail.

Design:
  * Schema-light.  We match the raw JSON-encoded bytes, not the message
    shape.  The only structural assumption is that each JSONL line is a
    single record and that assistant records contain the substring
    ``"type":"assistant"`` while user records contain ``"type":"user"``.
    Both have held stable across Claude Code versions and are used by
    Anthropic's own tooling.
  * Task-scoped, not strictly latest-turn.  After an ``idle_prompt``
    hook fires we want the verdict for the work this worker was asked to
    do.  A worker that emitted its verdict and then received a ``/loop``
    wakeup, a Monitor/task notification, or another system nudge may
    answer with a no-verdict postscript; treating that as the latest
    turn loses the verdict (pr-8efa789).  We walk backward across
    *non-task* user records (see ``_user_record_is_non_task``) and stop
    at the first genuine task boundary — the initial prompt, a retry, a
    verifier follow-up, or a new user task.  A stale verdict from an
    earlier task can therefore never be resurrected.
  * Boundary-aware.  A verdict keyword must sit on its own text-line
    within the assistant's output, i.e. bounded by a JSON newline-escape
    (``\\n`` / ``\\r\\n``) or a JSON string quote, optionally wrapped in
    markdown bold/code markers (``**PASS**`` / ```` `PASS` ````).  That
    rejects incidental mentions like "PASS this file" while accepting
    bare or lightly-formatted ``PASS`` as the entire message.
  * Visible text only.  The keyword must appear in a record's ``text``
    content — not in a thinking block or a ``tool_use`` input.  Those are
    raw JSON strings too, so an agent that greps for ``INPUT_REQUIRED`` or
    writes the keyword into a file would otherwise be read as emitting a
    verdict.
  * Longest-match-first.  Verdicts are scanned in descending length
    order so any longer candidate would take precedence over a shorter
    prefix (kept for robustness — today's verdicts have no prefix
    overlap).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


# Tolerate whitespace between key and value (``"type":"assistant"`` from
# real Claude transcripts, ``"type": "assistant"`` from ``json.dumps``).
_ASSISTANT_RE = re.compile(r'"type"\s*:\s*"assistant"')
_USER_RE = re.compile(r'"type"\s*:\s*"user"')


def _read_transcript_text(transcript_path: str | Path | None) -> str:
    """Read a Claude transcript, tolerating slug-mismatched symlinks.

    Band-aid for pr-488b748: when ``build_claude_shell_cmd`` creates the
    transcript symlink it derives the target's parent dir from the cwd
    *we* passed in, but Claude writes to a parent derived from its
    actual runtime cwd. If those diverge (e.g. a worktree symlinked to a
    different canonical path, or a nested pm invocation that registered
    one workdir while launching the pane at another), the symlink
    target never appears. The session_id is unique, though, so we can
    recover the real path by scanning ``~/.claude/projects/*/`` for the
    matching ``<session_id>.jsonl``.
    """
    if not transcript_path:
        return ""
    p = Path(transcript_path)
    try:
        return p.read_text(errors="replace")
    except (OSError, FileNotFoundError):
        pass
    # Symlink target missing — fall back to a session-id glob.
    sid: str | None = None
    try:
        if p.is_symlink():
            sid = Path(os.readlink(p)).stem
    except OSError:
        sid = None
    if not sid:
        sid = p.stem
    if not (len(sid) == 36 and sid.count("-") == 4):
        return ""
    projects_dir = Path.home() / ".claude" / "projects"
    try:
        matches = list(projects_dir.glob(f"*/{sid}.jsonl"))
    except OSError:
        return ""
    if not matches:
        return ""
    # Pick the most recently modified — handles edge cases where stale
    # files with the same sid linger from a prior run.
    real = max(matches, key=lambda m: m.stat().st_mtime)
    try:
        return real.read_text(errors="replace")
    except OSError:
        return ""


def _resolve_transcript_file(transcript_path: str | Path | None) -> Path | None:
    """The readable JSONL for *transcript_path*, tolerating broken symlinks.

    Mirrors :func:`_read_transcript_text`'s slug-mismatch band-aid but
    returns a path so callers can read only the tail of a large transcript.
    """
    if not transcript_path:
        return None
    p = Path(transcript_path)
    try:
        # A readable file (including a symlink to one).  Directories are not
        # transcripts — fall through to the session-id glob so the previous
        # "read it, else search" behaviour is preserved.
        if p.is_file():
            return p
    except OSError:
        pass
    sid: str | None = None
    try:
        if p.is_symlink():
            sid = Path(os.readlink(p)).stem
    except OSError:
        sid = None
    if not sid:
        sid = p.stem
    if not (len(sid) == 36 and sid.count("-") == 4):
        return None
    projects_dir = Path.home() / ".claude" / "projects"
    try:
        matches = list(projects_dir.glob(f"*/{sid}.jsonl"))
    except OSError:
        return None
    if not matches:
        return None
    try:
        return max(matches, key=lambda m: m.stat().st_mtime)
    except OSError:
        return matches[0]


# The latest turn lives at the end of the transcript; reading a bounded tail
# keeps the scheduler's per-tick check cheap on multi-megabyte sessions.
# The window grows only when the smallest one cannot see a turn boundary —
# a single record (e.g. a Write tool_use carrying a large file) can exceed
# it, and dropping that partial line would otherwise hide the newest turn.
_TURN_TAIL_WINDOWS = (262144, 2 * 1024 * 1024, 8 * 1024 * 1024)
_TURN_TAIL_BYTES = _TURN_TAIL_WINDOWS[0]


def _read_transcript_tail(path: Path, max_bytes: int = _TURN_TAIL_BYTES) -> str:
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                data = f.read()
                nl = data.find(b"\n")
                if nl >= 0:
                    data = data[nl + 1:]
            else:
                data = f.read()
        return data.decode("utf-8", "replace")
    except OSError:
        return ""


def latest_turn_state(transcript_path: str | Path | None,
                      interrupted_before: float | None = None) -> str:
    """Whether the transcript's newest turn is finished.

    Returns ``"complete"`` when the newest record is an assistant message
    that is not waiting on a tool (no ``tool_use`` block, no
    ``stop_reason == "tool_use"``) and, when its ``stop_reason`` is still
    unset (a record written mid-stream), carries the answer ``text``.
    Returns ``"in_progress"`` when a newer user record (a submitted prompt or
    a ``tool_result``) means the agent still owes a response, or when the
    newest assistant record is a partial one with no answer yet (a streamed
    thinking block), and ``"unknown"`` when the transcript is missing, empty
    or unparseable.  Injected/transcript-only user records (slash-command
    output, ``!`` shell commands, task notifications, compaction summaries)
    are not prompts and are skipped — see
    :func:`_is_non_prompt_user_record`.

    An ``[Request interrupted by user]`` marker ends a turn (the CLI writes it
    exactly when it aborts generation, and the agent owes no reply), but only
    when it carries a readable timestamp that predates *interrupted_before*
    (epoch seconds — the fresh-autostart request time).  A marker written
    *after* the request may be followed by a retyped prompt, so it keeps the
    turn ``"in_progress"``; with no fence (or no readable marker timestamp,
    which cannot be shown to predate the request) the conservative
    ``"in_progress"`` is returned too.  This matters because the marker is a
    *list*-content user record, so it is not covered by
    :func:`_is_non_prompt_user_record`, and an interrupt left as the tail
    would otherwise stall the handoff forever.

    Used by the explicit fresh-autostart handoff: a completed turn is the
    signal that the user's implementation feedback turn is over.
    """
    path = _resolve_transcript_file(transcript_path)
    if path is None:
        return "unknown"
    try:
        size = path.stat().st_size
    except OSError:
        return "unknown"
    # Grow the window until a turn boundary is visible.  A tail that starts
    # mid-record loses its first (partial) line, so a newest turn larger
    # than the window would otherwise read as "unknown" forever.
    for window in _TURN_TAIL_WINDOWS:
        state = _turn_state_from_tail(_read_transcript_tail(path, window),
                                      interrupted_before)
        if state != "unknown" or window >= size:
            return state
    return "unknown"


# Claude Code records slash commands, ``!`` shell commands, injected context
# and background-task notifications as ``type: "user"`` entries.  They are not
# a submitted prompt (the agent owes no reply), so they must not read as a
# pending turn — otherwise a ``/model``, a ``!ls`` or a task notification left
# at the end of the transcript would stall the handoff forever.
_NON_PROMPT_USER_PREFIXES = ("<local-command-", "<command-name>",
                             "<command-args>", "<command-message>",
                             "<task-notification>", "<bash-input>",
                             "<bash-stdout>", "<bash-stderr>")

# Esc during a turn makes Claude Code write the aborted turn as a user record
# (``[Request interrupted by user]`` / ``[Request interrupted by user for tool
# use]``) whose content is a *list* of text blocks — so the prefix check above
# misses it.  It is not a prompt: the agent owes no reply.
_INTERRUPT_PREFIX = "[Request interrupted by user"


def _is_interrupt_record(rec: dict) -> bool:
    """Whether a user record is Claude Code's turn-aborted marker."""
    return _record_text(rec).lstrip().startswith(_INTERRUPT_PREFIX)


def _record_epoch(rec: dict) -> float:
    """The record's ``timestamp`` as epoch seconds (0.0 when unusable)."""
    from pm_core.signoff import parse_ts
    try:
        return parse_ts(rec.get("timestamp")).timestamp()
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _is_non_prompt_user_record(rec: dict) -> bool:
    """Whether a ``type: "user"`` record is injected/meta, not a prompt."""
    # A compaction summary ("This session is being continued from a previous
    # conversation...") is written as a plain-string user record after the
    # session ran out of context.  It is transcript-only context, not a
    # submitted prompt; treating it as one reads "in_progress" forever for a
    # session that ended right after compacting (real transcripts: every such
    # tail record is preceded by a completed ``end_turn`` assistant answer).
    # ``isVisibleInTranscriptOnly`` accompanies it in real records but is the
    # broader flag, so only the precise ``isCompactSummary`` is trusted here —
    # a false "in_progress" is recoverable, a false "complete" is not.
    if rec.get("isMeta") or rec.get("isCompactSummary"):
        return True
    msg = rec.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    return isinstance(content, str) and content.lstrip().startswith(
        _NON_PROMPT_USER_PREFIXES)


def _turn_state_from_tail(text: str,
                          interrupted_before: float | None = None) -> str:
    """Classify the newest user/assistant record in *text* (see above)."""
    if not text.strip():
        return "unknown"
    # Split on "\n" only: ``str.splitlines`` also splits on Unicode line
    # boundaries (U+2028, U+2029, U+0085) that JSON leaves *unescaped* inside
    # a string — real transcripts contain them.  Such a record would be
    # fragmented into pieces that fail ``json.loads`` and skipped, so the
    # newest turn would be read from an older record: a handoff that never
    # advances when the final answer carries one, or an early "complete" over
    # a prompt that was just submitted.
    for line in reversed(text.split("\n")):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(rec, dict):
            continue
        typ = rec.get("type")
        if typ == "user":
            if _is_interrupt_record(rec):
                # The CLI writes this marker when it aborts the turn, so the
                # turn is over — but only if the abort happened before the
                # caller's fence (the fresh-autostart request).  A marker
                # written after it may be followed by a retyped prompt, so
                # wait rather than start a review over aborted work.  A
                # missing fence (0.0 from an unparseable ``requested_at``) is
                # not a fence, and neither is an unreadable record timestamp
                # (0.0 — it cannot be shown to predate the request): stay
                # conservative in both cases.  A false "complete" would start
                # the review over aborted work; a false "in_progress" is
                # recoverable (the user's next turn ends it).
                epoch = _record_epoch(rec)
                if (interrupted_before and 0.0 < epoch <= interrupted_before):
                    return "complete"
                return "in_progress"
            if _is_non_prompt_user_record(rec):
                continue
            return "in_progress"
        if typ == "assistant":
            msg = rec.get("message") or {}
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list) and any(
                    isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    for block in content):
                return "in_progress"
            if isinstance(msg, dict) and msg.get("stop_reason") == "tool_use":
                return "in_progress"
            if isinstance(msg, dict) and msg.get("stop_reason") is None:
                # Claude Code streams a message's content blocks as separate
                # records and only fills ``stop_reason`` in once the message
                # is complete.  A trailing record with no answer text is
                # therefore a turn still in progress — the thinking block of
                # a turn whose answer (or tool call) has not been written
                # yet.  Reading that as "complete" would start the
                # fresh-autostart review over in-flight work.
                #
                # A ``text`` record, by contrast, ends the turn: measured
                # over every transcript under ``~/.claude/projects``, the
                # answer text is almost always the last thing a turn writes,
                # and a null ``stop_reason`` on the *final* record is the
                # common shape (a finished or killed session often never gets
                # the closing flush — thousands of real transcripts end
                # this way).  Requiring a set ``stop_reason`` would therefore
                # stall the handoff on the majority of real sessions.  The
                # cost is a rare mid-message text flush reading as complete
                # for that moment (6 of ~8.4k records; the next block followed
                # within ~1.5 s, or the record was an API-error retry of an
                # already-finished answer).  The poll runs every second, so
                # the exposure is small and the alternative failure (a
                # handoff that never advances) is worse.
                has_text = (
                    isinstance(content, str)
                    or (isinstance(content, list) and any(
                        isinstance(block, dict)
                        and block.get("type") == "text"
                        for block in content)))
                if not has_text:
                    return "in_progress"
            return "complete"
        # Other record kinds (system/meta) are not turn boundaries.
    return "unknown"



@dataclass(frozen=True)
class VerdictHit:
    """A verdict found in a transcript, with the identity of its turn.

    ``text`` is the concatenated text content of the assistant records in
    the verdict's turn (so callers can read the ``Reason:`` line or parse
    markers without re-reading the file).  ``turn_id`` / ``timestamp``
    identify the assistant record that carried the verdict; ``line_index``
    is its 0-based position in the JSONL file.
    """

    verdict: str
    text: str
    turn_id: str = ""
    timestamp: str = ""
    line_index: int = -1


# Fixed-interval ``/loop`` and cron deliveries re-send the stored task
# prompt, but Claude Code prefixes them with this marker: they are
# automated re-fires of the same task, not live user input.
_SCHEDULED_TASK_PREFIX = (
    "[SCHEDULED TASK - AUTOMATED FIRING OF A CONFIGURED PROMPT]"
)
# Dynamic / loop.md loop ticks and the autonomous-loop sentinels.
_NON_TASK_TEXT_PREFIXES = (
    _SCHEDULED_TASK_PREFIX,
    "# /loop tick",
    "# Autonomous loop check",
    "# Autonomous loop tick",
    "<task-notification>",
    # Harness marker written when the user hits Esc / stops the turn
    # (``[Request interrupted by user]`` and the ``for tool use`` variant).
    # It is not a new task: the user asked for nothing, so a verdict emitted
    # before the interruption still stands.  A follow-up instruction the user
    # types afterwards is a separate record and remains a task boundary.
    "[Request interrupted by user",
    # qa_loop's own "your verdict must be alone on its line" nudge.
    "Reminder: your verdict must appear alone",
)
_NON_TASK_SENTINELS = frozenset({
    "<<autonomous-loop>>",
    "<<autonomous-loop-dynamic>>",
    "<<loop.md>>",
    "<<loop.md-dynamic>>",
})
# A Stop hook can inject new instructions; treat its feedback as a task
# boundary even though it is a system (``isMeta``) record.
_STOP_HOOK_PREFIX = "Stop hook feedback:"

# Text-block gate for the backward scan: ``"type": "text"`` in a content
# block, tolerating the same key/value spacing as ``_ASSISTANT_RE``.
_TEXT_BLOCK_RE = re.compile(r'"type"\s*:\s*"text"')
_SYSTEM_REMINDER_BLOCK_RE = re.compile(
    r"<system-reminder\b[^>]*>.*?</system-reminder>", re.I | re.S)


def _record_text(rec: object) -> str:
    """Return the concatenated text content of a user/assistant record."""
    if not isinstance(rec, dict):
        return ""
    msg = rec.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            piece = block.get("text")
            if isinstance(piece, str):
                chunks.append(piece)
    return "\n".join(chunks)


def _is_tool_result_record(rec: dict) -> bool:
    """True for a user record that only carries tool results.

    Tool results are part of the assistant's tool-use turn, not a new
    user prompt, so they must not terminate the backward scan.
    """
    if "toolUseResult" in rec:
        return True
    msg = rec.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list) or not content:
        return False
    has_result = False
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            has_result = True
        elif block.get("type") == "text" and str(block.get("text") or "").strip():
            # A mixed record with real user text is a prompt, not a result.
            return False
    return has_result


def _unwrap_system_reminder(text: str) -> str | None:
    """Strip ``<system-reminder>`` blocks from a user record.

    Returns ``None`` when nothing but reminders remains — a system notice,
    not a user prompt.  Otherwise returns the remaining text (the prompt
    plus any appended reminder), which is classified normally.  Every block
    is stripped, not just one at each end, so a record carrying several
    notices is still recognised as transparent.  An unclosed reminder tag is
    left in place, so the record is treated as a prompt (fail closed).
    """
    stripped = text.strip()
    if "<system-reminder" not in stripped.lower():
        return stripped
    remainder = _SYSTEM_REMINDER_BLOCK_RE.sub("", stripped).strip()
    return remainder or None


def _user_record_is_non_task(rec: dict) -> bool:
    """True when a user record does not start a new task.

    Non-task records are transparent to the backward verdict scan:
    system-injected wakeups/notifications and the loop's own nudges.  Any
    other user text (the initial prompt, a retry, verifier feedback, a new
    user task) is a task boundary.
    """
    if _is_tool_result_record(rec):
        return True
    text = _record_text(rec)
    unwrapped = _unwrap_system_reminder(text)
    if unwrapped is None:
        return True  # reminder-only record
    if unwrapped.startswith(_STOP_HOOK_PREFIX):
        return False
    if rec.get("isMeta") is True:
        return True
    # Compaction injects a "This session is being continued…" summary as a
    # plain user record; it is harness-generated, not a new task, and the
    # pre-compaction turns stay in the file behind it.
    if rec.get("isCompactSummary") is True:
        return True
    if not unwrapped:
        return True
    if unwrapped in _NON_TASK_SENTINELS:
        return True
    return any(unwrapped.startswith(p) for p in _NON_TASK_TEXT_PREFIXES)


def _parse_record(line: str) -> dict | None:
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return None
    return rec if isinstance(rec, dict) else None


def _verdict_patterns(verdicts: tuple[str, ...]) -> list[tuple[str, re.Pattern]]:
    ordered = sorted({v for v in verdicts if v}, key=len, reverse=True)
    # Boundary: JSON newline-escape (``\n`` / ``\r``) or string quote.
    # Between the boundary and the verdict we tolerate markdown bold/code
    # markers (``*``, `` ` ``) so ``**PASS**`` on its own line still
    # matches — the pane-scraping path used to strip those before
    # comparing, and reviewers routinely wrap verdicts in bold.
    return [
        (v, re.compile(
            r'(?:\\[nr]|")[*`]*' + re.escape(v) + r'[*`]*(?:\\[nr]|")'
        ))
        for v in ordered
    ]


def _turn_text(lines: list[str], verdict_idx: int, verdict_text: str,
               after_texts: list[str]) -> str:
    """Concatenate the assistant text of the turn holding *verdict_idx*.

    ``after_texts`` are the text records the backward scan already collected
    (newest first) between the verdict record and the end of its turn.  The
    walk below adds the records that precede the verdict in the same turn, so
    the returned text covers the whole turn — callers such as the
    concretization / verification flows parse markers (``REFINED_STEPS_*``,
    ``FLAGGED_*``) that may sit in an earlier text record than the verdict.
    Tool results belong to the turn; any other user record opened it and ends
    the walk.
    """
    before: list[str] = []
    for idx in range(verdict_idx - 1, -1, -1):
        line = lines[idx]
        if _ASSISTANT_RE.search(line):
            if _TEXT_BLOCK_RE.search(line):
                piece = _record_text(_parse_record(line))
                if piece:
                    before.append(piece)
            continue
        if _USER_RE.search(line):
            rec = _parse_record(line)
            if rec is not None and _is_tool_result_record(rec):
                continue
            break
        # Meta/unknown record inside the turn — skip.
    chunks = list(reversed(before))
    if verdict_text:
        chunks.append(verdict_text)
    chunks.extend(reversed(after_texts))
    return "\n".join(chunks)


def _text_line_is_verdict(text: str, verdict: str) -> bool:
    """True when *verdict* occupies a whole line of the assistant's text.

    The verdict must be alone on its line; markdown emphasis/code markers
    around it are tolerated (reviewers wrap verdicts in ``**`` / backticks).
    Checking the *parsed* text rather than the raw JSONL line keeps a keyword
    that appears only inside a thinking block or a tool_use input — a Grep
    pattern, a file the agent wrote — from being read as a verdict.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == verdict or stripped.strip("*`").strip() == verdict:
            return True
    return False


def find_verdict_turn(
    transcript_path: str | Path | None,
    verdicts: tuple[str, ...],
) -> VerdictHit | None:
    """Return the verdict for the current task scope, with its turn.

    Scans backward from the tail.  A verdict in the newest assistant
    segment wins; when the newest segment has none, the scan continues
    across non-task wakeup records (``/loop`` ticks, Monitor task
    notifications, system nudges) into older assistant segments.  The
    first genuine task boundary (a real user prompt, retry, verifier
    feedback, or Stop-hook instruction) stops the scan, so a verdict from
    a superseded task is never returned.

    Returns ``None`` when the transcript is missing/unreadable or no
    verdict exists in the current task scope.
    """
    text = _read_transcript_text(transcript_path)
    if not text:
        return None
    patterns = _verdict_patterns(verdicts)
    if not patterns:
        return None

    lines = text.split("\n")
    # Text blocks of assistant records in the current (newest-first)
    # segment.  Reset when the scan crosses a non-task *wakeup* record;
    # tool results belong to the same turn and keep it.
    segment_texts: list[str] = []
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        if _ASSISTANT_RE.search(line):
            # A verdict is visible output: only a text-bearing assistant
            # record can carry one.  Thinking blocks and tool_use inputs are
            # raw JSON strings too, so a Grep pattern for the keyword or a
            # file the agent wrote would otherwise match (the task-scoped
            # scan reaches records the latest-turn scan never entered).
            if not _TEXT_BLOCK_RE.search(line):
                continue
            rec = _parse_record(line)
            this_text = _record_text(rec)
            if not this_text:
                continue
            for verdict, pat in patterns:
                if (verdict in line and pat.search(line)
                        and _text_line_is_verdict(this_text, verdict)):
                    turn_text = _turn_text(
                        lines, idx, this_text, segment_texts)
                    return VerdictHit(
                        verdict=verdict,
                        text=turn_text,
                        turn_id=str((rec or {}).get("uuid") or ""),
                        timestamp=str((rec or {}).get("timestamp") or ""),
                        line_index=idx,
                    )
            segment_texts.append(this_text)
            continue
        if _USER_RE.search(line):
            rec = _parse_record(line)
            if rec is not None and _is_tool_result_record(rec):
                # Part of the same assistant turn: keep the text already
                # collected after the verdict so ``VerdictHit.text`` covers
                # the whole turn.
                continue
            if rec is not None and _user_record_is_non_task(rec):
                segment_texts = []
                continue
            # Genuine task boundary — older assistant output belongs to a
            # superseded task.
            break
        # Meta/unknown record (last-prompt, permission-mode, attachment,
        # system, …) — skip without terminating the scan.
    return None


def extract_verdict_from_transcript(
    transcript_path: str | Path | None,
    verdicts: tuple[str, ...],
) -> str | None:
    """Return the current task's verdict keyword emitted by the assistant.

    Returns ``None`` when the transcript is missing, unreadable, or no
    assistant turn in the current task scope contains any of *verdicts* on
    its own line.  See :func:`find_verdict_turn` for the task-scoping
    rules.
    """
    hit = find_verdict_turn(transcript_path, verdicts)
    return hit.verdict if hit else None


_REASON_RE = re.compile(
    r'(?im)^\s*[*`]*\s*reason\s*[*`]*\s*[:\-]\s*[*`]*\s*(.+?)\s*[*`]*\s*$'
)


# Mirrors the QA / review loops' ``ALL_VERDICTS`` so a caller that does not
# care which task the verdict belongs to (or only wants a reason for a
# scenario verdict) does not have to pass the tuple.  Kept local rather than
# imported: ``qa_loop`` imports this module, so importing back would cycle.
_DEFAULT_REASON_VERDICTS = ("INPUT_REQUIRED", "NEEDS_WORK", "PASS")


def extract_reason_from_text(text: str) -> str:
    """Return the last ``Reason: ...`` line in *text* (``""`` when none).

    Shared by the transcript helper and callers that already hold a
    :class:`VerdictHit` and must not re-read the transcript (a re-read can
    land on a different turn if the worker appends a wakeup turn in
    between).
    """
    last = ""
    for line in (text or "").splitlines():
        m = _REASON_RE.match(line)
        if m:
            last = m.group(1).strip()
    return last


def extract_verdict_reason_from_transcript(
    transcript_path: str | Path | None,
    verdicts: tuple[str, ...] = _DEFAULT_REASON_VERDICTS,
) -> str:
    """Return the ``Reason: ...`` line from the turn that carried the verdict.

    Scenario runners are prompted to emit a single ``Reason: <one sentence>``
    line immediately before their verdict keyword.  Reading the *verdict
    turn* (rather than the latest turn) keeps the reason attached to the
    verdict when a ``/loop`` wakeup or Monitor notification adds a later
    postscript (pr-8efa789).  We pick the last such line in the turn so the
    line nearest the verdict wins if the agent wrote multiple.  Falls back
    to the latest assistant turn when the transcript holds no verdict in
    the current task scope.  Returns an empty string when no reason line is
    present.
    """
    hit = find_verdict_turn(transcript_path, verdicts)
    text = hit.text if hit else read_latest_assistant_text(transcript_path)
    return extract_reason_from_text(text)


def read_latest_assistant_text(transcript_path: str | Path | None) -> str:
    """Return the concatenated ``text`` content of the latest assistant turn.

    Used by callers that need to post-process the assistant's output
    (e.g. :func:`pm_core.loop_shared.extract_between_markers` scanning
    for ``REFINED_STEPS_START``/``REFINED_STEPS_END`` markers).  Returns
    an empty string when the transcript is missing or the latest turn
    has no text content.

    This *is* mildly schema-dependent: it parses each assistant JSONL
    record and looks for ``message.content[].type == "text"`` entries.
    If Anthropic changes that shape we update this helper.  Verdict
    detection (:func:`find_verdict_turn`) still matches the raw JSONL
    bytes for the keyword, so a shape change would only cost the returned
    turn *text*, not the verdict itself.
    """
    text = _read_transcript_text(transcript_path)
    if not text:
        return ""

    # Walk backward, collect the contiguous block of assistant records
    # that forms the latest turn (i.e. everything between the last user
    # record and the end of file, bypassing meta records).
    turn_lines: list[str] = []
    in_turn = False
    for line in reversed(text.split("\n")):
        is_assistant = bool(_ASSISTANT_RE.search(line))
        is_user = bool(_USER_RE.search(line))
        if not in_turn:
            if is_assistant:
                in_turn = True
                turn_lines.append(line)
            continue
        if is_user:
            break
        if is_assistant:
            turn_lines.append(line)

    turn_lines.reverse()  # back to file order
    chunks: list[str] = []
    for raw in turn_lines:
        piece = _record_text(_parse_record(raw))
        if piece:
            chunks.append(piece)
    return "\n".join(chunks)
