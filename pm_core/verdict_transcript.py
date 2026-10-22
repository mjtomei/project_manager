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
    real = _resolve_transcript_path(transcript_path)
    if real is None:
        return ""
    try:
        return real.read_text(errors="replace")
    except OSError:
        return ""


def _resolve_transcript_path(transcript_path: str | Path | None) -> Path | None:
    """Return a readable path for *transcript_path* (see
    :func:`_read_transcript_text` for the session-id fallback), or None."""
    if not transcript_path:
        return None
    p = Path(transcript_path)
    try:
        if p.exists():
            return p
    except OSError:
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
        return None
    projects_dir = Path.home() / ".claude" / "projects"
    try:
        matches = list(projects_dir.glob(f"*/{sid}.jsonl"))
    except OSError:
        return None
    if not matches:
        return None
    # Pick the most recently modified — handles edge cases where stale
    # files with the same sid linger from a prior run.
    return max(matches, key=lambda m: m.stat().st_mtime)


def extract_verdict_from_transcript(
    transcript_path: str | Path | None,
    verdicts: tuple[str, ...],
) -> str | None:
    """Return the latest verdict keyword emitted by the assistant.

    Returns ``None`` when the transcript is missing, unreadable, or the
    latest assistant turn does not contain any of *verdicts* on its own
    line.
    """
    text = _read_transcript_text(transcript_path)
    if not text:
        return None

    ordered = sorted({v for v in verdicts if v}, key=len, reverse=True)
    if not ordered:
        return None
    # Boundary: JSON newline-escape (``\n`` / ``\r``) or string quote.
    # Between the boundary and the verdict we tolerate markdown bold/code
    # markers (``*``, `` ` ``) so ``**PASS**`` on its own line still
    # matches — the pane-scraping path used to strip those before
    # comparing, and reviewers routinely wrap verdicts in bold.
    patterns = [
        (v, re.compile(
            r'(?:\\[nr]|")[*`]*' + re.escape(v) + r'[*`]*(?:\\[nr]|")'
        ))
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


_REASON_RE = re.compile(
    r'(?im)^\s*[*`]*\s*reason\s*[*`]*\s*[:\-]\s*[*`]*\s*(.+?)\s*[*`]*\s*$'
)


def extract_verdict_reason_from_transcript(
    transcript_path: str | Path | None,
) -> str:
    """Return the latest ``Reason: ...`` line from the latest assistant turn.

    Scenario runners are prompted to emit a single ``Reason: <one sentence>``
    line immediately before their verdict keyword. We pick the *last* such
    line in the turn so the line nearest the verdict wins if the agent wrote
    multiple. Returns an empty string when no reason line is present.
    """
    text = read_latest_assistant_text(transcript_path)
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


# Claude Code echoes local slash commands (``/model``, ``/cost`` …) into the
# transcript as user records; they are not answers to the assistant.
_LOCAL_COMMAND_PREFIXES = ("<command-name>", "<command-message>",
                           "<local-command-stdout>", "<local-command-stderr>")


def is_human_prompt_record(rec: object) -> bool:
    """True when a parsed JSONL record is a prompt the human submitted.

    Tool results are ``"type":"user"`` records too — they carry command
    output, never a human decision, so they never count.  Neither do meta,
    sidechain and compact-summary records or local slash-command echoes.
    """
    if not isinstance(rec, dict) or rec.get("type") != "user":
        return False
    if rec.get("isMeta") or rec.get("isSidechain") or rec.get("isCompactSummary"):
        return False
    msg = rec.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        texts = [content]
    elif isinstance(content, list):
        blocks = [b for b in content if isinstance(b, dict)]
        if not blocks or any(b.get("type") == "tool_result" for b in blocks):
            return False
        texts = [b.get("text") or "" for b in blocks if b.get("type") == "text"]
        if not texts:
            return True  # e.g. a pasted image
    else:
        return False
    text = "".join(texts).lstrip()
    return bool(text) and not text.startswith(_LOCAL_COMMAND_PREFIXES)


def _record_epoch(rec: dict) -> float | None:
    """The record's ISO ``timestamp`` as epoch seconds, or None."""
    from datetime import datetime
    ts = rec.get("timestamp")
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _assistant_text_has_verdict(line: str, verdict: str) -> bool:
    """True when an assistant record's *text* blocks carry *verdict* on its
    own line (tool_use inputs such as ``grep INPUT_REQUIRED`` don't count)."""
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return False
    msg = rec.get("message") if isinstance(rec, dict) else None
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return False
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            for text_line in str(block.get("text") or "").splitlines():
                if text_line.strip().strip("*`").strip() == verdict:
                    return True
    return False


class HumanResponseWatch:
    """Track whether the human answered after the assistant's *verdict* turn.

    Built when a loop starts waiting on a verdict that needs a human (e.g.
    INPUT_REQUIRED).  The constructor scans back from the end of the
    transcript to the latest assistant record carrying *verdict*: a human
    prompt after it means the question was already answered (a TUI restart
    or a fast reply).  :meth:`poll` then reads only the bytes appended since
    the last call.  :attr:`answered_at` is the epoch time of the latest
    answer (the record's ``timestamp``, else the time it was seen), or None
    while the question is unanswered.
    """

    def __init__(self, transcript_path: str | Path | None, verdict: str):
        self._transcript_path = transcript_path
        self.answered_at: float | None = None
        self._offset = 0
        self._partial = b""
        path = _resolve_transcript_path(transcript_path)
        if path is None:
            return
        try:
            data = path.read_bytes()
        except OSError:
            return
        self._offset = len(data)
        last_nl = data.rfind(b"\n")
        self._partial = data[last_nl + 1:]
        # Only an answer *after* the question counts: if the question record
        # can't be found, the latest human prompt may be the iteration's own
        # review prompt, so stay unanswered rather than guess.
        answer = None
        for line in reversed(data[:last_nl + 1].decode(errors="replace").splitlines()):
            if _ASSISTANT_RE.search(line):
                if verdict in line and _assistant_text_has_verdict(line, verdict):
                    self.answered_at = answer
                    break
            elif answer is None and _USER_RE.search(line):
                answer = self._answer_epoch(line)

    @staticmethod
    def _answer_epoch(line: str) -> float | None:
        """Epoch time of *line* when it is a human prompt, else None."""
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not is_human_prompt_record(rec):
            return None
        at = _record_epoch(rec)
        if at is None:
            import time
            at = time.time()
        return at

    def poll(self) -> float | None:
        """Read newly appended records; return :attr:`answered_at`."""
        path = _resolve_transcript_path(self._transcript_path)
        if path is None:
            return self.answered_at
        try:
            with path.open("rb") as f:
                f.seek(self._offset)
                chunk = f.read()
        except OSError:
            return self.answered_at
        if not chunk:
            return self.answered_at
        self._offset += len(chunk)
        data = self._partial + chunk
        last_nl = data.rfind(b"\n")
        self._partial = data[last_nl + 1:]
        for line in data[:last_nl + 1].decode(errors="replace").splitlines():
            at = self._answer_epoch(line) if _USER_RE.search(line) else None
            if at is not None:
                self.answered_at = max(self.answered_at or 0.0, at)
        return self.answered_at

    def rearm(self) -> None:
        """The assistant is waiting on the human again: forget the answer."""
        self.answered_at = None
