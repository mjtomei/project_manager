# QA spec: never fall back to host execution when container mode is enabled (pr-574e851)

## Goal

When container mode is enabled, a container-eligible launch that cannot run in
its container (runtime missing / `info` failing or timing out / image or
container create failing / container lost mid-run / resume after a restart)
must **stop with an explicit infrastructure ERROR** that names the original
cause and an actionable remedy. It must never silently run the agent on the
host, never invent a scenario verdict, and never flip the `container-enabled`
setting. Explicitly disabled container mode must keep executing on the host,
and a healthy runtime must keep launching refiner/worker/scenario agents inside
their containers.

This spec is written against the user-visible surfaces: `pm qa run`,
`pm qa debug`, the TUI QA loop (`t` / auto-start), the QA status file
(`qa_status.json`), PR notes, tmux windows, and `pm container status`.

## Grounded code paths (from the diff)

- `pm_core/container.py`: `_runtime_status()` keeps the cause (missing binary,
  `info` timeout, nonzero `info`, `OSError`); `container_preflight_error()`;
  `container_unavailable_message()`; `container_retry_remedy()`.
- `pm_core/qa_loop.py`:
  - `_run_qa_sync` preflight — container mode enabled + unusable runtime now
    aborts with `ERROR` **before** the planner window, Scenario 0, or any
    refiner/worker; writes `qa_status.json` with `overall="ERROR"`, no
    `qa_resume.json`.
  - `_launch_scenarios_in_containers` — a container create/setup failure is
    collected and raised as `ContainerLaunchError` (after prep threads join);
    only the failed container name is removed; already-created containers and
    windows stay.
  - `_execute_and_finalize` — catches `ContainerLaunchError` from
    `_poll_tmux_verdicts` (queued scenarios and relaunches) and publishes
    `ERROR`.
  - `_relaunch_scenario_window(..., use_containers)` — a container run with no
    container, or a container that is no longer running, raises instead of
    relaunching on the host; host runs keep the old behaviour.
  - `_resume_qa_sync` — a snapshot with `use_containers=true` re-validates the
    runtime and aborts `ERROR` if it is unusable; a snapshot with
    `use_containers=false` stays a host run even if container mode is now on.
  - `_fail_run_infrastructure()` — single publisher of the ERROR state
    (`running`/`held` cleared, verdict `ERROR`, one-line `latest_output`,
    full cause+remedy in `_error`, status file).
- `pm_core/cli/qa.py`: `qa_run` prints `qa_error_detail(state)` (cause +
  remedy) after the progress line; `qa_debug` resolves container mode and
  fails closed **before** creating a workdir/clone, and converts any
  `create_qa_container` failure into a message + exit 1 (only its own
  container released).

Intentionally **not** changed (do not assert as bugs): QA Scenario 0, the QA
planner, and the authoring helpers (`pm qa launch/standalone/regression/
author-*`) are host-only roles. On a run that reaches planning, the planner
(and Scenario 0) legitimately run on the host — "zero host launches" in this
spec always means **zero host launches of a container-eligible
refiner/worker/scenario agent**, and, for the fresh-run preflight abort,
zero launches of anything at all.

## Requirements (Given / When / Then)

### R1 — Execution-only `pm qa run` fails closed on an unusable runtime
- **Given** container mode was enabled for this project (`pm container status`
  reports enabled) and the container runtime has since become unavailable,
- **When** the user runs `pm qa run <instruction> --pr <id>` from a pm session,
- **Then**
  - the command prints an explicit error naming the *original cause*
    (runtime binary not found / `info` exited nonzero / `info` timed out),
  - it states that no agent was launched on the host because container mode is
    an execution boundary,
  - it offers both remedies: start/install the runtime and verify
    `<runtime> info`, or deliberately `pm container disable`,
  - the final line is `Result: ERROR`,
  - no QA scenario window is created, and no host agent process is launched,
  - the run's `qa_status.json` has `overall: "ERROR"` carrying the same
    cause+remedy.

### R2 — The fail-closed error is actionable and mode-preserving
- **Given** the R1 failure,
- **When** the user runs `pm container status`,
- **Then** container mode is still reported **enabled** (the run did not flip
  the setting), and the runtime is reported unavailable.

### R3 — Retry after fixing the runtime runs in container mode
- **Given** the R1 failure and a still-enabled setting,
- **When** the user restores the runtime and re-runs the same `pm qa run`
  command,
- **Then** the run proceeds in container mode — it does not abort with the
  fail-closed message, a container launch is attempted for the scenario (the
  runtime receives `run`/`exec` calls; a container window is used), and no
  scenario/refiner agent is executed on the host.

### R4 — Explicitly disabled container mode still runs on the host (control)
- **Given** container mode is explicitly disabled and the runtime is absent,
- **When** the user runs the same QA command,
- **Then** the run executes on the host exactly as before the change: a host
  agent is launched for the scenario and no container-mode error is shown.

