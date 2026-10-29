# pr-1ab9075 — one failed QA worker blocks verdict collection during retry backoff

## Background (current code)

`pm_core/qa_loop.py::_poll_tmux_verdicts` is the single orchestration loop
for QA scenario workers (shared by `run_qa_sync` and `resume_qa_sync` via
`_execute_and_finalize`).  When a scenario's pane is gone it does, inline:

```python
backoff = _SCENARIO_RETRY_BASE * (2 ** retries)   # 5, 10, … 2560 s
time.sleep(backoff)                               # blocks EVERY scenario
... _relaunch_scenario_window(...)
grace_start = time.monotonic()                    # resets grace for ALL scenarios
```

with `_SCENARIO_MAX_RETRIES = 10`.  During that sleep no verdict is collected,
no verification result is processed, no queued scenario is launched and a
stop request is only observed after the sleep.  The relaunch also resets the
*global* `grace_start`, delaying verdict polling for every healthy scenario.
A relaunch that only creates a tmux window counts as success, so a worker
whose `podman exec` dies instantly (PID/keyring exhaustion) burns retries
without any recorded cause, and the final reason is the generic
"worker exited before any verdict; no recovery after 10 relaunches".

Scenarios that never got a window (workdir clone, `create_qa_container`, or
`new_window_get_pane` failure — e.g. #239 key EDQUOT) are marked
INPUT_REQUIRED immediately at loop start (or on dequeue) and are never
retried.  `_launch_scenarios_in_containers._prepare_scenario` logs the
container-create exception but records no reason.

Queued scenarios are launched synchronously from the poll loop through
`_launch_next_queued`, which temporarily swaps `state.scenarios` and blocks
until the scenario's concretizer finishes (minutes).

## 1. Requirements

R1. **Per-scenario, nonblocking retry deadlines.**  Remove every
`time.sleep(backoff)` from `_poll_tmux_verdicts`.  A dead/failed scenario
gets a per-scenario retry record (attempts used, failure kind, cause,
wall-clock `retry_at`).  Each poll tick only checks `time.time() >= retry_at`;
until then the scenario is skipped and the loop continues to collect
verdicts for other scenarios, process verification results, launch queued
scenarios and observe `state.stop_requested`.

R2. **Relaunch work runs off the poll thread.**  The relaunch (exec/exit
path: `_relaunch_scenario_window`) and the full re-launch (creation path:
`_launch_scenarios_in_tmux` / `_launch_scenarios_in_containers` for one
scenario) run in a per-scenario background thread; the loop collects the
outcome on a later tick (same pattern as `_run_verification` /
`verification_results`).  At most one launch operation per scenario is in
flight.  Queued-scenario dequeues use the same background mechanism so a
slow concretizer no longer stalls the loop either.  To make this safe the
launchers take an explicit `scenarios` list instead of the
`state.scenarios` swap, and can skip their own status-file write.

  This also closes the follow-up recorded from the pr-592e4bd review
  (2026-10-22): `_launch_next_queued` no longer runs the queued scenario
  refiner (`_concretize_scenario` / `poll_for_verdict`) synchronously
  inside `_poll_tmux_verdicts`, so a long or route-stalled refiner (e.g.
  one held by `_RouteStallWatch` during a mid-run route outage) cannot
  block verdict collection, retries, verification or stop for its
  duration.  Covered by `test_queued_launch_runs_off_the_poll_thread`.

R3. **Per-scenario verdict grace.**  Replace the global `grace_start` with a
per-scenario `grace_until`, set at loop start for pre-launched scenarios and
whenever that scenario's worker pane is (re)created.  One scenario's relaunch
no longer delays verdict collection for the others.

R4. **Bounded retries and delays.**  `_SCENARIO_MAX_RETRIES = 6`,
`_SCENARIO_RETRY_BASE = 5`, new `_SCENARIO_RETRY_MAX_DELAY = 300`:
delay(n) = min(5·2ⁿ, 300) → 5, 10, 20, 40, 80, 160 s (≈5 min total).  The
budget is per scenario per run and is not reset by a successful start, so a
crash-looping worker is still bounded.

R5. **Distinguish "window created" from "worker started".**  A worker is
*started* once Claude has materialised its transcript (the target of the
`transcript-s<N>.jsonl` symlink exists) or a hook event exists for its
session id.  Failure kinds, recorded separately:
  - `create` — no worker pane was ever created this attempt (workdir clone,
    container create, window/split failure), including no-pane failures of
    the initial batch and of dequeued launches.
  - `exec` — a worker pane was created but died before the worker started
    (e.g. `podman exec` → "Cannot fork", keyring EDQUOT).
  - `exit` — the worker started and its pane later died without a verdict.
`create` failures retry through the full launcher (fresh clone/container
create/concretize/split); `exec`/`exit` failures retry through
`_relaunch_scenario_window` (keeps the clone and container, so worker
commits/evidence survive).  Before a `create` retry the previous attempt's
leftover concretizer window and container are removed (the launcher
re-clones the scenario dir, and `create_container` would otherwise reuse a
running same-name container still mounting the deleted clone).  Both are
removed under their *recorded* name and under the deterministic one the
launcher computes (`_scenario_window_name(pr_data, index)` /
`qa_container_name(pr_id, loop_id, index, session_tag)`): an attempt that
died mid-launch may never have published `window_name`, and a create
attempt that died after `container run` succeeded never publishes
`container_name` at all — exactly the case the teardown exists for.  A
missed window would leave two windows with the same name, and a reused
container would keep serving the deleted clone.  No worker ran in them, so
no evidence is lost.

R6. **Surface the runtime cause.**  Add
`container.classify_runtime_error(text, name=None) -> str | None` (the
optional *name* only feeds the `<runtime> restart <name>` remediation),
`container.runtime_error_summary(text, name=None) -> str` (classified cause,
else the last two non-empty stderr lines) and
`container.launch_error_summary(exc, name=None) -> str` (same, preferring a
`CalledProcessError`'s stderr/output) alongside
`container.diagnose_exec_failure(name) -> str` (short-timeout
`<runtime> inspect` + `<runtime> exec <name> true`, stderr classified).
Classifier recognises:
  - keyring/EDQUOT ("session key" — runc's "unable to create session key:
    disk quota exceeded" —, "keyring" — crun's "create keyring `…`: Disk
    quota exceeded" —, "EDQUOT") → "container keyring quota exhausted (… ) —
    reap orphaned containers (pr-1139060) or raise
    kernel.keys.maxkeys/maxbytes".  A bare "disk quota exceeded" is a
    filesystem quota and stays unclassified (stderr tail passed through),
  - PID exhaustion ("Cannot fork", "fork: retry", "fork: Resource temporarily
    unavailable", "pids limit", "pids.max"; a bare EAGAIN is too generic) →
    "container process (PID) limit exhausted — restart the container
    `<runtime> restart <name>` (files are kept)",
  - container not running / missing (`diagnose_exec_failure` names the
    container's state or "container <name> not found"; the text classifier
    itself stays quiet, since a "no such container" line is not a resource
    cause and its stderr tail is passed through unchanged).
Unclassified output is passed through (stderr tail).  Container-create
failures in `_prepare_scenario` record `container create failed: <cause>`
(classified `CalledProcessError.stderr` / `ContainerError` text) in
`scenario_verdict_reasons`.  In container mode every dead worker pane
(`exec` *and* `exit` — an exhausted container also kills running workers,
as in #236) is diagnosed before its retry is scheduled; the diagnosis runs
in the scenario's background thread (never on the poll thread).
While retrying, `qa_status.json` shows the scenario as
`(launch-retry:<n>/<max>)` with the cause as `verdict_reason`;
`qa_status.py` renders it as "launch retry n/max" and does not count it as
complete.  When retries are exhausted the scenario gets INPUT_REQUIRED with
an explicit reason
`<kind label> (runtime failure, not an agent verdict); gave up after <n>
relaunch attempt(s): <cause>` (kind labels: "worker could not be created",
"worker exited before Claude started", "worker exited before any verdict" —
"launch failed" would misdescribe an `exit`); the overall verdict therefore
stays INPUT_REQUIRED (not PASS).

R7. **Cancellation.**  A stop request is observed on the next tick (≤
`_POLL_INTERVAL`), never after a backoff.  The loop itself does not start a
relaunch once `state.stop_requested` is set — a retry that comes due in the
same tick a stop lands is skipped and the record stays `waiting` (still due),
so a resume retries it immediately instead of the attempt being spent on a
launch that would only abort.  Background launch threads also check
`state.stop_requested` before creating a window/pane (launchers already
check at prep start; add the check before the worker split and in
`_relaunch_scenario_window`), so a stopped run does not spawn orphan
workers.

R8. **Restart preserves results and retry state.**  `QALoopState` gains
`launch_retries: dict[int, dict]` (attempts, kind, cause, retry_at, prior
session ids, and a `state` of `waiting` / `launching` / `running` /
`failed` that drives the status display and the "an interrupted launch
spends an attempt" rule).  `_write_resume_file` persists it and
`build_resume_state` restores it.  Verdicts / reasons / verified set are
already persisted.  On resume a scenario with a retry record continues from
its recorded attempt count and `retry_at` (immediately if past due).  A
launch that was in flight when the controller died is re-attempted (counts
as an attempt).

R9. **Preserve evidence.**  Retries never delete a started worker's clone or
container (`exec`/`exit` use relaunch).  Retry bookkeeping also never
replaces a completed verdict: `_record_failure` settles (and does not
record a failure for) a scenario that already has a verdict, so a verdict
that lands while a failure is being classified — including when the retry
budget is already spent — is preserved rather than overwritten with
INPUT_REQUIRED.  Each relaunch re-points the
transcript symlink to a new session; the previous session id is recorded in
the retry record (`sessions`) so the earlier native transcript can still be
found.  Completed verdicts are never touched by retry logic.  A relaunch
first kills any leftover window with the scenario's name (a lingering
concretizer pane can keep the old window alive), so a relaunch never leaves
two same-named windows for name-based pane lookup / dashboard navigation to
choose between.

R9a. **Never resurrect a deliberately cleared verdict.**  The dead-pane
collection (a worker that emitted its verdict and then died before the poll
loop read it) is skipped for a scenario whose verdict was cleared on
purpose, because that verdict is still in the dead worker's transcript:
cleared for a verification re-evaluation (`verification_failures`) or
cleared so a lost `INPUT_REQUIRED` wait is handed back to the retry path
(`_scan_waiting_scenarios` → `scan.dropped`).  Without the second guard a
worker that asked for input and then lost its pane would be settled
`INPUT_REQUIRED` from its own stale turn instead of being relaunched for
the user to answer, turning a recoverable wait into a terminal result.  The
exclusion lasts until a new worker attempt starts (the relaunched session's
transcript may be collected normally).

The wait-drop guard lives on the state (`QALoopState.dropped_wait_verdicts`)
and in the resume snapshot, not in a loop-local set: a held run does its
scanning in `_hold_for_follow_up`, which hands the dropped scenario to a
*fresh* `_poll_tmux_verdicts` invocation, and the controller can restart in
between — a loop-local guard is empty in both cases and the cleared verdict
is collected straight back.  It is set where `_scan_waiting_scenarios`
records a drop and cleared when a background launch reports that a new
worker started (and when the wait is settled terminally, `drop_verdict=False`).
`verification_failures` stays in-memory: after a restart the stale PASS can
be re-collected and re-verified, which re-runs the verifier (bounded by
`qa-verify-retries`, converging to NEEDS_WORK) rather than turning a
recoverable wait into a terminal result.

The guard covers pane resolution, not only the dead-pane collection.  A
worker that exits on its own leaves the scenario window alive: the
concretizer pane stays in it, and the worker-pane fallback resolves to the
window's *first* pane — so the reopened loop would poll that sibling pane
with the dead attempt's transcript and collect the cleared verdict after the
verdict grace (observed live: a `hold`-limited worker died, the hold scan
dropped the wait, and 30 s later the reopened loop re-recorded
`INPUT_REQUIRED` with no worker left to answer, never entering the retry
path).  While a dropped wait is in recovery and no worker pane is recorded,
the scenario therefore never adopts a sibling pane as its worker; it records
the exit launch failure directly and lets the retry path relaunch it.

R10. **No verdict-criteria or verification change.**  Verdict extraction,
idle-hook gating, verification, and aggregation in `_execute_and_finalize`
are unchanged apart from per-scenario grace.

## 2. Implicit requirements

- A scenario that is waiting for a retry or has a launch in flight stays in
  `pending` so the loop doesn't exit and aggregation doesn't run early; it
  keeps its concurrency slot (resource pressure is the common cause, so a
  failing scenario must not let extra containers start in its place).
- Concurrency accounting: `active = pending + verifying + in-flight
  dequeues`; a dequeued scenario is in `pending` from the moment its launch
  thread starts.
- Thread safety: launch threads mutate their own scenario object, report the
  outcome through a lock-protected results dict, and (as the launcher
  already did for refiner rejections / trust blocks) may record that
  scenario's verdict/reason; every other update — pending/retry state,
  status and resume writes — happens on the poll thread, which applies the
  outcomes.  The resume writer snapshots the verdict/reason dicts before
  serialising so a concurrent insert cannot break the write.
- A (re)created worker pane starts with fresh per-session polling state:
  the hook timestamp, trust watch and verdict-reminder timer of the dead
  session are cleared, so the new worker is not gated by the old session's
  grace or reminder interval.
- Failure classification is per attempt: a `create` retry clears the
  attempt's window/container/pane/session/transcript pointer before it
  re-launches, and the `create` check is skipped when the previous attempt's
  worker actually started (transcript materialised).  A worker that ran is
  therefore always an `exec`/`exit` failure and is relaunched in place —
  never re-cloned, which would delete its commits (R9).  Covered by
  `test_started_worker_without_session_keeps_clone`.
- A successful start clears the stale launch-failure `verdict_reason` so the
  eventual transcript verdict isn't shown with an old launch error.
- A `create` retry re-runs `_prepare_scenario`, which clears
  `instruction_path` once the concretizer has inlined the steps.  The
  original pm-relative reference is therefore kept in a new
  `QAScenario.instruction_source` (persisted in the resume snapshot) so a
  retried or resumed launch still reads the instruction content and
  reinstalls the file; without it the retried concretizer would silently
  lose the instruction steps.
- A launch/diagnosis outcome that lands in the same tick as a stop request
  is still applied: dropping it would leave the retry record `launching`
  with no operation in flight, and the per-scenario loop would then
  re-classify the scenario as a fresh failure and overwrite the real
  cause.  Nothing in that block starts new work, and the loop exits on the
  next condition check.
- Concretizer rejections / trust-blocked concretizers record a verdict and
  must NOT be retried (existing "no session id + verdict present" branch).
- Status/resume snapshot are refreshed when a background launch publishes a
  window name, so the dashboard can navigate to an in-flight concretizer
  (the resume snapshot is rewritten every tick; the status file is rewritten
  whenever any scenario's window name differs from the last write).
- Existing tests that drive the old sleep-based retry with
  `time.monotonic` side-effect lists are rewritten against the new
  deadline model.

## 3. Ambiguities (resolved)

A1. *New verdict state vs INPUT_REQUIRED.*  pr-7ab0a99 allows either an
explicit error state or "INPUT_REQUIRED with reason 'container exec failed:
…'".  A new verdict would change verdict criteria and ripple through
auto-sequence/TUI routing (forbidden).  **Resolution:** keep INPUT_REQUIRED
as the terminal verdict, with an explicit "<kind label> (runtime failure,
not an agent verdict) … <cause>" reason (see R6); during retries show a non-verdict
`(launch-retry:n/max)` state.

A2. *Container health/restart.*  The incident was cleared by restarting the
container.  pr-1139060 owns container health and lifecycle.
**Resolution:** this PR diagnoses and names the remediation (including the
exact restart command) but does not restart/recreate containers itself.
Retries pick up automatically once a human/pr-1139060 recovers the
container within the retry window.

A3. *Should the budget reset after a successful start?*  **Resolution:** no
— one bounded budget per scenario per run (old code behaved the same).

A4. *Retry for deterministic creation failures* (e.g. planner-head mismatch
in `create_scenario_workdir`).  **Resolution:** retried within the same
bounded budget; cheap and the final reason carries the original error.

A5. *pr-7ab0a99 scope.*  This PR delivers its launch-error reason +
remediation for create/exec failures and the "stuck running → bounded
error" item for dead panes.  Not delivered here: persisting every
scenario's transcript to the host captures dir.  A note on pr-7ab0a99
records what landed and what remains; it is not claimed closed.

A6. *pr-3201ea8 scope.*  Initial-batch launch (before the first
`qa_resume.json`) and adoption of partially-launched runs stay with
pr-3201ea8.  This PR only makes retry state survive restarts once the poll
loop owns the run.

## 4. Edge cases

- E1. Stop while a scenario is in backoff → loop exits on the next tick, no
  relaunch (existing `test_stop_during_backoff_does_not_relaunch` intent,
  now `test_stop_during_backoff_returns_on_next_tick`).
- E1a. Stop that lands in the same tick a retry comes due → the waiting
  branch skips it (no thread, no spent attempt), the record stays `waiting`
  with its due `retry_at` (`test_stop_in_the_tick_a_retry_comes_due_does_not_relaunch`).
- E2. Stop while a background launch thread is mid-concretize → the thread
  bails before splitting the worker pane.
- E3. Resume with a pane id from the old controller that is dead and a
  transcript that exists → classified `exit`; no transcript → `exec`.
- E4. Retry record exists but scenario already has a verdict (verdict landed
  before restart) → record ignored, verdict preserved.
- E5. Queued scenario whose dequeue launch fails with no pane → `create`
  retry instead of immediate INPUT_REQUIRED.
- E6. Verification follow-up path that finds the pane gone keeps its
  existing INPUT_REQUIRED behaviour (verification-specific, out of scope).
- E7. Host (non-container) mode: `exec` diagnosis has no container to probe;
  cause is "pane died at startup; no runtime cause found" (fallback causes
  complement the kind label rather than repeating it).
- E8. Relaunch in container mode for a scenario whose `container_name` is
  None (create failure) goes through the full launcher, never
  `_relaunch_scenario_window`.
- E9. A waiting (`INPUT_REQUIRED`) scenario whose worker pane died with no
  follow-up is dropped back to the retry path, not settled from the dead
  worker's transcript: the cleared verdict is excluded from the dead-pane
  collection until a new attempt starts
  (`test_dropped_waiting_attempt_is_relaunched_not_recollected`,
  `test_recovered_wait_collects_a_verdict_from_its_new_worker`).
- E9a. The same holds when the drop happens in the hold loop
  (`_hold_for_follow_up`) and the run reopens in a fresh
  `_poll_tmux_verdicts` call, and when the controller restarts before the
  retry runs: the guard is persisted
  (`test_hold_dropped_wait_is_relaunched_not_recollected`,
  `test_dropped_wait_guard_survives_a_restart`).
- E9b. The drop is still recovered when the window survives the worker: the
  concretizer pane keeps the window alive, the worker-pane fallback would
  resolve to it, and the reopened loop would re-read the cleared
  `INPUT_REQUIRED` instead of relaunching
  (`test_dropped_wait_is_relaunched_when_window_keeps_a_sibling_pane`).
