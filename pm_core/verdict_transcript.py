"""JSONL transcript-based verdict extraction.

Replaces pane-scraping verdict detection.  Walks a Claude Code
transcript (``~/.claude/projects/<mangled>/<session-id>.jsonl``) in
reverse and returns the verdict keyword emitted in the *latest*
assistant turn — if any.

Design:
  * Schema-light.  We match the raw JSON-encoded bytes, not the message
    shape.  The only structural assumption is that each JSONL line is a
    single record and that assistant records contain the substring
    ``"type":"assistant"`` while user records contain ``"type":"user"``.
    Both have held stable across Claude Code versions and are used by
    Anthropic's own tooling.
  * Latest-turn only.  After an ``idle_prompt`` hook fires we only care
    about what Claude just said — returning a stale verdict from an
    earlier turn would misreport.  We walk backward, enter the latest
    assistant turn at its last line, and stop at the next user line.
  * Boundary-aware.  A verdict keyword must sit on its own text-line
    within the assistant's output, i.e. bounded by a JSON newline-escape
    (``\\n`` / ``\\r\\n``) or a JSON string quote.  That rejects
    incidental mentions like "PASS this file" while accepting bare
    ``PASS`` as the entire message.
  * Longest-match-first.  ``PASS`` is a prefix of
    ``PASS_WITH_SUGGESTIONS``; verdicts are scanned in descending
    length order so the more specific keyword wins.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


# Tolerate whitespace between key and value (``"type":"assistant"`` from
# real Claude transcripts, ``"type": "assistant"`` from ``json.dumps``).
_ASSISTANT_RE = re.compile(r'"type"\s*:\s*"assistant"')
_USER_RE = re.compile(r'"type"\s*:\s*"user"')


def extract_verdict_from_transcript(
    transcript_path: str | Path | None,
    verdicts: tuple[str, ...],
) -> str | None:
    """Return the latest verdict keyword emitted by the assistant.

    Returns ``None`` when the transcript is missing, unreadable, or the
    latest assistant turn does not contain any of *verdicts* on its own
    line.
    """
    if not transcript_path:
        return None
    try:
        text = Path(transcript_path).read_text(errors="replace")
    except (OSError, FileNotFoundError):
        return None
    if not text:
        return None

    ordered = sorted({v for v in verdicts if v}, key=len, reverse=True)
    if not ordered:
        return None
    patterns = [
        (v, re.compile(r'(?:\\[nr]|")' + re.escape(v) + r'(?:\\[nr]|")'))
        for v in ordered
    ]

    in_turn = False
    for line in reversed(text.splitlines()):
        is_assistant = bool(_ASSISTANT_RE.search(line))
        is_user = bool(_USER_RE.search(line))
        if not in_turn:
            if is_assistant:
                in_turn = True
            else:
                continue
        elif is_user:
            # Crossed the boundary of the latest assistant turn.
            break
        if not is_assistant:
            # Meta lines (e.g. last-prompt, permission-mode) within the
            # turn window — skip but do not terminate.
            continue
        for verdict, pat in patterns:
            if verdict in line and pat.search(line):
                return verdict
    return None


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
    if not transcript_path:
        return ""
    try:
        text = Path(transcript_path).read_text(errors="replace")
    except (OSError, FileNotFoundError):
        return ""
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
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        msg = rec.get("message") if isinstance(rec, dict) else None
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                piece = block.get("text")
                if isinstance(piece, str):
                    chunks.append(piece)
    return "\n".join(chunks)
