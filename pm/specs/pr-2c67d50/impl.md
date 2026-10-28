# Spec — pr-2c67d50: resume QA scenario polling after INPUT_REQUIRED

## 0. Problem

A QA scenario worker that emits `INPUT_REQUIRED` is treated as terminal today:

- `_poll_tmux_verdicts` (`pm_core/qa_loop.py`) records the verdict in
  `state.scenario_verdicts`, removes the scenario from its local `pending`
  set, and never reads that pane's transcript again.
- When all runnable work is done, `_execute_and_finalize` aggregates the
  verdicts (`INPUT_REQUIRED` wins over `PASS`) and runs the finalize pane.
- `qa_loop_ui.poll_qa_state` calls `_on_qa_complete` (records a QA note,
  logs "paused for human input"), then drops the completed state from
  `app._qa_loops` and clears `qa_resume.json`.

The user then answers the blocker in the *original worker pane*. The worker
finishes and emits a new verdict, but nothing consumes it: the collector no
longer polls the scenario, the TUI no longer tracks the run, and autostart
keeps reporting the original `INPUT_REQUIRED` (#267 QA `fb7eecdb7ab986be`,
note-8ee427c).

`review_loop.py` already solves the single-pane version of this: on
`INPUT_REQUIRED` it calls `loop_shared.wait_for_follow_up_verdict`, which
waits for a *new* idle event and accepts only a verdict turn whose transcript
line is newer than the one that prompted the wait (pr-8efa789).

## 1. Requirements (grounded in code)

### R1 — Live run: a worker `INPUT_REQUIRED` keeps the scenario polled

In `_poll_tmux_verdicts`, when a verdict accepted from a scenario's own
transcript (`hit = find_verdict_turn(scenario.transcript_path, ALL_VERDICTS)`)
is `INPUT_REQUIRED`:

- Record the verdict and its `scenario_verdict_sources` identity as today
  (evidence/display/aggregation).
- Add the scenario index to `QALoopState.waiting_for_input`.
- Store a follow-up source under `QALoopState.waiting_input_sources[idx]`:
  `{pr_id, loop_id, scenario, session_id, transcript_path, turn_id,
  timestamp, line_index, head, reason}`.
- Discard the index from `state.verified_scenarios` (a PASS from this
  attempt was verified for an older turn and must not be inherited).
- Remove the scenario from the local `pending` set, call
  `_launch_next_queued()` so queued work proceeds (a waiting worker is
  user-bound and does not count against `concurrency_cap`), and keep the
  run alive.

Loop-exit behaviour: `_poll_tmux_verdicts` exits when `pending`, `verifying`
and `_launch_queue` are empty. `waiting_for_input` alone must **not** keep
the collection loop spinning: when no runnable work remains, the run
finalizes (overall `INPUT_REQUIRED`) and the held phase (R2) takes over.
While other work is runnable the run stays `running` (autostart shows
progress, not a wait).

### R2 — Held run: finalize as INPUT_REQUIRED, then keep watching

`_execute_and_finalize` gains an outer loop:

1. `_poll_tmux_verdicts(...)`.
2. Aggregate as today, plus `input_wait_code_changes` (R6) forcing
   `NEEDS_WORK`.
3. Write status + persist verdict evidence.
4. If `state.held` is **false**, run the normal finalize pane and set
   `state.completion_processed = False` / `state._ui_complete_notified =
   False`.
5. `state.held = bool(waiting_for_input) and latest_verdict ==
   INPUT_REQUIRED and not stop_requested`.
6. `state.running = False`; persist the resume snapshot; `notify()`.
7. If not held (or stopped), break.
8. Otherwise `_hold_for_follow_up(...)` blocks, polling the waiting
   scenarios. On a follow-up (or a waiting attempt that needs the live
   loop to act) it returns `True`: reset `held=False`, `running=True`,
   `latest_verdict=""`, `finalize_verdict=None`, `_ui_complete_notified=
   False`, `completion_processed=False`, `notify()`, and loop back to 1.

