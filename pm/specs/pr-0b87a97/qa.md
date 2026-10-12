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
