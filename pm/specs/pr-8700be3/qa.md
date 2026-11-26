# pr-8700be3 — QA spec: compact, highlighted autostart status (one dependency forest)

Regenerated 2026-11-01 for the restart implementation (merge of origin/master
c1fcecc5 + `b92ef613` and the review-loop follow-ups through `38455ea1`).  The
archived `qa.pre-restart-2026-10-22.md` tested removed behaviour
(stop-before-merge, `autostart all`, per-target grouped rows) and must not be
used as a pass criterion.

Surfaces under test:

- `pm autostart status` — text (`--width N`, `--color/--no-color`, `NO_COLOR`,
  `TERM=dumb`, TTY vs redirected) and `--json`, served by the owner TUI over
  the request/reply channel.
- The TUI runs popup (key `a`) — same layout, rendered through the same shared
  presenter (`pm_core/autostart_view.py`) from the same
  `pm.autostart.status/1` dict (`autostart_state.build_status` /
  `status_rows`).

Out of scope: `pm autostart list` text, scheduler semantics (only checked as
"unchanged").

## 1. Requirements

### R1 — One dependency forest, one row per PR

- **R1.1** Given two targets that share an unmerged dependency D,
  When the user runs `pm autostart status`,
  Then D appears on exactly one row (under the first target in target order
  that reaches it), and that row names the other dependent as
  `also needed by <id>`.
- **R1.2** Given a target T2 that is itself a dependency of another target T1,
  When the report is shown,
  Then T2 appears once, nested under T1 with its own target marker `◎` and its
  own policy label — not as a second top-level group.
- **R1.3** Given a diamond (T depends on B and C, both depend on A),
  When the report is shown,
  Then A appears once (under B, the first path), and its row says
  `also needed by` the other dependent.
- **R1.4** Given targets added in a given order,
  When the report is shown repeatedly (and after a refresh with no state
  change),
  Then the row order is identical each time; roots follow target order;
  children follow each PR's `depends_on` order.
- **R1.5** Given two distinct local PRs that share one GitHub number,
  When the report is shown,
  Then they are two separate rows (each keeps its own pm id) and every
  reference to them (blocker reason, also-needed-by, need-you list, holder)
  uses the pm id, not the ambiguous `#N`.

### R2 — Inherited policy stated once; exceptions kept

- **R2.1** Given a wait-for-merge target W with an unmerged dependency chain,
  When the report is shown,
  Then W's row shows `[wait-for-merge]` once; rows below W show no
  `wait-for-merge ← W` label; blocker reasons read
  `blocked on #N (status), …` with no hold cause.
- **R2.2** Given an auto-merge target A that was added before a wait target W
  and shares dependency D with W (so D sits under A),
  When the report is shown,
  Then D's row carries the exception `[wait-for-merge ← W]` once, D's own
  subtree rows do not repeat it, and D says `also needed by W`.
- **R2.3** Given an auto-merge target nested under (or otherwise held by) a
  wait target W,
  When the report is shown,
  Then that target's row shows `[auto-merge] [wait-for-merge ← W]`.
- **R2.4** Given any target row, Then it names its own configured policy
  (`[wait-for-merge]` or `[auto-merge]`).  No row anywhere says
  `stop-before-merge`, even for a target added with the deprecated
  `--stop-before-merge` alias (which is a wait-for-merge target).

### R3 — Phase/progress once per PR

- **R3.1** Given a PR whose review loop is on iteration N with last verdict
  NEEDS_WORK,
  When the report is shown,
  Then the row has one token `review #N` and the reason `last NEEDS_WORK`
  (no `running/review`, no `review iteration N`).
- **R3.2** Given a PR in QA with scenarios running (or planning),
  Then the row has one `qa d/t PASS:k` (or `qa planning`) token and no
  scenario count repeated in the reason.
- **R3.3** Given a PR back in review after a finished QA loop (or in QA after
  review), Then the token reflects the current phase only (no stale
  `qa …` on a review row or `review #N` on a QA row).
- **R3.4** Given any row, Then display id (`#N` when a GitHub number exists),
  pm id (dim, when different), state or attention label, at most one
  phase/progress token, policy labels, and the title are all on the row,
  followed by a short reason; COMPLETED/FAILED rows show no `done` token.

### R4 — Semantic highlighting of human waits

