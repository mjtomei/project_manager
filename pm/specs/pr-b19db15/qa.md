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
  recorder's session handle, check the cast is non-empty, and check
  asciinema's own exit status (a killed recorder leaves a non-empty cast, and
  in the tmux recipe the target session is a witness only while it lives);
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
  guarded on `command -v agg` so it never replaces a working binary;
  they also check the renderers' own exit statuses (a failed `agg`/`ffmpeg`
  leaves a partial mp4 that `test -s` accepts), say "there is no cast to
  render" when the recording wrote nothing, and the tmux recipe reports a
  failed transcript pipe and checks `transcript.log`;
- the web-UI finalize/driver/teardown guards stop the block with
  `if … exit 1`, because `: "${VAR:?}"` only stops a *scripted* run — in an
  interactive shell the next line still runs (the `rm` aimed at
  `/recording.mp4`, the driver's link landed `node_modules` in the worker's
  cwd) — and the teardown stops *this run's* app from a fresh shell: step 1
  records the pid in `server.pid` (cleared first), so the block does not
  depend on a `SERVER_PID` that died with step 1's shell, and it refuses when
  neither is available instead of silently leaving the app holding the port.
  The Layer 2 protocol block carries the same guard: with `CAPDIR`/`APP_URL`
  unset it used to redirect to `/http.log` and `/sse.log` and still exit 0.
- a start step that cannot do its job says so where it fails: an unusable
  capture directory and a `new-session` that never creates the recorder stop
  the run with their own message instead of being misdiagnosed as a dead
  recorder, the web-UI driver block refuses a capture directory it cannot
  enter, and a failed web-UI start removes the pid it recorded;
- a failure message names a remedy that still exists: the web-UI busy-port
  refusal says the answering server's pid is no longer in `server.pid` (the
  cleanup just cleared it) and to find it with `ss -ltnp`, and the Playwright
  resolution failure offers the global link only when
  `/usr/lib/node_modules/playwright` exists (otherwise `npm i playwright`).
  Both recording recipes' produced-files lists name the flow's diagnostics
  (`recorder.status`, `recorder-stderr.log`, and `recorder-pane.log` when a
  wait gives up) so the manifest's `## Files` section matches the directory.