A held run whose overall is `NEEDS_WORK`/`PASS` does **not** hold: the run
has left QA (review/sign-off takes over) and the remaining waiting
scenarios stay recorded as `INPUT_REQUIRED` evidence for the next run.

The held phase also stops if the PR leaves `qa` status (checked
periodically) so a stale watcher cannot resurrect QA after an out-of-band
status change.

### R3 — Persistence and restart adoption

`qa_resume.json` gains: `waiting_for_input`, `waiting_input_sources`,
`held`, `completion_processed`, `latest_verdict`, `input_wait_code_changes`.
`_write_resume_file` / `build_resume_state` round-trip them.

`build_resume_state` reconciles waiting entries against the restored
scenario identity (same `pr_id`/`loop_id`/`scenario`/`session_id`/
`transcript_path`). A waiting entry whose attempt was superseded (worker
relaunched, different session) is dropped together with its provisional
verdict/verification so the new attempt is polled from scratch. A waiting
entry with no recoverable session is dropped as terminal `INPUT_REQUIRED`
(the verdict stays).

`qa_loop_ui._resume_incomplete_qa`:

- Snapshot with `overall` and **not held** → existing behaviour (process
  completion, clear snapshot).
- Snapshot that is held (or still incomplete) → `build_resume_state`,
  `state._ui_complete_notified = state.completion_processed`, keep the
  snapshot, track the state in `app._qa_loops`, and re-spawn
  `resume_qa_background`. A held run that was never processed
  (`completion_processed=False`) is processed by the normal
  `poll_qa_state` completion path; one already processed is not
  re-noted.

`qa_loop_ui.poll_qa_state`:

- When a completed state is `held`: run `_on_qa_complete` once, keep the
  state in `app._qa_loops`, keep the resume snapshot, and persist
  `completion_processed=True` (new `qa_loop.mark_completion_processed`).
- When the held watcher reopens (`running=True`,
  `_ui_complete_notified=False`), no completion is processed.
- When it finalizes again, `_on_qa_complete` runs for the new verdict.
- Non-held completion keeps today's delete + clear behaviour.

`start_qa`, `fresh_start_qa`, `start_or_stop_qa_loop` and `stop_qa` treat a
`held` state as active: starting/focusing does not spawn a duplicate run;
stopping sets `stop_requested`; a fresh start clears the superseded
snapshot.

### R4 — Follow-up acceptance rules (no stale output)

For each waiting scenario, `_scan_waiting_scenarios`:

- Validates the attempt identity; on mismatch drops the waiting entry and
  its provisional verdict (superseded attempt).
- Reads the worker's own `scenario.transcript_path` only (never another
  pane). A cheap `stat()` (mtime/size) cache on the state avoids re-parsing
  an unchanged transcript.
- Looks for a **newer** `INPUT_REQUIRED` turn than the recorded baseline
  (`line_index` / `timestamp`): if found, refresh the baseline, source
  identity and reason — a repeated `INPUT_REQUIRED` keeps waiting and does
  not finalize.
- Looks for a newer `PASS`/`NEEDS_WORK` turn with the same baseline rule
  (excludes `INPUT_REQUIRED`). On a hit: clear the waiting entry, its
  provisional verdict/source/reason and verification, add the scenario back
  to `pending`, and let the normal acceptance path record it (so PASS
  verification / NEEDS_WORK routing are unchanged).
- If no follow-up exists and the pane/session is gone, drop the waiting
  entry and its provisional verdict and put the scenario back in `pending`
  so the existing retry/relaunch path owns the new attempt. A follow-up
  already present in the transcript is accepted even if the pane has since
  died.

Baseline comparison: `hit.line_index > src["line_index"]` or, when the
transcript was truncated/rotated, `hit.timestamp > src["timestamp"]`.

### R5 — Status/visibility

- `_write_status_file` gains a `waiting_for_input` argument; each waiting
  scenario entry gets `"waiting_for_input": true` and the top-level object
  gets `"waiting_for_input": [indices]`. `qa_status.py` renders a dim
  `(waiting)` suffix while keeping the canonical verdict/colour/counts.
