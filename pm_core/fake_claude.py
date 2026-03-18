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


def run_fake_claude(
    verdict: str,
    preamble: int = 3,
    delay: float = 0.0,
    body: str | None = None,
    stream: bool = False,
) -> None:
    """Execute the fake Claude session.

    Args:
        verdict: Verdict keyword to emit (required).
        preamble: Number of filler prose lines to write before the verdict.
        delay: Seconds to sleep before writing the verdict block.
        body: Custom text between _START/_END markers (block verdicts only).
        stream: Write output character-by-character to simulate streaming.
    """
    upper = verdict.upper()

    # Write preamble prose
    for i in range(preamble):
        line = _PREAMBLE_LINES[i % len(_PREAMBLE_LINES)]
        _write(line + "\n", stream=stream)

    # Optional delay before verdict
    if delay > 0:
        time.sleep(delay)

    # Determine whether this is a single-line or block verdict
    if upper in SINGLE_LINE_VERDICTS:
        _write("\n" + upper + "\n", stream=stream)
        return

    block_name = _resolve_block_name(upper)
    if block_name is None:
        # Unknown verdict — emit it as-is on its own line (best-effort)
        _write("\n" + upper + "\n", stream=stream)
        return

    start_marker, end_marker = BLOCK_VERDICTS[block_name]
    body_text = body if body is not None else _DEFAULT_BODIES.get(block_name, "")

    _write("\n" + start_marker + "\n", stream=stream)
    if body_text:
        _write(body_text.rstrip("\n") + "\n", stream=stream)
    _write(end_marker + "\n", stream=stream)
