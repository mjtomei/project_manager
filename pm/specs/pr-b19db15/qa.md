# QA Spec — pr-b19db15

**PR**: Bug: generated background-job waits can match themselves and stall
completed work.

**Reduced scope (sign-off 2026-10-28, note-93f1418).** The wait helper, the
shared background-job prompt guidance, the QA-loop helper install, and the
verifier freshness text were dropped: stalled waits are agent behaviour the
watcher PR (pr-ff9b728) will catch. What remains is a set of real
recording-recipe bugs that any worker following the recipe hits:

- both recording recipes create the capture directory before recording;
- both remove a stale cast before recording (the tmux recipe also removes a
  stale `transcript.log`, which is appended to, and attaches its transcript
  pipe so a leftover pipe cannot silently swallow the new log);
- both clear a recorder session left by an aborted run before starting a new
  one (the CLI scaffold clears the session, not the server);
- both wait (bounded) for the recorder to draw before sending keys; in the
  tmux recipe a recorder that exits before drawing — or that prints its own
  attach error ("can't find session: …") and then exits — is a failure, not
  an early finish;
- both stop by ending the recorded command and then wait (bounded) on the
  recorder's session handle and check the cast is non-empty;
- the CLI no-TTY scaffold writes the cast where the render reads it;
- the tmux pm-session poll is bounded and waits on the computed session
  (`tmux has-session -t "$TARGET"`), not on any `pm-` session (which would
  also match the recipe's own `pm-recorder`); the web-UI `until curl` poll is
  bounded, bounds each attempt, and stops the server it started;
- the render steps delete this run's outputs before rendering and check the
  mp4 afterwards, so a failed render ends with no video and a clear error
  instead of the previous run's mp4 (and the CLI scaffold documents the
  escaped `bash -c` command form that actually survives its quoting). The
  render sections name `agg` as a prerequisite and carry its install line,
  and the web-UI finalize step refuses to run with no `CAPDIR`.

Recipes render in the foreground, exactly as on master. Nothing in this PR
changes `pm_core/`.

The original failures (self-matching `pgrep -f` waits, a bare `wait` blocked
on a persistent reaper) are **not** fixed here; see `impl.md`.

**Scenario mapping for re-QA.** Keep the three recipe scenarios from the
previous round — S14 (CLI capture + render, stale dir, no-TTY form), S18
(tmux TUI capture, bounded readiness/stop), S20 (web-UI readiness bound +
cleanup) — and re-verify them against the reduced diff. Retire S15, S16, S17,
and S19: they exercised the dropped helper, the shared prompt guidance, and
the QA-loop helper install, none of which exist in this PR any more.

## Setup (cross-cutting)

- Run inside the repo (or a clone) at the PR head. The pm-dev image ships
  `asciinema`, `ffmpeg`/`ffprobe`, and `tmux`; `agg` is **not** always present
  — install its release binary for the architecture
  (`agg-$(uname -m)-unknown-linux-gnu`) rather than substituting a renderer.
- Captures for a scenario go under the per-PR captures dir at
  `$CAP/scenarios/<n>/` (the worker prompt names `$CAP`).
- The PR-head recipes are at `pm/qa/artifacts/` in the scenario's clone
  (`/workspace`). The copy the runner installs into `scratch/qa-artifacts/`
  comes from the QA session's project library, which is the project's main
  branch and **can lag the PR head** — use the PR-head copy for recipe-content
  assertions and record any difference.
- A worker may start long-lived decoys/observers and run several jobs in
  parallel inside its own scenario; scenarios never depend on another
  scenario's state.

## Requirements

### R1 — A CLI capture records and renders successfully (nominal, stale dir, no-TTY form)

**Given** `asciinema`/`agg`/`ffmpeg` available and the CLI recording recipe at
hand, including a capture directory that already holds a cast from an earlier
run,
**When** the worker records a short CLI command using the recipe's no-TTY
scaffold (and the interactive `bash` form) and renders it with the recipe's
foreground render block,
**Then**
- the capture step creates the capture directory and removes the earlier cast
  *before* recording;