- **R4.1** Given PRs at review/QA INPUT_REQUIRED, with a pending impl spec,
  with a pending QA spec, and a signed-off PR held by a wait-for-merge target,
  When the report is shown in a colour terminal,
  Then those rows read `INPUT_REQUIRED`, `IMPL SPEC REVIEW`,
  `QA SPEC REVIEW`, `MANUAL MERGE` as explicit text labels styled bold white
  on red, with their reason in bold red saying what to do (`answer in the …
  window`, `see the QA note; press t / z t…`, `approve or edit the spec —
  press V`, `signed off — press g to merge`).
- **R4.2** Given a PR still running (impl/review/QA) under a wait-for-merge
  target, Then its label is green `RUNNING`; the inherited policy is only a
  magenta label and never makes the row red.
- **R4.3** Given a PR whose QA ended INPUT_REQUIRED and that then got a
  pending QA spec, Then the row reads `QA SPEC REVIEW` with no trailing
  `qa` / `qa INPUT_REQUIRED` token.
- **R4.4** Given human-action PRs exist,
  Then the header reads `⚠ K need(s) you: a, b, …` listing each such PR once
  in report order — a shared dependency counts once.
- **R4.5** Given a permission prompt in an implementation pane (or a review
  HOLD) or a SIGNOFF_BLOCKED sign-off, where reachable,
  Then the row is labelled `PERMISSION` / `DECISION NEEDED` in the same red
  style and is in the need-you list.
- **R4.6** Given a failed run, Then `FAILED` is red text without a red
  background and is not in the need-you list.
- **R4.7** Given the same project, When the user compares the CLI report with
  the popup, Then both list the same need-you PRs in the same order and red
  labels sit on the same rows.

### R5 — Width and wrapping

- **R5.1** Given a terminal ≥ 99 columns or redirected output,
  Then no line (header included) exceeds 99 terminal cells.
- **R5.2** Given a narrower terminal or `--width N`,
  Then every line fits min(N, 99) (N clamped to 30..99); long titles, reasons,
  blocker lists, also-needed-by lists and header items wrap onto continuation
  lines indented under their row; nothing is truncated; no line starts or ends
  with a `·` separator; a PR id, window name or policy label is never split
  unless a single word is wider than the line.
- **R5.3** Given titles with wide characters (CJK, emoji),
  Then wrapping counts display cells and lines stay within width.
- **R5.4** Given a deep dependency chain at a narrow width,
  Then indentation stops growing once a row would have under ~24 cells of
  content; every line still fits.
- **R5.5** Given a title or reason with tabs, newlines or terminal escape
  sequences, Then the text report lays them out as spaces / drops the escapes
  (no raw ESC bytes, no break to column 0), while `--json` keeps the original
  text verbatim.

### R6 — Colour control and machine-readable output

- **R6.1** Given an interactive terminal (TTY), Then the CLI report is
  coloured (SGR codes visible via `cat -v` / `tmux capture-pane -e`).
- **R6.2** Given `NO_COLOR=1`, `TERM=dumb`, `--no-color`, or stdout
  redirected to a file/pipe, Then the report contains no ESC bytes;
  `--color` forces colour even when piped and wins over `NO_COLOR`.
- **R6.3** Given redirected output without `COLUMNS`, Then width is 99; with
  `COLUMNS=60` set, width is 60.
- **R6.4** Given `--json` (with or without `--color` / `--width`),
  Then the output is valid JSON with no ANSI; `ok` is true; each run keeps
  its full `reason` (e.g. blocker reasons still include
  `wait-for-merge ← W` hold causes), and has the additive `short_reason`,
  `attention` (null or one of input_required / spec_review / manual_merge /
  permission / decision), `attention_label`, and `blockers`
  (`[{pr_id, display_id, status, held_by}]`); targets carry `attention`.
- **R6.5** Given the popup in pm's default tmux (TERM=screen, 16 colours),
  Then attention labels render with the same SGR as the CLI (bold white on
  red, e.g. `1;37;41`), WAITING yellow, RUNNING green — not Textual theme
  magenta/bright-red substitutes.

### R7 — Popup behaviour preserved

- **R7.1** Given the popup open, Then j/k (and arrows) move one PR per step —
  a shared dependency is a single stop; the selected row shows a gray
  selection bar that does not invert its red label.
- **R7.2** Given a selected row with a live window, When the user presses
  Enter/f, Then that PR's tmux window is focused; on a row without a window a
  notice appears on that row, wrapped within width.
