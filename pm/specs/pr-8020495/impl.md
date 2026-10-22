# pr-8020495 — PR action history and active timers (impl spec)

## Background (current code)

- **Runtime mirror** — `pm_core/runtime_state.py`, `~/.pm/runtime/{pr}.json`:
  one dict per action (`start`, `review`, `review-loop`, `qa`, `merge`),
  overwritten under flock by `set_action_state`. `started_at` is
  `setdefault` (first value wins), entries are deleted when a pane vanishes
  (`pane_idle._runtime_mirror_*`), in-flight entries are deleted by
  `sweep_stale_states` on TUI mount, and the whole file is deleted by
  `pr_cleanup.cleanup_pr_resources` after merge. Writers:
  `pane_idle.py` (start/review/merge/qa panes), `tui/review_loop_ui.py`
  (`_start_loop`, `_on_iteration_from_thread`, `_on_complete_from_thread`,
  non-loop review verdict mirror), `tui/qa_loop_ui.py` (qa done+verdict),
  `tui/signoff_ui.py` (qa clear on SIGNOFF_REQA). It cannot provide history.
- **Hook events** — `~/.pm/hooks/{session_id}.json`, *latest event only*
  (`idle_prompt` / `permission_prompt` / `Stop`), overwritten per event.
  Good for "what is this session doing now", not for history.
- **Loop records** — review loop: in-memory `ReviewLoopState.history`
  (breadcrumb only on merge-restart); QA: `qa_status.json` (overwritten),
  `qa_resume.json` (deleted when the run ends), scenario captures.
  Transcripts persist per iteration.
- **Timers** (all in-memory, monotonic, nothing persisted):
  - review verdict grace `review_loop._VERDICT_GRACE_PERIOD = 20`
    (`_run_claude_review` → `poll_for_verdict(grace_period=…)`);
  - QA scenario verdict grace `qa_loop._VERDICT_GRACE_PERIOD = 30`
    (`_poll_tmux_verdicts.grace_start`, shared by all scenarios, reset on
    every relaunch);
  - QA scenario relaunch backoff `_SCENARIO_RETRY_BASE * 2**retries`
    (blocking `time.sleep(backoff)` in `_poll_tmux_verdicts`, max
    `_SCENARIO_MAX_RETRIES = 10`);
  - QA planner deadline `_PLANNER_TIMEOUT = 3600` (`run_qa_sync`);
  - sign-off relaunch throttle `signoff_ui.RELAUNCH_BACKOFF_SECONDS = 60`
    (`_launch`, `app._signoff_launched_at`);
  - workspace-trust grace (120 s, `WorkspacePromptWatch`) — no PR identity
    at the arm site.
  - There is **no** review-loop retry/backoff and no "unknown-HEAD" retry
    timer in production code (unknown HEAD → `step_signoff` stale relaunch,
    which bypasses the throttle).
- **Human holds** — review-loop INPUT_REQUIRED (`state.input_required`,
  follow-up wait with no timeout); merge-window INPUT_REQUIRED
  (`app._merge_input_required_prs`); auto-merge hold
  (`_maybe_auto_merge` → `auto_start.merge_hold`); `spec_pending`
  (project.yaml, `{phase, generated_at}`); QA INPUT_REQUIRED (runtime `qa`
  `done` + verdict, also the auto-start QA relaunch hold
  `QA_HOLD_VERDICTS`); sign-off BLOCKED (`pr["signoff"]`).
- **PR actions pane** — fzf popup `pm _popup-picker` in
  `pm_core/cli/session.py` built from module tables `_ALL_ACTIONS`,
  `_LIST_ACTIONS`, `_SHORTCUT_KEYS` (local), `_actions_for_status` (returns
  `[]` for merged/closed). There is no shared action catalog yet
  (pr-72c8695 will extract one). pr-291e891 (action-source context) is not
  merged; no action-context structure exists in the tree.

## 1. Requirements (grounded)

