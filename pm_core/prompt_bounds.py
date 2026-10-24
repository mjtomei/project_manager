"""Size-aware helpers for prompts passed to claude as one argv entry.

``claude`` receives a session prompt as a single ``argv`` entry.  Linux caps
one argument at ``MAX_ARG_STRLEN`` (128 KiB / 131072 bytes, including the
terminating NUL); exceeding it makes ``execve`` fail with ``E2BIG``
(``OSError [Errno 7] Argument list too long``).  ``PROMPT_ARG_LIMIT`` stays
well under that cap so prompt builders can degrade gracefully before the
launcher has to fall back to file-backed delivery.

Builders inline collections (PR notes, specs, sibling PRs, QA scenarios,
instruction libraries, ...) whose size grows with project age.  The helpers
here keep those blocks bounded.  When a helper trims, it appends an explicit
omission marker naming what was dropped and how to read the full detail —
never silently dropping evidence or instructions.
"""

from __future__ import annotations

from typing import Callable, Iterable, TypeVar

T = TypeVar("T")

# A single argv entry cannot exceed MAX_ARG_STRLEN; leave headroom so a
# builder that degrades "just in time" still lands under the hard cap.
PROMPT_ARG_LIMIT = 120_000
MAX_ARG_STRLEN = 131_072

# Per-block defaults.  Static prompt text runs 4-19 KB; these leave room for
# it while keeping the assembled prompt under PROMPT_ARG_LIMIT.  Callers may
# pass tighter budgets; these are the shared fallbacks.
PR_NOTES_BUDGET = 35_000
PR_NOTE_SUMMARY_CHARS = 200
SPEC_BUDGET = 30_000
SESSION_NOTES_BUDGET = 8_000
QA_CHILD_STEPS_BUDGET = 20_000
CONCRETIZE_INSTRUCTION_BUDGET = 20_000
PLAN_CONTEXT_MAX_SIBLINGS = 25
LIBRARY_ITEMS_MAX = 20
MOCKS_BUDGET = 12_000
QA_SCENARIOS_MAX = 40
QA_SCENARIO_REASON_CHARS = 200
INTEGRATION_MAX_PATHS = 20
ARTIFACT_PATHS_MAX = 20
WATCHER_MANAGED_MAX = 40
MERGE_ERROR_MAX_LINES = 60
DEPS_MAX = 40


class PromptTooLargeError(RuntimeError):
    """A prompt cannot be delivered as one argv entry.

    Raised when a prompt exceeds :data:`PROMPT_ARG_LIMIT` and no writable
    location exists for file-backed bootstrap delivery.  Carries the size and
    limit so callers can report the failure without parsing a raw OSError.
    """

    def __init__(self, size: int, limit: int = PROMPT_ARG_LIMIT,
                 what: str = "prompt"):
        self.size = size
        self.limit = limit
        self.what = what
        super().__init__(
            f"{what} is {size} bytes, over the {limit}-byte argv limit "
            f"(MAX_ARG_STRLEN is {MAX_ARG_STRLEN}). Reduce inlined detail or "
            f"provide a writable directory for file-backed delivery."
        )


def prompt_bytes(text: str) -> int:
    """Byte length of *text* as argv would measure it (UTF-8).

    Characters and bytes differ for non-ASCII text; MAX_ARG_STRLEN counts
    bytes, so every size check must too.
    """
    return len(text.encode("utf-8"))


def prompt_fits(text: str, limit: int = PROMPT_ARG_LIMIT) -> bool:
    """True when *text* fits one argv entry under *limit*."""
    return prompt_bytes(text) <= limit


def _prefix_within(text: str, max_bytes: int) -> str:
    """Longest prefix of *text* whose UTF-8 encoding is <= *max_bytes*."""
    if max_bytes <= 0:
        return ""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if prompt_bytes(text[:mid]) <= max_bytes:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def _suffix_within(text: str, max_bytes: int) -> str:
    """Longest suffix of *text* whose UTF-8 encoding is <= *max_bytes*."""
    if max_bytes <= 0:
        return ""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if prompt_bytes(text[len(text) - mid:]) <= max_bytes:
            lo = mid
        else:
            hi = mid - 1
    return text[len(text) - lo:] if lo else ""


