# pr-3201ea8 — Preserve and resume QA ownership during worker startup

## Root cause (grounded)

`run_qa_sync` (pm_core/qa_loop.py) writes the first `qa_resume.json` only in
`_execute_and_finalize`, i.e. after `_launch_scenarios_in_tmux` /
`_launch_scenarios_in_containers` have **joined every prepare and
concretize/launch thread**.  A scenario refiner (concretizer) can take
minutes, so while one scenario's worker is already running another can still
be refining and no snapshot exists.  `qa_loop_ui._resume_incomplete_qa` (and
`auto_start._adopt_live_qa`, which calls it) discovers runs *only* through
`~/.pm/workdirs/qa/*/qa_resume.json`, so a TUI restart in that window:

* finds nothing to adopt, then `auto_start._auto_start_qa_loops` sees no
  `app._qa_loops[pr]` and calls `start_qa` → a **second run** for the PR
  (#234, 2026-10-22: the original workers kept pushing while replacement
  review/planning used an older head);
* without auto-start (the original W3.4 report, run 1b on pr-983dd4a, worker
  s2 launched 14:37:30, kill -9 at 14:38:00) nothing ever logs "Resuming
  incomplete QA from disk" because no snapshot exists — not a HOME/qa_root
  mismatch and not the `status == "qa"` gate (W3.5, which had reached the
  poll loop, resumed within 1 s through the very same scan).  This is the
  answer to the report's "check whether qa_resume.json existed" question: it
  could not have, because s2 launched while another scenario was still in
  the launcher's join.

Related gaps found while grounding:

* Queued (dequeued) launches in `_poll_tmux_verdicts._launch_next_queued`
  swap `state.scenarios = [scenario]` while the launcher runs; a snapshot
  written meanwhile would drop every other scenario.  The dequeued launch is
  only snapshotted on the next poll iteration (pr-8020495 adds an immediate
  snapshot on its branch; not on master).
* `_relaunch_scenario_window` changes `pane_id`/`session_id`/`transcript_path`
  but the snapshot is refreshed only on the next poll; a restart in between
  resumes with the dead pane, relaunches again → duplicate worker in the same
  clone.
* `_resume_incomplete_qa` treats `qa_status.json["overall"]` as "complete",
  but `_execute_and_finalize` writes `overall` **before** the finalizer pane
  runs.  A restart during finalize advances the lifecycle
  (`_on_qa_complete`) without the finalizer having reconciled worker pushes.
* On resume `_poll_tmux_verdicts` puts every scenario with a `window_name` in
  `pending`, including ones whose verdict is already final (e.g. retries
  exhausted → INPUT_REQUIRED with a dead pane), which are then relaunched.
* Several snapshots for one PR (an older interrupted run plus a newer one)
  are adopted in glob order; a deliberately stopped run (`zz t` stop,
  `stop_qa`, `z t` superseding) is indistinguishable from an interrupted one.

## 1. Requirements

R1. **Ownership from the start.**  `run_qa_sync` writes `qa_resume.json` as
soon as the QA workdir exists (before any planner / scenario-0 window is
created) and keeps it current through every phase.  The snapshot records a
run-level `phase`: `planning` → `planned` → `launching` → `executing` →
`finalizing` → `done`, plus `started_at` and `cancelled`.

R2. **Per-scenario phase (refiner vs worker identity).**  Each `QAScenario`
carries `launch_phase`: `queued` (not started), `preparing` (clone /
container creation, no pane yet), `refining` (concretizer session id
recorded — written *before* its window is created — plus its pane id),
`launching` (worker session id + transcript recorded — written *before* the
pane split), `running` (worker pane recorded), `settled` (no worker will run:
refiner rejection, workdir/container failure, trust block).  The refiner's
identity (`concretize_session_id`, `concretize_pane_id`, `concretize_cwd`)
is separate from the worker's (`session_id`, `pane_id`, `transcript_path`).
The original instruction reference (`instruction_src`) is kept so a refiner
that never started can be launched after a restart.  Each transition is
checkpointed (snapshot + status file) by the thread that makes it.