### R5 — `pm qa debug` refuses to open a host debug session
- **Given** container mode enabled and the runtime unusable,
- **When** the user runs `pm qa debug <instruction>` (foreground or windowed),
- **Then** it exits nonzero with the cause+remedy message, no QA debug
  workdir/clone is created, no debug window opens, and no agent runs on the
  host.

### R6 — `pm qa debug` reports a container create failure instead of a traceback
- **Given** container mode enabled, the runtime answering `info`, but the
  configured image unusable (e.g. a tag that does not exist),
- **When** the user runs `pm qa debug <instruction>`,
- **Then** it exits nonzero with a message naming the container-creation
  failure and the retry remedy, no traceback-only output, no host agent, and
  the failed container name is not left behind.

### R7 — TUI QA run fails closed at the planning handoff and reports ERROR
- **Given** a project with a PR in `qa`, container mode enabled, runtime down,
- **When** the user starts QA for the PR from the TUI,
- **Then**
  - the TUI log shows a line naming the runtime cause,
  - the run ends `QA finished for <pr>: ERROR` (not INPUT_REQUIRED, not PASS,
    not NEEDS_WORK),
  - the PR gains a `QA ERROR: …` note carrying the cause,
  - no `qa-<pr>`, `qa-<pr>-s0` or `qa-<pr>-s1` window is created, and no
    planner/refiner/worker/Scenario-0 agent runs anywhere,
  - `qa_status.json` records `overall: "ERROR"` with the error text.

### R8 — A fail-closed run is not re-adopted on restart
- **Given** the R7 run already failed closed (completed ERROR, no resume
  snapshot),
- **When** the user restarts the pm session/TUI,
- **Then** the run is not resumed ("Resuming QA for <pr>" does not appear),
  nothing is relaunched, and no host agent starts.

### R9 — A container create failure is an infrastructure ERROR, not a verdict
- **Given** container mode enabled, the runtime answering `info`, but the
  configured image unusable (nonexistent tag),
- **When** the user starts QA,
- **Then**
  - the run ends `ERROR` with a message naming the failed scenario(s), the
    cause, and the retry remedy,
  - the scenario is **not** recorded as INPUT_REQUIRED / PASS / NEEDS_WORK in
    `qa_status.json`, the PR note, or the QA status pane,
  - no refiner/worker runs on the host,
  - the workdir, status file, logs and any already-created containers are
    preserved (no broad cleanup), and the failed attempt's own container is
    gone.

### R10 — Healthy runtime still launches the worker inside its container
- **Given** container mode enabled and a usable runtime/image,
- **When** the user starts QA,
- **Then** the scenario container is created and the scenario window's agent
  command is a container exec (worker runs inside the container), no host
  scenario/refiner agent is launched, and the run proceeds normally.

### R11 — A lost container fails the run closed; a live one is reused
- **Given** a container-mode run with a scenario worker inside its container,
- **When** another actor kills the scenario's tmux window while the container
  is still running,
- **Then** the worker is relaunched inside the *same* container (container
  exec), not on the host.
- **When** another actor instead force-removes the container and its window
  dies,
- **Then** the run ends `ERROR` stating the container is gone, refuses to
  relaunch on the host, and any other scenario's live container and pane are
  left untouched.

### R12 — A queued scenario's container failure also fails the run closed
- **Given** a container-mode run with a concurrency cap so a later scenario is
  queued, and the runtime becomes unusable before that scenario's turn,
- **When** the queued scenario is dequeued,
- **Then** the run ends `ERROR` with the cause; the queued scenario is not
  marked INPUT_REQUIRED, and nothing is launched on the host.

### R13 — Resume preserves the requested execution mode
- **Given** a container-mode run interrupted by a TUI restart and the runtime
  now unusable,
- **When** the TUI restarts and resumes the run,
- **Then** it aborts `ERROR` with the cause+remedy, launches nothing on the
  host, and does not switch the run to host mode.
- **Given** a host-mode run interrupted, with container mode enabled
  afterwards,
- **When** the TUI restarts,
- **Then** the run resumes on the host as originally requested (no
  retroactive containerization, no fail-closed abort).

### R14 — Concurrent runs read the shared setting and never flip it
- **Given** two PRs in `qa`, container mode enabled, runtime down, and an
  isolated `HOME`,
- **When** two QA runs are started at the same time (two panes, or TUI + CLI)
  while a third actor inspects container status,
- **Then** both runs end `ERROR` with their own PR-scoped status files and
  windows (no collisions), zero scenario/refiner host launches occur, and the
  shared `container-enabled` setting file still reads enabled — neither run
  silently disabled container mode to "succeed".

## Setup (cross-cutting)

