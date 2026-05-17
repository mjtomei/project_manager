# QA Spec: Container Memory Governor

PR: pr-eb2dbfc — "Container memory governor: dynamic memory limits with per-type stop policy and QA queuing"

## 1. Requirements

### R1: CLI settings for memory governor

**Expected behavior:** `pm container set` accepts all new keys and validates inputs:
- `system-memory-target <value>` — parsed as memory value (e.g. "48g"), stored in global settings
- `system-memory-scope pm|system` — only accepts "pm" or "system"
- `system-memory-default-projection <value>` — parsed as memory value
- `system-memory-history-size <N>` — positive integer only
- `stop-idle-impl on|off`, `stop-idle-review on|off`, `stop-idle-qa on|off` — only "on" or "off"
- `pm container status` displays all governor settings and current memory usage

**Code paths:** `pm_core/cli/container.py:container_set()` (line 98), `container_status()` (line 37)

### R2: Memory projection and gate check

**Expected behavior:** Before launching a container, the governor checks `current_used + projected_new <= target`. If the check fails, the launch is blocked with a descriptive error.
- Projection uses rolling average of historical peak memory samples per container type
- Fallback cascade: historical samples > default-projection setting > per-container memory-limit
- When no target is configured, all launches are allowed (governor inactive)
- When memory measurement fails, launches are allowed (graceful degradation)
- Concurrent launch attempts are serialized via lock

**Code paths:** `pm_core/memory_governor.py:check_launch()` (line 480), `project_memory()` (line 432), `pm_core/container.py:wrap_claude_cmd()` (line 768)

### R3: Stop-on-idle per container type

**Expected behavior:** When stop-on-idle is enabled for a container type:
- QA scenarios (default: on): container removed after PASS-verified or NEEDS_WORK verdict, NOT on INPUT_REQUIRED
- Impl (default: off): container removed after idle detection fires and no interactive prompt detected
- Review (default: off): container removed after review loop completes (not on INPUT_REQUIRED), or after standalone review goes idle

**Code paths:**
- QA: `pm_core/qa_loop.py:_poll_tmux_verdicts()` lines 1681, 1703, 1882
- Impl: `pm_core/tui/review_loop_ui.py:_poll_impl_idle()` line 708
- Review loop: `pm_core/review_loop.py:run_review_loop_sync()` line 427
- Review standalone: `pm_core/tui/review_loop_ui.py:_poll_impl_idle()` line 725

### R4: Memory stats tracking

**Expected behavior:** Memory usage is captured at container end-of-life (before `docker rm -f`):
- Stats recorded to `~/.pm/container-stats.json` with memory_mb, age_minutes, recorded_at
- Rolling window trimmed to history-size (default 20) per type
- Container type inferred from name (`pm-*-impl`, `pm-*-review-*`, `pm-*-qa-*-s{N}`, `pm-*-qa-planner`)
- Stats capture failure does not block container removal

**Code paths:** `pm_core/memory_governor.py:capture_and_record()` (line 530), `pm_core/container.py:remove_container()` (line 654)

### R5: QA launch gating with queuing

**Expected behavior:** QA planner computes how many scenarios fit in memory and queues the rest:
- `concurrency_cap` is further constrained by available memory headroom
- When zero scenarios fit, all are queued and retried in the poll loop
- `_launch_next_queued()` checks the memory gate before launching each queued scenario
- Queued scenarios waiting for memory show `waiting_memory` status (magenta) in QA status pane

**Code paths:** `pm_core/qa_loop.py:run_qa_sync()` line 2524, `_poll_tmux_verdicts()` line 1601

### R6: TUI status bar memory display

**Expected behavior:** Status bar shows `34G/48G (pm)` or `52G/56G (sys)` when a target is configured. Empty when no target set.

**Code paths:** `pm_core/memory_governor.py:format_memory_status()` (line 560), `pm_core/tui/widgets.py:StatusBar.update_status()`, `pm_core/tui/app.py` line 562

### R7: Tmux pane preservation on stop-on-idle

