# Implementation Spec: Container Memory Governor

PR: pr-eb2dbfc — "Container memory governor: dynamic memory limits with per-type stop policy and QA queuing"

## 1. Requirements

### R1: Global memory target setting

**What:** A user-configurable maximum memory consumption target (e.g. `pm container set system-memory-target 48g`).

**Grounded in code:**
- `pm_core/cli/container.py:container_set()` (line 68) currently accepts `image`, `memory-limit`, `cpu-limit` via `click.Choice`. Must add `system-memory-target` to the choice list.
- Value stored via `pm_core/paths.py:set_global_setting_value("container-system-memory-target", value)` in `~/.pm/settings/container-system-memory-target`.
- Read back via `pm_core/paths.py:get_global_setting_value("container-system-memory-target", default)`.
- Additional settings:
  - `system-memory-scope` — what "current used" measures: `pm` (only pm containers via `docker stats`) or `system` (total system memory via `/proc/meminfo`). Default: `pm`. Example: `pm container set system-memory-scope system`.
  - `system-memory-default-projection` — override the fallback projection used when no historical data exists (e.g. `pm container set system-memory-default-projection 6g`). When unset, falls back to the per-container `memory-limit`.
  - `system-memory-history-size` — number of peak samples to keep per container type for the rolling average (e.g. `pm container set system-memory-history-size 10`). Default: 20. Lower values adapt faster to changing workloads; higher values smooth out outliers.

### R2: Memory projection before launch

**What:** Before launching any container, the governor checks: `current_used + projected_new <= target`. Projection uses a rolling average of peak memory per container type (`impl`, `review`, `qa_scenario`, `qa_planner`), observed from `docker stats` and persisted across sessions.

**Grounded in code:**
- Container creation goes through `pm_core/container.py:create_container()` (line 338) and `pm_core/container.py:create_qa_container()` (line 620). The governor gate must run before these calls.
- `docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}'` gives current memory per running container. Filter by `CONTAINER_PREFIX = "pm-"`.
- Historical stats persisted to `~/.pm/container-stats.json`.

### R3: Per-type stop-on-idle policy

**What:** Configurable per container type: `pm container set stop-idle-impl|stop-idle-review|stop-idle-qa on|off`. When enabled, containers of that type are `docker stop`ped (not removed) after their session completes. Stopped containers preserve filesystem overlay; `docker start` brings them back. Default: qa=on, impl=off, review=off.

**Grounded in code:**
- CLI: extend `pm_core/cli/container.py:container_set()` choices with `stop-idle-impl`, `stop-idle-review`, `stop-idle-qa`.
- Settings: `~/.pm/settings/container-stop-idle-{type}` (e.g. `container-stop-idle-qa`).
- Container stop: new `stop_container(name)` function in `pm_core/container.py` calling `docker stop <name>`.

**Session completion triggers differ per type — there is no single insertion point.** Each type has its own completion detection mechanism in a different loop/callback. All sessions that can run during QA are covered.

#### Impl containers
- **Detection:** Idle-based via `PaneIdleTracker.became_idle(key)`.
- **Where:** `review_loop_ui.py:_poll_impl_idle()` line 671.
- **Mechanism:** Pane content unchanged for 30s AND `content_has_interactive_prompt()` returns False.
- **Insertion point:** After the interactive prompt check (line 678). This is the same point that currently triggers auto-review. Add `stop_container(container_name)` call here, gated on `get_stop_idle_policy("impl")`.
- **Pane structure:** Single pane — the impl Claude session.
- **Note:** `content_has_interactive_prompt()` catches gum-style selection UIs but NOT Claude's own input cursor (`❯`). At the input cursor, the session is genuinely waiting — stopping is acceptable.

