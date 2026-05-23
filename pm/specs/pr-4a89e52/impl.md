# Spec: QA verdict collection survives TUI restart (pr-4a89e52)

> **History note.** The branch's original fix (move pane-capture verdict
> polling into `qa_status.py`) was implemented against a base that is now
> 1152 commits behind master. Master re-architected QA verdict collection
> into a rich in-process orchestration loop (transcript/JSONL-based
> detection, PASS-verification panes, a concurrency-capped scenario launch
> queue, hook-driven idle detection, verdict reasons, and a finalize
> phase). The user chose to **re-implement on master**. This spec describes
> the master-based design that landed. The old `qa_status.py` `VerdictPoller`
> approach was discarded during the merge (it could not host master's
> orchestration loop, which needs launch/container/hook context the
> display-only status pane lacks).

## Problem

QA orchestration (`run_qa_sync` in `pm_core/qa_loop.py`) runs in a **daemon
thread inside the TUI process**, spawned by `start_qa_background` (called from
`pm_core/tui/qa_loop_ui.py`). The thread plans scenarios, launches them in tmux
windows, then runs `_poll_tmux_verdicts` — a long orchestration loop that
collects verdicts (from per-scenario JSONL transcripts, gated on hook
`idle_prompt` events), runs PASS-verification panes, launches queued
scenarios, computes the overall verdict, and runs the finalize pane.

When the TUI restarts, that daemon thread dies and `app._qa_loops` is emptied.
The scenario tmux windows keep running (they live in the pm tmux session, which
outlives the TUI client), but **nobody collects their verdicts, computes the
overall result, or drives the lifecycle transition** (merge / back-to-review).
`poll_qa_state` only ever inspected in-memory `app._qa_loops`, so a restarted
TUI never observes the run again.

## Approach: resume the orchestration loop on restart

Verdict collection on master is too tightly coupled to in-process, in-memory
state to relocate into the status pane. Instead, the orchestration is made
**resumable**: each in-progress run persists a snapshot of its reconstructable
state, and the TUI re-spawns the loop (or processes a completion) for any
orphaned run it finds on disk.

### R1 — Persist a resume snapshot (`qa_resume.json`)
`qa_status.json` is the display contract (read by `qa_status.py`) and only
carries `index/title/verdict/verdict_reason/window_name`. The orchestration
loop needs far more per-scenario runtime state to keep going:
`session_id` (the hook turn-gate key), `transcript_path` (verdict source of
truth), `pane_id` (reminders/follow-ups), and `worktree_path`/`container_name`
/`verifier_*` (relaunch + verification).

New in `pm_core/qa_loop.py`:
- `_RESUME_FILENAME = "qa_resume.json"`, `_resume_file_path(qa_workdir)`.
- `_scenario_to_resume_dict` / `_scenario_from_resume_dict` — serialize the
  resumable `QAScenario` fields.
- `_write_resume_file(state, use_containers, concurrency_cap, queued_indices)`
  — atomic tmp+rename; best-effort (logs, never raises). Persists run-level
  fields (`pr_id`, `loop_id`, `qa_workdir`, `session_tag`, `use_containers`,
  `concurrency_cap`, `finalize_verdict`, `scenario_verdicts`,
  `scenario_verdict_reasons`, `verified_scenarios`, `queued_indices`),
  every scenario, and `scenario_0`.
- `_load_resume_file` / `clear_resume_file` / `build_resume_state`.

The snapshot is written:
- once before the blocking poll (start of `_execute_and_finalize`),
- every poll iteration inside `_poll_tmux_verdicts` (so queued-launch and
  verdict mutations persist),
- again after finalize (so the overall + finalize verdict are carried).

### R2 — Re-enter the execution phase without re-launching
`run_qa_sync`'s tail (poll → aggregate → persist → finalize → summary) is
extracted into `_execute_and_finalize(...)`, called by both `run_qa_sync`
(after planning + launch) and the new `resume_qa_sync` (skipping planning +
launch — the scenario windows already exist). Behavior of `run_qa_sync` is
unchanged (verified by the existing `tests/test_qa_loop.py` /
`test_qa_finalize_wiring.py` / `test_qa_self_driving.py` suites).

`resume_qa_sync(state, pm_root, pr_data, on_update)` rebuilds the execution
context (session, workdir, status path, repo root, `use_containers`,
`concurrency_cap`, queued scenarios from the snapshot) and calls
`_execute_and_finalize`. `resume_qa_background` wraps it in a daemon thread,
mirroring `start_qa_background`.

### R3 — TUI detects and resumes orphaned runs
`poll_qa_state` (`pm_core/tui/qa_loop_ui.py`) keeps its in-memory completion
handling and now also calls `_resume_incomplete_qa(app)` each tick.
`_resume_incomplete_qa` scans `~/.pm/workdirs/qa/*/qa_resume.json` (cheap glob;
project data loaded lazily only when a candidate is found) and, for each run
not in `app._qa_loops` and not in `app._resumed_qa_pr_ids`, whose PR is still
`status == "qa"`:
- **Completed during downtime** (`qa_status.json` has `overall`): build the
  state, set `latest_verdict = overall`, run `_on_qa_complete`, and
  `clear_resume_file`. (Daemon wrote the verdict but the TUI died before
  processing it.)
