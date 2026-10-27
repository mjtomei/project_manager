# Implementation Spec: Container Memory Governor

PR: pr-eb2dbfc — "Container memory governor: dynamic memory limits with per-type stop policy and QA queuing"

## 0. Revision 2026-10-27 — safety hardening after the OOM host restart

The PR was refreshed onto origin/master@450a6362 and hardened per the
2026-10-27 PR note.  These decisions supersede any conflicting text in
the sections below (which are amended in place where they conflict).

**Fail closed.**  Admission never treats "cannot measure" as "nothing in
use".  A failed `<runtime> stats` call (runtime down, rootless Podman
without a delegated memory cgroup, one cgroup-less container making
`podman stats` fail for *every* container — seen live, rc=125), a pm
container with no usage figure (`--`, `0B`), unreadable `/proc/meminfo`
on Linux, an invalid target/scope/reserve setting, or a busy governor
lock (`GovernorLockTimeout`, 30 s) all refuse the launch with the reason.
impl/review/signoff/qa-debug get a `ContainerError` naming the blocked
action; QA scenarios wait (`waiting_memory` + reason) and retry.  Unset
the target (`pm container set system-memory-target off`) to bypass.

**Runtime abstraction.**  All measurement goes through
`container._get_runtime()` (docker or podman).  Docker prints binary
units (`1.5GiB`), Podman decimal SI units (`1.06GB`); both parse to MiB
(`parse_runtime_memory`).  Podman's `--format` tabwriter turns tabs into
padding, so stats use `{{.Name}}|{{.MemUsage}}` (found by the live
check).  Podman's StartedAt template output (`2026-10-27 14:11:38.69
+0000 UTC`) is parsed alongside RFC 3339.  Verified against real rootless
Podman 3.4.4 — evidence in `/pm-captures/impl/live-podman/`.

**Peaks, not snapshots.**  End-of-life capture reads the container's
cgroup peak (`/sys/fs/cgroup/memory.peak`, v1 `memory.max_usage_in_bytes`)
via `<runtime> exec`; samples record `kind: peak|snapshot`.  Snapshot
samples (and legacy samples without `kind`) are inflated by
`_SNAPSHOT_GROWTH_FACTOR` = 1.5.  Projection is the 90th percentile
(nearest rank) of the adjusted samples, not the mean.

**Committed usage.**  `take_snapshot()` measures, per scope:
- pm: Σ current usage of running pm containers + the growth still ahead
  of each (max(0, projection(type) − current)).
- system: host used (MemTotal − MemAvailable) + the same growth; if
  per-container stats fail but `ps` works, every running pm container is
  assumed to have its full projection ahead of it.
Admission (`admit`) requires committed + in-flight reservations +
projection ≤ target **and** that host MemAvailable − growth − in-flight
− projection ≥ the host reserve (`system-memory-reserve`, default 10 % of
MemTotal; accepts `8g` or `10%`).

**In-flight reservations.**  A granted queue entry reserves its
projection until its container (`container_name` on the entry) shows up
in runtime stats, or until it is dequeued; then the snapshot carries it
(usage + growth), so there is no double counting (E16).  Acquired entries
expire after 30 min as a backstop.

**Shared admission and ownership across processes/restarts.**  Entries
carry pid, pid start time and a per-exec instance nonce: entries of dead
or recycled pids and of this process's pre-restart instance (pm restarts
re-exec in place with the same PID) are stale.  Waiting entries expire
unless their owner renews them (`keepalive`, ≤ every 15 s while waiting;
TTL 300 s).  Entries have keys (container name; `<pr>-<loop_id>:s<N>`
for QA) so retries don't pile up and a resumed QA run adopts its old
entries and keeps its place in line.  On a TUI restart every resumed run
adopts all its queued scenarios' entries (`launch_queue.adopt_run`, which
cleans nothing) before any resumed loop starts, because a loop's first
queue access cleans pre-restart entries and would drop the other runs'
(and its own non-head) entries (QA S44).  Adoption runs on a daemon
thread (it can wait on the lock), and the resumed runs count as running
from the moment they are found, so `t` / `zz t` cannot start a second loop
meanwhile (review 05f6 i1, i2).  A resume that ends before its poll
loop (no pm session, missing workdir, thread crash) releases the
adopted entries itself (review 05f6 i3); if the adoption thread cannot
start at all, the runs end ERROR instead of staying "running" with no
loop (review 05f6 i4).  impl/review/signoff/QA all walk the
same queue under the same lock (`enqueue_and_try_acquire` uses the full
policy walk).

**Launch paths gated.**  Every path that *creates* a container: impl,
review (incl. review-loop iterations), signoff (`wrap_claude_cmd` →
`acquire_launch_admission`), QA scenarios (initial batch in
`_admit_initial_batch`, queued in `_poll_tmux_verdicts`), and
`pm qa debug` containers.  Reusing an already-running container needs no
admission (its usage is already counted).  The QA planner, refiner
(concretizer), verifier and finalizer create no containers on current
master: the planner/verifier/finalizer run on the host and the refiner
execs into the scenario container that was admitted.

**QA admission.**  The initial batch is admitted in one walk (as many as
fit launch; the rest wait at the head of the queue with a reason).  Only
scenarios with a free concurrency slot get queue entries, so capped
scenarios don't reserve memory other launches could use.  Queued
admission attempts are rate-limited (`_MEMORY_RETRY_INTERVAL` = 15 s).
The waiting reason names INPUT_REQUIRED containers still held (E11).
Every entry is dequeued on loop exit (stop, completion, crash).

**Stop-on-idle is removal, and never cuts off a person.**  As before,
"stop" removes the container (`remove_container`, stats captured first;
the bind-mounted workdir keeps all state).  It now runs on a daemon
thread (never on the TUI thread or the QA poll loop), targets the exact
container name of this session (no keyword search, so another pm
session's container for the same PR is never touched), and keeps the
container when:
- the runtime reports exec sessions (`.ExecIDs`) beyond the exec clients
  started from the session's own panes (someone attached a shell —
  "retained human session"), or ownership cannot be determined;
- the session transcript changed after the idle/verdict point (someone
  resumed it);
- (impl / review) the pane was not started with the session whose idle
  event and verdict fired: the TUI registers a window's pane against its
  own transcript symlink, which can name an earlier session after a review
  loop or auto-sequence iteration reused the window (review 1811 i5); a
  review loop compares the window's pane with its last iteration's
  transcript, since the window may have been replaced by then (review
  1811 i6);
- the verdict is INPUT_REQUIRED or verification is in flight (unchanged).
The ownership and resumed checks run again right before removal, after
the stats capture (which takes seconds), so a person who attaches or
resumes during the capture keeps the container.
Standalone reviews stop only after a final review verdict (not
INPUT_REQUIRED) is mirrored by master's hook-driven review pass.  A
review loop stops its container only on PASS, NEEDS_WORK or KILLED —
not INPUT_REQUIRED, not ERROR (a failed launch or poll may leave the
reviewer starting or running), and not when the loop was stopped or
superseded (`stop_requested`): `z d` / `zz d` kill the loop's window and
start a fresh review under the same `review-<pr>` name.  Killing the window
runs master's exec EXIT trap (`build_exec_cmd(cleanup=True)`, `rm -f`), which
removes the container whatever the stop-idle policy is.  The fresh review
then recreates it, or reuses it if it is still running.  Either way the
container belongs to the new review.  `stop_container` pins the container
ID it first saw.  It keeps a container that was recreated under the same
name since then, and it removes by ID (review 3f45 i1, after QA S39).
The end-of-life sample is also taken by ID, and the name-keyed push proxy
is left to a container that took the name meanwhile (review 3f45 i2).
Window kill and fresh-review recreation are master lifecycle behaviour.
They are not part of stop-on-idle, and #241's ownership work will
revisit them.

Two timing and sampling questions came up in QA S38 (review 3f45 i3).
- **Which removals record a sample.**  Every removal of a *running* pm
  container records an end-of-life sample, and that includes the stale
  cleanup at the start of a fresh QA run (`z t`).  Those leftovers ran
  real scenarios, so their cgroup peaks are real observations.  The run
  does not re-baseline after cleanup.  A scenario that counts samples
  should expect one sample per running container that is removed.
- **When a verdict happens.**  QA stop-on-idle runs after the loop
  *records* the verdict, not when the pane prints it.  Master's poll
  loop starts verdict polling only after every scenario has launched
  and `_VERDICT_GRACE_PERIOD` (30 s) has passed.  It then needs two
  stable polls.  So "removed within N s of the verdict" counts from the
  verdict recorded in `qa_status.json`.

Container types are read from the label at the *end* of the name
(`…-impl-pr-x`, `…-qa-pr-x-<loop>-sN`): the session tag comes from the
project name and may itself contain words like `impl` or `review`.

**UI.**  The status bar reads a cached memory string only; a 15 s TUI
interval refreshes it off the UI thread (runtime stats take seconds).
Text: `mem 34G/48G (pm)`, `mem ?/48G (pm) unmeasurable` on failure, and
`blocked: impl pr-1 [+N]` for launches refused in the last 10 min
(`~/.pm/governor-blocked.json`, cleared when the action launches; written under the governor lock because refusals come from separate CLI processes, entries past the window pruned).  The used figure is committed usage — measured plus expected growth — the number admission compares with the target.  The TUI also refreshes once at startup.
`pm container status` prints usage, growth, host free/reserve, the
unmeasurable reason and blocked launches.  The QA status pane counts
`waiting_memory` as not complete and shows "N waiting for memory".

**Coordination with #241 (pr-1139060, unmerged).**  #241 rewrites
container lifecycle with ownership labels, retain markers,
`live_owner_panes`/`activity_owner`, `release_containers` and launch
slots.  This PR keeps its container changes to narrow hooks so they
compose: `acquire_launch_admission`/`release_launch_admission` around
creation, `capture_and_record` before removal, and `stop_container` as
the single stop-on-idle removal path.  When #241 lands, `stop_container`
should defer to its retain markers / live-owner checks and release
primitive instead of the local exec-session check.  (Cross-PR note left
on pr-1139060.)

**Known limit — nested rootless Podman.**  Inside a pm container whose
cgroup isn't delegated (this dev environment), inner containers share
the outer cgroup, so `podman stats` and `memory.peak` report the
*enclosing* cgroup for each.  Sums then overcount (conservative); use
`system-memory-scope system` there.

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

**What:** Before launching any container, the governor checks: `current_used + projected_new <= target`. Projection uses a rolling window of peak memory samples per container type (`impl`, `review`, `signoff`, `qa_scenario`, `qa_debug`), observed through the container runtime and persisted across sessions (90th percentile since 2026-10-27, see A7).

**Grounded in code:**
- Container creation goes through `pm_core/container.py:create_container()` (line 338) and `pm_core/container.py:create_qa_container()` (line 620). The governor gate must run before these calls.
- `docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}'` gives current memory per running container. Filter by `CONTAINER_PREFIX = "pm-"`.
- Historical stats persisted to `~/.pm/container-stats.json`.

