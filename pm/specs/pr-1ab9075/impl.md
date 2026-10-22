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
running same-name container still mounting the deleted clone); no worker
ran in them, so no evidence is lost.

R6. **Surface the runtime cause.**  Add
`container.classify_runtime_error(text) -> str | None` (pure) and
`container.diagnose_exec_failure(name) -> str` (short-timeout
`<runtime> inspect` + `<runtime> exec <name> true`, stderr classified).
Classifier recognises:
  - keyring/EDQUOT ("unable to create session key", "disk quota exceeded",
    "EDQUOT") → "container keyring quota exhausted (… ) — reap orphaned
    containers (pr-1139060) or raise kernel.keys.maxkeys/maxbytes",
  - PID exhaustion ("Cannot fork", "fork: retry", "Resource temporarily
    unavailable", "pids limit") → "container process (PID) limit exhausted —
    restart the container `<runtime> restart <name>` (files are kept)",
  - container not running / missing.
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
`_POLL_INTERVAL`), never after a backoff.  Background launch threads check
`state.stop_requested` before creating a window/pane (launchers already
check at prep start; add the check before the worker split and in
`_relaunch_scenario_window`), so a stopped run does not spawn orphan
workers.

R8. **Restart preserves results and retry state.**  `QALoopState` gains
`launch_retries: dict[int, dict]` (attempts, kind, cause, retry_at,
prior session ids).  `_write_resume_file` persists it and
`build_resume_state` restores it.  Verdicts / reasons / verified set are
already persisted.  On resume a scenario with a retry record continues from
its recorded attempt count and `retry_at` (immediately if past due).  A
launch that was in flight when the controller died is re-attempted (counts
as an attempt).

R9. **Preserve evidence.**  Retries never delete a started worker's clone or
container (`exec`/`exit` use relaunch).  Each relaunch re-points the
transcript symlink to a new session; the previous session id is recorded in
the retry record (`sessions`) so the earlier native transcript can still be
found.  Completed verdicts are never touched by retry logic.

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
- Thread safety: launch threads mutate only their own scenario object and
  report outcome through a lock-protected results dict; the poll thread
  applies outcomes (pending/verdict/retry updates, status writes).
- A successful start clears the stale launch-failure `verdict_reason` so the
  eventual transcript verdict isn't shown with an old launch error.
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
  relaunch (existing `test_stop_during_backoff_does_not_relaunch` intent).
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
  cause is "worker pane exited before Claude started".
- E8. Relaunch in container mode for a scenario whose `container_name` is
  None (create failure) goes through the full launcher, never
  `_relaunch_scenario_window`.