#### Review containers
- **Detection:** Two paths — reviews can run standalone (plain `d` key) or inside a review loop (`zz d`/`zzz d`).
- **Review loop path:** `review_loop.py:run_review_loop_sync()` line 426, where `state.running = False`. The loop calls `_run_claude_review()` per iteration, which launches a window and polls for a verdict. The loop exits when `should_stop()` returns True (PASS/PASS_WITH_SUGGESTIONS), stop is requested, or max iterations reached.
- **Standalone review path:** `cli/pr.py:_launch_review_window()` line 1081. This creates the review tmux window with Claude + a diff pane, but has **no completion detection** — the window stays alive until manually closed. For standalone reviews, idle detection (same as impl) is the only way to detect completion.
- **Insertion points:**
  1. **Loop:** At `run_review_loop_sync()` line 426 (`state.running = False`). Add `stop_container()` gated on `get_stop_idle_policy("review")`. Do NOT stop if the final verdict is INPUT_REQUIRED (user needs interaction).
  2. **Standalone:** Hook into `_poll_impl_idle()` — review windows are also tracked by `PaneIdleTracker`. When the review pane goes idle, the same idle-detection path applies. The key insight: `_poll_impl_idle()` already tracks both `in_progress` and `in_review` panes (line 647: `if status not in ("in_progress", "in_review"): continue`).
