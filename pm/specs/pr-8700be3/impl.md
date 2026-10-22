# pr-8700be3 — Compact, highlighted autostart status (impl spec)

## 1. Requirements (grounded in code)

Today the report is built in three places:

- `pm_core/autostart_state.py` — `build_status()` / `_derive()` produce the
  `pm.autostart.status/1` dict (`runs`, `targets`); `status_rows()` flattens it
  into grouped rows; `policy_labels()` names merge policy per row;
  `_progress()` makes the progress token; `format_text()` renders CLI text.
- `pm_core/cli/autostart.py::autostart_status` — `pm autostart status` (text
  via `format_text`, or `--json` dumps the status dict verbatim).  The CLI
  receives the status dict as JSON over the reply file, so everything the
  presenter needs must live in the status dict.
- `pm_core/tui/screens.py::AutoRunsScreen` — the `a` runs popup; renders rows
  itself with Rich `Text` (`_render_rows`, `_POLICY_STYLES`, `_STATE_STYLES`).

R1 — Drop group-implied text.
- `_derive()` builds pending blockers as `"blocked on c (pending, wait-for-merge
  ← f)"` via `held_by_text()`, and `policy_labels()` puts `[wait-for-merge ← f]`
  on every dep under wait target `f`.  New behaviour: a wait target's header
  states `wait-for-merge` once; dep rows under a group whose target holds them
  show no inherited wait label.  Exceptions still shown on dep rows: an
  explicit stop-before-merge mark; a wait hold from a target other than the
  group's when the group target does not itself hold the dep (e.g. dep under
  an auto-merge target held by wait target X → `wait-for-merge ← X`); a dep
  that is itself a wait target under a non-wait group.  An auto-merge target
  held by another wait target keeps `auto-merge` + `wait-for-merge ← X`.
- Blocker reasons in the rendered report list the blocking PRs and their
  status only (`blocked on #12 (pending), b (sign_off)`); within a group every
  unmerged blocker has its own row showing its hold exceptions, so the hold
  annotation is dropped there.  In flat `all` mode (no groups) blocker hold
  annotations are kept.  Structured blockers are added to the run entry
  (`blockers: [{pr_id, display_id, status, explicit_hold, held_by}]`).
- "also needed by X" stays (it is the shared-dependency source).

R2 — Phase/progress once per PR.
- One phase/progress token per row (`impl`, `review #3`, `qa 2/5 PASS:2`,
  `qa planning`, `qa PASS`, `sign-off`, `merge`, `pending`, `done`) replaces
  the separate `phase` column + `progress`.  The row's reason is a compact
  `short_reason` that omits what the token already says: review running →
  `last NEEDS_WORK` (not `review iteration 3 (last NEEDS_WORK)`); QA running /
  planning → no reason (not `scenario 2/5 done`); QA PASS → `awaiting
  sign-off…` (not `QA passed; awaiting…`); INPUT_REQUIRED rows →
  `answer in the review/QA/merge window`.
- `_derive()` returns, besides `(phase, state, reason)`, an info dict with
  `attention`, `short_reason`, `blockers`.  The JSON `reason` keeps its full
  current text (machine-readable data unchanged); `short_reason` and
  `attention` are additive fields.  A presenter given a status dict without
  `short_reason` (older owner TUI) falls back to `reason`.

R3 — Semantic highlighting.
- New run field `attention` (null or one of): `input_required` (review / QA /
  merge INPUT_REQUIRED, incl. a recorded QA INPUT_REQUIRED), `spec_review`
  (`spec_pending`, label by its phase: `IMPL SPEC REVIEW` / `QA SPEC REVIEW`),
  `manual_merge` (fresh SIGNOFF_MERGE + held by explicit stop or a wait
  target: `MANUAL MERGE`), `permission` (impl pane permission prompt:
  `PERMISSION`), `decision` (SIGNOFF_BLOCKED: `DECISION NEEDED`).
- Rows with `attention` replace the generic state label (`WAITING`) with that
  explicit label, styled conspicuous red (bold white on red background in
  TUI and ANSI), and the reason in bold red.  A configured wait-for-merge
  policy is a magenta policy label only; a running PR under a wait target is
  green RUNNING, never red.