- `recording.cast` exists, is non-empty, and is from this run (the earlier
  run's marker is not present);
- the interactive form is stopped with `exit`, and the recorder session is
  observed to end before the cast is checked;
- a one-shot command that prints nothing for longer than the 30 s readiness
  bound still records (the scaffold's readiness wait is on the cast file, not
  pane content), and one that runs longer than the default stop bound records
  when `RECORDER_STOP_TIMEOUT` is raised;
- `recording.mp4` is freshly written, non-empty, and `ffprobe` reports
  `codec_name=h264`;
- `manifest.md` exists and its `## Files` section lists the produced files.

### R2 — The tmux screen-recording recipe records a TUI and renders it (nominal)

**Given** a throwaway project with a pm session running,
**When** the worker follows the tmux screen-recording recipe to record a TUI
session, stop the recorder, and render the cast,
**Then**
- `transcript.log` and `recording.cast` are non-empty and from this run;
- the recorder session ends before the cast check (the completion signal is
  observed, not assumed);
- a recorder that is already gone before the detach while the pm session it
  was attaching to still exists (it died mid-scenario) fails the run with
  the "cast is incomplete" message instead of rendering a truncated cast as
  this run's capture, and a detach that itself fails because the recorder
  vanished in that gap fails the same way;
- `recording.mp4` is fresh and H.264, and `manifest.md` lists the files.

### R3 — Recipe readiness and stop waits are bounded, and stale files are cleared

**Given** a `pm session` that never appears (including with a leftover
`pm-recorder` session already on the server), or a recorder that never exits,
**When** the worker runs the recipe's readiness/stop wait,
**Then** it exits within the stated deadline with an actionable message and
cleans up (kills the recorder/session) instead of hanging or passing on the
wrong session; and
**Given** a cast, transcript, or recorder session left by an earlier run,
**When** the capture step starts, **Then** the stale files and session are
cleared first, so the recorder does not abort with "recording already exists"
or "duplicate session", the readiness wait does not pass on the previous
run's recorder, the new cast is this run's, and the transcript holds only this
run.

### R4 — The web-UI recipe's readiness wait is bounded and cleans up

**Given** a local web app that never answers on its URL,
**When** the worker runs the recipe's server-start/readiness step,
**Then**
- it exits within the deadline (~120 s) with the "app did not answer …"
  message, and stops the server process it started (no orphan listener);
- a single blocking `curl` cannot stall the deadline (per-attempt
  connect/max-time bounds);
- with something already answering on the port (a previous run's server),
  the step fails at once with the "something already answers …" message and
  does not start the app — otherwise the readiness wait would pass against
  that server and the driver would record the wrong app;
- the Playwright driver starts in the image: `node driver.mjs` resolves
  `playwright` through the recipe's `node_modules` link (without it the run
  dies with `ERR_MODULE_NOT_FOUND`), and the recipe's resolution check
  prints its ok line;
- with no resolvable Playwright the step stops at its own check with the
  "playwright does not resolve beside driver.mjs" message (it does not run
  the driver into a second copy of the error), and a local `npm i playwright`
  install is left alone (no link created inside it);
- with an app that does answer, the recipe proceeds and produces its captures.

## Edge cases

- Capture directory missing before `asciinema rec` → the recipe creates it
  first (otherwise asciinema exits 0 and writes nothing).
- A cast left by an earlier run in the capture directory → the capture step
  deletes it before recording, so a recording that wrote nothing cannot be
  rendered into a fresh-looking video of the previous run.
- Ctrl-C at a recorded interactive shell reaches the recorded command, not
  asciinema → the recipe ends the recorded shell with `exit` and checks the
  cast, rather than killing the pane by process name.
- Keystrokes sent before the recorder draws are silently dropped → the tmux
  recipe waits (bounded) for pane content before driving it, and the CLI
  scaffold waits for the cast header (a quiet command draws nothing).
- A failed `tmux attach` draws its own error into the recorder pane and exits
  milliseconds later → the tmux recipe re-checks that the recorder is still
  alive after the content appears, so the error text cannot pass as a drawn
  TUI and the cast check cannot pass on a cast holding that error.
- The recorder dies *during* the scenario (attach client or asciinema killed,
  tmux server lost) → the tmux recipe notices the recorder is gone before the
  detach while the pm session it was attaching to still exists, and fails the
  run; `test -s` alone would pass on the truncated cast and report a
  successful recording. A recorder that dies in the gap between that check
  and the detach key send makes `tmux send-keys` fail, and that failure ends
  the run with the same message instead of falling through to the cast check.
- A quiet or long one-shot CLI command is still recording → it must not be
  killed at the readiness or stop deadline; the stop bound is raised with
  `RECORDER_STOP_TIMEOUT` for a long command.
- The web-UI server accepts the connection but never answers → the per-attempt
  curl bound keeps the deadline meaningful.
- Something already answers on the web-UI port (a previous run's server, or
  another scenario on the default port) → the recipe refuses to start rather
  than let the readiness wait pass against that server and record the wrong
  app.
- The web-UI driver is an ES module and the image's Playwright is a *global*
  install advertised through `NODE_PATH`, which ESM ignores → a bare
  `node driver.mjs` fails with `ERR_MODULE_NOT_FOUND: Cannot find package
  'playwright'`; the recipe links the global install as a `node_modules`
  beside the driver (only when there is no local install and the global one
  exists) and stops at its resolution check, with an actionable message, when
  the import still does not resolve.
- A render fails (no `agg`, unreadable cast, failed transcode) in a capture
  directory that already holds a video → the render steps delete this run's
  mp4/gif (and the web-UI webm) first and then check the mp4, so the run ends
  with no video and an actionable error, never with the previous run's video
  presented as this run's capture. `agg` is the missing piece in the image:
  the recipe's own install line (`agg-$(uname -m)-unknown-linux-gnu`, verified
  as agg 1.9.0) has to make the same cast render to H.264; substituting a
  different renderer is not a pass.
