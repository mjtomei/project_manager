"""Fake Claude session for integration testing.

Writes realistic-looking output and emits a specified verdict so tests can
exercise verdict detection, review loop state machines, and QA loop
transitions without real API calls.
"""

import sys
import time

# ---------------------------------------------------------------------------
# Verdict catalogue
# ---------------------------------------------------------------------------

# Single-line verdicts: emitted as bare keywords on their own line
SINGLE_LINE_VERDICTS = (
    "PASS",
    "PASS_WITH_SUGGESTIONS",
    "NEEDS_WORK",
    "INPUT_REQUIRED",
    "VERIFIED",
)

# Block-style verdicts: emitted as START … END pairs
BLOCK_VERDICTS = {
    "FLAGGED": ("FLAGGED_START", "FLAGGED_END"),
    "REFINED_STEPS": ("REFINED_STEPS_START", "REFINED_STEPS_END"),
    "QA_PLAN": ("QA_PLAN_START", "QA_PLAN_END"),
}

# Accept both the short name (e.g. "FLAGGED") and the bare end-marker
# (e.g. "FLAGGED_END") as the --verdict argument for block verdicts.
ALL_VERDICTS = (
    list(SINGLE_LINE_VERDICTS)
    + list(BLOCK_VERDICTS.keys())
    + [end for _, end in BLOCK_VERDICTS.values()]
)

# ---------------------------------------------------------------------------
# Per-session-type verdict constraints
# ---------------------------------------------------------------------------

# Maps each session type to the verdict names that are valid for it.
# Empty tuple means the session type never emits a verdict (no fake needed).
# Used to validate fake-claude configs and to pick sensible defaults.
SESSION_TYPE_VERDICTS: dict[str, tuple[str, ...]] = {
    "impl":            (),   # implementation: no verdict, interactive coding
    "review":          ("PASS", "PASS_WITH_SUGGESTIONS", "NEEDS_WORK", "INPUT_REQUIRED"),
    "qa":              ("PASS", "NEEDS_WORK", "INPUT_REQUIRED"),  # generic fallback
    "qa_planning":     ("QA_PLAN",),
    "qa_scenario":     ("PASS", "NEEDS_WORK", "INPUT_REQUIRED"),
    "qa_verification": ("VERIFIED", "FLAGGED"),
    "watcher":         (),   # background watcher: no verdict
    "merge":           (),   # merge conflict: no verdict
}


def validate_session_verdicts(session_type: str, verdicts: dict) -> list[str]:
    """Return a list of error strings for verdicts invalid for *session_type*.

    An empty list means the config is valid.  Raises nothing — callers decide
    whether to warn or hard-error.
    """
    if session_type not in SESSION_TYPE_VERDICTS:
        return [f"Unknown session type {session_type!r}. "
                f"Valid types: {sorted(SESSION_TYPE_VERDICTS)}"]
    allowed = SESSION_TYPE_VERDICTS[session_type]
    errors = []
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
    return errors

# ---------------------------------------------------------------------------
# Default placeholder bodies for block verdicts
# ---------------------------------------------------------------------------

_DEFAULT_BODIES = {
    "FLAGGED": "Step 1: FAILED — expected output not produced.",
    "REFINED_STEPS": "1. Build the project\n2. Run the test suite\n3. Verify output",
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
        if upper == end or upper == end.replace("_END", ""):
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


def run_fake_claude(
    verdict: str,
    preamble: int = 3,
    preamble_delay: float = 0.0,
    delay: float = 0.0,
    body: str | None = None,
    body_lines: int = 0,
    body_batch: int = 1,
    body_delay: float = 0.0,
    stream: bool = False,
    char_delay: float = 0.015,
) -> None:
    """Execute the fake Claude session.

    Output sequence:
      1. *preamble* filler lines, with *preamble_delay* between each.
      2. *body_lines* generated lines, emitted *body_batch* at a time
         with *body_delay* between batches.  Useful for testing that the
         verdict poller does not prematurely accept keywords from earlier
         output while new content is still arriving.
      3. Sleep *delay* seconds (simulates overall session duration).
      4. The verdict block.

    Args:
        verdict: Verdict keyword to emit (required).
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
    """
    upper = verdict.upper()
    _w = lambda text: _write(text, stream=stream, char_delay=char_delay)

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

    # 4. Verdict block
    if upper in SINGLE_LINE_VERDICTS:
        _w("\n" + upper + "\n")
        return

    block_name = _resolve_block_name(upper)
    if block_name is None:
        # Unknown verdict — emit as-is (best-effort)
        _w("\n" + upper + "\n")
        return

    start_marker, end_marker = BLOCK_VERDICTS[block_name]
    body_text = body if body is not None else _DEFAULT_BODIES.get(block_name, "")

    _w("\n" + start_marker + "\n")
    if body_text:
        _w(body_text.rstrip("\n") + "\n")
    _w(end_marker + "\n")
