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

    lines = text.splitlines()
    # Text blocks of assistant records in the current (newest-first)
    # segment.  Reset when the scan crosses a non-task user record.
    segment_texts: list[str] = []
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        if _ASSISTANT_RE.search(line):
            for verdict, pat in patterns:
                if verdict in line and pat.search(line):
                    rec = _parse_record(line)
                    this_text = _record_text(rec)
                    turn_text = _turn_text(
                        lines, idx, this_text, segment_texts)
                    return VerdictHit(
                        verdict=verdict,
                        text=turn_text,
                        turn_id=str((rec or {}).get("uuid") or ""),
                        timestamp=str((rec or {}).get("timestamp") or ""),
                        line_index=idx,
                    )
            # Only text-bearing records contribute to the turn text; skip
            # the JSON parse for thinking/tool_use-only records.
            if _TEXT_BLOCK_RE.search(line):
                this_text = _record_text(_parse_record(line))
                if this_text:
                    segment_texts.append(this_text)
            continue
        if _USER_RE.search(line):
            rec = _parse_record(line)
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


_DEFAULT_REASON_VERDICTS = ("INPUT_REQUIRED", "NEEDS_WORK", "PASS")


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
    if not text:
        return ""
    last = ""
    for line in text.splitlines():
        m = _REASON_RE.match(line)
        if m:
            last = m.group(1).strip()
    return last


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
    extraction (:func:`extract_verdict_from_transcript`) remains purely
    text-based and is not affected.
    """
    text = _read_transcript_text(transcript_path)
    if not text:
        return ""

    # Walk backward, collect the contiguous block of assistant records
    # that forms the latest turn (i.e. everything between the last user
    # record and the end of file, bypassing meta records).
    turn_lines: list[str] = []
    in_turn = False
    for line in reversed(text.splitlines()):
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
