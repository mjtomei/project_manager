# Impl Spec — pr-b19db15

**Bug**: generated background-job waits can match themselves and stall
completed work.

Two independent reproductions, both *improvised worker commands* rather than
checked-in PM polling loops:

1. **#229 QA round 2 scenario 10** — `until ! pgrep -f "dl-agg/agg|ffmpeg -loglevel"`
   matched the waiting shell's own command line after both renderers had
   finished; the worker stalled ~8 minutes.
2. **#249 S74 / review round 3 iteration 1** — a bare `wait` blocked on a
   deliberately persistent reaper child after the finite snapshot had
   finished; separately, `until ! pgrep -f "pytest ..."` matched its own shell
   after the suite finished.

## Scope decision (2026-10-28, sign-off note-93f1418)

The user decided to reduce this PR. Stalled waits are *agent behaviour* that
may fade as models improve, and the watcher PR (pr-ff9b728) will catch them,
so this PR must not add code or prompt text for them.

**Dropped** (implemented in earlier review loops, now removed):

- `pm/qa/artifacts/wait-for-job.sh` and its regression tests;
- `_background_jobs_block` in `pm_core/prompt_gen.py` and all three
  injections (impl, review, QA child);
- the QA-child `RECIPE_DIR`/helper paragraph;
- the `*.sh` helper copy in `qa_loop._install_artifact_files`;
- the verifier freshness paragraph, the stale wording in the FLAGGED bullet,
  and "present and fresh" in the VERIFIED bullet (`pm_core/qa_loop.py`);
- the "Shared helpers" section of `pm_core/docs/qa_library.md`;
- recipe text about `pgrep`/bare `wait`/the helper, and the render-through-
  helper form. Recipes render directly in the foreground as on master; the
  i5 `|| true` ffprobe fallback only mattered inside the helper's `set -e`
  script, so it is dropped too.

After the reduction the PR no longer touches `pm_core/` at all.

**Kept** — real recipe bugs that any model following the recipes hits.

## Requirements

R1. **Create the capture directory before recording.** Both
   `tmux-screen-recording.md` and `cli-recording.md` `mkdir -p` the capture
   directory first — in the runnable capture block, not only in prose, so a
   worker that pastes the block gets it. `asciinema rec` prints "asciicast
   saved" and exits 0 while writing nothing when the directory is missing, so
   a missing `mkdir` looks like a successful capture that does not exist (the
   tmux recipe's `pipe-pane` transcript is lost the same way).

R2. **Remove a stale cast before recording, and a stale recorder.** Both
   recipes `rm -f` the cast before starting the recorder. The render step
   rewrites the `.mp4` from whatever cast is on disk, so without this a
   recording that wrote nothing still produces a fresh-looking video of the
   *previous* run (and without `--overwrite`, `asciinema rec` aborts on the
   existing file and the recorder session dies). The tmux recipe also removes
   a stale `transcript.log`: `pipe-pane ... "cat >>"` appends, so an earlier
   run's log would be mixed into this run's evidence. Both recipes also clear
   the recorder session an aborted run left behind (`tmux kill-session -t
   pm-recorder` / `tmux -L scaffold kill-session -t rec`): `new-session` fails
   with "duplicate session" while it exists, and the readiness wait would
   then pass on the previous run's recorder. The CLI scaffold clears the
   session, not the server — `kill-server` followed a few milliseconds later
   by `new-session` races the server's exit ("server exited unexpectedly",
   reproduced ~7 times in 40 tight iterations). Both recipes also remove a
   stale `recorder.status` (R4): a leftover one would let a recorder that was
   torn down before it finished pass the exit-status check. The two failure
   logs of R11 (`recorder-stderr.log`, `recorder-pane.log`) are cleared with
   them, so a run that never wrote one cannot present the previous run's
   failure as its own.

R3. **Wait for the recorder to be up before sending keys, on the right
   handle.** Keystrokes sent before asciinema has attached are silently lost,
   so an immediate `exit`/detach leaves the recorder running. Both recipes
   have a bounded readiness wait that also ends when the session goes away
   (a quick one-shot command legitimately finishes first). The *handle*
   differs by recipe: the tmux recipe waits on pane content, because there the
   pane is the attach client and the cast exists before it renders; the CLI
   scaffold waits on the cast file, because asciinema writes the header the
   moment it starts recording, and pane content is not a readiness signal
   there — a command that prints nothing for a while (a long run, a quiet
   `-q` command) records fine with a blank pane (verified: the previous
   pane-content wait failed `-c 'sleep 45'` at 30 s and killed a healthy
   recording whose cast already held the header). In the tmux recipe a
   recorder that *exits* before drawing is a failure (the attach could not
   start; the cast it leaves holds asciinema's error, not the TUI), not a
   recording that finished early — the CLI scaffold still accepts an early
   exit, because a one-shot command legitimately ends the pane. In the tmux
   recipe pane content alone is not proof the attach worked: a *failed*
   attach prints "can't find session: …" into the pane and exits a few
   milliseconds later, so the content check can break on asciinema's own
   error text and the step-5 cast check then passes on a cast holding that
   error. The recipe therefore confirms the recorder is still alive a moment
   after the content appears (a settle window) and fails with the same
   "recorder exited before it drew" message otherwise. The content signal is
   unsound rather than frequently wrong: the error is drawn ~50–75 ms after
   `new-session` and the session is gone ~25 ms later, so a tight poll takes
   it as readiness in 15 of 15 runs, while the recipe's own 0.2 s cadence
   missed the ~25 ms window in 100 of 100 idle runs (and 40 of 40 loaded) —
   i.e. whether a run false-passes depends on timing, not on the state. The
   settle check makes it deterministic (0 of 15 tight-poll runs, 0 of 100 at
   the recipe cadence) and also catches a recorder that dies just after its
   first draw, which would otherwise pass with a truncated cast. Evidence:
   `$CAP/review-419c-i1/`.

R4. **Stop by ending the recorded command, then wait on the recorder's real
   handle and check the cast.** The tmux recipe detaches the attach client and
   waits (bounded) for `tmux has-session -t pm-recorder` to fail — the pane is
   started *as* the asciinema command, so the session ending is the flush
   signal — then `test -s` the cast. The CLI no-TTY scaffold ends an
   interactive `bash` with `exit` (Ctrl-C is forwarded to the recorded command,
   not asciinema) and applies the same bounded wait and cast check. Tearing the
   pane down under a live recorder can truncate the cast. The CLI bound is a
   hang detector, not a time limit on the recorded work: a one-shot command
   legitimately runs as long as it runs, so the bound is raisable with
   `RECORDER_STOP_TIMEOUT` (default 30 s) and the failure message says so —
   otherwise a healthy long recording is killed at the deadline and leaves a
   cast holding only its header (verified with `-c 'echo started; sleep 45'`).
   The tmux stop step also distinguishes a recorder that ended because the
   session ended (a legitimate finish — the attach client follows the session,
   so it only exits on the detach, when the session ends, or because it died)
   from one that is *already* gone while the session it was attaching to
   still exists: that one died mid-scenario, the cast stops wherever it
   stopped, and `test -s` alone would pass on a truncated recording and
   report the run as success (reproduced live: the step-5 block exits 0 with
   a partial cast when the recorder session is gone). The recipe fails that
   case instead, and skips the detach when both are gone. The detach itself
   is the last handle that can race the recorder: a recorder that dies in the
   gap between that check and the key send makes `tmux send-keys` fail
   (verified live: "can't find pane", exit 1), after which the stop wait
   exits at once on the gone session and `test -s` passes on the truncated
   cast — the same false success through a smaller window. The failed detach
   is therefore a failure with the same "cast is incomplete" message.
   `test -s` is not proof the recording finished in either recipe. In the CLI
   pane there is no independent witness at all, so an asciinema killed
   mid-recording leaves a header-only cast that passes (reproduced live:
   SIGKILL 1 s into a 60 s one-shot left a 117-byte cast and the previous
   scaffold printed success). In the tmux recipe the target session is a
   witness *only while it is alive*: the both-gone branch above has no live
   session left, and a recorder killed mid-scenario followed by (or just
   before) a session teardown leaves a truncated cast that `test -s` accepts
   (reproduced in the execution harness: the previous recipe exits 0 on a
   non-empty cast with no recorder left). Both recipes therefore have the
   pane's shell record asciinema's *own* exit status (`…; echo \$? >
   …/recorder.status` — the `\$` survives this shell's double-quote expansion
   and is expanded by the pane's shell), fail on a missing status file (the
   pane was torn down before asciinema returned) or a non-zero one, and
   remove a stale status file in step 0 with the stale cast. asciinema's
   status is 0 whenever the recording ran to completion — the *recorded*
   command's status is not propagated (verified: `-c 'exit 3'`, and a
   recorded command killed by a signal, both exit 0) — so recording a failing
   command is still a valid recording, while an asciinema killed by a signal
   exits 128+N. Verified live for the tmux recipe (real tmux 3.2a, asciinema
   2.1.0): nominal detach → status 0; asciinema SIGKILLed mid-recording →
   status 137 on a non-empty cast; server killed mid-recording → no status
   file; and the legitimate "the pm session ended, the attach followed it
   out" finish → status 0 on a complete cast, so the check does not reject a
   real recording.

