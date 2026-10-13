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

No unresolved ambiguities.

## 6. Shared setup and historical scenarios

Completed rounds 1–5 (S1–S25, former §6–§10) are preserved verbatim in
[qa-rounds-1-5.md](qa-rounds-1-5.md). Moving them keeps the active planner
prompt within the launcher's command-line argument limit (pr-ace66e5);
no requirement, scope decision, scenario, or evidence is discarded.
Use the current definitions below for new execution, and consult the history
file when tracing an earlier run. Preserve the original run IDs and verdicts.

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

### S27 — CLI/command bar, validation, owners, typing, prefixes, pulls
Covers R2, R8, R9, R11–R13, R23, R29, R30, R32 (policy flip), R33, R34,
R37 (pulling status bar), R38 (deferred drop, prefix/error clears).
- GIVEN PRs A, B, C pending and M merged before the session (with
  `gh_pr_number` set), WHEN the user runs `pm autostart add A B` and
  re-adds A as `pr-…`, `#N` and `N`, THEN every command exits 0; `list` /
  `list --json` show exactly A and B, stop-before-merge, with added_at and
  source; re-adds report "already a target" with no second A window; the
  TUI shows ◎ on both with a readable confirmation.
- WHEN `add A --auto-merge` then `add A` (no flag), THEN the first reports
  policy_changed (was stop-before-merge) and the second keeps auto-merge.
- WHEN `add A nosuch`, `add M`, `add`, `remove nosuch`, `remove C`, each
  with and without `--json`, THEN the first four exit 1 `unknown_pr` /
  `terminal_pr` / usage with the list unchanged; `remove C` is ok
  `not_target`.
- GIVEN A and B targets and a tree filter, WHEN the user presses `r` and a
  background sync runs, THEN during "pulling" the status bar keeps
  `AUTO ×2`, the filter segment and WCH (if watchers run).
- GIVEN the user has just pressed `w` (and separately `y`, and `z`) so a
  prefix hint is showing, WHEN another pane runs `pm autostart remove A`
  inside the 2 s prefix window and the prefix then auto-cancels (repeat:
  user presses Esc), THEN "removed A (1 remaining)" is readable for its
  full hold after the hint clears (not blanked by the prefix timer).
- GIVEN an error message showing in the log line (e.g. a refused action),
  WHEN a CLI `add` lands before its auto-clear, THEN the "targets +=" line
  is not erased when the error's timer fires.
- WHEN the user runs `clear`, and within 3 s moves in the tree and types
  `autostart list` (and separately bare `autostart`) in the command bar,
  THEN the command-bar answer stays on screen; no stale "Selected: X"
  replaces it when the hold ends. "Auto-start: OFF" was readable; C never
  starts afterwards; A's window is kept.
- GIVEN the TUI, WHEN the user drives the command bar (`autostart target
  C`, `add B`, `list`, `remove C`, bare `autostart` on and off, `autostart
  all`) and `A` on a never-stop-marked non-target, a target, and nothing
  selected, THEN `target` is additive, bare-when-off prints usage, only
  `all` enables backlog mode with a readable "ON (all…)" line, and `A` adds
  auto-merge / removes only that PR / says "No PR selected".
- GIVEN half of `autostart add B` typed in the command bar, WHEN another
  pane runs `pm autostart status --json`, then `add C`, then an external
  `pm pr edit` triggers a reload, and the user finishes typing and presses
  Enter after each interruption (repeat with the interruption after one
  character), THEN the bar keeps focus and text, cursor at the end with
  nothing selected; the submitted command is the full text and B is added;
  no keystroke acted as a tree hotkey.
- GIVEN each owner: no session; killed TUI with stale pidfile; zombie
  (killed, unreaped) TUI; `-s nonexistent`, WHEN `status --json` and `add
  A` run, THEN each exits 2 `owner_unavailable` immediately, and a command
  refused for a zombie owner is not applied by the next TUI.
- GIVEN a directory outside any pm project, WHEN `add A --json` and
  `remove A --json` run, THEN each exits 1 with `no_project` JSON;
  `status --json` there exits 0 from a pane inside a running pm session
  and exits 2 `owner_unavailable` with no session.
- GIVEN the TUI held suspended, WHEN a command runs with `--timeout 2`,
  THEN it exits 2 `owner_timeout` saying it may still be applied; after
  resume the state is consistent and the command was applied at most once.

### S28 — Shared dependency under concurrent CLI, keys and merges
Covers R3–R6, R22, R24, R36, R37 (confirmations vs spinner), R38 (held
queue, sync clears), E1, E3, E4, E6, E9.
- GIVEN a diamond X→D←Y, independent Z and chain T2→T1, all pending, WHEN
  two shells add X and Y at the same instant, THEN both exit 0 with their
  own replies; D is launched exactly once and Z never starts; status lists
  D once with needed_by [X, Y], X/Y "blocked on D", and the popup lists D
  under both with "also needed by" the other.
- GIVEN D running, WHEN at the same moment one shell removes X, another
  re-adds Y and adds T2, a third fires 10 parallel `status --json`, and the
  user presses `O` on T1, THEN every command gets its own valid reply (no
  timeouts); the target set is {Y, T2, T1}; D keeps running with needed_by
  [Y]; T1 runs once and T2 waits on T1; ◎ marks and popup match the CLI;
  no PR has two windows; the cursor stays where the user put it.
