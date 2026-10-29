# QA Spec — pr-1ab9075

**Title:** Bug: one failed QA worker blocks verdict collection during retry
backoff

## Summary of the change (what a user can observe)

The QA orchestration loop (`_poll_tmux_verdicts`) used to retry a dead scenario
worker inline: `time.sleep(5 * 2**n)` (up to 2560 s) inside the single poll
loop, plus a global `grace_start` reset. One dead worker therefore froze
verdict collection, verification, queued launches and stop handling for every
other scenario. The loop also counted "a tmux window was created" as success,
so a worker whose `podman exec` died instantly (PID/keyring exhaustion) burned
its retries with no recorded cause, and scenarios that never got a window
(workdir clone / container create / window failure, e.g. keyring EDQUOT before
any pane existed) were marked INPUT_REQUIRED immediately and never retried.

What a user can now observe in the TUI and in `qa_status.json`:

1. **Per-scenario, nonblocking retries.** A dead or un-launchable scenario gets
   its own retry record (attempts, failure kind, cause, next-attempt wall
   clock). The poll loop only checks deadlines; launches, relaunches and
   container diagnosis run in background threads. Healthy scenarios keep
   collecting verdicts, verifying, and dequeuing queued scenarios; a stop is
   observed on the next tick.
2. **Bounded retries.** At most 6 attempts per scenario per run, delays
   5/10/20/40/80/160 s (capped at 300 s). The budget is not reset by a
   successful start.
3. **Three failure kinds.** `create` (no worker pane ever existed — workdir,
   container create or window/split failure, including initial no-pane
   failures), `exec` (a pane existed but Claude never started), `exit` (the
   worker started and its pane later died without a verdict). `create` retries
   go through the full launcher (fresh clone/container); `exec`/`exit` retries
   re-create only the worker window in the existing clone/container.
4. **Runtime cause surfaced.** Container failures are classified: keyring
   quota (EDQUOT / "session key" / "keyring"), process (PID) limit exhaustion
   ("Cannot fork", "pids limit", …), and container state ("container X is
   exited/not found"). A PID cause names `podman restart <name>`; a keyring
   cause names the reap/raise-quota remediation. When the budget runs out the
   scenario is INPUT_REQUIRED with a reason that says it is a **runtime
   failure, not an agent verdict**, and the overall run is INPUT_REQUIRED.
5. **Status display.** While retrying, the dashboard shows `launch retry n/6`
   (rendered from `(launch-retry:n/6)` in `qa_status.json`) with the cause and
   the next-attempt time; it is not counted as complete and the progress line
   reports `(n relaunching)`. The TUI log shows the relaunch number, delay and
   cause.
6. **Results, evidence and retry state survive.** Verdicts are never replaced
   by retry bookkeeping. `exec`/`exit` retries keep the clone and container
   (worker commits/files survive; container id unchanged); `create` retries
   tear down the previous attempt's leftover window/container. A relaunch
   leaves exactly one window with the scenario's name. `launch_retries` is
   persisted in `qa_resume.json`, so a TUI restart continues the same attempt
   count/deadline and an interrupted launch counts as an attempt.
7. **Queued launches run off the poll thread.** A slow or stalled concretizer
   for a dequeued scenario no longer blocks verdict collection, verification,
   retries or stop.

## Requirements

### R1 — One dead worker does not block the others
**Given** a QA run with several scenarios whose workers are running,
**When** one scenario's worker dies (its container is stopped, or its pane is
killed) and the loop schedules a retry,
**Then** the other scenarios still reach their verdicts and are verified while
the failed scenario is still in its retry backoff, and the run does not stall
until the failed worker recovers.

### R2 — Retries are per scenario and bounded
**Given** a scenario that has failed its first launch,
**When** the loop retries it,
**Then** the retry is scheduled on that scenario's own deadline (about 5, 10,
20, 40, 80, 160 s between attempts, at most 6 attempts), the delay is visible
in the TUI log/status, and another scenario's failure or recovery does not
change this scenario's attempt count or deadline.

### R3 — The runtime cause is surfaced, not an agent judgment
**Given** a worker whose launch/exec failed for a container/runtime reason
(container stopped, PID limit, keyring quota, missing image),
**When** the loop records the failure,
**Then** the status reason names the runtime problem (and, for PID/keyring
exhaustion, the named remediation) and the scenario is shown as a launch
retry — not as an agent verdict and not as an unexplained request for human
judgment.

