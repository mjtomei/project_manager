# Spec: QA verdict collection survives TUI restart (pr-4a89e52)

## Problem

QA scenario verdict polling ran in a **daemon thread inside the TUI process**:
`start_qa_background` (in `pm_core/tui/qa_loop_ui.py`) spawns a daemon thread
running `run_qa_sync` (`pm_core/qa_loop.py`), which previously called
`_poll_tmux_verdicts`. That function captured each scenario's tmux pane,
extracted verdicts, and wrote them to `qa_status.json`.

Because the poller lived in the TUI process, a TUI restart killed the daemon
threads and lost `app._qa_loops`. The scenario tmux panes kept running to
completion, but **nobody collected their verdicts or updated
`qa_status.json`**, so the TUI never observed completion and never triggered
the QA lifecycle transitions (merge / back-to-review).

## Requirements (grounded in code)

### R1 — Move verdict polling out of the TUI process into `qa_status.py`
The verdict-collection logic must run inside the `qa_status.py` process that
already executes in the QA **status pane** (launched at
`pm_core/qa_loop.py:999-1005` via
`python3 .../qa_status.py <status_path> <session>` split into the main QA
window). That pane's lifetime is independent of the TUI, so verdict
collection survives TUI restarts.

Implemented as `VerdictPoller` in `pm_core/qa_status.py:157`, invoked once per
refresh cycle from both `_run_interactive` (`:462`) and `_run_passive`
(`:513`). Each `poll(status)` call:
- Skips when `status is None` or an `overall` verdict already exists.
- Iterates `status["scenarios"]`, skipping `interactive` (scenario 0),
  already-completed, and window-less entries.
