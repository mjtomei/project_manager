# Implementation Spec: Batched QA Scenario Execution

## 1. Requirements

### 1.1 Batched Worker Configuration
- Add a new global setting `qa-worker-count` (integer) that controls how many worker sessions are spawned for QA execution.
  - `-1` (default): The planner decides how many worker groups to create based on scenario relationships. Scenarios are grouped by shared context (functional area, files, theme).
  - `0`: Disabled — one session per scenario (legacy behavior).
  - `>0`: Fixed number of worker sessions — scenarios are grouped into exactly this many batches.
- The setting is read via `_get_worker_count()` in `pm_core/qa_loop.py`, following the same pattern as `_get_max_scenarios()` (reads from `pm_core.paths.get_global_setting_value`).
- Registered in `pm_core/cli/__init__.py`: added to `_INT_SETTINGS`, `_SETTING_DEFAULTS` (default `"-1"`), and the `set_cmd` help text.

### 1.2 Scenario Grouping by Shared Context
- When batching is enabled (`worker_count != 0`), the planner prompt (`pm_core/prompt_gen.py:generate_qa_planner_prompt()`) is extended to ask the planner to output a `GROUP: <N>` field per scenario, where N is the worker index (1-based).
- When `worker_count == -1`, the planner is told to decide the number of groups itself. When `worker_count > 0`, groups are capped at that value.
- The planner is instructed to group scenarios that share functional area, related files, or test theme together to maximize shared context within each worker.
- `parse_qa_plan()` in `pm_core/qa_loop.py` is extended to parse the optional `GROUP` field and store it on `QAScenario.group` (new field, default `None`).
- If the planner doesn't produce valid GROUP assignments, scenarios are distributed round-robin across workers as a fallback. When `worker_count == -1` and no groups are assigned, defaults to 1 worker.

### 1.3 Worker Session Architecture (three panes per worker window)
- Each worker has its own tmux window (`qa-{display_id}-w{N}`) and its own clone of the repo (via `create_scenario_workdir`), shared across all its scenarios.
- The window is created **immediately at launch**, before any concretization, and hosts three independent Claude sessions in three panes:
  1. **Concretizer pane** — one persistent Claude session that refines scenario steps serially. The initial prompt concretizes scenario 1; follow-up messages ("concretize scenario N") trigger the next refinement. Output is bracketed by `REFINED_STEPS_START` / `REFINED_STEPS_END` markers, same format as today's external concretizer. Refinements are pipelined with evaluation (see §1.5).
  2. **Evaluator pane** — the worker Claude session that reviews the diff, loads files once, and runs scenarios sequentially. Its initial prompt embeds only scenario 1's refined steps. Subsequent scenarios arrive inline in `PROCEED TO SCENARIO N` messages carrying the refined steps for N.
  3. **Verifier pane** — a Claude session that runs per-scenario verification against the evaluator's output, matching the pre-batched verification behavior (one verifier session kept alive across scenarios, prompted per scenario to verify the latest PASS verdict).
- A new prompt generator `generate_qa_worker_prompt()` produces the evaluator's initial prompt for scenario 1 only; a sibling `generate_qa_worker_proceed_message()` produces the `PROCEED TO SCENARIO N` follow-up. Concretizer and verifier reuse / adapt the existing prompt generators.

### 1.4 Per-Scenario Report Files
- Each worker writes a per-scenario report to `{qa_workdir}/report-s{scenario_index}.md` after completing each scenario.
- The report contains: scenario title, verdict, summary of findings, any issues found.
- The worker prompt instructs the agent to write this file before outputting its verdict.
- Report file path is tracked in a new field `QAScenario.report_path`.

