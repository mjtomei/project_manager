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
  (`tmux has-session -t "=$TARGET"`, exact since R37), not on any `pm-`
  session (which would also match the recipe's own `pm-recorder`); the
  web-UI `until curl` poll is bounded, bounds each attempt, and stops the
  server it started;
- the render steps delete this run's outputs before rendering and check the
  mp4 afterwards, so a failed render ends with no video and a clear error
  instead of the previous run's mp4 (and the CLI scaffold documents the
  escaped `bash -c` command form that actually survives its quoting). The
  render sections name `agg` as a prerequisite and carry its install line,
  guarded on a check that the `agg` on `PATH` runs (`agg --version`), so it
  never replaces a working binary and does replace a truncated one;
  they also check the renderers' own exit statuses (a failed `agg`/`ffmpeg`
  leaves a partial mp4 that `test -s` accepts), say "there is no cast to
  render" when the recording wrote nothing, and the tmux recipe reports a
  failed transcript pipe and checks `transcript.log`; both render blocks also
  refuse a capture directory that is missing or cannot be written before they
  remove or render anything, so an unwritable directory is not reported as
  "agg failed on the cast — is 'agg' installed?" (a remedy that runs and
  changes nothing) and a path that is not there is not reported as a
  recording that wrote nothing (R57); "cannot be written" covers both
  permission shapes — a directory with no write bit and one with the write
  bit and no *search* bit, which `[ -w ]` alone cannot see — and a render
  that stops before `agg` (a missing encoder) still leaves none of the
  previous run's video or gif behind (R59);
- the render blocks now use master's `render_cast` (merged from #249,
  2026-10-31): a variable-frame-rate encode with the final frame held at the
  GIF's duration, writing `recording.mp4.partial.mp4` and renaming it only
  after a successful encode. The guards above are unchanged and still run
  before the renderer; a failed render still exits non-zero and leaves no
  `recording.mp4`, gif or partial behind (R60 in impl.md).
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
  Its `curl -N` reader is stopped by the block before it returns (`kill
  "$SSE_PID"`; `--max-time` is the backstop), so `sse.log` is final when the
  block says the protocol capture is done (R59).
- a start step that cannot do its job says so where it fails: an unusable
  capture directory and a `new-session` that never creates the recorder stop
  the run with their own message instead of being misdiagnosed as a dead
  recorder, the web-UI driver block names a missing capture directory ("does
  not exist") separately from one that exists and cannot be written or
  entered ("cannot be written — … check the path and its permissions") —
  both checks run before its `cd`, because an unsearchable directory failed
  that `cd` and used to be reported as missing (R58) — and a failed web-UI
  start removes the pid it recorded;
- a failure message names a remedy that still exists: the web-UI busy-port
  refusal says the answering server's pid is no longer in `server.pid` (the
  cleanup just cleared it) and to find it with `ss -ltnp`, and the Playwright
  resolution failure offers the global link only when
  `/usr/lib/node_modules/playwright` exists (otherwise `npm i playwright`).
  Both recording recipes' produced-files lists name the flow's diagnostics
  (`recorder.status`, `recorder-stderr.log`, and `recorder-pane.log` when a
  wait gives up) so the manifest's `## Files` section matches the directory,
  and the web-UI list names `server.pid` (present when a run stopped before
  the teardown) and the `recording.webm` a failed transcode keeps for a
  retry (R44).