- **R7.3** Given the popup at wide (≥140 cols) and narrow (≈70 and ≈50 cols)
  terminals, Then each popup row's text equals the CLI row at the popup's
  report width (`pm autostart status --no-color --width <popup width>`,
  ignoring the 2-column selection gutter); the header stays within 99; the
  header title is `Auto-start runs:` instead of `Auto-start:`.
- **R7.4** Given the terminal is resized while the popup is open,
  Then the popup re-wraps to the new width without closing or losing the
  selection.
- **R7.5** Given a popup taller than its visible area,
  Then the key-hint footer stays visible (docked) while rows scroll, wraps
  without a leading/trailing `·`, and moving the selection scrolls it into
  view clear of the footer.
- **R7.6** Given the popup with a PR selected, When a refresh (auto 2 s or
  `r`) moves that PR elsewhere in the tree (e.g. after a target is removed or
  re-added), Then the selection stays on the same PR.
- **R7.7** Esc / q / a close the popup.

### R8 — Unchanged behaviour

- **R8.1** Scheduling, merge holds, lifecycle transitions and the
  `pm autostart add/remove` acknowledgements (`added:`, `policy_changed: …
  (x; was y)`, `released merge hold: …`, `removed:`) behave as on master:
  a wait-held PR is never auto-merged; merging it (g / `pm pr merge`) starts
  newly unblocked dependents; an auto-merge target merges after sign-off and
  leaves the report.

## 2. Setup

Follow `pm/qa/instructions/tui-manual-test.md`:

1. Install pm from this branch (`./install.sh --local` or a venv with
   `pip install -e .`), `export PYTHONPATH=<clone>`; `pm which` shows the
   clone.
2. Throwaway git project; `pm init --backend local --no-import`; add PRs with
   `pm pr add … --depends-on …`.  Bootstrap-only `pm/project.yaml` edits are
   allowed for `gh_pr_number` (to get `#N` display ids / a shared GitHub
   number), initial `status`, and `spec_pending: {phase: impl|qa}`; commit
   `pm/` to master before autostart.
3. Start `pm session` with `PATH=/usr/local/bin:/usr/bin:/bin:$PATH` (real git
   ahead of the `~/.local/bin` proxy, but keep `~/.local/bin` for
   fake-claude); `export EDITOR=true` (or install vim-tiny) before the first
   tmux server so V / `pm pr spec-approve` works.  Run every pm command from a
   pane inside the test tmux session.
4. Drive sessions with fake-claude (`pm fake-claude config set`); stage
   targets one at a time (scripted cursors are per session type and reset on
   `config set`; fake reads its config at pane launch, so per-PR delays
   stick):
   - running review: `review: [{"verdict":"NEEDS_WORK","delay":3600}]`;
   - running QA: `qa_scenario` PASS with a long delay; fake QA needs
     `pm/specs/<pr>/qa.md` (`pm pr spec <pr> qa` in spec-mode auto) or it ends
     INPUT_REQUIRED;
   - stable INPUT_REQUIRED: a recorded QA INPUT_REQUIRED (`qa_scenario`
     INPUT_REQUIRED) — a fake review INPUT_REQUIRED self-resolves in ~2 s;
   - impl/QA spec review: `pm set spec-mode review`, then
     `pm pr spec <pr> impl|qa` while the PR is already in_progress (hold impl
     with fake `impl: {"delay":3600}`), or bootstrap `spec_pending`;
   - manual merge: a wait-held PR reaching fresh SIGNOFF_MERGE.  Fake impl
     makes no commits, so sign-off is coerced BLOCKED until a commit lands in
     the PR workdir; commit there and autostart re-runs sign-off →
     MANUAL MERGE.
5. Policies: `pm autostart add X` defaults to wait-for-merge; use
   `--auto-merge` for auto targets.  `--stop-before-merge` is only a
   deprecated alias for `--wait-for-merge`.  Merged targets are pruned.
6. Inspect: CLI from a test-session pane (`script -qc` or a tmux pane for TTY
   colour; redirect to a file for plain), `cat -v` for SGR; popup via
   `pm tui view` / `tmux capture-pane -e -p`.  Measure line widths in display
   cells (e.g. Python `wcwidth`) on ESC-stripped text.
7. Optional reference rendering of the intended layout:
   `tests/autostart_mixed_fixture.py` (`mixed_inputs`, `edge_inputs`) — for
   comparison only; scenarios must create state through pm.

