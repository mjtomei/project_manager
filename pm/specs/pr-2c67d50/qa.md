# QA Spec — pr-2c67d50: resume QA scenario polling after INPUT_REQUIRED

## Scope (what shipped, in user terms)

A QA scenario worker that emits `INPUT_REQUIRED` is no longer treated as a
finished scenario. The QA loop keeps that scenario's own pane/transcript
under observation while the user answers the blocker, and when the worker
emits a follow-up `PASS` or `NEEDS_WORK` the run reopens, re-aggregates and
finalizes the new result — exactly the way `review_loop.py` already waits on
a single pane.

User-visible surfaces touched:

1. **The QA run itself** (TUI `t` / `/pr qa`, or an auto-start-driven run):
   a run with a waiting scenario stays alive; when no runnable work remains it
   finalizes `INPUT_REQUIRED` and is *held* (unbounded) until a follow-up,
   a stop, or the PR leaving `qa`.
2. **QA status dashboard** (`qa_status.py` pane in the `qa-<id>` window):
   the waiting scenario keeps its `INPUT_REQUIRED` verdict and gains a dim
   `(waiting)` suffix; the footer must still fit.
3. **TUI log lines / completion handling**: "waiting for input in the
   scenario worker pane (still watching for a follow-up verdict)" instead of
   "paused for human input"; pressing `t` on a held run reports the wait
   instead of starting a second run.
4. **PR notes**: each finalized result appends one QA note (`QA PASS`,
   `QA NEEDS_WORK`, `QA INPUT_REQUIRED`); a follow-up result appends a new
   note; a restart must not duplicate a note.
5. **Autostart status** (`pm autostart status` / `--json`): a held run reports
   "answer in the scenario worker pane (still watching for a follow-up)", and
   the JSON run entry carries `held: true`; while other scenarios are runnable
   the run reports as running, not waiting.
6. **`pm pr auto-sequence`**: a live run whose `qa_status.json` has no overall
   and whose qa window is gone but whose resume snapshot is owned by a live
   process reports `running: qa` instead of launching a duplicate driver.
7. **Restart/adoption**: `qa_resume.json` carries the waiting/held state and
   the run is re-adopted by a restarted TUI (Ctrl+R / `pm tui restart`, or a
   stop/start of the TUI), including a follow-up that landed during downtime.
8. **Worker/refiner prompts**: the scenario worker prompt now says
   `INPUT_REQUIRED` is *not* terminal (answer, then end with PASS/NEEDS_WORK;
   a repeated INPUT_REQUIRED keeps waiting) while PASS/NEEDS_WORK remain
   final. The concretizer prompt keeps its one-shot decision but is scoped.

Out of scope (deferred): scenario add/replace/rerun UI, regression authoring
(pr-0b14f2c), and the TUI auto-start scheduler duplicate-driver race filed as
pr-2ed93e5.

## Requirements (Given / When / Then)

### R1 — A waiting scenario keeps a live run alive
**Given** a QA run with a scenario worker that emitted `INPUT_REQUIRED`,
**When** the user does nothing,
**Then** the QA status dashboard shows that scenario as `INPUT_REQUIRED` with a
`(waiting)` marker, the run is still tracked (pressing `t` reports the wait, it
does not start a second run), a `QA INPUT_REQUIRED` PR note is recorded, and
the worker pane is left alive.

### R2 — Waiting must not block runnable work
**Given** a plan with two scenarios and a concurrency cap of 1, where scenario 1
emits `INPUT_REQUIRED` and scenario 2 is still queued,
**When** scenario 1 enters the wait,
**Then** scenario 2 is launched anyway (the waiting worker does not hold a
concurrency slot), the dashboard shows scenario 1 `(waiting)` while scenario 2
runs, and the run reports as running/progressing rather than waiting.

