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

import re
from pathlib import Path


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

    # Tolerate whitespace between key and value ( ``"type":"assistant"``
    # from real transcripts, ``"type": "assistant"`` from ``json.dumps``).
    ASSISTANT_RE = re.compile(r'"type"\s*:\s*"assistant"')
    USER_RE = re.compile(r'"type"\s*:\s*"user"')

    in_turn = False
    for line in reversed(text.splitlines()):
        is_assistant = bool(ASSISTANT_RE.search(line))
        is_user = bool(USER_RE.search(line))
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