R5. **CLI scaffold writes the cast where the render reads it.** The no-TTY
   scaffold uses `<capture-dir>/<short-name>/recording.cast`, matching every
   other CLI form and the render block; the old scaffold wrote
   `<capture-dir>/recording.cast`, so a worker following it would render
   nothing.

R6. **Bound the remaining readiness polls, and poll the right handle.** The
   tmux recipe's pm-session poll (60 s) and the web-UI recipe's `until curl`
   (120 s) carry a deadline with an actionable failure instead of hanging
   forever when the session/server never comes up. The tmux poll waits on the
   computed session (`tmux has-session -t "$TARGET"`), not on `tmux ls | grep
   '^pm-'`: that also matches the recipe's own `pm-recorder` session (and any
   other project's pm session), so the poll would pass before the target
   exists and the failure path would never fire. An empty target is rejected
   first because `tmux has-session -t ''` succeeds. The web-UI poll also stops
   the server it started, and bounds each attempt (`--connect-timeout 2
   --max-time 5`) because a deadline is only consulted between attempts. It
   also refuses to start at all when something *already* answers on the port:
   a previous run's server (or another scenario using the same default port)
   would satisfy the poll, this run's app would never bind, and the driver
   would record that other app as this run's evidence — the same "the wait
   matched the wrong handle" bug as the `grep '^pm-'` poll, one layer down.
   The probe is `curl` without `-f` on purpose: any HTTP answer, including a
   404, means the port is taken. The
   tmux transcript pipe is attached *without* `-o` (which only opens a pipe
   when none is attached): a pipe left behind by an aborted run would
   otherwise make the step a silent no-op, so no `transcript.log` is ever
   written while the cast check still passes. Every tmux failure path stops
   the pipe before exiting. The stop is best-effort (`2>/dev/null || true`):
   a recording that legitimately ended because the pm session itself ended
   reaches the cleanup with the target gone, where `tmux pipe-pane` prints
   "can't find session: …" and returns 1 — noise on a *successful* run that a
   worker can read as a failure. The pipe is closed by the session's death
   anyway, so the error carries no information.