- `state.latest_output` says the scenario is waiting for input (answered in
  its worker pane) while other work continues.
- `autostart_state._derive` needs no new input: while the run is live
  `running=True` → running; once held `running=False` and verdict
  `INPUT_REQUIRED` → `QA INPUT_REQUIRED — answer in QA window`. This
  satisfies "a single waiting scenario must not make the whole run WAITING
  while other runnable work proceeds".

### R6 — Later PASS / NEEDS_WORK / new source changes

- A follow-up `PASS` goes through the normal independent verifier
  (`verified_scenarios` was discarded when the scenario entered waiting) and
  the normal finalize pane.
- A follow-up `NEEDS_WORK` aggregates to `NEEDS_WORK`; `_on_qa_complete`
  transitions to `in_review` and the review loop runs.
- At follow-up acceptance, compare the PR head against the head all
  scenarios started from (`state.planner_head`, falling back to the head
  recorded when the scenario entered waiting). If the head moved, record
  `state.input_wait_code_changes` and force the scenario verdict/overall to
  `NEEDS_WORK` with a reason — a new source head is never promoted on the
  strength of the old run's approval.
- The manual merge gate is untouched: a later PASS still needs sign-off, and
  the existing freshness checks invalidate old approvals when HEAD moves.

### R7 — Prompt reconciliation

- `prompt_gen.generate_qa_child_prompt`'s "Your Verdict Is Final for This
  Run" block: PASS/NEEDS_WORK remain terminal (except loop-initiated
  re-verification); `INPUT_REQUIRED` is explicitly **not** terminal — the
  loop keeps the pane under observation and accepts a later PASS/NEEDS_WORK
  after the user answers, and a repeated INPUT_REQUIRED keeps waiting.
  Cross-run handoff via PR notes still applies to final verdicts.
- `qa_loop._build_concretization_prompt`'s "This Decision Is Final" block
  stays (the concretizer is genuinely one-shot) but gains one sentence
  scoping that rule to the concretizer, distinct from the scenario worker's
  INPUT_REQUIRED continuation.

### R8 — Preserve evidence and user holds

- INPUT_REQUIRED reasons are written to `scenario_verdict_reasons` and
  persisted to `verdict.md`/`scenario.json` at finalize; they are only
  replaced when a genuine follow-up verdict supersedes them.
- Worker panes/containers/captures are never killed by the hold.
- Autostart merge holds and the manual merge gate are not modified.

## 2. Implicit requirements

- `state.scenario_verdicts` remains the canonical verdict map (status,
  notes, captures, aggregation). Waiting is an *overlay*: a verdict present
  in the map is provisional while the index is in `waiting_for_input`.