- **Still incomplete** (no `overall`): build the state, register it in
  `app._qa_loops`, and `resume_qa_background(...)`. The resumed loop completes
  through the normal in-memory `poll_qa_state` path.

### R4 — Snapshot lifecycle keeps it from re-firing
`qa_resume.json` exists ⇔ "this run still needs TUI attention." It is removed:
- by `poll_qa_state` when an in-memory run finishes and is dropped
  (`_ui_complete_notified` branch → `clear_resume_file(state.qa_workdir)`),
- by `_resume_incomplete_qa` after processing a completed-during-downtime run.

So a fully processed run leaves no snapshot, and a subsequent restart will not
re-process it. `app._resumed_qa_pr_ids` additionally dedupes within a session.

## Implicit Requirements

- **IR1 — Scenario windows outlive the TUI.** They live in the pm tmux session
  (separate from the TUI client), so a TUI restart leaves them running and
  `get_pm_session()` still resolves on resume. (If the whole tmux server is
  gone, `resume_qa_sync` returns `ERROR` early — nothing to resume.)
- **IR2 — `session_id` drives the hook gate.** `_poll_tmux_verdicts` marks any
  scenario without a `session_id` as `INPUT_REQUIRED`; persisting/restoring it
  is what lets resumed scenarios be polled rather than abandoned. It is also
  derivable from the transcript (`session_id_from_transcript`) as a fallback.
- **IR3 — Atomic, tolerant IO.** Both `qa_status.json` and `qa_resume.json` use
  tmp+rename; every reader (`_load_resume_file`, `_resume_incomplete_qa`)
  swallows `FileNotFoundError` / `JSONDecodeError` / `OSError` and retries next
  tick.
- **IR4 — Resume runs on the TUI thread.** `_resume_incomplete_qa` is invoked
  from the poll timer, so `_on_qa_complete` is called synchronously (same as
  the in-memory path); the resumed daemon's `on_update` marshals back via
  `call_from_thread`.
- **IR5 — Idempotent completion.** A resumed run completes through the in-memory
  path's `_on_qa_complete` (guarded by `_ui_complete_notified`); the
  completed-during-downtime path guards via the snapshot removal +
  `_resumed_qa_pr_ids`.

## Ambiguities (resolved)

- **A1 — Relocate vs resume.** Resolved in favor of resume-on-restart. The
  status pane lacks the launch/container/hook context the orchestration loop
  needs, so collection cannot move there on master.
- **A2 — One snapshot file vs overloading `qa_status.json`.** Resolved: a
  separate `qa_resume.json`. `qa_status.json` stays the lean display contract
  that `qa_status.py` renders; the verbose runtime state lives in the sidecar.
- **A3 — When to delete the snapshot.** Resolved: on TUI processing of the
  completion (not at daemon exit), so a daemon that finishes just before the
  TUI dies is still recoverable on the next restart.

## Edge Cases

- **EC1 — Interrupted during planning/launch** (before the first snapshot):
  not resumable; the half-planned run is abandoned (planning is cheap, restart
  re-plans). Accepted limitation.
- **EC2 — Scenario window died while the TUI was down**: handled by the
  existing `_poll_tmux_verdicts` relaunch/backoff path (worktrees/containers
  persist), eventually `INPUT_REQUIRED` if exhausted — same as the live loop.
- **EC3 — `verification_failures` not persisted**: resets to 0 on resume, so a
  scenario mid-verification may get a few extra verification attempts. Minor;
  accepted (verdicts and `verified_scenarios` *are* persisted).
- **EC4 — PASS without auto-start leaves status `qa`**: the snapshot is removed
  on processing, so it is not re-processed across restarts even though the
  status stays `qa`.
- **EC5 — Grace period resets on resume**: the resumed loop re-applies the 30s
  content-poll grace, delaying verdict acceptance briefly after restart.
  Accepted.
- **EC6 — pr-b59f0c7 overlap (verdict reasons)**: already landed on master;
  `scenario_verdict_reasons` is persisted/restored in the snapshot.

## Tests

`tests/test_qa_resume.py` (11 tests): snapshot round-trip incl. scenario
runtime fields/verdicts/reasons/verified/finalize; `clear_resume_file`;
`_resume_incomplete_qa` re-spawn (incomplete), process+clear (completed), skip
non-qa PR, skip already-tracked / already-recovered, no-op without qa root; and
`poll_qa_state` clearing the snapshot on in-memory completion. The orphaned
`tests/test_qa_status.py` (old `VerdictPoller`) was removed in the merge.

Full suite: 2369 passed (1 pre-existing, unrelated failure in
`tests/test_hook_events.py::test_installer_writes_standalone_receiver`, which
fails identically on the merge base — a hook-receiver install/env artifact,
out of scope for this PR).