- step 1 of the tmux recipe refuses a `pm session name` that printed nothing
  before its readiness wait, as steps 2, 4 and 5 do: with an empty target the
  wait polls `has-session -t "="` to its deadline and reports "pm session  did
  not appear within 60s" for a `pm` that is not on PATH (R44).
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
  look — including the tmux recipe's step 2 pasted on its own, whose claim is
  canonicalized while its pipe's command runs in the session's directory
  (R56); and the CLI stop step's two failures (a bound that ran out, a
  mistyped `RECORDER_STOP_TIMEOUT`) leave the recording running, so the
  larger-bound re-run they prescribe can actually be applied instead of
  meeting a torn-down pane. (The CLI scaffold's `-L scaffold` socket name is
  shared by every run on the host, so two CLI captures must run in sequence;
  the step-1 prose says so — both runs fail loudly rather than sharing
  evidence, the same disposition as the tmux recipe's `pm-recorder` note.)
- a remedy that runs but cannot work says so, and an empty answer never
  becomes a path (review loop 7c9c i3): both recording recipes' `agg` install
  block stops when the binary it just downloaded still does not resolve
  (`~/.local/bin` not on `PATH`) or still does not run, naming the export or
  the binary to remove, instead of exiting 0 and
  leaving the render to ask "is 'agg' installed?" — which sends the worker
  back to the block that already ran, in a loop; and the web-UI start block
  resolves its captures root through a checked `pm qa captures-path` and
  refuses a failed or empty answer, because the bare substitution turned it
  into `/scenarios/1/web-ui` at the filesystem root, which `mkdir -p` creates
  when the worker is root — the capture then lands outside the per-PR
  captures directory while every later check passes on those files.
- a renderer that writes nothing is not an encoder failure (review loop 7c9c
  i11): both recording recipes' render blocks check the cast before `agg` and
  the mp4 after `ffmpeg`, but not the gif between them, so an `agg` that
  exits 0 without writing its output reached ffmpeg as a missing input and
  the run said "ffmpeg failed on the gif" — the worker is sent to the encoder
  for a renderer that wrote nothing (verified with the recipes' own blocks
  and a stub `agg`; real ffmpeg's "No such file or directory" was the only
  hint). The gif is checked (`[ -s "$cast.gif" ]`) before the encode and the
  failure names `agg`. The re-QA re-checks it in S21/S22: with an `agg` that
  exits 0 and writes no gif, the render must say "agg wrote no gif" and must
  not blame ffmpeg.
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
  driver block refuses a missing `driver.mjs` — or an empty one, which is a
  valid ES module that `node` runs successfully (review loop ebd1 i10, below)
  — with "there is no driver.mjs in …" instead of letting `node driver.mjs`
  fail and reporting "the driver
  failed — this run's video, trace and screenshots are incomplete", which
  sends the worker to debug a file that was never saved; and its Playwright
  resolution failure says to remove a `node_modules` that does not hold the
  package before linking the global install, because the bare `ln -sfn` nests
  inside an existing (partial `npm i`) directory and still cannot resolve —
  a remedy that cannot work, repeated.
- a block refused for its input does not act on a shared handle (review loop
  7c9c i8): both recording recipes create the capture directory *before* they
  clear the recorder session they share with concurrent runs (`pm-recorder`
  per server, `rec` per host socket). With an uncreatable `<capture-dir>`
  under a regular file and another capture's recorder up, the block used to
  kill that recorder and then refuse, so the concurrent run failed as
  "recorder exited while the TUI was still running" / "recorder status is
  missing" — a failure it could not connect to the other worker's paste. A
  refused block now makes no tmux call at all.
- a session target is not exact without tmux's `=` (review loop 7c9c i9):
  `has-session -t <name>` is matched by *prefix* when no session has the whole
  name (verified on tmux 3.2a: `-t pm-test` exits 0 with only `pm-test~1` on
  the server), and pm creates exactly those grouped `<base>~N` sessions — so
  the tmux recipe's readiness wait, its claim read/write and pipe attach, and
  its step-5 witness and pipe stops all name the session with `=`. With only a
  grouped session on the server the old block recorded and reported *it* and
  exited 0 while `pm session` had created nothing; the fixed block fails at the
  readiness wait. A *bare* `show-options`/`set-option -t '=name'` is refused,
  so step 2 asserts the exact session first; the claim handles themselves take
  the `=name:0.0` pane form, which those commands do accept and resolve
  exactly (review loop ebd1 i9, below).
- a missing runtime is not a missing package (review loop 7c9c i9): the web-UI
  driver block checks `command -v node` before it links anything, because
  without the runtime its import check fails exactly as a missing Playwright
  does and both remedies it offers (the global link, `npm i playwright`) need
  node — a remedy that cannot work, repeated. The Tooling section names
  Node.js alongside Playwright, Chromium and `ffmpeg`.
- a session handle is not exact without tmux's `=` either (review loop 7c9c
  i10): the tmux recipe's *recorder* handles were bare, and pm's sessions are
  `pm-<repo>-<hash>`, so a repo named `recorder…` has a session a bare
  `pm-recorder` target prefix-matches (verified on tmux 3.2a). Step 0's clear
  runs on every capture and killed it silently; a dead recorder could be
  replaced by it in the readiness check (its pane read as "the TUI drew"),
  receive the detach key, and be killed at the stop timeout; and the recorder
  pane's own `tmux attach` was bare, so a target that ended landed the attach
  on a grouped `<base>~N` session and the run reported it as success. Every
  recorder handle now names `=pm-recorder` (with the `:0.0` pane spec for
  `capture-pane`/`send-keys`, which need it to honour `=`) and the attach
  names `=$TARGET`. The CLI recipe's `-t rec` stays plain: its `-L scaffold`
  socket is recipe-private and every session on it is named `rec`.
