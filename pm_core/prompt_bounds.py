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
# One-line listings (sibling PRs, a PR's dependencies, the plan/other-PR
# lists the plan builders inline) are count-capped, but a count cap alone does
# not bound the listing: the lines carry user-authored titles, so 25 siblings
# with long titles measured 180 KB (over PROMPT_ARG_LIMIT).  This byte budget
# bounds the product; real listings in this repo run 0.4-14.5 KB, so it only
# bites on pathological titles.
PLAN_LIST_BUDGET = 20_000
# Count cap for the same listings; the byte budget above bounds the product.
PLAN_LIST_MAX = 40
LIBRARY_ITEMS_MAX = 20
# The QA library summary is count-capped per category, but the items carry
# user-authored descriptions, so a count cap does not bound the listing — the
# same cap-times-item-size defect the plan listings had (20 items with long
# descriptions measured 300 KB, and the QA planner prompt that E2BIG'd in the
# field inlines this block).  Each category gets a byte budget, and the joined
# block gets an aggregate one so three categories cannot multiply it.
LIBRARY_LIST_BUDGET = 6_000
LIBRARY_TOTAL_BUDGET = 12_000
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

    The marker is appended *after* the budget is exhausted, so the result can
    exceed ``max_bytes`` by the marker's length.  Callers that need an exact
    ceiling (e.g. accumulating a shared budget) should use
    :func:`bounded_text`, which subtracts the marker's bytes first.
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
    defeat the line bound; *pointer* names where the full text lives (a
    generic fallback is used when the caller has none), so the byte bound is
    never silently dropped.
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
    if max_bytes is not None:
        text = bounded_text(text, max_bytes=max_bytes,
                            pointer=pointer or "the full output on disk",
                            label=label)
    return text


# Slack added to each shrink step in fit_prompt so the re-render lands under
# the limit even if a block's own marker shifts the byte count slightly.
_FIT_MARKER_SLACK = 300


def fit_prompt(
    render: Callable[[dict[str, str]], str],
    blocks: dict[str, tuple[str, str, str]],
    *,
    limit: int = PROMPT_ARG_LIMIT,
    min_bytes: int = 2_000,
) -> str:
    """Assemble a prompt, abbreviating blocks until it fits one argv entry.

    The per-block budgets in this module bound each block on its own, but
    their *sum* plus a builder's static text can still exceed the limit: a PR
    that is large in several dimensions at once (many PR notes, a big spec,
    many QA scenarios, a long description) can push a builder whose static
    text is already ~19 KB over the cap, even though every block is within its
    own budget.

    *render* takes a mapping of block name to (possibly abbreviated) text and
    returns the finished prompt, so the caller keeps its own static text and
    block placement.  *blocks* maps each shrinkable name to ``(text, pointer,
    label)``.  The largest blocks are shrunk first, each with a head+tail
    marker naming its *pointer*, until the render fits.

    Blocks are never shrunk below *min_bytes*.  If the static text alone is
    over the limit this returns the render unchanged — the launcher's
    file-backed bootstrap then carries the complete prompt, so nothing is
    lost.
    """
    texts = {name: text for name, (text, _pointer, _label) in blocks.items()}
    prompt = render(texts)
    if prompt_bytes(prompt) <= limit:
        return prompt

    for name in sorted(blocks, key=lambda n: -prompt_bytes(texts[n])):
        over = prompt_bytes(prompt) - limit
        if over <= 0:
            break
        current = prompt_bytes(texts[name])
        target = max(min_bytes, current - over - _FIT_MARKER_SLACK)
        if target >= current:
            continue
        _text, pointer, label = blocks[name]
        texts[name] = bounded_text(texts[name], max_bytes=target,
                                   pointer=pointer, label=label)
        prompt = render(texts)
    return prompt
