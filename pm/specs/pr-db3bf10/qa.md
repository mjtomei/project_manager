# pr-db3bf10 — QA spec: a sign-off REQA deferred behind a live `pm qa run` survives a TUI restart

Implementation spec: `pm/specs/pr-db3bf10/impl.md`.
Change under test: `pm_core/qa_loop.py` (per-run `qa_run.json` record +
`run_driven_elsewhere`), `pm_core/tui/qa_loop_ui.py` (`owed_reqa_prs`,
`start_owed_reqa`, `reconcile_owed_reqa`, `arm_owed_reqa`, the poll-tick and
mount hooks, the `t`/`zz t` consumption, the pre-return PASS guards),
`pm_core/tui/app.py` (mount hook), `pm_core/tui/signoff_ui.py` (qa hop defers
behind a live run), `pm_core/tui/auto_start.py` (skip driven-elsewhere, route
the owed REQA through the claim), `pm_core/cli/pr.py` (`pm pr auto-sequence`
hop/catch-up guards), `pm_core/signoff.py`
(`claim_return_launch(require_status=...)`).

The bug: a `SIGNOFF_REQA` bounce leaves the PR at `qa` with an open
`signoff_return` awaiting `qa` — an owed **full** QA re-run. The start used
to live only in one TUI's memory (or behind the global auto-start switch), so
a TUI restart with auto-start off lost it and the PR sat at `qa` until
someone pressed `t`. The fix makes the obligation the persisted return record
and reconciles it from the poll tick and at mount, independent of auto-start,
waiting out a run another live process drives.

## How the obligation is created (setup knowledge for the scenarios)

There is no user command that writes `signoff_return.awaiting: qa`. It is
written by the sign-off router when it records `SIGNOFF_REQA` and applies the
`sign_off -> qa` hop. The realistic ways a *persisted, unstarted* obligation
appears on disk:

