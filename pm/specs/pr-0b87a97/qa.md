# QA spec — pr-0b87a97: multiple auto-start targets, `pm autostart` CLI, runs popup

Grounded in `pm/specs/pr-0b87a97/impl.md` (§5 "as built" supersedes §1–4)
and the diff against master: `pm_core/autostart_state.py`,
`pm_core/cli/autostart.py`, `pm_core/tui/auto_start.py`,
`pm_core/tui/screens.py` (`AutoRunsScreen`), `pm_core/tui/app.py` (key `a`),
`pm_core/tui/review_loop_ui.py`, `pm_core/tui/tech_tree.py`, watcher prompt.

## 0. Bug being fixed

Pre-fix the TUI held one `_auto_start_target`. Pressing `O` on PR B after
PR A repointed the target to B, so when A's implementation went idle its
impl→review transition was filtered out of scope and A stalled in
`in_progress`. Reproduction test: `tests/test_autostart_retarget_regression.py`
(`test_second_O_keeps_first_pr_advancing`). User-visible repro: in a live
session with fake Claude, `O` on A, then `O` on B; A must still advance to
review/QA.

## 1. Requirements (Given / When / Then)

### Target collection & scheduling
- **R1 additive O.** Given a session with independent PRs A and B and
  auto-start off, When the user presses `O` on A and then `O` on B, Then both
  are shown as targets (◎ on both, status bar `AUTO ×2`), both get impl
  windows, and both advance impl → review → QA without either stalling.
- **R2 idempotent re-add.** Given A is already a target, When the user adds A
  again (`O` again or `pm autostart add A`), Then the target set is unchanged
  (no duplicate entry, B kept), and the CLI reports A as already a target /
  re-armed; no second impl window for A appears.
- **R3 shared dependency once.** Given targets X and Y that both depend on
  unmerged D, When both are added, Then D is launched exactly once (one tmux
  window), status lists D once with `needed_by` containing both X and Y, and X
  and Y show `waiting` "blocked on D".
- **R4 dependency readiness.** Given target X depends on unmerged D, When
  auto-start runs, Then X is not started until D merges; after D merges
  (manually via `g`/`pm pr merge`, or auto-merge), X starts on the next
  scheduler pass without user action.
- **R5 removal is scoped.** Given targets X and Y sharing running D, When the
  user removes X, Then D's window keeps running and D remains scheduled for Y;
  X-only PRs stop being advanced (no new windows/transitions) but any already
  running window of theirs is not killed; Y keeps advancing.
- **R6 completion prunes one target.** Given targets A and B, When A merges,
  Then A disappears from the target set (log line names it), B stays and keeps
  advancing, auto-start stays on. When the last target completes or is
  removed, auto-start turns off (mode `off`), never "all".
- **R7 per-target merge policy.** Given A added with stop-before-merge (`O`,
  or CLI default) and B with `--auto-merge` (or `A` key), When both reach
  merge-readiness, Then A is not merged (status: waiting with a "press g"
  style reason) and B's merge is attempted through `pm pr merge`, which still
  enforces the sign-off gate (without a fresh SIGNOFF_MERGE the merge is
  refused and status says "merge blocked by sign-off gate"). Re-adding without
  a policy flag keeps the existing policy; `--auto-merge` switches it.
- **R8 A key toggle.** Given A is a target, When the user presses `A` on A,
  Then only A is removed; others remain. Given auto-start off and no PR
  selected, `A` prints "No PR selected" and never enables the backlog.

### CLI (`pm autostart add|remove|clear|list|status [--json]`)
- **R9 add/list/remove/clear.** Given a running TUI session, When the user runs
  `pm autostart add A B`, Then exit 0, both are listed by `list` (text and
  `--json`) with policy, and the TUI reflects them immediately (◎ marks,
  status bar). `remove A` → exit 0, A gone, B kept. `clear` → mode off,
  windows kept.
- **R10 status JSON.** When the user runs `pm autostart status --json`, Then
  output is a single JSON object with `schema: pm.autostart.status/1`,
  `owner{session,pid}`, `mode`, `targets[]`, `runs[]` where each run has
  pr_id, title, phase (pending|implementation|review|qa|sign_off|merge|done),
  state (queued|running|waiting|paused|failed|completed), reason, window
  (name/id when a window exists), review iteration / QA progress when
  available.
- **R11 validation before state change.** When the user runs add/remove with
  an unknown ID (alone or mixed with valid IDs), Then exit 1, error
  `unknown_pr` naming the bad id, nothing changes (valid ids not applied).
  Adding a merged/closed PR → exit 1 `terminal_pr`. No ids → usage error exit
  1. `remove` of a valid non-target → ok, reported `not_target`. IDs accepted
  as `pr-xxx`, `#N`, `N`.
