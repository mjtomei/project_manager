# pr-8700be3 — Compact, highlighted autostart status (impl spec)

## 0. Restart (2026-11-02): reconciled with current master

The first implementation (branch head `de87c5ac`, kept as the local ref
`pm/pr-8700be3-pre-restart-de87c5ac` and in this branch's history) was
written against a master that still had the per-PR `stop-before-merge`
policy and the whole-backlog `autostart all` mode.  Current origin/master
(merged in at the restart) removed both:

- #261 (pr-25f4038): `wait_for_merge` is the only manual merge policy.
  `--stop-before-merge` / `stop_before_merge` survive only as deprecated
  input aliases that map to `wait_for_merge`; there is no `POLICY_STOP`, no
  explicit per-PR hold, no `explicit_hold` field.
- #267 (pr-049649a): no all-PR autostart.  `mode` is `targets` or `off`;
  rows never come from a flat backlog.

This spec drops every stop-mark and all-mode rule of the first version
(they must not be restored) and adds the user requirement of 2026-11-02:
one unified dependency forest (R6).  Master's newer status branches are
kept and classified: a re-armed review launch retry (`review #N (launch
retry K)`), `LAUNCH_FAILED` / `HOLD` review verdicts, and a held QA
INPUT_REQUIRED that is still watching its scenario worker pane.

## 1. Requirements (grounded in code)

The report is built in three places:

- `pm_core/autostart_state.py` — `build_status()` / `_derive()` produce the
  `pm.autostart.status/1` dict (`runs`, `targets`); `status_rows()` turns it
  into display rows; `policy_labels()` names merge policy per row;
  `_progress()` makes the progress token; `format_text()` renders CLI text.
- `pm_core/cli/autostart.py::autostart_status` — `pm autostart status` (text
  via `format_text`, or `--json` dumps the status dict plus master's `ok`
  flag).  The CLI receives the status dict as JSON over the reply file, so
  everything the presenter needs must live in the status dict.
- `pm_core/tui/screens.py::AutoRunsScreen` — the `a` runs popup.

R1 — Drop text the tree already implies.
- A wait-for-merge target holds its whole unmerged closure
  (`merge_holds`).  Its row states `[wait-for-merge]` once; rows placed
  below it in the forest (R6) show no inherited wait label, and blocker
  reasons do not repeat `wait-for-merge ← T`.
- Exceptions still shown: a hold by a wait target that is *not* an ancestor
  of the row in the forest (a shared dependency placed under an auto-merge
  target → `[wait-for-merge ← X]`), stated once on the topmost such PR —
  its subtree is in its closure, so held the same way, and shows no label
  for that hold (row field `inherited`); an auto-merge target held by a wait
  target (`[auto-merge] [wait-for-merge ← X]`, even when X is its ancestor,
  because it overrides the target's own configured policy).  Every target
  row names its own policy (`[wait-for-merge]` / `[auto-merge]`).
- Blocker reasons in the rendered report list the blocking PRs and their
  status only (`blocked on #12 (pending), b (sign_off)`): every unmerged
  blocker the report lists has its own row (with any hold label it needs),
  and one it does not list is closed or missing, which its status says.
  Structured blockers are added to the run entry
  (`blockers: [{pr_id, display_id, status, held_by}]`); the JSON `reason`
  keeps the full text including hold causes.

R2 — Phase/progress once per PR.
- One phase/progress token per row (`impl`, `review #3`, `review #3 (launch
  retry 2)`, `qa 2/5 PASS:2`, `qa planning`, `qa PASS`, `sign-off`, `merge`,
  `pending`) replaces the separate `phase` column + `progress`; `done` is
  never shown (COMPLETED/FAILED and the reason say merged/closed/not
  found).  Progress comes only from the loop of the current phase.
- The row's reason is a compact `short_reason` that omits what the token
  already says: review running → `last NEEDS_WORK` (not `review iteration 3
  (last NEEDS_WORK)`; nothing for a re-armed retry whose last verdict is
  `LAUNCH_FAILED`); QA running / planning → no reason; QA PASS → `awaiting
  sign-off…`; review launch failure → `launch failed (retryable): …`;
  INPUT_REQUIRED rows → `answer in the review/QA/merge window` (held QA:
  `answer in the scenario worker pane`).
- `_derive()` returns `(phase, state, reason, info)`; info carries
  `attention`, the short reason and `blockers`.  The JSON `reason` keeps its
  full text (machine-readable data unchanged); `short_reason`, `attention`,
  `attention_label` and `blockers` are additive.  A presenter given a status
  dict without them (older owner TUI) falls back to `reason`.

R3 — Semantic highlighting.
- Run field `attention` (null or one of): `input_required` (review / QA /
  merge INPUT_REQUIRED, incl. a recorded or held QA INPUT_REQUIRED),
  `spec_review` (`spec_pending`, label by its phase: `IMPL SPEC REVIEW` /
  `QA SPEC REVIEW`), `manual_merge` (fresh SIGNOFF_MERGE held by a wait
  target: `MANUAL MERGE`), `permission` (impl pane permission prompt, or a
  review `HOLD` at a trust/permission prompt: `PERMISSION`), `decision`
  (SIGNOFF_BLOCKED: `DECISION NEEDED`).  The target entry gets `attention`
  too.
- Rows with `attention` replace the generic state label with that explicit
  label, styled conspicuous red (bold white on red background in TUI and
  ANSI), and the reason in bold red.  A configured wait-for-merge policy is
  a magenta label only; a running PR under a wait target is green RUNNING,
  never red.  A signed-off auto-merge target is not a human wait.
- Restrained styles: display id bold, secondary pm id dim, phase/progress
  cyan, policy magenta (exception and cycle bold magenta), title plain,
  window/also dim.  `failed` stays red text without background.
- Header lists human-action PRs once each, in report order:
  `⚠ 2 need you: #12, pr-abc` — one shared function (`needs_human`) for CLI
  and TUI so they agree.
- `spec_pending` is checked for any active status (`in_progress`,
  `in_review`, `qa`) so a pending QA spec is surfaced (status only).

R4 — Width and wrapping.
- Shared layout targets ≤ 99 visible columns, or the narrower available
  width.  Each row: line 1 = indent, marker, id, STATE label, phase/progress,
  policy labels, title; then reason · window · cycle · also-needed-by.  Words
  wrap onto continuation lines with a hanging indent (row indent + 4);
  over-long words are hard-split.  Width uses Unicode cell width
  (`rich.cells.cell_len`) on the plain text, so styling never counts.  Same
  for the header.  Tabs/newlines in reasons are laid out as spaces;
  terminal escape sequences and other control characters in titles or
  reasons are dropped (the JSON keeps them verbatim).
- Tree indentation is two cells per level, capped so a row keeps at least
  24 cells for its content (deeper levels stay flat at the cap).
- Short lead phrases (`blocked on`, `also needed by`, `↻ dependency cycle:
  needs`, `⚠ N need you:`) do not break internally unless they alone are
  wider than a line; single secondary labels (`⧉ window`, `run X`, `owner
  X`) wrap as a whole; a ` · ` separator at a break is dropped (no line
  starts or ends with `·`).
- CLI: width = `min(99, terminal columns)` (redirected output → 99);
  `--width N` overrides (clamped to 30..99).  TUI: popup container fits 99 +
  chrome (`width: 106; max-width: 95%`, stable 1-column scrollbar gutter);
  render width is the body's content width minus the 2-column selection
  gutter, re-rendered on resize; the header stays within 99 columns; the
  key hint is docked below the rows and wraps without dangling `·`.

R5 — Shared presentation; colors.
- Pure module `pm_core/autostart_view.py` (no Textual imports): rows →
  lines of `(text, role)` segments; `to_ansi(lines, color)` for the CLI
  (16-color SGR) and `to_rich(line)` for the popup (explicit RGB that rounds
  to the same ANSI colours in a 16-colour pane).  `format_text(status,
  width=99, color=False)` in `autostart_state` delegates to it.
- CLI color: on when stdout is a TTY, `NO_COLOR` unset/empty, `TERM !=
  dumb`; `--color/--no-color` overrides.  Plain output has no ESC bytes;
  `--json` never has ANSI.
- Popup keeps j/k, Enter/f focus, r, Esc/q/a, Ctrl+R, the notice on the
  selected row, and scroll-into-view; the selection is a gray bar (not
  reverse, which would invert the red label).

R6 — One dependency forest, one row per PR (user requirement 2026-11-02).
- `status_rows()` returns one row per local PR id: every run plus every
  target (a target without a run gets a synthetic row).  A shared
  dependency, a diamond, or a target that is another target's dependency
  appears exactly once.  Distinct local PR ids never merge, even when their
  GitHub numbers coincide.
- Roots: targets that no listed PR depends on, in target order.  Children:
  a PR's listed direct dependencies in `depends_on` order.  A depth-first
  walk places each PR at the first path that reaches it; a target reached
  this way is nested (keeps `◎` and its own policy label) instead of being
  a second root.
- Other relationships become references on the canonical row: `also` =
  other direct dependents in the forest (not the tree parent), then targets
  whose need is invisible through forest edges (e.g. via a merged
  intermediate) — rendered `also needed by X, Y`, ordered by row position.
  A listed dependency that is the row's own ancestor (or itself) is a cycle:
  `cycle` field, rendered `↻ dependency cycle: needs X`; the walk does not
  re-enter it.
- Fallbacks, all deterministic: targets only reachable through a cycle
  become roots (first in target order) after the true roots; a non-target
  PR with no listed dependent (needed only through a merged PR) hangs under
  the first target in its `needed_by` that is already placed.  Closed and
  missing blockers have no row; their status names them in the blocker
  reason.  A target whose PR is gone is a `FAILED` row, `PR not found`.
- References (holders, also, cycle, blockers, need-you list) use display
  ids (`#240`), except where several local PRs share a display id — then
  each is named by its pm id.
- Row fields: `{pr_id, depth, kind (target|dep), run, parent, ancestors,
  root, inherited, also, cycle, progress, policy}`.  Policy labels are
  relative to the row's ancestors and the wait targets holding them
  (`inherited`, R1).
- Popup selection key is the pm id alone (one row per PR), so a selection
  survives refreshes even if the PR moves in the tree; navigation moves one
  PR per j/k; Enter/f focuses that PR's window.

## 2. Implicit requirements

- `policy_labels(row, name)` stays the single policy-label function; kinds
  `policy` (a target's own) / `exception`.
- Scheduling, merge holds (`merge_holds`, `effective_policy`), lifecycle and
  log lines (`review_loop_ui` uses `held_by_text`) are untouched; the
  forest is presentation only and never widens what autostart drives.
- `targets` in the status dict is unchanged except the additive
  `attention`; `runs` order is unchanged.
- `pm autostart list` text output is out of scope.

## 3. Ambiguities (resolved)

- *Which statuses are "human action"?* INPUT_REQUIRED, spec review, manual
  merge, plus permission prompt / review HOLD and SIGNOFF_BLOCKED, which
  equally wait on a person.  A failed launch is `FAILED`, not a human wait.
- *Change JSON `reason`?* No — kept verbatim; compact text is the additive
  `short_reason`.  Schema id stays `pm.autostart.status/1`.
- *Where does a shared dependency go?* Under the first PR a depth-first
  walk in target order reaches it from; the user controls this by target
  order.  Its hold label is then relative to that position (an ancestor
  wait target is implied, another one is an exception).
- *"also needed by" — direct dependents or targets?* Direct dependents
  (every non-tree edge appears once), plus targets only where no forest
  edge shows the need.  Targets reachable through a listed dependent follow
  from that dependent's own row.
- *Cycle annotation side?* On the PR whose dependency is its ancestor
  (`needs X`), so the loop reads off the tree without a duplicate row.
- *Missing-target phase token?* None (`done` is never shown).

## 4. Edge cases

- Shared dep / diamond / nested target: one row, `also` references,
  `attention` from the single run entry (header counts it once).
- Cycles between targets, below a target, and a self-dependency: bounded
  walk, `cycle` reference, each PR once.
- Deep chains: indentation capped by width; every line ≤ width.
- Same GitHub number on two local PRs: two rows, references by pm id.
- Missing/closed blockers: `blocked on pr-x (missing), #304 (closed)`.
- Very narrow widths (30): wrap still bounded; over-long tokens hard-split.
- Wide characters / emoji in titles: wrapping counts cell width.
- Old owner without `short_reason`/`attention`: falls back to `reason`, no
  highlighting; runs listed in another order give the same forest.