**Given** that scenario never recovers and its retry budget is spent,
**When** the run finalises,
**Then** the scenario is INPUT_REQUIRED with a reason containing "runtime
failure, not an agent verdict", the failure kind label ("worker could not be
created" / "worker exited before Claude started" / "worker exited before any
verdict"), the number of attempts and the recorded cause, and the overall run
is INPUT_REQUIRED (never PASS).

### R4 — Creation failures (no pane at all) are retried
**Given** a QA run where a scenario's container/workdir/window could not be
created, so no worker pane ever existed (e.g. the container image is missing,
or the runtime returns a keyring EDQUOT),
**When** the loop reaches that scenario,
**Then** it is put into a bounded launch retry (shown as `launch retry n/6`)
instead of being marked INPUT_REQUIRED immediately, the recorded cause begins
with "worker could not be created" and includes the container-create text, and
no scenario window is left behind for that attempt.

**Given** the cause is then fixed by the user (valid image restored, quota
recovered),
**When** the next retry fires,
**Then** the scenario is re-cloned/re-created and its worker starts, without a
controller restart, and no duplicate container/window from the failed attempts
remains.

### R5 — Stop is prompt during backoff
**Given** a scenario waiting out a retry backoff,
**When** the user stops the QA loop,
**Then** the loop exits within about one poll interval (≤ ~10–20 s), the TUI
reports the run as finished/stopped promptly rather than after the backoff,
and no new worker window/pane is created after the stop.

**Given** a retry comes due in the same tick the stop lands,
**When** the loop processes the tick,
**Then** no relaunch is started and the attempt is not spent (the retry record
stays waiting), so a later resume retries it.

### R6 — Restart preserves results and retry state
**Given** a run where some scenarios already PASSed and were verified and
another is in launch-retry backoff,
**When** the user restarts the TUI (Ctrl+R),
**Then** the run resumes automatically, the completed verdicts are still shown
as PASS and are not re-verified, the retrying scenario's attempt count does
not reset, and the retry fires at/after its recorded deadline (immediately if
the deadline passed while the TUI was down).

**Given** the restart happened while a launch was in flight,
**When** the run resumes,
**Then** that interrupted launch counts as one attempt against the bounded
budget and is re-attempted.

### R7 — Evidence and windows are preserved
**Given** a scenario whose worker started and then died (`exec`/`exit`),
**When** it is relaunched,
**Then** its clone (including files/commits the worker wrote) and its
container (same id) are preserved, the transcript symlink is re-pointed to the
new session, and exactly one tmux window with the scenario's name exists.

**Given** a scenario whose verdict already landed (collected before the pane
died, or restored from the resume snapshot),
**When** the retry bookkeeping runs,
**Then** the verdict is not overwritten with INPUT_REQUIRED and the scenario
is not relaunched.

### R8 — Queued launches do not block the loop
**Given** a run with a concurrency cap and a queued scenario whose concretizer
is slow or stalled,
**When** other scenarios finish and need verdict collection/verification, or
the user stops the run,
**Then** those actions happen promptly during the stall (the loop is not
blocked behind the concretizer) and a stop does not spawn a worker for the
queued scenario.

The pr-592e4bd review note called out that the queued refiner
(`_concretize_scenario`/`poll_for_verdict`) still ran on the poll thread. The
current code reconciles this: `_launch_next_queued` starts the whole launch
(workdir, container, concretizer poll, worker split) via `_start_op` in a
background thread, so a slow or stalled refiner — including a routed refiner
held by `_RouteStallWatch` during a mid-run route outage — no longer holds
verdict collection, retries, verification or stop. Exercise this, not the
route-gate deferral alone.

### R9 — Verdict criteria and verification unchanged
**Given** healthy scenarios emitting PASS / NEEDS_WORK / INPUT_REQUIRED,
**When** the run completes (with or without retries elsewhere),
**Then** each scenario's verdict is exactly what its worker emitted, PASSes
still go through verification, and the overall verdict follows the existing
aggregation (any NEEDS_WORK → NEEDS_WORK, any INPUT_REQUIRED/unverdicted →
INPUT_REQUIRED, all PASS → PASS).

### R10 — Verification re-evaluation and launch retries interact safely
**Given** a worker that emitted PASS and whose verification was FLAGGED, so
its verdict was cleared and a follow-up was sent for re-evaluation,
**When** that worker's pane then dies before it emits the re-evaluated
verdict,
**Then** the stale PASS in its old transcript is **not** resurrected (the
`idx not in verification_failures` guard), the scenario enters a bounded
launch retry classified as `exit` with a runtime cause, its clone/commits
survive, and the relaunched worker's new verdict is collected and verified
normally. Repeated flags/crashes must end at NEEDS_WORK via the existing
verification-retry budget, not silently at PASS and not as an unexplained
INPUT_REQUIRED.

