# QA Spec — pr-b19db15

**PR**: Bug: generated background-job waits can match themselves and stall completed work.

This is a **bug fix** whose product surface is *guidance plus one shared helper*:

- `pm/qa/artifacts/wait-for-job.sh` — a documented, reusable background-job
  waiter (captured PID, bounded timeout, real exit status, `pipefail` for
  `-c`, fresh + optionally validated artifact, process-group cleanup on
  timeout/interrupt).
- The recording recipes (`cli-recording.md`, `tmux-screen-recording.md`) now
  render through that helper and completion-check the capture step; the
  `web-ui-recording.md` readiness poll is bounded.
- A shared "Background Jobs and Test Runs" block is injected into impl,
  review, and QA-child prompts.
- The QA loop copies sibling `*.sh` helpers next to the recipes it installs
  into a scenario, and its verifier prompt/FLAGGED rule now require a *fresh*
  artifact rather than mere presence.

Two independent original failures, both improvised worker commands:

1. `until ! pgrep -f "dl-agg/agg|ffmpeg -loglevel"` (and the pytest variant)
   matched the waiting shell's own command line after the job had finished, so
   the wait never ended.
2. A bare `wait` blocked on a deliberately persistent observer/reaper child
   after the finite job had finished.

The fix must make the prescribed path wait on the actual job handle, with a
bound and an honest failure, and must never treat a stale leftover, a killed
wait, or a timeout as a successful result.

## Setup (cross-cutting)

- Run inside the repo (or a clone) for the helper/recipe scenarios; the
  pm-dev image ships `asciinema`, `agg`, `ffmpeg`/`ffprobe`, and `tmux`, so
  real recordings and real H.264 renders are expected.
- Captures for a scenario go under the per-PR captures dir at
  `$CAP/scenarios/<n>/` (the worker prompt names `$CAP`).
- For the generated-guidance / QA-loop scenario, `pm` must be usable
  (`./install.sh --local` if needed) and a throwaway project is created with
  `pm init`; the project's QA library is bootstrapped by copying the repo's
  `pm/qa/artifacts/` into it so the loop has the recipe and helper to install.
- A worker may start long-lived decoys/observers and run several jobs in
  parallel inside its own scenario; scenarios never depend on another
  scenario's state.

## Requirements

### R1 — A CLI capture records and renders successfully (nominal)

**Given** a fresh capture directory, `asciinema`/`agg`/`ffmpeg` available, and
the CLI recording recipe (and its shipped helper) at hand,
**When** the worker records a short CLI command using the recipe's no-TTY
scaffold and renders it with the recipe's render block (through
`wait-for-job.sh`),
**Then**
- `recording.cast` exists, is non-empty, and is from this run;
- `recording.mp4` is freshly written, non-empty, and `ffprobe` reports
  `codec_name=h264`;
- the helper prints its `ok — job exited 0 … artifact fresh` line and exits 0;
- `manifest.md` exists and its `## Files` section lists the produced files.

### R2 — The original self-match stall no longer reproduces on the prescribed path

**Given** a decoy shell whose own command line contains the renderer pattern
(e.g. it runs a long sleep with `agg`/`ffmpeg -loglevel` in its arguments),
and a render that has already finished,
**When** the worker runs the pre-fix improvised wait
(`until ! pgrep -f "<renderer pattern>"`) under an external bound, and then
waits for an equivalent finite job with the recipe's helper,
**Then**
- the improvised `pgrep -f` loop does **not** terminate on its own (it is
  killed by the external bound), because it matches the waiting shell itself;
- the helper returns promptly (well under its timeout) with exit 0 once the
  job finishes, and the decoy is still running afterwards;
- the new regression test for the self-match case
  (`test_completed_renderer_while_shell_has_renderer_pattern`) passes when run
  from the repo — supporting evidence that the bug is fixed.

### R3 — A persistent observer/reaper does not block a finite job (bare-`wait` regression)

**Given** a shell that starts a deliberately persistent observer/reaper child
and then a finite render job,
**When** the worker waits for the finite job with the helper,
**Then**
- the helper returns when the *job* finishes (not when the observer does) and
  reports the job's real status;
- the observer is still running afterwards (the helper does not kill
  unrelated children);
- a bare `wait` in the same setup would still be blocked at the external
  bound — i.e. the prescribed path avoids the deadlock.

### R4 — A finished-but-unreaped (zombie) job is treated as complete

**Given** a job that has exited but has not yet been reaped,
**When** the worker waits on it through the helper,
**Then** the helper reaps it, uses its exit status, and does not treat the
zombie as live work (no hang).

### R5 — A renderer failure is a failure, even if an artifact exists