- Resolves the scenario's tmux pane via `_find_claude_pane(session,
  window_name)`; if the window is gone, records `INPUT_REQUIRED`.
- Captures the pane (`_capture_pane`) and extracts a verdict
  (`_extract_verdict` over the last `_VERDICT_TAIL_LINES=30` lines, matching a
  bare `PASS` / `NEEDS_WORK` / `INPUT_REQUIRED` line via `_match_verdict`).
- Requires `_STABILITY_POLLS=2` consecutive identical detections
  (`_VerdictStabilityTracker`) before committing a verdict.
- When all non-interactive scenarios have a verdict, computes `overall`
  (NEEDS_WORK > INPUT_REQUIRED > PASS precedence) and writes it.
- Writes updates back atomically (`_write_status` → tmp file + `rename`).

### R2 — `qa_status.json` is the cross-process contract
The TUI seeds the file; `qa_status.py` takes over monitoring; the TUI reads it
back to detect completion.

- **Seeding**: `run_qa_sync` writes the initial `qa_status.json`
  (`_write_status_file`, `pm_core/qa_loop.py:1031`) after launching scenarios
  and the status pane. The file contains `pr_id`, the `scenarios` list (each
  with `index`, `title`, `verdict`, `window_name`), and an empty `overall`.
  Scenario 0 (interactive) is seeded with `verdict: "interactive"` and is
  never polled.
- **Schema** (`_write_status_file`, `:279`): `{ "pr_id", "scenarios": [{
  "index", "title", "verdict", "window_name" }], "overall" }`. This schema is
  the shared contract — `VerdictPoller` reads/writes the same shape.

### R3 — TUI no longer polls tmux panes itself
`run_qa_sync` must stop calling `_poll_tmux_verdicts` and instead wait on the
status file. Implemented as `_wait_for_verdicts_via_status_file`
(`pm_core/qa_loop.py:686`), which polls `qa_status.json` every `_POLL_INTERVAL`
seconds, mirrors per-scenario verdicts into `state.scenario_verdicts` (firing
`_notify()` on change), and returns once `overall` is set (assigned to
`state.latest_verdict`). The old `_poll_tmux_verdicts`,
`_relaunch_scenario_window`, retry/backoff machinery, and the final
aggregate-and-write block in `run_qa_sync` are removed (overall is now
computed by `qa_status.py`).

### R4 — TUI detects completion and drives lifecycle, surviving restart
`poll_qa_state` (`pm_core/tui/qa_loop_ui.py:254`) runs on the shared poll
timer and must handle two cases:
1. **Normal flow** — in-memory `app._qa_loops`: when a state is not running and
   has a `latest_verdict`, call `_on_qa_complete` once
   (guarded by `state._ui_complete_notified`).
2. **Restart recovery** — `_recover_completed_qa_from_disk` (`:274`) scans
   `~/.pm/workdirs/qa/*/qa_status.json` for files with an `overall` verdict
   whose `pr_id` is **not** in `app._qa_loops`, builds a synthetic
   `QALoopState` (scenarios + verdicts + `latest_verdict=overall`,
   `running=False`), and feeds it through `_on_qa_complete`. A per-app
   `_recovered_qa_pr_ids` set prevents re-processing.

## Implicit Requirements

- **IR1 — `qa_status.py` runs standalone, no PYTHONPATH.** It is launched as a
  bare script in a tmux pane, so verdict helpers (`_find_claude_pane`,
  `_capture_pane`, `_extract_verdict`, `_VerdictStabilityTracker`) are
  **inlined** rather than imported from `pm_core.loop_shared` (see module
  docstring `:71-73`). Drift between the two copies is an accepted tradeoff;
  they must stay verdict-compatible.
- **IR2 — Atomic writes from two writers.** Both the TUI seed
  (`_write_status_file`) and `qa_status.py` (`_write_status`) write via
  tmp-file + `rename`, and readers tolerate `FileNotFoundError` /
  `JSONDecodeError` (mid-rename). The status pane is the only writer after
  seeding except the TUI's initial seed, so there is no last-writer-wins
  conflict in the steady state.
- **IR3 — Grace period.** `qa_status.py` applies `_VERDICT_GRACE_PERIOD=30s`
  before accepting *content-based* verdicts (`in_grace` check at `:205`), so a
  scenario that prints a verdict-looking line early isn't latched
  prematurely. Window-gone → `INPUT_REQUIRED` is **not** gated by grace
  (a missing window is unambiguous).
- **IR4 — Recovery only fires for PRs still in QA.** `_recover...` loads
  project data (lazily, only when a candidate is found) and skips PRs whose
  status is no longer `qa` (already transitioned), recording them in
  `_recovered_qa_pr_ids` so they aren't rechecked.
- **IR5 — Idempotent completion.** `_on_qa_complete` must run exactly once per
  completed run, whether via the in-memory path or the disk-recovery path
  (both set `_ui_complete_notified = True`).

## Ambiguities (resolved)

- **A1 — Who computes `overall`?** Resolved: `qa_status.py` computes and
  persists `overall`; the TUI only reads it. Removing the duplicate
  aggregation in `run_qa_sync` avoids two processes racing to set it.
- **A2 — Scenario retry/relaunch on dead windows.** The old poller relaunched
  dead scenario windows with exponential backoff. Resolved: dropped. A
  status-pane poller cannot recreate worktree/container-backed windows
  (it lacks the launch context), so a gone window now deterministically maps
  to `INPUT_REQUIRED`. This is a behavior change but keeps the cross-process
  contract simple; relaunch was best-effort and is out of scope for this fix.
- **A3 — Grace timer across restart.** `VerdictPoller._start_time` resets each
  time `qa_status.py` (re)starts. Resolved as acceptable: the status pane
  normally outlives the TUI, and a re-launched status pane re-applying a 30s
  grace only delays verdict acceptance slightly.

## Edge Cases

- **EC1 — TUI restarts mid-run, then again after completion.** First restart:
  `qa_status.py` keeps collecting; `_recover_completed_qa_from_disk` picks up
  the completed file on the next poll. Covered by `_recovered_qa_pr_ids`
  dedup.
- **EC2 — Window dies before any verdict.** `VerdictPoller` records
  `INPUT_REQUIRED` immediately (not grace-gated), so the run still reaches an
  `overall` rather than hanging.
- **EC3 — Scenario 0 (interactive).** Seeded with `verdict:"interactive"`,
  excluded from polling, from the `pending` set, and from
  recovery-synthesized scenarios.
- **EC4 — Status file missing/half-written.** All readers
  (`_load_status`, `_wait_for_verdicts_via_status_file`,
  `_recover_completed_qa_from_disk`) swallow `FileNotFoundError` /
  `JSONDecodeError` / `OSError` and retry on the next tick.
- **EC5 — Overlap with pr-b59f0c7 (reason strings).** Per PR notes,
  pr-b59f0c7 adds reason strings into the verdict shape persisted here.
  Coordination: the `scenarios[]` entry shape is the shared surface; a future
  `reason` field is additive and both writers must preserve unknown keys.
  (No code change required in this PR beyond not clobbering extra keys —
  current writers rebuild the dict from known fields, so a follow-up will need
  to thread `reason` through `_write_status_file` and `VerdictPoller`.)

## Status

Implementation already present on this branch (commit `1b4c8cea` + review-loop
follow-ups). `tests/test_qa_status.py` (19 tests) covers `VerdictPoller`,
verdict extraction, stability, and overall computation; all qa_loop /
qa_self_driving / qa_pane / qa_status suites pass locally.

### Outstanding (non-implementation)
The branch is **1152 commits behind master**. Per PR note (2026-04-24),
master PR #166 removed `PASS_WITH_SUGGESTIONS`, the `zzz` prefix, and the QA
strict/lenient distinction; `qa_loop_ui.py`'s docstring and some test
references still mention `zzz`/strict. A master merge will conflict and is
tracked as a follow-up decision, not part of the core verdict-collection fix.