- Restrained styles: PR display id bold, secondary pm id dim, phase/progress
  cyan, policy magenta (exception bold magenta), title plain/italic,
  window/also dim.  `failed` stays red text without background (distinct from
  human waits).
- Header counts human-action PRs once each (shared deps counted once):
  `⚠ 2 need you: #12, pr-abc`.  This is computed by one shared function used
  by both CLI and TUI so they agree.
- `spec_pending` was only checked for `in_progress`; it is now checked for any
  active status (`in_progress`, `in_review`, `qa`) so a pending QA spec is
  surfaced (status-only change; no scheduling change).

R4 — Width and wrapping.
- Shared layout targets ≤ 99 visible columns, or the narrower available
  width.  Each row: line 1 = marker, id, STATE label, phase/progress, policy
  labels, title; line 2 = reason · window · also-needed-by.  Words wrap onto
  continuation lines with a hanging indent (row indent + 4); over-long words
  are hard-split.  Width uses Unicode cell width (`rich.cells.cell_len`) and is
  computed on the plain text, so styling never counts.  Same for the header.
- CLI: width = `min(99, terminal columns)` (redirected output → 99); new
  `--width N` option overrides (clamped to ≥ 30).  TUI: popup container fits
  99 + chrome (`width: 105; max-width: 95%`); render width is the body's
  content width (fallback to the app width estimate before layout), minus the
  2-column selection gutter, re-rendered on resize.

R5 — Shared presentation; colors.
- New pure module `pm_core/autostart_view.py` (no Textual imports): row
  layout → list of lines, each a list of `(text, role)` segments.  Renderers:
  `to_ansi(lines, color)` for the CLI and `to_rich(segments)` (lazy rich
  import) for the popup.  `format_text(status, width=99, color=False)` in
  `autostart_state` delegates to it (keeps CLI import).
- CLI color: on when stdout is a TTY, `NO_COLOR` unset/empty, `TERM != dumb`;
  `--color/--no-color` overrides.  Plain output (redirect, `--no-color`,
  `NO_COLOR`) contains no ESC bytes; `--json` unchanged (no ANSI).
- Popup keeps selection/navigation keys (`_row_key`, j/k, Enter/f), the
  notice on the selected row, and scroll-into-view (each row is now a list of
  pre-wrapped lines).

## 2. Implicit requirements

- `status_rows()` keeps `{pr_id, depth, kind, run, also, progress}` and gains
  `group` (owning target id) and `group_policy`, so policy labels can be
  group-aware without changing row identity/order (popup row keys unchanged).
- `policy_labels(row)` remains the single policy-label function; its kinds
  become `policy` (the target's own) / `exception`; existing tests updated.
- Scheduling, merge holds (`merge_holds`, `effective_policy`), lifecycle and
  log lines (`review_loop_ui` uses `held_by_text`) are untouched.
- The `pm autostart list` text output is out of scope (already compact).

## 3. Ambiguities (resolved)

- *Which statuses are "human action"?* The three required (INPUT_REQUIRED,
  spec review, manual merge) plus permission prompt and SIGNOFF_BLOCKED, which
  equally wait on a person.  A stop-before-merge target that is signed off is
  a manual merge wait (it needs `g`), same as a wait-for-merge hold.
- *Change JSON `reason`?* No — kept verbatim; compact text is an added
  `short_reason` field.  Schema id stays `pm.autostart.status/1` (additive).
- *Show auto-merge on target headers in CLI?* Yes; CLI and popup now share one
  label set, so target headers always name their policy.
- *Hold text for a dep under a wait group that is also held by another wait
  target?* Omitted — the group's own hold implies it and "also needed by"
  names the other target.

## 4. Edge cases

- Shared dep appearing under several groups renders differently per group
  (labels are group-relative) but `attention` comes from the single run entry,
  so the header's need-you list counts it once.
- Completed target with no run entry (synthetic run in `status_rows`) — no
  attention, policy label still shown.
- `all` mode: flat rows, no groups; explicit stop marks shown; blocker hold
  annotations kept.
- Missing/closed blockers: rendered with their status (`missing`/`closed`).
- Very narrow widths (< 40): wrap still bounded; ids/labels longer than the
  width are hard-split rather than overflowing.
- Wide characters / emoji in titles: wrapping counts cell width.
- Old owner without `short_reason`/`attention`: falls back to `reason`, no
  highlighting.