**Expected behavior:** When stop-on-idle stops a container, `remain-on-exit` is set on all affected tmux panes before the container is removed. This preserves the session scrollback text in the pane even after the `docker exec` process dies.
- QA scenario panes (concretizer, worker, verification) remain visible after stop
- Impl pane stays visible after idle detection
- Review pane stays visible after review completion

**Code paths:** `pm_core/container.py:stop_container()` (line 680), `pm_core/tmux.py:set_pane_option()` (line 449)

## 2. Setup

### Environment requirements
- Docker available and running
- tmux available
- pm installed (`pip install -e .` from project_manager clone)
- A test project initialized with `pm init`

### Configuration steps
1. Enable container mode: `pm container enable`
2. Set memory target: `pm container set system-memory-target 48g`
3. Configure stop-on-idle as needed for the test: `pm container set stop-idle-qa on`
4. Optionally seed stats file: write sample data to `~/.pm/container-stats.json`

### For manual TUI testing
- Follow the TUI Manual Testing instruction to create a throwaway project
- Start a pm session: `pm session`
- Use `pm tui view` to inspect TUI state

## 3. Edge Cases

### E1: Single container projection exceeds target
When the projected memory for a single container exceeds the target (e.g. projection=16G, target=12G), `check_single_container_fits()` should return a clear error rather than entering an infinite wait loop.

### E2: All QA scenarios memory-blocked
When zero scenarios fit in memory at QA launch time, all should be queued with `waiting_memory` status. The poll loop should retry periodically and launch them as memory becomes available.

### E3: INPUT_REQUIRED prevents memory reclamation
Scenarios stuck on INPUT_REQUIRED hold their containers alive, potentially starving queued scenarios of memory. The system should not deadlock — the user must manually resolve INPUT_REQUIRED.

### E4: Race between concurrent launches
Multiple QA scenarios launching simultaneously should be serialized by `_gate_lock` so they don't all pass the gate check at once.

### E5: Stats file corruption
Corrupt `container-stats.json` (invalid JSON) should be handled gracefully — log a warning, return empty stats, don't crash.

### E6: Docker stats unavailable
If `docker stats` fails (timeout, Docker down), the gate check should allow the launch rather than blocking it.

### E7: Memory target changed mid-QA-run
Changing the target while QA is running should take effect on the next gate check cycle without requiring restart.

### E8: Container type inference for unusual names
Names that don't match known patterns should return `None` from `infer_container_type()` — no crash, no stats recorded.

### E9: History trimming
When samples exceed `history-size`, only the newest N samples should be kept.

### E10: Pane preservation with multiple panes per container
QA scenario containers have up to 3 panes (concretizer, worker, verification). All must get `remain-on-exit` set before the container is removed.

## 4. Pass/Fail Criteria

### Pass
- All unit tests in `tests/test_memory_governor.py` pass
- CLI settings are validated correctly (rejects invalid values)
- Gate check blocks launches when budget is exceeded
- Gate check allows launches when budget permits
- QA scenarios are correctly queued when memory is insufficient
- Queued scenarios show `waiting_memory` status in QA status pane
- Stop-on-idle correctly removes containers after session completion per type
- Stop-on-idle does NOT remove containers during INPUT_REQUIRED
- Stop-on-idle does NOT remove containers during active verification
- Memory stats are recorded before container removal
- Stats file is written atomically (temp + rename)
- Governor is inactive when no target is configured
- Graceful degradation when Docker stats unavailable
- TUI status bar displays memory usage when target is set
- Tmux panes remain visible (with scrollback) after stop-on-idle

### Fail
- Any unit test failure
- Launch blocked when no memory target is configured
- Launch blocked when Docker stats fails (should allow)
- Container stopped while INPUT_REQUIRED verdict is active
- Container stopped while verification is in progress
- Stats file corruption on concurrent writes
- QA scenarios permanently stuck in waiting_memory (no retry)
- CLI accepts invalid values for settings (e.g. stop-idle-impl=maybe)
- TUI crash when importing memory_governor