- GIVEN D finished, WHEN the user merges D with `g` while a CLI `remove Y`
  races the merge (repeat with `add Y`), THEN the outcome is consistent (Y
  removed, or pruned and started exactly once); "removed Y (N remaining)"
  (or "targets +=") is readable after the spinner and in `L`; X is not
  started; no traceback.
- GIVEN a slowed `g` merge of a target W spinning, WHEN the user runs `pm
  autostart remove` on a non-target Q, and separately `pm autostart clear`
  during another slowed merge, THEN "Q not a target" and then "target W
  merged — removed" are each readable in turn (neither replaced in one
  frame), likewise "Auto-start: OFF", and all are in `L` (re-add targets
  afterwards to continue).
- GIVEN Y advancing, WHEN Y is merged by hand while a background or manual
  GitHub/refresh sync finishes right after, THEN "target Y merged — removed
  (N remaining)" is readable for its full hold (the sync's own result line
  clear does not cut it short) and is in `L`; T1/T2 keep advancing.
- WHEN T1 and then T2 merge, THEN the last prune line says "all targets
  complete — auto-start OFF", the mode is off, the popup is empty, and Z
  never starts.

### S29 — Merge policies, sign-off gate, finished QA, skip-QA (scoped)
Covers R7, R14/R37 (policy tags), R21, R32, R36, E2, E8, ambiguities 4 and
12. Post-sign-off and transient paints are asserted in the ambiguity-12
tolerant form.
- GIVEN independent S and U, WHEN S is added with the default policy (and
  with `O`) and U with `--auto-merge` (and with `A` on a never-stop-marked
  PR), THEN list/status show stop_before_merge for S and auto_merge for U,
  and the popup headers read `[stop-before-merge]` and `[auto-merge]`.
- WHEN both pass review and QA, THEN S is held with a "sign off / press g"
  reason; U's merge is refused by the sign-off gate (no SIGNOFF_MERGE) and
  status says merge blocked by sign-off gate / awaiting sign-off; `pm pr
  list` shows neither merged; nothing passes `--no-signoff-check` (debug
  log and merge commands).
- WHEN the user signs U off through `pm pr auto-sequence` from another
  pane, THEN `status --json` shows `signoff.fresh` true for U at once and no
  row in the TUI, status or open popup still says "awaiting sign-off"; U
  then merges through `pm pr merge` with the gate passing (scheduler, or
  the user's `g` per pr-7c32e44); U leaves the target set with a readable
  "target U merged — removed" line that is also in `L`.
- WHEN several scheduler passes and a sync/reload happen, THEN no new QA
  run starts for S or U.
- WHEN `add S` (no flag), `add S --auto-merge`, then `remove S` + `add S`,
  THEN policies change only as flagged, `policy_changed` names the previous
  policy, and the stop mark survives remove/re-add.
- GIVEN stop-before-merge D needed by auto-merge Q, WHEN D is
  merge-ready, THEN D is not auto-merged, Q waits on D, Q's header says
  `[auto-merge]` and D's row carries only the stop mark.
- GIVEN skip-QA enabled, WHEN an auto-merge and a stop-before-merge target
  pass review, THEN (via `status --json`, popup, `L`, `pm pr list`) the
  status says "QA skipped (skip_qa); awaiting sign-off", the auto-merge
  target is not merged without a fresh SIGNOFF_MERGE, and the stop target
  stops.

### S30 — Restart adoption, CLI during restart, typing after restart
Covers R19, R20, R26, R27, R33, R34, ambiguities 7–8, 14.
- GIVEN A (stop, QA in flight), B (auto-merge, review iteration running),
  C (waiting on D, D impl running), WHEN the user runs `pm tui restart
  --breadcrumb`, THEN `list --json` shows A, B, C with the same policies;
  `tmux list-windows -F '#{window_id} #{window_name}'` is identical before
  and after; A's QA continues without re-planning and B's review keeps its
  window; the resume summary is readable; the popup shows the same runs
  and policy tags.
- WHEN during the restart one shell runs `status --json` and another `add
  Z`, followed later by an unrelated `status`, THEN each initial command
  succeeds or exits 2 within `--timeout`; Z is applied exactly once right
  after startup, not by the later command; the TUI pane survives.
- GIVEN the user typing `autostart li` in the command bar right after the
  restart, WHEN the deferred startup queue (Z) drains and the user types
  `st` and Enter, THEN the bar kept focus and text with nothing selected,
  and the submitted command is `autostart list` with Z in its output.
- GIVEN a queue left by a TUI that died more than 60 s ago, WHEN a new TUI
  starts, THEN that command is not applied.
- GIVEN the popup open, WHEN the user presses Ctrl+R, and separately runs
  `pm tui restart`, THEN the TUI restarts (popup does not swallow it) and
  targets are dropped by design.
- GIVEN a legacy single-target breadcrumb produced by the master build
  (override → /opt/pm-src, `O`, override back, `pm tui restart
  --breadcrumb`), WHEN the new build consumes it, THEN that PR is the only
  target with stop-before-merge, and no windows are duplicated.