### R3: Per-type stop-on-idle policy

**What:** Configurable per container type: `pm container set stop-idle-impl|stop-idle-review|stop-idle-qa on|off`. When enabled, containers of that type are removed after their session completes. Default: qa=on, impl=off, review=off. **Revised (review 6f31 i2, kept 2026-10-27):** the PR description said `docker stop` (not removed) so `docker start` keeps the overlay; the workdir — packages, venv, source — is bind-mounted from the host and survives removal, so the stopped-container restart path was dropped and "stop" means `remove_container` (stats captured first).

**Grounded in code:**
- CLI: extend `pm_core/cli/container.py:container_set()` choices with `stop-idle-impl`, `stop-idle-review`, `stop-idle-qa`.
- Settings: `~/.pm/settings/container-stop-idle-{type}` (e.g. `container-stop-idle-qa`).
- Container stop: `stop_container(name, pane_ids, resumed)` in `pm_core/container.py` — ownership/resumed checks, stats capture, `remain-on-exit` on the session's panes, then `remove_container(capture=False)`. Callers use `stop_idle_in_background` (policy-gated, daemon thread).

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
- **Capture points:** Before a running container is removed, read its cgroup peak (fallback: a `<runtime> stats` snapshot; see A8). Integration points:
  - `container.py:remove_container()` — called from cleanup and orphan removal; samples only a *running* container (one inspect), and `create_container()`'s pre-create cleanup passes `capture=False` (nothing is running there).
  - `container.py:stop_container()` — captures itself, then removes with `capture=False`.
  - `pm session kill` — `sample_session_containers()` samples every running session container *before* tmux is killed (that fires each pane's exec EXIT trap, `rm -f`, which would remove pm-launched containers unsampled), then `cleanup_session_containers()` removes those with `capture=False` (QA S56).
  - Both go through `memory_governor.capture_and_record()`.
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
- **Age-aware projection:** When projecting memory for a new container, use the stored samples (**revised 2026-10-27:** 90th percentile, snapshots ×1.5 — see A7; the text below said "average"). Since samples are captured at end-of-life, they naturally represent peak usage for typical session durations. No need for complex age-duration modeling initially — the rolling average of end-of-life peaks is a good estimator. If a user's sessions are consistently long or short, the samples reflect that pattern.

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

### R8: Cross-process launch queue with fairness policies

**What:** Multiple pm projects can run simultaneously. The in-process threading locks in the memory governor are insufficient — two pm processes can both pass the memory check simultaneously, overshooting the target. A global launch queue serializes cross-process access and provides configurable fairness when multiple QA runs compete for memory.

**Problems solved:**
1. **Stats file race**: `record_sample()` uses a threading lock but no cross-process lock. Two pm processes can lose each other's samples during concurrent write.
2. **Gate check race**: `check_launch()` uses a threading lock. Two processes can both pass the memory check simultaneously, overshooting the target.
3. **No fairness**: QA scenarios waiting for memory just poll `check_launch()` every 5 seconds. Whoever polls at the right time wins. No ordering between processes or QA runs.

**Design:**

#### Single governor file lock
All governor operations serialize through `~/.pm/governor.lock` using `fcntl.flock` (same pattern as `pane_registry.py:locked_read_modify_write()`). This one lock covers stats file writes, gate checks, and queue mutations. Lock timeout: 30 seconds (admission measures runtime stats under the lock; a timeout refuses — see E15).

#### Global launch queue
New file `~/.pm/launch-queue.json`, managed by new module `pm_core/launch_queue.py`.

Queue file format:
```json
{
  "entries": [
    {
      "id": "a1b2c3d4",
      "container_type": "qa_scenario",
      "pid": 12345,
      "enqueued_at": 1712678400.123,
      "qa_run_id": "pr-eb2dbfc-abc123"
    }
  ],
  "last_served_qa_run": null
}
```

#### Queue policy setting
Single setting: `pm container set system-memory-queue-policy fifo|priority-drain|priority-round-robin`

- **`fifo`** (default): All entries served strictly by enqueue time. No type priority, no QA sub-ordering.
- **`priority-drain`**: impl (0) > review (1) > qa (2). Within QA, all scenarios from one QA run complete before moving to the next. Runs ordered by earliest entry time.
- **`priority-round-robin`**: Same type priority as `priority-drain`. Within QA, alternate between QA runs. Tracks `last_served_qa_run` to resume rotation.

The QA sub-policies (drain vs round-robin) are modes of priority ordering — they only make sense when QA entries are grouped together by type priority. In FIFO mode, entries interleave by time regardless of type, so sub-ordering is meaningless.

#### Memory accounting for acquired entries
When an entry is granted by `try_acquire`, it stays in the queue briefly (status="acquired") until the container is running. The `try_acquire` walk accounts for acquired entries' projected memory so two processes can't both claim the same headroom. Entries are cleaned up via `dequeue()` after container creation or by stale PID cleanup.

**Grounded in code:**
- New module: `pm_core/launch_queue.py` — lock, queue I/O, enqueue/try_acquire/dequeue, policy sorting.
- Cross-process lock replaces `_gate_lock` and `_stats_lock` threading.Lock in `memory_governor.py`.
- `container.py:wrap_claude_cmd()` (~line 770): replace direct `check_launch` call with `enqueue_and_try_acquire(ctype)`.
- `qa_loop.py`: enqueue all scenarios at phase 2 entry, use `try_acquire` in `_launch_next_queued`, dequeue on completion/stop.
- CLI: add `system-memory-queue-policy` to `container_set` choices.

#### `pm_core/launch_queue.py` public API
```python
def governor_lock(timeout=30.0) -> contextmanager
    # Cross-process file lock on ~/.pm/governor.lock
    # Reusable by memory_governor.py for stats operations

def enqueue(container_type, qa_run_id=None, count=1) -> list[str]
    # Add entries to queue. Returns entry IDs.
    # count>1 for batch QA enqueue.

def try_acquire(entry_ids: list[str]) -> list[str]
    # Under lock: clean stale, sort by policy, walk sorted order,
    # grant entries from entry_ids that are next AND fit in memory.
    # Returns granted entry IDs (may be empty).
    # Accounts for acquired entries' projected memory.

def enqueue_and_try_acquire(container_type, qa_run_id=None) -> tuple[str, bool]
    # Atomic fast path for impl/review: enqueue 1 + immediate try.
    # Returns (entry_id, acquired). One lock round-trip.

def dequeue(entry_ids: list[str]) -> None
    # Remove entries (post-launch cleanup, cancellation, stop).

def get_queue_status() -> dict
    # Read-only snapshot for status display (no lock needed).
```

#### try_acquire walk logic
```
1. Clean stale entries (dead/recycled pid, pre-restart instance, expired TTL — see E14)
2. Sort by policy (_sort_queue)
3. Compute: used = current_docker_stats + sum(projected for acquired entries)
4. Walk sorted waiting entries:
   - If entry.id in my entry_ids AND used + projected <= target → grant it
   - If entry.id NOT mine → add its projected to `used` (it might launch soon)
   - If used > target → stop walking
5. Update last_served_qa_run if QA entry granted (priority-round-robin only)
6. Save queue
```

#### Policy sorting
- **FIFO**: sort all by `enqueued_at`
- **Priority-drain**: sort by (type_priority, then group QA by `qa_run_id` ordered by earliest entry, concatenate)
- **Priority-round-robin**: sort by (type_priority, then interleave QA entries across `qa_run_id` groups starting from `last_served_qa_run + 1`)

## 2. Implicit Requirements

### IR1: Fail closed when memory cannot be measured
`<runtime> stats` may fail (runtime not running, permissions, rootless Podman without memory cgroup delegation, a cgroup-less container). **Revised 2026-10-27:** the governor must not read a failed measurement as zero usage or allow the launch. When the target is set and usage cannot be measured, launches are refused (impl/review) or wait (QA) with the reason shown; the user can unset the target to bypass. (The original "allow and log a warning" let an unmeasurable host launch until it OOMed.)

### IR2: Thread and cross-process safety
Memory governor state (stats file, current usage cache) is accessed from multiple threads within a process (QA scenario threads, TUI poll timer, review loop) and from multiple pm processes running concurrently. All shared state must be protected by the cross-process file lock (`governor_lock` from `launch_queue.py`), which also serializes within-process access. The threading locks (`_gate_lock`, `_stats_lock`) in `memory_governor.py` are replaced by this file lock.

### IR3: Stats file atomicity
`~/.pm/container-stats.json` must be written atomically (write-to-temp + rename) to avoid corruption from concurrent readers/writers, following the pattern used elsewhere in pm (e.g. `qa_status.json`).

### IR4: Container restart after stop
**Superseded:** stop-on-idle removes the container, so there is no stopped container to restart. `create_container()` reuses a *running* container (restarting its push proxy if needed via `_ensure_push_proxy`) and otherwise removes any leftover and creates a fresh one.

### IR5: Memory units parsing
Memory values come from users (`48g`, `8g`) and from Docker (`1.5GiB`, `500MiB`). A utility function must normalize these to a common unit (MB).

### IR6: Default memory target
When no target is configured, the governor must be inactive (all launches allowed). The feature is opt-in.

### IR7: Stop-on-idle must not interfere with verification or INPUT_REQUIRED
QA scenarios in the verification phase (`verifying` set in `_poll_tmux_verdicts`) must not be stopped until verification completes. If verification fails and the scenario is sent back to `pending` (follow-up message sent, line 1670), the container must remain running. Scenarios with INPUT_REQUIRED verdict must never be stopped — the user needs the container alive to interact.

### IR8: Stats capture must not block container teardown
The capture before stop/removal (cgroup peak via exec, falling back to a stats snapshot) uses short timeouts (5s each), and a busy governor lock skips the sample. If it fails or times out, proceed with the stop/removal anyway — missing one sample is acceptable. Log a warning but don't prevent cleanup.

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
1. If there are **any** samples for this container type (even 1), use them. **Revised 2026-10-27:** the projection is the 90th percentile (nearest rank) of the samples, with snapshot samples inflated ×1.5 (end-of-life usage is not the peak); peak samples are used as recorded. A partial window (e.g. 3 samples when `history-size` is 20) is still real data and better than any default.
2. If there are **zero** samples and `container-system-memory-default-projection` is set, use that.
3. If there are **zero** samples and no default projection configured, fall back to the per-container `memory-limit` from `ContainerConfig` (e.g. `8g`).

The key principle: any real observation beats a configured default, and a configured default beats the Docker hard limit.

### A8: Stats capture timing
**Ambiguity:** When exactly is memory captured?
**Resolution:** At container end-of-life — immediately before removal. **Revised 2026-10-27:** read the cgroup peak counter through `<runtime> exec` first; fall back to a single-container `<runtime> stats --no-stream` snapshot, with 5s timeouts. This replaces periodic background polling. For the gate check's "current used" value, a one-shot `docker stats` (all pm containers) or `/proc/meminfo` read is done synchronously at check time.

### A9: Queue policy vs QA sub-policy interaction
**Ambiguity:** The original design had two independent settings: `system-memory-queue-policy fifo|priority` and `system-memory-qa-policy drain|round-robin`. With FIFO queue policy, the QA sub-policies conflict — FIFO means strict time ordering, but drain/round-robin reorder QA entries.
**Resolution:** Collapsed into a single setting: `pm container set system-memory-queue-policy fifo|priority-drain|priority-round-robin`. The drain and round-robin modes are sub-modes of priority ordering — they only apply when QA entries are grouped together by type priority. In FIFO mode, all entries (including QA) are strictly ordered by enqueue time with no sub-ordering. This removes the ambiguity entirely. One setting, three values.

### A10: Container age and its use in projection
**Ambiguity:** Should projection account for how long the new container is expected to run?
**Resolution:** Not initially. The rolling average of end-of-life samples already reflects typical session durations for each type (QA scenarios are short, impl sessions are long). The age is stored in each sample for future refinement — e.g., if we later want to project differently for a quick QA scenario vs. a long impl session. For now, the 90th percentile of all samples per type is sufficient.

## 4. Edge Cases

### E1: All containers stopped but memory still high (pm scope)
In `pm` scope, Docker reports memory for running containers only. If host memory is high from non-Docker processes, the governor can't detect this. Users on machines where non-pm workloads are significant should use `system-memory-scope system` instead, which reads total system memory from `/proc/meminfo` and accounts for all processes.

### E1b: System scope on non-Linux
`/proc/meminfo` is Linux-only. On macOS, fall back to `sysctl hw.memsize` and `vm_stat` (or `memory_pressure`). If neither is available, log a warning and fall back to `pm` scope automatically.

### E2: Container memory limit exceeds target
If `container-memory-limit` is `16g` but `system-memory-target` is `12g`, a single container can't fit. The governor should detect this and report a clear error: "Container memory limit (16g) exceeds system memory target (12g)". impl/review/signoff/qa-debug launches are refused with it; QA scenarios keep waiting with it as their reason (raising the target mid-run lets them launch). Sizes set through `pm container set` need a unit — a bare number is bytes; `off` unsets `system-memory-target` (governor inactive), `system-memory-reserve` (back to 10%) and `system-memory-default-projection` (back to `memory-limit`).

### E3: Race between stats sampling and container lifecycle
A container may start or stop between the stats sample and the launch gate check. Admission measures under the governor lock, and a granted entry keeps reserving its projection until its container is visible in stats, so a launch in flight is never missed. A container that just stopped may still be counted for one cycle — conservative.

### E4: Concurrent launch attempts
Multiple containers may attempt to launch simultaneously (e.g. QA scenarios in parallel threads). The governor gate must be serialized (single lock) to prevent N containers all seeing "enough memory" and all launching.

### E5: Removing a container with an active claude session
Removal kills every exec session in it. The claude process inside will be terminated. This is acceptable for idle containers (session complete), but the governor must ensure the container is truly done before stopping. Per-type rules:
- **QA:** Only stop after verdict accepted (and verified if PASS). Never stop INPUT_REQUIRED.
- **Impl:** Only stop after `became_idle()` fires (hook-driven idle on current master).
- **Review:** Only stop after review loop completes, or a standalone review has a final verdict and is idle.
- **All:** keep the container if another exec session is open in it, ownership is unknown, or the transcript changed since idle (revised 2026-10-27).

### E10: Verification failure after stop-on-idle
If a QA scenario gets PASS, enters verification, and verification *fails* — the scenario goes back to `pending` and receives a follow-up message (line 1670). The container must still be running at this point. Since stop-on-idle only fires *after* verification passes, this is safe — the container hasn't been stopped yet. But if we change the trigger ordering this becomes a bug.

### E11: INPUT_REQUIRED preventing memory reclamation
A QA scenario stuck on INPUT_REQUIRED holds its container alive indefinitely (cannot be stopped). If several scenarios hit INPUT_REQUIRED, their containers consume memory that queued scenarios are waiting for, creating a deadlock. Mitigation: the QA status dashboard already shows INPUT_REQUIRED prominently — the user must resolve these manually. The governor should log a warning when memory-waiting scenarios exist and INPUT_REQUIRED containers are holding memory.

### E12: `docker start` after `docker stop` — process state
**Superseded:** containers are removed, not stopped (see R3). Kept for history:
`docker stop` kills the `sleep infinity` process (the container's CMD). `docker start` re-runs the CMD, but the setup script (user creation, git wrapper, sentinel) has already written its artifacts to the filesystem overlay. The sentinel file `/tmp/.pm-ready` persists in the overlay, so the setup-wait loop in `create_container()` returns immediately. However, `/tmp` may be a tmpfs that is cleared on restart — need to verify. If cleared, the setup script runs again (idempotent operations) and re-creates the sentinel. The push proxy socket on the host side needs restarting regardless (already handled in the reuse path, line 406-418).

### E13: Impl idle detection false positive during slow operations
A long-running compile, test suite, or download can produce no pane output for >30s, triggering `became_idle()`. Since stop-idle for impl defaults to off, this only affects users who explicitly opt in. They should be aware that slow operations may cause premature stopping. A future enhancement could check `docker stats` CPU usage to distinguish "idle" from "busy but quiet".

### E6: Stopped container reuse vs. fresh container
**Superseded:** containers are removed, not stopped (see R3/IR4). Kept for history:
When a stopped container is restarted via `docker start`, the filesystem is intact but the process is fresh. The push proxy may need restarting. The existing reuse path in `create_container()` (line 395-419) handles proxy restart — extend this to also handle stopped containers.

### E7: QA scenario count exceeds memory capacity
If the planner generates 10 scenarios but only 3 fit in memory, the governor queues 7. If each scenario takes a long time, the QA run could be very slow. This is inherent to the constraint and acceptable — the status dashboard shows progress.

### E8: Memory target changed mid-QA-run
If the user changes the target while a QA run is active, the new value should take effect on the next governor check (next launch attempt or next poll cycle). No need to stop running containers — they're already within their individual limits.

### E9: Stats file corruption
If `container-stats.json` is corrupted (truncated write, manual edit), the governor should catch JSON parse errors, log a warning, and reset to empty stats (falling back to per-container limits for projection). Malformed entries in otherwise valid JSON (a non-numeric `memory_mb`, a `samples` that is not a list) are skipped by projection and replaced on the next `record_sample` — they must never raise inside admission (review 1811 i8).

### E14: Stale queue entries from dead processes
A pm process may crash or be killed with entries still in the launch queue. Every queue operation drops entries whose pid is dead or recycled (start time mismatch), entries of this process's previous instance (restart re-exec keeps the PID), waiting entries not renewed for 300s, and acquired entries older than 30 min.

### E15: Lock timeout on governor lock
**Revised 2026-10-27:** if `governor_lock()` times out (30s — admission measures stats while holding it), it raises `GovernorLockTimeout` and the launch is refused / keeps waiting with the reason. Proceeding unlocked would let two processes admit into the same headroom. Teardown paths (stats sample, dequeue) skip instead of blocking.

### E16: Acquired-entry double counting
**Revised 2026-10-27:** acquired entries carry their container name; once that container appears in runtime stats its usage and remaining growth are counted from the snapshot and the entry stops reserving, so there is no double counting even when `dequeue()` happens late (QA dequeues after the refiner finishes).

### E17: Priority mode with entries that don't fit
In priority-drain/priority-round-robin, an impl entry at the front of the queue may not fit in memory. The walk should continue past entries that don't fit to find smaller entries that do — an impl container needing 8GB shouldn't block a QA scenario that only needs 2GB when there's 3GB of headroom.

### E18: Queue file corruption
If `launch-queue.json` is corrupted, return empty queue and start fresh (same pattern as `container-stats.json` — E9).

### E19: Container removed externally (no stats captured)
Containers may be removed outside pm's control (`docker rm` by user, Docker daemon restart, system reboot). No end-of-life stats are captured in these cases. This is fine — the sample is simply missed. The governor still works with whatever historical samples exist.

### E20: Container type classification for stats
Stats are keyed by container type, but container names encode the type: `pm-{tag}-impl`, `pm-{tag}-review`, `pm-{tag}-qa-{pr}-{loop}-s{N}`. `remove_container()` and `stop_container()` need to infer the type from the name to record the sample correctly. Add `infer_container_type(name: str) -> str | None` to parse the naming convention.

## 5. Implementation Plan

### New files:
1. **`pm_core/memory_governor.py`** — Core governor logic:
   - `parse_memory(s: str) -> int` — parse "8g", "1.5GiB", "500MiB" to MB
   - `get_pm_container_memory() -> dict[str, int]` — one-shot `docker stats --no-stream` for all pm containers, returns name→MB
   - `read_host_memory() -> HostMemory | None` — read `/proc/meminfo` (MemTotal, MemAvailable), macOS fallback via `sysctl`/`vm_stat`
   - `get_current_used_mb() -> int` — dispatch based on `system-memory-scope` setting
   - `capture_container_memory(name: str) -> int | None` — `docker stats --no-stream` for a single container, returns MB or None on failure. Called before stop/removal.
   - `get_container_age_minutes(name: str) -> float | None` — `docker inspect` StartedAt, returns age in minutes
   - `load_stats() -> dict` / `save_stats(stats)` — read/write `~/.pm/container-stats.json` (atomic write via temp+rename). Uses `governor_lock()` from `launch_queue.py` for cross-process safety.
   - `record_sample(container_type: str, memory_mb: int, age_minutes: float)` — append sample to stats file under `governor_lock()`, drop oldest if over `system-memory-history-size`
   - `project_memory(container_type: str) -> int` — 90th percentile of stored end-of-life samples (snapshots ×1.5) (uses whatever samples exist, even if fewer than `history-size`); only falls back to `system-memory-default-projection` / `memory-limit` when zero samples
   - `get_history_size() -> int` — read `system-memory-history-size` setting, default 20
   - `take_snapshot()` / `admit(snapshot, projected, inflight)` — the gate math; production admission runs it inside the launch-queue walk (`launch_queue._admit_locked`). (The earlier standalone `check_launch()` was removed in review 2026-10-27: nothing used it and its in-flight accounting diverged from the queue walk.)
   - `get_memory_target() -> int | None` — read setting, None if unset (governor inactive)
   - `get_stop_idle_policy(container_type: str) -> bool` — check stop-on-idle setting
   - No threading locks (`_gate_lock`, `_stats_lock`) — cross-process file lock from `launch_queue.py` replaces them.

2. **`pm_core/launch_queue.py`** — Cross-process launch queue:
   - `governor_lock(timeout=30.0) -> contextmanager` — `fcntl.flock` on `~/.pm/governor.lock`. Shared by `memory_governor.py`.
   - `enqueue(container_type, qa_run_id=None, count=1) -> list[str]` — add entries to `~/.pm/launch-queue.json`, return entry IDs.
   - `try_acquire(entry_ids: list[str]) -> list[str]` — under lock: clean stale PIDs, sort by policy, walk and grant entries that are next in line AND fit in memory. Accounts for acquired entries' projected memory.
   - `enqueue_and_try_acquire(container_type, qa_run_id=None) -> tuple[str, bool]` — atomic fast path for impl/review (one lock round-trip).
   - `dequeue(entry_ids: list[str]) -> None` — remove entries post-launch or on cancellation.
   - `get_queue_status() -> dict` — read-only snapshot for status display.
   - Internal: `_sort_queue(entries, policy, last_served)` — sort by FIFO / priority-drain / priority-round-robin. `_clean_stale(entries)` — remove entries whose owner is gone or that expired (E14).

3. **`tests/test_memory_governor.py`** — Unit tests for the governor module

4. **`tests/test_launch_queue.py`** — Unit tests for launch queue: policy sorting, enqueue/acquire/dequeue, stale cleanup, round-robin state, concurrent acquire accounting.

### Modified files:
1. **`pm_core/cli/container.py`** — Add `system-memory-target`, `system-memory-scope`, `system-memory-default-projection`, `system-memory-history-size`, `system-memory-queue-policy`, `stop-idle-impl`, `stop-idle-review`, `stop-idle-qa` to `container_set` choices. Add validation for `system-memory-queue-policy` (`fifo|priority-drain|priority-round-robin`). Add memory info and queue status to `container_status` output.
2. **`pm_core/container.py`** — Add `stop_container()` (captures memory before stopping), modify `remove_container()` to capture memory before removal (stopped-container restart dropped — see IR4). Replace direct `check_launch()` call in `wrap_claude_cmd()` with `enqueue_and_try_acquire()` for impl/review gating; `dequeue()` after container creation or on denial.
3. **`pm_core/qa_loop.py`** — At phase 2 entry: `enqueue("qa_scenario", qa_run_id, keys=…)` for the scenarios with a free concurrency slot (`_admit_initial_batch`). In `_launch_next_queued()`: `try_acquire_detailed([head_entry])`, keeping the other waiting entries alive. Track `_entry_id_map` (scenario index → queue entry ID) and `_pending_entry_ids`. `dequeue()` on verdict completion or `stop_requested`. Add `"waiting_memory"` status. Call `stop_container()` for completed QA scenarios when stop-on-idle is enabled.
4. **`pm_core/tui/widgets.py`** — Add `memory_status` parameter to `StatusBar.update_status()`.
5. **`pm_core/tui/app.py`** — Compute and pass memory status to status bar.
6. **`pm_core/qa_status.py`** — Render `"waiting_memory"` verdict state with distinct indicator.
7. **`pm_core/memory_governor.py`** — (self-modification) Remove `_gate_lock` and `_stats_lock` threading locks. All lock-protected operations use `governor_lock()` from `launch_queue.py` instead.

## 6. QA Testing Notes

### QA must verify: all container panes properly stopped when stop-idle-qa is enabled

When `stop-idle-qa` is `on`, QA scenarios should verify that **all panes that were `docker exec`'d into a scenario container** are terminated when the container is stopped. Each scenario container hosts up to 3 panes:
1. **Concretizer pane** — `docker exec` that finishes early but stays open
2. **Worker pane** — `docker exec` that runs the scenario
3. **Verification pane** (only on PASS) — `docker exec` split from worker

Removing the container kills all its exec sessions. QA should confirm:
- After a PASS-verified scenario, the container is gone (`<runtime> ps -a` no longer lists it), and its panes stay readable (`remain-on-exit`)
- After a NEEDS_WORK scenario, same check
- After an INPUT_REQUIRED scenario, the container is still **running** (not removed)
- A container with a shell someone attached (`<runtime> exec -it <name> bash` from another pane) is kept
- The concretizer, worker, and verification panes are all dead after stop (tmux panes may show exit status or be closed by tmux)
- Memory was recorded in `~/.pm/container-stats.json` with the correct container type (`qa_scenario`) before the stop
- The QA status dashboard (`qa_status.py`) still renders correctly after containers are stopped (it reads `qa_status.json`, not container state)
- When stop-idle-qa is `off`, containers remain running after verdict (existing behavior preserved)

### QA must verify: standalone review container stop edge case

Reviews can run in two modes:
1. **Review loop** (`zz d` / `zzz d`): The loop has explicit verdict detection and a clear completion point in `run_review_loop_sync()`. Stop-on-idle integrates cleanly here.
2. **Standalone review** (plain `d`): The review window is left open indefinitely. The TUI's `_poll_impl_idle` mirrors its transcript verdict (hook-driven `PaneIdleTracker`); stop-on-idle needs a final verdict *and* idle.

QA should verify:
- **Standalone review with `stop-idle-review on`:** After the reviewer emits a final verdict (PASS/LGTM or NEEDS_WORK, not INPUT_REQUIRED) and goes idle, the container is removed. The diff shell pane (host-side, not containerized) remains alive.
- **Review loop with `stop-idle-review on`:** Container is stopped when the loop exits with a final verdict. If the final verdict is INPUT_REQUIRED and the loop is waiting for follow-up, the container is NOT stopped.
- **Review loop with `stop-idle-review off`:** Container remains running after loop completion (existing behavior).