- The web-UI finalize step is run in a fresh shell (no `CAPDIR`) → it stops
  with the "CAPDIR is unset" message instead of aiming its `rm -f` and ffmpeg
  at `/recording.mp4` / `/recording.webm`; with `CAPDIR` set it still produces
  the mp4 and drops the webm.
- The CLI no-TTY scaffold is pasted whole for the interactive `bash` form →
  the stop step times out with the shell still at its prompt, and its failure
  message names the remedy (`exit` in the recorded shell, step 3) rather than
  only `RECORDER_STOP_TIMEOUT`.
- A web-UI driver fails before it produces its outputs in a capture directory
  that already holds them → the driver step clears the previous run's webm,
  mp4, `trace.zip`, `dom.html` and screenshots first, so a failed run cannot
  present the earlier run's trace and screenshots as this run's evidence.
- The CLI scaffold's `bash -c` command form → it must be pasted escaped
  (`-c 'bash -c \"…\"'`); the unescaped form ends the outer double-quoted
  argument, the recorder exits, and step 4 reports "asciinema wrote no cast".

## Pass / Fail criteria

A scenario **passes** only when every Then is observed on the user's surface
with fresh evidence: command exit statuses and diagnostics, freshly written
artifacts validated with `ffprobe`, and the files the recipe says it produces.
A scenario **fails** (FLAGGED) if any Then is unmet, or if a stale cast is
rendered as this run's capture. Reporting INPUT_REQUIRED is correct when a
required tool cannot be installed; silently substituting a different
methodology is not.

## Ambiguities resolved

- **Renderer availability.** If `agg`, `ffmpeg`/`ffprobe`, or `asciinema` is
  genuinely absent and cannot be installed, the recording story is
  INPUT_REQUIRED. A missing `agg` is installable (release binary), so try that
  first.
- **Installed recipe copy vs PR head.** The runner installs recipes from the
  QA session's project library, which can lag the PR head. Recipe-content
  assertions use the PR-head copy in the scenario clone; record any difference
  in the installed copy.
- **No helper surface to exercise.** The dropped helper/prompt/verifier work
  has no QA surface; the repo regression tests in
  `tests/test_qa_artifact_recording_recipes.py` cover the kept recipe text.