R3. **Adopt partially launched runs.**  `resume_qa_sync` dispatches on the
snapshot phase and re-enters the shared pipeline:
* `planning`: adopt the live planner pane (session id recorded before the
  planner window was created) and keep polling its transcript; a plan
  already emitted during the downtime is read from the transcript.  If the
  planner pane is gone and its transcript holds no complete plan, the run
  ends INPUT_REQUIRED ("planner interrupted") — no new planner, no PASS.
* `planned`: plan already accepted; run the post-plan steps (spec gate,
  planner hand-off, mocks) once, then launch.
* `launching`/`executing`: drive every scenario from its recorded phase:
  `queued` → normal (cap-respecting) launch; `preparing` → prepare again
  (no agent has touched the clone; a container created for it is reused);
  `refining` → adopt the live refiner (or read its finished result from the
  transcript), start it only if it was never started, fall back to the
  planner's draft steps if it died without a result (same as the original
  path); `launching` → adopt the worker pane found by its `--session-id`,
  launch it only if no such pane exists; `running` → poll as today.
* `finalizing`: adopt the finalizer pane by its recorded session id, read
  its verdict from the transcript if it finished during the downtime, start
  a finalizer only if none was started (or it died without a verdict).
* `done`: completion is processed (`_on_qa_complete`) and the snapshot
  cleared — only then.

R4. **Launch only missing work, once.**  No adopted/resumed run launches a
second refiner, worker or finalizer for a scenario whose recorded one is
alive or finished.  Scenarios with final verdicts are not re-polled into
relaunch.  Relaunch (`_relaunch_scenario_window`) and dequeued launches
checkpoint the new identity immediately (write-ahead before the pane
exists, then again with the pane id).

R5. **No second run for an adoptable PR.**  `qa_loop_ui.start_qa` (used by
auto-start, review→qa, sign-off REQA) adopts an incomplete, non-cancelled
snapshot for a PR already in `qa` instead of starting a new run, and refuses
(with a log line) while a different live process owns it.  `fresh_start_qa`
(`z t`) and `start_or_stop_qa_loop` (`zz t`) still start a deliberate new
run; stop paths mark the old snapshot `cancelled` synchronously.

R6. **Distinguish interrupted vs cancelled.**  `cancelled` is persisted from
`state.stop_requested` on every checkpoint and set directly by the TUI stop
paths.  Per PR only the newest snapshot (by `started_at`, falling back to
mtime) is a candidate; a cancelled newest snapshot is never adopted; older
snapshots are never adopted.

R7. **Results and evidence preserved.**  Verdicts, reasons, verified set,
planner head / planner code changes, transcripts, captures, clones and
commits survive.  Resume never re-clones a scenario that reached `refining`,
never removes containers or windows of the adopted run, and the finalizer is
still the step that reconciles worker pushes.  Missing verdicts never become
PASS (existing aggregation keeps unverdicted → INPUT_REQUIRED); spec gate and
manual merge gates are untouched.

R8. **Regression coverage** (tests/test_qa_resume.py, new
tests/test_qa_startup_resume.py):
* kill mid-startup with s1 executing, s2 refining, s3 queued (cap 2): the
  snapshot exists, a resume of it adopts s1's worker and s2's refiner,
  launches s3 once and s2's worker once, never re-creates s1/s2 refiners or
  workers, collects all verdicts and runs the finalizer once;
* restart right after a worker launch / relaunch / dequeue (before the next
  poll): snapshot already holds the new pane/session; resume adopts it;
* restart during finalize: lifecycle is not advanced; finalizer adopted;
* TUI: `start_qa` adopts instead of starting; cancelled / older snapshots
  are not adopted; `done` is processed once.
Deterministic harness: patched tmux / launcher boundaries with bounded
failures (no sleeps beyond test-patched intervals).  Live evidence: fake
Claude in a real pm tmux session, TUI kill -9 + `pm session` respawn, pre-
and post-fix captures under `$CAP/impl/{pre,post}-fix/`.

