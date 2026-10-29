# Spec: never fall back to host execution when container mode is enabled (pr-574e851)

## Goal

Make "container mode enabled" an **execution boundary** for every
container-eligible launch. When the container runtime is missing, `info`
fails or times out, or a container cannot be created / is lost, the launch
must **stop with an explicit infrastructure error** — never silently run the
agent on the host, never fabricate a scenario/reviewer verdict, never flip
the global setting.

This is a focused completion of the fail-closed work begun in `16735789`
(shared launcher hard-fails on container creation), not a redesign of all PM
roles and not whole-session containerization.

## Confirmed downgrade paths (grounded)

All line numbers are on this workdir's base (`4a74d880`).

### P1 — QA run preflight (the primary bug)

`pm_core/qa_loop.py:4567-4575` (`_run_qa_sync`):

```python
use_containers = is_container_mode_enabled()
if use_containers:
    if _runtime_available():
        _log.info("Container mode enabled for QA execution")
    else:
        _log.warning("Container mode enabled but runtime unavailable "
                     "— falling back to host execution")
        use_containers = False
```

`use_containers` then selects `_launch_scenarios_in_tmux` (host refiners +
workers) at `qa_loop.py:5013-5020`, and is persisted as
`use_containers=False` in `qa_resume.json` by `_write_resume_file`
(`qa_loop.py:935-955`). A missing binary, nonzero `runtime info`, or a 10 s
timeout therefore launches the refiner and worker **on the host**.

### P2 — Scenario relaunch/retry

`pm_core/qa_loop.py:2898-2911` (`_relaunch_scenario_window`):

```python
use_containers = is_container_mode_enabled() and _runtime_available()
...
session=None if (use_containers and scenario.container_name) else session,
```

`_build_scenario_run_cmd` (`qa_loop.py:2800-2875`) decides container vs host
from `bool(scenario.container_name)`, so a scenario with **no** container name
(a launch that failed to create one) is host-relaunched by this retry path.
The runtime check also silently changes prompt shape. `_relaunch_scenario_window`
is called from `_poll_tmux_verdicts` at `qa_loop.py:3812`, which has
`use_containers` in scope but does not pass it.

### P3 — Execution-only `pm qa debug`

`pm_core/cli/qa.py:506`:

```python
use_containers = is_container_mode_enabled() and _runtime_available()
```

With the runtime down, `pm qa debug` launches the instruction on the host
(`cli/qa.py:550-590`). `pm qa run` itself goes through P1.

### P4 — Container create/setup failure is reported as a verdict

`pm_core/qa_loop.py:2645-2665` (`_launch_scenarios_in_containers._prepare_scenario`):

```python
except Exception:
    _log.error("Failed to create container for scenario %d — aborting scenario",
               scenario.index, exc_info=True)
    return
```

The scenario then has no window, so `_poll_tmux_verdicts`
(`qa_loop.py:3390-3402`) records **INPUT_REQUIRED** — an invented verdict for
an infrastructure failure. The same happens for a queued scenario at
`qa_loop.py:3446-3458` ("window creation failed — marking INPUT_REQUIRED").

### P5 — Resume does not re-check the requested mode

`pm_core/qa_loop.py:5358`: `use_containers = bool(resume_data.get("use_containers", False))`
is honored, but nothing validates that the runtime is usable before
`_execute_and_finalize` re-enters the queued/relaunch paths. A run persisted
with `True` (once P1 stops writing `False`) can resume into P2/P4.

### Already fail-closed (no change required, verify only)

- `wrap_claude_cmd` (`container.py:1134-1255`) returns the command unchanged
  only when `is_container_mode_enabled()` is **False**; otherwise it creates a
  container and raises `ContainerError` on failure. Callers:
  - sign-off: `signoff.py:505-540` (prints, returns)
  - review: `cli/pr.py:1418-1428` (`SystemExit(1)`)
  - impl: `cli/pr.py:1179-1181`
- `create_qa_container` / `create_container` (`container.py:634,1259`) raise on
  image-missing, `runtime run` nonzero, setup timeout (`ContainerError`).