- a check that cannot tell one state from another says so instead of guessing
  (review loop 9265 i4): the web-UI port pre-check treats only "connection
  refused" (curl exit 7) as a free port — a listener that accepts and never
  answers (28), a wrong URL (6) or a missing curl (127) stops the step with
  curl's own status and the `ss -ltnp` hunt, instead of starting an app that
  cannot bind and reporting "app did not answer" at the deadline; both
  recording recipes (and the CLI preamble and scaffold) refuse a relative
  `<capture-dir>`, because tmux runs the transcript pipe in the pm session's
  directory and each paste resolves the path against its own shell, so a
  relative path writes the cast/transcript where the end-of-run checks never
  look; and the CLI stop step's two failures (a bound that ran out, a
  mistyped `RECORDER_STOP_TIMEOUT`) leave the recording running, so the
  larger-bound re-run they prescribe can actually be applied instead of
  meeting a torn-down pane. (The CLI scaffold's `-L scaffold` socket name is
  shared by every run on the host, so two CLI captures must run in sequence;
  the step-1 prose says so — both runs fail loudly rather than sharing
  evidence, the same disposition as the tmux recipe's `pm-recorder` note.)
- a remedy that runs but cannot work says so, and an empty answer never
  becomes a path (review loop 7c9c i3): both recording recipes' `agg` install
  block stops when the binary it just downloaded still does not resolve
  (`~/.local/bin` not on `PATH`), naming the export, instead of exiting 0 and
  leaving the render to ask "is 'agg' installed?" — which sends the worker
  back to the block that already ran, in a loop; and the web-UI start block
  resolves its captures root through a checked `pm qa captures-path` and
  refuses a failed or empty answer, because the bare substitution turned it
  into `/scenarios/1/web-ui` at the filesystem root, which `mkdir -p` creates
  when the worker is root — the capture then lands outside the per-PR
  captures directory while every later check passes on those files.
- a completion check that cannot tell a finished recording from a dead one
  (review loop 7c9c i5): the tmux stop step's failed detach is a hard failure
  only while the pm session it was attaching to is still there — a recorder
  gone while that session lives died mid-scenario, and its cast is truncated.
  When the session is gone too (the scenario quit pm and the quit raced the
  detach key), the recording is the same legitimate "the session ended, the
  attach followed it out" finish the both-gone branch accepts, so the cast,
  `recorder.status` and transcript checks decide: status 0 passes, 128+N or a
  missing status file still fails. Both recipes' step-0 prose also no longer
  claims a leftover recorder session would pass the readiness wait — the
  start check stops a duplicate `new-session` before that.
- a missing input is not a failed job (review loop 7c9c i4): the web-UI
  driver block refuses a missing `driver.mjs` with "there is no driver.mjs in
  …" instead of letting `node driver.mjs` fail and reporting "the driver
  failed — this run's video, trace and screenshots are incomplete", which
  sends the worker to debug a file that was never saved; and its Playwright
  resolution failure says to remove a `node_modules` that does not hold the
  package before linking the global install, because the bare `ln -sfn` nests
  inside an existing (partial `npm i`) directory and still cannot resolve —
  a remedy that cannot work, repeated.

Recipes render in the foreground, exactly as on master. Nothing in this PR
changes `pm_core/`.

The original failures (self-matching `pgrep -f` waits, a bare `wait` blocked
on a persistent reaper) are **not** fixed here; see `impl.md`.

**Scenario mapping for re-QA.** The reduced diff was re-verified as S21 (CLI
capture + render, stale dir, no-TTY form, failure modes), S22 (recording
failure modes), S23 (tmux TUI capture, bounded readiness/stop), S24 (dead
recorders, failed drives, colliding runs — it found the collision the claim
fixes, and its post-fix captures cover the fix), S25 (web-UI start and
readiness) and S26 (web-UI driver + finalize). Re-run those against the
current PR head. S24 also re-checks the claim's canonical comparison: two
sessions reaching one capture directory through different spellings (`~/cap`
vs its absolute path) must be refused, and a same-session retry must not be
refused by its own `~/`-spelled claim; with another pm session on the server
that holds no claim, step 2 pasted from *inside* the capture directory must
proceed and take the claim, not refuse the run as a collision. S21/S23 also
re-check the `agg` install: with `agg` missing and `~/.local/bin` **not** on
`PATH`, the install block must fail with the export it names rather than
exit 0. S21/S22 also re-check the CLI scaffold's refusal order: pasted with a
relative or unsubstituted `<capture-dir>`, it must stop at "must be an
absolute path" *without* clearing the host-shared `rec` session — a
concurrent CLI capture's recorder has to survive the refused block (the
socket name is shared by every run on the host). S23 also re-checks the stop
step's detach race: after the scenario
ends the pm session itself, a stop step run while the recorder is winding
down must pass on the complete cast and `recorder.status` 0 (not report "the
cast is incomplete"), while a recorder killed as the session ends must still
fail on the non-zero status. S25 also re-checks the captures-path guard: step 1 pasted with an
unsubstituted `PR_ID` (or outside the project) must stop with "could not
resolve the captures directory" and create nothing, not run the capture in
`/scenarios/1/web-ui`. S26 also re-checks the driver block's two new
messages: pasting step 2 with no `driver.mjs` in the capture directory must
stop with "there is no driver.mjs in …" (not "the driver failed"), and a
capture directory holding a `node_modules` that does not resolve Playwright
must fail with the resolution message that names removing it first; after
that removal and the link, the same block must run the driver. The older
S14/S18/S20 covered the same recipe ground before the reduction; S15, S16,
S17 and S19 exercised the dropped helper, the shared prompt guidance and the
QA-loop helper install, none of which exist in this PR any more.

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
- a recorder killed mid-recording (asciinema killed while the pane lives, or
  the pane/server torn down) fails with the "cast is incomplete" message
  instead of reporting success on its header-only cast — `test -s` alone
  cannot tell — and a stale `recorder.status` from an earlier run is cleared
  with the earlier cast, so it cannot make a torn-down recorder look finished;
- `recording.mp4` is freshly written, non-empty, and `ffprobe` reports
  `codec_name=h264`; a render whose `agg`/`ffmpeg` fails partway (leaving a
  non-empty partial mp4) exits non-zero with the "render produced no mp4 — …"
  message and leaves no mp4, and a render with no cast at all says "there is
  no cast to render" instead of blaming a missing `agg`; a host with no
  `ffmpeg` on `PATH` stops with "ffmpeg is not installed — the render step
  needs it" instead of reporting the gif as failed;
- a capture that fails (e.g. the recorder never writes a cast) leaves *no*
  `recording.mp4`/`recording.cast.gif` from the earlier run in the capture
  directory — the render step's own cleanup never runs on that path, and the
  intermediate's real name is the one the render block writes (`$cast.gif`,
  where `cast=…/recording.cast`) — and the earlier run's `transcript.log` is
  cleared with them;