- The live `pending` set must exclude indices already in
  `waiting_for_input` (polled separately) and indices already carrying a
  verdict (so a restart/held restore never re-consumes a completed
  scenario's stale turn).
- `state.verified_scenarios` must be cleared for a scenario entering
  waiting and for a promoted follow-up.
- Resume identity validation reuses the `scenario_verdict_sources`
  contract: `(pr_id, loop_id, scenario, session_id)`.
- The held thread is the single owner of the run; `resume_owned_elsewhere`
  (owner pid + start time) already prevents a second TUI/CLI process from
  adopting it while the holder is alive.
- No new `claude -p` usage; the hold is passive polling.

## 3. Ambiguities and resolutions

- **Does a live waiting scenario consume a concurrency slot?** No. The
  worker is idle waiting for a human; queued runnable work should proceed
  (scope: "must not make the whole run WAITING while other runnable work
  proceeds"). `_launch_next_queued` is triggered when a scenario enters
  waiting.
- **Should a run with `NEEDS_WORK` from a follow-up keep holding other
  waiting scenarios?** No. The run has returned to review; the remaining
  INPUT_REQUIRED evidence is retained for the next run. Holding would let a
  later PASS promote a head that review has not approved.
- **What if the whole run finalized as INPUT_REQUIRED before this change
  (no snapshot)?** Not recoverable retroactively (no persisted identity);
  the feature persists the hold from the moment a run finalizes with
  waiting scenarios. The #267 flow is covered for runs under this code.
- **Does the refiner's INPUT_REQUIRED exist?** No — the refiner emits
  refine/reject. Its block remains final; only a clarifying sentence is
  added.
- **Repeated INPUT_REQUIRED after the user answers**: keep waiting and
  refresh the baseline/reason; it is not treated as a terminal verdict.

## 4. Edge cases

- Follow-up arrives before the live loop finalizes → collected in the live
  loop (no held round-trip).
- Follow-up arrives between finalize and the held loop → the held loop's
  first scan promotes it and reopens.
- TUI/controller restart while held → `_resume_incomplete_qa` re-spawns the
  held watcher; no duplicate note for an already-processed completion; a
  follow-up that landed during downtime is collected.
- TUI restart while a follow-up has landed but the completion was not
  processed (`completion_processed=False`) → processed on the next poll.
- Worker pane killed while waiting → existing retry/relaunch path owns the
  new attempt (bounded by `_SCENARIO_MAX_RETRIES`); retries exhausted →
  terminal INPUT_REQUIRED.
- Superseded session/transcript on resume → waiting dropped, verdict
  dropped, scenario polled fresh.
- Stop (`z t` / `zz t` stop) while held → hold exits, no relaunch.
- PR leaves `qa` while held → hold exits.
- Verification of a follow-up PASS is mandatory even if the scenario had a
  verified PASS earlier in the run.
- Follow-up PASS with a moved PR head → `NEEDS_WORK`, review required.

## 5. Test plan (unit)

- `waiting` entry on worker INPUT_REQUIRED; run stays live while another
  scenario is pending.
- Follow-up PASS/NW accepted; repeated INPUT_REQUIRED ignored; stale PASS
  before the baseline rejected; stale PASS from a superseded task rejected.
- Superseded session drops waiting + verdict.
- Snapshot round-trip of waiting/held/source fields; `_drop_foreign_verdicts`
  reconciliation.
- `_resume_incomplete_qa`: held snapshot re-spawns (no clear, no duplicate
  completion); held+unprocessed processes once; non-held completed clears.
- `poll_qa_state`: held completion keeps state + snapshot; non-held deletes.
- `_execute_and_finalize`: held after INPUT_REQUIRED-only run; reopen on
  follow-up; new source changes force NEEDS_WORK; no finalize re-run on a
  restored held run.
- Prompt assertions updated: INPUT_REQUIRED continuation described;
  PASS/NEEDS_WORK finality retained.

## 6. Implementation notes (review iteration 1)

Corrections found while reviewing the implementation against R2-R4; all are
covered by tests in `tests/test_qa_input_required.py` /
`tests/test_qa_resume.py`.

- **A follow-up found by the hold must survive to the live loop.** The hold
  reports `scan.follow_ups` and reopens the run, whose first act is to rescan
  the same transcript. The stat cache therefore only records a transcript
  that held *no* follow-up; `_clear_waiting` drops the entry when the live
  loop records it.
- **Reopening must not relaunch already-launched queued scenarios.** A held
  run re-enters `_poll_tmux_verdicts` with the original queue list, and a
  restart adopts a snapshot whose `queued_indices` may name scenarios
  launched before the restart. The launch queue keeps only scenarios with no
  window and no verdict.
- **The hold snapshot is written before the finalize pane.** The finalize
  pane can run for minutes; a restart during it must recover the wait rather
  than process the run as finished. `was_held` (the restored flag) decides
  whether to skip the finalize pane.
- **A superseded run never rewrites its snapshot.** `fresh_start_qa` /
  the `zz t` restart path clear `qa_resume.json`; the winding-down held
  thread must not recreate it or a later scan resurrects the run. The TUI
  sets `state.superseded`, and `_write_resume_file` /
  `mark_completion_processed` skip it. Snapshot writes are serialized by
  `_RESUME_WRITE_LOCK` so the TUI's read-modify-write cannot be clobbered.
- **The hold does not rewrite the snapshot every tick.** It writes only when
  the waiting set changes (repeated INPUT_REQUIRED / dropped attempt), and
  `_execute_and_finalize` writes once when the hold ends.

## 7. Implementation notes (review iteration 2)

- **Reopening publishes `running` before clearing `held`.** `poll_qa_state`
  drops a state whose completion it has already processed once it sees
  `running=False` and `held=False`. Setting `held=False` first left a window
  in which the TUI could observe exactly that and delete the state and the
  resume snapshot for a run that had just reopened — orphaning it. `running`
  is now set first; the TUI skips any state that is running.
- **Only an INPUT_REQUIRED result may be held.** A crashed driver sets
  `latest_verdict="ERROR"`; if `held` stayed set the TUI kept the state in
  `_qa_loops` forever with no thread behind it, so every later `t` reported
  "waiting for input". The TUI held branch now requires
  `latest_verdict == INPUT_REQUIRED`, and both background-thread crash
  handlers clear `held`.
- **Waiting relaunches are capped across hold/reopen cycles.** The live
  loop's `_SCENARIO_MAX_RETRIES` budget is local to one
  `_poll_tmux_verdicts` call, and each hold/reopen starts a new one, so a
  worker that asked for input and then kept dying (user closes the pane,
  container OOM) was relaunched forever — a fresh full scenario run every
  cycle. `QALoopState.wait_relaunch_count` (in-memory) caps the total and
  then records the INPUT_REQUIRED verdict as terminal, matching R4's
  "retries exhausted → terminal INPUT_REQUIRED".
- **The attempt-identity check is shared.** `_attempt_is_current()` is the
  single implementation of the resume identity contract (R3/§2); the
  waiting variant pins the transcript path on top of
  `(pr_id, loop_id, scenario, session_id)`.
- **The `(waiting)` marker fits the status line.** `qa_status._render`
  reserves the suffix width when any row is waiting; otherwise an 80-column
  pane wrapped the row and pushed the footer off screen.

## 8. Implementation notes (review iteration 3)

- **Reopening publishes an in-progress status.** The held finalize leaves
  `overall: INPUT_REQUIRED` in `qa_status.json`, and
  `qa_loop_ui._resume_incomplete_qa` reads that `overall` as "the run
  completed while the TUI was down". A restart during the reopened
  collection window (seconds for a dropped attempt, minutes while a
  follow-up PASS is verified) therefore finalized the stale result, cleared
  the snapshot and dropped the run before the follow-up was collected.
  `_execute_and_finalize` now rewrites the status file with `overall=""`
  (and the snapshot with `held=False`, `latest_verdict=""`) at the reopen,
  status first: a restart between the two writes re-adopts the safe held
  snapshot instead of finalizing.
- **A dead pane no longer discards a PASS behind a repeated
  INPUT_REQUIRED.** `_scan_waiting_scenarios`'s pane-death branch skipped
  the PASS/NEEDS_WORK check whenever a newer INPUT_REQUIRED existed, so
  "ask → answer → ask → answer → PASS, then the pane exits" lost the PASS
  and relaunched the scenario. It now refreshes the baseline past the
  repeated INPUT_REQUIRED and then applies the normal newer-verdict check,
  matching the live-pane branch.

## 9. Implementation notes (review iteration 4)

- **A run reopened mid-poll keeps its state.** `poll_qa_state` reads
  `state.running`, then calls `_on_qa_complete` (which does note I/O), then
  re-reads `state.held`. The held thread can reopen the run (running=True,
  held=False) in that window; the TUI would then fall through to the
  finished-run path, clear the reopened run's resume snapshot and mark the
  completion notified — so the follow-up verdict it was reopened to collect
  would never be processed. `poll_qa_state` now re-checks `state.running`
  after `_on_qa_complete` and skips the state when the run has reopened.
- **The per-scenario head is only a fallback baseline.** `_enter_waiting`
  resolved the current PR head on every worker INPUT_REQUIRED even though
  `_poll_waiting` prefers `state.planner_head` (set for every run that
  launches scenarios). That lookup queries the upstream with a 15s timeout,
  so it is now skipped when a planner head exists, keeping the verdict
  collection loop off the network in the normal path.
- **Head resolution is best-effort as documented.** `_current_pr_head`
  wrapped only the upstream query; the local `_rev_parse` fallback could
  raise (a workdir deleted mid-run) and crash the collection thread. Both
  paths now return `None` on failure.
- **Known trade-off (unchanged): follow-ups are accepted from the
  transcript without an idle_prompt gate.** The hold and the live loop read
  the scenario's own transcript on a stat-change poll, so a standalone
  verdict line written mid-turn could be accepted before the turn ends.
  The baseline rule (newer than the INPUT_REQUIRED turn) keeps stale output
  out, and the worker prompt requires the verdict on the final line; a
  hook gate was rejected because a missed `idle_prompt` would strand the
  scenario in an unbounded wait, which is the failure this PR exists to
  remove.
- **Known trade-off (unchanged): a follow-up that lands between the hold's
  scan and the reopened live loop's scan.** If the worker appends a
  repeated INPUT_REQUIRED in that one-interval window, the live loop
  refreshes the baseline instead of accepting the earlier follow-up and the
  run re-finalizes as INPUT_REQUIRED. The re-finalize re-runs the finalize
  pane for the same result (idempotent: it re-verifies pushes and
  fast-forwards) and records a second, textually identical QA note — QA
  notes are appended per completed run (`test_three_qa_runs_three_notes`),
  so identical text is *not* de-duplicated; the extra note is noise, not a
  lost result.

## 10. Implementation notes (review iteration 5)

- **The two `_scan_waiting_scenarios` branches share one acceptance path.**
  The live-pane and pane-death branches had drifted apart once already
  (iteration 3 fixed a lost PASS behind a repeated INPUT_REQUIRED), so the
  repeated-INPUT_REQUIRED refresh, the PASS/NEEDS_WORK check and the
  "never cache an unconsumed follow-up" rule now run once for both. The
  only branch-specific parts remain: the stat cache applies to a live pane
  only (a dead pane must be re-checked every tick), a live pane defers the
  PASS/NEEDS_WORK check to the next tick after a repeated INPUT_REQUIRED,
  and a dead pane with no follow-up goes through the relaunch cap.
- **Persistence test covers the whole waiting contract.** The resume
  round-trip test now also asserts the per-scenario `head` fallback
  baseline and `input_wait_code_changes`, which force NEEDS_WORK after a
  resumed run.
- **Spec correction.** Iteration 4's note claimed the TUI de-duplicates an
  identical QA note; it does not (see the trade-off above).

## 11. Implementation notes (review iteration 6)

- **A hold can reopen the run between the TUI's two checks.** `poll_qa_state`
  reads `state.running` (False, pre-reopen), then the held thread publishes
  `running=True` and only afterwards clears `held`; the TUI's `held` read can
  therefore see the already-cleared False and fall through to the finished
  path, clearing the reopened run's resume snapshot.  `running` is re-checked
  after the held branch, so every ordering of the reopen transition keeps the
  run and its snapshot.
- **A completed snapshot whose result was already noted is not re-noted.**
  `_resume_incomplete_qa`'s completed-run branch now honours
  `completion_processed` from the snapshot.  A held run that ends its hold
  without a follow-up (stop, PR left qa, last attempt dropped terminal)
  leaves a snapshot with `held=False` and the already-noted result; adopting
  it must clear the snapshot, not record a second QA note / lifecycle
  transition.
- **Test coverage.** `test_restored_held_run_finalizes_a_collected_follow_up`
  pins the `_clear_waiting` → `held=False` coupling that makes a restored
  held run re-finalize a collected follow-up (a follow-up PASS must not skip
  the finalize pane's push/fast-forward verification);
  `test_resume_completed_snapshot_already_processed_is_not_renoted` covers
  the `completion_processed` guard.