- **R12 owner unavailable.** Given no running TUI (session never started,
  TUI killed, stale pidfile), When any `pm autostart` command runs, Then exit
  2 with `owner_unavailable` (JSON with `--json`); no reply arrives → exit 2
  `owner_timeout`. Nothing is persisted.
- **R13 command-bar parity.** The same verbs typed in the TUI command bar
  (`autostart add X`, `autostart remove X`, `autostart list`, `autostart
  status` opens popup). `autostart target X` is an additive alias; bare
  `autostart` when off prints usage (does not enable backlog); `autostart
  all` is the only way to enable backlog mode.

### Popup (key `a`)
- **R14 popup content.** When the user presses `a`, Then a modal lists each
  target (header with policy + state) and its unmerged closure PRs with
  ID/title, phase, state, reason, review iteration/QA progress, window. Shared
  deps appear with "also needed by". Empty set shows "No auto-start targets
  (auto-start off)".
- **R15 popup == CLI.** For the same moment, the popup and `pm autostart
  status --json` agree on targets, phases, states and reasons.
- **R16 live refresh.** While open, the popup refreshes (~2s) to reflect
  phase/state changes and CLI target changes without reopening; `r` forces a
  refresh.
- **R17 focus & dismiss.** j/k/↑/↓ select; Enter/f focuses the selected run's
  tmux window (popup closes); Esc/q/a close back to the TUI with normal keys
  working; Ctrl+R while open still restarts the TUI.
- **R18 discoverability.** `a` appears in footer ("Runs"), `?` help, and
  `pm tui keys`; `pm autostart --help` documents verbs/policies.

### Restart & consistency
- **R19 breadcrumb restart.** Given several targets with mixed policies and
  in-flight review/QA, When the TUI restarts via the supported breadcrumb path
  (merge-triggered restart or `pm tui restart --breadcrumb`), Then targets and
  policies are restored, live review/QA loops and impl windows are adopted (no
  duplicate windows, QA not re-run), and scheduling resumes. Plain Ctrl+R
  remains a clean restart.
- **R20 legacy breadcrumb migration.** Given a breadcrumb written by the
  pre-PR build (single `target: X`), When the new TUI consumes it, Then X
  becomes the single target with its stop policy preserved.
- **R21 finished QA not relaunched.** A PR whose QA finished PASS or
  INPUT_REQUIRED is not re-run by later scheduler passes or restarts.
- **R22 concurrent mutations.** Given a live session, When several `pm
  autostart` commands (add/remove/status) run in parallel from different
  shells while the scheduler is launching, Then every command gets its own
  reply (no cross-talk, no timeouts), final state equals the serial result,
  and no PR gets two windows.

### Added from QA round 1 fixes (verify on the final revision)
- **R23 confirmations visible.** Auto-start confirmations ("targets += X",
  "ON (all ready PRs…)", "removed X (N remaining)", "O armed") are readable in
  the TUI even when a follow-up message or a sticky log line lands in the same
  frame, and every log-line message also appears in the `L` command log.
- **R24 cursor stays put.** Refreshes, tree reorders and background PR starts
  do not move the TUI cursor; `O`/`A` act on the PR the user selected.
- **R25 one review session per iteration.** Auto-review of an idle impl
  launches exactly one review window per iteration (no throwaway session that
  consumes a review verdict); the popup shows "qa planning" / "qa <verdict>"
  rather than a stale "review #N" once a PR is in QA.
- **R26 CLI during restart is applied once.** A `pm autostart` command sent
  while the TUI is restarting is applied by the new TUI after it restores its
  breadcrumb (or reported `owner_timeout` "may still be applied"); it is never
  replayed later by an unrelated command, and a queue left by a TUI that died
  long ago (>60 s) is discarded at startup. The TUI pane survives SIGUSR2 sent
  in the exec gap.
- **R27 breadcrumb restart adopts review windows.** An in-flight review
  iteration keeps the same tmux window (same id) and transcript dir across a
  breadcrumb restart; "Auto-start: resumed after merge restart" is visible.
- **R28 popup robustness.** ↑/↓ and j/k move the selection and keep it in
  view when rows overflow the popup height; a failed refresh shows plain text
  (no markup error); Esc from a popup opened via the command bar returns focus
  to the tree.
- **R29 outside a project.** `pm autostart add/remove/status --json` run
  outside any pm project exit 1 with a JSON `no_project` error.

## 2. Setup
Per `pm/qa/instructions/tui-manual-test.md`: install pm from this branch
(`./install.sh --local` or editable venv with `PYTHONPATH` pointing at the
clone; verify with `pm which`), create a throwaway git project, `pm init
--backend local --no-import`, add PRs with the needed dependency shape, start
`pm session`, and configure fake Claude (`pm fake-claude config set`) so impl
goes idle, review emits NEEDS_WORK→PASS, QA planning emits a small plan and
scenarios PASS. Run `pm` commands from a pane inside the test tmux session.
Typical shapes: two independent PRs A,B; a diamond X→D←Y; a chain T1→T2.
Bootstrapping statuses (e.g. one `merged` PR to test `terminal_pr`) may be
set in project.yaml before the session starts only.

