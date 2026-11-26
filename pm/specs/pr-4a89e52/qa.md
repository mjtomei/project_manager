# QA Spec: QA verdict collection survives TUI restart (pr-4a89e52)

## Summary

QA scenario verdict collection used to run in a daemon thread *inside the
TUI process*. When the TUI restarted, that thread died and `app._qa_loops`
was lost — the scenario tmux windows kept running to completion, but nobody
collected their verdicts, computed the overall result, updated
`qa_status.json`, or drove the lifecycle transition (merge / back-to-review).

The fix makes the orchestration **resumable**: each in-progress QA run
persists a `qa_resume.json` sidecar in its QA workdir. On every poll tick the
restarted TUI scans `~/.pm/workdirs/qa/*/qa_resume.json` and, for any run not
already tracked in memory whose PR is still in `qa`:
- **re-spawns** the verdict-collection loop if the run is still incomplete, or
- **processes the completion** directly if the daemon already wrote the
  `overall` verdict before the TUI died.

The user-visible contract: **a TUI restart while QA is in flight must not lose
the QA result.** Verdicts still get collected, the overall verdict still gets
computed and written to `qa_status.json` (rendered in the QA status pane), the
QA note is still recorded on the PR exactly once, and the PR still transitions
(PASS → ready/merge, NEEDS_WORK → in_review).

## Surfaces under test

- **The pm TUI** (tech tree shows PR status; the QA status pane renders
  `qa_status.json`; the TUI log shows "Resuming QA … after restart").
- **`pm tui restart`** — sends Ctrl+R to the TUI pane. The *clean* restart
  (no `--breadcrumb`) is exactly the condition that drops `app._qa_loops`.
  The pm tmux session and the scenario windows survive the restart.
- **The pm tmux session** — scenario windows/panes and the QA status window
  outlive the TUI restart.
- **The PR record** (`project.yaml`) — status + QA notes, observable via the
  tech tree and via `pm pr show` / `pm pr list`.
- **fake-claude** — scripted Claude stand-in driving deterministic verdicts
  for the planner, scenario workers, verification, and finalize so a run
  reaches a verdict without real API calls.

## Shared resources touched by the diff (concurrency inventory)

| Resource | Writers | Readers | Concurrency concern |
|---|---|---|---|
| `~/.pm/workdirs/qa/<run>/qa_resume.json` | daemon poll loop (every iteration), `_execute_and_finalize` (before/after) | TUI poll scan, cleared by TUI on completion | A resumed daemon keeps rewriting it while the TUI poll reads it |
| `~/.pm/workdirs/qa/<run>/qa_status.json` | daemon poll loop | QA status pane process, TUI resume scan | Display pane and resume scan both read while daemon writes |
| pm tmux session + scenario windows/panes | scenario Claude sessions, relaunch path | TUI, status pane | Must outlive the TUI restart; resume re-binds to existing panes |
| `project.yaml` (PR status + notes) | lifecycle transition, `_record_qa_note` (locked_update) | TUI, CLI | Two concurrently-resumed PRs both append notes |
| glob `qa/*/qa_resume.json` | — | every TUI poll on every running TUI | Must not resurrect historical/finished/non-qa runs |
| `~/.pm/hooks/` idle_prompt events | scenario hooks | poll loop turn-gate | Persist on disk, so completed scenarios re-enter `pending` on resume (guarded by `verified_scenarios`) |

Each is exercised by Scenario 3 (concurrent two-PR resume) and/or Scenario 4
(no spurious resurrection across the shared glob).

## Setup (cross-cutting)

All scenarios use the **TUI Manual Testing** instruction:
1. Install the editable pm clone into a venv, override `PYTHONPATH` to the
   clone, confirm with `pm which`.
2. Create a throwaway git project, `pm init --backend local --no-import`, add
   one or more PRs, and set the PR(s) under test to `status: in_review` (or
   `qa`) in the bootstrap `project.yaml`.
3. Configure **fake-claude** for the session so QA reaches verdicts
   deterministically (`pm fake-claude config set`). Start from
   `tests/fixtures/fake_claude/example-config.json`. The relevant session
   types for a full QA run: `qa_planning` (emits the scenario plan),
   `qa_concretize` (REFINED_STEPS), `qa_scenario` (PASS / NEEDS_WORK / …),
   `qa_verification` (VERIFIED), `qa_finalize` (FINALIZE_DONE). Use a `delay`
   on `qa_scenario` to keep a run in-progress long enough to restart mid-flight.
4. Start the pm session (`pm session 2>/dev/null || true`).

Drive QA from the TUI (`t` = one-shot QA, `zz t` = QA loop) or via
`pm tui send`, and restart with `pm tui restart` (clean) — all from inside the
test tmux session, never the worker's own session.

## Requirements (Given / When / Then)

### R1 — A mid-run TUI restart resumes verdict collection
**Given** a PR in QA whose scenario windows are still running (verdicts not yet
collected) and the TUI showing the run in progress,
**When** the user runs a clean `pm tui restart` (Ctrl+R),
**Then** after restart the TUI logs that it is resuming QA for that PR, the QA
status pane continues to fill in per-scenario verdicts, an overall verdict is
eventually computed and written to `qa_status.json`, and the scenario windows
were never killed/relaunched from scratch.

### R2 — A resumed PASS run drives the PASS lifecycle and records one note
**Given** a QA run that resumes after restart and all scenarios pass
verification,
**When** the resumed loop reaches an overall PASS,
**Then** the PR shows an overall PASS in the status pane, a single `QA PASS …`
note is recorded on the PR, and (auto-start off) the PR remains in `qa` ready
for manual merge — with no duplicate note even after further restarts.