## 5. Ambiguities

### A1: "Stop" vs "Remove" semantics
**Ambiguity:** The PR description says "docker stopped (not removed)" but the implementation uses `remove_container()` (docker rm -f) instead of `docker stop`.
**Resolution:** The implementation chose removal over stopping because the workdir is bind-mounted from the host — all project state survives removal. Container-internal ephemeral state (like running processes) is lost either way with `docker stop`. Removal is cleaner because it doesn't leave stopped containers cluttering `docker ps -a`, and avoids the complexity of `docker start` reuse (push proxy restart, setup sentinel, tmpfs clearing). QA tests should verify that containers are REMOVED (not just stopped) and that workdir state is preserved.

### A2: Scope of "waiting_memory" detection in poll loop
**Ambiguity:** Should `waiting_memory` be displayed only when the memory governor is the blocking factor, or also when concurrency cap limits launches?
**Resolution:** `waiting_memory` is only shown when the memory gate check fails. Scenarios waiting for a concurrency slot show plain `queued`. The code distinguishes these by running `check_launch("qa_scenario")` and marking the queue as memory-waiting only when it returns False.

### A3: Retry timing for memory-waiting scenarios
**Ambiguity:** How frequently should memory-waiting scenarios be retried?
**Resolution:** They are retried on each `_poll_tmux_verdicts` cycle (every ~2 seconds). When a scenario finishes and frees memory (via stop-on-idle), `_launch_next_queued()` is called immediately in the same cycle. There is also a periodic retry for the case where all pending scenarios are done but queue items remain.

### A4: Review stop-on-idle for standalone reviews
**Ambiguity:** Standalone reviews (plain `d` key) have no explicit completion detection — only idle detection.
**Resolution:** The implementation hooks into `_poll_impl_idle()` which also tracks `in_review` PR panes. When a standalone review pane goes idle (30s no output, no interactive prompt), stop-on-idle fires. This is tracked under a separate key (`review:{pr_id}`) from the impl pane.

## 6. Mocks

### MOCK: docker-stats
**Dependency:** Docker daemon (`docker stats`, `docker inspect`, `docker ps`)
**Contract:** Simulates Docker CLI responses for memory measurement:
- `docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}'` → returns tab-separated name and memory for each running pm container (e.g. `pm-impl\t4.1GiB / 8GiB`)
- `docker stats --no-stream --format '{{.MemUsage}}' <name>` → returns memory for a single container (e.g. `5.2GiB / 8GiB`)
- `docker inspect --format '{{.State.StartedAt}}' <name>` → returns ISO timestamp (e.g. `2026-04-07T14:30:00.123456789Z`)
- `docker ps --filter name=pm- --format '{{.Names}}'` → returns names of running pm containers
**Scripted responses:** Vary per scenario to test different memory states (under budget, over budget, zero containers, etc.)
**What remains unmocked:** The memory governor's internal logic (projection, gate check, stats persistence) runs with real code against mocked Docker output.

### MOCK: container-stats-file
**Dependency:** `~/.pm/container-stats.json` filesystem
**Contract:** Uses `tmp_path` fixture to redirect stats persistence to a temporary directory. Allows testing stats read/write/trim without touching the real stats file.
**What remains unmocked:** JSON serialization, atomic write (temp + rename), rolling window logic.

### MOCK: global-settings
**Dependency:** `~/.pm/settings/` files (via `get_global_setting_value` / `set_global_setting_value`)
**Contract:** Patches `get_global_setting_value` to return test-controlled values for memory target, scope, projection defaults, stop-idle policies.
**What remains unmocked:** Setting validation in CLI (`container_set`), memory unit parsing.

### MOCK: tmux-panes
**Dependency:** tmux server (pane listing, option setting)
**Contract:** Mocks `tmux.set_pane_option()`, `tmux.find_window_by_name()`, `tmux.get_pane_indices()` for testing pane preservation without a running tmux server.
**What remains unmocked:** The `stop_container()` logic that calls these functions.