**Given** a capture whose renderer fails (e.g. a corrupt/empty cast makes
`agg` fail, or a job writes a valid mp4 and then exits non-zero),
**When** the worker runs the render through the helper,
**Then**
- the helper exits non-zero and prints the job's exit status;
- the presence of a valid/leftover mp4 does not turn the run into a success;
- no "ok" line is printed.

### R6 — A stale leftover is not a completed render

**Given** an mp4 (or cast) left by an earlier run,
**When** the worker runs a job that exits 0 but does not rewrite that
artifact,
**Then** the helper exits 4 and says the artifact was not rewritten / is
stale, rather than reporting success; the worker records the failure rather
than citing the leftover as evidence.

### R7 — A timeout is a bounded failure with no orphan

**Given** a renderer that runs longer than the allowed bound (including one
that ignores SIGTERM),
**When** the worker runs it through the helper with a short `--timeout`,
**Then**
- the helper exits 3 with the "job exceeded Ns and was killed" message;
- the renderer's process (and any TERM-ignoring descendant) is gone after the
  helper returns — no orphan left to race a later run;
- no artifact is claimed as produced.

### R8 — A killed/interrupted wait is never a pass

**Given** a long-running render under the helper,
**When** the waiting helper process itself is signalled (Ctrl-C / a
supervisor TERM),
**Then**
- the helper exits 130 and prints that the run was interrupted and this is a
  failure, not a result;
- the renderer's process group is stopped (no orphan), including a job that
  ignores TERM (after the short grace period);
- the worker records this as a failed/incomplete capture, not a successful
  render.

### R9 — Pipeline failure status is preserved (test/review execution)

**Given** a failing test command piped into a formatter (`… | tail`),
**When** the worker runs it as a background job per the shared guidance
(captured PID + `pipefail`/`PIPESTATUS`),
**Then**
- the run is reported as failed (non-zero), not as success;
- the same pipeline run without `pipefail` visibly reports 0, showing the
  masked-failure anti-pattern the guidance warns about.

### R10 — A missing helper fails actionably, and RECIPE_DIR fixes it

**Given** a worker running the recipe's render block from a directory where
`RECIPE_DIR` does not point at `wait-for-job.sh`,
**When** the block runs,
**Then**
- it exits non-zero with the actionable "wait-for-job.sh missing or not
  executable … set RECIPE_DIR to the directory holding this recipe" message,
  instead of a bare "No such file or directory" and a silently skipped render;
- setting `RECIPE_DIR` to the directory holding the recipe (repo copy or
  installed `qa-artifacts/` copy) makes the render run.

### R11 — Concurrent jobs and recordings are isolated

**Given** two workers (or two runs) in the same container, each with its own
capture directory, plus a persistent observer,
**When** both renders/recordings run at once and one of them times out,
**Then**
- each helper returns its own job's status; the timeout of one does not kill
  the other job, the observer, or the caller's shell;
- both successful captures produce fresh, validated mp4s in their own
  directories; neither is reported stale because of the other;
- two concurrent CLI recordings use distinct tmux sockets/session names and
  distinct capture subdirectories; a shared fixed socket/session name yields a
  visible duplicate-session error rather than silent cross-talk.

### R12 — Same artifact path across runs is not mistaken for this run's output

**Given** run A produced a valid mp4 at a path,
**When** run B starts with that file present and its job does not rewrite it,
**Then** run B fails as stale even though the file is recent and valid; the
helper never reports success for an artifact it did not produce.

### R13 — The tmux screen-recording recipe records a TUI and renders it (nominal)

**Given** a throwaway project with a pm session running,
**When** the worker follows the tmux screen-recording recipe to record a TUI
session, stop the recorder, and render the cast,
**Then**
- `transcript.log` and `recording.cast` are non-empty and from this run;
- the recorder session ends before the cast check (the completion signal is
  observed, not assumed);
- `recording.mp4` is fresh and H.264, and `manifest.md` lists the files.

### R14 — tmux-recipe readiness and stop waits are bounded

**Given** a `pm session` that never appears, or a recorder that never exits,
**When** the worker runs the recipe's readiness/stop wait,
**Then** it exits within the stated deadline with an actionable message and
cleans up (kills the recorder/session) instead of hanging; and
**Given** a cast left by an earlier run, **When** the capture step starts,
**Then** the stale cast is removed first so the recorder does not abort with
"recording already exists" and the new cast is this run's.

### R15 — Impl sessions get the shared background-job guidance

**Given** a throwaway project with a PR,
**When** the user runs `pm prompt <pr>`,
**Then** the printed prompt contains the shared guidance: capture the job
handle (`$!`), wait on that PID (never bare `wait`, never `pgrep -f` on a
process name), bound the wait and treat expiry as failure, preserve pipeline
status (`pipefail`/`PIPESTATUS`), and require a fresh validated artifact —
never equate killing a wait with a passing result.

