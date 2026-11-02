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
  ID/title, phase, state, reason, review iteration/QA progress, window. Every
  target header names its policy (`[stop-before-merge]` or `[auto-merge]`).
  A dependency shared by two or more targets is listed under each target with
  "also needed by <the other targets>"; a target that is itself in another
  target's closure is not annotated with itself (b336ee34). Empty set shows
  "No auto-start targets (auto-start off)".
- **R15 popup == CLI.** For the same moment, the popup and `pm autostart
  status --json` agree on targets, phases, states and reasons.
- **R16 live refresh.** While open, the popup refreshes (~2s) to reflect
  phase/state changes and CLI target changes without reopening; `r` forces a
  refresh.
- **R17 focus & dismiss.** j/k/↑/↓ select; Enter/f focuses the selected run's
  tmux window (popup closes); Esc/q/a close back to the TUI with normal keys
  working; Ctrl+R while open still restarts the TUI.
- **R18 discoverability.** `a` appears in footer ("Runs"), `?` help, and
  `pm tui keys`; `pm autostart --help` documents verbs/policies. "Footer"
  means the visible bottom command-bar hint ("press / to type a command ·
  a Runs" while the bar is unfocused); the TUI has no Textual Footer widget
  (impl §5 item 43).

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
- **R29 outside a project.** `pm autostart add/remove --json` run outside
  any pm project exit 1 with a JSON `no_project` error (the ids are
  validated against the project before anything is sent). `status`,
  `list` and `clear` do not read the project: they resolve the owner by
  tmux session, so from a pane inside a pm session they exit 0, and with
  no session they exit 2 `owner_unavailable` (S17 refine, impl §5 item 12).

### Added from QA round 2 fixes and review 9448 (verify on the final revision)
- **R30 command bar keeps focus.** While the user is typing in the command
  bar (or has `/` pending), background reloads (auto-review sync, external
  `pm pr edit`, SIGUSR1) and CLI/picker commands drained from the queue
  (e.g. a `pm autostart status`/`add` from another pane) do not move focus to
  the tree; the half-typed command completes as typed and no characters are
  interpreted as tree hotkeys (a5ef5aa4, e98caf98).
- **R31 narrow status bar.** At 80 columns or with the `L` log pane split,
  the status bar still shows `AUTO ×N` (and WCH) right after the project
  name; the repo path is clipped with an ellipsis instead (ce0b79e9).
- **R32 sign-off refresh + policy flip.** Signing off through `pm pr
  auto-sequence` updates the TUI, `pm autostart status` and the popup right
  away (no stale "awaiting sign-off" until some unrelated reload);
  `pm autostart add X --auto-merge` on an existing stop-before-merge target
  reports `policy_changed` with the previous policy, and re-adding an
  unchanged target says "already a target" (92973427, 785dd557).
- **R33 zombie owner.** A TUI process that was killed but not yet reaped
  (zombie) is reported `owner_unavailable` (stale pidfile) immediately, not
  `owner_timeout` after the full timeout, and the command is not replayed by
  the next TUI in that session (7f5cb46b).

### Added from QA round 3 fixes and review 472d (verify on the final revision)
- **R34 half-typed text survives refocus.** When focus returns to the
  command bar programmatically (a drained `pm autostart` command, the
  startup queue drain after a breadcrumb restart, a background reload), the
  half-typed text is kept with the cursor at the end, not selected; the next
  keystrokes append to it and Enter submits the full command (b9b337d4).
- **R35 L shows recent history.** Opening the `L` log pane shows the recent
  backlog (up to 500 lines), so `log: Auto-…` confirmations mirrored a few
  seconds or minutes earlier are visible without waiting for new output
  (808c8583).
- **R36 merge-prune line visible.** When a target is merged with `g` (or
  `pm pr merge`, or auto-merge), the TUI shows one readable line "target Y
  merged — removed (N remaining)"; for the last target the same line says
  "all targets complete — auto-start OFF". The merge spinner/result line
  does not hide it, and it is in `L` (e0d891a7).

### Added from QA round 4 fixes (verify on the final revision)
- **R37 round-4 display fixes.**
  - Runs popup: every target header carries its policy tag, auto-merge
    included; dependency rows carry only a stop mark (3239e71b).
  - Enter/f on a row with no live window keeps the popup open and shows
    "No live window for X" on the selected row, so it is visible even when
    the popup covers the log line (80x12). Moving the selection clears it
    (d1885432).
  - While `r` or a background sync is pulling, the status bar keeps
    `AUTO ×N`, the filter segment and WCH (b68801b8).
  - "Auto-start: removed X (N remaining)", "X not a target" and
    "Auto-start: OFF" from `pm autostart remove|clear` stay readable when a
    `g` merge spinner is running at the same moment (79575dcc).

### Added from QA round 5 fixes and review 4be9 (verify on the final revision)
- **R38 log-line ordering and scoped clears.**
  - A message deferred during a confirmation hold (e.g. tree-nav
    "Selected: X") is dropped once a newer message is shown, so the
    answer to a command-bar `autostart list` / bare `autostart` typed
    within 3 s of an add/remove/OFF stays readable (9caf9baf).
  - Held confirmations that arrive during another hold queue behind it
    (up to 3) and each is readable in turn, e.g. "Z not a target"
    followed by "target W merged — removed"; a replay never paints over
    a newer message (1c4da9e1).
  - `L` prints the backlog and then the last few `log: Auto-start /
    Auto-sequence / Auto-merge` lines under a "recent auto-start
    messages" divider, so old confirmations are on screen when `L` opens
    even with a busy debug log (bd754a14).
  - Timed clears only clear their own message: the manual-refresh
    ("Refreshed", including a refresh with nothing to report), GitHub
    sync, `log_error`/Busy, and the `z`/`w`/`y` prefix hints (2 s
    auto-cancel, second key, Esc). A held auto-start confirmation that
    lands during one of these (a CLI command during a `w` prefix, a prune
    line logged by the refresh's own scheduler pass) keeps its full hold
    (a140e22f, 64d44b9b, 8a222466).

### Added from QA round 6 fix and review 66f9 (verify on the final revision)
- **R39 L opens with the recap on screen.** Opening `L` waits ~1 s for
  the pane's own launch lines (split, pane-opened hook, rebalance,
  "launched pane"), prints them above the recap, then prints the "recent
  auto-start messages" header with the last few `log: Auto-…` lines and
  the "following log" divider, then follows. In a half-width split
  (60 columns) the header, the recap lines and the divider are all on
  screen together when `L` opens and stay there until new log output
  pushes them up. Lines written while the pane settles appear once
  above the recap and are not repeated below the divider, and nothing
  written after that is lost (5ef79e37). `pm autostart --help` names
  `--stop-before-merge` next to `--auto-merge` in its policy list.

### Added from QA round 7 fixes (verify on the final revision)
- **R40 O's armed line is a held confirmation.** `O` shows "Auto-sequence
  armed for X (will stop before merge)" as its one held confirmation
  (it replaces O's "targets +=" line). A second `O` inside an earlier
  hold (another `O`, a CLI add/remove/clear, a merge prune line) queues
  behind it and is readable for its own ~3 s; the deferred "starting X"
  never paints over it. Re-pressing `O` on a target re-arms it with the
  same line, and `O` on an auto-merge target switches it to
  stop-before-merge (d6778d7f). The bottom row of the TUI, while the
  command bar is unfocused, reads "press / to type a command · a Runs"
  (R18; 3831cbba); focusing the bar shows the usual typing placeholder,
  and leaving it restores the hint.

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

Environment notes learned in QA round 2:
- `PM_CAPTURES_PR` may be unset in the outer scenario container (the
  controlling PM is still master code). Before nested fake QA runs, pre-create
  `~/.pm/sessions/<nested-tag>/captures/<pr>` for each throwaway PR so
  captures go to the host path, not `/pm-captures`.
- The container `~/.local/bin/git` proxy forwards pulls from nested test
  projects into `/workspace` (pr-8cdbe60). Run nested `pm` sessions with
  `PATH` putting the real git first, and check `/workspace` HEAD is still the
  revision under test before and after the run (`git -C /workspace log -1`).
- Holding the TUI for `owner_timeout`: tmux SIGCONTs a stopped pane child,
  so SIGSTOP the tmux server first, then the TUI, and run the CLI with `-s
  <session>` from a shell on another tmux socket; SIGCONT both afterwards.
- Stale queue (>60 s): only a live-but-unresponsive TUI leaves one — hold
  it as above, `pm autostart add Q --timeout 2` (exit 2), `kill -9` the TUI,
  wait ≥65 s, re-run `pm session` (respawns the TUI pane).
- Sign-off for a QA-PASS PR: `pm pr auto-sequence <id>` (or `i` in the TUI)
  records sign_off and the SIGNOFF_MERGE gate record.
- To keep one PR busy while another advances, set the fake impl delay
  (`"impl":{"delay":900}`) just before adding the PR that should stay busy;
  the fake cursor is global per session type.

Environment notes learned in QA round 3:
- `pm fake-claude config set` resets the verdict cursors; set the final
  config before the PRs whose verdict sequence matters start that phase.
- With the `L` pane split at 80 columns the log pane becomes the active
  pane: send TUI keys to the TUI pane id, not `$SESS:main`.
- Popup Enter/`f` switch the attached grouped session (`$SESS~1`), so check
  the focused window there, not in bare `$SESS`.
- Local backend `#N`/`N` ids need `gh_pr_number` set in project.yaml at
  bootstrap (the file is 0444: `chmod u+w` first, before `pm session`).
- Simultaneous starts: several shell panes busy-waiting on one touch file
  start within microseconds. Read status-line messages from the last 3
  lines of `tmux capture-pane`.
- Scripts launched through `timeout` need `#!/bin/bash` (EPOCHREALTIME).

Environment notes learned in QA round 4:
- The `L` pane opens in whichever window the attached client is on, and
  auto-QA `select_window` (pr-f094946) can move the client. Press prefix+0
  (back to the TUI window) before `L`.
- CLI helper panes keep the environment they sourced when created. After
  exporting new variables (e.g. `$TUIP`, PR ids), re-source `env.sh` in
  every pane before using them.
- `pm push` is needed only when it prints a sync branch; committing `pm/`
  on master directly also works.
- `pm tui restart` under concurrent pytest load took ~30 s (CLI got
  `owner_timeout`, drained on mount). Run the pytest step before or after
  live restarts, not during them.
- To see transient paints (spinner vs confirmation), sample the TUI pane
  every 0.1 s with `tmux capture-pane` into a log, in addition to the
  asciinema recording.

Environment notes learned in QA round 5:
- The "pulling..." status-bar state lasts ~26 ms; sample `capture-pane`
  every 20 ms (not 0.1 s) to observe it.
- Fake impl makes no commits, so a `g` merge is a ~0.25 s no-op and a
  dependent starts before the user can look. To hold a merge long enough
  to observe (popup notice → window, spinner vs confirmation), commit a
  file on the target branch and add a `reference-transaction` hook in
  the test project that sleeps ~4 s on `refs/heads/master`.
- `pm pr auto-sequence <id>` may need a second call before it reads the
  fake SIGNOFF_MERGE record.
- After a merge the tree reorders (merged PR hidden); re-locate the
  cursor by PR id before the next `g`.
- `L` keeps only 500 lines of backlog plus the recap; open it soon after
  the event being checked.
- Plain `pm tui restart` with finished fake QA panes can crash the QA
  resume (pr-ae66f59, filed, out of scope).

Environment notes learned in QA round 6:
- The spec PATH that puts the real git first can drop `~/.local/bin`,
  which holds the fake-claude shim; then impl windows die at once.
  Append a directory that contains only `fake-claude`.
- Committing on a branch after `pm pr auto-sequence` makes its
  SIGNOFF_MERGE stale, and `g` is refused. Commit before signing off.
- On the local backend a second `g` merge (W2 after W1) can fail
  ff-only because the workdir master is stale, and pm opens a
  merge-resolution window (pr-a75da60, out of scope). Workaround: reset
  the workdir master to origin/master.
- Esc followed at once by `L` in tmux reads as Alt+L; sleep ~0.3 s
  between them.
- After `/`, wait for "CommandBar: got focus" in the debug log before
  typing (otherwise pr-6412997 eats h/j/k/l).

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
10. Round 3 (S11–S15) runs on the post-review revision (e98caf98 or later).
   Round 2 S10 passed; S15 re-checks restart/queue behaviour because
   7f5cb46b and e98caf98 changed owner detection and queue draining after
   that pass. Known, filed and out of scope: pr-92041d7 (stale "merge
   manually" log), pr-7c32e44 ("merge attempt failed" row after sign-off),
   pr-97614ed (finished review summary lost after breadcrumb restart),
   pr-3951487 (respawned TUI window named python3), pr-f094946
   (select_window switches clients), pr-488ac6d (no automatic sign-off
   hand-off). Observing one of these is not a failure of this PR.
11. Round 4 (S16–S20) runs on 85ba8955 or a later commit of this branch.
   Round 3 S14 passed, but e0d891a7 changed the prune that runs when a
   target merges, so S19 re-checks the merge path end to end. Also known,
   filed and out of scope: pr-22c92ef (`AUTO ×N` clipped in an unzoomed
   ~40-column pane; 80 columns must still show it), pr-6412997 (with `/`
   pending, the tree consumes h/j/k/l before the command bar opens).

12. Scope boundaries for round 5 and later. Round 4 S19 first reported
   PASS although some concrete Thens had failed. Independent verification
   flagged it, and it ended NEEDS_WORK with one in-scope fix (3239e71b).
   Planners and refiners must follow these rules:
   - **In scope (assert them):**
     - The policy and gate behaviour in R7, R21, R32 and R36: a
       stop-before-merge PR is never merged automatically; an auto-merge PR
       merges only after a fresh SIGNOFF_MERGE, through `pm pr merge`
       without `--no-signoff-check`; and so on.
     - The policy tags on the popup headers (R14, R37).
     - Every fix listed in R23–R37.
   - **Out of scope (do not write Thens that need them):**
     - pr-7c32e44. After an auto-merge PR whose merge the gate refused is
       signed off, its status row may read "merge attempt failed; no merge
       window" (state failed), and the scheduler may not retry the merge.
       In that case assert:
       - `signoff.fresh` is true in `status --json`, and no row still says
         "awaiting sign-off";
       - the user's `g` (or `pm pr merge`) then merges it with the gate
         passing.
     - pr-0a08055 (pre-existing on master). These lines may not paint in
       the TUI log line: "Auto-merge: X … merging", the skip-QA "review
       passed, skipping QA", and "ready to merge … press g", because the
       sticky "Review loop done" line or a same-frame merge error hides
       them. Assert those transitions through `status --json`, the popup,
       the `L` log and project.yaml instead. The R23/R36 lines are still
       required to paint.
     - Everything listed in ambiguities 10 and 11.
   - **Wording, not bugs:**
     - `mode` is "targets", not "on".
     - `A` on a PR that kept an earlier stop mark adds it as stop (the stop
       mark survives a remove, per ambiguity 2), so use a PR that was never
       stop-marked to test `A` → auto-merge.
     - The status bar at 80 columns clips the repo path and may clip the
       last characters of a filter label. Only `AUTO ×N` must survive.
   - **Rules for writing Thens:**
     - Concrete steps must not add obligations that the R-items and
       scenario text above do not require. Mark any extra observation as
       informational.
     - A literal Then that fails is never waived as a harness or wording
       issue. Fix it (NEEDS_WORK), or return INPUT_REQUIRED and name the
       contract conflict.

13. Round 5 (S21–S25) runs on the commit that adds §10 of this spec or a
   later commit of this branch (it includes review 6ad2's 1224d3f1). Round
   4 S20 passed, and no restart code changed since, but S25 re-runs it on
   the final revision because the remove/clear confirmations (79575dcc)
   and the popup notice (d1885432, 1224d3f1) are on paths a restart
   replays. R29 was corrected this round (see the R-item): `status`/`list`
   outside a project is not a `no_project` error. Round 5 S24 follows
   ambiguity 12 exactly; its post-sign-off Thens are written in the
   pr-7c32e44-tolerant form.

14. Round 6 (S26–S30) runs on the commit that adds §11 of this spec or a
   later commit of this branch (it includes review 4be9's a140e22f,
   64d44b9b and 8a222466). Round 5 ended NEEDS_WORK on S21–S23 with
   log-line fixes (R38); S24 and S25 passed. Review 4be9 then changed
   how every timed log-line clear works, which touches the confirmation
   paints that all five stories check, so round 6 re-runs all five.
   Also known, filed and out of scope: pr-edc256b (WCH missing until the
   next refresh after `w s`), pr-ae66f59 (QA resume crash on a vanished
   pane after plain restart). Ambiguity 12 still governs scope.

15. Round 7 (S31–S32) runs on the commit that adds §12 of this spec or
   a later commit of this branch. Round 6 S27–S30 PASS and were
   independently VERIFIED on e17d5671 (evidence index
   `shepherd-20261012/qa-round-6-evidence-index.json`; run
   pr-0b87a97-1528f33320623871). The application changes since then are
   one commit: 5ef79e37, the `L` pane command in `pane_ops.log_pane_command`
   and the help text. Scheduling, target ownership, sign-off gates,
   restart and log-line hold/clear logic are unchanged. By the
   impact-based scope guidance (PR note, 03:09Z), round 7 re-runs S26
   in full as S31 because it ended NEEDS_WORK. S32 covers the places
   where 5ef79e37 meets other workflows: `L` read at the same time as
   concurrent writers, `L` used as evidence after merges, policy
   changes and restarts, reopening and `z L`, and the help. The
   S27–S30 evidence is carried forward for e17d5671 and is not
   reclassified. The first round-7 launch (pr-0b87a97-1c4694f0e44f9c4c)
   failed before planning with zero scenarios. It is not evidence. If
   further review changes touch other code, the plan must expand to
   cover them. Ambiguity 12 still governs scope.

16. S32 restart/focus contract conflict resolved by the supervisor on
   2026-10-13: concretization added a Then requiring the transient TUI
   line `Focused existing log pane` to be visible immediately after
   restart. That line can be suppressed by the existing sticky restart
   summary even when pane focus works correctly. R39 and the published
   S32 require actual focus/reuse, live resume output, stable targets and
   windows, and a fresh recap after `z L`; they do not require a new
   priority relationship between these transient messages. Check focus
   using the active pane and preserved pane ID, plus the required log
   output. The suppressed feedback is an informational incidental
   finding, not an application change for #229. Preserve the original
   failed extra assertion and this explicit resolution in the scenario
   report; independent verification must check all the actual S32
   requirements and identify which contract it assessed. This corrects
   concretization's extra obligation under ambiguity 12; it does not
   turn the original literal assertion into a pass.

17. Round 8 (S33–S34) runs on the commit that adds §13 of this spec or
   a later commit of this branch. Round 7 S32 is independently VERIFIED
   on 7e9d414a (its extra transient-feedback assertion stays FAILED and
   out of scope, ambiguity 16, pr-2428766). S31 ended NEEDS_WORK with two
   application commits: d6778d7f (`O` armed line via `add_targets`
   `confirm=`) and 3831cbba (bottom hint "· a Runs"). The `L` pane
   command, scheduler decisions, merge gates, restart adoption, popup
   refresh and the log-line hold/clear code are unchanged. By the
   impact-based scope guidance (PR note after round 7), round 8 re-runs
   S31 end to end as S33, and S34 covers the places where the two
   commits meet other workflows: `O` inside other held confirmations
   (CLI, merge prune, other `O`s) and command-bar answers, `O` on an
   existing/auto-merge/refused PR, `O` racing CLI writers, and the hint
   across focus changes, queued CLI commands, the popup, narrow splits
   and a breadcrumb restart. S32 (7e9d414a) and S27–S30 (e17d5671) are
   carried forward with those revisions and are not reclassified.
   No review pass of these two commits is recorded yet; if review
   changes other code, the plan must expand. Ambiguity 12 still governs scope; with
   four or more held confirmations back to back the held queue keeps
   only the newest three on screen by design (R38), so Thens about
   back-to-back lines use at most three.

No unresolved ambiguities.

## 6. Shared setup and historical scenarios

Completed rounds 1–5 (S1–S25, former §6–§10) are preserved verbatim in
[qa-rounds-1-5.md](qa-rounds-1-5.md). Moving them keeps the active planner
prompt within the launcher's command-line argument limit (pr-ace66e5);
no requirement, scope decision, scenario, or evidence is discarded.
Use the current definitions below for new execution, and consult the history
file when tracing an earlier run. Preserve the original run IDs and verdicts.
Round 6 S26 (§11) stays here because S31/S33 re-run it; the
carried-forward S27–S30 definitions are verbatim in
[qa-round-6-carried.md](qa-round-6-carried.md) (ambiguities 15, 17).
Round 7 (§12) defines S31, which S33 re-runs; round 8 (§13) is the
current execution.

The machine-readable QA_PLAN block for this run is deliberately compact (PR
transport workaround: ≤22 lines × ≤60 cols, pending pr-b8561ac). Each
scenario's `STEPS:` line there points here; **the current scenario sections below define the steps**. Every scenario: follow `pm/qa/instructions/tui-manual-test.md`
setup (pm installed from this branch, throwaway project, `pm session`, fake
Claude configured so impl goes idle, review NEEDS_WORK→PASS, QA plan of 1–2
scenarios that PASS), drive only through the TUI keys, command bar and `pm`
CLI (run from a pane inside the test tmux session), and capture a tmux
screen recording of the TUI plus a CLI recording of the `pm autostart`
commands. Assert on what is visible: pane captures, CLI stdout/exit codes,
`tmux list-windows`, `pm pr list`.

## 11. QA round 6 scenarios (S26–S30, full detail — authoritative)

Use the shared transport workaround and setup in §6 above, including every environment
note in §2 (rounds 1–5). Run against the PR branch head: verify `git -C <pm
checkout> log -1` before and after the run. It must be the commit that adds
this section or a later commit of this branch (never 8a222466 or earlier).
Every scenario records the TUI (tmux screen recording through a grouped
view session, plus a `capture-pane` sampler at 0.1 s, or 20 ms where a Then
is about the ~26 ms "pulling" state) and every `pm` command (CLI
recording). Ambiguities 12 and 14 govern scope; mark extra observations
informational. A literal Then that fails is fixed (NEEDS_WORK) or returned
INPUT_REQUIRED with the contract conflict named, never waived.

Round 5 ended NEEDS_WORK on S21–S23 with log-line fixes; review 4be9 then
rescoped every timed clear (R38). Round 6 re-runs every user story end to
end on the final revision and adds the interleavings behind R38: a refresh,
a GitHub sync, a `z`/`w`/`y` prefix or an error auto-clear landing while an
auto-start confirmation is held, and two held confirmations back to back.

Shared resources and where round 6 drives them concurrently:
- Command queue `~/.pm/tui-<session>.cmd-queue`, SIGUSR2 wake-up, reply
  files: S27 (CLI while typing / during a prefix), S28 (parallel shells +
  keys + `g`), S30 (exec gap, stale queue).
- TUI pidfile: S27 (stale, zombie, suspended), S30 (restart).
- In-memory target set and merge breadcrumb: S28, S30.
- `project.yaml` statuses and sign-off records: S28, S29.
- tmux windows (one per run): S26, S28, S30 (no duplicates).
- The single TUI log line, its hold queue and timed clears, the status bar
  and the `L` pane: S26–S29.

### S26 — Bug repro: two targets advance; popup and CLI agree; L recap
Covers bug §0, R1, R10, R14–R18, R23–R25, R28, R31, R35–R38.
- GIVEN the branch checkout, WHEN the user runs `pytest
  tests/test_autostart_retarget_regression.py
  tests/test_autostart_multi_target.py tests/test_view_focus_command_bar.py
  tests/test_status_bar_narrow.py tests/test_log_pane_backlog.py
  tests/test_log_message_force.py tests/test_sync_status_bar_pulling.py`,
  THEN all pass.
- GIVEN independent pending PRs A and B, a PR C that depends on A,
  auto-start off, fake review NEEDS_WORK→PASS and QA PASS, WHEN the user
  presses `O` on A, moves to B and presses `O`, with a refresh or A's
  background start in between, THEN:
  - the cursor stays on the PR the user picked;
  - both show ◎ and the status bar shows `AUTO ×2`;
  - A's impl going idle moves A to review then QA; A never stays stuck
    in_progress (the original bug);
  - B advances independently; each review iteration has one review window.
- GIVEN both "armed" confirmations happened a minute or more ago with a
  busy debug log, WHEN the user opens `L`, THEN both `log: Auto-sequence
  armed …` lines are on screen at once (in the recent auto-start messages
  recap) without waiting or scrolling.
- GIVEN A in QA and B in review iteration 2, WHEN the user opens the popup
  and at the same moment runs `pm autostart status --json`, THEN they agree
  on targets, policies, phase, state, reason, review iteration / QA progress
  and window names; A shows "qa planning" or scenario counts, never a stale
  "review #N"; both headers show `[stop-before-merge]`.
- GIVEN the popup open, WHEN a phase transition happens and the user runs
  `pm autostart add C` from another pane, THEN the popup updates on its own
  and shows C waiting, blocked on A (A under C without "also needed by"
  itself); `r` refreshes immediately.
- GIVEN an 80x12 terminal with `L` split and more popup rows than fit, WHEN
  the user moves with ↑/↓ and j/k, presses Enter / `f` on a run with a
  window, and Enter on C's window-less row, THEN `AUTO ×N` is visible, the
  selected row stays in view, Enter/`f` switch to that run's window, and on
  C the popup stays open with "No live window for C" on the row, cleared
  when the selection moves; nothing crashes.
- GIVEN the notice showing on C's row and A's merge slowed (see §2 round 5
  notes), WHEN the user merges A with `g` and then presses `r` within the
  3 s hold of the prune line, THEN "target A merged — removed (N
  remaining)" stays readable for its hold (the refresh's own "Refreshed"
  clear does not cut it short) and is in `L`; C starts without user
  action; once the popup finds C's window the notice disappears and Enter
  switches to C's window.
- GIVEN the popup, WHEN it is dismissed with Esc, `q` and `a`, and also
  opened through the command bar `autostart status` then closed with Esc,
  THEN the tree has focus and normal keys work; `?`, the footer "Runs",
  `pm tui keys` and `pm autostart --help` document `a`/`O`/`A` and the
  verbs/policies.
- GIVEN B and C remain, WHEN the user removes both from the CLI, THEN the
  mode is off, the popup shows the empty "auto-start off" message, and no
  backlog PR is listed or started.

S27–S30 (round 6, PASS/VERIFIED on e17d5671, carried forward) are
preserved verbatim in [qa-round-6-carried.md](qa-round-6-carried.md).

## 12. QA round 7 scenarios (S31–S32, full detail — authoritative)

Use the setup in §6 and every environment note in §2 (rounds 1–6). Run
against the PR branch head: check `git -C <pm checkout> log -1` before and
after the run. It must be the commit that adds this section or a later
commit of this branch (it contains 5ef79e37). Record the TUI (tmux screen recording through a grouped
view session plus a 0.1 s `capture-pane` sampler of the TUI pane and,
when `L` is open, of the log pane) and every `pm` command (CLI
recording). Ambiguities 12 and 15 govern scope. Mark extra observations
informational. A literal Then that fails is fixed (NEEDS_WORK) or
returned INPUT_REQUIRED with the contract conflict named. It is never
waived. Each verdict names the revision it covers.

Shared resources driven concurrently in round 7:
- The TUI debug/command log file (`command_log_file()`). The TUI and
  CLI-triggered commands write to it while the `L` pane counts and
  reads it at open and then follows it: S31, S32.
- The command queue, SIGUSR2 and reply files: parallel CLI adds, removes
  and status polls while `L` opens (S32), and a CLI add while the popup
  is open (S31).
- tmux panes/windows: one log pane per window (reopen, `z L`), one window
  per run (S31, S32).
- The in-memory target set and merge breadcrumb (S32 restart).

### S31 — Bug repro: two targets advance; popup == CLI; L recap on screen
Re-runs S26 (§11) end to end on the final revision. Every S26 Then still
applies unchanged. In addition:
- The pytest step adds `tests/test_log_pane_backlog.py` (already listed)
  and must include `test_log_pane_prints_launch_burst_above_recap`; all
  pass.
- The `L` story becomes: GIVEN both "armed" confirmations happened a
  minute or more ago with a busy debug log, WHEN the user opens `L` in
  the default half-width split (about 60 columns), THEN in the first
  capture after the pane settles (≤2 s) the "recent auto-start
  messages" header, both `log: Auto-sequence armed …` lines and the
  "following log" divider are all on screen at once. The pane's own
  launch lines are above the header, not between the recap and the
  divider. They stay on screen for at least 10 s unless new log
  output pushes them up. Repeat once with a full-width 80-column
  terminal.
- The help story adds: `pm autostart --help` shows `--stop-before-merge`
  and `--auto-merge` in the policy list.
- Bug assertion (§0): after `O` on A then `O` on B, A leaves
  `in_progress` for review and then QA without any user action, as
  shown in the TUI, `pm pr list` and `status --json`.

### S32 — L pane with concurrent writers and as evidence across workflows
Covers R39 together with the R23, R35, R36, R37 and R38 checks that use
`L` as their evidence, and R19 (restart) only as far as `L` reaches it.
- GIVEN a session with targets A and B and a busy debug log, WHEN the
  user opens `L` while, inside the same ~1 s, several shells fire in
  parallel `pm autostart add C`, `remove C`, `add C` and 10 `status
  --json` polls, THEN:
  - every CLI command exits 0 with its own reply;
  - each auto-start line logged during the settle appears exactly once
    above the header and again in the recap. It is not repeated after
    the "following log" divider;
  - lines logged after the pane settles appear after the divider, with
    no gap: count them against the debug log file;
  - the final targets match the serial result;
  - one log pane exists.
- GIVEN `L` open, WHEN the user closes it and reopens it with `L`, and
  then uses `z L` (fresh), THEN each open shows the backlog, the burst,
  the header with the latest auto-start lines, and the divider. Only one
  log pane exists afterwards, and the TUI keys still work.
- GIVEN a target W whose merge is slowed (§2 round 5), WHEN the user
  merges W with `g` and opens `L` within a few seconds, THEN "target W
  merged — removed (N remaining)" is in the recap on screen when `L`
  opens. The TUI log line showed it readably after the spinner (R36).
  The same holds for a CLI `remove` and for `clear` ("Auto-start: OFF")
  that race a slowed merge.
- GIVEN an auto-merge target U held by the sign-off gate, WHEN the user
  flips a stop-before-merge target to auto-merge with `pm autostart add
  S --auto-merge`, signs U off with `pm pr auto-sequence`, and opens `L`,
  THEN the recap shows the "targets += S (now auto-merge)" line, the
  TUI, popup and `status --json` drop "awaiting sign-off" for U at once
  (R32), and U merges only through the gate (ambiguity 12 tolerant
  form); its "target U merged — removed" line is in the next `L`
  recap. `L` only reports what the TUI logged; opening it changes no
  status.
- GIVEN targets with in-flight review/QA and `L` open, WHEN the user runs
  `pm tui restart --breadcrumb` and presses `L` after the TUI comes
  back, THEN ordinary `L` focuses the existing live log pane; its live
  output contains "Auto-start: resumed after merge restart" (or the
  resume summary), targets and windows are unchanged (`tmux list-windows`
  before and after), and there is at most one log pane. WHEN the user
  then uses `z L` (fresh), THEN the new recap contains that resume line
  and there is still only one log pane. This distinguishes the existing
  focus behavior from a fresh launch; ordinary `L` does not regenerate
  an already-open pane's recap.
- GIVEN the TUI at 80x12 with `L` split, WHEN the user opens the runs
  popup and dismisses it, THEN `AUTO ×N` is still shown, the popup works
  as in S26, and Esc followed by `L` (with a short pause) opens `L`, not
  Alt+L.

## 13. QA round 8 scenarios (S33–S34, full detail — authoritative)

Use the setup in §6 and every environment note in §2 (rounds 1–6). Run
against the PR branch head: check `git -C <pm checkout> log -1` before and
after the run. It must be the commit that adds this section or a later
commit of this branch (it contains d6778d7f and 3831cbba). Record the TUI
(tmux screen recording through a grouped view session plus a 0.1 s
`capture-pane` sampler of the TUI pane and, when `L` is open, of the log
pane) and every `pm` command (CLI recording). Ambiguities 12 and 17
govern scope. Mark extra observations informational. A literal Then that
fails is fixed (NEEDS_WORK) or returned INPUT_REQUIRED with the contract
conflict named. It is never waived. Each verdict names the revision it
covers.

Shared resources driven concurrently in round 8:
- The single TUI log line, its hold timer and its held queue (max 3):
  `O` presses, CLI confirmations and merge prune lines landing inside
  each other's holds (S33, S34).
- The command queue, SIGUSR2 and reply files: CLI adds/removes/status
  racing `O`, and a CLI command drained while the command bar is empty
  or half-typed (S34).
- The in-memory target set, stop marks and merge breadcrumb: `O`
  re-arm/policy switch racing CLI writers, and a breadcrumb restart
  (S34).
- The command bar (bottom row): its focus, text and hint (S33, S34).
- tmux windows: one per run, never duplicated by repeated `O` (S33, S34).

### S33 — Bug repro: two O targets advance; popup == CLI; L; Runs hint
Re-runs S31 (§12), and through it S26 (§11), end to end on the final
revision. Every S26 and S31 Then still applies unchanged. In addition:
- The pytest step must include
  `test_second_O_inside_first_hold_keeps_its_armed_line`
  (tests/test_autostart_multi_target.py) and
  `test_unfocused_hint_advertises_runs_popup`
  (tests/test_view_focus_command_bar.py); all pass.
- The two-`O` story: GIVEN A and B pending and auto-start off, WHEN the
  user presses `O` on A, presses `r`, and presses `O` on B about 2.5–2.9 s
  after the first `O` (inside A's hold), THEN "Auto-sequence armed for A
  …" is readable for its hold and then "Auto-sequence armed for B …" is
  readable for its own ~3 s; neither is replaced by "starting A/B" or a
  refresh line within a frame; both are in the `L` recap; `AUTO ×2`, ◎ on
  both, one impl window each. A then leaves `in_progress` for review and
  QA without user action (bug §0), in the TUI, `pm pr list` and
  `status --json`.
- The `L` recap story runs at both the default half-width split (~60
  columns) and a full-width 80-column terminal, as in S31.
- The hint story: GIVEN the TUI with the command bar unfocused, at full
  width and at an actual 80x12 TUI pane with `L` available in a split
  (zoom the TUI pane for the full-width assertion), THEN the bottom row reads "press /
  to type a command · a Runs" and pressing `a` opens the runs popup.
  The hint may clip in the narrower unzoomed split, as documented by
  impl §5 item 43; this does not add a full-hint requirement at ~39 columns.
  WHEN the user presses `/`, THEN the bar shows the typing placeholder;
  the user types `autostart list` and presses Enter, and separately types
  part of a command and presses Esc; THEN the command runs as typed (no
  dropped or selected characters), and after each the hint "· a Runs" is
  back with the tree focused and normal keys working.

### S34 — O hold and the Runs hint across workflows
Covers R40 with R2, R7, R18, R22, R23, R34, R36, R38 and R19 as far as
`O` and the hint reach them. Setup: independent pending PRs P1–P4 and a
target W whose `g` merge is slowed (§2 round 5 notes), fake Claude as in
§6, CLI helper panes in the test tmux session.
- GIVEN auto-start off, WHEN a CLI pane runs `pm autostart add P1` and
  within its 3 s hold the user presses `O` on P2 and then `O` on P3,
  THEN "targets += P1", "Auto-sequence armed for P2 …" and "Auto-sequence
  armed for P3 …" are each readable in turn (no line replaced within a
  frame; no "starting Px" painted over an armed line before its hold
  ends); all three are in the `L` recap; the target set is {P1, P2, P3}
  with P1–P3 stop-before-merge; each starts exactly once.
- GIVEN P4 added with `pm autostart add P4 --auto-merge` (popup header
  `[auto-merge]`), WHEN the user presses `O` on P4, THEN the armed line is
  readable; `list --json`, `status --json` and the popup header now show
  stop-before-merge for P4; no second P4 window. WHEN the user presses
  `O` on P4 again, THEN the same armed line shows, the set and the other
  policies are unchanged, still one window. WHEN a CLI pane then runs
  `pm autostart add P4 --auto-merge`, THEN it reports `policy_changed`
  (was stop-before-merge).
- GIVEN W ready to merge with its merge slowed, WHEN the user merges W
  with `g` and presses `O` on another pending PR while the "target W
  merged — removed (N remaining)" line is held, THEN the prune line and
  then the armed line are each readable in turn after the spinner; both
  are in `L`; the newly armed PR starts once.
- GIVEN the user just pressed `O` on a PR, WHEN within 3 s the user moves
  in the tree and types `autostart list` (and separately bare
  `autostart`) in the command bar, THEN the command-bar answer stays on
  screen when the armed hold ends; no stale "Selected: X" or "starting
  X" replaces it; the list includes the armed PR.
- GIVEN targets P1 and P2, WHEN the user presses `O` on P3 at the same
  instant as two CLI panes run `pm autostart remove P1` and `add P4` and
  a third fires 10 `status --json` polls, THEN every CLI command exits 0
  with its own reply; the final set equals the serial result
  {P2, P3, P4}; P3 is stop-before-merge; every confirmation is represented
  in `L`, with each actual source debug-log record copied once into its
  appropriate backlog/burst/follow region (R39); the recap intentionally
  repeats up to the last 8 matching source records. Do not infer duplicate
  actions from recap repetition or separately logged enqueue/display
  records. No PR has two windows; the cursor stays on P3.
- GIVEN the bar unfocused and empty, WHEN another pane runs `pm
  autostart status --json` and `add` (drained from the queue), THEN the
  bottom row still reads "… · a Runs" and the tree keeps focus. GIVEN
  half of `autostart add P1` typed in the bar, WHEN the same CLI commands
  drain, THEN the text is kept with the cursor at the end (R34), Enter submits the full
  command, and the hint returns afterwards.
- GIVEN the runs popup open, WHEN it is closed with Esc, `q` and `a`, and
  opened from the command bar `autostart status` then closed with Esc,
  THEN the bottom row reads "… · a Runs" each time and `a` reopens the
  popup.
- GIVEN targets added with `O` (stop) and with `--auto-merge`, WHEN the
  user runs `pm tui restart --breadcrumb`, THEN after the restart the
  targets and policies are unchanged (`list --json`, popup headers),
  `tmux list-windows` is identical before and after, the bottom row
  reads "… · a Runs", and `O` on a pending PR then shows its armed line
  and adds it without disturbing the restored targets.