- `build_exec_cmd` (`container.py:1050`) only ever emits `<runtime> exec`.
- `pm container enable` (`cli/container.py:44-56`) already refuses when the
  runtime is unavailable.

### Out of scope (intentionally host-only / not a downgrade)

- QA Scenario 0 (`qa_loop.py:2140-2145`: "always runs on the host").
- QA planner (`qa_loop.py:4600-4675`, built unwrapped).
- QA verifier (`_verify_single_scenario`, `qa_loop.py` — `build_claude_shell_cmd`
  into a split pane in the PR workdir, never wrapped) and QA finalizer
  (`_run_qa_finalize_pane`, likewise unwrapped). Neither ever consults
  container mode, so neither can "downgrade"; they are host-only roles like
  the planner, and are left as-is by this PR.
- `pm qa launch`, `pm qa standalone`, `pm qa regression`, `pm qa author-*`
  (`cli/qa.py:599,690,305,234`) never consult container mode; they are
  authoring/host helpers, not container-eligible launchers, and do not
  "downgrade" based on runtime state.
- Container memory governor, providers/models, automatic merges.

## Requirements

### R1 — Runtime preflight fails closed, with cause and remedy

Add to `pm_core/container.py`:

```python
def _runtime_status() -> tuple[bool, str]:
    """(available, problem). problem is a short human diagnostic."""
    # mirrors _runtime_available but keeps the cause:
    #   FileNotFoundError -> "'<runtime>' was not found on PATH"
    #   TimeoutExpired    -> "'<runtime> info' timed out after 10s"
    #   OSError           -> "could not run '<runtime> info': ..."
    #   returncode != 0   -> "'<runtime> info' exited N: <first stderr line>"

def _runtime_available() -> bool:
    return _runtime_status()[0]

def container_preflight_error() -> str | None:
    """None when container mode is disabled or usable; else the problem."""
    if not is_container_mode_enabled():
        return None
    ok, problem = _runtime_status()
    return None if ok else problem

def container_unavailable_message(problem: str) -> str:
    """Actionable multi-line error: cause + 'no host fallback' + remedy."""
```

`container_unavailable_message` must name the runtime and give two remedies:
start/install the runtime and verify `<runtime> info`, **or** deliberately
`pm container disable`. It must state that no agent was launched on the host
because container mode is an execution boundary.

The `To retry:` block is factored into
`container_retry_remedy(first_step)` so the four fail-closed messages (runtime
preflight, container create failure, relaunch with no container, relaunch with
a lost container) cannot drift apart; each passes only its own first bullet.

### R2 — `_run_qa_sync` aborts before any window/agent when the runtime is unusable

Replace P1. Keep `use_containers = is_container_mode_enabled()` (the
**requested** mode). If enabled and `_runtime_status()` fails:

- `state.running = False`
- `state.latest_verdict = "ERROR"`
- `state.latest_output` = one-line cause
- `state._error` = `container_unavailable_message(problem)`
- write `qa_status.json` with `overall="ERROR"`, `error=state._error`
- `on_update(state)` and return.