## 3. Edge Cases

- **E1** Given auto-start off (no targets), When status is run (text, piped,
  JSON) or the popup opened, Then `Auto-start: off` /
  `No auto-start targets (auto-start off).`, no crash, no ANSI when piped.
- **E2** Given no owner TUI running, When `pm autostart status` is run, Then
  it fails with master's error and exit code, no traceback, no ANSI.
- **E3** Given `--width 0`, Then click rejects it (usage error); `--width 1`
  and `--width 10` render at 30; `--width 500` equals the default 99 output.
- **E4** Given a dependency cycle created with `pm pr edit --depends-on`
  (between two targets, below a target, and a self-dependency), Then the
  report renders promptly, each PR once, with `↻ dependency cycle: needs X`
  on the PR whose dependency is its ancestor; the popup navigates normally.
- **E5** Given a pending PR whose dependency was closed (`pm pr close`) and
  another whose dependency was deleted (`pm pr close --remove`), Then the
  blocker reason names them `(closed)` / `(missing)`; they have no rows of
  their own.  If the closed blocker shares a GitHub number with an active PR,
  both are named by pm id.
- **E6** Given a dependency reached only through a merged intermediate, Then
  it appears once under the target that needs it (with `also needed by` for
  any other target whose need is not visible through tree edges).
- **E7** Given a target whose PR record is deleted while it is a target,
  Then it shows as a `FAILED` row `PR not found` (or the owner reports it
  missing), never a crash or duplicate.
- **E8** Given an unbreakable word longer than the width (long identifier in
  a title), Then it is hard-split within width, never overflowing.
- **E9** Given an owner TUI running master's (pre-PR) code and the CLI from
  this branch, When `pm autostart status` is run, Then the report renders
  using the full `reason` (no highlighting, no crash) and `--json` passes the
  owner's data through.
- **E10** Given an INPUT_REQUIRED or spec-review PR, When the human answers
  (re-run QA with a PASS verdict / approve the spec), Then on the next
  refresh the row is no longer red, leaves the need-you list, and shows its
  new phase/progress.
- **E11** Given a MANUAL MERGE PR, When the user merges it (g), Then its row
  disappears, the need-you count drops, and the newly unblocked dependent
  starts.

## 4. Pass/Fail Criteria

Pass — every Then above is observable in CLI output or popup captures:
each PR exactly once; inherited policy only on the holder row with exceptions
where the tree does not imply the hold; one phase/progress token per row;
red bold-white-on-red labels with explicit text exactly on human-wait rows;
need-you list identical between CLI and popup; widths measured on plain text
≤ requested width (header too); ESC-free plain/JSON output; JSON `reason`
unchanged with additive fields present; popup navigation, focus, notice,
resize, footer and close keys working; scheduling/merge outcomes as on master.

Fail — a PR on more than one row, a missing dependency relationship (no
also-needed-by / cycle reference), a repeated inherited policy, duplicated
phase/progress text, a running PR shown red, a human wait not red or without
its text label, CLI/popup disagreement, a line over width or truncated
content, a line starting/ending with `·`, ANSI in redirected/JSON output,
a hang or crash on cycles/missing PRs, broken popup navigation, or any change
in scheduling/merge behaviour.

## 5. Ambiguities (resolved)

- *Where a shared dependency sits*: under the first target (target order)
  whose depth-first walk reaches it; the other dependents are named via
  `also needed by`.  Its hold label is relative to that position.
- *A target that is another target's dependency*: nested under that target
  (keeps `◎` and its own policy), not repeated as a root.
- *Human-action set*: INPUT_REQUIRED, IMPL/QA SPEC REVIEW, MANUAL MERGE, plus
  PERMISSION and DECISION NEEDED (they wait on a person just the same).  A
  signed-off auto-merge target and a FAILED run are not human waits.
- *JSON `reason`*: kept verbatim; compact text is the additive
  `short_reason`; schema id stays `pm.autostart.status/1`.
- *Width bounds*: `--width` is clamped to 30..99; `--width 0` is a usage
  error (IntRange min 1); redirected output defaults to 99 unless `COLUMNS`.
- *stop-before-merge*: removed on master (#261); only a deprecated input alias
  for wait-for-merge.  All-PR autostart is removed (#267) and is not tested.
- *Old owner TUI*: the presenter falls back to `reason` when
  `short_reason`/`attention` are absent; tested as E9.

No unresolved ambiguities.