### R16 — A QA scenario receives the recipe *and* the helper, and is told about RECIPE_DIR

**Given** a throwaway project whose QA library contains the recording recipe
and `wait-for-job.sh`, and a QA plan whose scenario references
`ARTIFACT: cli-recording.md`,
**When** the QA loop launches that scenario,
**Then**
- the scenario's scratch `qa-artifacts/` directory contains the recipe and an
  executable `wait-for-job.sh`;
- the scenario's `prompt.md` lists the installed recipe path and explains that
  `RECIPE_DIR` must be set to the directory holding the recipe (the default
  `pm/qa/artifacts` only resolves at the repo root).

### R17 — The installed helper copy is usable from the scenario directory

**Given** the installed `qa-artifacts/` copy from R16,
**When** the worker runs the recipe's render block from outside the repo root
with `RECIPE_DIR` pointing at that directory,
**Then** the helper is found and the render completes successfully (fresh,
validated mp4), proving the copy — not just the repo-root path — works.

### R18 — The web-UI recipe's readiness wait is bounded and cleans up

**Given** a local web app that never answers on its URL,
**When** the worker runs the recipe's server-start/readiness step,
**Then**
- it exits within the deadline (~120 s) with the "app did not answer …"
  message, and stops the server process it started (no orphan listener);
- a single blocking `curl` cannot stall the deadline (per-attempt connect/max
  time bounds);
- with an app that does answer, the recipe proceeds and produces its captures.

## Edge cases

- Job exits 0 but never touches a pre-existing artifact → stale → failure.
- Job exits non-zero after writing a valid artifact → failure (status wins).
- Job exits 124 on its own before the bound → reported as job failure, not a
  timeout.
- Job exits 125 on its own → failure with a message naming both possible
  causes (not blamed on `timeout` alone).
- Job killed by a signal → failure with its status.
- Helper signalled twice during cleanup → still finishes cleanup and exits 130
  (a second Ctrl-C must not abandon the job).
- TERM-ignoring job/descendant under timeout or interrupt → killed after the
  grace period; no orphan.
- Artifact is a directory or a dangling symlink → failure (not a regular
  file).
- Empty `--validate` → usage error; hanging `--validate` → bounded, exit 4;
  failing stage in the validate pipeline → validation failure.
- Artifact parent directory missing → helper creates it; artifact itself is
  never repaired.
- `--timeout` missing/invalid, no command, `-c` with extra args → usage error
  (exit 2).
- Capture directory missing before `asciinema rec` → recipe creates it first
  (otherwise asciinema exits 0 and writes nothing).
- Ctrl-C at a recorded interactive shell reaches the recorded command, not
  asciinema → the recipe ends the recorded shell with `exit` and checks the
  cast, rather than killing the pane by process name.
- Two helpers targeting the same artifact path → the second run must not
  accept the first run's file as its own.

## Pass / Fail criteria

A scenario **passes** only when every Then is observed on the user's surface
with fresh evidence: command exit statuses and diagnostics, freshly written
artifacts validated with `ffprobe`, surviving/killed processes checked by
their own PIDs, and the files the recipe says it produces. A scenario
**fails** (FLAGGED) if any Then is unmet, if an artifact is stale/absent
without a stated valid reason, if a wait hangs until an external bound, or if
a failure/timeout/interrupt is presented as a successful render. Reporting
INPUT_REQUIRED is correct when a required tool cannot be installed; silently
substituting a different methodology is not.

## Ambiguities resolved

- **Verifier freshness (R4 in the impl spec) at runtime.** The QA verifier is
  itself a model; driving it deterministically would require a real Claude
  session inside the scenario. Runtime scenarios therefore assert the
  *worker-visible* consequences (stale/killed artifacts are failures) and rely
  on the repo's regression tests for the verifier prompt wording. This is
  intentional, not a gap in the plan.
- **Which "user" drives the surfaces.** Three distinct users are exercised:
  a QA/impl worker following a recipe or the shared guidance, a developer
  running `pm prompt`, and a QA loop operator whose scenario gets the recipe
  and helper installed. Scenarios target each user's own surface.
- **Concurrency with fixed tmux names.** The CLI recipe uses `-L scaffold` and
  session `rec`; concurrent recordings must give each run its own socket (or
  accept a visible duplicate-session error). The scenario expects isolation,
  not a shared fixed name.
- **Real vs stub renderers.** Real `agg`/`ffmpeg` are used wherever a
  recording is the point; direct helper invocations (a documented surface) are
  used for timeout/interrupt/stale cases that would otherwise take 30 minutes
  or need process tricks.