- the transcript pipe's target is a session handle too (review loop ebd1 i1):
  the recipe already names it `"=$TARGET:0.0"` (R37), but no test guarded it
  — all fourteen handles made bare left the file green. A bare target is
  prefix-matched, so a target that ends between step 2's exact-session assert
  and the pipe attach leaves the pipe attached to pm's grouped `pm-test~1`
  and streams *that* session into this run's `transcript.log`; the rest of
  the flow (cast, status, transcript) then passes and the run exits 0 on
  evidence that is not the target's (verified on tmux 3.2a, and reproduced in
  the harness: the block exits 0 with the bare handle). The text guard and
  the new `pipegap` execution case now fail on the bare form.

- the capture-directory claim's handles were the last bare session targets
  (review loop ebd1 i9): step 2 asserted the exact target and then read, wrote
  and released `@pm_capture_dir` with a plain `-t "$TARGET"`. The bare
  `=pm-test` form is refused by `show-options`/`set-option` ("no such
  session"), but the `=pm-test:0.0` pane form is accepted and exact (verified
  on tmux 3.2a), and a plain target is prefix-matched once the exact session
  is gone — so a target that ended between the assert and the claim write did
  not fail the write: `set-option -t pm-test @pm_capture_dir <cap>` exited 0
  and put the claim on pm's grouped `pm-test~1`, the "could not claim … the
  session went away" guard never fired, and the run failed one step later as
  "could not stream … — check that pane exists" (a pane for a session that
  went away). The read took a grouped session's claim for this session's, and
  the release — a no-op once the target has ended — cleared the grouped
  session's option instead. Every claim handle now names `"=$TARGET:0.0"`, so
  the write fails where the guard can report it and nothing lands on the
  grouped session. No nominal flow changes.

- an artifact that exists but is empty is not an input the next stage can use
  (review loop ebd1 i5, test coverage only): the render/finalize blocks'
  stage-input checks are `test -s`, so a 0-byte cast, gif or webm — the state
  each message names ("the recording wrote nothing", "or a 0-byte gif") — is
  rejected as a missing input instead of being handed to the next stage, and
  the final mp4 check rejects an encoder that reports success and writes
  nothing. No test modelled the empty-file shape (only the absent file), so
  weakening any of the checks to `-e` left the whole file green; the
  misdiagnosis is reachable and was verified live with the recipes' own
  blocks: a 0-byte cast → real agg's "Error: empty file" → "agg failed on the
  cast — is 'agg' installed?"; a 0-byte gif → real ffmpeg's "Invalid data
  found" → "ffmpeg failed on the gif"; a 0-byte webm → "ffmpeg failed on the
  driver's webm"; and deleting the final mp4 check → rc 0 with a 0-byte
  `recording.mp4`. The cases now cover both shapes and the final check, and
  the CLI preamble block (the one fenced block no case executed) is run too.
  No recipe change, so no scenario gains a new surface; the re-QA may re-check
  the empty-artifact shapes in S21/S22 (cast, gif, mp4) and S26 (webm).