1. **Deferred behind a live run** (the bug's repro): a `pm qa run <instr>
   --pr <id>` is in flight while the `SIGNOFF_REQA` verdict is routed
   (`pm pr auto-sequence <pr>` from a pane, or the TUI's own sign-off step
   with auto-start on). The hop defers and leaves `awaiting: qa` on disk.
2. **The TUI died between the bounce and its start** — a race; not
   driveable deterministically, so scenarios use (1) and then restart.

The sign-off verdict can be produced deterministically with the bundled
fake-claude stand-in (`signoff` session type accepts `SIGNOFF_REQA`); a
`pm qa run` in flight is made long enough to overlap by giving the
`qa_scenario` / `qa_verification` fakes a delay.

**Observability.** `awaiting` is not printed by `pm pr show`. The user-visible
signals are: the PR's status (`pm pr list` / `pm pr show` / TUI row), the
TUI log pane, `pm pr auto-sequence` output, the tmux window set
(`qa-<pr>` plus one `qa-<pr>-sN` per scenario, and `signoff-<pr>`), the QA
workdir under `~/.pm/workdirs/qa/<pr>-*/` (`qa_status.json`, transcripts,
recordings), and `~/.pm/runtime/<pr>.json`. Scenarios assert on those, not on
internal keys.

## 1. Requirements

**R1 — A REQA deferred behind a live run is reported, not started.**
GIVEN a project with auto-start OFF, a PR in `sign_off` whose sign-off
router records `SIGNOFF_REQA`, and a `pm qa run` of that PR in flight,
WHEN the user's driver routes the verdict back to QA (`pm pr auto-sequence`
tick),
THEN the PR returns to `qa`, the tick reports that the re-QA is deferred
behind a run in flight, no second QA driver is launched, and the live run's
windows are left alone.

**R2 — A restarted TUI picks the obligation up without auto-start.**
GIVEN the state of R1 (PR at `qa`, the open return still awaiting QA, the
`pm qa run` still running) and a TUI restarted with auto-start OFF and no
targets,
WHEN the restarted TUI reaches its first ticks,
THEN it reports that the owed QA starts once the run another process drives
ends, starts nothing over the live run, and does so without any key press.

**R3 — Once the live owner finishes, exactly one full QA runs.**
GIVEN R2's state, WHEN the live `pm qa run` process exits,
THEN the TUI starts exactly one full QA for the PR — one `qa-<pr>` window
set, one scenario run, one verifier and one finalizer pass, one
`qa_status.json` for the new run — with auto-start still off and no `t`
press, and the PR stays at `qa` throughout (it is not handed to sign-off).

**R4 — The deferral is reported once per bounce, not once per tick.**
GIVEN a TUI watching an owed REQA that is deferred behind a live run,
WHEN several poll ticks pass,
THEN the deferral appears once in the log for that bounce episode (a repeat
after a fresh restart is fine), and the log does not fill with repeats.

**R5 — The obligation is durable across repeated restarts.**
GIVEN an owed REQA that has already been started (the run is in flight or
finished),
WHEN the user restarts the TUI again (auto-start off),
THEN no second full QA run is started — the TUI at most adopts/resumes the
existing run — and no duplicate `qa-<pr>` window set appears.

**R6 — Only a persisted open return authorizes a start.**
GIVEN auto-start OFF and each of: a PR at `qa` with no sign-off return, a PR
at `qa` whose return was already consumed/resolved, and a PR at `qa` whose
return is awaiting a different hop,
WHEN the TUI runs its ticks,
THEN no QA run starts for any of them, no `qa-<pr>` window appears, and the
idle ticks do not rewrite `pm/project.yaml` (its mtime is stable).

**R7 — A run in flight blocks every other starter.**
GIVEN a live `pm qa run` of a PR and, separately, auto-start ON targeting
that PR, an `O`/auto-sequence tick, and a second TUI on the same project,
WHEN each driver runs while the run is in flight,
THEN none of them starts a loop over it (auto-start does not announce a QA
start; the auto-sequence tick reports "driven elsewhere"; the second TUI
defers), and the live run's windows and files survive.

**R8 — Every starter shares one owner: one run, whoever wins.**
GIVEN an owed REQA and two or more drivers acting concurrently (two TUI
processes on the same project, a TUI plus `pm pr auto-sequence` ticks, plus
auto-start),
WHEN the live run ends and they all reconcile,
THEN exactly one full QA starts across all of them: one `qa-<pr>` window set,
one verifier/finalizer, one `qa_status.json`, and the losers report that the
launch was claimed elsewhere rather than starting.

**R9 — A pre-return verdict neither advances nor bounces the PR.**
GIVEN an owed REQA whose live run was in flight when the bounce was recorded
and now ends with PASS (or NEEDS_WORK) before the owed run writes its own
status,
WHEN the auto-sequence tick (or the TUI) observes that status,
THEN the PR is neither advanced to `sign_off` nor bounced to `in_review`;
the owed full re-run still happens (started by the tick or the TUI).

**R10 — Manual starts consume the same obligation.**
GIVEN an owed REQA, WHEN the user presses `t` (or starts the self-driving
loop with `zz t`),
THEN that run consumes the obligation: exactly one loop runs, and no second
full QA follows when it ends.

**R11 — Evidence is preserved.**
GIVEN a live `pm qa run` with its QA workdir (transcripts, scenario
recordings, `qa_status.json`) and the project's sources with uncommitted
changes,
WHEN the deferral, the restart and the owed start happen,
THEN no source file, draft, transcript, recording or workdir file is deleted
by the handoff, and the finished run's artifacts remain inspectable.

**R12 — The restarted TUI is usable immediately.**
GIVEN a restart with an owed REQA,
WHEN the TUI starts,
THEN its first frame paints promptly (it does not appear hung for seconds
while the owed start's project.yaml writes happen) and the owed start follows
right after startup.

**R13 — The original bug no longer reproduces.**
GIVEN the reproduction path of the bug report (auto-start off; PR in
`sign_off`; `pm qa run <instr> --pr <id>` live; `SIGNOFF_REQA` recorded;
`pm tui restart` before the CLI run exits),
WHEN the CLI run exits,
THEN the PR does not stay stranded at `qa`: exactly one full QA runs and
reaches a verdict, without pressing `t`.

## 2. Setup (cross-cutting, as user steps)

1. Install the workdir's pm into a venv (`pip install -e .`) with
   `PYTHONPATH` pointing at the workdir clone; confirm `pm which`.
2. Create a throwaway git project, `pm init --backend local --no-import`,
   add at least two PRs (the PR under test and an unrelated one that must be
   left alone). Advance the PR under test to `qa`/`sign_off` through the
   normal surface (`pm pr start`/`review`/`qa`/`signoff`, or the TUI keys).
3. `pm session` to create the pm tmux session, then start the TUI in its
   pane.
4. Write a fake-claude config for the session with the verdicts the scenario
   needs (`signoff: ["SIGNOFF_REQA"]`, a slow `qa_scenario`/`qa_verification`
   so a `pm qa run` stays in flight long enough to overlap, and a
   `qa_planning` body for the owed loop).
5. Keep auto-start OFF (no targets) for the recovery scenarios; only the
   auto-start-interplay story turns it on, via its normal control.
6. Do all of this inside the scenario container; captures go to the
   per-PR captures directory the worker prompt names.

## 3. Edge cases and failure modes

**E1 — The obligation disappears while the TUI watches.** GIVEN a TUI
showing an owed REQA, WHEN another process (a second TUI or an
auto-sequence tick) starts the run first, THEN the first TUI stops offering
it and does not start a second one, and stops rewriting `project.yaml` every
tick.

**E2 — The PR leaves `qa` before the owed start.** GIVEN an owed REQA and a
PR that is merged/closed or routed back to `sign_off`/`in_review` before the
tick starts it, WHEN the TUI ticks, THEN nothing starts and no `qa-<pr>`
window is created for a PR that is no longer at `qa`.

**E3 — A finished run's window is not mistaken for a live run.** GIVEN a
bounce whose previous QA windows are still on screen for inspection, WHEN
the auto-sequence tick evaluates the PR, THEN the stale window does not make
it report the PR as running forever; the owed run is launched (once).

**E4 — The live run's own status is not taken as the owed run's verdict.**
GIVEN the owed run has started (the obligation consumed) but has not written
its status yet, WHEN an older PASS or NEEDS_WORK is the newest status file,
THEN neither the TUI nor the tick acts on it while the owed run is in
flight.

**E5 — A PR with no workdir.** GIVEN an owed REQA on a PR whose workdir QA
itself provisions, WHEN the tick reconciles, THEN the run still starts (the
workdir is created by the run).

**E6 — Unrelated PRs are untouched.** GIVEN other PRs at `qa`/`in_review`/
`merged` with auto-start off, WHEN the reconciler runs, THEN none of them is
started or retargeted.

## 4. Pass / Fail criteria

A scenario passes when every `THEN` clause is observed on the user surface:
the exact PR status, the presence/absence and count of `qa-<pr>` windows,
the TUI log lines / `pm pr auto-sequence` output, the QA workdir contents,
and the stability of unrelated state. Failing any of: a second full QA run
(two `qa-<pr>` window sets, two `qa_status.json` for the new episode, two
verifier/finalizer passes), a stranded PR (still at `qa` with nothing
running after the live run ends), an unintended status change, a deleted
artifact, or a start over a live run — fails the scenario.

Anti-patterns that do not count as evidence: importing pm internals in a
script to read `awaiting`, grepping source files, or asserting on a specific
log string's position. Where the wording of a line is asserted it is only as
corroboration; the contract is single-owner / single-rerun.

## 5. Ambiguities resolved

- **`awaiting: qa` is internal.** Scenarios assert on the PR status, the
  windows, the logs and the workdir; the return record's key is not a user
  surface (`pm pr show` prints the verdict/hop, not `awaiting`).
- **The deferral log wording.** The implementation deliberately reuses the
  S127 wording ("QA starts once the QA run another process drives ends"). A
  scenario may look for that line, but must not fail solely because the
  wording changed if the behaviour (defer, then one start) is right.
- **How the owed state is created.** Hand-editing `signoff_return` into
  `project.yaml` is not a user action and is not used; the scenarios create
  it through the real bounce (see "How the obligation is created").
- **"Restart" means `pm tui restart`** (a clean restart, auto-start off), not
  a merge-restart breadcrumb restart — the latter preserves auto-start and
  is a different code path.
- **A claim left by a client that died** expires after 180 s. That is a
  unit-tested path; a scenario does not wait it out unless it can create the
  stale claim through a real user action, so no scenario asserts on it.

## 6. Unresolved ambiguities

None.