## Setup

Cross-cutting setup (per scenario, in its own container):

- Follow `tui-manual-test.md`: install pm into a venv from the PR clone, set
  `PYTHONPATH=/workspace` (verify with `pm which`), create a throwaway git
  project, `pm init --backend local --no-import`, `pm pr add` one or more PRs
  and note their ids/branches, start `pm session` (ignore the attach error).
- Seed a QA spec for the PR so the post-planning spec gate passes: write
  `pm/specs/<pr-id>/qa.md` in the test project (the gate also accepts the
  PR workdir copy) before starting QA. The spec content is not under test.
- Configure fake-claude for the run (`pm fake-claude config set`, current
  session tag): `qa_planning` emits a `QA_PLAN` body with 2–3 `SCENARIO`
  blocks; `qa_concretize` emits `REFINED_STEPS` (optionally with a `delay` to
  stall a queued scenario); `qa_scenario` emits the verdict(s) needed
  (`{"verdicts": {"PASS": 100}}` for an all-PASS run, or a scripted sequence
  for a mixed PASS/NEEDS_WORK run); `qa_verification` emits `VERIFIED`;
  `qa_finalize` emits `FINALIZE_DONE`; `_all: {}` for everything else.
- Drive the loop from the TUI: select the PR and start QA (`t`), watch the QA
  window's status dashboard pane, the scenario windows, the TUI log, and
  `qa_status.json` under `~/.pm/workdirs/qa/<pr-id>-<loop-id>/`.