R7. **Regression coverage.** `tests/test_qa_artifact_recording_recipes.py`
   asserts the kept recipe behaviour: capture-dir creation in the runnable
   block, stale-cast and stale-transcript removal, scaffold parses, recorder
   readiness before keys on the right handle (pane content for tmux, the cast
   file for the CLI scaffold), the raisable CLI stop bound, bounded stop +
   cast check, the CLI `exit` stop, the
   CLI scaffold cast path, the pm-session poll targeting the computed handle
   (and not `grep '^pm-'`), the bounded readiness polls (including the
   web-UI failure path stopping the server it started), clearing a stale
   recorder session before starting a new one (session, not server, for the
   CLI scaffold), the transcript pipe being reattachable, a tmux recorder
   that exits before drawing failing instead of passing, the tmux
   settle check that keeps a failed attach's error text from counting as a
   drawn TUI, a tmux recorder that is already gone before the detach while
   the target session still exists failing instead of passing on a truncated
   cast, a detach that itself fails because the recorder vanished in that
   gap failing the same way, the recorder readiness wait carrying its own
   deadline (the pm-session poll's `deadline` would otherwise satisfy a
   looser assertion), and the recorder-status handle in *both* recipes: the
   file the pane command writes is the file the stop step reads, a stale one
   is cleared with the stale cast, and `$?` survives the scaffold's own
   quoting (each statement is run through a stub `tmux` and the captured pane
   command through a stub `asciinema` that exits 7, so the status file has to
   hold 7 — and in the tmux recipe `$TARGET` still expands in the same
   command); and the web-UI driver block refuses an unset `CAPDIR` instead of
   creating a `node_modules` link in the worker's cwd.
   The capture flow is also *executed*, not only matched as text
   (`TestCaptureFlowExecution`): each recipe's fenced capture block runs
   against stub `tmux`/`pm` that drive a session table, so the readiness and
   stop logic is exercised. Cases: CLI completes; a recorder that never
   writes a cast fails at its bound; a recorder that dies without a cast
   fails; a CLI recorder killed mid-recording fails on its status although
   its cast is non-empty; a CLI recording with no status file fails; tmux
   completes (and prints no tmux error while stopping the pipe);
   a recorder that exits before drawing fails; a failed attach that drew its
   error text fails; a recorder that died mid-scenario fails on its
   truncated cast; a detach that fails because the recorder vanished in the
   check-to-send gap fails; a tmux recorder killed mid-scenario whose target
   session is *also* gone fails on its status although its cast is non-empty
   (no live session is left as a witness, so `test -s` decides alone); and a
   recording that ended with the session itself passes.
   Each of those fails when its fix is reverted (checked by mutation: dropping
   the settle re-check, the mid-scenario branch, the detach-failure branch,
   the CLI cast check, the CLI status check, the tmux status check, and the
   `2>/dev/null` on the pipe stop each fail exactly one case).
   The render/finalize assertions cover both recording recipes (a failed
   render leaves no mp4/gif and exits non-zero with its message) and the
   web-UI recipe (the pre-driver cleanup drops the previous run's webm, mp4,
   trace, DOM dump and screenshots before the app starts, and the transcode
   drops the old mp4 before running and checks the new one exists). The
   web-UI driver's module resolution is executed too: the recipe's own run
   block is driven against a fake global Playwright install, so the link has
   to make the driver's bare `import 'playwright'` resolve (a wrong link
   target reproduces the image's `ERR_MODULE_NOT_FOUND`); with a local
   install already in place the block must not link the global one *inside*
   it, and with no install at all it must stop at its own resolution check
   with an actionable message (both fail against the unconditional
   link-and-continue form). The web-UI app-start block is executed against
   stub `pm`/`curl`/`my-app` (`TestWebUiStartExecution`): it completes
   normally, it refuses a port something already answers on (and never
   starts the app), and a server that never answers fails at its deadline.
   R10's three leftovers are covered too: both recording recipes carry the
   `agg` install line *before* the render block (the render block is looked
   up by its own content, `agg --idle-time-limit`, because the section now
   holds a second fenced block), the CLI stop message names the interactive
   remedy, and the web-UI finalize block is executed both ways — with no
   `CAPDIR` it exits before ffmpeg runs, and with `CAPDIR` set a stub ffmpeg
   still produces the mp4 and drops the webm.
   R11's evidence handling is covered as well: both recipes clear a stale
   `recorder-stderr.log`/`recorder-pane.log` in step 0; each pane command's
   redirect is driven through the stub `tmux` + a stub `asciinema` that
   writes to stderr, so the text has to reach the file step 4/step 5 reads;
   the CLI's documented `'\''` form is driven through the recipe's own
   statement and asciinema has to receive the command intact; and the two
   stop-timeout paths are *executed* (stub mode `stuck`: the recorder never
   goes away), asserting that the message names `recorder-pane.log` and that
   the file holds what the recorder drew. The tmux readiness timeout is
   executed too (mode `norec`). All ten new/tightened assertions fail
   against the previous recipes.
   R12's leftovers are covered as well: the render block is *executed* with
   stubs that model each stage's contract — a failed `ffmpeg` that leaves a
   partial mp4 (the file is removed and the run fails), a healthy render (rc
   0, mp4 written, gif dropped), and a missing cast (fails with "there is no
   cast to render" and does not tell the worker to install `agg`); the
   web-UI transcode gets the partial-mp4 case; the tmux transcript is
   covered both as text (the attach's failure branch, the end-of-run check)
   and by execution (stub modes `pipefail` and `notranscript`); and the
   finalize/driver guards are driven through a *real interactive bash on a
   pty* (`script -qec bash`), where the old `: "${VAR:?}"` form let the next
   line run and created `node_modules` in the worker's cwd. All of those fail
   against the previous recipes.
   R13's leftovers are covered by running the *stop block alone*, the way a
   worker pasting it into a fresh shell does (`_stop_block`, sharing the
   stub `tmux`/`pm` harness): a stop timeout must save the pane it names and
   must not print `command not found` (both recipes, stub mode `stuck`); the
   tmux both-gone finish must pass with `$TARGET` unset (the stub's
   `has-session` now models real tmux, where an empty target *succeeds*, which
   is what made the pre-fix recipe report a legitimate finish as an
   incomplete recording); and with `pm session name` printing nothing the
   step must refuse rather than act on an empty target. The web-UI driver
   block is run with `APP_URL` unset and must stop before the driver, whose
   fallback would otherwise drive port 8000. All five fail against the
   previous recipes (checked with the pre-fix recipes in place: `dump_pane:
   command not found` in both stop blocks, "recorder exited while the TUI was
   still running" for the unset target, and the driver running on the
   fallback URL).
   R14's leftovers are covered too: step 1 must record the app's pid in
   `server.pid` (and clear a stale one first), the teardown must stop a real
   process whose pid it reads from that file in a *fresh* shell (the test
   starts `sleep 300` and reaps it with `wait`, so the assertion does not
   depend on `kill -0`, which a zombie in a non-reaping container satisfies),
   the teardown must still refuse with neither `SERVER_PID` nor `CAPDIR`, the
   Layer 2 protocol block must stop before running `curl` with `CAPDIR`/
   `APP_URL` unset and must still write `http.log` and `sse.log` when they
   are set, and the tmux pm-session failure must say its output was
   discarded. All of those fail against the previous recipes except the
   healthy-path Layer 2 case (verified with the pre-fix recipes in place:
   `rc=0` with `/http.log: Permission denied`).
   R18's driver handle is covered by executing the driver block against a
   driver that resolves Playwright and then throws: the block must exit
   non-zero with "the driver failed", and the earlier attempt's
   webm/trace/`dom.html`/screenshot must be gone (the pre-fix block ran the
   driver with no check and left all four in place), plus step 1's cleanup
   must glob `*.webm` under the `${CAPDIR:?}` guard.

R8. **A failed render must not leave the previous run's video, and the
   recorded command must survive the scaffold's quoting.**
   - The render steps delete this run's outputs before rendering:
     `rm -f "${cast%.cast}.mp4" "$cast.gif"` in both recording recipes, and
     `rm -f "$CAPDIR/recording.mp4" "$CAPDIR/trace.zip" "$CAPDIR/dom.html"
     "$CAPDIR/http.log" "$CAPDIR/sse.log" "${CAPDIR:?}"/*.webm
     "${CAPDIR:?}"/*.png` before the
     web-UI driver (plus the mp4 again before the transcode; R18 explains why
     the webm glob is `*.webm`). The `${CAPDIR:?}`
     on the globs is the guard that keeps an unset variable from expanding the
     pattern against the filesystem root. `ffmpeg` does
     not touch an existing output when it fails (verified: a missing input
     leaves the old mp4 byte-for-byte), so without this a render that failed
     — `agg` missing, unreadable cast, failed transcode — still ends with a
     `recording.mp4` that the manifest and the report present as this run's
     evidence; the stale gif likewise lets a failed `agg` encode an earlier
     run. The web-UI driver's trace, screenshots and DOM dump are cleared
     with the webm for the same reason: a driver that dies at the first
     locator writes none of them, so the earlier run's files would be listed
     as this run's evidence. The Layer 2 protocol logs (`http.log`,
     `sse.log`) go too: a run that never re-captures the protocol would
     otherwise present the earlier run's logs as this run's. This is the
     same bug class as rendering a stale cast (R2), one level up.
   - Each render step then `test -s` the mp4 and exits 1 with an actionable
     message ("render produced no mp4 — …") instead of exiting 0 with no
     video. The web-UI step keeps the webm until the mp4 exists so a failed
     transcode can be retried. R12 checks the renderers' exit statuses too,
     because a failed renderer leaves a partial output that `test -s` accepts.
   - The CLI scaffold's `<command-to-record>` sits inside single quotes
     inside the outer double-quoted `new-session` argument, so the recipe
     documents the *escaped* form for the `bash -c` command form:
     `-c 'bash -c \"set -x; cmd-one; cmd-two\"'` (and notes the outer shell
     expands `$` first). Pasting the double-quoted form unescaped ends the
     outer string — verified live: the shell splits the command into stray
     words, the recorder exits immediately and the scaffold fails with
     "asciinema wrote no cast". The escaped form was verified end to end with
     real asciinema + tmux (rc 0, the cast holds the recorded output).
   - A `'` inside the command needs `'\''`, for the same reason and in the
     same place: the single quotes around `<command-to-record>` are ordinary
     characters by the time the pane's shell parses the command, so an
     unescaped one ends it early. Verified live: the natural
     `-c 'pm pr note add pr-x 'a note''` leaves asciinema exiting 2
     ("expected one argument") with no cast, while
     `-c 'pm pr note add pr-x '\''a note'\'''` records the command intact
     (the recorded `pm` received `pr-x` and `a note` as separate arguments).
     Recording a command with a quoted argument is routine in QA, so the
     recipe documents the escape.

R9. **The web-UI driver has to resolve Playwright before it can run.** The
   QA image installs Playwright globally under `/usr/lib/node_modules` and
   advertises it through `NODE_PATH`, which Node's *ES module* resolver
   ignores, so the recipe's `driver.mjs` (`import { chromium } from
   'playwright'`) dies at startup with `ERR_MODULE_NOT_FOUND: Cannot find
   package 'playwright'` (verified in the QA image: rc 1, no driver output,
   no capture). A `node_modules` beside the driver that resolves the package
   fixes it, so the run block links the image's global install
   (`ln -sfn /usr/lib/node_modules node_modules`) and checks it with
   `node -e "import('playwright')…"` before running the driver; the Tooling
   section explains why the image alone is not enough. Verified end to end in
   the QA image: after the link the same driver launches Chromium and drives
   a page (rc 0), and with a wrong link target the run fails with the same
   `ERR_MODULE_NOT_FOUND` the recipe now documents.

   Two guards make the step safe in the cases the image's own path does not
   cover. The link is conditional (`[ ! -e node_modules ] && [ -d
   /usr/lib/node_modules/playwright ]`, so a global directory that does not
   hold the package is not linked — R16): the recipe offers a *local*
   `npm i playwright` as the alternative, and an unconditional `ln -sfn`
   creates a link named after the target's basename *inside* an existing
   `node_modules` (verified:
   `node_modules/global` for a substituted target, `node_modules/node_modules`
   for the image's), and with no global install it leaves a dangling
   `node_modules` beside the driver that breaks that same fallback. And the
   resolution check now *gates* the run (`|| { …; exit 1; }`): without it the
   worker got the same `ERR_MODULE_NOT_FOUND` twice — once from the check,
   once from the driver — and no statement of what to do about it (verified:
   the old block continues into the driver after the check fails). Evidence:
   `/pm-captures/review-419c-i8/`.

R10. **Name the renderer prerequisite, and never aim a cleanup at the
   filesystem root.** Three leftovers of the same "a step that cannot do its
   job has to say so, and must not act on a handle it does not have" class:
   - The QA image ships `ffmpeg` but not `agg` (verified: `command -v agg`
     prints nothing in the pm-dev image), and R8 made a missing renderer a
     hard failure. Neither recording recipe named `agg` as a prerequisite or
     said how to get it, so the new failure message ("check 'agg' is
     installed") had no remedy in the recipe. Both render sections now carry
     the per-architecture release-binary install
     (`agg-$(uname -m)-unknown-linux-gnu` under
     `github.com/asciinema/agg/releases/latest/download`; verified: agg 1.9.0
     downloads, runs, and renders the recipe's own cast to H.264), guarded on
     `command -v agg` so it never re-downloads over a working binary (R16),
     and say not to substitute a different renderer.
   - The CLI scaffold is pasted as one block and step 3 (driving the shell)
     is comments, so a worker that pastes it whole for the `-c bash` form
     waits out the stop bound with the shell still at its prompt. The stop
     failure offered only `RECORDER_STOP_TIMEOUT`, which for an interactive
     recording just makes the same failure slower; it now names the actual
     remedy (`exit` in the recorded shell, step 3).
   - The web-UI finalize step's new `rm -f "$CAPDIR/recording.mp4"` (R8) was
     unguarded, while step 1's cleanup guards its glob with `${CAPDIR:?}` for
     exactly this reason. The blocks are pasted separately, so a worker
     running step 3 in a fresh shell had no `CAPDIR`: the `rm -f` aimed at
     `/recording.mp4` and ffmpeg at `/recording.webm`. The step now stops with
     `: "${CAPDIR:?…}"` before either.
   - The web-UI *driver* block (step 2) had the same hole, one step earlier
     and with a filesystem side effect: `cd "$CAPDIR"` with `CAPDIR` unset
     returns 0 and silently stays in the worker's cwd (verified), so the
     conditional link created `node_modules -> /usr/lib/node_modules` *there*
     (the PR workdir, say), the resolution check printed "playwright ok" on
     that stray link, and the run then died with a bare "Cannot find module
     …/driver.mjs" instead of naming the missing variable. It now stops with
     `: "${CAPDIR:?…}"` first, as the finalize step does.

R11. **A failure message has to point at evidence that still exists, and the
   recorder's own diagnostics have to survive the pane.** Every failure path
   in both recording recipes tears the recorder pane down, yet the timeout
   messages told the worker to inspect it — verified live in both recipes:
   the CLI scaffold printed "check the pane with `tmux -L scaffold
   capture-pane -p -t rec`" and its next line killed the server (the follow-up
   answers "no server running"); the tmux recipe printed "check `tmux
   capture-pane -p -t pm-recorder`" and killed that session the same way. Two
   small additions make the failures actionable and keep their evidence:
   - The pane command sends asciinema's *own* stderr to
     `<capture-dir>[/<short-name>]/recorder-stderr.log` (`… 2>
     …/recorder-stderr.log; echo \$? > …/recorder.status`). asciinema's
     startup errors (a broken `-c` command, an unwritable cast path) are
     exactly what a failed run needs, and they would otherwise die with the
     pane. Verified that this does not disturb a recording: the recorded
     command's stderr still goes through the pty and is recorded, and the
     tmux recipe's failed-attach error (`can't find session: …`, from the
     recorded `tmux attach`) still reaches the pane and the cast, so the
     pane-content readiness signal is unaffected.
   - Each timeout path saves the pane's last screen to
     `…/recorder-pane.log` before the teardown, and its message names the
     file (the save is written out at each site rather than shared through a
     helper function, because the stop step is pasted on its own — R13). The
     died-recorder messages name
     `recorder-stderr.log` instead, because in those paths the pane is already
     gone and the status/stderr files are what is left. Both files are
     cleared in step 0 with the stale cast (R2), so an earlier run's reason
     cannot be read as this run's.

R12. **A renderer's exit status is the handle; a promised artifact that was
   never written is a failure; and a guard has to stop the block, not just
   print.** Three leftovers of the "validate the artifact before declaring
   success, and act only on a handle you have" class:
   - **A failed renderer leaves a partial output.** `test -s` on the mp4 is
     not proof the encode finished: verified live in this container with real
     `ffmpeg` 4.4.2, a SIGKILLed encode leaves a **267,945-byte** mp4 (and a
     SIGTERM one 119,704 bytes), which the file check accepted as a
     successful render — the header-only-cast bug one artifact over. Both
     recording recipes and the web-UI finalize step now check the renderer's
     own exit status (`agg … || render_fail …`, `ffmpeg … || render_fail …`)
     and remove the partial output; `test -s` stays, to catch a renderer that
     reports success and writes nothing. Evidence:
     `/pm-captures/review-419c-i13/` (wrapper log + the recipe's own render
     block: rc 1, "render produced no mp4 — ffmpeg failed on the gif", no mp4
     left) and a healthy render of a real cast with agg 1.9.0 → rc 0,
     H.264 mp4, gif dropped.
   - **A missing cast is not an `agg` problem.** Every render failure used to
     say "check 'agg' is installed and the cast is readable", but the CLI
     recipe documents a `tee transcript.log` fallback for a host without
     asciinema — and that fallback writes no cast at all, so the worker was
     sent to install a renderer it already had. The render block now checks
     the cast first and says "there is no cast to render (the recording wrote
     nothing)", and the fallback paragraph says the render step will fail and
     the capture has no video.
   - **A `${VAR:?}` guard does not stop an interactive paste.** Verified in a
     real interactive bash (`script -qec bash`): `: "${CAPDIR:?…}"` prints
     the error, aborts only its own command, and the *next line still runs* —
     so the finalize block's `rm -f "$CAPDIR/recording.mp4"` aimed at
     `/recording.mp4`, and the driver block's `cd ""` + conditional link
     created `node_modules` in the worker's cwd (both reproduced; the link
     case is what the new execution test sees). The guard only stopped a
     scripted run. All three standalone guards (finalize, driver, teardown)
     are now `if [ -z "${VAR:-}" ]; then … exit 1; fi`. Step 1's cleanup keeps
     its in-command `${CAPDIR:?}` glob, which is sound in both modes because
     the expansion fails before `rm` runs (verified).
   - **The tmux transcript is a promised artifact too.** `tmux pipe-pane`
     returns non-zero when the pane is gone (verified with tmux 3.2a:
     "can't find window: 9", rc 1) and the recipe ignored it, so the run
     carried on and reported success with no `transcript.log` — the same
     silent loss as the `-o` bug, through a different cause. The attach's
     failure is now reported where it happens, and the file is checked
     (`test -s <capture-dir>/transcript.log`) before the run is called
     finished; a pipe attached to a pane that emits nothing leaves a 0-byte
     file (verified), which that check catches.
   - **The web-UI teardown silently did nothing in a fresh shell.**
     `kill "$SERVER_PID" 2>/dev/null || true` with the variable unset is a
     no-op, so the app kept the port and the *next* run's port pre-check
     refused with "something already answers" — a failure the worker cannot
     connect to its own missed teardown. The teardown now stops with that
     reason, and says to run it in the shell that started the app.

R13. **The stop step is pasted on its own, so it must not depend on shell
   state from an earlier paste.** A scenario that needs interactive driving
   cannot paste the whole capture block — step 3 *is* the driving — so step 4
   of the CLI scaffold and step 5 of the tmux recipe run in a fresh shell
   (the recipe's own `RECORDER_STOP_TIMEOUT` note says workers paste steps
   separately). Two things broke there, both the PR's own class:
   - **A failure message pointing at evidence that does not exist.** The pane
     save was a `dump_pane()` function defined back in the first block, so
     the fresh shell printed `bash: dump_pane: command not found` (verified
     in this container with real tmux 3.2a + asciinema 2.1.0) and the timeout
     message still claimed "the pane is saved in …/recorder-pane.log" while
     no file was written. Both recipes now write the `capture-pane`
     redirection out at each failure site instead of calling a function.
   - **Acting on a handle the step does not have.** `$TARGET` comes from step
     1, and `tmux has-session -t ''` *succeeds* (verified, tmux 3.2a), so an
     unset target made the legitimate "the scenario ended the pm session"
     finish report "recorder exited while the TUI was still running — the
     cast is incomplete" (reproduced in the execution harness), and
     `pipe-pane -t ':0.0'` streamed whatever pane tmux picks as current
     (returns 0 — verified) instead of the target's. Step 5 now re-derives it
     (`TARGET=${TARGET:-$(pm session name)}` — the command prints the computed
     name from cwd, whether or not the session exists) and refuses an empty
     one with a message naming the fix.
   - Same class, one variable over: the web-UI driver block's guard checked
     only `CAPDIR` while its own prose says both variables come from step 1,
     and the driver falls back to `process.env.APP_URL ||
     'http://localhost:8000'` — so with `APP_URL` unset the block drove
     whatever answers on port 8000, exactly what the step-1 busy-port
     pre-check exists to prevent. The guard now names both.

R14. **A handle that has to survive a shell boundary is written down, and a
   block with no handle stops before it writes somewhere it did not mean.**
   Two leftovers of the PR's own class found by review loop e7e1 i1, both in
   `web-ui-recording.md` (plus two small wording/prerequisite fixes):
   - **The teardown could not work from a fresh shell.** `SERVER_PID` is a
     shell variable from step 1 and the app is backgrounded, so by the time
     the teardown block runs (every block in this recipe is pasted into a
     fresh shell) the variable is gone. Verified in this container: the block
     refused with "SERVER_PID is unset — run the teardown in the shell that
     started the app", and the app kept holding the port — while re-running
     step 1 is not a remedy, because its own app answers the port pre-check
     the block added in i8 (so the worker's only recovery was an undocumented
     manual kill). Step 1 now writes the pid to `$CAPDIR/server.pid`
     (cleared with the other stale outputs first, so the teardown cannot
     signal a recycled pid) and the teardown falls back to it, then removes
     it. Verified live: step 1 in one shell records the pid of a live app,
     and the teardown in a fresh shell (no `SERVER_PID`) exits 0 and the app
     is gone.
   - **The Layer 2 protocol block had no guard, and reported success while
     writing nothing.** With `CAPDIR` unset its redirects are `/http.log` and
     `/sse.log` — into the filesystem root when the worker is root, and
     "Permission denied" otherwise — and the block still **exits 0**,
     because the failing redirects are backgrounded/ignored and the last
     command succeeds. So a run with no protocol capture at all read as
     success, the same "silent success" the rest of the recipe fixes.
     Verified: `rc=0` with both redirects denied. The block now stops on an
     unset `CAPDIR`/`APP_URL` before the first redirect, like the driver,
     finalize and teardown blocks; with both set it still writes `http.log`
     and `sse.log` (verified).
   - **A failure message pointing at discarded output.** The tmux recipe's
     pm-session readiness failure said "check 'pm session' output", but step
     1 runs it as `( pm session >/dev/null 2>&1 ) &` — there is no output to
     check. It now says the output was discarded and to run `pm session` in a
     tmux pane (where it has a tty) to see why.
   - **The `agg` install line could not create its own directory.** `curl -o
     ~/.local/bin/agg` fails outright when `~/.local/bin` does not exist
     (`curl` does not create parent directories), which leaves the documented
     remedy silently inert and the render failing with "is 'agg' installed?".
     Both render sections `mkdir -p ~/.local/bin` first.

R15. **A start step that cannot do its job says so, instead of being
   misdiagnosed downstream.** Four leftovers of the PR's own class found by
   review loop e7e1 i2, all reproduced live in this container:
   - **An unusable capture directory is not a recorder problem.** All three
     recipes `mkdir -p` the capture directory and ignored the result. With
     `<capture-dir>` under a regular file, the tmux recipe ran on and ended
     with "recorder exited before it drew — see the cast and
     `recorder-stderr.log`" (neither exists), the CLI scaffold with its
     readiness timeout naming a pane log it could not write, and the web-UI
     start block **exited 0** — it launched the app, wrote no pid file and
     reported success with no capture directory at all (the same "silent
     success while writing nothing" as the Layer 2 block). Each `mkdir -p`
     now stops the run with "could not create … — check the path and its
     permissions".
   - **A failed `tmux new-session` is not a recorder that died.** Both
     scaffolds ignored `new-session`'s exit status. Verified with real tmux
     3.2a: a missing `TMUX_TMPDIR` makes `new-session` fail (the client
     reports "server exited unexpectedly"; a concurrent run holding the name
     gives "duplicate session"), the pane command never runs, and the recipe
     reported "recorder exited before it drew" / "asciinema wrote no cast",
     pointing at a cast and a `recorder-stderr.log` that were never written.
     Both scaffolds now stop with "could not start the recorder session — see
     tmux's error above" (the tmux recipe stops the transcript pipe; the CLI
     scaffold tears its private server down, like its other failure paths).
   - **The web-UI driver block's `cd "$CAPDIR"` was unchecked.** The guard
     covered an *unset* `CAPDIR` but not a *missing* one: `cd` fails, the
     shell stays in the worker's cwd, and the conditional link plus the
     resolution check run there — verified: `node_modules` was created in the
     cwd and the check printed "playwright ok", after which the driver dies
     with a bare "Cannot find module …/driver.mjs". The block now stops with
     "capture directory … does not exist — create it and run step 1".
   - **A failed web-UI start left its dead pid in `server.pid`.** The
     readiness failure kills the app but kept the file, which the teardown
     falls back to — so a teardown after the failure could signal a recycled
     pid, the exact reason step 1 clears a stale `server.pid`. The failure
     path now removes it.
   - Also corrected: the render sections claimed categorically that "the QA
     image ships `ffmpeg` but **not** `agg`". The bundled `Dockerfile` has
     installed `agg` since e51274fe (2026-05-30); the image actually used for
     QA here was built before that, which is why it was missing. The prose now
     says `agg` *may* be missing and keeps the `command -v agg` conditional
     (the actionable rule was already conditional).

R16. **A remedy must not damage the thing it is meant to fix, and no request
   may be left unbounded.** Three leftovers of the PR's own class found by
   review loop e7e1 i3:
   - **The `agg` install block re-downloaded over a working binary.** The
     prose said to install `agg` only when `command -v agg` prints nothing,
     but the runnable block was unconditional — and the bundled `Dockerfile`
     now installs `agg`, so a worker pasting the remedy block on a current
     image would replace it for nothing. That is not harmless: the image's
     `PATH` puts `~/.local/bin` first, and `curl -o` writes in place, so a
     transfer that fails partway leaves a truncated binary that shadows the
     working one (verified in this container with real `curl`: a server that
     closed mid-body replaced a working 12-byte `agg` with a 500-byte
     partial). The block is now guarded on `command -v agg` in both recording
     recipes, matching its own prose; verified that the guarded block still
     installs `agg` 1.9.0 for real when it is missing.
   - **The Playwright link tested the parent directory, not the package.**
     The driver block linked `/usr/lib/node_modules` whenever that directory
     existed. With the directory present but `playwright` absent, the link
     cannot resolve, the block then stops at its own check and tells the
     worker to create *that same link* (a remedy that cannot work), and the
     stray `node_modules` sends a later `npm i playwright` into the global
     install instead of the capture directory. The guard now tests
     `/usr/lib/node_modules/playwright`, so the link is created only when the
     package is actually there and the `npm i playwright` fallback is left
     usable.
   - **The protocol block's route snapshots were unbounded.** R6 bounded the
     step-1 readiness poll per attempt because a deadline is only consulted
     between attempts, but the Layer 2 `curl` per route had no timeout at all:
     a route that accepted the connection and never answered blocked the
     block forever — the unbounded wait this PR removes everywhere else. Each
     route now carries `--connect-timeout 2 --max-time 10`; a timed-out route
     is recorded in `http.log` as curl's own error with status `000`, so that
     route's failure is the evidence rather than a hang.

R17. **A refusal must name a remedy that still exists, and the produced-files
   list must match what the flow writes.** Three leftovers of the PR's own
   class found by review loop e7e1 i4:
   - **The busy-port refusal pointed at a teardown that cannot work.** Step 1
     clears a stale `server.pid` *before* the port pre-check, on purpose: the
     server answering may be another scenario's, so acting on this capture's
     recorded pid could signal an innocent process. But the refusal said only
     "stop it (or pick another PORT)", and the documented recovery is the
     teardown — which now has no pid to read. Verified live with a real local
     server on the port: the message named neither the manual hunt nor the
     fact that the pid file is gone. It now says the pid is no longer in
     `server.pid` and to find it with `ss -ltnp` on the port, so the failure
     is actionable without the file this step deleted.
   - **The Playwright resolution failure offered a remedy that cannot work.**
     The block links the image's global install only when
     `/usr/lib/node_modules/playwright` exists (R16), but the failure message
     still said "link the image's global install ('ln -sfn
     /usr/lib/node_modules node_modules') or run 'npm i playwright' here" — on
     a host without that package the first suggestion leaves a link that
     cannot resolve, the same flaw the guard fix was about. The message is now
     conditional ("if /usr/lib/node_modules/playwright exists, link it …;
     otherwise run 'npm i playwright' here").
   - **The produced-files list omitted the flow's diagnostics.** Both
     recording recipes write `recorder.status` and `recorder-stderr.log` into
     the capture directory (and `recorder-pane.log` when a wait gives up),
     while their manifest section asks for "every non-default file the
     capture produced". A worker following the produced-files list does not
     know they exist, so the manifest's `## Files` section and the directory
     disagree. Both lists now name them as failure evidence and say to
     mention whichever exist in the manifest.

R18. **The web-UI driver is a job too: its exit status is the handle, and its
   auto-named video is stale evidence.** Two leftovers of the PR's own class
   found by review loop e7e1 i5, both reproduced live in this container with
   real Playwright (chromium-1223, node 22.22.2):
   - **The driver's exit status was not checked.** Step 2 ended on
     `CAPDIR=… APP_URL=… node driver.mjs`, and the finalize step (pasted
     separately) then transcoded whatever webm was on disk. A driver that
     fails therefore surfaced one block later as "transcode produced no mp4 —
     ffmpeg failed on the driver's webm" — a misdiagnosis that sends the
     worker to the encoder — and a driver that fails after an earlier attempt
     had left a webm produced a *successful* transcode of that earlier
     attempt, presented as this run's recording. The block now checks the
     driver's own exit status and stops with "the driver failed — this run's
     video, trace and screenshots are incomplete".
   - **Playwright's auto-named video is a stale artifact nothing cleared.**
     The driver renames its video onto `recording.webm`, so the flow only
     cleared that name. Observed in this container: after a driver was killed
     mid-recording, Playwright's auto-named `page@<hash>.webm` was left in the
     capture directory and `ffprobe` reports a real duration for it — a
     *valid, playable* partial recording. (Whether the browser gets to
     finalize the file is timing-dependent, but the cleanup gap is not: the
     file is one Playwright can leave there, and nothing else in the flow ever
     removes it — the pre-fix step-1 `rm` leaves it and the `*.webm` glob
     removes it, shown in `probe-e` below.) Step 1's cleanup is now `"${CAPDIR:?}"/*.webm` (and the
     comment says why), and step 2 clears this attempt's `*.webm`,
     `trace.zip`, `dom.html` and `*.png` before running the driver, because
     that block is pasted on its own when a driver is adapted and retried: a
     retry that fails part-way would otherwise leave the earlier attempt's
     complete webm for the finalize step to transcode into "this run's"
     recording. (A driver that exits through its own `.catch` leaves no webm
     at all — verified — which is why the stale-video case needs the kill.)

R19. **A missing transcode input is not an ffmpeg problem.** One leftover of
   the PR's own class found by review loop e7e1 i6, reproduced live in this
   container with real ffmpeg 4.4.2. The finalize step checked ffmpeg's exit
   status and the mp4 (R12), but never that there was a webm to transcode: a
   driver that exits 0 without recording — `recordVideo` dropped while
   adapting the skeleton, or a `video` that comes back null — leaves no
   `recording.webm`, and the step then handed ffmpeg a nonexistent input and
   reported "transcode produced no mp4 — ffmpeg failed on the driver's webm",
   pointing the worker at the encoder. That is the same misdiagnosis R12 fixed
   for a missing cast ("there is no cast to render", not "check 'agg' is
   installed"), one artifact over. The step now checks `recording.webm` before
   running ffmpeg and stops with "there is no webm to transcode — the driver
   wrote no video; re-run step 2 and check the driver's recordVideo option".
   The stale mp4 is still removed first, so a run that recorded nothing cannot
   present the previous run's video as its own.

R20. **A failure must not leave an output the manifest can present, a produced
   file must be where the capture looks, and a failed send must not pass as a
   legitimate finish.** Four leftovers of the PR's own class found by review
   loop e7e1 i7:
   - **The web-UI finalize's "wrote nothing" branch left an empty mp4.**
     `test -s` is the check for a renderer that reports success and writes
     nothing (R12), but that branch only printed. Verified with the recipe's
     own block and a stub `ffmpeg` that exits 0 after truncating its output:
     the step exits 1 and leaves a **0-byte** `recording.mp4` in the capture
     directory — an output left on a failed step, which the recording recipes'
     `render_fail` removes for exactly this reason. The branch now removes it
     too; the webm stays, so the transcode can still be retried.
   - **The CLI recipe's no-asciinema fallback wrote its transcript into the
     worker's cwd.** The fallback was `| tee transcript.log`, a relative path:
     the capture directory ends up with no transcript while the manifest lists
     one — the same "a promised artifact is written somewhere the capture does
     not look" bug as the no-TTY scaffold's cast path (R5), one file over. It
     is now `| tee <capture-dir>/<short-name>/transcript.log`, and the
     produced-files list names the file (noting that such a capture has no
     cast and no video).
   - **A failed `pm tui send` in the driving step passed as a legitimate
     finish.** Step 5's both-gone branch is right to accept "the scenario
     ended the pm session itself" — but a TUI that *dies* mid-scenario (a
     crash) leaves exactly the same end state, so step 5 passes on a cast that
     stops before the behaviour under test, and nothing in the recipe said so.
     The driving step now says a `pm tui send` that fails means the TUI is
     gone, the scenario did not run, and the capture must be re-run rather
     than accepted (the send that quits pm on purpose is the one case where a
     failure is the quit racing the send).
   - **The driving step used `$TARGET` without re-deriving it.** Step 4 is
     pasted on its own for a scenario, the same reason step 5 re-derives the
     handle (R13), and an empty `$TARGET` is not a no-op here: `pm tui send
     -s ""` falls back to auto-detection — the cwd's session, then *any* pm
     session with a TUI (`pm_core/cli/helpers.py::_find_tui_pane`) — so the
     keys can drive a different TUI than the one being recorded, with no
     error at all and a cast that never showed the behaviour. Step 4 now
     re-derives `TARGET=${TARGET:-$(pm session name)}` and refuses an empty
     one, as step 5 does.

   Considered and rejected: a liveness wait in the web-UI teardown (`kill`
   plus a bounded check that the pid is gone). The teardown's remaining job is
   best-effort signal delivery, PID 1 does not reap in the QA container (so
   `kill -0` cannot tell a zombie from live work), and a liveness wait would
   reintroduce exactly the waiting logic the scope decision moved to the
   watcher (pr-ff9b728). The busy-port refusal already names the manual pid
   hunt (`ss -ltnp`) for an app that survives its teardown.

## Non-goals
- **No product polling loop.** There is no checked-in `pgrep` loop to fix.
- **No new helper, prompt block, verifier text, or QA-loop change.** Those
  were the dropped scope above.
- **No new `claude -p` usage** (session rule).

## Files

| File | Change |
|---|---|
| `pm/qa/artifacts/tmux-screen-recording.md` | capture-dir mkdir (checked), stale cast + transcript + recorder status removal, recorder readiness, bounded stop + cast check, recorder-status handle so a recorder killed while the target session also ended is not a success, bounded pm-session poll on `has-session -t "$TARGET"`, failed `pipe-pane` reported + `transcript.log` checked, stale render outputs cleared + renderer exit statuses checked + mp4 checked, `agg` prerequisite + install line, asciinema's own stderr + the pane's last screen saved on failure (R11), step 5 re-derives `$TARGET` and saves the pane inline because it is pasted on its own (R13); the pm-session readiness failure says its output was discarded instead of pointing at it, the `agg` install creates `~/.local/bin` first (R14), a failed `new-session` is reported as a start failure (R15), the `agg` install is guarded on `command -v agg` so it cannot replace a working binary (R16), the produced-files list names the flow's diagnostics (R17), and the driving step says a failed `pm tui send` means the scenario never ran, so the capture must not be accepted, and re-derives `$TARGET` (refusing an empty one) so its sends cannot auto-detect a different TUI (R20) |
| `pm/qa/artifacts/cli-recording.md` | same capture fixes; no-TTY scaffold rewritten (cast path, readiness, `exit` stop, bounded wait + cast check, escaped command form, recorder-status handle so a killed recorder is not a success); stale render outputs cleared + renderer exit statuses checked + mp4 checked + no-cast failure named; `agg` prerequisite + install line; stop failure names the interactive remedy; `'\''` escape documented; `tee` fallback reconciled with the hard-failing render; asciinema's own stderr + the pane's last screen saved on failure (R11), saved inline in step 4 for the same paste-alone reason (R13); the `agg` install creates `~/.local/bin` first (R14); the capture-dir `mkdir` and the recorder `new-session` are checked (R15); the `agg` install is guarded on `command -v agg` (R16); the produced-files list names the flow's diagnostics (R17); and the `tee` fallback writes its transcript into the capture directory, with the produced-files list naming it (R20) |
| `pm/qa/artifacts/web-ui-recording.md` | port pre-check (refuses a server already answering) then bounded `until curl` with per-attempt timeout and server cleanup; stale webm/mp4/trace/screenshots/DOM dump/protocol logs cleared before the driver + mp4 checked on ffmpeg's exit status (the webm glob is `*.webm`, so Playwright's auto-named video from a killed driver goes too — R18); finalize/driver/teardown guards stop the block (`if … exit 1`, because `${VAR:?}` only stops a scripted run); driver resolves the image's global Playwright through a conditional local `node_modules` (ESM ignores `NODE_PATH`) and stops if it does not; the driver block clears this attempt's own outputs and checks `node driver.mjs`'s exit status, so a failed driver is named where it fails instead of being misdiagnosed as an ffmpeg error and a retry cannot be finalized from an earlier attempt's webm (R18); the driver guard covers `APP_URL` too, because the driver falls back to `localhost:8000` (R13); step 1 records the app's pid in `server.pid` (cleared first, removed by the teardown) so the teardown works from a fresh shell, and the Layer 2 protocol block stops on an unset `CAPDIR`/`APP_URL` instead of redirecting to `/http.log` and `/sse.log` and exiting 0 (R14); the start block checks its `mkdir` and drops the dead pid on a failed start, and the driver block refuses a capture directory it cannot enter (R15); the Playwright link is conditional on `/usr/lib/node_modules/playwright` so a global directory without the package is not linked, and the Layer 2 route snapshots carry per-request `--connect-timeout`/`--max-time` bounds (R16); the busy-port refusal names the manual pid hunt instead of a teardown whose `server.pid` this step just cleared, and the Playwright resolution failure only offers the link when the package is there (R17); the finalize step checks that there is a `recording.webm` to transcode before running ffmpeg, so a driver that wrote no video is named instead of surfacing as an encoder failure (R19), and its "ffmpeg wrote nothing" branch removes the empty mp4 it would otherwise leave behind (R20) |
| `tests/test_qa_artifact_recording_recipes.py` | **new** regression tests for the kept recipe fixes |
| `pm/specs/pr-b19db15/impl.md` | this spec |
| `pm/specs/pr-b19db15/qa.md` | reduced QA scope (recipe fixes only) |

## Verification plan

1. Run `tests/test_qa_artifact_recording_recipes.py` — all pass (including
   the execution tests: a failed render with stub `agg`/`ffprobe`/`ffmpeg`
   leaves no mp4/gif and exits non-zero, the scaffold's documented
   escaped command form reaches asciinema's `-c` intact, both scaffolds'
   status echo survives its own quoting and lands asciinema's status on
   disk, a killed/missing recorder fails although the cast is non-empty, the
   `'\''` form arrives intact, a failing wait saves the pane where its
   message says it is, asciinema's own stderr lands on disk, and
   the capture flow runs end to end against a stub `tmux`/`pm` for its
   success and failure paths, and the stop block runs *on its own* for both
   recipes so its failure path does not depend on a function or variable
   from an earlier paste; the web-UI step-1 pid recording and the fresh-shell
   teardown against a real `sleep` process, the Layer 2 protocol block both
   ways, and the tmux readiness message; R15's start-step checks: a recorder
   session that `new-session` cannot create, a capture directory that cannot
   be created (both recording recipes, and the web-UI start block), the
   web-UI driver block with a missing capture directory, and a failed web-UI
   start removing its pid file; R16's remedies: the `agg` install block is
   *executed* both ways against a stub `curl` — with `agg` on `PATH` the
   download never runs and the binary is untouched, and with it missing the
   download runs and the file is made executable — the driver block, given a
   global `node_modules` that does not hold `playwright`, stops at its
   resolution check without creating the link, and the Layer 2 route snapshots
   carry their per-request bounds; R17's messages: the busy-port refusal names
   the manual pid hunt and the cleared `server.pid`, the Playwright resolution
   failure offers the link only when the package exists, and both recording
   recipes' produced-files lists name `recorder.status`,
   `recorder-stderr.log` and `recorder-pane.log`; R18's driver handle: step 1's
   cleanup is the `*.webm` glob (asserted together with the `${CAPDIR:?}`
   guard) and the driver block is *executed* against a failing driver that
   exits after resolving Playwright, which must fail with "the driver failed"
   and leave none of the earlier attempt's webm/trace/`dom.html`/screenshot
   behind; R19's missing input: the finalize block is *executed* with no
   `recording.webm`, which must fail with "there is no webm to transcode"
   (not an ffmpeg message), never run ffmpeg, and still drop the stale mp4;
   R20's leftovers: the finalize block is *executed* against a stub `ffmpeg`
   that exits 0 and writes an empty output, which must fail with "ffmpeg wrote
   nothing", leave no mp4 and keep the webm; the CLI fallback paragraph and
   produced-files list must name the capture-dir `transcript.log`; and the
   tmux driving step must warn that a failed `pm tui send` means the scenario
   never ran, and must re-derive `$TARGET` for its sends — executed against
   the stub `pm`, so an unresolvable target stops the step and a resolved one
   is what the sends carry).
2. Run the related suites for regressions (`test_qa_artifact_web_ui_recording.py`,
   `test_qa_instructions.py`, `test_qa_loop.py`).
3. Manual/QA evidence: the recipe fixes were exercised live in QA scenarios
   S14 (CLI capture + render, stale dir, no-TTY form), S18 (tmux TUI capture,
   bounded readiness/stop), and S20 (web-UI readiness bound + cleanup). Their
   captures live under `$(pm qa captures-path pr-b19db15)/scenarios/{14,18,20}/`.
   Re-QA re-verifies them against the reduced diff.

## Evidence notes

- The original self-match stall capture remains at
  `$(pm qa captures-path pr-b19db15)/impl/pre-fix/repro-selfmatch/`: a decoy
  shell whose command line contains the renderer pattern keeps
  `until ! pgrep -f ...` spinning after the render finished. That is the
  original bug report, not something this PR now fixes.
- The earlier `impl/post-fix/render-wait/` capture demonstrated the dropped
  `wait-for-job.sh` helper and no longer describes this diff.
- Review loop 419c i10 verified the CLI status handle live in this container
  (real tmux 3.2a + asciinema 2.1.0, the recipe's own fenced block):
  one-shot success → rc 0, `recorder.status` = 0; asciinema SIGKILLed 1 s
  into a 60 s one-shot with the pane shell left alive → status 137, "asciinema
  exited 137 — the cast is incomplete" rc 1 (the pre-fix block printed
  success on the same 117-byte cast); pane torn down with a *stale* status
  file and stale cast pre-seeded → both cleared, "recorder status is
  missing" rc 1; interactive `-c bash` driven with `exit` → rc 0, status 0,
  cast holds the driven command. asciinema's status was checked to be 0 for
  `-c 'exit 3'` and for a recorded command killed by a signal, so a failing
  recorded command is not mistaken for a failed recording.
- Review loop 419c i11 extended that handle to the tmux recipe and verified
  it live in this container (real tmux 3.2a + asciinema 2.1.0, the recipe's
  own `new-session` statement on a private socket): nominal detach → status
  0, cast 2970 bytes; asciinema SIGKILLed mid-recording → status 137 on a
  non-empty (2401-byte) cast, which the previous recipe accepted on
  `test -s`; whole server killed mid-recording → no status file, cast 2400
  bytes, so the run fails as an incomplete recording; and the legitimate
  finish where the scenario ends the pm session itself (the attach follows
  it out) → status 0 on a complete 2946-byte cast, so the new check does not
  reject a real recording. The execution harness reproduces the hole the fix
  closes: with a killed recorder *and* the target session gone, the previous
  recipe exits 0 on the non-empty cast.
- Review loop 419c i13 verified R12 live in this container (real agg 1.9.0,
  ffmpeg/ffprobe 4.4.2, tmux 3.2a, asciinema 2.1.0). A healthy render of a
  real cast through the recipe's own render block → rc 0, H.264 mp4, gif
  dropped. A real `ffmpeg` SIGKILLed 0.35 s into the encode left a
  **267,945-byte** mp4 (a SIGTERM one leaves 119,704 bytes) — a file the old
  `test -s` accepted as a successful render; with the exit-status check the
  same block exits 1 with "render produced no mp4 — ffmpeg failed on the gif"
  and removes the partial mp4. `tmux pipe-pane` against a gone target
  returns 1 ("can't find session"/"can't find window"), and a pipe attached
  to a quiet pane leaves a 0-byte transcript — both previously ignored. In a
  real interactive bash on a pty, `: "${CAPDIR:?…}"` printed its error and
  the next line still ran (`rm` would have aimed at `/recording.mp4`), and
  the driver block's link landed `node_modules` in the shell's cwd; the
  `if … exit 1` form stops both. Evidence: `/pm-captures/review-419c-i13/`
  (`render.sh`, `ffmpeg-killed-wrapper.sh`, `wrapper.log`,
  `tmux-and-teardown.log`). File 80 pass; related suites 255 pass.
- Review loop 419c i12 verified R11 live in this container (real tmux 3.2a +
  asciinema 2.1.0, the recipes' own fenced blocks, private sockets). The
  contradiction reproduced in both recipes: the CLI scaffold printed
  "recorder did not start within 30s — check the pane with `tmux -L scaffold
  capture-pane -p -t rec`" and killed the server on the next line, after
  which that command answers "no server running"; the tmux recipe's
  readiness timeout did the same to `pm-recorder`. Post-fix: the CLI stop
  timeout exits 1 with the pane saved in `recorder-pane.log` (holding what
  the recorder drew) and asciinema's own error in `recorder-stderr.log`
  ("asciinema: error: cast path is not writable"); a nominal one-shot run
  leaves an empty `recorder-stderr.log` and rc 0. The single-quote trap was
  reproduced live: `-c 'pm pr note add pr-x 'a note''` → asciinema exits 2
  ("expected one argument"), no cast, while `'\''` records and `pm` receives
  `pr-x` and `a note` as separate arguments. Verified that the stderr
  redirect does not disturb recording: a recorded command's own stderr is
  still recorded, and a failed `tmux attach` still draws "can't find
  session: …" in the pane and records it in the cast (its stderr file stays
  empty), so the pane-content readiness signal is unaffected. Evidence:
  `/pm-captures/review-419c-i12/`. Full suite 3920 passed, 1 skipped, with
  `test_merge_publish`/`test_signoff_integration` excluded (push proxy
  rejects pushes to master) and the two known baselines
  (`test_git_ops::test_keeps_unpushed_merge`,
  `test_hook_events::test_installer_writes_standalone_receiver`) deselected.
- Review loop 419c i14 verified R13 live in this container (real tmux 3.2a +
  asciinema 2.1.0, private socket): a real `rec` session running `asciinema
  rec -c 'sleep 60'`, then the CLI recipe's step-4 block pasted *on its own*
  in a fresh shell with `RECORDER_STOP_TIMEOUT=3` → rc 1, the message naming
  `recorder-pane.log`, and the file written (30 bytes of the blank pane the
  quiet command draws) — the previous recipe printed `bash: dump_pane:
  command not found` and wrote nothing. `tmux has-session -t ''` was checked
  against real tmux and returns 0 with or without a live session, which is
  what turned the tmux both-gone finish into a false "recorder exited while
  the TUI was still running" when step 5 was pasted alone; `tmux pipe-pane -t
  ':0.0'` likewise returns 0, targeting whatever pane tmux picks as current.
  `pm session name` prints the computed name from cwd with no session
  present (`pm-project_manager-eab0d61a` here), so the re-derivation is safe.
  File 85 pass (3 runs); related suites 175 pass. All five new assertions
  fail against the pre-fix recipes (checked by pointing the test module at
  the previous recipe files).
- Review loop e7e1 i1 verified R14 live in this container (bash, stub
  `curl`/`pm`/`my-app`). The Layer 2 protocol block with `CAPDIR`/`APP_URL`
  unset → `rc=0` with `/http.log: Permission denied` and `/sse.log:
  Permission denied` on the pre-fix block (the redirects aimed at the
  filesystem root and the block still reported success); post-fix → rc 1 with
  the guard's message, and with both set → rc 0 with `http.log` holding the
  route snapshot and a non-empty `sse.log`. The teardown: step 1 run in one
  shell recorded `server.pid` = the pid of a live `sleep 120` app; the
  pre-fix teardown in a fresh shell (no `SERVER_PID`) refused with "run the
  teardown in the shell that started the app" and the app kept running
  (verified), while re-running step 1 is not a remedy because that app
  answers the port pre-check; post-fix the same fresh shell exits 0 and the
  app is gone (state `Z` here, because PID 1 does not reap — judged by
  process state, not `kill -0`). File 91 pass (3 runs); the six new/
  tightened behavioural assertions fail against the pre-fix recipes, and the
  healthy-path Layer 2 case passes both ways by design.
  Full suite (this container): 3932 passed, 1 skipped, 14 failed with only
  the environment/baseline failures — 12 `test_markdown_render` tests (this
  environment has no `markdown` module: `ModuleNotFoundError`), plus
  `test_git_ops::TestPullRebase::test_keeps_unpushed_merge` and
  `test_hook_events::test_installer_writes_standalone_receiver` (both
  reproduce on origin/master). `test_merge_publish`/`test_signoff_integration`
  were excluded (the push proxy rejects pushes to master). Evidence:
  `/pm-captures/review-e7e1-i1/` (`probe.log`, the pre/post recipe copies and
  the two probe scripts).
- Review loop e7e1 i2 verified R15 live in this container (real tmux 3.2a,
  bash; stub `tmux`/`pm` for the block runs, and a real `node` for the driver
  guard). A failed `new-session` (`TMUX_TMPDIR` unset to a missing path, or a
  duplicate name) makes both scaffolds end with "recorder exited before it
  drew" / "asciinema wrote no cast" and point at a cast and
  `recorder-stderr.log` that were never written — reproduced with the
  recipes' own blocks (empty capture dir) — and post-fix they stop with
  "could not start the recorder session — see tmux's error above". With
  `<capture-dir>` under a regular file the tmux recipe reported the recorder
  as having died and the CLI scaffold hit its readiness timeout; the web-UI
  start block **exited 0** with the app launched and no pid file; post-fix
  all three stop at "could not create …". The web-UI driver block with
  `CAPDIR` set but missing created `node_modules` in the worker's cwd,
  printed "playwright ok" on that link, and then failed on `driver.mjs`;
  post-fix it stops with "capture directory … does not exist". A failed
  web-UI start (app never answers) left the dead pid in `server.pid` for the
  teardown to signal; post-fix the file is gone. The Layer 2 protocol block
  with `CAPDIR` set but missing fails both redirects, runs neither `curl`,
  and still **exits 0** (verified); post-fix it stops at the directory guard.
  File 99 pass (3 runs); the eight new assertions fail against the pre-fix
  recipes (checked by restoring them in place). Full suite: 3954 passed,
  1 skipped, 92 deselected (`test_merge_publish`/`test_signoff_integration`
  — the push proxy rejects pushes to master), run with `env -u PM_HOST_HOME
  PATH=/usr/bin:/bin` and `markdown` on the path, which is what makes the
  hook-installer, git-pull and markdown baselines pass here. Evidence:
  `/pm-captures/review-e7e1-i2/` (`probe.log`, the pre/post recipe copies).
- Review loop e7e1 i3 verified R16 live in this container. The `agg` install
  hazard is real: a local HTTP server that sent a `Content-Length: 100000`
  header, 500 bytes of body and then closed made real `curl -fsSL … -o agg`
  replace a working `agg` with a **500-byte** partial file (curl rc 18,
  "transfer closed with 99500 bytes remaining"), and that file is still
  executable — so it would shadow the image's working binary earlier on
  `PATH`. The guarded block does nothing when `agg` is present (stub `curl`
  not called, binary byte-identical) and still installs for real when it is
  missing: `command -v agg` empty → the same block downloaded **agg 1.9.0**
  into `~/.local/bin` and `agg --version` answered. For the Playwright link,
  a global directory that exists but holds no `playwright` made the old guard
  create `node_modules`, after which the block stopped at its own check and
  told the worker to create that same link — while the stray link would send
  a later `npm i playwright` into the global install. Post-fix no link is
  created and the `npm i playwright` advice stays valid. The Layer 2 route
  snapshots were the one request in the recipes with no bound at all (step 1's
  readiness poll bounds each attempt for exactly this reason), so they now
  carry `--connect-timeout 2 --max-time 10`; a timed-out route lands in
  `http.log` as curl's error with status 000, which is that route's evidence.
  New tests: the install block executed both ways (2 recipes ×
  present/missing), the driver block with a package-less global directory, and
  the protocol block's per-route bounds; the three behavioural ones fail
  against the pre-fix recipes (checked by restoring them in place), the
  missing-`agg` cases pass both ways by design, and the bound assertion fails
  with the timeouts removed. File 105 pass (3 runs); related suites 175 pass;
  full suite 3958 passed, 1 skipped, 94 deselected (`test_merge_publish`/
  `test_signoff_integration` — the push proxy rejects pushes to master — plus
  the two known baselines `test_git_ops::TestPullRebase::test_keeps_unpushed_merge`
  and `test_hook_events::test_installer_writes_standalone_receiver`, both of
  which reproduce on origin/master), run with `markdown` on the path so the
  render tests run too. Verified the recipes' own edited blocks live: the
  guarded `agg` block downloaded real agg 1.9.0 when agg was missing, the
  driver block still linked and ran the driver against the image's
  `/usr/lib/node_modules/playwright`, and the Layer 2 block wrote `http.log`
  and `sse.log` against a real local server with the new timeouts in place.
- Review loop e7e1 i4 verified R17 live in this container. The busy-port
  refusal was reproduced with a real local HTTP server answering the port
  (Python `http.server` on 8731) and the recipe's own start block: pre-fix it
  printed "something already answers on … — a previous run's server or
  another scenario holds the port; stop it (or pick another PORT)" while the
  cleanup on the line above had already removed `server.pid`, so the
  documented recovery (the teardown, which reads that file) could not run and
  the message did not say so; post-fix the same block exits 1 with "Its pid is
  no longer in server.pid (this step cleared it): find it with 'ss -ltnp' on
  the port and stop it, or pick another PORT". The Playwright message was
  checked by running the driver block against a global `node_modules` that
  holds no `playwright`: it now offers the link only when
  `<global>/playwright` exists and otherwise names `npm i playwright`, so the
  remedy it prints can work on a host without the image's global install.
  Both produced-files lists now name `recorder.status`,
  `recorder-stderr.log` and `recorder-pane.log`, matching what the capture
  flow writes and what the manifest's `## Files` section asks for. Tests: 3
  new/tightened assertions (the produced-files lists in both recipes, the
  busy-port refusal's remedy, the resolution message's conditional link) —
  all four cases fail against the pre-fix recipes (checked by restoring them
  in place). File 107 pass; related suites (`test_qa_artifact_web_ui_recording.py`,
  `test_qa_instructions.py`) pass. No `pm_core/` change; the dropped
  helper/prompt/verifier work stays dropped.
- Review loop e7e1 i5 verified R18 live in this container with real Playwright
  (chromium-1223 from `/opt/ms-playwright`, node 22.22.2, the recipe's own
  `driver.mjs` skeleton against a local `python3 -m http.server`). The
  skeleton run verbatim produces `recording.webm`, `trace.zip`, three
  screenshots and `dom.html` (rc 0), so the flow itself is sound. A driver
  that fails through its own `.catch` (`locator.click` timeout →
  `process.exit(1)`) leaves **no webm at all**, which is why the pre-fix flow
  surfaced it one block later as "ffmpeg failed on the driver's webm" rather
  than as a driver failure. One run in which the driver was killed
  mid-recording left Playwright's auto-named `page@8d51f406….webm` (3,341
  bytes) in the capture directory, and `ffprobe` reports `duration=0.040000` —
  a valid, playable partial recording (whether the browser finalizes the file
  is timing-dependent; I could not reproduce it on demand with a static page
  or a long idle wait). The *cleanup* gap is deterministic and is what the fix
  closes: seeding that file into a capture directory, the pre-fix step-1 `rm`
  (HEAD's `web-ui-recording.md`) leaves it, and the `*.webm` glob removes it
  (`probe-e-cleanup-gap.log`). Post-fix the driver block
  stops with "the driver failed — this run's video, trace and screenshots are
  incomplete" and removes the earlier attempt's webm/trace/`dom.html`/`*.png`
  before running the driver. Tests: 1 new execution case plus a tightened
  cleanup assertion (the `*.webm` glob and its `${CAPDIR:?}` guard); both fail
  against the pre-fix recipe (checked by restoring `HEAD`'s web-ui recipe in
  place) and pass with it. File 108 pass; related suites
  (`test_qa_artifact_web_ui_recording.py`, `test_qa_instructions.py`,
  `test_qa_loop.py`, `test_markdown_render.py`) pass.
- Review loop e7e1 i6 verified R19 live in this container with real ffmpeg
  4.4.2, using the recipe's own fenced finalize block. With `CAPDIR` set and
  no `recording.webm`, the pre-fix block exits 1 with "transcode produced no
  mp4 — ffmpeg failed on the driver's webm" (real ffmpeg on stderr:
  "…/recording.webm: No such file or directory") — an encoder diagnosis for a
  driver that recorded nothing. Post-fix the same block exits 1 with "there is
  no webm to transcode — the driver wrote no video; re-run step 2 and check the
  driver's recordVideo option", never invokes ffmpeg, and still removes the
  stale mp4 seeded in the capture directory. Tests: 1 new execution case
  (stub ffmpeg that records that it was called), which fails against the
  pre-fix recipe (checked by restoring `HEAD`'s `web-ui-recording.md` in
  place) and passes with it. File 109 pass. No `pm_core/` change; the dropped
  helper/prompt/verifier work stays dropped.
- Review loop e7e1 i7 verified R20 in this container (bash; the empty-mp4
  case uses a stub `ffmpeg` that models only the contract, so no real encode
  is needed). The web-UI finalize block, run with a stub `ffmpeg` that exits 0
  and truncates its output, exits 1 with "ffmpeg wrote nothing" and leaves a
  **0-byte** `recording.mp4` before the fix, which the manifest's `## Files`
  section could list as this run's video; post-fix the same run leaves no mp4
  and keeps the webm. The CLI `tee` fallback was
  `| tee transcript.log` — a relative path, so the capture directory gets no
  transcript while the manifest lists one; it now names
  `<capture-dir>/<short-name>/transcript.log` and the produced-files list
  names the file. The tmux driving step now says a failed `pm tui send` means
  the TUI is gone and step 5's both-gone branch would pass a capture that
  never showed the behaviour (it cannot tell a crash from the scenario
  quitting pm). The driving step also now re-derives `$TARGET`: pasted on its
  own it has no handle, and `pm tui send -s ""` auto-detects (cwd session,
  then any pm session with a TUI), so the keys could drive a different TUI
  with no error — the stub `pm` confirms the sends carry the re-derived name
  and that an unresolvable target stops the step. Tests: 5 new (the
  empty-mp4 execution case, the fallback path + produced-files entry, the
  driving-step warning, and the two driving-step handle cases); all five fail
  against the pre-fix recipes (checked by pointing the test module at `HEAD`'s
  recipes in a scratch copy — no repo file was reverted). Evidence:
  `/pm-captures/review-e7e1-i7/` (`empty-mp4-probe.log` with the pre/post
  runs, `mutation-check-pre-fix.log` with the five cases against HEAD's
  recipes). File 114 pass;
  related suites pass. No `pm_core/` change; the dropped helper/prompt/
  verifier work stays dropped.