## 2. Implicit requirements

* Snapshot writes come from several threads (launcher threads, poll loop,
  TUI stop path): `_write_resume_file` and `_write_status_file` must be
  serialized (module lock) and tolerate dicts mutating during serialization
  (copy before iterating).  Temp files must not collide.
* Launchers take the scenario list to launch explicitly instead of swapping
  `state.scenarios`, so every snapshot always lists the whole plan.
* `use_containers`, `concurrency_cap`, run phase, planner identity,
  `pre_plan_head`, `scenario_start`, finalizer identity live on
  `QALoopState` so any thread can checkpoint.
* Old snapshots (no `phase` / `launch_phase`) keep today's semantics:
  `queued_indices` → `queued`, `window_name` → `running`, `overall` in
  qa_status.json → completed.
* A run that returns early (spec gate, trust-blocked planner, handoff error,
  merged/closed abort, ERROR) checkpoints `done` with its verdict so a later
  scan does not try to adopt a finished run.
* `pm qa run` (cli/qa.py) clears its snapshot after the synchronous run, like
  the `qa-run-bg` driver, so the TUI does not "recover" it.
* Pane adoption looks a pane up by the `--session-id <uuid>` in its start
  command (`tmux.pane_start_command` + `claude_launcher._PANE_SESSION_RE`),
  works for host, container (`docker exec … claude --session-id`) and fake
  Claude panes.
* Refiner adoption must not rely only on *new* idle events: a refiner that
  finished during the downtime already emitted its idle hook, so the
  transcript is checked first, then polled.

## 3. Ambiguities (resolved)

* **Scope of "startup".**  Covers planning through finalize; the key
  defect is refinement/launch.  Planning adoption reuses the existing
  planner poll; a dead planner without a plan becomes INPUT_REQUIRED rather
  than a re-plan (re-planning would be a new run; the user can `z t`).
* **Dead refiner on resume.**  Same outcome as without a restart: launch the
  worker with the planner's draft steps (the existing `(None, None)`
  fallback).  A refiner that was recorded but never got a window is started.
* **Self-driving (`zz t`) state across restarts** stays unpersisted (the
  documented limitation in `_resume_incomplete_qa`).
* **Retry counters / backoff state** are not persisted — owned by
  pr-1ab9075.  Stop-time worker/finalizer suppression and the "stopped run
  records PASS" bug are pr-f8acf21; this PR only persists `cancelled` and
  refuses to adopt it.  Branch synchronization before planning is
  pr-62fdd54.  pr-8020495's snapshot-after-dequeue/relaunch is subsumed by
  the checkpoints here (its branch will need a trivial merge).
* **Verifier panes** launched just before a restart may be launched again
  (read-only reviewers, not writers); unchanged.

## 4. Edge cases

* Restart between `refining` checkpoint and window creation: no pane, no
  transcript → refiner started once on resume.
* Restart between worker build (transcript symlink + session id written)
  and split: no pane with that session id → worker launched once (new
  session id; the old symlink pointed at a session that never ran).
* Concretizer window killed by a user while the worker pane survives:
  worker adopted by session id from the window; refiner not needed.
* Containers: `create_container` reuses a running container of the same
  name, so a `preparing` scenario re-prepared on resume reuses it; a clone
  for a `preparing` scenario has had no agent, so re-cloning is safe — but
  if its container already exists the old clone is reused when it is at the
  planner head (a re-clone would orphan the bind-mounted inode).
* The resumed run must not call `_cleanup_stale_scenario_windows` /
  `cleanup_orphaned_qa_containers` (those belong to starting a *new* run).
* TUI restart is exec-in-place (same pid); kill -9 + `pm session` is a new
  pid; a CLI `qa-run-bg` driver is another pid — `resume_owned_elsewhere`
  semantics are unchanged.
* PR left `qa` while the TUI was down: snapshot dropped (unchanged).
* `stop_requested` set while scenarios are refining: launcher threads do not
  start new workers (existing pre-prepare check plus a check before the
  worker launch).