### R3 — The whole run finalizes INPUT_REQUIRED and is held
**Given** the only remaining runnable work is done and a scenario is still
waiting,
**When** the run aggregates,
**Then** the run finalizes overall `INPUT_REQUIRED` (the waiting verdict wins),
records its QA note once, keeps the `(waiting)` marker, and stays held so a
later answer can reopen it — it is not dropped from the TUI's tracking.

### R4 — A follow-up verdict reopens and finalizes the run
**Given** a held (or live) run with a waiting scenario,
**When** the user answers the blocker in the original scenario worker pane and
the worker emits a follow-up `PASS`,
**Then** the run collects the follow-up, the scenario is no longer marked
`(waiting)`, the follow-up PASS goes through the normal independent verifier,
the run finalizes `PASS`, a new `QA PASS` note is appended, and the PR is
offered/handed to sign-off. Nothing is merged automatically.

**When** the follow-up is `NEEDS_WORK`, **Then** the run finalizes
`NEEDS_WORK`, the PR returns to `in_review`, and the review loop starts.

### R5 — A repeated INPUT_REQUIRED keeps waiting
**Given** a waiting scenario whose user answered,
**When** the worker emits `INPUT_REQUIRED` again instead of a verdict,
**Then** the scenario remains waiting (marker still shown), no new run
finalization/note is produced for the repeat, and a later `PASS`/`NEEDS_WORK`
is still collected.

### R6 — A follow-up PASS is never a free pass
**Given** a waiting scenario,
**When** the PR branch head moves (new source committed/pushed) before the
follow-up verdict is accepted,
**Then** the run records `NEEDS_WORK` with a reason/note that the PR head moved
during the INPUT_REQUIRED wait and new source changes require review, the PR
returns to `in_review`, and no sign-off/merge occurs.

**Given** the head did not move,
**When** the follow-up `PASS` is flagged by the independent verifier,
**Then** the scenario does not keep `PASS`; it becomes `NEEDS_WORK` and the PR
returns to review.

**Given** a follow-up `PASS` that verifies,
**When** the run finalizes `PASS`,
**Then** the manual merge gate is intact: `pm pr merge` still refuses until a
fresh sign-off approves the current head.

### R7 — Restart while held re-adopts the run
**Given** a held run (finalized `INPUT_REQUIRED`, one scenario waiting),
**When** the TUI is restarted,
**Then** the new TUI re-adopts the run (log line that it is still watching),
the dashboard still shows `(waiting)`, pressing `t` reports the wait rather
than starting a new run, no duplicate QA note is recorded, and the worker pane
survives.

### R8 — A follow-up that lands while the TUI is down is collected
**Given** a held run whose TUI is stopped and whose worker emits its follow-up
while the TUI is down,
**When** the TUI is started again,
**Then** the follow-up is collected, the run reopens and finalizes the new
result (one new note), and no verdict is lost or duplicated.

### R9 — Stopping or leaving QA ends the hold
**Given** a held run,
**When** the user stops it (`zz t` / stop) or the PR leaves `qa` status,
**Then** the hold ends, nothing is relaunched, the dashboard stops advertising
`(waiting)` (the `INPUT_REQUIRED` evidence remains), and autostart stops saying
it is still watching.

### R10 — Superseded attempts are not consumed
**Given** a waiting scenario whose worker pane/session is gone,
**When** the loop drops that attempt and launches a new one,
**Then** no verdict appended to the superseded attempt's transcript is
accepted; the run waits for the new attempt's verdict (bounded by the relaunch
retry budget), and a repeated dead pane eventually settles as terminal
`INPUT_REQUIRED`.

### R11 — A live run is not duplicated by auto-sequence
**Given** a QA run that is live/reopened (status has no overall) and whose
`qa-<id>` window is gone, with a resume snapshot owned by a live process,
**When** another actor runs `pm pr auto-sequence <pr>`,
**Then** it reports `running: qa`, does not launch a second driver, and the
scenario worker panes the user answers in are not killed. An orphaned run (no
live owner) still relaunches.

