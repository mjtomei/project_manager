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

**Integration note (2026-10-31).** This branch now contains #249
(pr-592e4bd) merged from `master@eaf3372e`. Earlier QA verdicts were
recorded against pre-integration revisions and are historical; a fresh QA
sequence runs against the combined head. The integration keeps every
fail-closed path above and adds #249's container-recreation on relaunch
(see R11): a lost container that can be recreated is recreated, not failed;
only an unrecreatable one ends the run `ERROR`. #249's new queued-status,
in-window relaunch, resume-ownership and provider-routing behaviour must
keep working alongside the fail-closed boundary.

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
    container name raises instead of relaunching on the host; a container that
    is no longer running is recreated under the same name (master's S78
    `_ensure_scenario_container`), and only if that recreation fails does it
    raise `ContainerLaunchError` (never a host relaunch, never an invented
    verdict). Host runs keep the old behaviour.
  - `_resume_qa_sync` — a snapshot with `use_containers=true` re-validates the
    runtime and aborts `ERROR` if it is unusable; a snapshot with
    `use_containers=false` stays a host run even if container mode is now on.
  - `_fail_run_infrastructure()` — single publisher of the ERROR state
    (`running`/`held` cleared, verdict `ERROR`, one-line `latest_output`,
    full cause+remedy in `_error`, status file).
  - `_launch_scenarios_in_containers` also fails the run closed when the
    scenario *window* cannot be created after its container exists (same
    `ContainerLaunchError`, only that attempt's container released) — the
    container exists but nothing can run in it.
  - `_write_resume_file` / `build_resume_state` — the resume snapshot now
    carries `error`, so a resumed run keeps its original diagnostics and an
    errored run with no scenario verdicts cannot re-aggregate as `PASS`
    after a restart.
  - `_record_qa_note` (TUI) — a mid-run `ERROR` (a queued scenario's create
    failure, or a relaunch whose container is gone, after another scenario
    already has a verdict) appends the cause+remedy to the `QA ERROR` note;
    `_resume_incomplete_qa` restores the error from `qa_status.json` when it
    adopts a run that completed during downtime.
  - Queued-status wiring (`_status_scenarios`, `_queued_indices`) — the
    status write performed *during* the initial launch keeps the
    not-yet-started scenarios listed as `queued`, for the container **and**
    host launchers (the launch batch no longer narrows the status file).
- `pm_core/cli/qa.py`: `qa_run` prints `qa_error_detail(state)` (cause +
  remedy) on stderr after the progress line and exits nonzero when the
  result is `ERROR` (a completed PASS/NEEDS_WORK/INPUT_REQUIRED still exits
  0); `qa_debug` resolves container mode and fails closed **before**
  creating a workdir/clone, and converts any `create_qa_container` failure
  into a message + exit 1 (only its own container released).
- `pm_core/qa_status.py` `_render` — the QA status dashboard's ERROR block
  wraps each cause/remedy line to the pane width (indent preserved) instead
  of letting a ~190-column fail-closed line wrap on its own and scroll the
  pane's own `QA Status: <pr>` header off the top (fix d70a3138, found by
  QA scenario 9). An ERROR status renders the header, the wrapped block and
  the `q: quit` hint only — the scenario table is not drawn while `error`
  is set.

Intentionally **not** changed (do not assert as bugs): QA Scenario 0, the QA
planner, the QA verifier and finalizer, and the authoring helpers (`pm qa
launch/standalone/regression/author-*`) are host-only roles. On a run that
reaches planning, the planner (and Scenario 0) legitimately run on the host —
"zero host launches" in this spec always means **zero host launches of a
container-eligible refiner/worker/scenario agent**, and, for the fresh-run
preflight abort, zero launches of anything at all.

## Status of the earlier QA runs (2026-10-29)

The first QA run drove scenarios 1–7 and covered R1–R14: six PASS, one
NEEDS_WORK (a queued scenario vanished from `qa_status.json` — fixed in
`868d48e8`). After that run, i4/i6 (`pm qa run` prints the cause and exits 1
on `ERROR`; the QA note carries a mid-run cause), `868d48e8` (queued rows
persist) and c534 i1 (window-create failure fails closed; resume keeps the
error; a recovered `ERROR` keeps its cause) landed.

The second QA run drove scenarios 8–10: R15 PASS, R11/R16 NEEDS_WORK, and
the scripted-entry-point exit codes PASS. Scenario 9's only failure was the
QA status pane: the ~190-column fail-closed cause line wrapped on its own in
the ~100-column status pane, adding rows and scrolling the `QA Status: <pr>`
header off the top. Fixed in `d70a3138` (wrap the error block to the pane
width, indent preserved, regression test at 60/80/100/120 columns). The
run's other checks (relaunch inside the same container; lost container fails
closed with cause in the log, status file and a single QA ERROR note; TUI
restart does not resume or re-run) passed.

The locked scenarios 1–10 are not re-emitted. New scenarios cover the
pane-wrap fix, the runtime-cause variants not yet driven end to end (timeout,
unexecutable runtime), the healthy `pm qa debug` control, and the adjacent
shared-launcher (review) fail-closed behaviour.

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
  - the full cause+remedy is also printed (on stderr) after the progress
    line, not only the one-line progress entry,
  - the final line is `Result: ERROR` and the command exits nonzero, so a
    scripted caller cannot read the infrastructure failure as success,
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
  - the same holds when the container is created but its scenario *window*
    cannot be created (the pm session is gone or tmux refuses the window):
    the run ends ERROR, no INPUT_REQUIRED is invented, and only that
    attempt's container is released,
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
  dies, and the container *can* be recreated from the scenario's host clone,