- Install pm from the PR checkout (`pip install -e .`, or `./install.sh
  --local` when the image has no pm on PATH) and confirm `pm which` points at
  the PR checkout, not a pre-installed copy.
- Throwaway project per scenario (`pm init --backend local --no-import`,
  `pm pr add …`), with at least one PR moved to `status: qa` and a QA
  instruction available (`pm qa list`). Add `nested_podman: true` to the
  project block only if the scenario uses the real inner runtime.
- **Isolation is mandatory (2026-10-28 incident):** export a scratch `HOME`
  (and a private tmux socket / session name) for everything pm reads; confirm
  with `pm container status` and by inspecting `$HOME/.pm/settings` that the
  scratch HOME is in use. Never run `pm container disable`/`enable`, or any
  QA run, against the real host `~/.pm`; never stop the real runtime, kill the
  real tmux session, or remove real containers.
- Container mode is enabled through the normal surface: a runtime stub (or the
  real inner runtime) answers `info` OK, then `pm container enable`; the
  "runtime became unavailable" state is produced afterwards (stub starts
  failing/removed from PATH, or the inner daemon is stopped) — that is the
  realistic "Docker was running yesterday" story and avoids fighting
  `pm container enable`'s own preflight.
- Host-launch detection: put a `claude` stub first on PATH that appends
  `HOST LAUNCH <args>` (plus cwd/prompt path) to a marker file and exits 0.
  Any host execution of an agent shows up there. Note the planner and
  Scenario 0 are intentionally host-only.
- `pm qa run`/`pm qa debug` need a pm session: create one (`pm session`) and
  drive commands from a pane inside it.

## Edge cases

| Situation | Expected |
|---|---|
| Runtime binary missing (configured runtime not on PATH) | ERROR naming the missing binary; no host launch |
| `runtime info` nonzero | ERROR including the first stderr line; no host launch |
| `runtime info` hangs past the 10s timeout | ERROR naming the timeout; no host launch |
| Runtime dies between preflight and container create | ERROR naming the create failure; no host launch, no traceback |
| Image tag does not exist | ERROR naming the image; failed container not left behind |
| Two scenarios, one container fails to create | Run ERROR; the other live container/pane preserved |
| Worker window dies, container alive | Relaunch inside the same container |
| Worker window dies, container removed | Run ERROR; no host relaunch; other scenarios preserved |
| Queued scenario dequeued while runtime is down | Run ERROR; no INPUT_REQUIRED for it |
| Resume snapshot says container, runtime down | ERROR; no host; mode not switched |
| Resume snapshot says host, container mode now enabled | Resumes on the host |
| Container mode disabled, runtime absent | Host execution unchanged |
| Fail-closed run leaves a completed ERROR status | Not resumed/re-adopted on TUI restart |
| User retries after fixing the runtime | Runs in container mode; setting never flipped |

## Pass / Fail criteria

A scenario passes only when the observable evidence shows **both** the
reported behaviour and the *absence* of host execution (empty host-launch
marker for container-eligible agents, no host agent windows, no host agent
process in the scenario pane/`ps`). An ERROR message alone is not a pass; a
host launch appearing alongside it is a hard fail. For controls, the expected
launch (host for disabled mode, container exec for healthy mode) must be
visible. Verdicts must never be invented: `qa_status.json`, the PR note and
the QA status pane must show `ERROR`, not INPUT_REQUIRED/PASS/NEEDS_WORK, for
infrastructure failures.

## Ambiguities (resolved)

- **"Zero host agent launches" vs host-only roles.** The planner and Scenario
  0 are intentionally host-only and run before the scenario launch on a
  healthy run. Resolution: for the fresh-run preflight abort (runtime
  unusable) assert zero launches of *anything*; for create-failure/relaunch
  failures assert zero host launches of container-eligible
  refiner/worker/scenario agents, while the planner/Scenario 0 may have run.
- **How to reach "enabled but runtime unavailable".** `pm container enable`
  refuses when the runtime is down, so tests enable first with a working
  runtime (stub or real inner runtime) and then break it. Directly writing the
  settings file is allowed only as a fallback and must be inside the scratch
  HOME.
- **Fake runtime vs real nested runtime.** Either is acceptable for
  establishing state, provided host-launch detection is independent (a
  `claude` marker stub) and the capture manifest states which was used. Real
  nested podman is preferred for R10/R11 when the scenario image supports it;
  a stub runtime that models container names is acceptable otherwise.
- **`pm qa run` exit code on ERROR.** The command prints `Result: ERROR`; the
  spec does not require a nonzero exit code for `qa run` (only `qa debug` is
  specified to exit nonzero).
- **Auto-start retry loop and `pm pr auto-sequence` ERROR handling** are
  known, separately-filed gaps (pr-7b1dd2e, pr-7abb052). They are out of
  scope here: a scenario must not report them as regressions of this PR, but
  may note them.

No **[UNRESOLVED]** ambiguities.