Environment notes learned in QA round 1:
- Run `pm push` and merge the resulting `pm/sync-*` branch into master
  before adding targets; otherwise `pm pr start` fails "not committed on
  master" (visible only in `~/.pm/debug/<tag>.log`).
- Fake QA needs `pm/specs/<id>/qa.md` (any text) for each throwaway PR or the
  QA loop stops at INPUT_REQUIRED after planning.
- tmux SIGCONTs a SIGSTOPped pane process; to hold the TUI suspended for the
  `owner_timeout` check use a `while :; do kill -STOP $P; done` loop.
- Auto-started QA `select_window` switches attached clients (pr-f094946);
  record through a grouped view session.
- Nested fake QA runs inside a scenario container no longer write into this
  PR's `/pm-captures` (237179d7); evidence for this PR lives only under
  `/pm-captures/scenarios/<n>/`. Do not treat throwaway-project QA
  metadata as this PR's evidence.

## 3. Edge cases
- E1 Target that depends on another target: dependency's own policy governs
  its merge; the dependent shows waiting on it.
- E2 Stop-before-merge dependency needed by an auto-merge target: never
  auto-merged; dependent shows waiting with that reason.
- E3 Remove a target whose review/QA loop is mid-run: loop not killed; no
  follow-on transition afterwards.
- E4 Add during an in-flight launch pass: new target is picked up.
- E5 TUI mid-restart while CLI runs: `owner_timeout` / `owner_unavailable`,
  message says the command may still be applied.
- E6 Removing the last target: mode `off`, popup shows empty message, status
  bar shows auto-start off; it never falls back to all PRs.
- E7 Mixed valid + invalid ids: whole command rejected.
- E8 `skip_qa` project: review PASS → merge path per target.
- E9 Manual merge of a stop-before-merge target via `g` / `pm pr merge`: the
  target is pruned and newly-unblocked dependents start (reload-detected
  merge kicks the scheduler).
- E10 Popup open while targets change from the CLI, and while a run's window
  disappears: popup updates, Enter on a window-less run does not crash.

## 4. Pass / Fail
Pass when every Then above is observable on the user surface (TUI pane
captures, CLI output/exit codes, `tmux list-windows`, project.yaml status as
changed through pm). Fail on: a target silently dropped/replaced; any PR with
two impl/review/QA windows; backlog PRs started when only targets were set;
an auto-merge without a fresh sign-off or a stop-before-merge PR merged; CLI
exit codes/JSON shape not as described; popup and CLI disagreeing; popup
leaving the TUI unresponsive or swallowing keys after dismiss; restart losing
targets/policies or relaunching finished/in-flight work; any traceback.

## 5. Ambiguities (resolved)
1. Default CLI policy → stop-before-merge; `--auto-merge` opt-in (impl §3.1).
2. Removing a stop-before-merge target keeps its stop mark (impl §3.2).
3. "Supported restart path" = breadcrumb restart (merge-triggered or `pm tui
   restart --breadcrumb`); plain Ctrl+R is a clean restart (impl §3.6).
4. QA PASS leaves PR in `qa`; automatic sign-off hand-off is pr-488ac6d — QA
   asserts the status *reports* this accurately, not that it happens.
5. Exact human strings in reasons are not asserted verbatim; meaning must
   match (e.g. "blocked on D", "press g").
6. Concurrency evidence: parallel CLI invocations against one owner are the
   user-reachable concurrent surface; a second PM session is out of scope
   (the PR forbids requiring one).
7. Plain `pm tui restart` / Ctrl+R (no breadcrumb) drops all targets by
   design (same as master); only the breadcrumb path preserves them.
8. After a breadcrumb restart an auto-merge target held by the sign-off gate
   may report "QA passed; awaiting sign-off" rather than "merge blocked by
   sign-off gate" (the pending-merge set is not persisted). Either is
   acceptable provided it is not merged and nothing claims it is ready to
   merge without sign-off.
9. Round 2 (S6–S10) re-verifies every requirement on the final revision
   (round 1 ended NEEDS_WORK with fixes) and adds interleaving of CLI
   commands with scheduler callbacks and TUI keys.

No unresolved ambiguities.

## 6. QA scenarios (full detail — authoritative)

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

## 7. QA round 2 scenarios (S6–S10, full detail — authoritative)

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
  starts for S or U and the QA PASS status line does not claim "merge
  manually" for an already-merged PR.
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
