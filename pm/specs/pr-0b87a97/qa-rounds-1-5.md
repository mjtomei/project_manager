# Historical QA scenarios — pr-0b87a97, rounds 1–5

These completed scenario definitions are preserved verbatim from commit
`23d69fe37f3c2a6cf368a613ddeffdd172ae7d4b`. They document past execution;
[qa.md](qa.md) contains the current requirements, scope decisions, setup, and
latest scenario definitions. Historical section references §6–§10 resolve here.
The original complete document is available with
`git show 23d69fe37f3c2a6cf368a613ddeffdd172ae7d4b:pm/specs/pr-0b87a97/qa.md`.

## 6. QA scenarios (round 1, S1–S5, full detail)

The machine-readable QA_PLAN block for this run is deliberately compact (PR
transport workaround: ≤22 lines × ≤60 cols, pending pr-b8561ac). Each
scenario's `STEPS:` line there points here; **this section is the scenario
definition**. Every scenario: follow `pm/qa/instructions/tui-manual-test.md`
setup (pm installed from this branch, throwaway project, `pm session`, fake
Claude configured so impl goes idle, review NEEDS_WORK→PASS, QA plan of 1–2
scenarios that PASS), drive only through the TUI keys, command bar and `pm`
CLI (run from a pane inside the test tmux session), and capture a tmux
screen recording of the TUI plus a CLI recording of the `pm autostart`
commands. Assert on what is visible: pane captures, CLI stdout/exit codes,
`tmux list-windows`, `pm pr list`.

### S1 — Second O no longer retargets; popup and CLI agree (bug repro)
Instruction: tui-manual-test.md · Artifacts: tmux-screen-recording.md,
cli-recording.md
- GIVEN the pm repo checkout of this branch, WHEN the user runs the
  reproduction test `pytest tests/test_autostart_retarget_regression.py` and
  `pytest tests/test_autostart_multi_target.py`, THEN both pass.
- GIVEN a session with two independent pending PRs A and B and auto-start
  off, WHEN the user presses `O` on A, then `O` on B, THEN both show ◎, the
  status bar shows `AUTO ×2`, each gets its own impl window, and when A's
  impl goes idle A advances to review and then QA (A must not stay stuck in
  in_progress — the original bug); B advances independently.
- GIVEN both runs are mid-flight at different steps (e.g. A in QA, B in
  review iteration 2), WHEN the user opens the runs popup (`a`) and, at the
  same moment, runs `pm autostart status --json` from another pane, THEN the
  popup and JSON agree on targets, policies (both stop-before-merge), phase,
  state and reason per PR, and each shows review iteration / QA scenario
  progress and the tmux window name.
- GIVEN the popup is open, WHEN a run changes phase (wait for a transition)
  and the user also runs `pm autostart add C` from the CLI, THEN the popup
  updates on its own within a few seconds (no reopen) and shows C; `r`
  refreshes immediately.
- GIVEN the popup is open with a row selected, WHEN the user moves with
  j/k/arrows and presses Enter (and on another try `f`), THEN the popup
  closes and tmux switches to that run's window; selecting a queued row with
  no window and pressing Enter does not crash and leaves the TUI usable.
- GIVEN the popup is open, WHEN the user dismisses it with Esc, then reopens
  and closes with `q`, then with `a`, THEN the TUI is back with normal keys
  working (tree navigation, `?`). `?` help, the footer ("Runs") and
  `pm tui keys` list `a`, `O`, `A` with the new semantics; `pm autostart
  --help` documents verbs and policies.
- GIVEN no targets, WHEN the user opens the popup, THEN it says "No
  auto-start targets (auto-start off)" and lists no backlog PRs.

### S2 — CLI and command-bar target management, validation, owner errors
Instruction: tui-manual-test.md · Artifacts: cli-recording.md,
tmux-screen-recording.md
- GIVEN a session with PRs A, B, C pending and M bootstrapped as merged
  before the session started, WHEN the user runs `pm autostart add A B`,
  THEN exit 0, output names both as added (stop-before-merge), `pm autostart
  list` and `list --json` show exactly A,B with policies/added_at/source, and
  the TUI shows ◎ on both.
- WHEN the user re-adds A (`add A`, and also via the `#N` / bare-number id
  forms), THEN exit 0, reported as already a target, list unchanged, no new
  window for A.
- WHEN the user runs `add A nosuch`, `add M`, `add` (no ids), `remove
  nosuch`, THEN each exits 1 with `unknown_pr` / `terminal_pr` / usage
  respectively (JSON with `--json`), and list is unchanged (A not re-added,
  nothing removed). `remove C` (valid, not a target) → ok, `not_target`.
- WHEN the user runs `remove A`, THEN exit 0, B remains, A's existing
  window is still present. WHEN `clear`, THEN mode off, status JSON
  `mode: off`, targets empty, running windows still present, and no backlog
  PR (C) is started afterwards.
- GIVEN the TUI, WHEN the user types in the command bar `autostart target
  C`, `autostart add B`, `autostart list`, `autostart remove C`, bare
  `autostart` while on, then bare `autostart` while off, THEN target alias is
  additive, list is logged, bare-when-on turns off, bare-when-off prints
  usage and does NOT enable everything; `autostart status` opens the popup.
  `autostart all` explicitly enables backlog mode (status `mode: all`).
- GIVEN the TUI, WHEN the user presses `A` on a non-target PR, then on a
  target PR, THEN it adds (auto-merge) then removes only that PR; with
  nothing selected and auto-start off, `A` says "No PR selected".
- GIVEN no session running for the project (and separately: TUI pane killed
  leaving a stale pidfile; `-s nonexistent`), WHEN the user runs `pm
  autostart status --json` and `add A`, THEN exit 2 with
  `owner_unavailable` JSON/text; with a TUI that is suspended (e.g. SIGSTOP
  the TUI pid) and `--timeout 2`, exit 2 `owner_timeout`; resume and confirm
  state is consistent.

### S3 — Shared dependency, concurrent adds, removal and completion
Instruction: tui-manual-test.md · Artifacts: tmux-screen-recording.md,
cli-recording.md
- GIVEN a diamond: X and Y both depend on D; Z independent; plus a chain
  T2→T1; all pending, auto-start off, WHEN two shells run `pm autostart add
  X` and `pm autostart add Y` at the same instant (background both), THEN
  both exit 0 with their own replies, list shows X and Y, D is launched
  exactly once (`tmux list-windows` has one D window, ever), Z is NOT
  started, and status lists D once with `needed_by` [X, Y] while X and Y are
  waiting "blocked on D".
- WHEN, while D is running, the user removes X, THEN D's window keeps
  running, D still lists Y in needed_by, X is gone from targets, Y unchanged.
- WHEN D finishes its loop and the user merges D (TUI `g` or `pm pr merge`),
  THEN without further action Y starts on the next scheduler pass and X does
  not (no longer a target).