- `manifest.md` exists and its `## Files` section lists the produced files;
  on a host without asciinema the documented `| tee …` fallback writes
  `transcript.log` into the capture directory (not the worker's cwd), and the
  manifest names it.

### R2 — The tmux screen-recording recipe records a TUI and renders it (nominal)

**Given** a throwaway project with a pm session running,
**When** the worker follows the tmux screen-recording recipe to record a TUI
session, stop the recorder, and render the cast,
**Then**
- `transcript.log` and `recording.cast` are non-empty and from this run; a
  failed `pipe-pane` fails the run where it happens ("could not stream …"),
  and a pipe that never writes fails it at the end ("transcript.log is
  empty") instead of reporting a capture with no transcript;
- the recorder session ends before the cast check (the completion signal is
  observed, not assumed), and a recorder that was killed mid-scenario — even
  when the pm session ended too, leaving no live witness — fails on
  asciinema's exit status instead of passing on its non-empty cast;
- a recorder that is already gone before the detach while the pm session it
  was attaching to still exists (it died mid-scenario) fails the run with
  the "cast is incomplete" message instead of rendering a truncated cast as
  this run's capture, and a detach that itself fails because the recorder
  vanished in that gap fails the same way;
- a `pm tui send` that fails during the scenario is not accepted as a
  finish: the TUI is gone, so the scenario did not run, and step 5's
  both-gone branch cannot tell that apart from the scenario quitting pm —
  the driving step's example sends are checked, so the block stops with
  "pm tui send failed … re-run the capture" instead of running on (the CLI
  scaffold says the same about a failed `send-keys`, which its step 4 cannot
  see because asciinema exits 0 either way); that failure path also tears the
  run down — the pane is saved in `recorder-pane.log`, the recorder session
  is killed, the pipe is stopped and the claim released — because a stale
  pane-registry entry fails the send while the session, its pipe and the
  recorder live on; and driving from a
  fresh shell re-derives `$TARGET` (an empty one is refused), so the keys
  cannot auto-detect and drive a different TUI than the one recorded;
- the stop step detaches with the prefix the server reports
  (`tmux show-options -gv prefix`), not a literal `C-b`: on a host whose
  `~/.tmux.conf` sets another prefix (this dev container sets `C-\`) the
  recording still ends, the cast is flushed and the run passes, where a
  literal `C-b` leaves the recorder up until the 30 s bound with the keys
  landing in the TUI as input (verified live both ways);
- `recording.mp4` is fresh and H.264, and `manifest.md` lists the files; a
  capture that fails leaves no `recording.mp4`/`recording.cast.gif` from the
  earlier run behind (the render step's cleanup never runs on that path), and
  a host with no `ffmpeg` stops with "ffmpeg is not installed — the render
  step needs it" instead of reporting the gif as failed.

### R3 — Recipe readiness and stop waits are bounded, and stale files are cleared

**Given** a `pm session` that never appears (including with a leftover
`pm-recorder` session already on the server), or a recorder that never exits,
**When** the worker runs the recipe's readiness/stop wait,
**Then** it exits within the stated deadline with an actionable message and
cleans up (kills the recorder/session) instead of hanging or passing on the
wrong session; and
**Given** a cast, transcript, recorder status, recorder session, or render
output (`recording.mp4`/`recording.cast.gif`) left by an earlier run,
**When** the capture step starts, **Then** the stale files and session are
cleared first, so the recorder does not abort with "recording already exists"
or "duplicate session", the readiness wait does not pass on the previous
run's recorder, the new cast is this run's, the transcript holds only this
run, and a capture that fails before the render step still leaves no earlier
run's video in the capture directory.

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
- an app that answers 404 at `/` (its UI lives at a subpath) counts as
  answering: the readiness poll carries no `-f`, so the step proceeds
  instead of running out its deadline, reporting "app did not answer", and
  killing a server it had just started;
- the Playwright driver starts in the image: `node driver.mjs` resolves
  `playwright` through the recipe's `node_modules` link (without it the run
  dies with `ERR_MODULE_NOT_FOUND`), and the recipe's resolution check
  prints its ok line;
- with no resolvable Playwright the step stops at its own check with the
  "playwright does not resolve beside driver.mjs" message (it does not run
  the driver into a second copy of the error), and a local `npm i playwright`
  install is left alone (no link created inside it);
- a driver that exits 0 but records no video leaves no `recording.webm`, and
  the finalize step then fails with "there is no webm to transcode — the
  driver wrote no video" instead of blaming ffmpeg, and leaves no mp4 (a
  stale one from an earlier run is removed);
- a transcode whose `ffmpeg` reports success but writes an empty mp4 fails
  with "ffmpeg wrote nothing", leaves no mp4 behind, and keeps the webm so
  the step can be retried;
- a host with no `ffmpeg` on `PATH` stops the finalize step with "ffmpeg is
  not installed — the finalize step needs it" before any transcode, instead
  of reporting the driver's webm as a failed encode;
- the finalize step run with a `CAPDIR` that does not exist fails with
  "capture directory … does not exist", not "there is no webm to transcode";
- a driver block whose Playwright resolution check fails leaves none of the
  earlier attempt's `*.webm`/`trace.zip`/`dom.html`/`*.png` behind;
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
  When the target session ended *too*, no live session is left as a witness,
  so the recipe decides on asciinema's own exit status: a recorder killed
  mid-scenario (status 128+N) or a pane torn down before asciinema returned
  (no status file) fails the run, while a recording that ended because the
  pm session itself ended exits 0 and passes.
- A quiet or long one-shot CLI command is still recording → it must not be
  killed at the readiness or stop deadline; the stop bound is raised with
  `RECORDER_STOP_TIMEOUT` for a long command. A *mistyped* value (`2m`,
  `1.5h`) must fail the step with "RECORDER_STOP_TIMEOUT must be whole
  seconds" instead of removing the bound: in an interactive shell the failed
  arithmetic leaves the deadline empty and the shell carries on, so the stop
  wait never ends.
- The TUI dies mid-scenario (a crash, not the scenario quitting pm) → the
  driving step's own `pm tui send` fails and step 5's both-gone branch cannot
  tell that from a legitimate finish, so the capture is re-run rather than
  accepted; and driving from a fresh shell re-derives `$TARGET` first, because
  `pm tui send -s ""` auto-detects and can drive another project's TUI.
- A renderer reports success and writes nothing → the render/finalize step
  fails on the empty artifact and removes it, so no output is left behind on a
  failed step for the manifest to list.
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
  beside the driver (only when there is no local install and
  `/usr/lib/node_modules/playwright` exists — a global directory without the
  package is not linked, so a later `npm i playwright` still lands in the
  capture directory) and stops at its resolution check, with an actionable
  message, when the import still does not resolve.
- A render fails (no `agg`, unreadable cast, failed transcode) in a capture
  directory that already holds a video → the render steps delete this run's
  mp4/gif (and the web-UI webm) first and then check the mp4, so the run ends
  with no video and an actionable error, never with the previous run's video
  presented as this run's capture. `agg` is the missing piece in the image:
  the recipe's own install line (`agg-$(uname -m)-unknown-linux-gnu`, verified
  as agg 1.9.0) has to make the same cast render to H.264; substituting a
  different renderer is not a pass. The install block is guarded on
  `command -v agg`, so on an image that already has `agg` it must do nothing
  — re-downloading over the working binary would truncate it earlier on
  `PATH` if the transfer failed partway. The download itself carries
  `--connect-timeout`/`--max-time` (a stalled transfer would otherwise hang
  the worker), and a failed transfer removes its partial file and stops with
  "could not download agg".
- An encoder fails *partway* → the render steps check `agg`'s and `ffmpeg`'s
  own exit statuses, not only the output file: a killed `ffmpeg` leaves a
  non-empty partial mp4 (verified: 267,945 bytes) that `test -s` accepts, so
  the file alone would be reported as a successful render. A failed encode
  must end with no mp4 and the "render produced no mp4 — ffmpeg failed …"
  message, and a healthy render must still produce its H.264 mp4.
- A capture has no cast at all (the CLI recipe's `tee transcript.log`
  fallback, or a recording that wrote nothing) → the render step says "there
  is no cast to render" rather than sending the worker to install `agg`.
- The tmux transcript pipe fails, or is attached to a pane that never emits
  anything → the recipe reports the failed `pipe-pane` where it happens and
  fails the run on an empty `transcript.log`, instead of declaring success
  with no transcript (a quiet pane leaves a 0-byte file, which `test -s`
  catches).
- The web-UI finalize, driver, teardown, or protocol-layer block is pasted
  into a *fresh* (or *interactive*) shell with no `CAPDIR`/`SERVER_PID` → the
  block stops with its message. The `: "${VAR:?}"` form only stops a scripted
  run: in an interactive shell it aborts its own command and the next line
  still runs (verified — the `rm` would have aimed at `/recording.mp4`, and
  the driver block's link landed `node_modules` in the worker's cwd). A
  teardown that silently does nothing leaves the app holding the port, which
  the next run's port pre-check then reports as "something already answers";
  the protocol block with no `CAPDIR` redirects to `/http.log` and
  `/sse.log` and exits 0, reporting success with no capture. Its per-route
  `curl` also carries `--connect-timeout`/`--max-time`, so a route that
  accepts but never answers is recorded in `http.log` as a curl error with
  status `000` instead of hanging the block. In a fresh shell
  the teardown must still stop the app: step 1 records its pid in
  `server.pid`, and the block falls back to it (`SERVER_PID` itself does not
  survive step 1's shell).
- The web-UI finalize step is run in a fresh shell (no `CAPDIR`) → it stops
  with the "CAPDIR is unset" message instead of aiming its `rm -f` and ffmpeg
  at `/recording.mp4` / `/recording.webm`; with `CAPDIR` set it still produces
  the mp4 and drops the webm. With `CAPDIR` *set but missing* it stops with
  "capture directory … does not exist" rather than reporting "there is no
  webm to transcode — the driver wrote no video".
- The CLI no-TTY scaffold is pasted whole for the interactive `bash` form →
  the stop step times out with the shell still at its prompt, and its failure
  message names the remedy (`exit` in the recorded shell, step 3) rather than
  only `RECORDER_STOP_TIMEOUT`.
- The stop step is pasted *on its own* (a scenario that needs interactive
  driving cannot paste the whole block) → both recipes must still save the
  pane their timeout message names, and the tmux step must re-derive the
  target session from `pm session name` instead of acting on an empty one:
  `tmux has-session -t ''` succeeds, which would report a legitimate
  "the scenario ended the pm session" finish as "recorder exited while the
  TUI was still running". With no resolvable target the step stops and says
  so.
- The web-UI driver block runs with `CAPDIR` set but `APP_URL` missing → it
  stops instead of letting the driver fall back to
  `http://localhost:8000` and record whatever answers there.
- A web-UI driver fails before it produces its outputs in a capture directory
  that already holds them → step 1 clears the previous run's mp4, `*.webm`,
  `trace.zip`, `dom.html`, `*.png`, `http.log`, `sse.log` and `server.pid`
  before the app starts, and the driver step repeats the attempt-scoped
  cleanup (`recording.mp4`, `*.webm`, `trace.zip`, `dom.html`, `*.png`) after
  its `cd`, so a failed run cannot present the earlier run's video, trace,
  screenshots or protocol logs as this run's evidence. The driver's own exit status is the
  completion handle: the driver block stops with "the driver failed — this
  run's video, trace and screenshots are incomplete" instead of letting the
  finalize step transcode whatever is on disk (which misreports a driver
  failure as an ffmpeg one), and it clears this attempt's outputs before the
  driver because that block is pasted on its own when a driver is retried —
  otherwise a retry that fails part-way leaves the earlier attempt's complete
  webm for the finalize step to present as this run's recording.
- A driver is killed rather than exiting through its own error path → the
  video it never renamed is Playwright's auto-named `page@<hash>.webm`, a
  *valid, playable* partial recording (`ffprobe` reports a real duration), so
  the capture step clears every `*.webm` in the capture directory, not only
  `recording.webm`. A stale auto-named video from an earlier run must not
  survive into this run's evidence.
- The CLI scaffold's `bash -c` command form → it must be pasted escaped
  (`-c 'bash -c \"…\"'`); the unescaped form ends the outer double-quoted
  argument, the recorder exits, and step 4 reports "asciinema wrote no cast".
- A recorded command containing a single quote (`pm pr note add pr-x '…'`) →
  it must be pasted as `'\''`; unescaped, the quote ends the pane command and
  asciinema exits 2 with no cast.
- A wait gives up (recorder never starts / never exits) → the failure message
  names a file that still exists after the teardown: asciinema's own error in
  `recorder-stderr.log`, and the pane's last screen in `recorder-pane.log`.
  Following the old "check the pane" instruction after the run gives "no
  server running" — the recipe must not point at evidence it destroys, and a
  stale log from an earlier run must be cleared with the stale cast.
- The capture directory cannot be created (the path is under a regular file,
  or the captures dir is unwritable) → the run stops at `mkdir` with "could
  not create …" instead of reporting the recorder as dead ("recorder exited
  before it drew", "asciinema wrote no cast", the readiness timeout) or, in
  the web-UI start block, exiting 0 with the app launched and no pid file.
- The recorder session cannot be created at all (`tmux new-session` fails:
  server gone or refusing, a duplicate session from a concurrent run, a bad
  option) → the run stops with "could not start the recorder session — see
  tmux's error above", not with the recorder-death messages that point at a
  cast and a `recorder-stderr.log` that were never written.
- The web-UI driver block runs with `CAPDIR` *set but missing* → it stops
  with "capture directory … does not exist" instead of `cd` silently staying
  put and creating `node_modules` in the worker's cwd (where the resolution
  check then passes on that stray link).
- A web-UI start that never answers → the readiness failure kills the app
  *and* removes the `server.pid` it recorded, so a teardown afterwards cannot
  signal a recycled pid.
- The bundled Dockerfile now installs `agg`, but the image used for QA on
  2026-10-27 was built before that and does not have it → check
  `command -v agg`; the recipe's install line is the remedy either way, and
  the render prose says `agg` may be missing rather than claiming it is
  always absent.
- Two runs on one tmux server → `pm-recorder` is one session name and
  `pipe-pane` is per-pane, so the runs collide. A second run recording the
  *same pm session* into another capture directory replaces the first run's
  transcript pipe: the first run's `transcript.log` stops growing and its
  stop step still exits 0 on the bytes written before the takeover. A second
  run recording into the *same capture directory* removes the first run's
  cast and transcript and overwrites them, and the first run's stop block
  then detaches the second run's recorder and reads its status as its own.
  Step 2 claims the capture directory in a `@pm_capture_dir` session option
  *before* attaching the pipe, and refuses a session recording a different
  directory, or a directory another live pm session is recording; step 5
  releases the claim, and so does every failure path after it is taken (a
  failed run must not make the next attempt look like a collision). A run
  killed outright leaves a claim no path can release, so both refusal
  messages name the manual clear (`tmux set-option -u -t <session>
  @pm_capture_dir`) — "end that capture" alone is impossible advice for a
  claim whose capture already ended. Both
  collisions now fail loudly on at least one side instead of passing. The
  claim is compared as a canonical directory (`cd` + `pwd -P`, with a stored
  claim's `~/` prefix expanded), not as the text a worker typed: `~/cap` and
  an absolute path to the same directory are one claim, so a second session
  that reaches the directory through the other spelling is still refused (it
  used to run on and share the directory), and a retry is not refused by its
  own `~/`-spelled claim. A session that holds **no** claim is not recording
  into anything: the scan skips an empty answer instead of normalizing it,
  because `cd ""` succeeds and stays in the worker's cwd — normalizing it made
  every other session on the server look like it recorded into the directory
  step 2 was pasted from, so a worker pasting the step from inside the capture
  directory was refused as a collision that does not exist. A raw
  `tmux pipe-pane` that does not go through step 2 still bypasses the claim —
  record it as a limitation, not a pass.

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