### R12 — Worker prompt reconciliation
**Given** a launched scenario worker,
**When** the user reads its prompt (the `prompt.md` QA artifact),
**Then** the prompt describes `INPUT_REQUIRED` as not terminal — the loop keeps
the pane under observation and accepts a later PASS/NEEDS_WORK after the user
answers, and a repeated INPUT_REQUIRED keeps waiting — while PASS/NEEDS_WORK
remain final.

## Setup (cross-cutting, user steps)

- Throwaway project in the workdir: a git repo **with an initial commit on the
  base branch** (the QA workdir clone fails otherwise), `pm init --backend
  local --no-import`, one PR added, `pm pr start` so the branch and PR workdir
  exist, then the PR set to `in_review`.
- Pre-seed the QA spec at `pm pr spec-path <pr> qa` (the fake planner does not
  generate one, and the spec gate otherwise halts the run as INPUT_REQUIRED
  before any scenario launches).
- `pm session`, then `export PYTHONPATH` at the editable clone so `pm which`
  reports the PR branch.
- fake-claude config per session type: `qa_planning` emits a `QA_PLAN` body
  (one or two scenarios), `qa_concretize` `REFINED_STEPS`, `qa_scenario`
  `INPUT_REQUIRED` (scripted sequences for per-scenario differences — remember
  the interactive Scenario 0 consumes the first `qa_scenario` entry),
  `qa_verification` `VERIFIED`/`FLAGGED`, `qa_finalize` `FINALIZE_DONE`.
- Start QA from the TUI (`t` on the PR), not the CLI.
- **Follow-up verdicts:** fake-claude cannot answer an in-pane user reply, so
  after the user "answers" the blocker, the worker's follow-up turn is
  simulated by appending a user record and an assistant turn whose last line is
  `PASS` / `NEEDS_WORK` / `INPUT_REQUIRED` to the scenario's transcript
  (`~/.pm/workdirs/qa/<pr>-<loop>/transcript-s<N>.jsonl`, a symlink to the
  worker's native transcript). This is the only deterministic stand-in for
  Claude emitting a new verdict; the pane itself keeps showing the
  INPUT_REQUIRED state.

## Edge cases

- Follow-up lands between the hold's scan and the reopened live loop's scan.
- A PASS that predates the INPUT_REQUIRED baseline must not be accepted.
- A follow-up already present in the transcript when the pane has since died.
- TUI restart during the (possibly long) finalize pane.
- A held result finalized while the TUI was down is noted exactly once on
  adoption.
- A run superseded by a fresh start (`z t`) must not rewrite its snapshot or be
  resurrected.
- The hold is unbounded by design; it ends only on stop, PR leaving `qa`, or a
  follow-up.

## Pass/fail criteria

A scenario passes when every Then clause is observable on the named surface
(dashboard row, TUI log, PR note, PR status, `pm autostart status`,
`pm pr auto-sequence` output, files under the QA workdir). It fails when a
waiting scenario is finalized and dropped (later output ignored), when the run
blocks runnable work or reports a wait while work proceeds, when a stale or
superseded verdict is accepted, when a follow-up PASS is promoted without
verification or after the head moved, when a note is duplicated/lost, when a
second driver launches over a live run, or when a stop/PR-leave does not end
the hold.

## Ambiguities resolved

- **What "the user answers in the original worker pane" means for the
  harness:** the transcript append described in Setup. The SUT behavior under
  test is verdict collection, not Claude's own reply.
- **PASS hand-off:** with auto-start in scope the TUI hands the PR to sign-off;
  without it the log offers sign-off (`i`). Scenarios assert "offered/handed
  off and not merged" rather than requiring one variant.
- **Whether a waiting scenario consumes a concurrency slot:** no (scope says
  runnable work must proceed); the cap-1/queued story depends on this.
- **Should the hold continue after a follow-up NEEDS_WORK?** No — the run has
  left QA; remaining INPUT_REQUIRED evidence stays recorded for the next run.

No **[UNRESOLVED]** ambiguities.