R1. **Durable per-PR action journal** — new `pm_core/action_history.py`.
Append-only JSONL at `pm_home()/history/{pr_id}.jsonl`; one JSON object per
line, written with `O_APPEND` under `flock(LOCK_EX)` so concurrent writers
(TUI main thread, loop threads, `qa-run-bg`, CLI) never interleave or lose
lines. Each event carries `v`, `ts` (ISO), `t` (epoch float from the
module clock), `pr_id`, `kind`, `owner` (`{pid, start}` — process start
token from `/proc/<pid>/stat`, used for liveness), and kind-specific fields.
Kinds:
  - `attempt_start` — `attempt` (random id), `action`, optional `parent`,
    `loop_id`, `iteration`, `scenario`, `retry`, `label`, `session_id` /
    `transcript`, `resumed`/`adopted` flags.
  - `phase` — `attempt`, `phase` (one of `launching`, `agent`, `verdict`,
    `verifying`, `queued`, `waiting_human`, `backoff`, `planning`), `detail`.
  - `attempt_end` — `attempt`, `outcome` (`done`, `failed`, `cancelled`,
    `superseded`, `interrupted`, `vanished`, `untracked`), optional
    `verdict`, `detail`, and `adopted` when a later owner ended a run it
    picked up (sign-off router across a TUI restart); the query shows
    such an attempt flagged `adopted`.
  - `timer_arm` — `timer` (stable id, e.g. `review-grace:<attempt>`),
    `purpose`, `owner_action`, `owner_attempt`, `armed_t`, `due_t` (null =
    indefinite hold), `effect` (`gate` = nothing happens at due, it only
    gates acceptance/relaunch; `fires` = the owner acts at due), `expected`
    (expected transition text).
  - `timer_clear` — `timer`, `reason` (`fired`, `elapsed`, `cancelled`,
    `released`, `superseded`).  A gate cleared `elapsed` after its due
    time (e.g. the QA grace cleared at scenario end) resolves at
    `min(clear, due)`: it elapsed when it ran out.
  - `owner_exit` — `reason`: the writing process stops now (journaled by
    `pane_ops.restart_app` before the in-place exec, to every PR where it
    has open attempts).  Readers bound that owner's interrupted attempts
    by its newest event of any kind, so they read `>Ns`, not `unknown`.
The journal is never deleted by `pr_cleanup` (survives merge and pane
removal). Every write is best-effort: exceptions are logged at debug and
swallowed, so instrumentation can never change control flow.

R2. **Controlled clock** — `action_history` reads time only through a
module clock (`now()` → `_clock()`, default `time.time`), overridable with
`set_clock(fn)` / `use_clock(fn)` context manager; the query takes
`now=`. Instrumentation converts in-memory monotonic durations to wall-clock
`due_t = now() + duration` at arm time.

R3. **Generic attempt capture from the runtime mirror** —
`runtime_state.set_action_state` emits journal events from *inside its
existing flock* so concurrent writers agree on one attempt:
  - entering `queued/launching/running` from a non-in-flight (or absent)
    state, **or** with a changed identity (`loop_id`, else `session_id`)
    → `attempt_start`; the new `attempt_id` is stored in the runtime
    entry (`attempt_id` field). An identity change first ends the old
    attempt as `superseded`.
  - transition to `done`/`failed` → `attempt_end` (`outcome` = state, or an
    explicit `history_outcome=` keyword, e.g. `cancelled`), with `verdict`.
  - clearing an in-flight entry → `attempt_end` `vanished` (pane gone),
    `untracked` (pane still open but PM stopped watching it, e.g. the impl
    pane once a review loop owns the PR), or `interrupted` (sweep, reason
    in `detail`, via a new `history_reason=` keyword).
  - `qa` is excluded (QA attempts are emitted by the QA loop itself, R5);
    its runtime entry is driven by per-pane registration and would
    otherwise produce attempts that start at the first scenario pane.
  The runtime file's public schema is unchanged except for the added
  `attempt_id` field and an `owner` token (R1 `owner`) on in-flight
  entries; `set_action_state` behaviour/return value unchanged.
  `sweep_stale_states` leaves in-flight entries whose `owner` is another
  live process image alone (several projects' TUIs and CLI drivers share
  one `~/.pm/runtime`), and the TUI's QA resume scan skips
  `qa_resume.json` snapshots written under another session tag.

