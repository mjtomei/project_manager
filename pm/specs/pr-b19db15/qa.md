# QA Spec — pr-b19db15

**PR**: Bug: generated background-job waits can match themselves and stall
completed work.

**Reduced scope (sign-off 2026-10-28, note-93f1418).** The wait helper, the
shared background-job prompt guidance, the QA-loop helper install, and the
verifier freshness text were dropped: stalled waits are agent behaviour the
watcher PR (pr-ff9b728) will catch. What remains is a set of real
recording-recipe bugs that any worker following the recipe hits:

- both recording recipes create the capture directory before recording;
- both remove a stale cast before recording;
- both wait (bounded) for the recorder to draw before sending keys;
- both stop by ending the recorded command and then wait (bounded) on the
  recorder's session handle and check the cast is non-empty;
- the CLI no-TTY scaffold writes the cast where the render reads it;
- the tmux `until tmux ls` and web-UI `until curl` readiness polls are
  bounded, with the web-UI poll bounding each attempt and stopping the server
  it started.

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
- `recording.mp4` is fresh and H.264, and `manifest.md` lists the files.

### R3 — Recipe readiness and stop waits are bounded, and a stale cast is cleared

**Given** a `pm session` that never appears, or a recorder that never exits,
**When** the worker runs the recipe's readiness/stop wait,
**Then** it exits within the stated deadline with an actionable message and
cleans up (kills the recorder/session) instead of hanging; and
**Given** a cast left by an earlier run, **When** the capture step starts,
**Then** the stale cast is removed first, so the recorder does not abort with
"recording already exists" and the new cast is this run's.

### R4 — The web-UI recipe's readiness wait is bounded and cleans up

**Given** a local web app that never answers on its URL,
**When** the worker runs the recipe's server-start/readiness step,
**Then**
- it exits within the deadline (~120 s) with the "app did not answer …"
  message, and stops the server process it started (no orphan listener);
- a single blocking `curl` cannot stall the deadline (per-attempt
  connect/max-time bounds);
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
- Keystrokes sent before the recorder draws are silently dropped → the recipe
  waits (bounded) for pane content before driving it.
- The web-UI server accepts the connection but never answers → the per-attempt
  curl bound keeps the deadline meaningful.

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
