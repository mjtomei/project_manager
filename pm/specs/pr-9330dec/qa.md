# pr-9330dec — QA Spec: Home-window line truncation undercounts emoji width

## Summary

The `pm-home` tmux window runs an in-process loop (`pm_core.home_window.pr_list`)
that polls the project's open PRs, formats each with `format_pr_line` (which
prepends a 2-cell status emoji from `PR_STATUS_ICONS`: ⏳🔨👀🧪✅🚫), and
truncates each line to the pane width before painting. The bug: `_truncate`
originally measured **code points**, so a line cut to `width` code points
rendered at `width + 1` terminal cells, overflowed the last column, and
**soft-wrapped** on a narrow pane — pushing the header off-screen and leaving a
stray `…` continuation row.

The production fix already landed in `master` (commit `f07b95f5`): `_truncate`
now measures **display width** via `unicodedata.east_asian_width` (W/F = 2
cells, combining marks = 0), reserving 1 cell for the ellipsis; `_compose`
sizes the header ruler by display width. All six status glyphs classify as `W`,
so no third-party dependency is needed. **This PR's deliverable is the missing
regression test** that drives the real `format_pr_line` + every status through
`_truncate` at boundary widths.

## Requirements

### R1 — Narrow home pane renders without soft-wrap
- **Given** a project with at least one open PR whose title is long enough to
  overflow a narrow pane, and the `pm-home` window visible
- **When** the user shrinks the home pane to a mobile-mode width (e.g. < 60
  cols, well under the 120-col mobile threshold)
- **Then** each rendered PR line fits within the pane width — no line wraps to a
  second row, no stray trailing character or extra `…` row appears at the
  bottom, and the header (`pm pr list -t --open …`) and its `===` ruler stay
  pinned at the top with the most-recent PR directly below.

### R2 — Every status emoji counts as two cells
- **Given** a project containing PRs across the full range of statuses
  (pending, in_progress, in_review, qa, merged/closed/blocked map to icons
  ⏳🔨👀🧪✅🚫)
- **When** the home pane is narrow enough that those lines truncate
- **Then** the truncation accounts for the 2-cell emoji on every status — no
  status renders one cell wider than the pane and soft-wraps. (Closed/merged
  PRs are filtered out of the home list, so this is exercised via the
  regression test and via the live statuses that remain visible.)

### R3 — Regression test passes and is tied to the live emoji source
- **Given** the PR branch checked out
- **When** the user runs the home-window test suite
- **Then** the new regression test
  (`test_truncate_fits_every_status_emoji_from_format_pr_line`) passes — it
  drives the real `format_pr_line` for every entry in `PR_STATUS_ICONS` through
  `_truncate` at boundary widths and asserts the result never exceeds the
  requested width — and the full home-window test module passes.

### R4 — Header ruler matches header display width
- **Given** the home window rendering a header that fits the pane
- **When** the pane is wide enough to show the full header
- **Then** the `===` ruler underneath spans the header's display width and does
  not itself overflow or wrap.

## Setup

- Install pm editable into a venv and confirm `pm which` points at the clone,
  not `/opt/pm-src` (per `tui-manual-test.md`).
- Create a throwaway git project, `pm init --backend local --no-import`, add
  several PRs with `pm pr add`, including at least one with a deliberately long
  title (50+ chars). Statuses can be varied by editing `pm/project.yaml` once at
  bootstrap (the only sanctioned hand-edit), then driving everything else
  through the CLI/TUI.
- Start the session with `pm session` (ignore the no-TTY attach error). The
  `pm-home` window is created automatically.
- To observe the home pane at a controlled width, resize the tmux window/pane
  with `tmux resize-window`/`resize-pane` or attach a recorder client sized
  narrow (per `tmux-screen-recording.md`).

## Edge Cases

- **Very narrow widths (1–7 cells).** Given the home pane shrunk to a handful of
  columns, when it repaints, then output is still width-bounded: width ≤ 0 → an
  empty line, width = 1 → a lone `…`, and a 2-cell emoji that won't fit in the
  remaining budget is dropped rather than half-emitted (no half-glyph, no
  overflow).
- **Wide chars in the PR title itself**, not just the status icon. Given a PR
  whose title contains CJK or other East-Asian Wide characters, when the pane
  is narrow, then the line still fits within the pane (title wide chars also
  counted as 2 cells).
- **Empty list / error states.** Given a project with no open PRs (or a load
  error), when the home pane renders narrow, then the `No open PRs.` line (or
  the error line) is itself truncated to width and does not wrap.
- **Dynamic resize.** Given the home window painted at a wide size, when the
  user shrinks it via a window resize (SIGWINCH), then the next repaint refits
  every line to the new narrower width with no leftover wrapped rows from the
  prior wide render.

## Concurrent Use

Shared resources touched by the change:
- The **`pm-home` tmux window output** — a single pane rendered to every
  attached client; with `window-size=smallest` the render follows the smallest
  client.
- The **refresh sentinel file** (`~/.pm/.../runtime/home-refresh-<base>`) —
  touched by `refresh()` from any session, polled by the loop.
- **`pm/project.yaml`** — read each tick by the loop, written by `pm pr`
  commands run from any pane/session.

Concurrent scenario: while the home loop renders, a second actor mutates the PR
list (adds/updates a PR, triggering a refresh) and a second narrower client
attaches simultaneously. The render must stay width-bounded for the smallest
client and never soft-wrap during the churn.

## Pass/Fail Criteria

- **PASS**: At every observed pane width — including mobile-mode narrow widths
  and the 1–7 cell extremes — no rendered home line exceeds the pane width and
  no line soft-wraps; the header + ruler stay at the top; the regression test
  and the home-window test module pass.
- **FAIL**: Any home line wraps to a second row; a stray trailing character or
  extra `…` row appears at the bottom; the header scrolls off the top; the
  ruler overflows; or the regression test fails.

## Ambiguities

- **Should `_truncate` be reimplemented in this PR?** No — the fix is already in
  `master`; this PR adds only the regression test. QA verifies the user-visible
  behavior (no soft-wrap) plus the regression test, rather than a reimplemented
  code path. *(Resolved.)*
- **wcwidth vs unicodedata?** Resolved in favor of the already-merged stdlib
  `unicodedata` path; all six status glyphs are East-Asian Wide. *(Resolved.)*
- **Closed/merged PRs are filtered from the home list**, so their icons (✅🚫)
  are not directly visible in the live pane. They are still exercised through
  the regression test, which iterates the full `PR_STATUS_ICONS` map.
  *(Resolved.)*