- **Pane structure:** Two panes — Claude review pane (left) + git diff shell pane (right, via `split_pane_at` in `_launch_review_window` line 1216). Both run on the host (diff pane is never containerized). Only the Claude pane is a `docker exec`. Stopping the container kills the Claude pane but the diff shell survives (it's a host process).

#### QA scenario containers — all panes enumerated
- **Detection:** Verdict-based. Per-scenario verdict polling in main QA poll loop.
- **Where:** `qa_loop.py:_poll_tmux_verdicts()` — multiple exit paths.
- **Mechanism:** `VerdictStabilityTracker` confirms verdict is stable for 2 consecutive polls.
- **Pane structure per scenario window (up to 3 panes, all `docker exec` into the SAME container):**
  1. **Concretizer pane** (created first, line 1251): Runs `_build_concretize_cmd()` via `docker exec`. Refines planned steps against actual code. Finishes early (outputs `REFINED_STEPS_END` marker). Stays open and inert for user inspection. Not polled for verdicts.
  2. **Worker pane** (created by `split_pane_at`, line 1322): Runs the actual QA scenario via `docker exec`. This is `scenario.pane_id`. **This is the only pane polled for verdicts.** Emits PASS/NEEDS_WORK/INPUT_REQUIRED.
  3. **Verification pane** (created later if PASS, line 2067): Split from worker pane via `split_pane_at`. Runs a Claude session that verifies the PASS verdict by reading the transcript. Emits VERIFIED or FLAGGED. **This pane is polled by the `_run_verification()` background thread, NOT by `_poll_tmux_verdicts`.** Left open after verification for user inspection (line 2115-2116).
- **All 3 panes are `docker exec` into the same container.** `docker stop` kills all of them simultaneously. This means we MUST NOT stop the container while verification is running (verification pane would die).
- **Insertion points (4 verdict exit paths):**
  1. **PASS + verification passes:** `_poll_tmux_verdicts()` line ~1631 — `completed_verifications` loop processes `passed=True`. All 3 panes are done. Safe to stop.
  2. **NEEDS_WORK (no verification):** line ~1819-1826 — verdict accepted, `_launch_next_queued()` called. Concretizer + worker done. No verification pane exists. Safe to stop.
  3. **INPUT_REQUIRED:** Do **NOT** stop. User needs the container alive. All panes remain accessible.
  4. **Verification fails, max retries exceeded → NEEDS_WORK:** line ~1644. All panes done. Safe to stop.
- **Do NOT stop on:**
  - **INPUT_REQUIRED** — user needs the container alive to interact with the worker pane.
  - **PASS entering verification** (line 1811) — verification pane is about to be created; container must stay running.
  - **Verification fails but retries remain** (line 1651-1691) — follow-up message sent to worker pane, scenario goes back to `pending`. All 3 panes need to stay alive.

#### QA planner container
- **Detection:** Marker-based. Polls pane for `QA_PLAN_END` marker.
- **Where:** `qa_loop.py:run_qa_sync()` line ~2341 (plan accepted) or line ~2346 (timeout/stop).
- **Insertion point:** After the planning phase exits (plan found or timeout). Add `stop_container()` call gated on `get_stop_idle_policy("qa")`.
- **Pane structure:** Two panes in the main QA window:
  1. **Planner Claude pane** — runs via `docker exec` (if container mode). Generates the QA plan.
  2. **Status dashboard pane** — runs `qa_status.py` on the host (NOT containerized). Reads `qa_status.json` and shows live scenario status.
  Stopping the planner container kills pane 1 but leaves the status dashboard alive (it's a host process).

#### QA verification
- **Not a separate container.** Verification runs as a split pane (`docker exec`) inside the existing scenario container. No separate stop needed — it's part of the scenario container lifecycle (see QA scenario pane 3 above).

#### Scenario 0 (interactive)
- **Not containerized.** Always runs on the host (line 892-893: "Scenario 0 always runs on the host"). Not subject to stop-on-idle. No governor interaction needed.

### R4: Memory stats tracking

**What:** Record memory consumption at container end-of-life (stop or removal), along with container age (how long it ran). Persist individual samples in `~/.pm/container-stats.json` across sessions so historical data survives restarts.

**Why end-of-life, not periodic polling:** A container's memory usage grows over its lifetime as caches fill, venvs build, node_modules expand, etc. The peak at end-of-life is the most representative data point for projecting what a new container of that type will eventually consume. Periodic samples during runtime capture intermediate states that underestimate true peak usage.

**Grounded in code:**
- New module: `pm_core/memory_governor.py` — central location for all governor logic.
- **Capture points:** Before every `docker stop` or `docker rm`, call `docker stats --no-stream --format '{{.MemUsage}}'` for that container to record its final memory. Integration points:
  - `container.py:remove_container()` (line 635) — called from cleanup, orphan removal, and container recreation paths.
  - New `container.py:stop_container()` — called by stop-on-idle triggers.
  - Both call `memory_governor.record_sample()` before the docker command.
- **Container age:** Derived from `docker inspect --format '{{.State.StartedAt}}'` at capture time. Age = now - started_at.
- Stats file format — individual samples with age, not just averages:
  ```json
  {
    "impl": {
      "samples": [
        {"memory_mb": 4200, "age_minutes": 45, "recorded_at": "2026-04-07T14:30:00Z"},
        {"memory_mb": 3900, "age_minutes": 120, "recorded_at": "2026-04-06T10:15:00Z"}
      ]
    },
    "qa_scenario": {
      "samples": [
        {"memory_mb": 5100, "age_minutes": 12, "recorded_at": "2026-04-07T15:00:00Z"},
        {"memory_mb": 4800, "age_minutes": 8, "recorded_at": "2026-04-07T14:50:00Z"}
      ]
    }
  }
  ```
- Sample list capped at `system-memory-history-size` per type (default 20). Oldest samples dropped when full.
- **Age-aware projection:** When projecting memory for a new container, use the average of stored samples. Since samples are captured at end-of-life, they naturally represent peak usage for typical session durations. No need for complex age-duration modeling initially — the rolling average of end-of-life peaks is a good estimator. If a user's sessions are consistently long or short, the samples reflect that pattern.

**Note on current-usage polling:** End-of-life recording replaces the background `StatsCollector` thread for *historical stats*. However, the governor still needs to know current live container memory for the gate check (`current_used + projected_new <= target`). In `pm` scope mode, this requires a one-shot `docker stats --no-stream` call at gate-check time (not a background poller). In `system` scope mode, it reads `/proc/meminfo`. Both are fast enough to do synchronously in the gate check.

### R5: Launch gating — impl and review

**What:** If projected memory exceeds target, show error in TUI status bar and refuse to launch. User can free memory by stopping containers manually or lowering the target.

**Grounded in code:**
- Impl containers created via `pm_core/container.py:wrap_claude_cmd()` (line 694), called from `pm_core/claude_launcher.py:build_claude_shell_cmd()`.
- Review containers similarly created via `wrap_claude_cmd()`.
- The gate function returns `(allowed: bool, reason: str)`. On denial, the caller logs the reason and updates the TUI status bar.

### R6: Launch gating — QA scenarios with wait loop

**What:** If a QA scenario fails the memory check, it enters a wait loop. The QA loop retries the check periodically and launches the scenario once memory is available. The TUI status pane shows which scenarios are waiting for memory.

**Grounded in code:**
- QA scenario launching: `qa_loop.py:_launch_scenarios_in_containers()` (line 1147) creates containers in parallel threads.
- Existing queuing: `_poll_tmux_verdicts()` (line 1457) already has `_launch_queue`, `_queued_indices`, and `_launch_next_queued()` (line 1560). The memory governor integrates here — `_launch_next_queued` calls the governor before launching.
- Status display: `qa_status.json` already supports `"queued"` verdict state (rendered in `qa_status.py`). Add a new `"waiting_memory"` state.
- QA planner projection: if `current + (remaining * avg_qa_peak) > target`, launch as many as fit and queue the rest.

### R7: TUI status bar integration

**What:** Status bar shows current memory usage vs target (e.g. `34G/48G`). When a launch is blocked, status bar shows the blocked action. QA scenarios waiting for memory show a waiting indicator.

**Grounded in code:**
- `pm_core/tui/widgets.py:StatusBar.update_status()` (line 24) — add a `memory_status: str` parameter.
- `pm_core/tui/app.py:_update_status_bar()` (line 530) — compute memory info and pass to `update_status`.
- QA status pane: `pm_core/qa_status.py` — render `"waiting_memory"` verdict with a distinct color/icon.

## 2. Implicit Requirements

### IR1: Graceful degradation when Docker stats unavailable
`docker stats` may fail (Docker not running, permissions). The governor must not block launches when stats are unavailable — fall back to allowing the launch and logging a warning.

### IR2: Thread safety
Memory governor state (stats file, current usage cache) is accessed from multiple threads: QA scenario threads, the TUI poll timer, the review loop. All shared state must use locks.

### IR3: Stats file atomicity
`~/.pm/container-stats.json` must be written atomically (write-to-temp + rename) to avoid corruption from concurrent readers/writers, following the pattern used elsewhere in pm (e.g. `qa_status.json`).

### IR4: Container restart after stop
When a stopped container is needed again (e.g. `docker start` for reuse), the setup sentinel and push proxy must be verified. `create_container()` already handles reuse of existing containers (line 395-419) — stopped containers need the same treatment but with `docker start` first.

### IR5: Memory units parsing
Memory values come from users (`48g`, `8g`) and from Docker (`1.5GiB`, `500MiB`). A utility function must normalize these to a common unit (MB).

### IR6: Default memory target
When no target is configured, the governor must be inactive (all launches allowed). The feature is opt-in.

### IR7: Stop-on-idle must not interfere with verification or INPUT_REQUIRED
QA scenarios in the verification phase (`verifying` set in `_poll_tmux_verdicts`) must not be stopped until verification completes. If verification fails and the scenario is sent back to `pending` (follow-up message sent, line 1670), the container must remain running. Scenarios with INPUT_REQUIRED verdict must never be stopped — the user needs the container alive to interact.

### IR8: Stats capture must not block container teardown
The `docker stats` call before stop/removal should have a short timeout (5s). If it fails or times out, proceed with the stop/removal anyway — missing one sample is acceptable. Log a warning but don't prevent cleanup.

## 3. Ambiguities

### A1: What counts as "current_used"?
**Ambiguity:** Is "current used" the sum of all pm containers' memory, or total system memory usage?
**Resolution:** Configurable via `pm container set system-memory-scope pm|system`:
- **`pm`** (default): Sum of all running `pm-*` containers' current memory from `docker stats`. The target represents how much memory pm is allowed to use. Good for shared machines where other workloads also need memory.
- **`system`**: Total system memory usage from `/proc/meminfo` (`MemTotal - MemAvailable`). The target represents a ceiling on total machine memory usage. Useful when pm is the primary workload and you want to prevent the whole machine from thrashing — e.g., `system-memory-target 56g` on a 64GB machine leaves 8GB headroom for the OS and other tools.

Setting stored in `~/.pm/settings/container-system-memory-scope`. The gate check `current_used + projected_new <= target` uses whichever scope is configured. The status bar shows the scope in the display: `34G/48G (pm)` or `52G/56G (sys)`.

### A2: Scope of `stop-idle` for QA
**Ambiguity:** Does `stop-idle qa` apply to `qa_planner` containers as well, or only `qa_scenario`?
**Resolution:** `stop-idle qa` applies to all QA container types (`qa_scenario`, `qa_planner`, `qa_verification`). If more granular control is needed, it can be added later as `stop-idle qa_scenario`, etc.

### A3: Rolling average window size
**Ambiguity:** How many samples to keep for the rolling average?
**Resolution:** Default 20 samples per type, configurable via `pm container set system-memory-history-size N`. Stored in `~/.pm/settings/container-system-memory-history-size`. Lower values (e.g. 5) adapt faster; higher values smooth outliers. The rolling average drops the oldest sample when the window is full.

### A4: Memory target includes or excludes per-container limits?
**Ambiguity:** The global target (`48g`) is separate from the per-container `memory-limit` (`8g`). The governor uses the target to gate launches but each container still has its own Docker-enforced limit.
**Resolution:** The target is a soft aggregate limit. Per-container Docker limits (`--memory`) remain unchanged and provide hard per-container ceilings. The governor prevents launching too many containers such that their aggregate exceeds the target, even though individual containers are within their own limits.

### A5: `stop-idle` CLI interface
**Ambiguity:** The task description says `pm container set stop-idle impl|review|qa on|off`, but the current `container set` command takes `key value` pairs where key is a `click.Choice`.
**Resolution:** Extend `container_set` to accept `stop-idle-impl`, `stop-idle-review`, `stop-idle-qa`, `system-memory-target`, `system-memory-scope`, `system-memory-default-projection`, `system-memory-history-size` as keys, mapping to `container-{key}` settings. This fits the existing CLI pattern without a new subcommand structure.

### A6: What happens to queued scenarios when the QA loop is stopped?
**Ambiguity:** If `state.stop_requested` is set while scenarios are in the memory wait queue, should they be abandoned or persist?
**Resolution:** Respect `stop_requested` — memory-waiting scenarios are abandoned, same as currently queued scenarios in `_poll_tmux_verdicts`.

### A7: Projection fallback cascade
**Ambiguity:** What does the governor project when historical data is incomplete or missing?
**Resolution:** Cascade:
1. If there are **any** samples for this container type (even 1), use their average. A partial window (e.g. 3 samples when `history-size` is 20) is still real data and better than any default. The average improves as more samples accumulate.
2. If there are **zero** samples and `container-system-memory-default-projection` is set, use that.
3. If there are **zero** samples and no default projection configured, fall back to the per-container `memory-limit` from `ContainerConfig` (e.g. `8g`).

The key principle: any real observation beats a configured default, and a configured default beats the Docker hard limit.

### A8: Stats capture timing
**Ambiguity:** When exactly is memory captured?
**Resolution:** At container end-of-life — immediately before `docker stop` or `docker rm -f`. A single `docker stats --no-stream` call for that specific container, with a 5s timeout. This replaces periodic background polling. For the gate check's "current used" value, a one-shot `docker stats` (all pm containers) or `/proc/meminfo` read is done synchronously at check time.

### A9: Container age and its use in projection
**Ambiguity:** Should projection account for how long the new container is expected to run?
**Resolution:** Not initially. The rolling average of end-of-life samples already reflects typical session durations for each type (QA scenarios are short, impl sessions are long). The age is stored in each sample for future refinement — e.g., if we later want to project differently for a quick QA scenario vs. a long impl session. For now, average of all samples per type is sufficient.

## 4. Edge Cases

### E1: All containers stopped but memory still high (pm scope)
In `pm` scope, Docker reports memory for running containers only. If host memory is high from non-Docker processes, the governor can't detect this. Users on machines where non-pm workloads are significant should use `system-memory-scope system` instead, which reads total system memory from `/proc/meminfo` and accounts for all processes.

### E1b: System scope on non-Linux
`/proc/meminfo` is Linux-only. On macOS, fall back to `sysctl hw.memsize` and `vm_stat` (or `memory_pressure`). If neither is available, log a warning and fall back to `pm` scope automatically.

### E2: Container memory limit exceeds target
If `container-memory-limit` is `16g` but `system-memory-target` is `12g`, a single container can't fit. The governor should detect this and report a clear error: "Container memory limit (16g) exceeds system memory target (12g)".

### E3: Race between stats sampling and container lifecycle
A container may start or stop between the stats sample and the launch gate check. Accepted — the gate check uses the most recent sample plus projection, which is conservative. In the worst case a launch is unnecessarily blocked for one polling cycle.

### E4: Concurrent launch attempts
Multiple containers may attempt to launch simultaneously (e.g. QA scenarios in parallel threads). The governor gate must be serialized (single lock) to prevent N containers all seeing "enough memory" and all launching.

### E5: `docker stop` of a container with active claude session
`docker stop` sends SIGTERM then SIGKILL after grace period. The claude process inside will be terminated. This is acceptable for idle containers (session complete), but the governor must ensure the container is truly done before stopping. Per-type rules:
- **QA:** Only stop after verdict accepted (and verified if PASS). Never stop INPUT_REQUIRED.
- **Impl:** Only stop after `became_idle()` fires and interactive prompt check passes.
- **Review:** Only stop after review loop completes.

### E10: Verification failure after stop-on-idle
If a QA scenario gets PASS, enters verification, and verification *fails* — the scenario goes back to `pending` and receives a follow-up message (line 1670). The container must still be running at this point. Since stop-on-idle only fires *after* verification passes, this is safe — the container hasn't been stopped yet. But if we change the trigger ordering this becomes a bug.

### E11: INPUT_REQUIRED preventing memory reclamation
A QA scenario stuck on INPUT_REQUIRED holds its container alive indefinitely (cannot be stopped). If several scenarios hit INPUT_REQUIRED, their containers consume memory that queued scenarios are waiting for, creating a deadlock. Mitigation: the QA status dashboard already shows INPUT_REQUIRED prominently — the user must resolve these manually. The governor should log a warning when memory-waiting scenarios exist and INPUT_REQUIRED containers are holding memory.

### E12: `docker start` after `docker stop` — process state
`docker stop` kills the `sleep infinity` process (the container's CMD). `docker start` re-runs the CMD, but the setup script (user creation, git wrapper, sentinel) has already written its artifacts to the filesystem overlay. The sentinel file `/tmp/.pm-ready` persists in the overlay, so the setup-wait loop in `create_container()` returns immediately. However, `/tmp` may be a tmpfs that is cleared on restart — need to verify. If cleared, the setup script runs again (idempotent operations) and re-creates the sentinel. The push proxy socket on the host side needs restarting regardless (already handled in the reuse path, line 406-418).

### E13: Impl idle detection false positive during slow operations
A long-running compile, test suite, or download can produce no pane output for >30s, triggering `became_idle()`. Since stop-idle for impl defaults to off, this only affects users who explicitly opt in. They should be aware that slow operations may cause premature stopping. A future enhancement could check `docker stats` CPU usage to distinguish "idle" from "busy but quiet".

### E6: Stopped container reuse vs. fresh container
When a stopped container is restarted via `docker start`, the filesystem is intact but the process is fresh. The push proxy may need restarting. The existing reuse path in `create_container()` (line 395-419) handles proxy restart — extend this to also handle stopped containers.

### E7: QA scenario count exceeds memory capacity
If the planner generates 10 scenarios but only 3 fit in memory, the governor queues 7. If each scenario takes a long time, the QA run could be very slow. This is inherent to the constraint and acceptable — the status dashboard shows progress.

### E8: Memory target changed mid-QA-run
If the user changes the target while a QA run is active, the new value should take effect on the next governor check (next launch attempt or next poll cycle). No need to stop running containers — they're already within their individual limits.

### E9: Stats file corruption
If `container-stats.json` is corrupted (truncated write, manual edit), the governor should catch JSON parse errors, log a warning, and reset to empty stats (falling back to per-container limits for projection).

### E14: Container removed externally (no stats captured)
Containers may be removed outside pm's control (`docker rm` by user, Docker daemon restart, system reboot). No end-of-life stats are captured in these cases. This is fine — the sample is simply missed. The governor still works with whatever historical samples exist.

### E15: Container type classification for stats
Stats are keyed by container type, but container names encode the type: `pm-{tag}-impl`, `pm-{tag}-review`, `pm-{tag}-qa-{pr}-{loop}-s{N}`. `remove_container()` and `stop_container()` need to infer the type from the name to record the sample correctly. Add `infer_container_type(name: str) -> str | None` to parse the naming convention.

## 5. Implementation Plan

### New files:
1. **`pm_core/memory_governor.py`** — Core governor logic:
   - `parse_memory(s: str) -> int` — parse "8g", "1.5GiB", "500MiB" to MB
   - `get_pm_container_memory() -> dict[str, int]` — one-shot `docker stats --no-stream` for all pm containers, returns name→MB
   - `get_system_memory_used_mb() -> int` — read `/proc/meminfo` (MemTotal - MemAvailable), macOS fallback via `sysctl`/`vm_stat`
   - `get_current_used_mb() -> int` — dispatch based on `system-memory-scope` setting
   - `capture_container_memory(name: str) -> int | None` — `docker stats --no-stream` for a single container, returns MB or None on failure. Called before stop/removal.
   - `get_container_age_minutes(name: str) -> float | None` — `docker inspect` StartedAt, returns age in minutes
   - `load_stats() -> dict` / `save_stats(stats)` — read/write `~/.pm/container-stats.json` (atomic write via temp+rename)
   - `record_sample(container_type: str, memory_mb: int, age_minutes: float)` — append sample to stats file, drop oldest if over `system-memory-history-size`
   - `project_memory(container_type: str) -> int` — average of stored end-of-life samples (uses whatever samples exist, even if fewer than `history-size`); only falls back to `system-memory-default-projection` / `memory-limit` when zero samples
   - `get_history_size() -> int` — read `system-memory-history-size` setting, default 20
   - `check_launch(container_type: str, count: int = 1) -> tuple[bool, str]` — gate check (current_used + count * projected <= target)
   - `get_memory_target() -> int | None` — read setting, None if unset (governor inactive)
   - `get_stop_idle_policy(container_type: str) -> bool` — check stop-on-idle setting

2. **`tests/test_memory_governor.py`** — Unit tests for the governor module

### Modified files:
1. **`pm_core/cli/container.py`** — Add `system-memory-target`, `system-memory-scope`, `system-memory-default-projection`, `system-memory-history-size`, `stop-idle-impl`, `stop-idle-review`, `stop-idle-qa` to `container_set` choices. Add memory info to `container_status` output.
2. **`pm_core/container.py`** — Add `stop_container()` (captures memory before stopping), modify `remove_container()` to capture memory before removal, modify `create_container()` to handle stopped container restart, add governor gate calls.
3. **`pm_core/qa_loop.py`** — Integrate governor into `_launch_scenarios_in_containers()` and `_launch_next_queued()`. Add `"waiting_memory"` status. Call `stop_container()` (not `remove_container()`) for completed QA scenarios when stop-on-idle is enabled.
4. **`pm_core/tui/widgets.py`** — Add `memory_status` parameter to `StatusBar.update_status()`.
5. **`pm_core/tui/app.py`** — Compute and pass memory status to status bar.
6. **`pm_core/qa_status.py`** — Render `"waiting_memory"` verdict state with distinct indicator.

## 6. QA Testing Notes

### QA must verify: all container panes properly stopped when stop-idle-qa is enabled

When `stop-idle-qa` is `on`, QA scenarios should verify that **all panes that were `docker exec`'d into a scenario container** are terminated when the container is stopped. Each scenario container hosts up to 3 panes:
1. **Concretizer pane** — `docker exec` that finishes early but stays open
2. **Worker pane** — `docker exec` that runs the scenario
3. **Verification pane** (only on PASS) — `docker exec` split from worker

`docker stop` sends SIGTERM to the container's main process (`sleep infinity`), which kills all `docker exec` sessions. QA should confirm:
- After a PASS-verified scenario, `docker ps` no longer shows the container running (it should show as `Exited`)
- After a NEEDS_WORK scenario, same check
- After an INPUT_REQUIRED scenario, the container is still **running** (not stopped)
- The concretizer, worker, and verification panes are all dead after stop (tmux panes may show exit status or be closed by tmux)
- Memory was recorded in `~/.pm/container-stats.json` with the correct container type (`qa_scenario`) before the stop
- The QA status dashboard (`qa_status.py`) still renders correctly after containers are stopped (it reads `qa_status.json`, not container state)
- When stop-idle-qa is `off`, containers remain running after verdict (existing behavior preserved)

### QA must verify: standalone review container stop edge case

Reviews can run in two modes:
1. **Review loop** (`zz d` / `zzz d`): The loop has explicit verdict detection and a clear completion point in `run_review_loop_sync()`. Stop-on-idle integrates cleanly here.
2. **Standalone review** (plain `d`): There is **no verdict polling**. The review window is created and left open indefinitely. The only completion signal is idle detection via `PaneIdleTracker` (same mechanism as impl sessions).

QA should verify:
- **Standalone review with `stop-idle-review on`:** After the reviewer goes idle (30s no output), the container is stopped. The diff shell pane (host-side, not containerized) remains alive.
- **Review loop with `stop-idle-review on`:** Container is stopped when the loop exits with a final verdict. If the final verdict is INPUT_REQUIRED and the loop is waiting for follow-up, the container is NOT stopped.
- **Review loop with `stop-idle-review off`:** Container remains running after loop completion (existing behavior).