- Container-mode scenarios additionally need `project: nested_podman: true`
  in the test project's `project.yaml` (bootstrap-only), `pm container
  enable`, and a working container image (the default image auto-builds on
  first use; allow time for it). Swap the image with `pm container set image
  <image>` to drive a missing-image create failure and to restore it.
- Host-mode scenarios simply skip `pm container enable`; their workers run
  `claude` (fake-claude) directly in a tmux pane, so a dead worker is a dead
  pane.
- To make one worker fail while its siblings stay healthy, give all workers
  the same fake-claude behaviour (e.g. a pre-verdict `delay`) and kill only
  the target worker's pane (or stop only its container) partway through — the
  fake config cursor is global to the session, so a scripted per-invocation
  sequence is not per scenario. `hold: 0` makes a worker exit right after
  writing its verdict (E2); a `delay` longer than the kill time makes it die
  before it ever starts (E7 `exec`).

## Edge cases

### E1 — Two workers fail at once
Two scenario containers are stopped (or two panes killed) within a few
seconds of each other while a third runs. Both must show independent attempt
counts and independent next-attempt times; the third must complete and be
verified; neither retry may delay the other or the third.

### E2 — Verdict emitted, then the pane dies before it is collected
A worker writes its verdict (transcript + idle hook) and its pane dies before
the next poll. The completed result is expected to be preserved (per "preserve
completed results"); if the loop instead relaunches the scenario and shows a
launch retry, record that the emitted verdict was discarded as a finding.

### E3 — Stop in the tick a retry comes due
The retry is due at the same moment the user stops. No relaunch may start, no
attempt may be spent, and the record must remain resumable.

### E4 — Resume with a past-due / in-flight retry
A retry deadline that passed while the TUI was down fires on the first resumed
tick; a launch that was in flight when the controller died counts as an
attempt (so a crash-looping controller still exhausts the bounded budget).

### E5 — Keyring EDQUOT before any pane exists
Creation fails with the crun/runc keyring text (reproduce with a bounded
runtime wrapper, not a real quota change). The cause must be classified as
keyring quota exhaustion with its remediation, and the retry must proceed.

### E6 — PID-limit exhaustion kills a running worker
A scenario container is put at a process limit (bounded synthetic failure,
e.g. a lowered pids limit or a wrapper returning "Cannot fork"). The surfaced
cause must name the PID/process limit and the `podman restart <name>`
remediation; a healthy sibling must keep moving meanwhile.

### E7 — Host mode (no container)
A worker pane dies with no container to probe. The cause must be a sensible
fallback ("pane died at startup…" / "pane died mid-run…") with no bogus
container restart hint, and the same nonblocking retry behaviour applies.

### E8 — Stop while a launch thread is mid-concretize
The stop must not leave a worker pane spawned after the fact, nor a scenario
stuck in a "launching" state.

### E9 — Verification flags a PASS and the worker dies during re-evaluation
A worker emits PASS, verification returns FLAGGED, the follow-up message is
sent, and the worker's pane dies before it emits a new verdict. The old PASS
must not be collected again; the scenario must enter an `exit` launch retry
with the clone preserved, and the new verdict must be collected after the
relaunch. Watch the follow-up send path: the extra blank Enters after the
follow-up are sent to the worker pane without re-checking that it still
exists, so a pane that dies between them is a candidate crash of the poll
loop — record it as an incidental finding if it reproduces.

### E10 — Restart during a create-kind backoff
A scenario whose container/workdir/window creation failed (no pane ever
existed) is waiting out a `create` retry when the TUI is restarted. The
attempt count and deadline must survive; the past-due retry must fire on the
first resumed tick; the retry must re-clone and re-install the scenario's
instruction file (the `instruction_source` field exists for exactly this), and
must not leave a duplicate window or the previous attempt's container behind.

## Pass/Fail criteria

A scenario passes when every Then above is observable in the captured TUI,
`qa_status.json`, the QA debug log, tmux window list and/or the container
list. Specific failures:

- A healthy scenario's verdict, verification, queued launch or a stop is
  delayed by another scenario's backoff (this is the original bug).
- A retry delay exceeds the bounded sequence, the attempt count is shared
  across scenarios, or the budget resets so a crash loop retries forever.
- A runtime failure is reported as an agent verdict / bare "needs human
  judgment", or INPUT_REQUIRED is shown without the "(runtime failure, not an
  agent verdict)" explanation and cause.
- A no-pane creation failure is marked INPUT_REQUIRED without retrying.
- A completed verdict is overwritten or a finished worker is relaunched.
- A relaunch re-clones a started worker (losing its commits) or leaves two
  same-named windows.
- A restart resets the retry count, re-verifies already-verified PASSes, or
  loses collected verdicts.
- The status board counts a `launch retry` scenario as complete, or the run's
  overall verdict becomes PASS with a scenario still retrying/unverdicted.
- Stop takes longer than a couple of poll intervals during backoff, or a
  worker/window is created after the stop.

## Ambiguities (resolved)

A1. **Live container-mode testing requires nested podman** inside the QA
scenario container (the test project's pm launches scenario containers from
inside the scenario container). If the environment cannot run nested podman,
exercise the equivalent host-mode paths (pane death → `exec`/`exit` retry,
stop, restart, queued launch) and record the container-specific coverage
(container diagnosis, container create failure, keyring/PID classification) as
**UNRESOLVED / missing** rather than passing it.

A2. **Synthetic runtime failures are sanctioned** by the PR description for
PID/keyring exhaustion ("bounded synthetic failure rather than creating a real
fork storm"). A wrapper runtime on `PATH`, or a container configuration that
makes `run`/`exec` fail with the real error text, is acceptable; a real fork
storm or a kernel-wide key-quota change is not.

A3. **Stop surface** is `zz t` (start/stop QA loop) and fresh restart is `z t`
(stop + restart). "Prompt" stop means within about one poll interval
(`_POLL_INTERVAL` = 5 s) plus loop teardown.

A4. **Completed-verdict preservation across a pane death** (E2) is resolved as
"preserve": the PR requires completed results and evidence to survive
recovery, and the transcript is the verdict source of truth. If the
implementation relaunches instead, it is a finding, not a pass.

A5. **`create` vs `exec` classification** is judged by what the user can see:
if the worker's transcript/idle hook ever materialised before the pane died it
is an `exit` (or a started worker), otherwise `exec`; a scenario that never
got a window/pane is `create`.

A6. **Nested podman is available in this environment.** The 2026-10-28 run
(scenarios 1–5, workdir
`/home/matt/.pm/workdirs/qa/pr-1ab9075-5108c0a1b04b9659`) drove real scenario
containers, container identity and container restarts end-to-end, so A1's
host-mode fallback is not needed; container-specific coverage is in scope.

A7. **Host mode (no container) is still worth exercising** even though A6
holds: it is the default backend and takes the no-container branches
(`_EXEC_CAUSE` / `_EXIT_CAUSE` fallbacks, no diagnosis, no restart hint) that
container-mode runs never touch.

A8. **Fake-claude makes a worker die on the verification follow-up.** When a
worker runs under fake-claude and the verifier FLAGs its PASS, the follow-up
`send_keys` is read as stdin by the fake, which then exits — so E9 can be
driven deterministically without killing panes by hand.
