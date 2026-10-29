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
   the pipe before exiting (the driving step's failed send included — R25;
   a guard that could not derive `$TARGET` at all has no handle to act on
   and stops before touching it, R13/R20). The stop is best-effort
   (`2>/dev/null || true`):
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

R21. **A mistyped bound is not a bound, an unguarded directory is not a
   diagnosis, a download is a request, and a failure path must not keep the
   earlier attempt's video.** Four leftovers of the PR's own class found by
   review loop e7e1 i8:
   - **`RECORDER_STOP_TIMEOUT=2m` removed the bound instead of failing.**
     Verified in a real interactive bash on a pty: `$(( … + 2m ))` prints
     "value too great for base", leaves `deadline` empty, and the shell
     *carries on* (only a scripted run exits on an arithmetic error), so
     `[ "$(date +%s)" -ge "" ]` is always false and the stop wait never ends —
     the unbounded wait this step exists to remove, reintroduced by the knob
     the recipe tells workers to raise. Reproduced against the pre-fix recipe:
     the stop block hangs (the test's own run had to be killed at 20 s). The
     block now validates the value (`case` on non-digits) and stops with
     "RECORDER_STOP_TIMEOUT must be whole seconds (got '2m'); e.g.
     RECORDER_STOP_TIMEOUT=120", tearing the scaffold server down; the
     arithmetic uses `10#$stop_timeout` so a leading zero is not read as
     octal. Verified live with real tmux 3.2a + asciinema 2.1.0 and a live
     `rec` session: `2m` → rc 1 in 0.0 s with that message and no server left;
     `2` → the ordinary "did not exit within 2s" timeout with the pane saved;
     default → 29.5 s; a one-shot recording → rc 0, status 0, cast 142 bytes.
   - **The web-UI finalize step guarded an unset `CAPDIR` but not a missing
     one.** R15 added the `[ ! -d "$CAPDIR" ]` stop to the driver and Layer 2
     blocks; the finalize block, one step later, still ran on with a wrong
     path and reported "there is no webm to transcode — the driver wrote no
     video; re-run step 2 and check the driver's recordVideo option" (verified
     against the pre-fix block) — an encoder/driver misdiagnosis for a
     directory that is simply not there. It now stops with "capture directory
     … does not exist — create it and run step 1".
   - **The `agg` install download was the last unbounded request in the
     recipes.** R6 bounded the readiness polls per attempt and R16 bounded the
     Layer 2 route snapshots for exactly this reason, but the install line was
     `curl -fsSL … -o ~/.local/bin/agg` with no deadline: a transfer that
     accepts the connection and then stalls hangs the worker forever, and
     `-o` writes in place, so a dead transfer leaves a partial binary that
     shadows the image's working `agg` earlier on PATH (R16's hazard). The
     block now carries `--connect-timeout 5 --max-time 180`, removes the
     partial file on failure, and stops with "could not download agg — put a
     release binary on PATH and re-run the render". Verified live with real
     `curl` against a closed proxy port: rc 1, that message, and
     `~/.local/bin` left empty.
   - **The driver block's resolution-failure path kept the earlier attempt's
     outputs.** R18 made the block clear this attempt's `*.webm`/trace/DOM
     dump/screenshots before running the driver, but the `rm` sat *after* the
     Playwright resolution check, so that failure exited with the previous
     attempt's complete webm still in the capture directory — the finalize
     step (a separate paste) would then transcode it into "this run's"
     recording. The cleanup now comes immediately after the `cd`, so every
     failure path of step 2 leaves no earlier attempt's artifact.

   Also fixed in the tests: `_run_in_interactive_shell` decoded the pty
   transcript as strict UTF-8, and readline redraws can interleave a control
   sequence inside a multi-byte character (the recipe text is full of em
   dashes), which failed `test_web_ui_driver_guard_stops_an_interactive_paste`
   once in six full-file runs under a POSIX locale. The transcript is now
   decoded with `errors="replace"` — the assertions look for ASCII words and
   file effects, so a pty echo artifact must not fail the run.

R22. **A driving step has to check its own sends, and a missing encoder is not
   a bad recording.** Three leftovers of the PR's own class found by review
   loop e7e1 i9:
   - **The tmux driving step's example sends were unchecked.** The prose above
     them said "Check each send", but the lines a worker pastes were plain
     `pm tui send q -s "$TARGET"` / `… a …`. A block's exit status is its last
     command's, so a *mid-sequence* failure was invisible: verified with a stub
     `pm` whose first send exits 1 (real `pm tui send` exits 1 when no TUI pane
     is found) and whose second succeeds → the pre-fix block exits **0** with
     only the stub's stderr, reaches step 5, which sees the recorder and the
     session both gone, calls it a legitimate finish, and passes a cast that
     stops before the behaviour under test. Both example sends now carry
     `|| { echo "pm tui send failed — …"; exit 1; }`; post-fix the same run
     exits 1, names the consequence, and sends no further keys (verified: the
     send log holds one entry).
   - **The CLI scaffold's driving step had no equivalent warning.** Its
     recorded pane has no witness at all: asciinema exits 0 whenever its
     recorded command ends — driven to `exit` or dead — so a shell that died
     before the behaviour under test leaves a cast that passes the readiness,
     stop, cast and status checks. The step (prose, since the worker types its
     own sends) now says to check each `send-keys`, why step 4 cannot tell, and
     to re-run rather than accept the capture — the CLI counterpart of the
     tmux recipe's R20 warning.
   - **The web-UI finalize step never named `ffmpeg`.** It checked the webm
     (R19) and ffmpeg's exit status (R12), but not that the encoder exists,
     and the Tooling section named Playwright only. Verified with no `ffmpeg`
     on `PATH`: the shell answers "ffmpeg: command not found" (status 127) and
     the block reports "transcode produced no mp4 — ffmpeg failed on the
     driver's webm" — the worker is sent to re-drive a UI for a missing tool,
     the same misdiagnosis R12 fixed for a missing cast and R19 for a missing
     webm. The block now stops with "ffmpeg is not installed — the finalize
     step needs it; install it (e.g. 'apt-get install ffmpeg') and re-run this
     step" (the stale mp4 is already removed, the webm is kept for the retry),
     and the Tooling section names the encoder and how to install it.

   Considered and rejected: bounding `node driver.mjs` with a `timeout`.
   Playwright's own action/navigation timeouts (30 s default) bound a driver's
   waits, the driver's exit status is already the completion handle, and a
   fixed bound would kill a legitimately long walk-through — a driver knob the
   scope decision did not ask for.

