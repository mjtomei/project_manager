# QA Spec: Batched QA Scenario Execution

## 1. Requirements

### 1.1 Worker Count Setting
- New `qa-worker-count` setting registered in CLI (`_INT_SETTINGS`, `_SETTING_DEFAULTS`).
- Values: `-1` (planner decides, default), `0` (disabled/legacy), `>0` (fixed count).
- Read via `_get_worker_count()` in `qa_loop.py`.

### 1.2 Planner Prompt GROUP Field
- `generate_qa_planner_prompt()` accepts `worker_count` param.
- When `worker_count != 0`, the output format includes a `GROUP: <N>` field per scenario.
- When `worker_count == -1`, planner decides group count; when `>0`, groups capped at that value.
- `_worker_group_field()` and `_worker_grouping_instructions()` generate the prompt additions.

### 1.3 GROUP Parsing
- `parse_qa_plan()` parses optional `GROUP: <N>` field into `QAScenario.group`.
- STEPS regex updated to include GROUP as a field boundary.
- Missing GROUP defaults to `None`.

### 1.4 Scenario Grouping
- `group_scenarios_into_workers()` distributes scenarios into worker batches.
- Uses planner GROUP assignments when valid; falls back to round-robin for unassigned/out-of-range.
- When `worker_count == -1` and no groups assigned, defaults to 1 worker.
- Empty workers are removed from the result dict.
- Returns `{}` when `worker_count == 0` or no scenarios.

### 1.5 Worker Prompt Generation
- `generate_qa_worker_prompt()` creates a prompt for a batched worker session.
- Includes all assigned scenarios with steps, report paths, execution order.
- Instructs worker to output `SCENARIO_N_VERDICT: <verdict>` and wait for PROCEED.
- Includes push/pull instructions, workdir info, mocks, PR notes.

### 1.6 Worker Launch (tmux)
- `_launch_workers_in_tmux()` creates one clone per worker, concretizes all scenarios in parallel, then launches a single Claude session per worker.
- Worker windows named `qa-{display_id}-w{N}`.
- All scenarios in a worker share the same `window_name`, `pane_id`, `transcript_path`.
- Report paths set via `_scenario_report_path()`.

### 1.7 Worker Launch (containers)
- `_launch_workers_in_containers()` mirrors tmux logic but creates one container per worker.
- Instruction content read and stored per-scenario before clearing paths.

### 1.8 Verdict Polling for Workers
- `_extract_worker_verdicts()` parses `SCENARIO_N_VERDICT: <verdict>` from pane content.
- `_poll_worker_verdicts()` polls active workers, tracks per-scenario verdicts.
- Handles: PASS (with optional verification), NEEDS_WORK (advance), INPUT_REQUIRED (wait).
- Sends `PROCEED TO SCENARIO <N>` after verdict is accepted.
- Re-emitted verdicts detected via count tracking (`seen_verdicts`).
- Queued workers launched when active workers complete.
- Worker pane death marks remaining scenarios INPUT_REQUIRED.

### 1.9 Concurrency Cap
- `qa-max-scenarios` limits concurrent workers (not scenarios) in batched mode.
- Queued workers launched as active workers finish.

### 1.10 Status Pane Helper
- `_add_status_pane()` extracted as a reusable helper for both batched and standard modes.

### 1.11 run_qa_sync Integration
- `run_qa_sync()` branches on `worker_count != 0` for batched vs standard mode.
- Standard mode preserved exactly when `worker_count == 0`.

### 1.12 Stale Window Cleanup
- `_cleanup_stale_scenario_windows()` now also cleans `qa-{display_id}-w*` windows.

## 2. Setup

- Python environment with project installed (`pip install -e .`).
- Tests run via `pytest tests/test_qa_loop.py`.
- TUI manual testing requires a tmux session and throwaway project (see `tui-manual-test.md`).
- For integration-level tests, a real tmux session is needed.

## 3. Edge Cases

1. **worker_count >= total_scenarios**: Some workers get 1 scenario, empty workers removed.
2. **worker_count = 1**: All scenarios in one worker (max batching, no parallelism).
3. **Planner assigns no GROUP fields with worker_count=-1**: Falls back to 1 worker with all scenarios.
4. **GROUP values out of range**: Round-robined to least-loaded worker.
5. **Mixed verdicts in one worker**: Each tracked independently; NEEDS_WORK advances, INPUT_REQUIRED blocks.
6. **Worker pane dies**: All remaining (un-verdicted) scenarios marked INPUT_REQUIRED.
7. **Verification failure in worker**: Follow-up sent to worker pane, verdict cleared for re-emission.
8. **Re-emitted verdict after INPUT_REQUIRED resolution**: Detected via count tracking in `seen_verdicts`.
9. **Zero scenarios**: Returns empty from `group_scenarios_into_workers()`.
10. **Concurrency cap < worker count**: Only cap workers launched; rest queued.

## 4. Pass/Fail Criteria

- **Pass**: All unit tests pass. Planner prompt includes GROUP field when batching enabled. Scenarios correctly grouped. Worker prompt contains all scenario details. Verdict extraction handles all formats. Polling loop correctly advances workers. Standard mode unchanged when worker_count=0.
- **Fail**: Tests fail. GROUP field not parsed. Scenarios incorrectly grouped. Worker gets wrong prompt. Verdict detection misses patterns. PROCEED not sent. INPUT_REQUIRED doesn't block. Standard mode broken.

## 5. Ambiguities

### 5.1 Verification timing in batched workers
**Resolution**: Verification runs per-scenario. Worker waits after each verdict; orchestrator runs verification before sending PROCEED. This preserves the existing per-scenario verification flow.

### 5.2 Transcript sharing
**Resolution**: All scenarios in a worker share one transcript file (Claude's `--transcript` flag is per-session). The transcript path is set to the first scenario's index path.

### 5.3 Report atomicity
**Resolution**: Worker prompt instructs writing to `.tmp` then renaming. This is a prompt instruction, not enforced by the orchestrator.

## 6. Mocks

### External Dependencies

For unit/integration tests in this PR:

1. **tmux module** (`pm_core.tmux`): Mocked in tests. Key functions: `list_windows`, `kill_window`, `new_window_get_pane`, `capture_pane`, `pane_exists`, `send_keys`, `split_pane_at`, `pane_window_id`. Contract: simulate window/pane lifecycle without real tmux.

2. **Claude launcher** (`pm_core.claude_launcher`): Mocked `build_claude_shell_cmd` returns a shell command string. Not actually executed in unit tests.

3. **Global settings** (`pm_core.paths.get_global_setting_value`): Mocked to return test values for `qa-worker-count`, `qa-max-scenarios`.

4. **Container module** (`pm_core.container`): Mocked for container-mode tests. `create_qa_container`, `build_exec_cmd`, `load_container_config`.

5. **Pane layout** (`pm_core.pane_layout`): Mocked `register_and_rebalance`. Can fail silently.

For QA scenario agents: No real Claude sessions. Scenarios should test via unit tests, code reading, and the TUI manual test instruction where applicable. Agents should read code and verify logic rather than launching real tmux/Claude sessions.