- **Then** it is recreated under the same name and the worker is relaunched
  inside it (still container mode, never the host) — this is #249's S78
  recreation, kept by the integration and not a downgrade.
- **When** the container cannot be recreated (e.g. its host clone is also
  gone, or the runtime is unusable), and its window dies,
- **Then** the run ends `ERROR` stating the container is gone and could not
  be recreated, refuses to relaunch on the host, and any other scenario's
  live container and pane are left untouched.

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

### R15 — Queued scenarios stay visible from the initial launch
- **Given** a QA plan with more scenarios than the concurrency cap
  (`qa-max-scenarios`, e.g. 1) and container mode enabled (and, as a control,
  container mode disabled),
- **When** the user starts QA and the first batch launches,
- **Then** the QA status pane and `qa_status.json` list **every** planned
  scenario from the start — the launched ones as pending/running and the rest
  as `queued` — and the queued rows do not disappear when the launch step
  rewrites the status file; as each queued scenario is dequeued it flips to
  running and launches in its own container (or on the host in the disabled
  control).

### R16 — A mid-run infrastructure ERROR keeps its cause in the note and across a restart
- **Given** a container-mode run where a container fails **after** another
  scenario already has a verdict (a lost container, or a queued scenario's
  create failure),
- **When** the run fails,
- **Then** the `QA ERROR` note on the PR carries the cause and the retry
  remedy (not a bare per-scenario summary with no reason), `qa_status.json`
  records `overall: "ERROR"` with the same error text, and the QA status pane
  shows the error block.
- **Given** that failed run and a TUI restart,
- **When** the TUI comes back (whether or not it processed the completion
  before it died),
- **Then** the recovered run still carries the cause, is not re-adopted or
  re-run, and no host agent starts.

### R17 — The QA status pane keeps its header and wraps the fail-closed ERROR
- **Given** a container-mode TUI QA run that ended `ERROR` while its QA
  window and status pane are open (a mid-run container failure, so the pane
  exists),
- **When** the user looks at the QA status pane,
- **Then**
  - the pane still shows its `QA Status: <pr>` header at the top,
  - the `ERROR` block's long cause and remedy lines are wrapped inside the
    pane width — no line spills past the right edge and no line's natural
    wrap pushes the header off the top,
  - the full cause and both retry remedies (fix the runtime / `pm container
    disable`) are readable, with the remedy bullets' indent preserved,
  - the `q: quit` hint is visible,
- **Given** the same pane,
- **When** the user narrows it (a few widths, e.g. ~100, ~80, ~60 columns),
- **Then** the header stays visible and every error line still fits the
  pane width at each size.

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
| Worker window dies, container removed but recreatable | Container recreated (same name); worker relaunched inside it; never the host |
| Worker window dies, container removed and not recreatable | Run ERROR (cause + remedy); no host relaunch; other scenarios preserved |
| Queued scenario dequeued while runtime is down | Run ERROR; no INPUT_REQUIRED for it |
| Capped run launches its first batch | Status pane/`qa_status.json` keep every planned scenario; the rest show `queued` |
| Container exists but its window cannot be created | Run ERROR; only that container released; no INPUT_REQUIRED |
| Container lost after another scenario already has a verdict | Note and status carry the cause+remedy, not a bare per-scenario summary |
| Fail-closed ERROR block longer than the status pane | Wrapped within the pane width; `QA Status: <pr>` header stays visible |
| Scenario workdir *clone* fails in container mode | Deliberately INPUT_REQUIRED (nothing was allocated, no host launch); not a launch ERROR |
| A review/signoff refiner launch while the runtime is down | Fails with a container-creation error and `pm container disable` guidance; no host refiner |
| TUI restarts after a mid-run ERROR | Recovered ERROR keeps its cause; not re-run; no host launch |
| `pm qa run` ends ERROR | Cause+remedy printed, `Result: ERROR`, exit code nonzero |
| `pm qa run` completes with a verdict | Exit code 0 (PASS / NEEDS_WORK / INPUT_REQUIRED) |
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
- **`pm qa run` exit code on ERROR (resolved by i6).** The command now prints
  the cause+remedy and exits nonzero when the result is `ERROR`; a completed
  verdict (PASS / NEEDS_WORK / INPUT_REQUIRED) still exits 0. Scenarios
  should assert both — a scripted caller depends on it.
- **Queued-status visibility (resolved by `868d48e8`).** The earlier QA run's
  NEEDS_WORK scenario found queued scenarios vanishing from `qa_status.json`
  during the initial launch. That is fixed and covered by R15; a queued row
  with an empty verdict in an `ERROR` status file is not a regression.
- **Auto-start retry loop and `pm pr auto-sequence` ERROR handling** are
  known, separately-filed gaps (pr-7b1dd2e, pr-7abb052). They are out of
  scope here: a scenario must not report them as regressions of this PR, but
  may note them.
- **A container-mode scenario whose workdir clone fails** (before any
  container is created) is deliberately recorded `INPUT_REQUIRED`, not a
  launch ERROR: nothing was allocated, so there is no container to leak and
  no host launch to refuse (impl.md i6). Only failures *after* a container
  is allocated (create/setup, or the window for an existing container) are
  launch ERRORs. Do not assert ERROR for a clone failure.
- **The QA status pane in an ERROR state shows the header + error block +
  `q: quit`, not the scenario table** (`_render` returns after the error
  branch). Per-scenario verdicts are asserted from `qa_status.json`, not
  from the pane.

No **[UNRESOLVED]** ambiguities.