### 1.5 Per-Scenario Verdict Detection and Pipelined Proceed
- The verdict polling loop (`_poll_worker_verdicts`) watches the **evaluator pane** of each worker for `SCENARIO_N_VERDICT: PASS|NEEDS_WORK|INPUT_REQUIRED` lines.
- After detecting a scenario verdict, the orchestrator:
  - Records the verdict in `state.scenario_verdicts[N]` and updates the status file.
  - If PASS and verification is enabled, sends the verification prompt to the **verifier pane** and waits for its verdict. Verification failure causes a re-evaluation message to the evaluator pane (existing behavior, unchanged semantics).
  - For accepted PASS or NEEDS_WORK: waits until the concretizer pane has emitted `REFINED_STEPS_END` for scenario N+1 (it should already be running in parallel — see below), extracts those refined steps, and sends `PROCEED TO SCENARIO N+1` to the evaluator pane with the refined steps embedded inline. Then immediately sends `concretize scenario N+2` to the concretizer pane to keep the pipeline one step ahead of the evaluator.
  - For INPUT_REQUIRED: leaves the evaluator pane blocked for human input (same as today).
- Pipeline invariant: concretization of scenario N+1 is kicked off as soon as the evaluator *starts* scenario N (i.e., right after its `PROCEED TO SCENARIO N` send). The worst case — concretizer slower than evaluator — means the orchestrator blocks briefly waiting for `REFINED_STEPS_END` before sending the next PROCEED; this is fine, it just collapses back to serial.

### 1.6 Worker Stops on INPUT_REQUIRED
- When a worker outputs INPUT_REQUIRED for any scenario, it stops and waits for human input, just as individual scenario sessions do today.
- The orchestrator does NOT send "proceed" — the worker stays blocked until the user interacts.
- After the user resolves the issue and the worker produces a new verdict, polling resumes normally.

### 1.7 QA Status Watcher Compatibility
- `_write_status_file()` continues to write per-scenario entries in `qa_status.json`, regardless of whether scenarios run individually or in batched workers.
- The `qa_status.py` TUI dashboard works unchanged — it reads per-scenario entries from the status file.
- When the user presses Enter on a scenario in the status dashboard, it navigates to the worker window containing that scenario (the `window_name` field on the scenario points to the worker window).

### 1.8 Concretization in Batched Mode (in-window, serial, pipelined)
- Concretization runs inside the worker window's **concretizer pane**, not in temporary external `conc-w*-s*` windows (those are removed).
- One Claude session per worker handles all of that worker's scenarios serially. The initial prompt refines scenario 1; follow-up messages refine subsequent scenarios. Refined output uses the existing `REFINED_STEPS_START` / `REFINED_STEPS_END` markers so the orchestrator can extract each scenario's steps from the pane after each follow-up.
- The concretizer is launched in parallel with the evaluator/verifier: as soon as scenario 1's refined steps are available, the evaluator pane is started (with scenario 1 embedded) and the concretizer is immediately prompted for scenario 2. This pipelines concretize(N+1) with evaluate(N).
- Concretization still happens per-scenario (one at a time within a worker), but the session is reused across scenarios within the worker so instruction-file loading and diff review are amortized.

### 1.9 Backward Compatibility
- When `qa-worker-count` is 0, the existing behavior is preserved exactly: one session per scenario, each in its own tmux window.
- The default (`-1`) enables batched mode with planner-decided grouping, which is the new standard behavior.
- The `qa-max-scenarios` concurrency cap still applies: it limits how many workers (not scenarios) run concurrently when batching is enabled.

## 2. Implicit Requirements

### 2.1 Evaluator Prompt Content
- The evaluator's **initial** prompt includes: diff context, workdir paths, PR notes, mocks, the scenario list headers (so the evaluator knows how many to expect and their titles), and the **refined steps for scenario 1 only**.
- Subsequent scenarios arrive via `PROCEED TO SCENARIO N` follow-ups that carry N's refined steps inline. The evaluator prompt explicitly documents this contract so the model doesn't try to act on later scenarios until it sees the message.

### 2.2 Report File Atomicity
- Report files should be written atomically (write to tmp, rename) to avoid partial reads by the status watcher.

### 2.3 Transcript Per Pane
- Each of the three panes (concretizer, evaluator, verifier) is its own Claude session and therefore gets its own transcript file. `QAScenario.transcript_path` for batched scenarios points to the **evaluator** transcript (the primary record). Concretizer and verifier transcripts live alongside it with distinct suffixes and are available for debugging but not surfaced in the TUI.