R23. **A capture that fails must not leave the earlier run's video, a missing
   encoder is not a bad gif, and readiness means the server answers.** Three
   leftovers of the PR's own class found by review loop e7e1 i10, all
   reproduced in this container:
   - **The render outputs were cleared only by the render step.** Both
     recording recipes' step 0 cleared the cast, transcript and the recorder
     diagnostics, and the render block cleared `recording.mp4`/`recording.gif`
     before rendering — but a capture that *fails* exits before the render
     block ever runs, so the earlier run's video stayed in the capture
     directory. Verified with the recipes' own blocks against a stub
     `tmux`/`pm` and an earlier `recording.mp4`/`recording.gif` seeded: the
     failed run exits 1 and leaves both files, with no cast at all — the
     manifest's `## Files` section and the sign-off report would present the
     previous run's video as this run's recording (the stale-cast bug, one
     step earlier; the web-UI recipe already cleared its mp4 in step 1 for
     exactly this reason). Step 0 now removes both in the tmux recipe and in
     the CLI preamble and scaffold, and the CLI scaffold also clears the
     `tee` fallback's `transcript.log` — a cast-path run writes no transcript,
     so an earlier fallback run's log would otherwise be read as this run's
     (the tmux recipe already cleared its appended transcript). The gif's
     real name is `recording.cast.gif` (the render block's `$cast.gif`), not
     the `recording.gif` written here; R28 corrects it.
   - **A missing `ffmpeg` was reported as a bad gif.** R22 gave the web-UI
     finalize step a `command -v ffmpeg` guard, but the two recording recipes
     — the primary artifacts of this PR — still ran `agg` and then the
     encoder. Verified with the recipes' own render blocks on a `PATH` that
     holds no `ffmpeg`: the shell answers "ffmpeg: command not found" (127)
     and the block reports "render produced no mp4 — ffmpeg failed on the
     gif", sending the worker to inspect the cast and `agg` for a tool that is
     simply not installed (this container has no `ffmpeg`, so the case is not
     hypothetical). Both blocks now stop before the `agg` render with
     "ffmpeg is not installed — the render step needs it; install it (e.g.
     'apt-get install ffmpeg') and re-run this step", and the render section's
     prerequisite prose names the check. `ffprobe`'s absence needs no guard:
     it only tunes the upscale and the encode still runs.
   - **The web-UI readiness poll required a 2xx at `/`.** The port pre-check
     deliberately uses `curl` *without* `-f` ("any HTTP answer, including a
     404, means the port is taken"), but the readiness poll one block later
     used `-sf`. Verified against a local server that answers 404 at `/`: the
     pre-check treats it as answering (rc 0) while `curl -sf` exits 22, so
     the poll ran out its 120 s deadline, reported "app did not answer on …"
     for a server that was answering, and killed the app it had just started.
     Readiness now uses plain `curl` — the same definition as the pre-check —
     and the comment says why.

R24. **Two runs on one tmux server must not read each other's evidence.**
   The tmux recipe's `pipe-pane` is per-pane and a later `pipe-pane` on the
   same pane *replaces* it (that is why step 2 omits `-o`), so two runs
   recording one pm session into different capture directories silently steal
   each other's transcript: the second run's pipe takes over, the first run's
   `transcript.log` stops growing, and its stop step still exits 0 on the
   bytes written before the takeover. The mirror collision is two runs
   pointed at one capture directory: the second run's step 0 removes the
   first run's cast and transcript and its recorder writes over them, so the
   first run's stop block detaches the *second* run's recorder and reads its
   status and cast as its own — a false pass. Verified live (QA S24, two
   projects on one server): pre-fix, the first run's transcript delta during
   its final driving step was 0 while the help screen landed in the other
   run's log, and the shared-directory run exited 0 on the other run's
   evidence. Step 2 now claims the capture directory in a tmux session option
   (`@pm_capture_dir`) *before* attaching the pipe and refuses a session that
   already records into a different directory, or a directory another live pm
   session already records into; step 5 releases the claim when the run ends.
   The claim is written before the pipe, not after: the read and the write are
   separate tmux calls, so claiming afterwards left a window in which a second
   run passed the same read, attached its own pipe (the takeover the claim is
   for), and only then wrote its claim over the first run's. A pipe that
   cannot be attached releases the claim again (nothing is recording, so the
   claim this step just took would be pure residue); step 5 stops the pipe
   before releasing the claim so its own cleanup cannot stop a later run's
   pipe. (The read/write pair is still not atomic — tmux has no
   compare-and-set — so two runs that read at the same instant can both pass;
   the window no longer covers the pipe attachment, which is what made the
   collision silent.) The claim lives on the session so it survives the
   separate pastes, and the refusal names the manual clear for a claim an
   abandoned run left behind.
   Step 2 also re-derives `$TARGET` (refusing an empty one) like steps 4 and
   5, because `tmux -t ''` resolves to whatever session tmux considers
   current — the claim would otherwise be read from, and the pipe attached
   to, another run's session. A raw `tmux pipe-pane` that does not go through
   step 2 still bypasses the claim; that is recorded as a limitation, not a
   pass, in the scenario's `shared-pipe-raw-bypass` capture.

R25. **A failed run must not leave its capture-directory claim behind, and a
   refusal must name a clear that works.** Two leftovers of the PR's own
   class found by review loop 9265 i2, both in `tmux-screen-recording.md`:
   - **Every failure path after the claim was taken left it set.** Step 2
     takes the claim; only the pipe-attach failure released it again, and
     step 5 released it at the end of a successful run. The other eleven
     failure paths (step 3's failed `new-session`, its readiness
     "exited before it drew", its readiness timeout and its settle check;
     step 4's failed send; step 5's recorder-gone-while-the-session-lives,
     failed detach, stop timeout, missing cast, missing status, non-zero
     status and empty transcript) tore the recorder down and stopped the
     pipe but exited with the claim still on the pm session — which normally
     survives the failed capture. The next attempt in that session, into
     another capture directory, is then refused with "… is already being
     recorded into …" for a capture that ended; the recipe's own rule for
     the pipe-attach failure ("nothing is recording, so the claim this step
     just took would be pure residue") applies to all of them. Verified live
     (real tmux 3.4, private default-config server): before the fix a
     readiness failure left `@pm_capture_dir` set on the pm session; after
     it the option is gone. Step 4's failed send was also the one that left
     the *recorder and the pipe* running: `pm tui send` looks the pane up in
     the pane registry, not in tmux, so a stale registry entry fails the send
     while the session, its pipe and the attach client live on. That path now
     saves the recorder pane (and names it in the message, as R11 requires),
     kills the recorder session, stops the pipe and releases the claim. The
     save and teardown are best-effort, so a send that failed because the
     session was already gone still ends with the message and no pane file.
     Verified live with a stub `pm` whose `tui send` fails: the pre-fix block
     exited 1 leaving the recorder session, the pipe and the claim in place;
     post-fix the pane is saved (the TUI's last screen), `#{pane_pipe}` is 0,
     the recorder session is gone and the claim is unset.
   - **The cross-session refusal offered a remedy that cannot work.** A run
     killed outright (SIGKILL) leaves its claim behind — no failure path
     runs — and a *different* pm session recording the same directory is
     then refused with "… is already being recorded by pm session X — end
     that capture, or use another capture directory". Ending a capture that
     already ended is impossible, and the same-session refusal next to it
     already names the manual clear. The message now says "if that run is
     gone, clear its claim with 'tmux set-option -u -t X
     @pm_capture_dir'". Verified live: the refusal names the other session's
     clear, and this run takes no claim of its own (the check runs before
     the claim is written).

R26. **The detach key is the prefix the server actually uses, and the
   recorder session name is shared by every run on one server.** Two leftovers
   in `tmux-screen-recording.md` found by review loop 9265 i3:
   - **Step 5 sent a hard-coded `C-b d`.** `~/.tmux.conf` may set another
     prefix (the dev container this recipe is exercised in sets `C-\`), and
     the attach client then treats `C-b d` as ordinary input to the recorded
     TUI. Verified live (real tmux 3.4 on a private server whose config sets
     `set -g prefix C-\`, real asciinema 2.4.0, the recipe's own step-3
     recorder command): the recorder stayed up, the pane showed `^Bd`, and the
     stop wait ran out its 30 s bound with "recorder did not exit within 30s —
     the pane is saved in …", naming neither the prefix nor the keys — and the
     cast holds those 30 s of wrong content. Step 5 now asks the server for
     its prefix (`detach_key=$(tmux show-options -gv prefix)`, falling back to
     `C-b` only when the server is gone, so the send fails as before) and
     names the key it sent in the stop-timeout message. Verified live with the
     same recipe block on the same server: pre-fix rc 1 after the full bound,
     no status file, a 4.6 KB cast of the wrong 30 s; post-fix rc 0,
     `recorder.status` 0, a 4.3 KB cast, the claim released. A text test
     asserts the block asks for the prefix, and an execution case runs the
     stop block alone against a server reporting `C-a` (the stub ends the
     recording only for the prefix the server reports), which fails against
     the pre-fix block with the stop timeout.
   - **The `pm-recorder` session name is shared by every run on one tmux
     server.** Step 0 kills any `pm-recorder` session, which on a server with
     a concurrent capture is the *other* run's recorder; that run then fails
     (its recorder vanished mid-scenario, so step 5 fails it instead of
     passing a truncated cast), and its own step 5 detaches whatever
     `pm-recorder` is up by then — the second run's recorder. Both runs fail
     loudly rather than reading each other's evidence, so this is recorded as
     a limitation rather than fixed with a per-run session name: the step-0
     prose now says two captures must run in sequence on one server, or each
     on its own server (a private `TMUX_TMPDIR`). Considered and rejected:
     deriving the session name from the capture directory — it would have to
     be re-derived in steps 0, 3, 4 and 5 (each its own paste) and the
     execution harness keys its session model by that name, while the
     collision is already loud, which is what this PR's class requires.

R27. **A port check that cannot tell a free port from a taken one, a
   promised artifact written where nothing looks, and a stop failure that
   destroys the recording its remedy retries.** Three leftovers of the PR's
   own class found by review loop 9265 i4:
   - **The web-UI port pre-check treated every curl failure as "free".** Only
     "connection refused" (curl exit 7) means the port is free. A listener
     that accepts the connection and never answers times curl out (28), and
     a previous run's hung server would satisfy the readiness poll as soon as
     it answered — so this run's app cannot bind, and the failure surfaces at
     the poll's deadline as "app did not answer on … — check its startup
     output", which names neither the cause nor the process holding the port,
     after the full deadline (120 s; the probe shortened it to 2 s, as the
     tests do). Verified live in this container with a socket that
     accepts and never replies (the app's own "Address already in use" was
     lost; the block reported "app did not answer … within 120s", killed the
     app it had started, and left no `server.pid`). A usage or resolution
     error (1, 6, 127 — a wrong `APP_URL`, or no `curl` at all) landed in the
     same misdiagnosis. The pre-check now stops on any status other than 7,
     naming curl's own exit and the `ss -ltnp` hunt. Verified post-fix: the
     same listener is refused in 5 s (the pre-check's own `--max-time`) with
     "could not check … with curl (exit 28; only 'connection refused', 7,
     means the port is free) …", and the app is never started.
   - **A relative `<capture-dir>` writes the capture where the checks do not
     look.** tmux runs `pipe-pane`'s command in the *pm session's* directory,
     not in the shell that pasted the step — verified live: a pipe attached
     from /tmp/b with `cat >> rel.log` wrote /tmp/a/rel.log, the session's
     directory — while step 5's `test -s <capture-dir>/transcript.log` runs
     in *its* shell's directory. A relative path therefore leaves the
     transcript elsewhere and step 5 reports "transcript.log is empty — the
     pipe-pane stream never wrote to it" for a transcript that was written;
     the recorder's cast and the CLI scaffold's pane command resolve against
     whichever shell pasted them, and step 4/5 are usually fresh pastes.
     Verified live in the tmux recipe: with `<capture-dir>` = `relcap`, the
     stop step pasted from another directory answered "asciinema wrote no
     cast" while the cast sat in the worker's directory. Step 0 of both
     recording recipes (and the CLI preamble and scaffold, which are separate
     pastes) now refuses a relative `<capture-dir>` — an absolute path or one
     starting with `~/` is accepted, since both resolve the same in every
     paste and in tmux's own shell — with a message saying why, before
     anything is created. Verified live: both blocks exit 1 with
     that message and create no directory; the nominal absolute-path flows are
     unchanged (tmux rc 0, status 0, claim released).
   - **The CLI stop step's two failures killed the recording its remedy
     retries.** The step's own comment says the bound "is a hang detector,
     not a time limit on the recorded work, and killing a healthy recording
     loses the evidence", and both failure messages tell the worker to re-run
     with a larger `RECORDER_STOP_TIMEOUT` — yet both branches ran
     `tmux -L scaffold kill-server` on the way out. Verified live: a one-shot
     `sleep 6` recorded, the stop block with `RECORDER_STOP_TIMEOUT=1` timed
     out and killed the server, and the documented re-run with 60 answered
     "recorder status is missing — the pane was torn down before asciinema
     exited" — the recording was gone, so the remedy could not work (the
     mistyped `2m` branch had the same shape, and it fails before anything is
     waited on). Both branches now leave the recorder running and say so: the
     timeout message says the recording is still running, to re-run with a
     larger bound or send `exit` (step 3), and names
     `tmux -L scaffold kill-server` for a genuinely stuck recording (which
     must then be re-recorded); the mistyped-value message says the recording
     is still running and to re-run with a whole number of seconds. Verified
     live post-fix: the timeout leaves the session alive and the re-run with
     60 exits 0 with `recorder.status` 0, and the pane is still saved on the
     timeout. The readiness timeout, the cast and status checks keep their
     teardown: nothing there is waiting on a retry.

   Also recorded, not fixed (the tmux recipe's `pm-recorder` note, R26, one
   file over): the CLI scaffold's `-L scaffold` socket *name* is shared by
   every run on the host, so two CLI captures must not run at once — the
   later run's `kill-session -t rec` ends the earlier run's recorder, and
   either run's failure path (`kill-server`) kills the other's server. Both
   runs fail loudly rather than reading each other's evidence, so the step-1
   prose now says to run captures in sequence.

R28. **The stale-video cleanup named a file the render never writes.** One
   leftover in the kept recipe scope found by review loop 9265 i5, in both
   recording recipes and in the tests that were supposed to guard them.
   R23's step-0 cleanup removed `recording.mp4` and `recording.gif`, but the
   render block holds the cast in `cast=<capture-dir>/recording.cast` and
   renders the intermediate to `"$cast.gif"` — i.e. **`recording.cast.gif`**,
   the name its own cleanup (`rm -f "${cast%.cast}.mp4" "$cast.gif"`) and its
   final `rm -f "$cast.gif"` use. Verified live with the recipes' own blocks:
   step 0 run against a seeded `recording.cast.gif` and `recording.gif`
   removes only the latter, and the render block hands `agg` the output path
   `…/recording.cast.gif` (a stub `agg` logging its last argument, and a real
   agg 1.9.0 render of a real cast, agree). So a capture that fails before
   the render step — exactly the R23 case, where the render block's own
   cleanup never runs — left the earlier run's *real* intermediate in the
   capture directory, while the cleanup removed a name nothing writes. The
   two tests could not see it for the same reason: they seeded
   `recording.gif`, asserted it was gone, and passed against a recipe that
   left the real file behind. Step 0 of both recipes now clears
   `recording.cast.gif`, and both tests *derive* the name from the render
   block (`cast=` plus `"$cast.gif"`) rather than spelling it out, so the
   cleanup, the render and the tests cannot drift apart again; the recipes'
   prose and the qa.md requirements name the real file. Verified live in this
   container with the recipes' own step-0 and render blocks; both tests fail
   against the pre-fix recipes (checked by restoring them in place, then
   restoring the post-fix copies) and pass with them. No `pm_core/` change;
   the dropped helper/prompt/verifier work stays dropped.

R29. **The capture-directory claim was compared as text, not as a directory.**
   One leftover in the kept tmux-recipe scope found by review loop 7c9c i1,
   in the R24 claim itself. Step 0 accepts `<capture-dir>` as an absolute path
   *or* one starting with `~/`, and a quoted `~` is never expanded, so
   `tmux set-option … @pm_capture_dir "<capture-dir>"` stored the literal
   `~/cap`. The claim was then compared with `[ "$claimed" != "<capture-dir>" ]`
   (and, across sessions, `[ "$v" = "<capture-dir>" ]`), i.e. one directory
   under two spellings was two different claims. Verified live on tmux 3.2a
   with the recipe's own step-2 block on a private server: with `~/capA`
   claimed on one session, a second session pasting step 2 with
   `/home/<user>/capA` — the same directory — **ran on (rc 0)** and claimed it
   too, so both runs wrote that directory's cast and transcript and each stop
   step read the other's evidence (the R24/S24 collision the claim exists to
   stop); the mirror case, a retry in the *same* session with the other
   spelling, was refused as "already being recorded into ~/capA", a collision
   that does not exist. Step 2 now compares canonically: `claim_dir` is
   `cd <capture-dir> && pwd -P` (which also collapses a trailing slash and a
   symlinked path), a stored claim is normalized the same way (its `~/` prefix
   expanded first, since a quoted `~` does not expand there either), and the
   canonical path is what the cross-session scan matches and what step 2
   writes. A directory that cannot be entered keeps the text as typed —
   nothing is recording into it then. Verified post-fix on the same server:
   `~/capA` is stored as `/home/<user>/capA`, the other session is refused,
   and the same-session retry proceeds. Tests: two cases (a shared directory
   reached through a `~/` spelling must be refused; a retry must not be
   refused by its own `~/` claim), both failing against `HEAD`'s step 2
   (checked by restoring the pre-fix recipe in place, then restoring the
   post-fix copy). Evidence: `$(pm qa captures-path pr-b19db15)/review-7c9c-i1/`
   (`probe-prefix.log`, `probe-postfix.log`, the pre/post step-2 blocks and
   the `tmux`/`pm` stubs). Also added, as coverage rather than a fix: the two
   step-5 branches no execution mode reached with the pm session still alive
   — `detachnocast` (the detach ends the recorder, the pm session survives,
   no cast) and `detachnostatus` (same, no status file) — must release the
   claim like the other nine, which is what R25 requires of every path; both
   fail when the release is removed from their branch. No `pm_core/` change;
   the dropped helper/prompt/verifier work stays dropped.

R30. **A session with no claim is not a claim on the worker's directory.**
   One leftover in the kept tmux-recipe scope found by review loop 7c9c i2,
   in the R24/R29 cross-session scan. `tmux show-options -v` answers *nothing*
   for a session that holds no `@pm_capture_dir` (tmux 3.2a: exit 0, empty
   output), and the scan normalized that empty answer with
   `vd=$(cd "$v" 2>/dev/null && pwd -P)` — but `cd ""` **succeeds and stays in
   the current directory**, so `vd` became the *pasting shell's* cwd. Step 2
   pasted from inside the capture directory therefore matched every other
   session on the server and refused the run with "<capture-dir> is already
   being recorded by pm session <other>", naming a session that was not
   recording anything, and taking no claim of its own (the check runs before
   the claim). Verified live on tmux 3.2a with the recipe's own step-2 block
   on a private server: with `pm-other` holding no claim, the pre-fix block run
   from the capture directory exited 1 naming `pm-other`; the same run post-fix
   exits 0, claims the directory and attaches the pipe. The mirror case is
   handled the same way: the same-session check already skipped an empty
   claim (`[ -n "$claimed" ]`), but its `claimed_dir` was computed the same
   way, so the normalization now runs only when there is a claim to normalize.
   A real collision is unchanged: with `pm-other` holding the claim on that
   directory, post-fix step 2 still refuses it and takes no claim. Tests: one
   execution case runs the step-2 block from the capture directory with a
   second session that holds no claim, which must proceed and claim the
   directory — it fails against `HEAD`'s step 2 (checked by restoring the
   pre-fix recipe in place, then restoring the post-fix copy). Evidence:
   `$(pm qa captures-path pr-b19db15)/review-7c9c-i2/` (`probe.log` with the
   pre/post runs and the real collision, `scripts/` with the pre/post step-2
   and full capture blocks and the stub `pm`). No `pm_core/` change; the
   dropped helper/prompt/verifier work stays dropped.

R31. **A remedy that runs but cannot work is not a remedy, and an empty
   answer must not become a path at the filesystem root.** Two leftovers in
   the kept recipe scope found by review loop 7c9c i3, both the PR's own
   class, both reproduced in this container:
   - **The `agg` install reported success while `agg` still did not
     resolve.** The install block downloads the release binary into
     `~/.local/bin/agg` and exits 0. `~/.local/bin` is on `PATH` in the QA
     image (R14 relies on that to make the remedy work at all), but on a host
     where it is not, the block exits 0 with a binary nothing can run: the
     render then fails with "agg failed on the cast — is 'agg' installed?",
     the worker pastes the install block again, it downloads again and exits
     0 — a remedy that cannot work, in a loop, and the failure never names
     the real cause. Verified in this container with a PATH that excludes
     `~/.local/bin` and a stub `curl` that writes the file: the pre-fix block
     exits **0**, `~/.local/bin/agg` exists and is executable, and
     `command -v agg` still fails; the render block then reports "agg failed
     on the cast — is 'agg' installed?" and exits 1. Both recording recipes'
     install blocks now check that `agg` resolves after the install and stop
     with "installed ~/.local/bin/agg but 'agg' still does not resolve —
     ~/.local/bin is not on PATH; add it (export
     PATH="$HOME/.local/bin:$PATH") and re-run the render", and the render
     prose says so.
   - **The web-UI start block turned an unresolvable captures path into
     `/scenarios/1/web-ui`.** `CAPDIR="$(pm qa captures-path "$PR_ID")/
     scenarios/1/web-ui"` with an empty answer is `/scenarios/1/web-ui` — the
     *filesystem root* — because the command prints nothing on stdout when it
     fails (its error goes to stderr, e.g. "PR 'pr-xxxxxxx' not found." for an
     unsubstituted placeholder, or "No project.yaml found" when the step is
     pasted outside the project) and exits non-zero. The block's own
     `mkdir -p "$CAPDIR"` then creates it when the worker is root (QA
     container workers are), the whole capture lands outside the per-PR
     captures directory while every later check passes on those files, and
     the manifest points at a directory the report never reads — the same
     "a promised artifact written where nothing looks" class as the relative
     `<capture-dir>` the recording recipes refuse (R27). Verified: real `pm`
     in this container answers an unsubstituted id with that stderr line,
     exit 1 and empty stdout, and the pre-fix block ran
     `mkdir -p /scenarios/1/web-ui` (as this container's non-root user that
     failed and was reported as "could not create … — check the path and its
     permissions", a misdiagnosis of a path that was never resolved). Step 1
     now resolves the captures root with a checked substitution
     (`cap_root=$(pm qa captures-path "$PR_ID") || cap_root=`) and stops with
     "could not resolve the captures directory for $PR_ID — run 'pm qa
     captures-path $PR_ID' in the project to see why …" before computing
     `CAPDIR` or creating anything. Verified post-fix: both the failing and
     the empty-answer cases exit 1 with that message and attempt no
     directory; the nominal run (a stub `pm` printing a captures root) still
     exits 0 and creates `<root>/scenarios/1/web-ui/server.pid`.
   Tests: four new cases — both recording recipes' install block run with
   `~/.local/bin` off `PATH` must exit non-zero with the message and leave
   the download in place, and the web-UI start block run with a failing `pm`
   and with a silent one must stop before `mkdir` (a logging `mkdir` stub
   asserts nothing was attempted) and never start the app. All four fail
   against `HEAD`'s recipes (checked by restoring them in place, then
   restoring the post-fix copies). Evidence:
   `$(pm qa captures-path pr-b19db15)/review-7c9c-i3/` (`probe.log` with the
   pre/post runs of both cases and the real `pm` failure shapes, `scripts/`
   with the extractor, the pre/post blocks and the probe driver). No
   `pm_core/` change; the dropped helper/prompt/verifier work stays dropped.

R32. **A missing input is not a failed job, and a remedy must not be
   impossible because of state the step left in place.** Two leftovers in the
   kept recipe scope found by review loop 7c9c i4, both in the web-UI driver
   block (step 2), both reproduced in this container with real `node` 22:
   - **A driver that was never saved is reported as a driver that ran and
     failed.** The prose says to save the skeleton as `driver.mjs` in the
     capture directory, and the block ends on
     `CAPDIR=… APP_URL=… node driver.mjs || { echo "the driver failed — this
     run's video, trace and screenshots are incomplete; do not finalize this
     attempt"; exit 1; }`. With no `driver.mjs` (never saved, or saved in the
     workdir instead of the capture directory) Node exits 1 with
     `Error: Cannot find module '<capture-dir>/driver.mjs'` and the block
     reports it as a failed driver run, sending the worker to debug a file
     that does not exist — the same misdiagnosis R19 fixed for a missing webm
     ("there is no webm to transcode", not an ffmpeg failure) and R23 for a
     missing encoder, one step earlier. The block now checks `[ -f driver.mjs
     ]` after its attempt cleanup (so an earlier attempt's outputs still go,
     per R21) and before the Playwright link/resolution work, and stops with
     "there is no driver.mjs in $CAPDIR — save the recipe's driver skeleton as
     driver.mjs here (step 2's prose) before running this block". Verified
     live: the pre-fix block exits 1 with "the driver failed …" on an empty
     capture directory (the Node stack trace names the file, but the block's
     own message contradicts it); post-fix the same run exits 1 with the
     message above and runs no driver.
   - **The Playwright resolution failure offered a link that nests inside an
     existing `node_modules`.** The link is guarded on `[ ! -e node_modules ]`
     so a worker's local install is not clobbered (R9/R16), which means a
     *partial* `npm i playwright` — a `node_modules` that does not hold the
     package — is left alone and the resolution check fails. The failure then
     said "if /usr/lib/node_modules/playwright exists, link it ('ln -sfn
     /usr/lib/node_modules node_modules'); otherwise run 'npm i playwright'
     here" (R17 made that conditional on the package being there). Pasting
     that `ln` with the directory in place creates
     `node_modules/node_modules` — verified: the block exits 1 with
     ERR_MODULE_NOT_FOUND, the empty `node_modules` is untouched, and the
     prescribed `ln -sfn <global> node_modules` answers `node_modules/global`
     and still fails the same import — a remedy that cannot work, repeated in
     a loop (the shape R31 fixed for the `agg` install). The message now says
     to remove the `node_modules` that does not hold it first: "if
     /usr/lib/node_modules/playwright exists, remove a node_modules here that
     does not hold it and link the global install ('rm -rf node_modules;
     ln -sfn /usr/lib/node_modules node_modules'); otherwise run 'npm i
     playwright' here". Verified live: after `rm -rf node_modules` and the
     link, the same block resolves Playwright and runs the driver (rc 0,
     "driver saw object").
   Tests: two new cases, both failing against `HEAD`'s driver block (checked
   by restoring the pre-fix recipe in place, then restoring the post-fix
   copy) — the block run with no `driver.mjs` must stop with the message that
   names it and must not report "the driver failed", and the block run with an
   empty `node_modules` and a fake global Playwright must name the removal
   (`rm -rf node_modules`) and, after applying it, resolve the package and run
   the driver. Evidence:
   `$(pm qa captures-path pr-b19db15)/review-7c9c-i4/` (`probe.log` with the
   pre/post runs of both cases). No `pm_core/` change; the dropped
   helper/prompt/verifier work stays dropped.

## Non-goals
- **No product polling loop.** There is no checked-in `pgrep` loop to fix.
- **No new helper, prompt block, verifier text, or QA-loop change.** Those
  were the dropped scope above.
- **No new `claude -p` usage** (session rule).

## Files

| File | Change |
|---|---|
| `pm/qa/artifacts/tmux-screen-recording.md` | capture-dir mkdir (checked), stale cast + transcript + recorder status removal, recorder readiness, bounded stop + cast check, recorder-status handle so a recorder killed while the target session also ended is not a success, bounded pm-session poll on `has-session -t "$TARGET"`, failed `pipe-pane` reported + `transcript.log` checked, stale render outputs cleared + renderer exit statuses checked + mp4 checked, `agg` prerequisite + install line, asciinema's own stderr + the pane's last screen saved on failure (R11), step 5 re-derives `$TARGET` and saves the pane inline because it is pasted on its own (R13); the pm-session readiness failure says its output was discarded instead of pointing at it, the `agg` install creates `~/.local/bin` first (R14), a failed `new-session` is reported as a start failure (R15), the `agg` install is guarded on `command -v agg` so it cannot replace a working binary (R16), the produced-files list names the flow's diagnostics (R17), and the driving step says a failed `pm tui send` means the scenario never ran, so the capture must not be accepted, and re-derives `$TARGET` (refusing an empty one) so its sends cannot auto-detect a different TUI (R20); the `agg` install download carries `--connect-timeout`/`--max-time` and removes a partial binary on failure (R21), and the driving step's example sends are checked in the block, not only in the prose above them (R22); step 0 also clears the earlier run's `recording.mp4`/`recording.gif`, because a capture that fails exits before the render step's own cleanup, and the render block names a missing `ffmpeg` instead of reporting it as a bad gif (R23); step 2 claims the capture directory in a session option *before* attaching the pipe and refuses a session recording a different directory, or a directory another live session is recording, releasing the claim if the pipe cannot be attached and in step 5 (after the pipe is stopped, so the cleanup cannot close a later run's pipe), and re-derives `$TARGET` like steps 4 and 5 (R24); every failure path after the claim is taken releases it again — including the driving step's failed send, which saves the recorder pane, kills the recorder, stops the pipe and releases the claim, because a stale pane-registry entry fails the send while the session, its pipe and the recorder live on — and the cross-session refusal names the clear command for the other session (R25); step 5 detaches with the prefix the server reports (`tmux show-options -gv prefix`) instead of a literal `C-b`, names that key in the stop-timeout message, and the step-0 prose records that the `pm-recorder` name is shared by every run on one server, so captures run in sequence or on separate servers (R26); step 0 refuses a relative `<capture-dir>` — tmux runs the transcript pipe in the pm session's directory, so a relative path writes the transcript where step 5 never looks — and the produced-files list also names `recorder-pane.log` for a failed driving send (R27); step 0 clears the real intermediate, `recording.cast.gif` (the render block's `$cast.gif`), not the `recording.gif` nothing writes (R28); step 2 compares the capture-directory claim as a canonical directory (`cd` + `pwd -P`, with a stored claim's `~/` prefix expanded) instead of as the text typed, so one directory spelled two ways is one claim — the cross-session collision and the same-session false refusal it caused (R29); step 2's claim scan skips a session that holds no claim instead of normalizing the empty answer (`cd ""` stays in the worker's cwd, which made every other session look like it recorded into the directory step 2 was pasted from) — R30; the `agg` install now verifies that the binary it wrote resolves on PATH and stops with the `~/.local/bin` fix instead of exiting 0, so the render's "is 'agg' installed?" cannot send the worker back to a remedy that already ran (R31) |
| `pm/qa/artifacts/cli-recording.md` | same capture fixes; no-TTY scaffold rewritten (cast path, readiness, `exit` stop, bounded wait + cast check, escaped command form, recorder-status handle so a killed recorder is not a success); stale render outputs cleared + renderer exit statuses checked + mp4 checked + no-cast failure named; `agg` prerequisite + install line; stop failure names the interactive remedy; `'\''` escape documented; `tee` fallback reconciled with the hard-failing render; asciinema's own stderr + the pane's last screen saved on failure (R11), saved inline in step 4 for the same paste-alone reason (R13); the `agg` install creates `~/.local/bin` first (R14); the capture-dir `mkdir` and the recorder `new-session` are checked (R15); the `agg` install is guarded on `command -v agg` (R16); the produced-files list names the flow's diagnostics (R17); the `tee` fallback writes its transcript into the capture directory, with the produced-files list naming it (R20); and `RECORDER_STOP_TIMEOUT` is validated as whole seconds before the arithmetic (a non-numeric value left the deadline empty and the stop wait unbounded in an interactive shell), with the deadline read as `10#`, the `agg` install download bounded and cleaned up on failure (R21), and the driving step warning that a failed `send-keys` means the recorded shell died before the behaviour under test, which step 4 cannot see (R22); the preamble and scaffold also clear the earlier run's `recording.mp4`/`recording.gif` and the `tee` fallback's `transcript.log`, and the render block names a missing `ffmpeg` (R23); the preamble and scaffold refuse a relative `<capture-dir>` (the pane command and step 4 resolve it against their own pastes), and the stop step's two failures — the timeout and a mistyped bound — leave the recorder running for the re-run they prescribe instead of killing it, so the documented remedy works, and the step-1 prose records that the `scaffold` socket name is shared by every run on the host, so captures run in sequence (R27); the preamble and scaffold clear the real intermediate, `recording.cast.gif` (the render block's `$cast.gif`), not the `recording.gif` nothing writes (R28); the `agg` install verifies that the binary it wrote resolves on PATH and stops with the `~/.local/bin` fix instead of exiting 0 (R31) |
| `pm/qa/artifacts/web-ui-recording.md` | port pre-check (refuses a server already answering) then bounded `until curl` with per-attempt timeout and server cleanup; stale webm/mp4/trace/screenshots/DOM dump/protocol logs cleared before the driver + mp4 checked on ffmpeg's exit status (the webm glob is `*.webm`, so Playwright's auto-named video from a killed driver goes too — R18); finalize/driver/teardown guards stop the block (`if … exit 1`, because `${VAR:?}` only stops a scripted run); driver resolves the image's global Playwright through a conditional local `node_modules` (ESM ignores `NODE_PATH`) and stops if it does not; the driver block clears this attempt's own outputs and checks `node driver.mjs`'s exit status, so a failed driver is named where it fails instead of being misdiagnosed as an ffmpeg error and a retry cannot be finalized from an earlier attempt's webm (R18); the driver guard covers `APP_URL` too, because the driver falls back to `localhost:8000` (R13); step 1 records the app's pid in `server.pid` (cleared first, removed by the teardown) so the teardown works from a fresh shell, and the Layer 2 protocol block stops on an unset `CAPDIR`/`APP_URL` instead of redirecting to `/http.log` and `/sse.log` and exiting 0 (R14); the start block checks its `mkdir` and drops the dead pid on a failed start, and the driver block refuses a capture directory it cannot enter (R15); the Playwright link is conditional on `/usr/lib/node_modules/playwright` so a global directory without the package is not linked, and the Layer 2 route snapshots carry per-request `--connect-timeout`/`--max-time` bounds (R16); the busy-port refusal names the manual pid hunt instead of a teardown whose `server.pid` this step just cleared, and the Playwright resolution failure only offers the link when the package is there (R17); the finalize step checks that there is a `recording.webm` to transcode before running ffmpeg, so a driver that wrote no video is named instead of surfacing as an encoder failure (R19), and its "ffmpeg wrote nothing" branch removes the empty mp4 it would otherwise leave behind (R20); the finalize step also refuses a set-but-missing capture directory instead of reporting "the driver wrote no video" (R21), and the driver block clears this attempt's outputs — including the earlier attempt's `recording.mp4`, which a failed retry would otherwise leave as the manifest's only video — *before* its Playwright resolution check, so that failure path cannot leave an earlier attempt's artifact for the finalize step (R21); the finalize step stops on a missing `ffmpeg` instead of reporting it as a failed transcode of the driver's webm, and the Tooling section names the encoder and how to install it (R22); the readiness poll uses plain `curl` (no `-f`), so an app that answers 404 at `/` counts as up instead of being reported as not answering after the full deadline and killed (R23); the port pre-check stops on any curl status other than 7, so a listener that accepts and never answers (28), a wrong URL (6) or a missing curl (127) is named instead of surfacing as "app did not answer" after the deadline and killing the app (R27); the produced-files list and the manifest's `## Files` example also name the `node_modules` link step 2 creates beside the driver, so the manifest matches the capture directory (R17's rule, one file over); step 1 resolves the captures root through a checked `pm qa captures-path` and refuses a failed or empty answer, which otherwise became `/scenarios/1/web-ui` at the filesystem root (R31); the driver block refuses a missing `driver.mjs` instead of reporting it as a driver that ran and failed, and its Playwright resolution failure says to remove a `node_modules` that does not hold the package before linking, because a bare link nests inside it (R32) |
| `tests/test_qa_artifact_recording_recipes.py` | **new** regression tests for the kept recipe fixes, including R21's four cases (the non-numeric stop bound — which hangs against the pre-fix recipe; the bounded `agg` download with a partial-file cleanup; the finalize step's missing-directory guard; the resolution-failure cleanup), a lenient pty decode so a readline redraw cannot fail the interactive-paste cases, R22's three cases (a mid-sequence failed send, the CLI driving warning, the missing encoder), and R23's cases (a failed capture clearing the earlier run's mp4/gif in both recipes and the CLI's transcript, the render block naming a missing `ffmpeg` on a `PATH` without one — and not running `agg` first — and the web-UI readiness poll accepting an app that answers 404 at `/`, driven through a stub `curl` that models `-f` as exit 22), and R24's five cases (step 2 writes the claim; the claim exists at the moment `pipe-pane` runs, so it is taken before the pipe it guards; a second capture directory on one session is refused; a directory another live session records into is refused; a finished run releases its claim) plus the empty-`$TARGET` refusal, with the stub `tmux` modelling `show-options`/`set-option`/`list-sessions` and recording the claim state seen by `pipe-pane`; and R25's cases (each of the nine failing modes releases the claim — `midbothbad` passes both ways by design, because a session's death takes its options with it, which the stub now models; a failed driving send leaves no recorder session, no claim and a saved pane; the cross-session refusal names the clear for the other session), and the web-UI driver block's failure case seeds the earlier attempt's `recording.mp4` and requires the attempt cleanup to remove it; R26's case runs the tmux stop block alone against a stub server whose prefix is `C-a`, which must still end the recording (the stub ends it only for the prefix the server reports) and must ask the server for it — against the pre-fix block the same run times out with the recorder up; R27's cases: the web-UI start block with a stub `curl` that times out on the pre-check (exit 28) must refuse before launching the app; each recording recipe's scaffold with a relative `<capture-dir>` must stop at its absolute-path guard without creating the directory; and the CLI stop block run alone must leave the `rec` session alive on both a timed-out bound and a non-numeric one, so the re-run its message prescribes can be applied; R28's cases derive the intermediate's name from the render block's `cast=` and `"$cast.gif"` and require the step-0 cleanup (both recipes, and the CLI scaffold) to remove that name and not the `recording.gif` nothing writes, with the execution case seeding the real intermediate; R29's cases: a capture directory claimed on another session through a `~/` spelling must be refused (the pre-fix step 2 ran on), and a retry must not be refused by its own `~/` claim (the pre-fix step 2 did), plus the two step-5 branches no mode reached with the pm session alive (`detachnocast`, `detachnostatus`) releasing the claim, which fails when the release is removed from either branch; R30's case runs the step-2 block from the capture directory against a second session that holds no claim, which must proceed and claim the directory (the pre-fix block refused it as a collision), with `_run_block` gaining a `cwd` argument so a case can say where the block is pasted from; R31's cases: both recording recipes' `agg` install run with `~/.local/bin` off `PATH` must fail with the message that names the fix (the pre-fix block exits 0 with an `agg` nothing can run), and the web-UI start block run with a failing `pm qa captures-path` and with a silent one must stop before `mkdir` (a logging `mkdir` stub asserts nothing was attempted) and never start the app (the pre-fix block ran `mkdir -p /scenarios/1/web-ui`); R32's two cases: the driver block run with no `driver.mjs` must stop with the message that names it and must not report "the driver failed", and the block run with an empty `node_modules` and a fake global Playwright must name the removal (`rm -rf node_modules`) and, once applied, resolve the package and run the driver |
| `pm/specs/pr-b19db15/impl.md` | this spec |
| `pm/specs/pr-b19db15/qa.md` | reduced QA scope (recipe fixes only), with the intermediate gif named `recording.cast.gif` as the render block writes it (R28), and the claim's canonical comparison — one directory under two spellings is one claim, refused across sessions and not refused for a retry (R29) |

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
   is what the sends carry); R21's four cases: the CLI stop block run with
   `RECORDER_STOP_TIMEOUT=2m` must exit non-zero with the message instead of
   hanging (against the pre-fix recipe the same run had to be killed at its
   20 s bound), the `agg` install block must carry `--connect-timeout`/
   `--max-time` and, run against a stub `curl` that dies mid-body, must exit
   non-zero, print "could not download agg" and leave no partial binary, the
   finalize block run with a set-but-missing `CAPDIR` must say "does not
   exist" and not "there is no webm to transcode", and the driver block's
   resolution failure must leave none of the earlier attempt's
   webm/trace behind. All five new/tightened assertions fail against the
   pre-fix recipes (checked by restoring them in place). R22's three cases:
   the tmux driving step run against a stub `pm` whose first send fails and
   whose second succeeds must exit non-zero with its message and send no
   further keys (against the pre-fix recipe the same run exits 0); the CLI
   scaffold's driving step must say to check each send and why step 4 cannot
   catch a dead shell; and the web-UI finalize block run with no `ffmpeg` on
   `PATH` must say "ffmpeg is not installed", never blame the driver's webm,
   keep the webm and drop the stale mp4. All three fail against the pre-fix
   recipes (checked by restoring `HEAD`'s recipes in place). R25's cases: each
   failing execution mode (`nostart`, `norec`, `dies`, `failedattach`,
   `stuck`, `notranscript`, `midadied`, `detachfail`, `midbothbad`) must
   leave no claim on the pm session, a failed driving send must leave no
   recorder session, no claim and a saved `recorder-pane.log`, and the
   cross-session refusal must name `tmux set-option -u -t <other>
   @pm_capture_dir`. Eight of the nine failing modes and both message/
   teardown cases fail against `HEAD`'s recipe (`midbothbad` passes both ways
   by design: the session's death takes the claim with it). R26's case: the
   tmux stop block run alone against a server whose reported prefix is `C-a`
   must end the recording (rc 0, recorder gone) and must ask the server for
   the prefix — against the pre-fix block the same run times out at its bound
   with the recorder still up. R27's cases: the web-UI start block run with a
   stub `curl` that times out on the pre-check (exit 28, mode `hung`) must
   stop with "could not check … exit 28" and the `ss -ltnp` remedy and never
   start the app (the pre-fix block starts it and reports "did not answer" at
   the deadline); each recording recipe's scaffold run with a *relative*
   `<capture-dir>` must stop with "must be an absolute path" and create no
   directory (the pre-fix blocks run on and fail later, one of them after
   writing into it); and the CLI stop block run alone with
   `RECORDER_STOP_TIMEOUT=2` (mode `stuck`) and with `2m` must fail with its
   message while leaving the `rec` session in place, so the re-run it
   prescribes can still be applied (the pre-fix block kills the server in
   both branches). All five fail against `HEAD`'s recipes. R29's cases: a
   capture directory another session claims through a `~/` spelling must be
   refused (the pre-fix step 2 runs on and the two runs share it), a retry
   must not be refused by its own `~/` claim (the pre-fix step 2 refuses
   it), and the step-5 cast/status branches reached with the pm session
   still alive (`detachnocast`, `detachnostatus`) must release the claim —
   both fail when the release is removed from their branch. The two
   spelling cases fail against `HEAD`'s recipe; the release cases guard
   behaviour the pre-fix recipe already had (they are coverage for R25's
   rule, not a fix). R31's cases: both recording recipes' `agg` install run
   with `~/.local/bin` off `PATH` must exit non-zero with "… still does not
   resolve — ~/.local/bin is not on PATH; add it …" and leave the downloaded
   binary in place (the pre-fix block exits 0 with an `agg` nothing can run);
   and the web-UI start block run with a `pm` that fails and with one that
   prints nothing must stop with "could not resolve the captures directory"
   before `mkdir` — a logging `mkdir` stub asserts no directory was
   attempted — and never start the app (the pre-fix block ran
   `mkdir -p /scenarios/1/web-ui`). All four fail against `HEAD`'s recipes.
   R32's cases: the web-UI driver block run with an empty capture directory
   (no `driver.mjs`) must exit non-zero with "there is no driver.mjs" and
   must not say "the driver failed"; and the block run with an empty
   `node_modules` and a fake global Playwright must fail with the resolution
   message that names `rm -rf node_modules` alongside the link, and after the
   removal and link the same block must resolve the package and run the
   driver. Both fail against `HEAD`'s block (checked by restoring the pre-fix
   recipe in place, then restoring the post-fix copy).
2. Run the related suites for regressions (`test_qa_artifact_web_ui_recording.py`,
   `test_qa_instructions.py`, `test_qa_loop.py`).
3. Manual/QA evidence: the recipe fixes were exercised live in QA scenarios
   S21 (CLI capture + render, stale dir, no-TTY form, failure modes), S22
   (recording failure modes), S23 (tmux TUI capture, bounded
   readiness/stop), S24 (dead recorders, failed drives, colliding runs), S25
   (web-UI start/readiness) and S26 (web-UI driver + finalize). Their
   captures live under `$(pm qa captures-path pr-b19db15)/scenarios/`. S24
   found the collision the claim fixes; its post-fix captures and the
   regression tests cover it, and a re-QA re-verifies the reduced diff.
4. R28's naming check: the two stale-video tests derive the intermediate's
   name from the render block and fail against `HEAD`'s recipes (checked by
   restoring them in place, then restoring the post-fix copies); the
   execution case seeds `recording.cast.gif` and requires the failed capture
   to remove it.

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
- Review loop e7e1 i8 verified R21 in this container. **The mistyped bound is
  a real hang, not a cosmetic one**: in a real interactive bash on a pty,
  `d=$(( 5 + 2m ))` prints "value too great for base", leaves `d` empty, and
  the shell carries on (`if [ 100 -ge "$d" ]` → "integer expression expected",
  false), so a deadline check built on it never fires. Driving the recipe's
  own step-4 block with `RECORDER_STOP_TIMEOUT=2m` against a live `rec`
  session (real tmux 3.2a + asciinema 2.1.0, private `TMUX_TMPDIR`) hung until
  the harness killed it at 20 s; post-fix the same run exits 1 in 0.0 s with
  "RECORDER_STOP_TIMEOUT must be whole seconds (got '2m'); e.g.
  RECORDER_STOP_TIMEOUT=120" and no scaffold server left. `2` still times out
  at its bound with the pane saved, the default still stops at 29.5 s, and a
  one-shot recording still passes (rc 0, status 0, 142-byte cast), so the
  guard does not disturb the paths it protects. The `agg` install failure was
  driven with **real curl** against a closed proxy port: rc 1, "could not
  download agg — put a release binary on PATH and re-run the render", and
  `~/.local/bin` left empty (the pre-fix block left the partial file and
  exited on curl's status with no message). The finalize block with a
  set-but-missing `CAPDIR` now prints "capture directory … does not exist —
  create it and run step 1" (pre-fix: "there is no webm to transcode — the
  driver wrote no video"). The pty decode fix was found by running the full
  file six times under this container's POSIX locale: `text=True` strict UTF-8
  failed once on a readline redraw that split an em dash. Tests: 3 new + 2
  extended (non-numeric stop bound, bounded/cleaned-up `agg` download ×2
  recipes, finalize missing directory, resolution-failure cleanup), all five
  failing against the pre-fix recipes (checked by restoring `HEAD`'s recipes
  in place and restoring the post-fix copies afterwards). File 118 pass;
  related suites (`test_qa_artifact_web_ui_recording`, `test_qa_instructions`,
  `test_qa_loop`, `test_markdown_render`) 306 pass with the `markdown` dep
  installed. No `pm_core/` change; the dropped helper/prompt/verifier work
  stays dropped.
- Review loop e7e1 i9 verified R22 in this container (bash; stub `pm`, and
  the web-UI finalize block run with a `PATH` that holds no `ffmpeg`).
  **The tmux driving step's unchecked send is a silent success, not a
  cosmetic gap**: with a stub `pm` whose first `tui send` exits 1 (real
  `pm tui send` exits 1 when no TUI pane is found — `pm_core/cli/tui.py`)
  and whose second succeeds, the pre-fix block exits **0** with only the
  stub's own stderr; post-fix the same run exits 1 with "pm tui send
  failed — the TUI is gone, so this scenario step never ran; re-run the
  capture instead of accepting it", and the send log holds exactly one
  entry (no keys sent after the failure). With all sends succeeding the
  block still exits 0 and both sends carry the re-derived session. The
  web-UI finalize block with a webm present, a stale mp4 seeded and no
  `ffmpeg` on `PATH` printed "ffmpeg: command not found" plus "transcode
  produced no mp4 — ffmpeg failed on the driver's webm" before the fix
  (an encoder/browser misdiagnosis for a missing tool); post-fix it exits 1
  with "ffmpeg is not installed — the finalize step needs it; install it
  (e.g. 'apt-get install ffmpeg') and re-run this step", leaves the webm
  for the retry and leaves no mp4. The CLI scaffold's driving step now
  carries the same warning as the tmux one (a failed `send-keys` means the
  recorded shell is gone, and step 4 cannot tell because asciinema exits 0
  whenever its command ends). Tests: 3 new — all three fail against the
  pre-fix recipes (checked by restoring `HEAD`'s recipes in place and
  restoring the post-fix copies afterwards). File 121 pass; related suites
  (`test_qa_artifact_web_ui_recording`, `test_qa_instructions`,
  `test_qa_loop`) 175 pass. No `pm_core/` change; the dropped
  helper/prompt/verifier work stays dropped.
- Review loop e7e1 i10 verified R23 live in this container (bash; stub
  `tmux`/`pm` for the block runs, and a real local HTTP server for the 404
  case). **A failed capture leaves the earlier run's video**: with an earlier
  `recording.mp4`/`recording.gif` seeded and a recorder that never writes a
  cast, the pre-fix blocks of both recording recipes exit 1 and leave both
  files in the capture directory (verified with the recipes' own capture
  blocks, and separately with the pre-fix copies in place) — a capture
  directory with no cast but a presentable video, which the manifest's
  `## Files` section and the report would read as this run's recording. Post-
  fix the same runs leave neither file; the CLI scaffold also drops the
  earlier `tee` fallback's `transcript.log`. **A missing encoder was reported
  as a bad gif**: this container has no `ffmpeg`, `ffprobe` or `agg`
  (`command -v` prints nothing for all three), so driving the recipes' own
  render blocks on a `PATH` without them printed "ffmpeg: command not found"
  plus "render produced no mp4 — ffmpeg failed on the gif" before the fix;
  post-fix they stop before the `agg` render with "ffmpeg is not installed —
  the render step needs it; install it (e.g. 'apt-get install ffmpeg') and
  re-run this step", and the gif is never created. **The readiness poll
  required a 2xx**: a local server answering 404 at `/` is treated as
  answering by the port pre-check (`curl -s` → rc 0) while `curl -sf` exits
  22, so the pre-fix poll ran out its deadline, reported "app did not answer"
  and killed a healthy server; with plain `curl` the poll returns at once
  (and a dead port still exits 7). Tests: 9 new cases (both recipes'
  step-0 video cleanup as text and by execution, the CLI transcript, the
  missing encoder in both render blocks, and the 404-at-root readiness case
  through a stub `curl` that models `-f` as exit 22) — all nine fail against
  the pre-fix recipes (checked by restoring `HEAD`'s recipe files in place,
  then restoring the post-fix copies). File 130 pass; related suites
  (`test_qa_artifact_web_ui_recording`, `test_qa_instructions`,
  `test_qa_loop`, `test_markdown_render`) 188 pass. No `pm_core/` change; the
  dropped helper/prompt/verifier work stays dropped.
- QA S24 verified R24 live in this container (real tmux 3.4 on a private
  server with the default `C-b` prefix, real asciinema 2.4.0, real `pm`
  from this clone). **One session, two capture directories**: with A
  recording and holding the claim, B pasting the recipe's step 2 is refused
  with "`<session>` is already being recorded into `<A's cap>` — end that
  capture, or clear the claim …"; A's final `?` step then grew its
  transcript by 54,884 bytes (the help screen's `Auto-start runs` appears)
  and A's stop exited 0 with status 0 and a non-empty cast. Pre-fix the same
  run left A's transcript delta at 0, put the help screen only in B's log,
  and still exited 0 — a silent false pass. **One capture directory, two
  sessions**: post-fix B's step 2 is refused with "… is already being
  recorded by pm session `<A's session>` …", A's stop exits 1 with "recorder
  exited while the TUI was still running", B's stop exits 1 the same way,
  and the shared directory holds no evidence either could present as its
  own; pre-fix A's stop exited 0 on B's cast and status. The remaining hole
  is recorded, not hidden: a worker who bypasses the recipe with a raw
  `tmux pipe-pane` still takes the pipe over (captured as
  `shared-pipe-raw-bypass`). The other eight scenario stories (recorder
  killed with the TUI alive, asciinema's 137, a torn-down pane with no
  status, the legitimate finish + render, the failed attach, the crashed-TUI
  send, the stale video, and the two-workers collision) all still behave as
  specified after the change. Tests: 5 new cases (the claim is written; a
  second capture directory on one session is refused; a directory another
  live session records into is refused; a finished run releases the claim;
  step 2 refuses an empty `$TARGET`), with the stub `tmux` extended to model
  `show-options`/`set-option`/`list-sessions`; four of the five fail against
  the pre-fix recipe (the release case passes both ways by design, like the
  missing-`agg` cases). File 135 pass. No `pm_core/` change; the dropped
  helper/prompt/verifier work stays dropped.
- Review loop 9265 i1 verified two leftovers in the kept recipe scope, both
  the PR's own class. (1) **The R24 claim was written after the pipe it
  guards**, although the recipe's own prose and this spec say before. Live
  probe with real tmux 3.4 on a private server, the recipe's own step-2 block,
  a `tmux` shim logging the call order, and a stub `pm`: HEAD runs
  `show-options` → `list-sessions` → **`pipe-pane`** → **`set-option`**,
  while the fixed block runs `show-options` → `list-sessions` →
  **`set-option`** → **`pipe-pane`** (rc 0, the claim holds the capture
  directory, `#{pane_pipe}` = 1). The claim's check and write are separate
  tmux calls, so with the write last a second run passes the same read,
  attaches its own pipe (the takeover the claim exists to stop), and only then
  overwrites the claim — the S24 false pass through a smaller window. The
  pipe-failure path now releases the claim it just took, and step 5 stops the
  pipe before releasing the claim (so its cleanup cannot stop a later run's
  pipe). (2) **The web-UI driver block's attempt cleanup omitted
  `recording.mp4`.** That block is pasted alone when a driver is retried; an
  earlier attempt that had already reached the finalize step leaves the
  primary artifact, and a retry that fails then ends with that video as the
  only recording the manifest can present as this run's — the finalize step
  clears it only when it runs, and a failed driver is told not to finalize.
  Tests: 1 new ordering case (the stub `tmux` records the claim state seen by
  `pipe-pane`) and the driver-failure case extended to seed the earlier
  attempt's `recording.mp4`; both fail against HEAD's recipes (checked by
  restoring them in place, then restoring the post-fix copies). File 136
  pass; related suites (`test_qa_artifact_web_ui_recording`,
  `test_qa_instructions`, `test_qa_loop`) 311 pass; full suite 3991 passed, 1
  skipped, 92 deselected (`test_merge_publish`/`test_signoff_integration`).
  Evidence: `/pm-captures/review-9265-i1/` (`probe.log`, the two order logs,
  both step-2 blocks and the `tmux` shim). No `pm_core/` change; the dropped
  helper/prompt/verifier work stays dropped.
- Review loop 9265 i2 verified R25 live in this container (real tmux 3.4 on a
  private default-config server, real asciinema 2.4.0, a stub `pm` that
  creates the pm session and fails its `tui send`). **A failed run kept its
  claim**: with no `asciinema` on `PATH` the capture block fails at its
  readiness check, and before the fix `tmux show-options -t pm-test -v
  @pm_capture_dir` still answered with the capture directory afterwards; with
  the release in that path it answers "invalid option". The same was true of
  every other failure path (verified by the nine execution modes in the test
  module). **A failed driving send left the run alive**: with the stub `pm`
  failing `tui send`, the pre-fix block exited 1 with the recorder session
  still present, `#{pane_pipe}` still 1 and the claim still set; post-fix the
  pane is saved in `recorder-pane.log` (the TUI's last screen), the recorder
  session is gone, `#{pane_pipe}` is 0 and the claim is unset. **The
  cross-session refusal was a dead end**: with another session holding the
  claim, the block now answers "… already being recorded by pm session
  pm-other — end that capture, or use another capture directory; if that run
  is gone, clear its claim with 'tmux set-option -u -t pm-other
  @pm_capture_dir'", and takes no claim of its own. The nominal flow was
  re-run end to end after the change (rc 0, cast 4046 bytes, transcript
  written, status 0, claim released). Tests: 9 release cases + the driving
  teardown case + the refusal-message case; 8 of the 9 release modes and both
  of the other cases fail against `HEAD`'s recipe (checked by restoring it in
  place, then restoring the post-fix copy); the stub `tmux`/`pm` now model a
  session's death taking its options with it. Evidence:
  `$(pm qa captures-path pr-b19db15)/review-9265-i2/` (`probe.log` with all
  six live cases, `recipe-pre.md`/`recipe-post.md`, and `scripts/` — the
  extractor and the probe driver). File 147 pass; related suites
  (`test_qa_artifact_web_ui_recording`, `test_qa_instructions`,
  `test_qa_loop`, `test_markdown_render`) 188 pass; full suite 4002 passed, 1
  skipped, 92 deselected (`test_merge_publish`/`test_signoff_integration`).
  No `pm_core/` change; the dropped helper/prompt/verifier work stays
  dropped.
- Review loop 9265 i3 verified R26 live in this container (real tmux 3.4 on a
  private server whose `~/.tmux.conf` sets `set -g prefix C-\` — this host's
  own prefix — real asciinema 2.4.0, the recipe's own step-3 recorder command
  and its step-5 block extracted verbatim with `<capture-dir>` substituted).
  **The detach key was wrong for the server.** With `C-b d`, the recorder was
  still up 3 s later and the pane showed `^Bd` — the keys landed in the
  attached TUI as input — so the stop wait ran out its 30 s bound and exited 1
  with "recorder did not exit within 30s — the pane is saved in
  …/recorder-pane.log", no `recorder.status`, and a 4.6 KB cast of the wrong
  30 s. With the derived prefix (`tmux show-options -gv prefix` → `C-\`) the
  same run exits 0 with `recorder.status` 0 and a 4.3 KB cast. The same pair
  was reproduced with `C-a` as the server's prefix (`C-b d` left the recorder
  up; `C-a d` ended it). Tests: 1 execution case (the stop block alone against
  a stub server reporting `C-a`, whose `send-keys` ends the recording only for
  the prefix the server reports) plus a text assertion that the block asks for
  it; the execution case fails against `HEAD`'s recipe (checked by restoring
  it in place, then restoring the post-fix copy) with the stop timeout.
  Evidence: `$(pm qa captures-path pr-b19db15)/review-9265-i3/`
  (`probe.log` with the pre/post live runs, `scripts/` with both step-5
  blocks, the live driver and the three prefix probes). File 148 pass; related
  suites (`test_qa_artifact_web_ui_recording`, `test_qa_instructions`,
  `test_qa_loop`, `test_markdown_render`) 188 pass; full suite 4003 passed, 1
  skipped, 92 deselected (`test_merge_publish`/`test_signoff_integration`).
  No `pm_core/` change; the dropped helper/prompt/verifier work stays dropped.
- Review loop 9265 i4 verified R27 live in this container (real tmux 3.4 on a
  private default-config server with `~/.tmux.conf`'s `C-\` prefix, real
  asciinema 2.4.0, a stub `pm` that creates the session and sends keys, a
  real local socket for the port case). **The port pre-check could not tell a
  taken port from a free one**: with a listener that accepts the connection
  and never answers, the pre-check's own `--max-time 5` expired, the block
  treated the port as free, the stub app failed to bind ("Address already in
  use"), and the run reported "app did not answer on … within 120s — check
  its startup output" after the deadline and killed the app it had started
  (the probe shortened the deadline to 2 s, as the tests do); post-fix the
  same listener is refused in 5.0 s with "could not check … with curl (exit
  28; only 'connection refused', 7, means the port is free) … find a listener
  with 'ss -ltnp' …" and the app is never started. `curl`'s statuses were
  checked directly in this container: closed port → 7, hung listener → 28.
  **A relative capture directory was accepted and the artifact landed where
  the checks did not look**: `tmux pipe-pane` from /tmp/b with
  `cat >> rel.log` wrote /tmp/a/rel.log (the session's directory, verified
  separately), and with `<capture-dir>` = `relcap` the tmux stop block pasted
  from another directory answered "asciinema wrote no cast" while the cast
  sat in the worker's directory; post-fix both recipes' step 0 exit 1 with
  "must be an absolute path" and create nothing. **The CLI stop step killed
  the recording its remedy retries**: a one-shot `sleep 6` was recorded, the
  stop block with `RECORDER_STOP_TIMEOUT=1` timed out, killed the server, and
  the documented re-run with 60 answered "recorder status is missing" — the
  recording was gone; post-fix the timeout leaves the session alive, the
  re-run with 60 exits 0 with `recorder.status` 0, and the pane is still
  saved. The nominal flows were re-run after the changes (tmux: rc 0, status
  0, 4.3 KB cast, claim released; CLI: the retry above). Tests: 5 new cases
  (the web-UI pre-check refusing exit 28 without launching the app; a
  relative `<capture-dir>` refused in both recipes without creating it; the
  CLI stop block leaving the `rec` session on a timed-out bound and on a
  mistyped one), all five failing against `HEAD`'s recipes (checked by
  restoring them in place, then restoring the post-fix copies). File 153
  pass; related suites (`test_qa_artifact_web_ui_recording`,
  `test_qa_instructions`, `test_qa_loop`) 175 pass; full suite 4008 passed, 1
  skipped, 92 deselected (`test_merge_publish`/`test_signoff_integration`).
  Evidence: `$(pm qa captures-path pr-b19db15)/review-9265-i4/`
  (`probe-prefix.log` with the HEAD-recipe observations above,
  `probe-postfix.log` with the same cases re-run after the fix, and
  `scripts/` — the block extractor, the three probe drivers and the stub
  `pm`). No `pm_core/` change; the dropped helper/prompt/verifier work stays
  dropped.
- Review loop 9265 i5 verified R28 live in this container (the recipes' own
  extracted step-0 and render blocks; a stub `agg`/`ffprobe`/`ffmpeg`, plus
  a real agg 1.9.0 render of a real cast for the name). **The stale-video
  cleanup named a file nothing writes**: with an earlier
  `recording.cast.gif` and `recording.gif` seeded, the pre-fix step-0 `rm`
  removed only `recording.gif` and left the real intermediate behind, and
  the render block's `agg` output argument is
  `…/recording.cast.gif` (`cast=…/recording.cast`, rendered to `"$cast.gif"`).
  The two tests seeded and checked the same wrong name, so they passed
  against the pre-fix recipes. Post-fix step 0 clears the real name in both
  recipes (and the CLI scaffold), and the tests derive it from the render
  block; both tests fail against `HEAD`'s recipes (checked by restoring them
  in place, then restoring the post-fix copies). Evidence:
  `$(pm qa captures-path pr-b19db15)/review-9265-i5/`
  (`probe-gif.log`, the extractor, and the seeded-cleanup and render-name
  probes). No `pm_core/` change; the dropped helper/prompt/verifier work
  stays dropped.
- Review loop 7c9c i1 verified R29 live in this container (real tmux 3.2a on a
  private `TMUX_TMPDIR`, real asciinema 2.1.0 for the nominal re-run, the
  recipe's own step-2 block extracted verbatim with `<capture-dir>`
  substituted, a stub `pm` that names the session). **The claim was compared
  as text**: with `~/capA` claimed on `pm-test`, a second session pasting step
  2 with `/home/<user>/capA` — the same directory — ran on (rc 0) and claimed
  it too, so both runs write that directory's cast and transcript and each
  stop step reads the other's evidence; the same run's retry with the other
  spelling was refused as "already being recorded into ~/capA". Post-fix on a
  fresh server: `~/capA` is stored as `/home/<user>/capA`, the other session
  is refused with the "already being recorded by pm session pm-test" message,
  and the same-session retry exits 0. The full capture block was re-run end to
  end after the edit (rc 0, cast + transcript + `recorder.status` 0, claim
  released), and the CLI scaffold's nominal run is unchanged (rc 0). The two
  spelling cases fail against `HEAD`'s step 2 (checked by restoring the
  pre-fix recipe in place, then restoring the post-fix copy); the two
  `detachnocast`/`detachnostatus` release cases pass both ways by design —
  they are coverage for R25's rule — and fail when the `set-option -u` is
  removed from their branch. File 157 pass; related suites
  (`test_qa_artifact_web_ui_recording`, `test_qa_instructions`,
  `test_qa_loop`, `test_markdown_render`) 188 pass. Evidence:
  `$(pm qa captures-path pr-b19db15)/review-7c9c-i1/` (`probe-prefix.log`,
  `probe-postfix.log`, `nominal.log`, the pre/post step-2 blocks and the stub
  `pm`). No `pm_core/` change; the dropped helper/prompt/verifier work stays
  dropped.
- Review loop 7c9c i2 verified R30 live in this container (real tmux 3.2a on
  private `TMUX_TMPDIR`s, real asciinema 2.1.0 for the nominal re-runs, the
  recipe's own step-2 and full capture blocks extracted verbatim with
  `<capture-dir>` substituted, a stub `pm` that names the session and creates
  it). **A session with no claim was read as a claim on the worker's
  directory**: `tmux show-options -t pm-other -v @pm_capture_dir` answers
  nothing for an unset user option (exit 0, empty), and `cd ""` succeeds and
  stays in the current directory, so the scan compared the pasting shell's
  cwd with the claim. With `pm-other` holding no claim, step 2 pasted from the
  capture directory exited 1 with "<capture-dir> is already being recorded by
  pm session pm-other" and took no claim of its own; post-fix the same run
  exits 0, stores the canonical directory on `pm-test` and attaches the pipe
  (`#{pane_pipe}` = 1). A real collision is unchanged post-fix: with
  `pm-other` holding `/tmp/capA`, the same block still refuses it and leaves
  `pm-test` without a claim. The full capture block re-ran end to end after
  the edit from *outside* the capture directory with another pm session on the
  server (rc 0, `recorder.status` 0, cast + transcript, claim released,
  `pm-recorder` gone). Tests: one new execution case (the step-2 block run
  from the capture directory against a session with no claim), which fails
  against `HEAD`'s step 2 (checked by restoring the pre-fix recipe in place,
  then restoring the post-fix copy). File 159 pass; related suites
  (`test_qa_artifact_web_ui_recording`, `test_qa_instructions`,
  `test_qa_loop`) 175 pass (334 together with the file). Evidence:
  `$(pm qa captures-path pr-b19db15)/review-7c9c-i2/` (`probe.log` with cases
  A-D, `scripts/` with the pre/post step-2 and capture blocks and the stub
  `pm`). No `pm_core/` change; the dropped helper/prompt/verifier work stays
  dropped.
- Review loop 7c9c i3 verified R31 live in this container. **The `agg`
  install exited 0 with an `agg` nothing could run**: with a PATH that
  excludes `~/.local/bin` and a stub `curl` that writes the release binary,
  the pre-fix block installed `~/.local/bin/agg` (executable), exited **0**,
  and `command -v agg` still failed; the render block then printed "agg
  failed on the cast — is 'agg' installed?" and exited 1 — the remedy the
  message names is the block that just ran, so the worker loops. Post-fix
  the same run exits 1 with "installed ~/.local/bin/agg but 'agg' still does
  not resolve — ~/.local/bin is not on PATH; add it (export
  PATH="$HOME/.local/bin:$PATH") and re-run the render", and with
  `~/.local/bin` on PATH (the image's layout) the block still exits 0 with
  `agg` resolving, so the nominal path is unchanged. **The web-UI start
  block turned an unresolvable captures path into a directory at the
  filesystem root**: `pm qa captures-path pr-xxxxxxx` (real `pm`, this
  container) prints "PR 'pr-xxxxxxx' not found." on stderr, exits 1 and
  leaves stdout empty, and pasted outside the project it answers "No
  project.yaml found" the same way — so the bare substitution made
  `CAPDIR=/scenarios/1/web-ui`, and the pre-fix block ran
  `mkdir -p /scenarios/1/web-ui` (as this container's non-root user that
  failed and was reported as "could not create /scenarios/1/web-ui — check
  the path and its permissions"; in the root QA container it would have been
  created, and the block carried on: the probe's stubbed `mkdir` models that
  and the run exited **0** with the capture aimed at `/scenarios/1/web-ui`).
  Post-fix both the failing and the empty-answer runs exit 1 with "could not
  resolve the captures directory for pr-xxxxxxx — run 'pm qa captures-path
  pr-xxxxxxx' in the project to see why …", attempt no directory and never
  start the app; the nominal run (a stub `pm` printing a captures root)
  still exits 0 and writes `<root>/scenarios/1/web-ui/server.pid`. Tests:
  four new cases, all failing against `HEAD`'s recipes (checked by restoring
  them in place, then restoring the post-fix copies). File 163 pass; related
  suites (`test_qa_artifact_web_ui_recording`, `test_qa_instructions`,
  `test_qa_loop`) 175 pass; full suite (`env -u PM_HOST_HOME
  PATH=/usr/bin:/bin pytest tests/ -q --deselect
  tests/test_merge_publish.py --deselect tests/test_signoff_integration.py`)
  4545 passed, 1 skipped, 92 deselected, 12 failed — all
  `tests/test_markdown_render.py` with `ModuleNotFoundError` for the
  `markdown` dep this container lacks (the same file passes 13/13 once it is
  installed on the scratch path); none touch the changed area. Evidence:
  `$(pm qa captures-path pr-b19db15)/review-7c9c-i3/` (`probe.log` with the
  pre/post runs of both cases and the real `pm` failure shapes, `scripts/`
  with the extractor, the pre/post blocks and the probe driver). No
  `pm_core/` change; the dropped helper/prompt/verifier work stays dropped.
- Review loop 7c9c i4 verified R32 live in this container with real `node`
  22.22.2. **A missing `driver.mjs` was reported as a failed driver run**:
  with an empty capture directory (a fake global Playwright so the resolution
  check passes) the pre-fix block exits 1 with "the driver failed — this
  run's video, trace and screenshots are incomplete; do not finalize this
  attempt" after Node's `Cannot find module '<capture-dir>/driver.mjs'`;
  post-fix the same run exits 1 with "there is no driver.mjs in … — save the
  recipe's driver skeleton as driver.mjs here (step 2's prose) before running
  this block" and runs no driver. **The resolution failure's link remedy
  nested inside an existing `node_modules`**: with an empty `node_modules`
  and a fake global Playwright holding the package, the pre-fix block exits 1
  with "… link it ('ln -sfn <global> node_modules') …", and pasting that `ln`
  creates `node_modules/global` — `node -e "import('playwright')"` still
  answers ERR_MODULE_NOT_FOUND — so repeating the remedy cannot work;
  post-fix the message names "remove a node_modules here that does not hold it
  and link the global install ('rm -rf node_modules; ln -sfn … node_modules')",
  and after that removal and link the same block resolves Playwright and runs
  the driver (rc 0, "driver saw object"). Tests: two new cases, both failing
  against `HEAD`'s driver block (checked by restoring the pre-fix recipe in
  place, then restoring the post-fix copy). File 165 pass. Evidence:
  `$(pm qa captures-path pr-b19db15)/review-7c9c-i4/` (`probe.log` with the
  pre/post runs of both cases). No `pm_core/` change; the dropped
  helper/prompt/verifier work stays dropped.
