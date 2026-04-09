# Implementation Spec: Batched QA Scenario Execution

## 1. Requirements

### 1.1 Batched Worker Configuration
- Add a new global setting `qa-worker-count` (integer) that controls how many worker sessions are spawned for QA execution. Default: 0 (disabled, current behavior — one session per scenario).
- When `qa-worker-count` > 0, the planner's scenarios are grouped into that many batches instead of being launched as individual sessions.
- The setting is read via `_get_worker_count()` in `pm_core/qa_loop.py`, following the same pattern as `_get_max_scenarios()` (reads from `pm_core.paths.get_global_setting_value`).
- Registered in `pm_core/cli/__init__.py`: added to `_INT_SETTINGS`, `_SETTING_DEFAULTS` (default `"(unset)"`), and the `set_cmd` help text.

### 1.2 Scenario Grouping by Shared Context
- When batching is enabled, the planner prompt (`pm_core/prompt_gen.py:generate_qa_planner_prompt()`) is extended to ask the planner to output a `GROUP: <N>` field per scenario, where N is the worker index (1-based, up to `qa-worker-count`).
- The planner is instructed to group scenarios that share functional area, related files, or test theme together to maximize shared context within each worker.
- `parse_qa_plan()` in `pm_core/qa_loop.py` is extended to parse the optional `GROUP` field and store it on `QAScenario.group` (new field, default `None`).
- If the planner doesn't produce valid GROUP assignments (or batching is disabled), scenarios are distributed round-robin across workers as a fallback.

### 1.3 Worker Session Architecture
- Each worker is a single Claude session running in its own tmux window (`qa-{display_id}-w{N}` naming pattern).
- Each worker gets a single clone of the repo (via `create_scenario_workdir`), shared across all its scenarios.
- The worker's prompt includes the full list of its assigned scenarios with their refined steps, and instructs it to:
  1. Review the diff and load relevant files once
  2. Execute scenario 1, write a per-scenario report file, output the verdict
  3. Wait for approval (the orchestrator sends a "proceed" message after detecting the verdict)
  4. Execute scenario 2, write report, output verdict, wait... and so on
- A new prompt generator `generate_qa_worker_prompt()` is added to `pm_core/prompt_gen.py` that takes a list of `QAScenario` objects and the worker index.

### 1.4 Per-Scenario Report Files
- Each worker writes a per-scenario report to `{qa_workdir}/report-s{scenario_index}.md` after completing each scenario.
- The report contains: scenario title, verdict, summary of findings, any issues found.
- The worker prompt instructs the agent to write this file before outputting its verdict.
- Report file path is tracked in a new field `QAScenario.report_path`.

### 1.5 Per-Scenario Verdict Detection in Worker Panes
- The verdict polling loop (`_poll_tmux_verdicts`) is extended to detect per-scenario verdicts from worker panes.
- Workers output verdicts in the format: `SCENARIO_N_VERDICT: PASS|NEEDS_WORK|INPUT_REQUIRED` (where N is the scenario index).
- After detecting a scenario verdict, the orchestrator:
  - Records the verdict in `state.scenario_verdicts[N]`
  - Updates the status file
  - If the verdict is PASS and verification is enabled, runs verification
  - For PASS or NEEDS_WORK: sends a "proceed to next scenario" message to the worker pane
  - For INPUT_REQUIRED: leaves the worker waiting (same as current INPUT_REQUIRED behavior)
- New helper: `_poll_worker_verdicts()` that handles the sequential scenario-by-scenario polling within a single worker pane.

### 1.6 Worker Stops on INPUT_REQUIRED
- When a worker outputs INPUT_REQUIRED for any scenario, it stops and waits for human input, just as individual scenario sessions do today.
- The orchestrator does NOT send "proceed" — the worker stays blocked until the user interacts.
- After the user resolves the issue and the worker produces a new verdict, polling resumes normally.

### 1.7 QA Status Watcher Compatibility
- `_write_status_file()` continues to write per-scenario entries in `qa_status.json`, regardless of whether scenarios run individually or in batched workers.
- The `qa_status.py` TUI dashboard works unchanged — it reads per-scenario entries from the status file.
- When the user presses Enter on a scenario in the status dashboard, it navigates to the worker window containing that scenario (the `window_name` field on the scenario points to the worker window).

### 1.8 Concretization in Batched Mode
- When batching is enabled, concretization still runs per-scenario (not per-worker), because each scenario may reference different instruction files.
- Concretization runs in a temporary pane before the worker launches, same as today.
- All scenarios in a worker batch are concretized in parallel, then the worker is launched with the refined steps.
- Alternative: concretization could run inside the worker session as a first step. However, running it externally preserves the existing parallel concretization and keeps the worker prompt cleaner.

### 1.9 Backward Compatibility
- When `qa-worker-count` is 0 or unset, the existing behavior is preserved exactly: one session per scenario, each in its own tmux window.
- The `qa-max-scenarios` concurrency cap still applies: it limits how many workers (not scenarios) run concurrently when batching is enabled.

## 2. Implicit Requirements

### 2.1 Worker Prompt Must Include All Scenario Details
- The worker prompt must include the full refined steps for each scenario, the diff context, workdir paths, PR notes, and mocks — everything currently in `generate_qa_child_prompt()` but for multiple scenarios.

### 2.2 Report File Atomicity
- Report files should be written atomically (write to tmp, rename) to avoid partial reads by the status watcher.

### 2.3 Transcript Per Worker
- Each worker gets one transcript file (the Claude `--transcript` flag applies per-session). The transcript covers all scenarios in that worker.
- `QAScenario.transcript_path` for batched scenarios points to the worker's transcript.

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
**Resolution**: Verification still runs per-scenario. When a worker outputs `SCENARIO_N_VERDICT: PASS`, the orchestrator captures the pane content and runs verification for that scenario. The worker is told to wait after each verdict, giving the verification time to complete before the "proceed" message arrives.

### 3.3 Interaction Between `qa-worker-count` and `qa-max-scenarios`
**Resolution**: When batching is enabled, `qa-max-scenarios` limits the number of concurrent workers (not scenarios). If `qa-worker-count=4` and `qa-max-scenarios=2`, only 2 workers run at a time, with the other 2 queued. This provides consistent behavior — the concurrency cap always limits the number of tmux windows/sessions.

### 3.4 Worker Failure (Window Dies)
**Resolution**: If a worker window dies, the existing retry logic (`_relaunch_scenario_window`) applies to the worker window. The relaunched worker resumes from the last unfinished scenario (those without a verdict in `state.scenario_verdicts`). The worker prompt includes only remaining scenarios on relaunch.

### 3.5 Concretization Strategy
**Resolution**: Concretization runs externally (before worker launch), in parallel across all scenarios in the batch. This preserves the existing concurrent concretization pattern and avoids making the worker session responsible for concretization. The concretizer panes are created and polled as today, then killed before the worker launches in the same window.

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