### 2.4 Push Conflict Handling
- Multiple workers may try to push fixes to the same PR branch. The worker prompt must include the pull-rebase-push retry pattern (already in `generate_qa_child_prompt`).

### 2.5 Window Naming
- Worker windows use `qa-{display_id}-w{N}` (e.g., `qa-#116-w1`) to distinguish from individual scenario windows (`qa-#116-s{N}`).
- All scenarios assigned to worker N share that window_name.

### 2.6 Scenario 0 Unchanged
- Scenario 0 (interactive session) is unaffected by batching — it always runs in its own window as today.

## 3. Ambiguities

### 3.1 Verdict Format for Batched Workers
**Resolution**: Workers use `SCENARIO_N_VERDICT: <verdict>` format (e.g., `SCENARIO_3_VERDICT: PASS`) so the orchestrator can distinguish which scenario the verdict belongs to. The worker prompt clearly instructs this format. After all scenarios in a worker complete, the worker session ends naturally.

### 3.2 Verification in Batched Mode
**Resolution**: Verification runs per-scenario in the worker window's dedicated **verifier pane** (a persistent Claude session, like the concretizer). When the evaluator outputs `SCENARIO_N_VERDICT: PASS`, the orchestrator sends a verify-this-scenario prompt to the verifier pane, waits for its verdict, and either accepts (triggers pipelined PROCEED) or rejects (sends a re-evaluation message to the evaluator pane, same as today's verification-failure recovery).

### 3.3 Interaction Between `qa-worker-count` and `qa-max-scenarios`
**Resolution**: When batching is enabled, `qa-max-scenarios` limits the number of concurrent workers (not scenarios). If `qa-worker-count=4` and `qa-max-scenarios=2`, only 2 workers run at a time, with the other 2 queued. This provides consistent behavior — the concurrency cap always limits the number of tmux windows/sessions.

### 3.4 Worker Failure (Window Dies)
**Resolution**: If a worker window dies, the existing retry logic (`_relaunch_scenario_window`) applies to the worker window. The relaunched worker resumes from the last unfinished scenario (those without a verdict in `state.scenario_verdicts`). The worker prompt includes only remaining scenarios on relaunch.

### 3.5 Concretization Strategy
**Resolution (updated 2026-04-13)**: Concretization runs inside the worker window in a dedicated **concretizer pane** (one persistent Claude session per worker), serially across that worker's scenarios via follow-up messages. The worker window is created immediately at launch so the concretizer has a home; the evaluator and verifier panes are created in the same window once scenario 1's refined steps are ready. Concretize(N+1) is kicked off as soon as evaluate(N) starts, so the two pipeline. No temporary `conc-w*-s*` windows.

## 4. Edge Cases

### 4.1 Single Scenario Worker
- If `qa-worker-count >= total_scenarios`, some workers may have only 1 scenario. This is fine — the worker prompt and verdict format work the same way, just with a single scenario.

### 4.2 Zero Scenarios
- If the planner produces no scenarios, the existing error handling applies regardless of batching.

### 4.3 All Scenarios in One Worker
- If `qa-worker-count=1`, all scenarios go to a single worker. This is the extreme batching case — maximum context sharing, minimum parallelism.

### 4.4 Mixed Verdicts Within a Worker
- A worker may produce PASS for scenario 1 and NEEDS_WORK for scenario 2. Each verdict is tracked independently. The overall QA verdict follows the existing aggregation logic (NEEDS_WORK > INPUT_REQUIRED > PASS).

### 4.5 Verification Failure Causes Worker Re-evaluation
- If verification flags a scenario's PASS, the follow-up message is sent to the worker pane. The worker re-evaluates that specific scenario. The "proceed to next" message is only sent after the re-evaluation produces an accepted verdict.

### 4.6 Container Mode
- Batched workers in container mode: each worker gets one container with its clone. The container launch logic in `_launch_scenarios_in_containers` is adapted to create one container per worker instead of one per scenario.

### 4.7 Report File Not Written
- If the worker fails to write a report file (e.g., crashes mid-scenario), the status watcher falls back to showing only the verdict from `qa_status.json`. The report file is optional enrichment, not a hard dependency.