No `_launch_scenario_0`, no planner window, no refiner/worker. (Scenario 0
and the planner are host-only roles, but the run-level preflight aborts before
them so the acceptance's "ZERO host agent launches" holds literally.)

Do **not** write `qa_resume.json` on this abort (nothing launched; a resume
would re-enter an empty execution phase). The setting is not touched, so a
retry re-runs the same preflight in container mode.

### R3 — Container create/setup failure is an infrastructure ERROR, not a verdict

In `_launch_scenarios_in_containers`:

- add a `failures: list[tuple[int, BaseException]]` guarded by `pending_lock`.
- on `create_qa_container` failure, best-effort remove **only that exact**
  container name (`remove_container(cname)`, wrapped in try/except — a
  missing runtime makes `_run_runtime` raise), record `(index, exc)`, and
  return from the prep thread.
- after prep threads join, if `failures`: raise `ContainerLaunchError` with a
  message that includes each scenario index, the exception text, and the
  actionable remedy. Live containers/windows already created for other
  scenarios are **not** torn down.

Define `class ContainerLaunchError(RuntimeError)` in `qa_loop.py`.

Callers:

- `_run_qa_sync` launch block (`qa_loop.py:5010-5020`): wrap in
  `try/except ContainerLaunchError`; restore `state.scenarios` in `finally`;
  set ERROR fields, write status, notify, return (no finalize pane).
- `_execute_and_finalize` (`qa_loop.py:5041`): wrap the
  `_poll_tmux_verdicts(...)` call; on `ContainerLaunchError` set
  `running=False`, `held=False`, `latest_verdict="ERROR"`, `_error`, notify,
  write status with `overall="ERROR"`, and return. This covers queued
  scenarios launched from `_launch_next_queued` (`qa_loop.py:3446-3458`),
  whose "window creation failed → INPUT_REQUIRED" branch must no longer be
  reachable for container create failures (the raise precedes it).

### R4 — Relaunch fails closed on a missing/lost container

Change `_relaunch_scenario_window(..., use_containers: bool)` and pass the
run's `use_containers` from `_poll_tmux_verdicts`:

- `use_containers and not scenario.container_name` → raise
  `ContainerLaunchError` (a container run has no host fallback).
- `use_containers and scenario.container_name`: verify
  `container_is_running(name)` (try/except; any exception = not running).
  If not running → raise `ContainerLaunchError` ("container … is no longer
  running; refusing to relaunch the worker on the host").
- host runs (`use_containers` False) keep the existing host relaunch.
- pass `session=None if scenario.container_name else session` to
  `_build_scenario_run_cmd` (do not consult the runtime to shape the prompt).

The raise propagates through `_poll_tmux_verdicts` to the
`_execute_and_finalize` handler from R3.

### R5 — Resume preserves and validates the requested mode

In `_resume_qa_sync`, after reading `use_containers` from the snapshot
(`qa_loop.py:5358`):

- if `use_containers` is True and `_runtime_status()` fails → `_abort(...)`
  with `container_unavailable_message`, and set `state._error` so diagnostics
  survive. Do not enter `_execute_and_finalize`; do not relaunch on host.
- if the snapshot says False, keep host execution even if container mode is
  now enabled (the run's mode was explicitly host; live host workers are not
  retroactively containerized).

Extend the local `_abort` helper with an optional `error: str | None = None`
that also sets `state._error`.

### R6 — `pm qa debug` fails closed

In `qa_debug` (`cli/qa.py:438`), move the mode decision before creating the
QA workdir/clone:

```python
use_containers = is_container_mode_enabled()
if use_containers:
    problem = container_preflight_error()   # or _runtime_status()
    if problem:
        click.echo(container_unavailable_message(problem), err=True)
        raise SystemExit(1)
```

Then proceed with the existing container branch. No host claude launch.

### R7 — Preserve evidence and allocations

- Never call broad cleanup (`cleanup_qa_containers`, `cleanup_*_containers`,
  `tmux kill-*`) on the error paths.
- The only removal is R3's exact failed container name.
- Captures, transcripts, workdirs, unsent drafts and live containers are left
  in place. The TUI records the ERROR verdict/note via the existing
  `_on_qa_complete` "else" branch (`tui/qa_loop_ui.py:1011`).

## Implicit requirements

1. **ERROR must not be reclassified.** `_execute_and_finalize`'s aggregation
   maps `state._error` → INPUT_REQUIRED (`qa_loop.py:5104`). Container
   failures must return before that aggregation (R2/R3), so the published
   verdict is `ERROR`. Do not set `_error` and then fall into aggregation.
2. **The resume snapshot must not resurrect a downgrade.** Because R2 leaves
   `use_containers` True, `_write_resume_file` stores True; a restart during a
   container run resumes in container mode or fails closed (R5).
3. **No settings mutation.** Nothing in the fix calls `set_global_setting`;
   the `container-enabled` value is only read. Tests must isolate `HOME` so a
   scratch project cannot write the real global setting (the 2026-10-28
   incident).
4. **Health control.** Healthy runtime must still call
   `_launch_scenarios_in_containers` (refiner + worker in-container), and
   disabled mode must still call `_launch_scenarios_in_tmux`.
5. **Status/UX.** Errors are written to `qa_status.json` (error field) and
   surfaced through `latest_output`/`_error` so the TUI log and PR note show
   the cause and remedy.

## Ambiguities and resolutions

- **[RESOLVED] Whole-run abort vs per-scenario failure.** Abort the run with
  `ERROR` on a runtime preflight failure or a container create failure. This
  is the only shape that guarantees zero host launches and no invented
  verdict without redesigning verdict aggregation. Already-running container
  workers are preserved (not killed) for inspection.
- **[RESOLVED] Resume mode when the setting changed mid-run.** Honor the
  persisted per-run `use_containers`. True → require the runtime; False →
  keep host. The setting itself is never flipped.
- **[RESOLVED] Exec failure.** Container exec is validated during
  `create_container` (the readiness-sentinel `exec` loop). A later exec
  failure that leaves the container running is a worker failure, not a
  container-mode downgrade, and it never host-launches because
  `build_exec_cmd` only emits `<runtime> exec`. Container **loss** is
  detected on relaunch (R4) and reported as infrastructure ERROR.
- **[RESOLVED] Host-only roles.** Scenario 0, the QA planner and the QA
  authoring helpers stay on the host. They are not container-eligible and
  are not downgrade paths.

No **[UNRESOLVED]** ambiguities.

## Edge cases

| Situation | Expected |
|---|---|
| enabled + runtime missing / `info` nonzero / timeout, fresh run | ERROR before any window; no host claude; no resume snapshot |
| enabled + healthy runtime | refiners/workers launch via `_launch_scenarios_in_containers` |
| disabled + runtime missing or healthy | host execution unchanged |
| enabled + create/setup failure (image missing, run nonzero, setup timeout) | ERROR; exact failed container best-effort removed; live containers preserved; no INPUT_REQUIRED |
| enabled + scenario window cannot be created after its container exists | ERROR (same launch-failure path); that container released; no INPUT_REQUIRED, no leak |
| enabled + queued scenario create failure | ERROR from inside `_execute_and_finalize`; no host launch |
| enabled + worker pane dies, container still running | existing retry → relaunch in the same container |
| enabled + worker pane dies, container gone | `ContainerLaunchError` → ERROR, no host relaunch |
| enabled + resume snapshot True + runtime now down | ERROR via `_abort`; no host; `_error` preserved |
| enabled + resume snapshot False | host resume (run mode preserved) |
| disabled + resume snapshot False | host resume unchanged |
| `pm qa debug` enabled + runtime down | exit 1 with remedy; no clone/claude launch |
| `pm container status` enabled + runtime down | unchanged warning |
| stop requested during prep | no failure recorded; existing stop path |

## Implementation plan

1. `pm_core/container.py`: `_runtime_status`, `_runtime_available` wrapper,
   `container_preflight_error`, `container_unavailable_message`.
2. `pm_core/qa_loop.py`:
   - `class ContainerLaunchError(RuntimeError)`.
   - R2 preflight in `_run_qa_sync`.
   - R3 failure capture + raise in `_launch_scenarios_in_containers`; catch in
     `_run_qa_sync` and `_execute_and_finalize`.
   - R4 `_relaunch_scenario_window(..., use_containers)` + caller.
   - R5 resume preflight + `_abort(error=...)`.
3. `pm_core/cli/qa.py`: R6.
4. Tests (new file `tests/test_container_fail_closed.py` plus additions to
   `tests/test_container.py`):
   - `_runtime_status` cause strings (missing binary, timeout, nonzero).
   - P1 regression: `_run_qa_sync` with enabled+unavailable → ERROR,
     `_launch_scenarios_in_tmux` / `_launch_scenario_0` / `_launch_scenarios_in_containers`
     never called (fails on pre-fix because `_launch_scenarios_in_tmux` is called).
   - P3 regression: `_relaunch_scenario_window` container run with no/lost
     container → raises, `tmux.new_window_get_pane` not called.
   - P4 regression: create failure → `ContainerLaunchError` and
     `_execute_and_finalize` publishes ERROR, not INPUT_REQUIRED.
   - P5 regression: resume True + runtime down → ERROR, `_execute_and_finalize`
     not called.
   - `pm qa debug` CliRunner: exit 1, message, `build_claude_shell_cmd` not called.
   - Healthy/disabled controls.
5. Manual repro (below) before/after; captures under
   `$(pm qa captures-path pr-574e851)/impl/{pre,post}-fix/`.

## Manual repro plan (disposable, container-local)

Never touch the host's real settings/tmux/containers. Everything under a
scratch dir with its own `HOME`, `PATH`, tmux socket and fake runtime.

1. Scratch `HOME=$SCRATCH/home`; write `home/.pm/settings/container-enabled`
   = `true` (or use `PM_PROJECT` + a scratch project) and
   `container-runtime` = `podman`.
2. Fake `podman` on `PATH` first: `info` exits 1 (also a variant that exits 0
   for the healthy control). Fake `claude` on `PATH` first: appends
   `HOST LAUNCH <args>` to `$SCRATCH/host-launch.log`, exits 0.
3. Disposable project repo `$SCRATCH/repo` with `pm/project.yaml` (one
   `status: qa` PR whose `workdir` is a clone), `pm/qa/instructions/repro.md`,
   and a committed branch so `create_scenario_workdir` can clone.
4. Private tmux: `tmux -L qa574 new-session -d -s pm-repro574`.
5. Record with `asciinema rec` inside a pane (cli-recording recipe) while
   running the native entry point: `pm qa debug repro --foreground`
   (pre-fix: fake claude runs and writes the marker) and `pm qa run repro --pr <id>`
   (pre-fix: refiner/worker windows launch on host).
6. Post-fix: same commands; expect the ERROR message and **no**
   `host-launch.log` entry. Render `.cast` → `.mp4` with `agg`+`ffmpeg`.

If the full CLI repro is blocked (tmux/pm-session plumbing inside this impl
container), fall back to a direct `_run_qa_sync`/`_relaunch_scenario_window`
driver script that uses the same fakes and still asserts absence of host
launch, and note the substitution in the capture manifest.

## Review iteration (f951 i1)

The implementation matched this spec. Additions made during review:

- `container.container_retry_remedy(first_step)` — one shared `To retry:`
  block for all four fail-closed messages (R1/R3/R4), so the remedy text
  cannot diverge per path. `container_unavailable_message` now composes it.
- `_resume_qa_sync`'s container preflight abort now keeps `latest_output` a
  single line (`Container mode is enabled but the container runtime is
  unavailable: <cause>`) and puts the full cause+remedy in `state._error`,
  matching the fresh-run preflight in `_run_qa_sync` (R2) and keeping the TUI
  log line readable.
- `pm qa debug` (R6) now also converts a `create_qa_container` failure after
  the preflight into a clear message + `SystemExit(1)` instead of a traceback,
  releasing only its own `cname`. Still no host launch.
- Tests added: `_run_qa_sync`'s `ContainerLaunchError` handler (ERROR + status
  file + no finalize); a queued scenario create failure raising out of
  `_poll_tmux_verdicts` (proves the queued path never becomes INPUT_REQUIRED);
  the healthy relaunch control (running container → exec command, `session=None`);
  and the `OSError` branch of `_runtime_status`.


## Review iteration (f951 i2)

- `pm qa debug` now catches **any** `create_qa_container` failure (not only
  `ContainerError`), so a runtime that dies between the preflight and the
  create (e.g. the binary disappearing → `OSError`) still reports the cause
  and the remedy instead of a traceback. It releases only its own `cname`.
- Tests added: the non-`ContainerError` create path; no resume snapshot on
  the fresh-run preflight abort; `container_preflight_error()` inert when
  container mode is disabled; a persisted host run resuming on the host.

## Review iteration (f951 i3)

- The four ERROR publish sites — the R2 fresh-run preflight abort, the R3
  initial-launch handler, the R3 queued/relaunch handler in
  `_execute_and_finalize`, and the R5 resume abort — now go through one
  helper, `qa_loop._fail_run_infrastructure()`, so they cannot drift apart
  in what they set (`running`/`held` cleared, verdict `ERROR`, one-line
  `latest_output`, full cause+remedy in `_error`, status file). The status
  write is best-effort: a display-file error no longer crashes the driver
  thread on top of the failure it is already reporting.
  `_resume_qa_sync._abort()` drops its now-unused `error` parameter.
- `qa_loop._first_line()` replaces `str(exc).splitlines()[0]`, which raised
  `IndexError` for an exception with an empty message.
- Tests added: the host-mode relaunch control (`use_containers=False` never
  probes a container, keeps the pm session in the prompt shape); the
  fresh-run preflight abort and the resume abort both publish
  `overall=ERROR` with the cause in `qa_status.json`; the bytes-stderr branch
  of `_runtime_status`.

## Review iteration (f951 i4)

- `pm qa run` — the primary execution-only CLI entry point — now prints the
  full cause+remedy of a fail-closed launch, via the new
  `qa_loop.qa_error_detail(state)`.  Its `on_update` only prints the
  one-line `latest_output`, so the actionable remedy (start the runtime, or
  deliberately `pm container disable`) never reached a CLI user.  Other
  early-abort ERRORs (no pm session, missing workdir) carry no `_error` and
  print nothing extra.
- Tests added: `qa_error_detail` is gated on the ERROR verdict; a
  `CliRunner` test for `pm qa run` asserting the cause and remedy reach the
  console.  The create-failure test now asserts the specific
  `ContainerLaunchError` instead of `Exception`.
- Incidental (separate PR, not fixed here): `pm pr auto-sequence` has no
  branch for the `overall: "ERROR"` status value this PR introduces, so it
  keeps reporting `running: qa` and never surfaces the cause.  Filed
  pr-7abb052 with the repro and the fix sketch (an explicit ERROR branch +
  the watcher-token docs).
- Evidence note: `/pm-captures/impl/post-fix/qa-run/manifest.md` records
  that the i4 remedy block postdates the recording; the fail-closed
  behaviour and the absence of a host launch are unchanged.

## Review iteration (f951 i5)

No code changes: re-verified the four fail-closed paths (fresh-run preflight,
initial container launch, queued/relaunch inside `_poll_tmux_verdicts`,
resume re-validation), the relaunch guard, and the CLI reporting against the
spec. Full pytest on this workdir: 4492 passed, 13 failed — all
environmental/pre-existing (the `markdown` module is missing;
`test_hook_events::test_installer_writes_standalone_receiver` is defeated by
`PM_HOST_HOME`), none in the touched areas.

- Incidental (separate PR, not fixed here): the new terminal
  `overall: "ERROR"` status is restartable by the TUI auto-start scheduler —
  `_auto_start_qa_loops` holds only on `QA_HOLD_VERDICTS = ("PASS",
  "INPUT_REQUIRED")`, so a recorded `ERROR` starts QA again on the next
  `check_and_start` pass (startup/breadcrumb, target change, a merge in the
  plan, a QA NEEDS_WORK). Each retry fails the same preflight, writes another
  QA workdir and appends a duplicate `QA ERROR:` note to the git-tracked
  `project.yaml`. Filed pr-7b1dd2e with the repro and the fix sketch (mirror
  the review loop's `VERDICT_LAUNCH_FAILED` + episode cap + cooldown, or hold
  on `ERROR`). This is the auto-start sibling of the auto-sequence gap filed
  as pr-7abb052 in i4.

## Review iteration (f951 i6)

Re-audited the fail-closed paths and the reporting/evidence surfaces:

- Re-checked every container-mode gate in the tree
  (`is_container_mode_enabled`, `_runtime_available`, `wrap_claude_cmd`,
  `build_exec_cmd`, `container_is_running`). The QA launch boundary is
  closed: fresh-run preflight, initial container launch, queued launch and
  relaunch (inside `_poll_tmux_verdicts`, including the held-run reopen),
  `pm qa debug`, and resume. The remaining host-only roles are enumerated
  above (planner, Scenario 0, verifier, finalizer, authoring helpers); none
  consults the runtime, so none is a downgrade path.
- `pm qa run` now exits nonzero when the run ends `ERROR` (no result at
  all — e.g. a fail-closed launch), matching `pm qa debug`; a completed
  scenario verdict (PASS / NEEDS_WORK / INPUT_REQUIRED) still exits 0.
  Without it a scripted caller read "Result: ERROR" as success.
- `_record_qa_note` now appends the fail-closed cause+remedy when the verdict
  is `ERROR` and the summary does not already carry it. `qa_outcome_detail`
  only surfaces `state._error` when *no* scenario ran, so a mid-run failure
  (queued scenario create failure, or a relaunch whose container is gone,
  after another scenario already has a verdict) produced a note reading
  "QA ERROR: S1: PASS" with no reason — the PR note is the handoff channel
  for the next session, so the cause has to be in it. The text is flattened
  to one line and skipped when the summary already contains it.
- Tests added: `pm qa run` ERROR → exit 1 and the NEEDS_WORK control → 0;
  the note carries the cause mid-run, does not duplicate it when nothing
  ran, and verdict notes are unchanged; the host (`_launch_scenarios_in_tmux`)
  launcher's `_status_scenarios` / `_queued_indices` wiring, which closes
  the test gap the 868d48e8 queued-status fix left (it covered only the
  container launcher).

## Review iteration (c534 i1)

Re-audited the fail-closed boundary end to end (fresh run, initial launch,
queued launch, relaunch, resume, `pm qa debug`) and closed three remaining
gaps:

- **A container whose scenario window cannot be created now fails the run
  too.** In `_launch_scenarios_in_containers`, `new_window_get_pane`
  returning `None` (pm session gone, tmux refused the window) used to log
  and return: the container had already been created, so it leaked until the
  next run's orphan cleanup and `_poll_tmux_verdicts` recorded an invented
  `INPUT_REQUIRED` for the windowless scenario — the same class of failure
  R3 removes for a failed create. It now records a launch failure and
  releases only that attempt's own container, so the run ends `ERROR`. The
  `ContainerLaunchError` text was widened from "the container … could not be
  created" to "at least one QA scenario could not be launched in its
  container".
- **`_error` survives a resume snapshot.** `_write_resume_file` now persists
  `state._error` and `build_resume_state` restores it. Two consequences: a
  resumed run keeps its original diagnostics, and a run the planner produced
  nothing for (no scenarios, no verdicts, `_error` set) can no longer
  re-aggregate as a clean `PASS` after a restart — the aggregate reads
  `state._error` as `INPUT_REQUIRED`, as the live run did.
- **A recovered completed `ERROR` keeps its cause.** `_resume_incomplete_qa`
  now also reads the `error` field from `qa_status.json` when it adopts a
  run that finished during downtime. The snapshot is written *before* the
  poll, so a failure raised from inside it (queued create failure, lost
  container) only ever reached the status file; without this the note the
  TUI records — the next session's handoff — read "QA ERROR: S1: PASS" with
  no reason. `status_error` wins over the snapshot's (fresher), and the
  snapshot's is kept as a fallback for older files.

Tests added: a container-mode scenario whose window cannot be created raises
`ContainerLaunchError`, releases exactly its own container, records no
verdict; the resume snapshot round-trips `_error` (and tolerates snapshots
without the key); a completed `ERROR` recovered from disk carries the
status file's cause into `_on_qa_complete`; a healthy `pm qa debug` control
(runtime up → `create_qa_container` + `build_exec_cmd`, in-container cwd, no
host claude).

Intentionally unchanged: the window-failure path in the **host** launcher
(`_launch_scenarios_in_tmux`) still records `INPUT_REQUIRED` for a windowless
scenario. That is host mode — no container was requested, so nothing is
downgraded — and the `INPUT_REQUIRED` is deliberate there: it keeps the
scenario from being silently lost, which could produce a false overall
`PASS`.