- GIVEN Y is advancing, WHEN the user adds T2 and T1 as targets (T1 is both
  a target and T2's dependency), THEN T2 waits on T1, T1 runs; when Y is
  merged Y disappears from the target set (log names it) while T1/T2 keep
  going; when the last target is removed/completed status shows mode off and
  the popup the empty message.
- Throughout, fire 5–10 `pm autostart status --json` calls in parallel from
  multiple shells while launches happen: every call exits 0 with valid JSON,
  none times out, no PR ever has two windows.

### S4 — Merge policies, sign-off gate and finished-QA hold
Instruction: tui-manual-test.md · Artifacts: tmux-screen-recording.md,
cli-recording.md
- GIVEN independent PRs S and U, WHEN the user adds S with `pm autostart add
  S` (default) and U with `pm autostart add U --auto-merge` (and also via
  keys: `O` on one, `A` on another), THEN list/status show stop_before_merge
  vs auto_merge respectively.
- WHEN both pass review and QA (fake verdicts PASS), THEN neither is merged
  silently: S is held with a reason telling the user to sign off/press g; U's
  auto-merge attempt is refused by the sign-off gate (no fresh SIGNOFF_MERGE)
  and status shows "merge blocked by sign-off gate" / awaiting sign-off;
  `pm pr list` shows neither merged. No `--no-signoff-check` bypass.
- WHEN the user waits through several scheduler passes (and triggers a
  sync/reload), THEN QA is not re-run for S or U (no new QA window/run
  appears for a PR whose QA already PASSed).
- WHEN the user runs `pm autostart add S` again without a flag, THEN S stays
  stop-before-merge; `add S --auto-merge` switches it; `remove S` then `add
  S` (no flag) keeps the stop mark when it was stop.
- GIVEN a stop-before-merge dependency D needed by an auto-merge target Q,
  WHEN D is merge-ready, THEN D is not auto-merged and Q shows waiting on D.
- GIVEN a project with skip-QA enabled, WHEN an auto-merge target passes
  review, THEN it goes to the merge path (gate still applied) and a
  stop-before-merge target stops.

### S5 — Restart adoption, legacy breadcrumb, CLI during restart
Instruction: tui-manual-test.md · Artifacts: tmux-screen-recording.md,
cli-recording.md
- GIVEN targets A (stop-before-merge, QA in flight), B (auto-merge, review
  loop running) and C (pending on dependency D, D impl running), WHEN the
  user runs `pm tui restart --breadcrumb` (the supported restart path), THEN
  after restart `pm autostart list --json` shows A,B,C with the same
  policies; `tmux list-windows` before/after shows identical impl/review/QA
  windows (no duplicates); A's QA continues (not restarted from planning),
  B's review iteration continues; the popup shows the same runs.
- WHEN, during the restart window, the user runs `pm autostart status
  --json` and `pm autostart add Z` in parallel, THEN each either succeeds or
  exits 2 with `owner_unavailable`/`owner_timeout` (never a traceback or
  hang past --timeout), and after restart the state reflects only applied
  commands.
- GIVEN the popup is open, WHEN the TUI is restarted (Ctrl+R in the TUI, and
  `pm tui restart`), THEN the restart happens (popup does not swallow it);
  a plain Ctrl+R is a clean restart (document what is kept).
- GIVEN a breadcrumb in the legacy single-target format (produce it by
  running the master build's TUI with one `O` target and triggering its
  breadcrumb restart, or as written by the pre-PR code), WHEN the new build
  consumes it, THEN that PR is the single target with stop-before-merge
  preserved and no duplicate windows are launched.

## 7. QA round 2 scenarios (S6–S10, full detail)

Same transport workaround as §6: the compact QA_PLAN block points here.
Same setup, recordings and assertion surfaces as §6 (tmux screen recording of
the TUI via a grouped view session + CLI recording of every `pm` command, run
from a pane inside the test session). Round 1 found and fixed bugs in every
scenario; round 2 re-runs the user stories end-to-end on the final revision,
with emphasis on the fixed areas and on interleaving.

### S6 — Bug repro: two targets advance; popup and CLI agree
Covers R1, R10, R14–R18, R23–R25, R28, bug §0.
- GIVEN the branch checkout, WHEN the user runs `pytest
  tests/test_autostart_retarget_regression.py
  tests/test_autostart_multi_target.py`, THEN both pass.
- GIVEN two independent pending PRs A and B, auto-start off, fake review
  NEEDS_WORK→PASS, WHEN the user presses `O` on A then `O` on B (and the
  tree refreshes / B's background start happens in between), THEN the cursor
  stays on the PR the user picked, both show ◎, status bar `AUTO ×2`, each
  "armed" confirmation is readable and appears in `L`; A's impl going idle
  moves A to review then QA (not stuck in_progress); B advances
  independently; each review iteration has exactly one review window.
- GIVEN A in QA and B in review iteration 2, WHEN the user opens the popup
  and simultaneously runs `pm autostart status --json`, THEN they agree on
  targets, policies, phase, state, reason, review iteration / QA progress
  ("qa planning", scenario counts, not a stale review #) and window names.
- GIVEN the popup open, WHEN a phase changes and the user runs `pm autostart
  add C` from the CLI, THEN the popup updates on its own and shows C; `r`
  refreshes immediately.
- GIVEN a terminal resized small enough that popup rows overflow, WHEN the
  user moves with ↑/↓ and j/k past the visible edge, THEN the selected row
  stays visible; Enter / `f` focus the selected run's window; Enter on a
  window-less queued row does not crash.
- GIVEN the popup, WHEN dismissed with Esc, `q`, `a`, and when opened via the
  command bar `autostart status` then Esc, THEN the tree has focus and normal
  keys work. `?`, footer "Runs", `pm tui keys`, `pm autostart --help`
  document `a`/`O`/`A` and the verbs/policies.
- GIVEN no targets, WHEN the popup opens, THEN it shows the empty
  "auto-start off" message and no backlog PRs.

### S7 — CLI and command-bar management, validation, owner errors
Covers R2, R8, R9, R11–R13, R23, R29.
- GIVEN PRs A, B, C pending and M merged before the session started, WHEN the
  user runs `pm autostart add A B`, then re-adds A as `pr-…`, `#N` and `N`,
  THEN exit 0, list/list --json show exactly A,B (stop-before-merge,
  added_at, source), the re-adds report "already a target", no second A
  window, and the TUI shows ◎ on both plus a readable confirmation.
- WHEN the user runs `add A nosuch`, `add M`, `add`, `remove nosuch`, `remove
  C`, each with and without `--json`, THEN exit 1 `unknown_pr` /
  `terminal_pr` / usage, list unchanged; `remove C` ok `not_target`.
- WHEN `remove A` then `clear`, THEN A's window is kept, the TUI shows
  "removed A (1 remaining)" even if a sticky message is up, `mode: off`,
  and C is never started afterwards.
- GIVEN the TUI, WHEN the user uses the command bar (`autostart target C`,
  `add B`, `list`, `remove C`, bare `autostart` on/off, `autostart all`)
  and the `A` key on a non-target, a target, and with nothing selected,
  THEN target is additive, bare-when-off prints usage, only `all` enables
  backlog mode (with a readable "ON (all…)" message), `A` adds auto-merge /
  removes just that PR / says "No PR selected".
- GIVEN no session, a killed TUI with stale pidfile, `-s nonexistent`, and a
  directory outside any pm project, WHEN `pm autostart status --json` and
  `add A` run, THEN exit 2 `owner_unavailable` (exit 1 `no_project` JSON
  outside a project); with the TUI held suspended and `--timeout 2`, exit 2
  `owner_timeout` saying it may still be applied; after resuming, the state
  is consistent and the command is applied at most once.

### S8 — Shared dependency under concurrent CLI, keys and scheduler events
Covers R3–R6, R22, E1, E3, E4, E6, E9, R24.
- GIVEN a diamond X→D←Y, independent Z, chain T2→T1, all pending, WHEN two
  shells add X and Y at the same instant, THEN both exit 0 with their own
  replies, D is launched exactly once (one D window ever), Z never starts,
  status lists D once with needed_by [X, Y] and X/Y "blocked on D".
- GIVEN D running, WHEN, at the same moment, one shell removes X, another
  re-adds Y and adds T2, a third loops `status --json` 10× in parallel, and
  the user presses `O` on T1 in the TUI, THEN every command gets its own
  valid reply (no timeouts), the final target set equals the serial result
  {Y, T2, T1}, D keeps running with needed_by [Y], T1 runs once, T2 waits on
  T1, the TUI ◎ marks and popup match the CLI, and no PR has two windows.
- GIVEN D finished, WHEN the user merges D via `g` while a CLI `remove Y`
  races the merge (repeat with `add`), THEN the result is consistent
  (Y either pruned-then-started or removed, never started twice, never a
  traceback), X is not started.
- GIVEN Y advancing, WHEN Y merges, THEN Y leaves the target set with a log
  line, T1/T2 keep advancing; when the last target is removed or completes,
  mode is off, popup empty, no backlog PR starts.

### S9 — Merge policies, sign-off gate, finished QA, skip-QA
Covers R7, R21, E2, E8, ambiguity 4.
- GIVEN independent S and U, WHEN S is added default (and via `O`) and U with
  `--auto-merge` (and via `A`), THEN list/status/popup show
  stop_before_merge vs auto_merge.
- WHEN both pass review and QA, THEN S is held with a "sign off / press g"
  reason; U's merge is refused by the sign-off gate (no SIGNOFF_MERGE) with
  status "merge blocked by sign-off gate"/awaiting sign-off; `pm pr list`
  shows neither merged; no `--no-signoff-check` bypass appears anywhere.
- WHEN several scheduler passes and a sync/reload happen, THEN no new QA run
  starts for S or U (the stale "merge manually" log after a fast merge is
  pr-92041d7, out of scope).
- WHEN `add S` (no flag), `add S --auto-merge`, `remove S` + `add S`, THEN
  policies change only as flagged and the stop mark survives remove/re-add.
- GIVEN stop-before-merge D needed by auto-merge Q, WHEN D is merge-ready,
  THEN D is not auto-merged and Q waits on D.
- GIVEN skip-QA enabled, WHEN an auto-merge and a stop-before-merge target
  pass review, THEN the status says "QA skipped (skip_qa); awaiting
  sign-off" (no promise of a QA transition), the gate still applies, and the
  stop target stops.

### S10 — Restart adoption, CLI during restart, legacy breadcrumb
Covers R19, R20, R26, R27, ambiguities 7–8.
- GIVEN A (stop, QA in flight), B (auto-merge, review iteration running), C
  (waiting on D, D impl running), WHEN the user runs `pm tui restart
  --breadcrumb`, THEN `list --json` shows A,B,C with the same policies,
  `tmux list-windows -F '#{window_id} #{window_name}'` is identical before
  and after (B's review window same id), A's QA continues, the resume
  summary line is readable, and the popup shows the same runs.
- WHEN during the restart one shell runs `status --json` and another `add
  Z`, and later an unrelated `status` is sent, THEN each initial command
  either succeeds or exits 2 within `--timeout`; Z is applied exactly once
  right after startup (not 60+ s later by the unrelated command); the TUI
  pane survives; no traceback.
- GIVEN a command queue left by a TUI that died >60 s ago, WHEN a new TUI
  starts, THEN that stale command is not applied.
- GIVEN the popup open, WHEN the user presses Ctrl+R and separately runs `pm
  tui restart`, THEN the TUI restarts (popup does not swallow it) and the
  targets are dropped (clean restart, by design).
- GIVEN a legacy single-target breadcrumb produced by the master build (see
  PR note: override → /opt/pm-src, `O`, switch override back, `pm tui restart
  --breadcrumb`), WHEN the new build consumes it, THEN that PR is the only
  target, stop-before-merge, with no duplicate windows.

## 8. QA round 3 scenarios (S11–S15, full detail)

Same transport workaround and setup as §6/§7, including the round 2
environment notes in §2. Run against the PR branch head (verify `git log -1`
in the pm checkout under test before and after; it must be e98caf98 or a
later commit of this branch, never ad9a84db/bddbac33). Every scenario records
the TUI (tmux screen recording via a grouped view session) and every `pm`
command (CLI recording). Round 2 ended NEEDS_WORK on S6–S9 with fixes, and
review 9448 added more fixes, so round 3 re-runs each user story end-to-end
on the final revision.

### S11 — Bug repro: two targets advance; popup and CLI agree
Covers bug §0, R1, R10, R14–R18, R23–R25, R28, R31.
- GIVEN the branch checkout, WHEN the user runs `pytest
  tests/test_autostart_retarget_regression.py
  tests/test_autostart_multi_target.py tests/test_view_focus_command_bar.py
  tests/test_status_bar_narrow.py`, THEN all pass.
- GIVEN independent pending PRs A and B, auto-start off, fake review
  NEEDS_WORK→PASS and QA PASS, WHEN the user presses `O` on A then moves to B
  and presses `O` (letting a refresh / A's background start happen in
  between), THEN the cursor stays on the PR the user picked, both show ◎,
  each "armed" confirmation is readable and also in `L`, the status bar shows
  `AUTO ×2`; A's impl going idle moves A to review then QA (never stuck
  in_progress — the original bug); B advances independently; each review
  iteration of each PR has exactly one review window.
- GIVEN A in QA and B in review iteration 2 (use impl/review delays to
  separate them), WHEN the user opens the runs popup and at the same moment
  runs `pm autostart status --json`, THEN they agree on targets, policies,
  phase, state, reason, review iteration / QA progress ("qa planning" or
  scenario counts, never a stale "review #N" for A) and window names.
- GIVEN the popup open, WHEN a phase transition happens and the user runs
  `pm autostart add C` from another pane, THEN the popup updates on its own
  and shows C; `r` refreshes immediately.
- GIVEN the terminal resized to 80 columns (and with `L` split), WHEN the
  user looks at the status bar and opens the popup with more rows than fit,
  THEN `AUTO ×N` is still visible; ↑/↓ and j/k keep the selected row in view;
  Enter / `f` switch to the selected run's window; Enter on a window-less
  queued row does not crash.
- GIVEN the popup, WHEN it is dismissed with Esc, `q`, `a`, and opened via
  the command bar `autostart status` then Esc, THEN the tree has focus and
  normal keys work; `?`, footer "Runs", `pm tui keys`, `pm autostart --help`
  document `a`/`O`/`A` and the verbs/policies.
- GIVEN all targets removed, WHEN the popup opens, THEN it shows the empty
  "auto-start off" message and no backlog PR is listed or started.

### S12 — CLI/command-bar management, validation, owner errors, focus
Covers R2, R8, R9, R11–R13, R23, R29, R30, R32 (policy flip), R33.
- GIVEN PRs A, B, C pending and M merged before the session started, WHEN
  the user runs `pm autostart add A B`, then re-adds A as `pr-…`, `#N` and
  `N`, THEN exit 0, list/list --json show exactly A,B (stop-before-merge,
  added_at, source), re-adds report "already a target", no second A window,
  TUI shows ◎ on both with a readable confirmation.
- WHEN `add A --auto-merge` then `add A` (no flag), THEN the first reports
  policy_changed (was stop-before-merge) and the second leaves auto-merge.
- WHEN `add A nosuch`, `add M`, `add`, `remove nosuch`, `remove C`, each with
  and without `--json`, THEN exit 1 `unknown_pr` / `terminal_pr` / usage
  with list unchanged; `remove C` is ok `not_target`.
- WHEN `remove A` then `clear`, THEN A's window is kept, the TUI shows
  "removed A (1 remaining)" even under a sticky message, `mode: off`, and C
  is never started afterwards.
- GIVEN the TUI, WHEN the user drives the command bar (`autostart target C`,
  `add B`, `list`, `remove C`, bare `autostart` on and off, `autostart all`)
  and `A` on a non-target, a target, and with nothing selected, THEN target
  is additive, bare-when-off prints usage, only `all` enables backlog mode
  with a readable "ON (all…)" message, `A` adds auto-merge / removes only
  that PR / says "No PR selected".
- GIVEN the user is half-way through typing `autostart add B` in the command
  bar, WHEN another pane runs `pm autostart status --json` and `pm autostart
  add C` and an external `pm pr edit` triggers a reload, THEN the command
  bar keeps focus and its text; finishing the command adds B; no keystroke
  acted as a tree hotkey (no QA started, no stray refresh/selection change).
- GIVEN no session, a killed TUI with stale pidfile, a killed-but-unreaped
  (zombie) TUI, `-s nonexistent`, and a directory outside any project, WHEN
  `status --json` and `add A` run, THEN exit 2 `owner_unavailable`
  immediately (exit 1 `no_project` JSON outside a project); with the TUI
  held suspended and `--timeout 2`, exit 2 `owner_timeout` saying it may
  still be applied; after resuming, state is consistent and the command is
  applied at most once; a command refused for a zombie owner is not applied
  by the next TUI.

### S13 — Shared dependency under concurrent CLI, keys and merges
Covers R3–R6, R22, R24, E1, E3, E4, E6, E9.
- GIVEN a diamond X→D←Y, independent Z, chain T2→T1, all pending, WHEN two
  shells add X and Y at the same instant, THEN both exit 0 with their own
  replies, D is launched exactly once (one D window ever), Z never starts,
  status lists D once with needed_by [X, Y] and X/Y "blocked on D".
- GIVEN D running, WHEN at the same moment one shell removes X, another
  re-adds Y and adds T2, a third fires 10 parallel `status --json`, and the
  user presses `O` on T1, THEN every command gets its own valid reply (no
  timeouts), the target set is {Y, T2, T1}, D keeps running with needed_by
  [Y], T1 runs once, T2 waits on T1, ◎ marks/popup match the CLI, and no PR
  has two windows; the cursor stays where the user put it.
- GIVEN D finished, WHEN the user merges D via `g` while a CLI `remove Y`
  races the merge (repeat with `add Y`), THEN the outcome is consistent
  (Y removed, or pruned-then-started exactly once), X is not started, no
  traceback.
- GIVEN Y advancing, WHEN Y merges (manual merge of a stop target), THEN Y
  leaves the target set with a log line and T1/T2 keep advancing; when the
  last target is removed or completes, mode is off, the popup is empty, and
  no backlog PR starts.

### S14 — Merge policies, sign-off gate and refresh, finished QA, skip-QA
Covers R7, R21, R32, E2, E8, ambiguity 4.
- GIVEN independent S and U, WHEN S is added default (and via `O`) and U with
  `--auto-merge` (and via `A`), THEN list/status/popup show
  stop_before_merge vs auto_merge.
- WHEN both pass review and QA, THEN S is held with a "sign off / press g"
  reason; U's merge is refused by the sign-off gate (no SIGNOFF_MERGE) and
  status says merge blocked by sign-off gate / awaiting sign-off; `pm pr
  list` shows neither merged; nothing passes `--no-signoff-check`.
- WHEN the user signs U off through `pm pr auto-sequence` from another pane,
  THEN the TUI, `status --json` and the open popup reflect the sign-off
  right away (no stale "awaiting sign-off" until an unrelated reload), and
  U's merge then proceeds through `pm pr merge` and U leaves the target set.
- WHEN several scheduler passes and a sync/reload happen, THEN no new QA run
  starts for S or U.
- WHEN `add S` (no flag), `add S --auto-merge`, `remove S` + `add S`, THEN
  policies change only as flagged (`policy_changed` reported with the
  previous policy) and the stop mark survives remove/re-add.
- GIVEN stop-before-merge D needed by auto-merge Q, WHEN D is merge-ready,
  THEN D is not auto-merged and Q waits on D.
- GIVEN skip-QA enabled, WHEN an auto-merge and a stop-before-merge target
  pass review, THEN status says "QA skipped (skip_qa); awaiting sign-off",
  the gate still applies, and the stop target stops.

### S15 — Restart adoption and CLI during restart (regression on final rev)
Covers R19, R20, R26, R27, R33, ambiguities 7–8.
- GIVEN A (stop, QA in flight), B (auto-merge, review iteration running), C
  (waiting on D, D impl running), WHEN the user runs `pm tui restart
  --breadcrumb`, THEN `list --json` shows A,B,C with the same policies,
  `tmux list-windows -F '#{window_id} #{window_name}'` is identical before
  and after, A's QA continues without re-planning, B's review keeps its
  window, the resume summary is readable, the popup shows the same runs.
- WHEN during the restart one shell runs `status --json` and another `add
  Z`, then later an unrelated `status`, THEN each initial command succeeds
  or exits 2 within `--timeout`; Z is applied exactly once right after
  startup (not by the later unrelated command); the TUI pane survives.
- GIVEN the user is typing in the command bar right after the restart,
  WHEN the deferred startup queue (Z) is drained, THEN the command bar keeps
  focus and text.
- GIVEN a queue left by a TUI that died >60 s ago, WHEN a new TUI starts,
  THEN that command is not applied.
- GIVEN the popup open, WHEN Ctrl+R and separately `pm tui restart`, THEN
  the TUI restarts (popup does not swallow it) and targets are dropped by
  design.
- GIVEN a legacy single-target breadcrumb produced by the master build
  (override → /opt/pm-src, `O`, override back, `pm tui restart
  --breadcrumb`), WHEN the new build consumes it, THEN that PR is the only
  target, stop-before-merge, with no duplicate windows.

## 9. QA round 4 scenarios (S16–S20, full detail)

Same transport workaround and setup as §6–§8, including the round 2 and
round 3 environment notes in §2. Run against the PR branch head: verify
`git -C <pm checkout> log -1` before and after the run. It must be 85ba8955
or a later commit of this branch. Never test ad9a84db, bddbac33 or
e98caf98. Every scenario records the TUI (tmux screen recording through a
grouped view session) and every `pm` command (CLI recording). Round 3
ended NEEDS_WORK on S11, S12, S13 and S15, each with a fix
(R34–R36). Round 4 re-runs every user story end to end on the final
revision. It weights the stories that failed and adds the
interleavings that exposed them.

### S16 — Bug repro: two targets advance; popup and CLI agree; L backlog
Covers bug §0, R1, R10, R14–R18, R23–R25, R28, R31, R35, R36.
- GIVEN the branch checkout, WHEN the user runs `pytest
  tests/test_autostart_retarget_regression.py
  tests/test_autostart_multi_target.py tests/test_view_focus_command_bar.py
  tests/test_status_bar_narrow.py tests/test_log_pane_backlog.py
  tests/test_log_message_force.py`, THEN all pass.
- GIVEN independent pending PRs A and B, auto-start off, fake review
  NEEDS_WORK→PASS and QA PASS, WHEN the user presses `O` on A, moves to B
  and presses `O`, with a refresh or A's background start happening in
  between, THEN:
  - the cursor stays on the PR the user picked;
  - both PRs show ◎ and the status bar shows `AUTO ×2`;
  - A's impl going idle moves A to review and then QA. A never stays stuck
    in_progress (the original bug).
  - B advances independently, and each review iteration has exactly one
    review window.
- GIVEN both "armed" confirmations happened a minute or more ago, while the
  debug log stayed busy, WHEN the user opens `L` for the first time, THEN
  both `log: Auto-sequence armed …` lines are on screen without waiting.
- GIVEN A in QA and B in review iteration 2, WHEN the user opens the runs
  popup and at the same moment runs `pm autostart status --json`, THEN they
  agree on targets, policies, phase, state, reason, review iteration / QA
  progress and window names. A shows "qa planning" or scenario counts,
  never a stale "review #N".
- GIVEN the popup open, WHEN a phase transition happens and the user runs
  `pm autostart add C` from another pane, THEN the popup updates on its own
  and shows C. `r` refreshes immediately.
- GIVEN an 80-column terminal with `L` split, WHEN the user checks the
  status bar and opens a popup that has more rows than fit, THEN:
  - `AUTO ×N` is visible;
  - ↑/↓ and j/k keep the selected row in view;
  - Enter and `f` switch to the selected run's window;
  - Enter on a window-less queued row does not crash.
- GIVEN the popup, WHEN it is dismissed with Esc, `q` and `a`, and also
  opened through the command bar `autostart status` and then closed with
  Esc, THEN the tree has focus and normal keys work. `?`, the footer
  "Runs", `pm tui keys` and `pm autostart --help` document `a`/`O`/`A`
  and the verbs/policies.
- GIVEN A and B targets, WHEN the user merges A with `g` and then removes
  B from the CLI, THEN:
  - the line "target A merged — removed (1 remaining)" is readable after
    the merge spinner;
  - B's removal leaves mode off, and the popup shows the empty
    "auto-start off" message;
  - no backlog PR is listed or started.

### S17 — CLI/command-bar management, validation, owners, typing focus
Covers R2, R8, R9, R11–R13, R23, R29, R30, R32 (policy flip), R33, R34.
- GIVEN PRs A, B, C pending and M merged before the session started (with
  `gh_pr_number` set for the `#N` forms), WHEN the user runs `pm autostart
  add A B` and then re-adds A as `pr-…`, `#N` and `N`, THEN:
  - every command exits 0;
  - `list` and `list --json` show exactly A and B, stop-before-merge, with
    added_at and source;
  - the re-adds report "already a target", and A gets no second window;
  - the TUI shows ◎ on both with a readable confirmation.
- WHEN the user runs `add A --auto-merge` and then `add A` with no flag,
  THEN the first reports policy_changed (was stop-before-merge). The second
  leaves A on auto-merge.
- WHEN the user runs `add A nosuch`, `add M`, `add`, `remove nosuch` and
  `remove C`, each with and without `--json`, THEN:
  - the first four exit 1 with `unknown_pr` / `terminal_pr` / usage, and
    the list is unchanged;
  - `remove C` is ok, reported as `not_target`.
- WHEN the user runs `remove A` and then `clear`, THEN:
  - A's window is kept;
  - "removed A (1 remaining)" is readable even under a sticky message;
  - the mode is off;
  - C is never started afterwards.
- GIVEN the TUI, WHEN the user drives the command bar (`autostart target
  C`, `add B`, `list`, `remove C`, bare `autostart` on and off, `autostart
  all`) and presses `A` on a non-target, on a target, and with nothing
  selected, THEN:
  - `target` is additive;
  - bare `autostart` while off prints usage;
  - only `all` enables backlog mode, with a readable "ON (all…)" line;
  - `A` adds auto-merge / removes only that PR / says "No PR selected".
- GIVEN the user has typed half of `autostart add B` in the command bar,
  WHEN another pane runs `pm autostart status --json`, then `pm autostart
  add C`, then an external `pm pr edit` triggers a reload, and the user
  types the rest and presses Enter after each interruption (repeat with
  the interruption landing after one typed character), THEN:
  - the bar keeps focus and its text, with the cursor at the end and
    nothing selected;
  - the submitted command is exactly the full text typed, and B is added;
  - no keystroke acted as a tree hotkey (no QA started, no stray refresh
    or selection change).
- GIVEN each of these owners: no session; a killed TUI with a stale
  pidfile; a killed-but-unreaped (zombie) TUI; `-s nonexistent`; and a
  directory outside any project, WHEN the user runs `status --json` and
  `add A`, THEN:
  - each exits 2 `owner_unavailable` immediately;
  - outside a project, each exits 1 with a `no_project` JSON error;
  - a command refused for a zombie owner is not applied by the next TUI.
- GIVEN the TUI held suspended, WHEN the user runs a command with
  `--timeout 2`, THEN:
  - it exits 2 `owner_timeout`, saying the command may still be applied;
  - after the TUI resumes, the state is consistent and the command was
    applied at most once.

### S18 — Shared dependency under concurrent CLI, keys and merges
Covers R3–R6, R22, R24, R36, E1, E3, E4, E6, E9.
- GIVEN a diamond X→D←Y, an independent Z and a chain T2→T1, all pending,
  WHEN two shells add X and Y at the same instant, THEN:
  - both exit 0 with their own replies;
  - D is launched exactly once (one D window ever), and Z never starts;
  - status lists D once with needed_by [X, Y], and X/Y show "blocked on D".
- GIVEN D running, WHEN, at the same moment, one shell removes X, another
  re-adds Y and adds T2, a third fires 10 parallel `status --json`, and the
  user presses `O` on T1, THEN:
  - every command gets its own valid reply, with no timeouts;
  - the target set is {Y, T2, T1};
  - D keeps running, with needed_by [Y];
  - T1 runs once, and T2 waits on T1;
  - the ◎ marks and the popup match the CLI, and no PR has two windows;
  - the cursor stays where the user put it.
- GIVEN D finished, WHEN the user merges D with `g` while a CLI `remove Y`
  races the merge (repeat with `add Y`), THEN:
  - the outcome is consistent: Y is removed, or pruned and then started
    exactly once;
  - X is not started, and there is no traceback.
- GIVEN Y advancing, WHEN Y is merged by hand (a stop target), THEN:
  - the TUI shows "target Y merged — removed (N remaining)" readably after
    the merge spinner/result line, and the same line is in `L`;
  - T1/T2 keep advancing.
- WHEN T1 and then T2 merge (the last one completing the set), THEN:
  - the last prune line says "all targets complete — auto-start OFF";
  - the mode is off, and the popup is empty;
  - no backlog PR (Z) starts.

### S19 — Merge policies, sign-off gate and refresh, finished QA, skip-QA
Covers R7, R21, R32, R36, E2, E8, ambiguity 4.
- GIVEN independent S and U, WHEN S is added with the default policy (and
  with `O`) and U with `--auto-merge` (and with `A`), THEN list, status and
  the popup show stop_before_merge for S and auto_merge for U.
- WHEN both pass review and QA, THEN:
  - S is held with a "sign off / press g" reason;
  - U's merge is refused by the sign-off gate (no SIGNOFF_MERGE), and the
    status says merge blocked by sign-off gate / awaiting sign-off;
  - `pm pr list` shows neither merged, and nothing passes
    `--no-signoff-check`.
- WHEN the user signs U off through `pm pr auto-sequence` from another
  pane, THEN:
  - the TUI, `status --json` and the open popup show the sign-off right
    away, with no stale "awaiting sign-off";
  - U merges through `pm pr merge`;
  - U leaves the target set with a readable "target U merged — removed"
    line.
- WHEN several scheduler passes and a sync/reload happen, THEN no new QA
  run starts for S or U.
- WHEN the user runs `add S` (no flag), `add S --auto-merge`, and then
  `remove S` + `add S`, THEN:
  - policies change only as flagged;
  - `policy_changed` is reported with the previous policy;
  - the stop mark survives the remove and re-add.
- GIVEN a stop-before-merge D needed by an auto-merge Q, WHEN D is
  merge-ready, THEN D is not auto-merged, and Q waits on D.
- GIVEN skip-QA enabled, WHEN an auto-merge target and a stop-before-merge
  target pass review, THEN:
  - the status says "QA skipped (skip_qa); awaiting sign-off";
  - the gate still applies;
  - the stop target stops.

Note for round 5 and later: S19's post-sign-off row for U and the transient
"Auto-merge … merging" / skip-QA log paints fall under ambiguity 12
(pr-7c32e44, pr-0a08055). Assert them through status, the popup and `L`. The
policy tag on U's header (R14) is in scope.

### S20 — Restart adoption, CLI during restart, typing after restart
Covers R19, R20, R26, R27, R33, R34, ambiguities 7–8.
- GIVEN A (stop policy, QA in flight), B (auto-merge, review iteration
  running) and C (waiting on D, D impl running), WHEN the user runs `pm tui
  restart --breadcrumb`, THEN:
  - `list --json` shows A, B and C with the same policies;
  - `tmux list-windows -F '#{window_id} #{window_name}'` is identical
    before and after;
  - A's QA continues without re-planning, and B's review keeps its window;
  - the resume summary is readable, and the popup shows the same runs.
- WHEN, during the restart, one shell runs `status --json` and another `add
  Z`, followed later by an unrelated `status`, THEN:
  - each initial command succeeds or exits 2 within `--timeout`;
  - Z is applied exactly once, right after startup, and not by the later
    unrelated command;
  - the TUI pane survives.
- GIVEN the user starts typing a command (for example `autostart li`) in
  the command bar right after the restart, WHEN the deferred startup queue
  (Z) drains and the user types the rest (`st`) and presses Enter, THEN:
  - the bar kept focus and text, with nothing selected;
  - the submitted command is the full `autostart list`, and its output
    includes Z.
- GIVEN a queue left by a TUI that died more than 60 s ago, WHEN a new TUI
  starts, THEN that command is not applied.
- GIVEN the popup open, WHEN the user presses Ctrl+R, and separately runs
  `pm tui restart`, THEN the TUI restarts (the popup does not swallow it),
  and the targets are dropped by design.
- GIVEN a legacy single-target breadcrumb produced by the master build
  (override → /opt/pm-src, `O`, override back, `pm tui restart
  --breadcrumb`), WHEN the new build consumes it, THEN:
  - that PR is the only target, with stop-before-merge;
  - no windows are duplicated.

## 10. QA round 5 scenarios (S21–S25, full detail)

Same transport workaround and setup as §6–§9, including every environment
note in §2 (rounds 1–4). Run against the PR branch head: verify `git -C <pm
checkout> log -1` before and after the run. It must be the commit that adds
this section or a later commit of this branch (never 51507548 or earlier).
Every scenario records the TUI (tmux screen recording through a grouped
view session, plus a 0.1 s `capture-pane` sampler where a Then is about a
transient paint) and every `pm` command (CLI recording). Ambiguity 12 governs
what is in and out of scope; mark extra observations informational.

Round 4 ended NEEDS_WORK on S16–S19, each with one display fix (R37);
S20 passed. Round 5 re-runs every user story end to end on the final
revision and adds the interleavings behind the round-4 fixes.

Shared resources this PR touches and where round 5 drives them
concurrently:
- The owner's command queue `~/.pm/tui-<session>.cmd-queue`, its SIGUSR2
  wake-up and per-command reply files: S22 (CLI while the user types), S23
  (parallel CLI from several shells plus TUI keys and a `g` merge), S25
  (CLI during the restart exec gap, stale queue).
- The TUI pidfile: S22 (stale, zombie, suspended owners), S25 (restart).
- The in-memory target set and the merge breadcrumb: S23, S25.
- `project.yaml` (statuses, sign-off records): S23/S24 (merges and sign-off
  from another pane while the scheduler runs).
- tmux windows (one per impl/review/QA run): S21, S23, S25 (no duplicates).
- The single TUI status/log line and the status bar: S21–S24 (confirmation
  lines against spinners, sticky lines and pulls).

### S21 — Bug repro: two targets advance; popup and CLI agree; popup notice
Covers bug §0, R1, R10, R14–R18, R23–R25, R28, R31, R35, R36, R37 (popup).
- GIVEN the branch checkout, WHEN the user runs `pytest
  tests/test_autostart_retarget_regression.py
  tests/test_autostart_multi_target.py tests/test_view_focus_command_bar.py
  tests/test_status_bar_narrow.py tests/test_log_pane_backlog.py
  tests/test_log_message_force.py tests/test_sync_status_bar_pulling.py`,
  THEN all pass.
- GIVEN independent pending PRs A and B, a PR C that depends on A, auto-start
  off, fake review NEEDS_WORK→PASS and QA PASS, WHEN the user presses `O` on
  A, moves to B and presses `O`, with a refresh or A's background start
  happening in between, THEN:
  - the cursor stays on the PR the user picked;
  - both PRs show ◎ and the status bar shows `AUTO ×2`;
  - A's impl going idle moves A to review and then QA. A never stays stuck
    in_progress (the original bug).
  - B advances independently, and each review iteration has exactly one
    review window.
- GIVEN both "armed" confirmations happened a minute or more ago, while the
  debug log stayed busy, WHEN the user opens `L` for the first time, THEN
  both `log: Auto-sequence armed …` lines are on screen without waiting.
- GIVEN A in QA and B in review iteration 2, WHEN the user opens the runs
  popup and at the same moment runs `pm autostart status --json`, THEN they
  agree on targets, policies, phase, state, reason, review iteration / QA
  progress and window names. A shows "qa planning" or scenario counts,
  never a stale "review #N". Both headers show `[stop-before-merge]`.
- GIVEN the popup open, WHEN a phase transition happens and the user runs
  `pm autostart add C` from another pane, THEN the popup updates on its own
  and shows C (waiting, blocked on A; A listed under C without an "also
  needed by" pointing at itself). `r` refreshes immediately.
- GIVEN an 80x12 terminal with `L` split and the popup open with more rows
  than fit, WHEN the user moves with ↑/↓ and j/k, presses Enter / `f` on a
  run with a window, and Enter on C's window-less row, THEN:
  - `AUTO ×N` is visible on the status bar;
  - the selected row stays in view;
  - Enter / `f` switch to the selected run's window;
  - on C the popup stays open and C's row shows "No live window for C";
    moving the selection away clears it; nothing crashes.
- GIVEN A and C targets and the notice showing on C's row, WHEN the user
  merges A with `g` (from the TUI, popup closed and reopened on C, Enter
  again to show the notice) and C then starts, THEN:
  - "target A merged — removed (N remaining)" is readable after the merge
    spinner and is in `L`;
  - C starts without user action, and once the popup refreshes and finds
    C's window the stale notice disappears; Enter then switches to C's
    window.
- GIVEN the popup, WHEN it is dismissed with Esc, `q` and `a`, and also
  opened through the command bar `autostart status` and then closed with
  Esc, THEN the tree has focus and normal keys work. `?`, the footer
  "Runs", `pm tui keys` and `pm autostart --help` document `a`/`O`/`A`
  and the verbs/policies.
- GIVEN B and C remain, WHEN the user removes both from the CLI, THEN the
  mode is off, the popup shows the empty "auto-start off" message, and no
  backlog PR is listed or started.

### S22 — CLI/command-bar management, validation, owners, typing, pulls
Covers R2, R8, R9, R11–R13, R23, R29 (corrected), R30, R32 (policy flip),
R33, R34, R37 (pulling status bar).
- GIVEN PRs A, B, C pending and M merged before the session started (with
  `gh_pr_number` set for the `#N` forms), WHEN the user runs `pm autostart
  add A B` and then re-adds A as `pr-…`, `#N` and `N`, THEN:
  - every command exits 0;
  - `list` and `list --json` show exactly A and B, stop-before-merge, with
    added_at and source;
  - the re-adds report "already a target", and A gets no second window;
  - the TUI shows ◎ on both with a readable confirmation.
- WHEN the user runs `add A --auto-merge` and then `add A` with no flag,
  THEN the first reports policy_changed (was stop-before-merge). The second
  leaves A on auto-merge.
- WHEN the user runs `add A nosuch`, `add M`, `add`, `remove nosuch` and
  `remove C`, each with and without `--json`, THEN:
  - the first four exit 1 with `unknown_pr` / `terminal_pr` / usage, and
    the list is unchanged;
  - `remove C` is ok, reported as `not_target`.
- GIVEN A and B targets and a filter active in the tree, WHEN the user
  presses `r` and also lets a background sync run, THEN during the
  "pulling" state the status bar still shows `AUTO ×2`, the filter segment
  and WCH (if watchers run); none of them blink out.
- WHEN the user runs `remove A` and then `clear`, THEN:
  - A's window is kept;
  - "removed A (1 remaining)" is readable even under a sticky message;
  - the mode is off;
  - C is never started afterwards.
- GIVEN the TUI, WHEN the user drives the command bar (`autostart target
  C`, `add B`, `list`, `remove C`, bare `autostart` on and off, `autostart
  all`) and presses `A` on a never-stop-marked non-target, on a target, and
  with nothing selected, THEN:
  - `target` is additive;
  - bare `autostart` while off prints usage;
  - only `all` enables backlog mode, with a readable "ON (all…)" line;
  - `A` adds auto-merge / removes only that PR / says "No PR selected".
- GIVEN the user has typed half of `autostart add B` in the command bar,
  WHEN another pane runs `pm autostart status --json`, then `pm autostart
  add C`, then an external `pm pr edit` triggers a reload, and the user
  types the rest and presses Enter after each interruption (repeat with
  the interruption landing after one typed character), THEN:
  - the bar keeps focus and its text, with the cursor at the end and
    nothing selected;
  - the submitted command is exactly the full text typed, and B is added;
  - no keystroke acted as a tree hotkey (no QA started, no stray refresh
    or selection change).
- GIVEN each of these owners: no session; a killed TUI with a stale
  pidfile; a killed-but-unreaped (zombie) TUI; `-s nonexistent`, WHEN the
  user runs `status --json` and `add A`, THEN each exits 2
  `owner_unavailable` immediately, and a command refused for a zombie owner
  is not applied by the next TUI.
- GIVEN a directory outside any pm project, WHEN the user runs `add A
  --json` and `remove A --json`, THEN each exits 1 with a `no_project` JSON
  error; `status --json` there exits 0 from a pane inside a running pm
  session and exits 2 `owner_unavailable` with no session.
- GIVEN the TUI held suspended, WHEN the user runs a command with
  `--timeout 2`, THEN:
  - it exits 2 `owner_timeout`, saying the command may still be applied;
  - after the TUI resumes, the state is consistent and the command was
    applied at most once.

### S23 — Shared dependency under concurrent CLI, keys and merges
Covers R3–R6, R22, R24, R36, R37 (confirmations vs merge spinner), E1, E3,
E4, E6, E9.
- GIVEN a diamond X→D←Y, an independent Z and a chain T2→T1, all pending,
  WHEN two shells add X and Y at the same instant, THEN:
  - both exit 0 with their own replies;
  - D is launched exactly once (one D window ever), and Z never starts;
  - status lists D once with needed_by [X, Y], X/Y show "blocked on D",
    and the popup lists D under both with "also needed by" the other.
- GIVEN D running, WHEN, at the same moment, one shell removes X, another
  re-adds Y and adds T2, a third fires 10 parallel `status --json`, and the
  user presses `O` on T1, THEN:
  - every command gets its own valid reply, with no timeouts;
  - the target set is {Y, T2, T1};
  - D keeps running, with needed_by [Y];
  - T1 runs once, and T2 waits on T1;
  - the ◎ marks and the popup match the CLI, and no PR has two windows;
  - the cursor stays where the user put it.
- GIVEN D finished, WHEN the user merges D with `g` while a CLI `remove Y`
  races the merge (repeat with `add Y`), THEN:
  - the outcome is consistent: Y is removed, or pruned and then started
    exactly once;
  - "Auto-start: removed Y (N remaining)" (and, on the add repeat, the
    "targets +=" line) is readable after the merge spinner, and is in `L`;
  - X is not started, and there is no traceback.
- GIVEN a `g` merge spinner running for a target, WHEN the user runs `pm
  autostart remove` on a PR that is not a target, and separately `pm
  autostart clear` while another `g` merge spins, THEN "… not a target"
  and "Auto-start: OFF" are each readable after the spinner and in `L`
  (re-add the remaining targets afterwards to continue).
- GIVEN Y advancing, WHEN Y is merged by hand (a stop target), THEN:
  - the TUI shows "target Y merged — removed (N remaining)" readably after
    the merge spinner/result line, and the same line is in `L`;
  - T1/T2 keep advancing.
- WHEN T1 and then T2 merge (the last one completing the set), THEN:
  - the last prune line says "all targets complete — auto-start OFF";
  - the mode is off, and the popup is empty;
  - no backlog PR (Z) starts.

### S24 — Merge policies, sign-off gate, finished QA, skip-QA (scoped)
Covers R7, R14/R37 (policy tags), R21, R32, R36, E2, E8, ambiguities 4 and
12. Thens follow ambiguity 12: pr-7c32e44 and pr-0a08055 behaviour is
asserted in its tolerant form, never required to paint.
- GIVEN independent S and U, WHEN S is added with the default policy (and
  with `O`) and U with `--auto-merge` (and with `A` on a never-stop-marked
  PR), THEN list and status show stop_before_merge for S and auto_merge for
  U, and the popup headers read `[stop-before-merge]` for S and
  `[auto-merge]` for U.
- WHEN both pass review and QA, THEN:
  - S is held with a "sign off / press g" reason;
  - U's merge is refused by the sign-off gate (no SIGNOFF_MERGE), and the
    status says merge blocked by sign-off gate / awaiting sign-off;
  - `pm pr list` shows neither merged, and nothing passes
    `--no-signoff-check` (check the debug log and the merge commands).
- WHEN the user signs U off through `pm pr auto-sequence` from another
  pane, THEN:
  - `status --json` shows `signoff.fresh` true for U at once, and no row in
    the TUI, `status --json` or the open popup still says "awaiting
    sign-off";
  - U then merges through `pm pr merge` with the gate passing: either the
    scheduler merges it, or (pr-7c32e44, row "merge attempt failed") the
    user's `g` merges it;
  - U leaves the target set with a readable "target U merged — removed"
    line that is also in `L`.
- WHEN several scheduler passes and a sync/reload happen, THEN no new QA
  run starts for S or U.
- WHEN the user runs `add S` (no flag), `add S --auto-merge`, and then
  `remove S` + `add S`, THEN:
  - policies change only as flagged;
  - `policy_changed` is reported with the previous policy;
  - the stop mark survives the remove and re-add.
- GIVEN a stop-before-merge D needed by an auto-merge Q, WHEN D is
  merge-ready, THEN D is not auto-merged, Q waits on D, Q's popup header
  says `[auto-merge]` and D's row carries only the stop mark.
- GIVEN skip-QA enabled, WHEN an auto-merge target and a stop-before-merge
  target pass review, THEN (through `status --json`, the popup, `L` and
  `pm pr list`, not the transient log line):
  - the status says "QA skipped (skip_qa); awaiting sign-off";
  - the gate still applies (the auto-merge target is not merged without a
    fresh SIGNOFF_MERGE);
  - the stop target stops.

### S25 — Restart adoption, CLI during restart, typing after restart
Covers R19, R20, R26, R27, R33, R34, ambiguities 7–8, 13.
- GIVEN A (stop policy, QA in flight), B (auto-merge, review iteration
  running) and C (waiting on D, D impl running), WHEN the user runs `pm tui
  restart --breadcrumb`, THEN:
  - `list --json` shows A, B and C with the same policies;
  - `tmux list-windows -F '#{window_id} #{window_name}'` is identical
    before and after;
  - A's QA continues without re-planning, and B's review keeps its window;
  - the resume summary is readable, and the popup shows the same runs
    with the same policy tags.
- WHEN, during the restart, one shell runs `status --json` and another `add
  Z`, followed later by an unrelated `status`, THEN:
  - each initial command succeeds or exits 2 within `--timeout`;
  - Z is applied exactly once, right after startup, and not by the later
    unrelated command;
  - the TUI pane survives.
- GIVEN the user starts typing a command (for example `autostart li`) in
  the command bar right after the restart, WHEN the deferred startup queue
  (Z) drains and the user types the rest (`st`) and presses Enter, THEN:
  - the bar kept focus and text, with nothing selected;
  - the submitted command is the full `autostart list`, and its output
    includes Z.
- GIVEN a queue left by a TUI that died more than 60 s ago, WHEN a new TUI
  starts, THEN that command is not applied.
- GIVEN the popup open, WHEN the user presses Ctrl+R, and separately runs
  `pm tui restart`, THEN the TUI restarts (the popup does not swallow it),
  and the targets are dropped by design.
- GIVEN a legacy single-target breadcrumb produced by the master build
  (override → /opt/pm-src, `O`, override back, `pm tui restart
  --breadcrumb`), WHEN the new build consumes it, THEN:
  - that PR is the only target, with stop-before-merge;
  - no windows are duplicated.