### R3 — A resumed NEEDS_WORK run returns the PR to review
**Given** a QA run that resumes after restart and at least one scenario reports
NEEDS_WORK,
**When** the resumed loop reaches an overall NEEDS_WORK,
**Then** the PR transitions from `qa` to `in_review` (visible in the tech
tree), a single `QA NEEDS_WORK …` note is recorded, and the status pane shows
the NEEDS_WORK overall.

### R4 — A restart after the daemon already finished still processes the result
**Given** a QA run whose daemon wrote the `overall` verdict to
`qa_status.json` but the TUI restarted before processing it,
**When** the TUI comes back up and runs its poll/resume scan,
**Then** the completion is processed directly (verdict surfaced, lifecycle
transition done, exactly one QA note recorded) without re-launching scenarios
or re-running the finalize pane.

### R5 — Concurrent runs both survive a single restart
**Given** two different PRs each with a QA run in progress,
**When** the user restarts the TUI once,
**Then** both runs are independently resumed, each reaches its own overall
verdict in its own status pane, and each PR gets its own single QA note and
correct lifecycle outcome — neither run interferes with the other.

### R6 — A restart with no in-flight QA is a clean no-op
**Given** a project where no QA run is currently in progress (none ever run, or
all prior runs finished and were processed),
**When** the user restarts the TUI (possibly several times),
**Then** the TUI starts cleanly, no scenario windows are spawned, no QA notes
are added, and no PR status changes — the resume scan finds nothing to do.

## Edge cases (Given / When / Then)

### EC1 — Resume does not re-verify already-verified scenarios
**Given** a run where some scenarios were already PASS-verified before the
restart (their verdicts/verified state are in the snapshot),
**When** the run resumes,
**Then** the resumed loop trusts the prior verification and does not spawn a
fresh verifier Claude session/pane for scenarios already in the verified set
(even though their on-disk idle_prompt events make them re-enter the pending
poll). New, not-yet-verified PASS scenarios still get verified once.

### EC2 — Repeated restarts after completion never duplicate the note
**Given** a PASS run that completed and was fully processed (PR remains in `qa`
with a single QA note, auto-start off),
**When** the user restarts the TUI again one or more times,
**Then** no additional QA note is appended, no scenarios are relaunched, and
the PR status is unchanged — the snapshot was cleared on first processing so it
cannot re-fire.

### EC3 — A snapshot whose PR has left QA is cleaned up, not resumed
**Given** a `qa_resume.json` lingering for a PR that is no longer in `qa`
status (e.g. it moved to `in_review` or `merged`),
**When** the TUI poll/resume scan runs,
**Then** the run is not resumed and the stale snapshot is removed from disk;
the PR's status and notes are untouched.

### EC4 — Historical QA workdirs are not resurrected
**Given** multiple old QA workdirs on disk from prior runs (the resume scan
globs all of `qa/*/qa_resume.json`),
**When** the TUI runs its periodic resume scan over many ticks,
**Then** only genuinely in-progress runs for PRs still in `qa` are resumed;
finished runs are ignored and the scan stays a cheap, non-disruptive no-op.

### EC5 — Interrupted before the first snapshot abandons the run cleanly
**Given** a QA run interrupted during the planning/launch phase, before any
`qa_resume.json` was written,
**When** the TUI restarts,
**Then** there is nothing to resume for that run (accepted limitation — no
spurious note, no half-state lifecycle transition), and the user can simply
start QA again.

## Pass / Fail criteria

**Pass:**
- After a clean TUI restart mid-run, the QA result is still produced: per-
  scenario verdicts appear in the status pane, an overall verdict is written to
  `qa_status.json`, and the correct lifecycle transition occurs.
- Exactly one QA note is recorded per run, regardless of how many times / at
  what point the TUI is restarted.
- Scenario windows survive the restart (not killed and re-planned from scratch).
- Concurrent runs resume independently; neither is dropped or cross-contaminated.
- Stale / non-qa / historical snapshots are ignored (and non-qa ones removed)
  rather than re-launching QA.

**Fail:**
- After restart, the run is silently abandoned — `qa_status.json` never gets an
  overall verdict, no note is recorded, and the PR sits in `qa` forever.
- A duplicate QA note is appended on restart, or `_on_qa_complete` runs twice.
- The resume re-spawns a verifier for already-verified scenarios, or relaunches
  scenarios from scratch / re-runs finalize when it shouldn't.
- A historical/finished/non-qa snapshot triggers a spurious QA run, note, or
  status change.
- One concurrent run's resume clobbers or starves the other.

## Ambiguities (resolved)

- **A1 — What "TUI restart" means.** Resolved as a clean `pm tui restart`
  (Ctrl+R, no `--breadcrumb`), which discards in-memory state including
  `app._qa_loops` while the pm tmux session and scenario windows persist. The
  `--breadcrumb` variant preserves review/auto-start state and is not the
  failure mode this PR targets.
- **A2 — Container mode vs tmux mode.** The snapshot persists `use_containers`
  / `container_name`, so container-mode resume is in scope. Container mode
  requires `nested_podman: true` in the test project and is environment-
  sensitive; the primary scenarios run in plain tmux mode (the more reliable
  surface) and container-mode resume is an optional variation in Scenario 1.
- **A3 — Observing "completed-during-downtime" vs "incomplete" resume.** Both
  produce the same end state (verdict + single note). The distinguishing
  observable is timing of the restart relative to the `overall` write; the plan
  drives restarts at multiple points rather than asserting on internal code
  paths.
- **A4 — Self-driving (`zz t`) state across restart.** `app._self_driving_qa`
  is in-memory only (accepted limitation EC7 in impl.md): a resumed run drives
  its transition via the legacy/auto-start path. Verdict survival and the
  PASS→merge / NEEDS_WORK→in_review transition still hold, so the scenarios
  assert on those, not on consecutive-pass counting.