R4. **Review-loop iterations** (`pm_core/review_loop.py`): each iteration
is a child attempt (`action="review-loop"`, `iteration=N`, `loop_id`,
`transcript`) with phases `launching` (before `_launch_review_window`),
`agent` (pane found, polling), `verdict` (verdict extracted → callbacks /
next-launch decision), `waiting_human` (INPUT_REQUIRED follow-up wait;
also an indefinite `review-input-required` hold timer). Verdict grace is a
`gate` timer (20 s) armed when polling starts and cleared when the poll
returns. Iteration ends: verdict → `done` with verdict; `PaneKilledError`
→ `vanished`; other exceptions → `failed`; stop requested → `cancelled`.
Adopted in-flight iterations (`_adopt_in_flight_review`) start with
`adopted=true`. The loop-level attempt comes from R3 (`_start_loop` →
running, `_on_complete_from_thread` → done/failed, with
`history_outcome="cancelled"` when `stop_requested`).

R5. **QA** (`pm_core/qa_loop.py`):
  - `run_qa_sync` / `resume_qa_sync` wrapped: QA run attempt
    (`action="qa"`, `loop_id`, `resumed` for resume) ended in `finally`
    with `state.latest_verdict` (`cancelled` when `stop_requested` or no
    verdict, `failed` for ERROR). Run-level phases: `planning`,
    `launching` (spec gate + concretize + scenario launch), `agent`
    (collecting scenario verdicts), `verdict` (aggregation + finalize
    pane).
  - Planner child attempt (`label="planner"`) with the planner deadline as a
    `fires` timer (`due = start + _PLANNER_TIMEOUT`, expected "give up
    planning → INPUT_REQUIRED"), cleared when planning ends.
  - Scenarios: a per-run observer (`ScenarioObserver` in
    `action_history`) is fed read-only snapshots from
    `_poll_tmux_verdicts` once per tick (and on exit). It diffs
    `{index: (pane_id, session_id, pending, verifying, queued, verdict)}`
    and emits: scenario attempt start (`scenario=N`, `retry=k`), `queued`
    phase while waiting for a concurrency slot, `verifying` phase, back to
    `agent` after a verification follow-up, attempt end with verdict, and
    end `vanished` + new attempt `retry=k+1` on relaunch.
  - Relaunch backoff: `fires` timer armed before `time.sleep(backoff)`,
    cleared (`fired`) after.  The retry attempt (`retry=k+1`) starts when
    the window is found dead, in a `backoff` phase that owns the timer, so
    the sleep is that attempt's leading wait; a successful relaunch moves
    it to `agent` (carrying the new session id), a failed one ends it
    `failed`.
  - Shared scenario verdict grace: `gate` timer armed at every
    `grace_start` assignment (id `qa-grace:<loop_id>`, re-arm replaces).
  - The observer only reads values; it never mutates loop state.

R6. **Sign-off** (`pm_core/tui/signoff_ui.py`): router launch attempt
(`action="signoff"`) started in `_launch` past the gates, ended when the
`_launch_quiet` worker finishes (`failed` on error/non-zero, otherwise the
launch is recorded as a phase `agent` and the attempt ends when `step`
routes a verdict hop, or `superseded` on a stale relaunch). The relaunch
throttle is a `gate` timer (60 s) armed at launch, cleared when
`_launched_at().pop(pr_id)` runs.

R7. **Holds** (indefinite timers, `due_t = null`, no countdown):
  - review INPUT_REQUIRED (R4), merge-window INPUT_REQUIRED
    (`_handle_merge_input_required`, only on first detection; released in
    `_finalize_detected_merge`), auto-merge hold (`_maybe_auto_merge`
    hold branch; released when a merge attempt runs, the PR merges, or a
    new sign-off router run starts — `superseded`, since the earlier
    SIGNOFF_MERGE no longer covers HEAD).
  - Derived at query time, not journaled: `spec_pending` (project.yaml,
    armed at `generated_at`), QA INPUT_REQUIRED (runtime `qa` done +
    INPUT_REQUIRED), sign-off BLOCKED (`pr["signoff"].verdict ==
    SIGNOFF_BLOCKED`).

R8. **One query/presentation model** — new `pm_core/history_query.py`:
`build_history(pr_id, *, pr=None, now=None, live=True) -> dict` (schema
`pm.pr.history/1`; `live=False` skips runtime/hook reads) and
`render_text(model, *, now=None) -> list[str]` (80-column layout; `now`
defaults to the model's `generated_at`), plus `summary_badge(model)` for
the pane row.
The model contains:
  - `attempts`: tree (roots + `children`), each with `started_at`,
    `ended_at`, `elapsed_s`, `outcome`, `verdict`, identity
    (`iteration`/`scenario`/`retry`/`label`), `phases` (ordered spans),
    `exec_s` / `wait_s` split (wait = `queued`, `waiting_human`, `backoff`
    phases; exec = the rest except `untracked` spans, E8), and an `open`
    flag (shown `running`).  An unended attempt whose owner process is
    gone is not open: `outcome` `interrupted`, `inferred` `owner-exited`,
    unknown end, elapsed as a lower bound (`elapsed_lower_bound_s`).  A runtime-derived attempt (R3) that the live runtime mirror
    still shows in flight (`attempt_id` on an in-flight entry) is
    `running` regardless of its opener: any process clearing the entry
    ends it, so a short-lived CLI opener (e.g. `pm pr auto-sequence`)
    exiting does not interrupt it.  Loop entries (`loop_id`) are the
    exception: only the opening process's loop thread advances or clears
    them, so a dead owner (e.g. a SIGKILLed TUI before the next mount
    sweep) interrupts them and the `runtime` line marks the entry
    `(stale: owner exited)`.
  - For parents with two or more scenario children: a `scenarios` dict
    with `count` (distinct scenarios), `attempts` (incl. retries),
    `wall_s` (union of child execution intervals — a scenario's leading
    `queued` wait is excluded), `sum_s` (explicitly labelled "not
    wall-clock") and `max_concurrency` — the parent's own elapsed time is
    never the sum.
  - `timers`: `active` (owner alive, not cleared, due in future or
    indefinite) with `armed_at`, `due_at`, `remaining_s` (null for holds),
    `expected`; `overdue` (`fires` timers past due, owner alive); and
    `recent` (cleared/elapsed/lost with resolution reason).
    Reconciliation: cleared → resolved; owner attempt ended → `cancelled
    (owner ended)`; owner process dead → `lost (owner process exited)`,
    except a `gate` that ran out while its owner was still alive (I9),
    which stays `elapsed`; `gate` timer past due → `elapsed`; a re-armed
    timer's earlier arm → `re-armed` (or its own clear reason when it was
    cleared before the re-arm); journaled hold still open on a
    merged/closed PR → `released (PR merged|closed)` at `merged_at`,
    whether or not its owner is still alive (merges via `pm pr merge` /
    GitHub sync never reach the TUI's hold-release point, and the arming
    TUI has usually exited by the time a merged PR's history is read).
  - `holds`: journaled + derived holds.
  - `now`: live per-action status (runtime `derive_action_status`) plus,
    for an open attempt in `agent` phase with a known session, the latest
    hook event → distinguishes "agent working", "agent turn finished at T
    (waiting for verdict / in grace)", "processing verdict", "launching
    next iteration", "waiting on human". The grace shown is the
    attempt's own `gate` timer or, failing that, the nearest ancestor's
    (the QA verdict grace is owned by the run and gates every scenario).
  - `waiting_for`: one-line summary (what PM is waiting for now). Priority:
    holds, overdue `fires` timers, an activity row needing a human
    (permission prompt / INPUT_REQUIRED wait), the soonest `fires` timer,
    then the newest activity row. The pane badge uses the same
    human-first activity row; its countdown is the row's own `fires`
    timer, or the verdict grace (own or ancestor's `gate`) only once the
    agent's turn has finished.
  - `milestones`: project.yaml timestamps (`created_at`, `started_at`,
    `reviewed_at`, `signed_off_at`, `merged_at`) as pre-journal evidence.
  - `missing`: honest notes (no journal file; journal starts after
    `created_at`; unknown timing shown as `unknown`).

R9. **CLI** — `pm pr history <pr> [--json]` in `pm_core/cli/pr.py`
(`_require_pr` / `#N` resolution via `_resolve_pr_id`). Text output =
`render_text(build_history(...))` via `emit_paged`; `--json` =
`json.dumps(model, indent=2)`. Works for merged/closed PRs and without a
TUI.

R10. **Actions pane + shared catalog** — new `pm_core/action_catalog.py`
with an `ActionDef` record and the `history` view action (`kind="view"`,
shortcut `H`, cli `pr history {pr_id}`, available for every status
including merged/closed, `query` = `history_query.build_history`, `render`
= `history_query.render_text`). The picker (`session.py`) adds a
`history` row from the catalog for every PR (including merged/closed — a
terminal PR shows only History instead of "No actions available"), binds
`H`, and dispatches view actions in-process: render the same model and show
it in `less -R` inside the popup (fallback: echo + `_wait_dismiss`). The
badge for the History row is a compact summary (`hold: …`, `overdue: …`,
`review-loop i3: turn done, 8s left`, `N runs`, `no history`).
pr-72c8695 will move the session actions into this same module.

R11. **Attribution** — events carry only `owner` (pid/start token) and an
optional `context` dict. No competing attribution model: pr-291e891 will
supply `context` (session/window/task); leave a cross-PR note.  The
query passes an attempt's start-event `context` through to the JSON
attempt rows uninterpreted (omitted when absent).

## 2. Implicit requirements

- I1. Journal writes must not raise into callers and must be cheap (one
  `open/append/close` per event); `set_action_state` must still write the
  runtime file and log/refresh exactly as before even if the journal write
  fails (e.g. read-only history dir).
- I2. Attempt ids must be unique across processes and restarts
  (`secrets.token_hex(6)`); restarts never reuse an attempt.
- I3. Reading tolerates torn/garbage lines (skip), unknown kinds, and
  events for unknown attempts (shown as orphan phase/ends are ignored).
- I4. Liveness check: the TUI restarts in place with `exec` (Ctrl+R),
  keeping its pid and start time, so pid checks alone would call a
  pre-restart owner alive. Each writing process image holds a shared flock
  on `history/owners/{instance}.lock` (opened close-on-exec, so exec,
  exit and crash all release it; a forked child takes its own instance).
  Liveness = that lock is still held. Fallback when the lock file is
  absent: `/proc/<pid>/stat` start token, then `os.kill(pid, 0)`.
  Probes take the owner lock exclusively for an instant, so concurrent
  probes serialize on `history/owners/.probe` (two unserialized probes of
  the same dead owner see each other's lock and call it alive). A pid
  reused by another process must not count as alive, and neither may an
  exited-but-unreaped (zombie) pid. A probe that cannot open the owners
  dir (read-only or broken history storage) reports unknown, never
  raises. One `build_history` judges each owner once (memoized), so all
  of an owner's open attempts and timers get the same verdict. Released
  lock files older than 30 days are pruned.
- I5. Tests isolate `pm_home` (conftest autouse fixture for the history
  dir, like `_isolated_runtime_state`).
- I6. Text output must be readable at 80 columns; times shown local
  `HH:MM:SS`, `MM-DD HH:MM:SS` when not today (full date in another
  year), and an attempt's end dated only when it falls on another day
  than its start, so rows from earlier days (most of a merged PR's
  history) still fit unwrapped; durations `1h02m`, `3m05s`, `12s`.
- I7. The picker tests that assert the exact action label list / row count
  are updated for the History row.
- I8. Journals are bounded: when a file exceeds 4 MB, the writer rotates it
  to `{pr}.1.jsonl` (one generation) and the reader reads both. Only a
  writer whose fd is still the current file (same inode) rotates, so a
  writer that opened the file just before another rotated it cannot
  replace the fresh journal over the previous generation.
- I9. Live owners touch their lock file once a second (heartbeat); a
  dead owner's last heartbeat bounds its interrupted attempts and keeps
  a `gate` that ran out before it died `elapsed` rather than `lost`.
  Only owners with an open attempt or uncleared timer are probed.

## 3. Ambiguities (resolved)

- A1. *"Retries"* — there is no review-loop retry; retries = QA scenario
  relaunches (with backoff), sign-off relaunches, review loop restarts
  (superseded), and re-runs of the same action (new attempts).
- A2. *"Approval waits"* — the human holds in R7; spec approval is derived
  from `spec_pending` (we do not journal spec approvals: approval clears
  `spec_pending`, and the hold simply disappears; the duration of past
  spec waits is not available and is not fabricated).
- A3. *"Separate waiting from execution where evidence permits"* — only
  phases PM itself observes (queued, backoff, human holds) count as wait.
  Time an agent spends idle at its prompt between hook events is not
  reconstructable (hook file keeps only the latest event), so it is part of
  the `agent` phase; the live view shows the current idle state.
- A4. *Shared catalog* — pr-72c8695 has not landed; this PR creates the
  catalog module with the History entry and the picker consumes it.
- A5. *Shortcut* — `H` (lowercase `h` is PR navigation).
- A6. Workspace-trust grace has no PR identity at its arm site; it is not
  journaled (out of scope; the attempt's `agent` phase covers the time).
- A7. Auto-start's in-memory launch dedupe / quiet-activation windows and
  TUI poll intervals are UI cadence, not PR-owned scheduled checks; not
  shown.

## 4. Edge cases

- E1. TUI restart mid-iteration: old attempts stay open in the journal;
  their owner is dead → shown `interrupted (owner exited)` with an elapsed
  lower bound from the owner's newest event (`owner_exit`, R1); the sweep
  also ends in-flight runtime attempts with `interrupted (tui-mount)`. The
  resumed loop/QA run starts new attempts flagged `resumed`/`adopted`.
- E2. Superseded review loop: the old loop's callbacks are skipped by
  `_is_active_loop`; R3 ends its attempt `superseded` when the new
  loop_id arrives; its iteration attempts end via the thread's own
  exception path (or stay open → owner alive but parent ended → shown
  `superseded`).
- E3. Concurrent scenarios: parent wall time from parent start/end; the
  sum of scenario time is only shown labelled "sum across N scenarios".
- E4. Merge: `cleanup_pr_resources` (and `pm pr merge`'s
  `_finalize_merge`, via `pr_cleanup.end_in_flight_actions`, since local
  merges kill windows without a resource cleanup) first clears in-flight runtime
  entries (ending their attempts `interrupted`, "PR resources cleaned
  up" — unlinking alone would leave them open and shown running after
  merge), then deletes runtime state; the journal remains, so `pm pr history` still works and the picker shows History for
  merged PRs.
- E5. No journal (PR older than this feature, or never run): text says
  "No recorded action history"; milestones from project.yaml still shown;
  JSON has `attempts: []` and a `missing` note.
- E6. Clock skew / due in the past for `fires` timers with a live owner →
  `overdue by Xs`, not negative remaining.
- E7. Pane removal of a `done` review (runtime keeps verdict, drops pane)
  is a pane cleanup, not an attempt end; only clearing an in-flight entry
  ends an attempt.
- E8. Re-tracked pane: PM stops watching the impl pane while a review
  loop owns the PR (the `start` attempt ends `untracked`) and
  re-registers the same session when the loop ends.  The query folds a
  runtime attempt that re-tracks the previous same-action attempt's
  session (which ended `untracked`) into that attempt, with the gap as an
  `untracked` ("not tracked") span counted as neither exec nor wait; the
  runtime mirror's attempt id for the re-opened attempt maps to the kept
  one.  A different session is a new attempt.  This removes the phantom
  "start untracked (5s)" rows seen in QA S4 without a runtime tombstone.
- E9. Claude-resolved merge: when the TUI detects a merge window's
  `MERGED` verdict (`_finalize_detected_merge`) it records runtime
  `merge` `done` + `MERGED` before killing the window, so the merge
  attempt ends `done MERGED`.  Killing the window first cleared the
  in-flight entry and journaled the successful merge as `vanished`.
- E10. Command-bar review: a typed `/pr review <pr>` gets the same
  `--transcript` as `d` (`pr_view._with_review_transcript`), so the
  review pane is tracked and journaled; without it history said "No
  recorded action history" for a review that ran (QA S35, 76742637).
- E11. Stale review transcript: after a plain `z d` review, the
  `review-<pr>.jsonl` symlink names that review's session while the
  review window may later hold a finished loop iteration's pane.  The
  non-loop review tracker registers a pane only when its start-command
  `--session-id` matches the transcript's session
  (`review_loop_ui._transcript_is_another_session`, cached per pane);
  pairing them mirrored a phantom "review running" forever (QA S26,
  c4e3f5b0).