- an input that exists but is empty is not an input — the driver included
  (review loop ebd1 i10): the web-UI driver block checked `[ -f driver.mjs ]`,
  so a **0-byte** `driver.mjs` (a save that wrote nothing) passed. An empty
  file is a *valid* ES module: `node driver.mjs` exits 0 having run nothing,
  the block reports success, and the finalize step then says "there is no webm
  to transcode — the driver wrote no video; re-run step 2 and check the
  driver's recordVideo option" — a remedy that cannot work, because step 2
  passes again and `recordVideo` was never the problem (verified with the
  recipe's own two blocks). The check is `-s`, the rule every stage-input
  check in the render/finalize blocks already follows, and the message names
  the empty file where it is. No nominal flow changes.

- the manifest example has to name the files the run keeps (review loop
  ebd1 i4): the web-UI `## Files` example listed the `node_modules` link but
  neither `server.pid` (a run stopped before the teardown) nor the
  `recording.webm` a failed transcode keeps, and unlike the recording
  recipes' examples it has no catch-all — so a worker copying the example
  into the manifest still left out the two files the produced-files list
  (R44) says to mention. Both are in the example now. The tmux step-2 claim
  guard (`could not claim …`) and the cleanup order (this run's pipe stop
  before the claim release) are also pinned by tests; neither is a recipe
  change, so no scenario gains a new surface.

- a request that is never bounded cannot report a diagnosis, and a retry's
  cleanup has to take the manifest with it (review loop ebd1 i7): the web-UI
  port pre-check's `--connect-timeout 2 --max-time 5` is what makes its own
  "exit 28" branch reachable — curl has no default deadline for a server that
  accepted the connection and never answers, so an unbounded probe blocks the
  step instead of answering 28 (verified: 5.0 s with the bounds, still blocked
  at 20 s without them), and the block runs before every capture. The stub
  `curl` answered by mode, not by arguments, so deleting the flags left the
  whole file green; it now logs each call's argv and
  `test_the_port_pre_check_is_bounded` pins the first call's bounds. Step 2's
  attempt cleanup also clears `manifest.md` now: it is the document that
  presents this attempt's video, and a retried driver that fails left the
  earlier attempt's manifest naming the `recording.mp4` the cleanup had just
  deleted — R47's disagreement in the one block R47 did not cover. Neither is
  a change to a nominal flow.

- three claimed guards had no case (review loop ebd1 i8): the CLI recipe's
  capture preamble carries its own copy of the absolute-path guard, and
  `test_capture_dir_must_be_absolute` runs each recipe's *scaffold* — so the
  preamble, the first block under `## Capture`, was never run with a relative
  `<capture-dir>`. Deleting its `case` guard left the whole file green (201
  passed) and the preamble then exited 0 with `relcap/run` created and cleared
  in the worker's cwd. Step 2's claim comparison canonicalizes with `pwd -P`,
  and the prose claims it collapses a symlinked path, but only the `~/`
  spelling had a case: replacing every `pwd -P` with `pwd` also left the file
  green, and two runs reaching one capture directory through a symlink and its
  target would then both proceed (and a retry through the symlink be refused
  as a collision). And the web-UI start block's cleanup runs *before* its port
  pre-check, which the busy-port refusal states ("Its pid is no longer in
  server.pid (this step cleared it)"); the cleanup's list was text-pinned but
  the refusal path was not, so moving the `rm` below the pre-check left the
  file green and a refused start then left the previous run's `server.pid`
  for the teardown to signal. All three are now execution-tested
  (`test_cli_preamble_refuses_a_relative_capture_dir`,
  `test_a_shared_dir_is_recognized_through_a_symlink`,
  `test_a_retry_is_not_refused_through_a_symlink`,
  `test_a_refused_start_clears_the_previous_pid`); the recipe text is
  unchanged, so no scenario gains a new surface.

- a capture directory that exists and cannot be written is not a capture
  directory (review loop ebd1 i13): both recipes guard the path by creating
  it, and `mkdir -p` answers 0 for a directory that already exists — so the
  guard passed, the transcript pipe and the recorder's cast/status redirects
  failed inside the pane, and the run reported "recorder exited before it
  drew — see the cast and …/recorder-stderr.log" (tmux) or "asciinema wrote
  no cast — see …/recorder-stderr.log" (CLI), naming files that cannot exist
  (verified live in this container with a mode-500 capture directory: both
  blocks exit 1 with that message and the directory stays empty). The tmux
  recipe's step 2, pasted on its own to re-attach a transcript, is the same
  hole for a path that is not there at all: it exited 0 with the
  capture-directory claim on the session, a pipe that wrote nothing and the
  claim left behind for the next attempt to clear by hand. Both recipes now
  refuse the directory where the path is known — "capture directory … cannot
  be written — check the path and its permissions" — the tmux recipe in step 0
  (before the shared `pm-recorder` clear) and in step 2 (before the claim),
  the CLI recipe in the preamble and in the scaffold (before the shared `rec`
  clear); the refused block makes no tmux call at all.
- the web-UI recipe's capture directory had no writability guard at all
  (review loop ebd1 i14): step 1 checks only that `mkdir -p` succeeded, and it
  answers 0 for a directory that exists and cannot be written — so the block
  exited **0**, started the app, wrote no `server.pid` and left the previous
  run's mp4/webm/manifest/screenshots in place; the driver block then
  reported "playwright does not resolve beside driver.mjs" (after `ln`
  answered "Permission denied"), the finalize block "transcode produced no
  mp4 — ffmpeg failed on the driver's webm", and the Layer 2 block exited
  **0** having written neither `http.log` nor `sse.log` — the silent success
  its own guard exists to prevent (verified live with a mode-500 capture
  directory and the recipe's own fenced blocks). All four now stop with
  "capture directory … cannot be written — … check the path and its
  permissions": step 1 right after its `mkdir` guard (before the stale
  clear), and the driver, finalize and Layer 2 blocks after their existing
  missing-directory check. Four new execution cases cover them.
- two guards the recipes carry had no case (review loop ebd1 i13, test
  coverage only): the CLI scaffold's readiness timeout names
  `recorder-pane.log`, and only the message was pinned — deleting the
  `capture-pane` line left the whole file green (211 passed) while the message
  went on pointing at a file nothing writes, so the case now requires the file
  to exist and hold what the recorder drew (as the tmux readiness-timeout case
  already did); and both recipes' absolute-path guards accept a `~/…` capture
  directory, which the prose documents and step 2's canonical comparison
  exists for — every case used an absolute path, so narrowing the pattern to
  `/*` left the file green and refused a documented-valid path; the tmux
  step-0 block and the CLI preamble now run with `~/cap` and must create it
  under `$HOME`.
- the web-UI driver block reported a capture directory it could not *enter*
  as one that is missing (review loop ebd1 i17): its missing-directory and
  writability checks sat after `cd "$CAPDIR"`, so a directory that exists and
  cannot be searched (mode 400) failed the `cd` with "Permission denied" and
  the block said "capture directory … does not exist — create it and run step
  1" — the worker is sent to create a directory that is already there and to
  re-run the step that created it, while the finalize and Layer 2 blocks,
  which never `cd`, name the same directory "cannot be written" (verified
  live in this container: pre-fix rc 1 with that message after bash's own
  "Permission denied"). The checks now run before the `cd` — `-d` first
  ("does not exist"), then `-w`/`-x` ("cannot be written — … check the path
  and its permissions") — and the `cd` only runs for a directory that passed
  both, so its failure says the directory "could not be entered — it may have
  been removed after the checks above". A new case
  (`test_web_ui_driver_block_refuses_a_capture_dir_it_cannot_enter`, mode
  400, skips under root) fails against the pre-fix block. The two recipes'
  prose also quote asciinema's real abort message ("asciinema: <path> already
  exists, aborting" on 2.1.0) instead of "recording already exists", which the
  tool does not print.

- the merged render's own guarantees had no case (review loop 928f i1, test
  coverage only): `render_cast` (merged from #249) publishes by renaming
  `recording.mp4.partial.mp4`, and this PR's step-0/`render_fail`/pre-render
  cleanups for that partial were removable without a failing test — the same
  for the rename's failure guard, the "cannot probe the gif" check and the
  `-nostdin`/VFR encode options. Five new/extended cases pin them, and the
  comment above the block's final mp4 check now says what that check actually
  is (a backstop: `render_cast` already refuses an encoder that wrote
  nothing). No behavioural change, so no scenario gains a new surface; S21
  and S22 may re-observe that a failed render leaves no
  `recording.mp4.partial.mp4` beside no mp4.

- the manifest has to name the video a killed driver leaves (review loop 928f
  i2): the web-UI driver renames Playwright's video onto `recording.webm` only
  after a complete walk-through, so a driver killed before the rename leaves
  Playwright's auto-named `page@<hash>.webm` — a valid, playable *partial*
  recording (verified live in this container: SIGKILLing a recording driver
  left `page@b87f….webm`, which ffprobe reports as 3.12 s) that the finalize
  step never touches, because it transcodes only `recording.webm`. The
  produced-files list and the manifest's `## Files` example omitted it, while
  the manifest section asks for "every file above" and the example is what a
  worker copies — the "manifest and directory disagree" class R44/R45 fixed
  for `server.pid` and the kept `recording.webm`. Both now name it. No
  behavioural change, so no scenario gains a new surface; S26 may re-observe
  that a killed driver's capture directory holds the auto-named video and
  that the manifest names it. Two step-2 cleanup guarantees are pinned by the
  same pass (test coverage only): the missing-driver refusal must still clear
  the earlier attempt's outputs (moving the check above the attempt cleanup
  left them — including the complete `recording.webm` — in place), and the
  retry cleanup's `./*.webm` glob must take the auto-named video, not only
  `recording.webm`.

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
proceed and take the claim, not refuse the run as a collision. S24 also
re-checks the claim handle's exactness (review loop ebd1 i9): with the target
session ended and a grouped `<base>~1` session left on the server, step 2 must
fail with "could not claim … — the session went away" and must not write the
claim on the grouped session (a plain `-t "$TARGET"` writes it there and the
run then fails as "could not stream … — check that pane exists"). S21/S23 also
re-check the `agg` install: with `agg` missing and `~/.local/bin` **not** on
`PATH`, the install block must fail with the export it names rather than
exit 0. S21/S23 also re-check the unwritable-capture-dir refusal (review loop ebd1
i13): with the capture directory at mode 500 — and, for step 2 pasted on
its own, with `<capture-dir>` missing — the block must stop at "capture
directory … cannot be written" without taking the claim, attaching the pipe
or clearing the shared recorder session (`pm-recorder` for the tmux recipe,
`rec` for the CLI scaffold); the pre-fix blocks ran on and failed later as
"recorder exited before it drew" / "asciinema wrote no cast", naming files
that cannot exist.
S25/S26 also re-check the web-UI blocks' refusal (review loop ebd1 i14): with
the capture directory at mode 500, step 1 must stop at "capture directory …
cannot be written" before starting the app (pre-fix it exits 0, writes no
`server.pid` and leaves the earlier run's evidence), and the driver, finalize
and Layer 2 blocks pasted on their own must stop with the same message rather
than reporting "playwright does not resolve", a failed transcode of the
driver's webm, or (the Layer 2 block) exiting 0 with neither log written.
With the capture directory at mode **400** (exists, cannot be entered), the
driver block must stop with "capture directory … cannot be written — …
check the path and its permissions" and *not* "does not exist — create it
and run step 1" (review loop ebd1 i17, R58); the pre-fix block reports the
directory as missing after bash's own `cd: … Permission denied`.
S21/S22 also re-check the CLI scaffold's refusal order: pasted with a
relative or unsubstituted `<capture-dir>`, it must stop at "must be an
absolute path" *without* clearing the host-shared `rec` session — a
concurrent CLI capture's recorder has to survive the refused block (the
socket name is shared by every run on the host). The same holds for a path
the block cannot create: with `<capture-dir>` under a regular file it must
stop at "could not create …" and leave a concurrent capture's recorder
(`rec` for the CLI, `pm-recorder` for the tmux recipe) running. S23 also re-checks the stop
step's detach race: after the scenario
ends the pm session itself, a stop step run while the recorder is winding
down must pass on the complete cast and `recorder.status` 0 (not report "the
cast is incomplete"), while a recorder killed as the session ends must still
fail on the non-zero status. S23 also re-checks the transcript pipe's target:
with the target session gone and only a grouped `<base>~1` session left on
the server, the pipe must fail ("could not stream …") instead of attaching
to the grouped session — a bare `pipe-pane -t "$TARGET:0.0"` attaches to it
and the run then reports success on that session's transcript. S25 also re-checks the captures-path guard: step 1 pasted with an
unsubstituted `PR_ID` (or outside the project) must stop with "could not
resolve the captures directory" and create nothing, not run the capture in
`/scenarios/1/web-ui`. S25 also re-checks the port pre-check's bound: with a
listener that accepts and never answers, the step must refuse in about five
seconds with "could not check … exit 28" (an unbounded probe blocks instead),
and S26 re-checks the driver retry's cleanup: with an earlier attempt's
`manifest.md` seeded beside its mp4, a retried driver that fails must leave no
manifest naming the deleted video, and with the earlier attempt's `http.log`
and `sse.log` seeded the retry must clear them too — the protocol layer is
supplementary, so a retry that does not re-run it would otherwise present the
earlier attempt's route snapshots and event stream as this run's evidence
(review loop ebd1 i12, R53). S26's recipe-content check includes the
manifest example: it must list `server.pid` and `recording.webm` beside the
files it already named (R45). S26 also re-checks the driver block's two new
messages: pasting step 2 with no `driver.mjs` in the capture directory must
stop with "there is no driver.mjs in …" (not "the driver failed"), and a
0-byte `driver.mjs` must stop with the same message instead of reporting
success (a run that then reached the finalize step would be told to check the
driver's `recordVideo` option, which a re-run of step 2 cannot fix), and a
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
  where `cast=…/recording.cast`) — and the earlier run's `transcript.log`
  and `manifest.md` are cleared with them, so the manifest left in the
  directory is this run's rather than a description of the run whose files
  were just deleted;
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
  asciinema's exit status instead of passing on its non-empty cast; the
  earlier run's `recorder.status` is cleared before the recorder starts, so a
  run whose pane was torn down before asciinema returned cannot read the
  previous run's `0` and report a recording that never finished as a finished
  one — seed `recorder.status` with `0` and end the recording without letting
  the pane write one: the run must fail "recorder status is missing", not
  exit 0 (review loop ebd1 i2, R42);
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
  earlier run behind (the render step's cleanup never runs on that path) and
  no earlier run's `manifest.md` either (review loop ebd1 i6, R47), and a host
  with no `ffmpeg` stops with "ffmpeg is not installed — the render step
  needs it" instead of reporting the gif as failed.

### R3 — Recipe readiness and stop waits are bounded, and stale files are cleared

**Given** a `pm session` that never appears (including with a leftover
`pm-recorder` session already on the server), or a recorder that never exits,
**When** the worker runs the recipe's readiness/stop wait,
**Then** it exits within the stated deadline with an actionable message
instead of hanging or passing on the wrong session — and the number the
message states is the number the code waits (tmux 60 s for the pm session and
30 s for the recorder readiness and the stop, the CLI 30 s, the web-UI 120 s;
review loop ebd1 i2, R43), so a worker told "within 30s" is not looking at a
5 s wait. What each failure tears down differs, and the message says which:
both readiness waits stop the recorder/session they started, and the tmux
stop timeout kills the recorder it could not detach (the cast stops there and
the run is not a recording) — while the CLI stop timeout deliberately leaves
the recording *running*, because the larger-bound re-run its own message
prescribes needs it, and killing it made that remedy impossible (R21/R27);
and
**Given** a cast, transcript, recorder status, recorder session, manifest, or
render output (`recording.mp4`/`recording.cast.gif`) left by an earlier run,
**When** the capture step starts, **Then** the stale files and session are
cleared first, so the recorder does not abort on it ("asciinema: <path>
already exists, aborting" on asciinema 2.1.0, the version in the QA image)
and a duplicate session does not stop the run at "could not start the recorder
session" (the start check reports that, so the run never reaches the readiness
wait with the previous run's recorder in place), the new cast is this run's,
the transcript holds only this run, a capture that fails before the render
step still leaves no earlier run's video in the capture directory, and the
directory's `manifest.md` is this run's rather than the previous run's — a
manifest naming files the step-0 clear just deleted is the same stale-evidence
bug in the document that interprets the rest (review loop ebd1 i6, R47).

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
  `agg --version`, so on an image whose `agg` runs it must do nothing
  — re-downloading over the working binary would truncate it earlier on
  `PATH` if the transfer failed partway — and a *truncated* `agg`, which
  resolves and cannot run, must be replaced: a guard on `command -v agg`
  answers that file too, so the block would no-op while the render keeps
  asking "is 'agg' installed?" (review loop ebd1 i11, R52). The download
  itself carries
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
  `trace.zip`, `dom.html`, `*.png`, `http.log`, `sse.log`, `server.pid` and
  `manifest.md` (R47: the manifest is the document that says what the capture
  is, so a stale one names files this step just deleted) before the app
  starts — `driver.mjs` is the one file kept, because it is the run's input,
  not its evidence — and the driver step repeats the attempt-scoped
  cleanup (`recording.mp4`, `*.webm`, `trace.zip`, `dom.html`, `*.png`,
  `manifest.md`, `http.log`, `sse.log`) after its `cd`, so a failed run
  cannot present the earlier run's video, trace, screenshots or protocol logs
  as this run's evidence, nor leave the earlier attempt's manifest naming the
  video that cleanup deleted (R48). The driver's own exit status is the
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
- The render step runs against a capture directory that is missing or cannot
  be written (a mistyped path, or one that became unwritable after the
  recording) → the block stops with "capture directory … does not exist — …"
  or "capture directory … cannot be written — …" before it removes or renders
  anything, instead of reporting the unwritable directory as "agg failed on
  the cast — is 'agg' installed?" (whose remedy runs and changes nothing) or
  the missing path as "there is no cast to render (the recording wrote
  nothing)" (review loop ebd1 i16, R57).
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
  2026-10-27 was built before that and does not have it → check that `agg`
  runs (`agg --version`); the recipe's install line is the remedy either way,
  and the render prose says `agg` may be missing rather than claiming it is
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
