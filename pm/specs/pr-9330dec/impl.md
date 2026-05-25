# pr-9330dec — Home-window line truncation undercounts emoji width

## Problem

`pm_core/home_window/pr_list.py` renders the `pm-home` window by polling the
PR list and fitting each line to the pane. The fitting helper `_truncate`
originally cut lines to `width` **code points** (`len(line) <= width`,
`line[:width-1] + "…"`).

But the lines come from `format_pr_line`
(`pm_core/cli/helpers.py:273`), which prepends a status emoji from
`PR_STATUS_ICONS` (`helpers.py:262`): `⏳ 🔨 👀 🧪 ✅ 🚫`. Every one of
these is a single code point that renders as **2 terminal cells**. A line
truncated to exactly `width` code points therefore renders at `width + 1`
cells (more if the title also carries wide chars), overflows the last
column, and **soft-wraps** on a narrow pane — pushing the header and the
most-recent PR off-screen and leaving a stray `…` continuation row.

This violates pr-28bda5d's own acceptance R5 ("no soft-wrap artifacts and
no line exceeding the pane width") and R4 ("no leftover wrapped output").
pr-28bda5d (`pm/specs/pr-28bda5d/impl.md:76-81`) explicitly scoped
wide-char awareness **out** and deferred it here, on the (incorrect)
premise that `format_pr_line` is plain ASCII.

## Current state (important)

The fix **already landed in `master`** as commit `f07b95f5`
("qa: measure display width in home `_truncate` so wide emoji don't
soft-wrap"), authored during pr-28bda5d's QA pass. This branch inherits it,
so `pm_core/home_window/pr_list.py` already contains:

- `_char_width(ch)` — 0 for combining marks, 2 for
  `unicodedata.east_asian_width(ch) in ("W", "F")`, else 1.
- `_display_width(s)` — sum of `_char_width` over the string.
- `_truncate` — fits by display width, reserving 1 cell for the ellipsis.
- `_compose` — sizes the ruler by `_display_width(head)`.

All six `PR_STATUS_ICONS` glyphs are classified `W` by
`unicodedata.east_asian_width` (verified U+23F3, U+1F528, U+1F440, U+1F9EA,
U+2705, U+1F6AB → all `W` → 2 cells), so the zero-dependency stdlib path
correctly fixes the stated bug **without** adding `wcwidth`.

There is one existing test
(`tests/test_home_window.py::TestPrList::test_truncate_measures_display_width_not_codepoints`)
but it only exercises a single hardcoded `⏳` literal and a hand-built
string — it does **not** go through `format_pr_line` or cover the full
`PR_STATUS_ICONS` set.

## Requirements

1. **R1 — Truncate by display width, not code points.** `_truncate` must
   measure terminal cells so its output never exceeds the requested width.
   *(Satisfied by master `f07b95f5`.)*

2. **R2 — Status emoji counted as 2 cells.** Each glyph in
   `PR_STATUS_ICONS` must contribute 2 to the measured width. *(Satisfied;
   all six are East-Asian `W`.)*

3. **R3 — Regression coverage tied to the real source.** Add a test that
   drives the *actual* `format_pr_line` + `PR_STATUS_ICONS` through
   `_truncate` for every status and asserts `_display_width(out) <= width`
   at boundary widths. This guards the exact failure mode and would catch a
   future status emoji that `east_asian_width` classifies as narrow (`N`/`A`)
   — something the existing single-literal test would miss. **This is the
   deliverable for this PR**, since the production fix already merged.

## Implicit Requirements

- **No new dependency.** The deferral note named "wcwidth *or* a
  unicodedata helper"; master took the stdlib path. Keep it — adding
  `wcwidth` now would be churn with no behavior change for the status set.
- **Over-count is safe, under-count is the bug.** Truncation must never
  *under*-count a glyph's width (that re-introduces soft-wrap). Over-counting
  (e.g. treating a variation selector as 1 cell) only truncates slightly
  earlier and never overflows — acceptable.
- The ruler under the header must match the header's display width so it
  doesn't itself overflow (`_compose`).

## Ambiguities

- **Should `_truncate` be re-implemented in this PR?** No. A correct,
  tested fix is already in `master`. Re-writing it would be pure churn and
  risks regressions. This PR adds the missing regression test that ties the
  guard to the live emoji source. *(Resolved.)*
- **wcwidth vs unicodedata?** Resolved in favor of the already-merged
  unicodedata approach (zero dependency, correct for the status set).

## Edge Cases

- **`width <= 0`** → `""`; **`width == 1`** → `"…"`. Already handled.
- **A wide glyph straddling the truncation boundary** — the char-by-char
  budget loop in `_truncate` stops before `used + w > budget`, so a 2-cell
  glyph that won't fit is dropped rather than half-emitted. Covered by the
  boundary widths in the new test.
- **Complex emoji in PR titles (ZWJ sequences, `U+FE0F` variation
  selectors).** Out of scope for the status-icon bug. `east_asian_width`
  may mis-measure these, but the error is in the safe (over-count)
  direction for `U+FE0F` (combining-class 0 → counted as 1) and titles are
  not the reported failure surface. Noted, not fixed.
- **Unknown status** → `format_pr_line` emits a 1-cell `?` fallback; the
  test uses only real statuses from `PR_STATUS_ICONS`.
