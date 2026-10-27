# QA Spec: Container Memory Governor

PR: pr-eb2dbfc — "Container memory governor: dynamic memory limits with per-type stop policy and QA queuing"

Revised 2026-10-27 after the OOM host restart: the governor now fails
closed, measures through the configured runtime (docker or podman),
projects from peaks, counts growth and in-flight reservations, keeps a
host reserve, and never removes a container someone is still using.  See
`pm/specs/pr-eb2dbfc/impl.md` §0.  Earlier QA runs (April) ended
INPUT_REQUIRED and do not approve this revision.

## 1. Requirements

### R1: CLI settings

`pm container set` accepts and validates:
- `system-memory-target <size>` (e.g. `48g`); `off`/`none`/`unset` clears it (governor inactive).  Sizes need a unit: a bare `48` is refused (it would be 48 bytes)
- `system-memory-scope pm|system`
- `system-memory-reserve <size>|<pct>%` (default 10% of host RAM)
- `system-memory-default-projection <size>`, `system-memory-history-size <N>` (N ≥ 1)
- `system-memory-queue-policy fifo|priority-drain|priority-round-robin`
- `stop-idle-impl|stop-idle-review|stop-idle-qa on|off`
- `runtime docker|podman` (master's key, unchanged)

`pm container status` shows the settings, committed usage (`used + expected growth / target`), host free/reserve, the reason when memory is unmeasurable, recently blocked launches, queue depth (excluding entries of dead/expired owners) and stop-on-idle policy.  Malformed `launch-queue.json` / `governor-blocked.json` entries are dropped, never a crash.

Code: `pm_core/cli/container.py:container_set()`, `container_status()`.

### R2: Admission (fail closed)

With a target set, a container launch is admitted only if
`committed usage + in-flight reservations + projection ≤ target` and
host `MemAvailable − growth − in-flight − projection ≥ reserve`.
- Committed usage: pm scope = Σ running pm container usage + growth to each one's projection; system scope = host used + the same growth.
- Projection: p90 of recorded samples (snapshot samples ×1.5), else default projection, else `memory-limit`.
- **Measurement failure refuses**: runtime stats failing, a pm container without a usage figure, unreadable `/proc/meminfo`, invalid target/scope/reserve, or a busy governor lock.  impl/review/signoff/qa-debug fail with a `ContainerError` naming the action and reason; QA scenarios show `waiting_memory` with the reason and retry.
- No target configured → governor inactive, no queue entries, launches unchanged.
- Reusing an already-running container needs no admission.
- The QA planner, verifier and finalizer run on the host and the refiner execs into the already-admitted scenario container, so they create no containers and need no admission.

Code: `pm_core/memory_governor.py:take_snapshot()`, `admit()`, `project_memory()`; `pm_core/launch_queue.py:try_acquire_detailed()`, `enqueue_and_try_acquire()`; `pm_core/container.py:acquire_launch_admission()` (called by `wrap_claude_cmd()` and `pm qa debug`).

### R3: Runtime abstraction

Measurement uses `container._get_runtime()`.  Docker (`1.5GiB`) and Podman (`1.06GB`, SI) units both parse.  Stats use `--format '{{.Name}}|{{.MemUsage}}'` (Podman pads tabs).  Container age parses Docker and Podman StartedAt formats.  End-of-life samples read the cgroup `memory.peak` through `<runtime> exec` (kind `peak`), falling back to a stats snapshot (kind `snapshot`).

### R4: QA admission and waiting

- Initial batch: as many as fit launch; the rest wait at the head of the queue (`waiting_memory` + "waiting for memory: <reason>").
- Scenarios held only by the concurrency cap show `queued` and get **no** queue entry.
- Queued admission retries at most every 15 s while waiting; launches once memory frees.
- Target changes mid-run take effect at the next attempt.
- All of a run's queue entries are released when the loop exits (completion, stop, crash).
- A resumed run (TUI restart) re-joins the queue under the same key and keeps its place.
- The QA status pane counts `waiting_memory` as not complete and shows "N waiting for memory".

Code: `pm_core/qa_loop.py:_admit_initial_batch()`, `_poll_tmux_verdicts()` (`_launch_next_queued`, `_admit_queued_head`), `pm_core/qa_status.py`.

### R5: Stop-on-idle

Removes (not `docker stop`) the exact container of this session, on a background thread, capturing stats first and setting `remain-on-exit` on the session's panes:
- QA (default on): after NEEDS_WORK, after verified PASS, after verification exhausts retries.  Never on INPUT_REQUIRED or while verification is in flight.
- impl (default off): when the impl session goes idle.
- review (default off): when a review loop ends with PASS, NEEDS_WORK or KILLED (pane gone), or a standalone review has a final verdict (PASS/LGTM/NEEDS_WORK) and goes idle.  Not on INPUT_REQUIRED or ERROR, and not when the loop was stopped or superseded.
- `z d`/`zz d` and closing a review window are master lifecycle, not stop-on-idle: killing the window runs the exec EXIT trap (`rm -f`), which removes `review-<pr>` whatever the policy, and each fresh review (`pm pr review --fresh`, so every loop iteration) recreates it — the container ID changes.  The stale stop thread pins the container ID it first saw, so it never removes the replacement container under the same name (impl.md §0, review 3f45 i1/i2).
- After a stop, plain `s` / `d` on that PR close the dead-pane window and relaunch (new container ID); `zz d` pressed while `z d`'s fresh review is still launching shows "Busy: Reviewing <pr> (fresh)" and must be pressed again once it opens.
- Kept also when the pane that went idle now runs a different Claude session than the one whose verdict/idle triggered the stop (window reused).
- Kept when: another exec session is open in the container (someone attached), ownership can't be determined, or the transcript changed since the idle/verdict point.
- Timing (QA): counted from the verdict the loop *records* in `qa_status.json`, not from when the pane prints it — the poll loop starts verdict polling only after every scenario launched plus the 30 s grace, then needs two stable polls.
- Samples: every removal of a *running* pm container records an end-of-life sample — stop-on-idle, `pm container cleanup`, `pm pr cleanup --resources`, and the stale cleanup at the start of a fresh QA run (`z t`).  No re-baseline; expect one sample per running container removed.

Code: `pm_core/container.py:stop_idle_in_background()`, `stop_container()`, `foreign_exec_sessions()`; callers in `qa_loop.py`, `review_loop.py`, `tui/review_loop_ui.py`.

### R6: TUI status bar

`mem 34G/48G (pm)` / `(sys)`, next to the AUTO/WCH indicators; `mem ?/48G (pm) unmeasurable` on failure; `blocked: <action> [+N]` for launches refused in the last 10 min.  Computed off the UI thread every 15 s — the status bar never runs `docker/podman stats` inline.

Code: `pm_core/memory_governor.py:compute_memory_status()`, `format_memory_status()`, `pm_core/tui/app.py:_refresh_memory_status()`, `pm_core/tui/widgets.py`.

## 2. Setup

- Container runtime: rootless Podman is the primary target (verify `podman info --format '{{.Host.Security.Rootless}}'` is `true`); Docker where available.
- tmux; pm from this branch (`PYTHONPATH=<checkout>` — `/opt/pm-src` shadows the checkout in pm containers).
- Use a throwaway `~/.pm` settings dir or restore settings afterwards; `pm container set system-memory-target off` disables the governor.
- Nested rootless Podman without cgroup delegation (pm dev containers) reports the enclosing cgroup for every inner container — usage sums overcount; prefer `system-memory-scope system` there, and note it in results.
- To force a stats failure: run a pm-named container with `--cgroups=disabled` (`podman stats` then fails for all containers, rc=125).
- Keep fixture pressure bounded: a few small containers (e.g. `alpine sleep`) and a low target are enough; do not launch large worker fan-outs.
- Fail-closed display shows only in pm scope: in system scope a stats failure falls back to `<runtime> ps` and counts each running pm container at its full projection, so the bar stays measured.
- Under nested podman every inner container reports the outer cgroup, so per-container growth shrinks for all N containers as outer usage rises; use generous margins for "exactly one launch per raise" checks.
- Lock-busy refusals are not written to `governor-blocked.json` (recording needs the same lock); they show only in the error/log.
- `pm qa debug` admission needs `nested_podman: true`, a committed repo, an instruction, and an image that exists locally (e.g. `docker.io/library/debian:bookworm-slim`); pre-build pm-dev with `pm container build-base` before TUI launches (300 s start timeout).
- `pm container set system-memory-history-size -3` is parsed by click as an option; use `-- -3` to reach the validator.
- fake-claude can't hold a review loop at INPUT_REQUIRED (pr-3c90e34); a standalone review or a QA scenario can.

## 3. Edge Cases

- E1: Projection > target → impl/review/signoff/qa-debug get the `check_single_container_fits` error, no wait loop; QA scenarios wait with that message as the reason (raising the target mid-run lets them launch).
- E2: All initial QA scenarios blocked → all `waiting_memory` with reason; launch as memory frees.
- E3: INPUT_REQUIRED containers hold memory → waiting reason names how many are held; no deadlock beyond needing the user.
- E4: Concurrent admission across two pm processes/sessions → one walk at a time under `~/.pm/governor.lock`; grants never overlap headroom.
- E5: Stats file / queue file corruption → reset, no crash.
- E6: Runtime stats fail → launches refused / QA waits, reason visible in CLI, status bar and QA pane (**not** allowed).
- E7: Governor lock held by another process past 30 s → refused with "lock busy", no unlocked admission.
- E8: Target changed mid-QA-run → next attempt uses it.
- E9: Unknown container names → no stats recorded, no crash.
- E10: History trimming keeps newest N samples.
- E11: Someone attached (`podman exec -it <name> bash`) to a finished scenario container → stop-on-idle keeps it.
- E12: Crashed/restarted pm process → its waiting entries expire or are adopted by the resumed run; its acquired reservations end when the container runs or after 30 min.  A crashed QA thread in a live TUI releases its run's entries at once.

## 4. Pass/Fail Criteria

### Pass
- Unit tests: `tests/test_memory_governor.py`, `tests/test_launch_queue.py`, `tests/test_qa_memory_governor.py`, `tests/test_container.py`, `tests/test_cli_container.py`, `tests/test_tui_imports.py`.
- Live on rootless Podman: usage/peak/age measured; a stats failure refuses admission with the reason; attached container kept, unattached one removed with a `peak` sample recorded.
- QA scenarios queue/wait/launch per R4; waiting reason shown.
- Stop-on-idle per R5, never on INPUT_REQUIRED or during verification, never with a foreign exec session.
- Status bar per R6 with no UI stall.

### Fail
- Any launch admitted while memory is unmeasurable, the lock is busy, or the target is invalid.
- A failed measurement displayed or counted as 0.
- Scenarios held by the concurrency cap reserving memory (queue entries).
- Queue entries left behind after a QA loop exits.
- A container removed while someone has an exec session open in it, during INPUT_REQUIRED, or during verification.
- Another session's container removed by stop-on-idle.
- The TUI blocking on `<runtime> stats`.

## 5. Ambiguities

### A1: "Stop" vs "remove"
Removal (`rm -f`) after capturing stats; the bind-mounted workdir keeps project state.  Unchanged from the April implementation.

### A2: `waiting_memory` vs `queued`
`waiting_memory` only when the governor refused the head of the queue; scenarios waiting for a concurrency slot show `queued`.

### A3: Retry timing
At most every 15 s while waiting (each attempt measures runtime stats); immediately after a scenario finishes if no attempt is pending.

### A4: Standalone review stop-on-idle
Master's hook-driven review pass mirrors the review verdict (PASS — what the review prompt asks for — LGTM, NEEDS_WORK, INPUT_REQUIRED; master only matched LGTM, fixed here); stop-on-idle fires on the first idle with a final verdict that isn't INPUT_REQUIRED.

## 6. Mocks

### MOCK: container-runtime
**Dependency:** `docker`/`podman` CLI (`stats`, `ps`, `inspect`, `exec cat /sys/fs/cgroup/memory.peak`).
**Contract:** unit tests patch `subprocess.run` in `pm_core.memory_governor` or the snapshot functions; live QA uses the real runtime.
**What remains unmocked:** parsing, projection, admission, queue walk.

### MOCK: governor-state
**Dependency:** `~/.pm` (settings, `launch-queue.json`, `container-stats.json`, `governor-blocked.json`, `governor.lock`).
**Contract:** `tests/conftest.py:_isolated_memory_governor` redirects all of it to a temp dir for every test.

### MOCK: tmux-panes
**Dependency:** tmux (`display-message`, `set-option`, `find_window_by_name`, `get_pane_indices`).
**Contract:** unit tests mock them; live QA uses a real tmux server (own socket).