def _omission_text(note: str | Callable[[int], str] | None, omitted: int) -> str:
    if callable(note):
        return note(omitted)
    if note:
        return note
    return f"... ({omitted} more omitted)"


def bounded_join(
    items: Iterable[T],
    formatter: Callable[[T], str],
    *,
    max_items: int | None = None,
    max_bytes: int | None = None,
    keep: str = "oldest",
    separator: str = "\n",
    omitted_note: str | Callable[[int], str] | None = None,
) -> str:
    """Format and join *items*, stopping at *max_items* / *max_bytes*.

    ``keep="oldest"`` preserves the leading items (default); ``keep="newest"``
    preserves the trailing items and restores their original order in the
    output, so the most recent handoff notes survive.

    *omitted_note* may be a string or a callable taking the omitted count; it
    is appended after the joined text when anything was dropped.  ``None``
    uses a generic marker.  An empty collection returns ``""`` with no marker.
    """
    seq = list(items)
    if keep == "newest":
        seq.reverse()

    kept: list[str] = []
    used = 0
    sep_bytes = prompt_bytes(separator)
    for item in seq:
        if max_items is not None and len(kept) >= max_items:
            break
        rendered = formatter(item)
        cost = prompt_bytes(rendered) + (sep_bytes if kept else 0)
        if max_bytes is not None and used + cost > max_bytes:
            break
        kept.append(rendered)
        used += cost

    if keep == "newest":
        kept.reverse()

    text = separator.join(kept)
    omitted = len(seq) - len(kept)
    if omitted > 0:
        marker = _omission_text(omitted_note, omitted)
        text = f"{text}{separator}{marker}" if text else marker
    return text


def bounded_text(
    text: str,
    *,
    max_bytes: int,
    pointer: str,
    label: str = "content",
    head_ratio: float = 0.75,
) -> str:
    """Return *text* unchanged when it fits; else head + marker + tail.

    Keeps the beginning (requirements, setup) and the end (verdicts, pass/fail
    criteria) so the session still sees the load-bearing parts.  The marker
    names *pointer* — a command or file path for the full text — so nothing is
    lost without a way to retrieve it.
    """
    if prompt_bytes(text) <= max_bytes:
        return text

    marker = (
        f"\n\n[... {label} truncated to fit the prompt size limit. "
        f"Read the full text: {pointer} ...]\n\n"
    )
    budget = max_bytes - prompt_bytes(marker)
    if budget <= 0:
        # Even the marker does not fit; return the marker alone so the caller
        # still gets an actionable pointer instead of a silently empty block.
        return marker.strip()
    head_budget = int(budget * head_ratio)
    tail_budget = budget - head_budget
    head = _prefix_within(text, head_budget).rstrip()
    tail = _suffix_within(text, tail_budget).lstrip()
    if not head:
        return marker.strip() + tail
    if not tail:
        return head + marker.strip()
    return head + marker + tail


def bounded_lines(
    text: str,
    *,
    max_lines: int,
    head_ratio: float = 0.25,
    max_bytes: int | None = None,
    pointer: str | None = None,
    label: str = "output",
) -> str:
    """Head/tail truncate *text* by line count, then optionally by bytes.

    Mirrors the verification prompt's existing head/tail behaviour: keep the
    setup at the top and the verdict at the bottom.  When *max_bytes* is set
    the result is passed through :func:`bounded_text` so long lines cannot
    defeat the line bound.
    """
    lines = text.splitlines()
    if len(lines) > max_lines:
        head = max(1, int(max_lines * head_ratio))
        tail = max(1, max_lines - head)
        omitted = len(lines) - head - tail
        text = (
            "\n".join(lines[:head])
            + f"\n\n[... {omitted} lines omitted ...]\n\n"
            + "\n".join(lines[-tail:])
        )
    if max_bytes is not None and pointer is not None:
        text = bounded_text(text, max_bytes=max_bytes, pointer=pointer,
                            label=label)
    return text
