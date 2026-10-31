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
   "=pm-recorder"` — exact since R39 — / `tmux -L scaffold kill-session -t
   rec`): `new-session` fails
   with "duplicate session" while it exists, and since R15 that failure stops
   the run at "could not start the recorder session". (Before the start check
   the run carried on, but not into a false pass: the tmux readiness wait's
   pane content came from the *old* attach client, while the CLI wait is on
   the cast file, which step 0 clears, so it ran out its deadline against a
   `rec` session that never wrote one. Neither path is reachable now; R35
   corrects the places that still described them as current.) The CLI
   scaffold clears the session, not the server — `kill-server` followed a few
   milliseconds later by `new-session` races the server's exit ("server exited
   unexpectedly", reproduced ~7 times in 40 tight iterations). Both recipes
   also remove a
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
   waits (bounded) for `tmux has-session -t "=pm-recorder"` to fail — the
   pane is
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
   computed session (`tmux has-session -t "=$TARGET"`, exact since R37), not
   on `tmux ls | grep
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
     a check a working `agg` passes so it never re-downloads over one (R16,
     later `agg --version` per R52), and say not to substitute a different
     renderer.
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
     recipes (R52 later changes the guard to `agg --version`, which keeps this
     protection and also catches a truncated binary), matching its own prose;
     verified that the guarded block still
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
     missing encoder, one step earlier. The block now checks `driver.mjs`
     after its attempt cleanup (so an earlier attempt's outputs still go,
     per R21) and before the Playwright link/resolution work — `[ -s
     driver.mjs ]`, tightened from `-f` by R51, because a 0-byte driver is a
     valid ES module that `node` runs successfully — and stops with
     "there is no driver.mjs in $CAPDIR (or it is empty) — save the recipe's
     driver skeleton as driver.mjs here (step 2's prose) before running this
     block". Verified
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

R33. **A quit that races the detach is not a truncated recording.** One
   leftover in the kept tmux-recipe scope found by review loop 7c9c i5, in
   step 5's failed-detach branch. Step 5 checks that the recorder session is
   still up and then sends the detach key; a failed `send-keys` was treated
   as a recorder that died mid-scenario ("recorder exited before the detach —
   the cast is incomplete, not a finished recording"). But the same failed
   send has a second cause: the scenario ended the pm session itself, the
   attach client followed it out, and the quit raced the key send — the
   recorder is gone by the time the key is sent, with a complete cast and
   `recorder.status` 0. That is exactly the "both gone" finish the branch one
   above accepts when it happens a moment earlier, so a complete recording
   was reported as incomplete. The status handle already decides this
   ambiguity everywhere else in the step (the both-gone branch, the CLI
   scaffold's stop); the detach-failure branch now uses it too: the failed
   send is a hard failure only while the target session is still there (the
   witness that says the recorder died mid-scenario), and when it is gone as
   well the cast, status and transcript checks below decide — status 0
   passes, 128+N or a missing status file still fails. Verified live in this
   container with real tmux 3.2a + asciinema 2.1.0 on a private
   `TMUX_TMPDIR`, the recipe's own step-3 recorder, and a `tmux` shim that
   reports the "is the recorder still up?" check as true exactly once (the
   race instant; everything else is real tmux): after the scenario ends the
   pm session, the pre-fix step 5 exits 1 with "recorder exited before the
   detach — the cast is incomplete" on a complete recording
   (`recorder.status` 0, 2623-byte cast), while the fixed block exits 0; with
   the recorder SIGKILLed and the session gone the fixed block still fails
   with "asciinema exited 137 — the cast is incomplete". Tests: two execution
   cases with a new stub mode that fails the detach and takes the target
   session with it — status 0 must pass (fails against `HEAD`'s step 5) and
   status 137 must still fail on the status message (also fails against
   `HEAD`'s step 5, which reports the detach instead). The
   target-still-alive detach failure and the server-prefix cases pass
   unchanged. Also corrected in both recipes: the step-0 prose said a
   leftover recorder session makes the readiness wait "pass on the previous
   run's recorder", but since R15 a duplicate `new-session` stops the run at
   "could not start the recorder session", so that failure mode is not
   reachable. Evidence: `$(pm qa captures-path pr-b19db15)/review-7c9c-i5/`
   (`probe.log` with the three live runs and the mutation check, `README.md`,
   `scripts/` — the pre/post step-5 blocks, the shim and the live driver). No
   `pm_core/` change; the dropped helper/prompt/verifier work stays dropped.

R34. **A block refused for its input must not already have acted on a shared
   handle, and the last uncovered failure path gets its assertion.** One
   leftover in the kept CLI-recipe scope, the PR's own class, found by review
   loop 7c9c i6, and a test gap on the same rule:
   - **The CLI scaffold cleared the host-shared `rec` session before
     validating `<capture-dir>`.** The scaffold's first statement was
     `tmux -L scaffold kill-session -t rec`, and the absolute-path guard came
     *after* it. The `-L scaffold` socket name is shared by every CLI capture
     on the host (the step-1 note says so), so that clear ends whatever
     capture is recording there before the guard has even looked at the
     path. Verified with the
     recipe's own scaffold block and a logging stub `tmux`: pasted with a
     relative `<capture-dir>` (`relcap`), the pre-fix block ran
     `-L scaffold kill-session -t rec` and only then refused with "must be
     an absolute path", so a worker who pasted the block with an
     unsubstituted placeholder killed a concurrent capture's recorder; that
     run then failed as "recorder status is missing", a failure it could not
     connect to this block. (The tmux recipe's step 0 already had the guard
     first, so this was also the one place the two recipes disagreed.)
     The guard now runs first and the `rec` clear follows it, with the
     reason in the guard's comment.
   - **The pipe-attach failure's claim release was the one path no test
     asserted.** `test_a_failed_run_releases_its_capture_dir_claim` covered
     nine failing modes but not `pipefail` (step 2's failed
     `pipe-pane`), so deleting that branch's
     `tmux set-option -u … @pm_capture_dir` left every test green even
     though the stale claim would refuse the next attempt in the session.
     `pipefail` is now in the parametrization (mutation-checked: removing the
     release from that branch fails exactly that case).
   Tests: one new execution case (the scaffold run with a relative
   `<capture-dir>` against a logging stub `tmux` must make no tmux call at
   all) and one new parametrization entry (`pipefail`). Both fail against
   `HEAD`'s recipe (the new case) or against the release removed from the
   branch (the parametrized case). Evidence:
   `$(pm qa captures-path pr-b19db15)/review-7c9c-i6/` (`probe.log` with the
   pre/post scaffold runs, the mutation check, and the scripts). No
   `pm_core/` change; the dropped helper/prompt/verifier work stays dropped.

R35. **A statement that names a failure mode the handle cannot have.** One
   leftover in the kept recipe/spec scope found by review loop 7c9c i7, and
   the same one in three more places. R33 corrected the step-0 prose that
   said a leftover recorder session would make the readiness wait "pass on
   the previous run's recorder", because since R15 a duplicate `new-session`
   stops the run at "could not start the recorder session". The correction
   was applied to the tmux recipe and to one sentence of `qa.md`, but the
   same claim survived in the CLI recipe's prose, in this spec's R2, in
   `qa.md`'s R3 and in `test_stale_recorder_is_cleared_before_start`'s
   docstring — and in the CLI it was never true for a second reason: that
   recipe's readiness handle is the *cast file* (a quiet command draws
   nothing), which step 0 clears, so a leftover `rec` session could only burn
   the deadline, never satisfy the wait. Verified live on tmux 3.2a with the
   recipes' own readiness blocks: with a leftover `rec` session and an empty
   cast the CLI block exits 1 with "recorder did not start within 30s",
   while the tmux block (pane content) passes at once on the leftover
   `pm-recorder`'s pane — which is why the tmux wording is a legitimate
   counterfactual and the CLI one was not. The CLI prose now says the
   scaffold reports the duplicate as a start failure instead of spinning out
   its wait against a `rec` session that never writes a cast; R2, `qa.md`'s
   R3 and the test docstring say the clear keeps a re-run from stopping at
   the start check (and record the pre-R15 behaviour as history, not as the
   current rationale). No behaviour change and no new assertion: the affected
   text is prose and a docstring, and the behaviour it explains is already
   covered by `test_recorder_session_that_never_starts_is_reported` (a
   duplicate session is a start failure) and the two readiness execution
   cases. Evidence: `$(pm qa captures-path pr-b19db15)/review-7c9c-i7/`
   (`probe.log` with the two live readiness runs and `scripts/` — the
   extracted blocks and the probe driver). No `pm_core/` change; the dropped
   helper/prompt/verifier work stays dropped.

R36. **A block refused for its input must not act on a shared handle — the
   rule one line below R34's guard.** One leftover in the kept recipe scope
   found by review loop 7c9c i8, in both recording recipes. R34 moved the
   absolute-path guard ahead of the `rec`-session clear because that clear
   ends whatever capture is running on the host-shared `scaffold` socket, but
   the *next* refusal in the same block — a capture directory that cannot be
   created (R15's check) — still came after the clear. The tmux recipe had
   the same order with `pm-recorder`, which is shared by every capture on one
   server (R26). Verified live on a private tmux server with the recipes' own
   capture blocks: with a concurrent capture's `pm-recorder` / `rec` up and
   `<capture-dir>` under a regular file (so the `mkdir` fails), the pre-fix
   blocks exit 1 with "could not create …" *after* killing that recorder
   (`tmux has-session` answers gone), so the concurrent run then fails as
   "recorder exited while the TUI was still running" (tmux) or "recorder
   status is missing" (CLI) — a failure it cannot connect to the other
   worker's paste. Both blocks now create the capture directory first and
   clear the recorder session after it, so a refused block makes no tmux call
   at all; post-fix on the same server the concurrent recorder survives
   (`probe-postfix.log`). The step-0 prose and the scaffold's step-1 note say
   why the order matters. Tests:
   `test_capture_dir_that_cannot_be_created_is_reported` now runs the block
   with the stub `tmux` logging its calls (a new `STUB_TMUX_LOG`) and requires
   that it make no `kill-session` call; both cases fail against `HEAD`'s
   recipes (checked by restoring them in place, then restoring the post-fix
   copies). The nominal flows were re-run end to end on real tmux 3.2a +
   asciinema 2.1.0 after the edit (tmux: rc 0, 3029-byte cast,
   `recorder.status` 0, 12-byte transcript, claim released; CLI: rc 0,
   143-byte cast, status 0). Evidence:
   `$(pm qa captures-path pr-b19db15)/review-7c9c-i8/` (`probe-prefix.log` /
   `probe-postfix.log`, `nominal.log`, and `scripts/` — the block extractor
   and the three live drivers). No `pm_core/` change; the dropped
   helper/prompt/verifier work stays dropped.

R37. **A session target is not exact without tmux's `=`.** Two leftovers in the
   kept recipe scope, both the PR's own class (a wait that matches the wrong
   thing), found by review loop 7c9c i9 and reproduced live in this container
   on tmux 3.2a.
   - **The readiness wait passed on pm's grouped session.** Step 1's comment
     said it waits "on that exact session", but `tmux has-session -t "$TARGET"`
     is not exact: tmux matches a session target by *prefix* when no session
     has the whole name (verified: `has-session -t pm-test` exits 0 with only
     `pm-test~1` on the server, and `-t pm` matches `pm-testX`). pm itself
     creates exactly those sessions — `pane_layout.py` and `pane_registry.py`
     handle the grouped `base~1`/`base~2` sessions pm adds per extra co-viewing
     client — so with only `pm-test~1` on the server and a `pm session` that
     could not create the base, the wait passed at once, step 2 claimed and
     piped that session, the recorder attached to it, and the run exited **0**
     with a cast, `recorder.status` 0 and a transcript: a complete, successful
     capture of a session pm never started, with the step-1 failure path
     unreachable. The wait now asks for `-t "=$TARGET"` (`=` forces the exact
     match), and the same run fails at "pm session pm-test did not appear
     within 60s". The nominal flow is unchanged (rc 0, 3029-byte cast,
     `recorder.status` 0, 12-byte transcript, claim released).
   - **Step 2's claim could land on the grouped session.** The claim is read
     and written with `show-options`/`set-option`, which do *not* accept `=`
     (verified: "no such session: =pm-test", while `has-session` and
     `pipe-pane` do). A bare `$TARGET` therefore resolved to the grouped
     session while the target did not exist, and once the target exists exact
     match wins — so that claim is invisible, and two runs can claim one
     capture directory, the collision the claim exists to prevent. Step 2 now
     asserts `has-session -t "=$TARGET"` before it reads anything (refusing a
     target that is not an exact session, with a message naming the grouped
     session) and attaches the transcript pipe with `-t "=$TARGET:0.0"`;
     exact-match-wins then makes the plain `show-options`/`set-option` targets
     mean the session they name. Step 5's two witness checks and every
     best-effort pipe stop take the `=` too, so the witness answers for the
     session the run targeted. (R50 later corrected this bullet's own premise
     for the claim handles: a *bare* `=pm-test` is refused, but the
     `=pm-test:0.0` pane form they also accept is exact, and the plain forms
     are prefix-matched once the target has ended — so the read, the write and
     the releases all take the `=…:0.0` form now.) Tests: the stub `tmux` now
     resolves targets the way real tmux does (exact name, then prefix; `=`
     forced exact), which is what makes
     the two new execution cases meaningful — the whole capture block with only
     `pm-test~1` on the server must fail at the readiness wait (against `HEAD`
     it exits 0), and step 2 alone must refuse and leave no claim on
     `pm-test~1` (against `HEAD` it claims and pipes it). The text assertions
     that pinned the old bare target were updated to require the `=` form and
     to reject a bare `has-session -t "$TARGET"`.

R38. **A missing runtime is not a missing package.** One leftover in the kept
   recipe scope, the PR's own class (a remedy that cannot work), found by
   review loop 7c9c i9 and reproduced live. The web-UI driver block's only
   tools are `node` and (when it links) `ln`, and it checked `CAPDIR`,
   `APP_URL`, `driver.mjs` and the Playwright resolution — but never that the
   runtime exists. With a `PATH` that has no `node` (verified), the import
   check failed and the block printed "playwright does not resolve beside
   driver.mjs", offering the global link and `npm i playwright`: both need the
   runtime that is missing, so the worker repeats a remedy that cannot work —
   the shape R31 fixed for the `agg` install and R32 for the nested
   `node_modules`. It also created the `node_modules` link on the way. The
   block now stops with "node is not installed — driver.mjs runs under
   Node.js; install it …" after its `driver.mjs` check and before the link, so
   a run that cannot happen creates nothing, and the Tooling section names
   Node.js alongside Playwright, Chromium and `ffmpeg`. Verified: no `node` on
   `PATH` → rc 1 with that message and no link; with `node` → "playwright ok",
   the driver runs, rc 0 (nominal unchanged). Test:
   `test_web_ui_driver_block_names_a_missing_node` runs the block with a
   `PATH` holding the shell and its other external tools but no `node`, and
   requires that message, no "playwright does not resolve", and no
   `node_modules`; it fails against `HEAD`'s block.

R39. **The recorder's session handle is prefix-matched too.** One leftover in
   the kept tmux-recipe scope, the PR's own class (a handle that matches the
   wrong thing), found by review loop 7c9c i10 and reproduced live in this
   container on tmux 3.2a. R37 made the *target* handles exact but left every
   `pm-recorder` handle bare, and the tmux server this recipe runs on is pm's
   own server: pm names sessions `pm-<repo>-<hash>` (`paths.get_session_tag`),
   so a repo whose name starts with `recorder` has a session that a bare
   `pm-recorder` target prefix-matches (verified: with only
   `pm-recorder-abc123` on the server, `has-session -t pm-recorder` exits 0,
   `capture-pane -p -t pm-recorder` prints that session's pane,
   `send-keys -t pm-recorder` delivers into it, and
   `kill-session -t pm-recorder` kills it — and the last session taking the
   server down with it).
   - **Step 0's clear runs on every capture, when no exact recorder exists**,
     so `tmux kill-session -t pm-recorder 2>/dev/null || true` killed any
     session starting with the name — verified live with the recipe's own
     step-0 block: a `pm-recorder-abc123` session was gone afterwards, rc 0,
     no message. That is another project's pm TUI session, or this capture's
     own target session when the repo is named `recorder` (the session the
     scenario prepared is destroyed before step 1 recreates it). The clear
     now names `=pm-recorder`.
   - **With this run's recorder gone, a prefix session stood in for it.** The
     readiness check's `has-session -t pm-recorder` matched it, so its pane
     read as "the TUI drew"; the settle check matched it too; step 5 sent the
     detach key into it (`send-keys -t pm-recorder`) and, when it did not
     exit, the stop timeout killed it. Every recorder handle now takes the
     `=`: `has-session`/`kill-session` as `"=pm-recorder"`, and
     `capture-pane`/`send-keys` as `"=pm-recorder:0.0"` — those two commands
     answer "can't find pane" for `-t "=pm-recorder"` without an explicit
     pane spec (verified), while the pane form resolves.
   - **The attach was the one target handle R37 left bare.** The recorder pane
     runs `tmux attach -t $TARGET`; with the target session gone (it can die
     between step 2's exact-session check and the attach) a bare target lands
     on a grouped `<base>~N` session (verified: `attach -t pm-test` with only
     `pm-test~1` proceeds, while `-t '=pm-test'` answers "can't find
     session"). The run then records that session and reports success, with
     step 5's exact witness seeing only that the target ended. The attach now
     names `=$TARGET`, so it fails and the readiness check reports the
     recorder that never drew.
   Verified: the fixed step-0 block leaves a `pm-recorder-abc123` session
   alive; `has-session -t "=pm-recorder"` exits 1, and
   `capture-pane`/`send-keys -t "=pm-recorder:0.0"` fail, with only the prefix
   session present, while all four resolve on the real `pm-recorder`; and the
   nominal flow re-run end to end with real tmux 3.2a + asciinema 2.1.0 after
   the edit (rc 0, 3044-byte cast, `recorder.status` 0, 126-byte transcript,
   recorder gone, claim released). Tests:
   `test_tmux_session_handles_are_exact` (text: no bare recorder/target
   handle remains, every exact form is present),
   `test_step_zero_does_not_kill_a_pm_session_that_shares_the_prefix` (the
   whole block with a `pm-recorder-abc123` session must fail at the start
   check and leave that session alive), and
   `test_a_prefix_session_is_not_the_recorder` (a recorder that died while a
   `pm-recorder-abc` session exists must fail at "recorder exited before it
   drew" and leave it alive) — all three fail against `HEAD`'s recipe. The
   stub `tmux`'s `send-keys` now strips the pane spec before resolving the
   session, as `pipe-pane` already did and as real tmux does. Considered and
   rejected: the CLI recipe's `-t rec` on the recipe-private `-L scaffold`
   socket, where this recipe is the only creator of sessions and every one is
   named `rec`.

R40. **The gif is a stage boundary too.** One leftover in the kept
   recipe scope found by review loop 7c9c i11, the PR's own class (a failure
   that names the wrong stage), in both recording recipes' render blocks. The
   block checks its input at every stage — the cast before `agg`, the
   encoder's presence before the encode, the encoder's exit status, and the
   mp4 at the end (which is what catches a renderer that reports success and
   writes nothing, R12) — except between `agg` and `ffmpeg`. An `agg` that
   exits 0 without writing its output (or a 0-byte gif) therefore reached
   `ffmpeg` as a missing input and the run reported "render produced no mp4 —
   ffmpeg failed on the gif", sending the worker to inspect the encoder for a
   renderer that wrote nothing. Verified with both recipes' own render blocks
   and a stub `agg` that exits 0 without writing: both printed exactly that,
   with real `ffmpeg`'s "No such file or directory" above it. This is the
   misdiagnosis R19 fixed for a missing webm and R23 for a missing encoder,
   one stage over; the cast check one line above is the same rule applied
   earlier. Both blocks now check `[ -s "$cast.gif" ]` after the `agg` line
   and stop with "agg wrote no gif (the renderer reported success and wrote
   nothing)"; the `render_fail` helper removes the partial outputs as before.
   Tests: `test_render_names_a_renderer_that_writes_no_gif`, both recipes,
   with an `ffmpeg` stub that models the real contract (fails on a missing
   input) — both fail against `HEAD`'s blocks with the "ffmpeg failed on the
   gif" message and pass with the check. Evidence:
   `$(pm qa captures-path pr-b19db15)/review-7c9c-i11/` (`probe.log` with the
   pre/post runs of both recipes). No `pm_core/` change; the dropped
   helper/prompt/verifier work stays dropped.

R41. **The transcript pipe's target is a session handle too, and it was the
   one R37 left unasserted.** No recipe change — the pipe already names
   `"=$TARGET:0.0"` at all fourteen sites (R37). This is the *guarantee* that
   no test guarded, the same shape as R34's "the pipe-attach failure's claim
   release was the one path no case asserted": mutating every one of those
   fourteen handles to the bare `"$TARGET:0.0"` left the whole file green
   (177 passed), although a bare pipe target is exactly the bug the PR is
   about. Real tmux 3.2a, private server, only a grouped `pm-test~1` present
   (what pm leaves when the target ends, and the state step 2's exact-session
   assert and the pipe attach can straddle): `has-session -t "=pm-test"`
   exits 1 while `-t pm-test` exits 0, `pipe-pane -t "=pm-test:0.0"` answers
   "can't find session: pm-test" and exits 1, and
   `pipe-pane -t "pm-test:0.0"` attaches to `pm-test~1` and writes its output
   into the capture directory (65 bytes of `grouped-out` in the probe). A run
   whose target vanishes in that gap would then stream a session pm never
   started into this run's `transcript.log` and pass every later check —
   cast, status, transcript — exiting 0 on evidence that is not the target's
   (reproduced in the harness: the `pipegap` mode makes the same block exit
   **0** with a bare pipe target and 1 with the exact one). Tests: the text
   guard `test_tmux_session_handles_are_exact` now rejects a bare
   `pipe-pane -t "$TARGET` and requires the `=` form, and the execution case
   `test_the_transcript_pipe_targets_the_exact_session` runs the whole block
   in the new stub mode `pipegap` (the target session and its claim go as the
   claim is written, and a grouped `pm-test~1` is left) — it must fail at
   "could not stream …", write no transcript and leave no claim. Both fail
   against the bare form (mutation-checked with the recipe's own file
   restored afterwards). Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i1/` (`probe.log` with the
   live tmux probe and the mutation check, `scripts/` with the probe and the
   mutation driver). No `pm_core/` change; the dropped helper/prompt/verifier
   work stays dropped.

R42. **The stale-status clear was the one completion guard no test made, and
   the assertion that claimed to was satisfied by a comment.** One leftover in
   the kept recipe/test scope, the PR's own class (a completion check that
   cannot tell a finished recording from a dead one), found by review loop
   ebd1 i2. No recipe change: both recipes' step 0 already remove
   `recorder.status` (R2/R4), and the status is the handle that tells a
   recorder torn down underneath a live recording from one that finished. The
   guard was the hole.
   `test_tmux_scaffold_checks_asciinemas_own_exit_status` asserted
   `"recorder.status" in block[block.index("rm -f "):block.index("new-session -d")]`,
   and that range also holds step 1's comment "(verified live — rc 0, cast,
   `recorder.status` 0, transcript, with …)" — so the substring was satisfied
   by the comment. Deleting `<capture-dir>/recorder.status` from the step-0
   `rm` list left the whole file green (**178 passed**), and the false pass is
   real: stub `tmux`/`pm`, the recipe's own block, mode `detachnostatus` (the
   recorder draws, the detach ends it legitimately, no status is written) with
   an earlier run's `recorder.status` seeded as `0` — the recipe as shipped
   exits 1 at "recorder status is missing", the recipe with that one `rm`
   argument removed exits **0** with the stale file still on disk. A recording
   that never finished is reported as a completed one, which is exactly what
   the CLI's copy of the same assertion guards ("an earlier run's recorder
   status survives, so a torn-down recorder can pass the status check"). The
   CLI assertion was sound only because no comment in *its* range mentions the
   file — the same assertion, one comment away from being vacuous.
   Both tests now derive the status path from the pane command (the file the
   pane writes) and require the `rm` *statement* (`_statement(block, "rm -f ")`,
   the helper `test_capture_block_clears_a_stale_failure_log` already used) to
   remove it, so the write, the clear and the read are one name and a comment
   cannot satisfy the check. The new execution case
   `test_a_stale_recorder_status_is_not_read_as_this_runs` (both recipes; tmux
   mode `detachnostatus`, CLI mode `nostatus`, both of which end the recording
   legitimately so the run reaches the status check) seeds the earlier run's
   `0` and requires "recorder status is missing". All four new/tightened
   assertions fail against the pre-fix recipes — the two deletions above fail
   exactly those four cases and nothing else — and pass on the unmodified
   recipes; the file is 180 passed at this point (183 with R43's three
   cases). Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i2/` (`probe.log` sections
   A–F, `README.md`, `scripts/` with the two mutation sweeps, the
   status-clear deletion and the seeded-status probe). The sweep that found
   this one tried fifteen mutations of the kept recipe guarantees and caught
   thirteen (stop wait, cast check, mkdir check, settle check, claim scan,
   cross-session scan, stale sse.log/server.pid/mp4/webm, pid recording,
   step-1 target guard); the other uncaught one — dropping `--overwrite` from
   the CLI scaffold — is not a completion guard, because step 0 clears the
   cast first and without the flag a leftover cast makes `asciinema rec` abort
   loudly at the bounded readiness wait rather than pass. No `pm_core/`
   change; the dropped helper/prompt/verifier work stays dropped.

R43. **Three more guarantees the harness claimed but did not prove, and a
   comment that claimed a bound guard that did not exist.** Found by review
   loop ebd1 i2's audit of the test harness; no recipe change. Each of the
   PR's guarantees was *asserted*, but three of the assertions could not fail
   for the regression they name.
   - **The pane-save ordering was unprovable.** The stub `tmux`'s
     `capture-pane` ignored its `-t` and always printed `$STATE/pane`, and
     `kill-session` did not take the pane with it, so a recipe that saved the
     pane *after* its teardown still wrote content into
     `recorder-pane.log`. Real tmux (3.2a) answers "can't find session: …"
     once the recorder is killed — which is exactly why every failure path
     saves the pane before it tears the session down (R11/R13), and why the
     messages can name that file. The stub now resolves the target and fails
     when the session is gone; moving the stop-timeout and `send_failed`
     saves after their `kill-session` fails three cases
     (`test_tmux_stop_timeout_saves_the_pane`,
     `test_a_failed_send_tears_the_run_down` and the tmux
     `test_stop_block_pasted_alone_saves_the_pane`), where before it left the
     file green.
   - **The driver block's "the link lands in the worker's cwd" assertions
     proved a different check.** Both fixtures ran the block with no
     `driver.mjs` in the cwd, and since R32 the block checks for that file
     *before* it links Playwright — so with the `CAPDIR` guard removed the
     block stopped at "there is no driver.mjs" and never linked, and the
     `not lexists(work / "node_modules")` assertion could not fail. The
     fixtures now put a `driver.mjs` in the worker's cwd (the recipe's own
     misdiagnosis for this case is "saved in the workdir instead of the
     capture directory"); with the guard's `exit 1` removed both tests fail,
     and they pass with it.
   - **No test pinned a bound's value, or the number its message prints.**
     `_run_block` rewrites every `deadline=$(( … + N ))` to two seconds so the
     failing cases finish quickly, and its comment claimed "the recipes' own
     bounds are asserted as text above" — nothing asserted them. A readiness
     deadline retuned to 0 or 1 s would pass every test and then fail a
     healthy `pm session`/app start on a slow machine, and a message that says
     "within 30s" while the code waits 5 s sends the worker after a cause that
     is not there. The new
     `test_every_deadline_is_a_real_bound_and_its_message_agrees` requires
     every arithmetic bound to be at least 10 s and every "within Ns" a recipe
     prints to be one of the bounds it actually waits (tmux 60/30/30 and its
     three messages, the CLI 30, the web-UI 120), and the `_run_block` comment
     now says the value is pinned separately instead of claiming a guard.
   Tests: file 183 pass; each mutation above fails the cases it names and
   those cases pass on the unmodified recipes. Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i2/` (`probe.log` sections
   G–K, `README.md`). No `pm_core/` change; the dropped helper/prompt/verifier
   work stays dropped.

R44. **One more guard no test proved, and two files the produced-files list
   never named.** Found by review loop ebd1 i3.
   - **Step 1's empty-target guard had no case.** Steps 2, 4 and 5 each
     refuse an empty `$TARGET` and each refusal is execution-tested
     (`test_step_two_refuses_an_empty_target`,
     `test_tmux_driving_step_refuses_an_unresolvable_target`,
     `test_tmux_stop_block_refuses_an_unresolvable_target`), but step 1's
     identical guard — the one that runs before the readiness wait — was not.
     Deleting it left the whole file green: with `pm session name` printing
     nothing, the wait polls `has-session -t "="` (an exact match on the empty
     name, which can never succeed) to its deadline and reports "pm session
      did not appear within 60s" — a slow failure naming an empty session, for
     a `pm` that is not on PATH. `test_step_one_refuses_an_empty_target` runs
     the recipe's own block with `pm session name` printing nothing and
     requires the guard's message instead; it fails with the guard removed
     (verified: rc 1 with "pm session  did not appear within 60s").
   - **`server.pid` and `recording.webm` were missing from the web-UI
     produced-files list.** Step 1 writes `server.pid` into the capture
     directory and the teardown removes it, so it is present exactly when a
     run stopped before the teardown — a failed driver, which step 2 tells the
     worker not to finalize, is the ordinary case. `recording.webm` is kept
     deliberately when the transcode fails, so the step can be retried without
     re-driving the UI. The recipe's manifest section asks for "every file
     above" and the recording recipes' lists name their failure evidence
     (R17), so a worker following this list leaves both out of `## Files`
     while the capture directory holds them — the same "the manifest and the
     directory disagree" class, two files over. Both are now listed, each with
     when it survives and the instruction to mention it in the manifest;
     `test_web_ui_produced_files_list_names_the_files_a_failed_run_keeps`
     requires both (it fails against the pre-fix list).
   Tests: file 185 pass (two new cases); both fail against the pre-fix recipe
   (the guard removed in place, the list restored from `HEAD`, each then
   restored) and pass on the fixed one. No recipe behaviour change beyond the
   web-UI list; no `pm_core/` change; the dropped helper/prompt/verifier work
   stays dropped.

R45. **A manifest example that omits the files the run keeps, and two more
   guarantees no test proved.** Found by review loop ebd1 i4.
   - **The web-UI manifest's `## Files` example still omitted the two files
     R44 added to the produced-files list.** The list says to mention
     `server.pid` (present when a run stopped before the teardown) and
     `recording.webm` (kept when the transcode failed) when they survive, but
     the example a worker copies into the manifest named neither — and unlike
     the recording recipes' examples it has no `<any extra file>` catch-all —
     so the manifest and the capture directory disagree for exactly the two
     files R44 named. The sibling `node_modules` line is pinned in both the
     list and the example
     (`test_web_ui_produced_files_list_names_the_playwright_link`); both files
     are now in the example too, and
     `test_web_ui_produced_files_list_names_the_files_a_failed_run_keeps`
     requires them in the example's file list. That assertion reads the list
     from the indented `    ## Files` heading, not from the first `## Files`
     in the section: the manifest's `## Commands` line already mentions
     `recording.webm`, and the prose above the template mentions a "`## Files`
     section", so the first-match split passed with the example's line
     removed (verified).
   - **Step 2's "could not claim" guard had no case.** The exact-session
     assert above it can be stale by the time the claim is written; with the
     guard removed the step runs on and attaches the pipe anyway, and the
     failure then surfaces as "could not stream … — check that pane exists" —
     a pane that never existed, because it was the *session* that went away.
     The new stub mode `claimgone` ends the session as the claim is written;
     `test_a_claim_that_cannot_be_written_is_reported` requires the step's own
     message and not the pipe-attach one (it fails with the guard removed:
     rc 1 at "could not stream …").
   - **The cleanup order — pipe stop, then claim release — was unproven.**
     Step 5 releases the capture-directory claim last because a later run in
     the same session can take it the instant it is released and attach its
     own pipe, which this run's pipe stop would then close (the takeover the
     claim exists to stop). Moving the release above the pipe stop left the
     whole file green (185 passed): no case observes the order, because the
     stub's claim state is the same either way.
     `test_the_claim_is_released_only_after_the_pipe_is_stopped` pins it at
     every release — only the recorder kill may sit between this run's pipe
     stop and its claim release — with step 2's own failed attach (which has
     no pipe to stop) as the one exception.
   Tests: file 187 pass; each mutation above fails exactly the case it names
   (the guard removed in place; the release moved above the pipe stop; the
   example's `recording.webm` line deleted) and those cases pass on the
   unmodified files. Related suites (test_qa_artifact_web_ui_recording,
   test_qa_instructions, test_qa_loop, test_markdown_render) 375 together with
   the file; full suite `env -u PM_HOST_HOME PATH=/usr/bin:/bin pytest tests/
   -q --deselect tests/test_merge_publish.py --deselect
   tests/test_signoff_integration.py` -> 4581 passed, 1 skipped, 92
   deselected, 0 failed (395 s, with the `markdown` dep on the scratch path).
   No recipe behaviour change beyond the web-UI manifest example; no
   `pm_core/` change; the dropped helper/prompt/verifier work stays dropped.

R46. **Every stage-input check is `test -s`, but the cases only modelled
   "the file is absent", and the final mp4 check had no case at all.** Found
   by review loop ebd1 i5 with a mutation sweep over the kept recipe
   guarantees (each check weakened from `-s` to `-e`, plus the deletions):
   every one of them left the whole file green (187 passed). The `-s` *is*
   the check — each message names the empty state ("the recording wrote
   nothing", "or a 0-byte gif") — and the misdiagnosis it prevents is
   reachable, verified live in this container with the recipes' own blocks:
   - **The cast** (`[ -s "$cast" ]`): a 0-byte cast reached real agg 1.9.0,
     which answers "Error: empty file", and the block reported "render
     produced no mp4 — agg failed on the cast — is 'agg' installed?" — the
     misdiagnosis R12 fixed for a *missing* cast, one state over.
   - **The gif** (`[ -s "$cast.gif" ]`): a 0-byte gif reached real ffmpeg
     4.4.2, which answers "Invalid data found when processing input", and the
     block reported "ffmpeg failed on the gif" — R40's misdiagnosis.
   - **The webm** (`[ -s "$CAPDIR/recording.webm" ]`): a 0-byte webm reached
     real ffmpeg ("EBML header parsing failed … Invalid data found when
     processing input"), and the finalize step reported "transcode produced no
     mp4 — ffmpeg failed on the driver's webm" — R19's misdiagnosis.
   - **The mp4** (the final `test -s` in both recording recipes): no case
     existed; deleting it left the file green, and the false success is real —
     a stub `ffmpeg` that exits 0 after creating its output leaves a
     **0-byte** `recording.mp4` and the block exits **0**, which the manifest
     and the report present as this run's recording. That is the "renderer
     reports success and writes nothing" case R12's last check exists for, and
     the recording recipes' counterpart of the web-UI
     `test_web_ui_transcode_that_writes_nothing_leaves_no_mp4`.
   Fix: the no-cast, no-gif and no-webm cases are parametrized over "no file"
   and "0-byte file", with the `ffmpeg` stub modelling real ffmpeg's contract
   for a missing *and* an empty input (the old stub wrote its output
   unconditionally, which hid the empty-file shape), and the new
   `test_render_names_an_encoder_that_writes_no_mp4` covers the final check in
   both recipes. The same sweep found the CLI recipe's *preamble* (the "before
   any of the forms below" block) was never executed by any case — only the
   scaffold's copy of the `mkdir` guard was — so weakening the preamble's
   guard to `|| true` also left the file green; the new
   `test_cli_preamble_refuses_an_uncreatable_capture_dir` runs that block.
   The sweep's other survivors are benign by design and are recorded here
   rather than "fixed": dropping `--overwrite` (step 0 clears the cast, so a
   leftover one aborts loudly at the bounded readiness wait), the final
   `kill-session` after the stop wait (the wait only ends once the session is
   gone), a bare `capture-pane` in the readiness check (it runs only after
   `has-session -t "=pm-recorder"` passed, and exact match wins), the CLI
   readiness wait's `-s` (step 4 checks the cast again), `-e` for `-f` on
   `driver.mjs` (a directory of that name is not a real state), and the CLI's
   `kill-server` cleanup calls (a leftover empty server is harmless, and the
   shared-socket collision is the documented limitation of R27/R34).
   No recipe change; no `pm_core/` change; the dropped helper/prompt/verifier
   work stays dropped.

R47. **The manifest is a produced file too, and it was the one step 0 never
   cleared.** Found by review loop ebd1 i6. All three recipes list
   `manifest.md` among the files they produce — it is the document that says
   what the capture *is* (workdir, the commands, the `## Files` list) — and
   every other produced artifact is removed before a run starts. The manifest
   was not: verified with each recipe's own step-0 clear run verbatim over a
   directory seeded with every produced artifact, `manifest.md` is the only
   one that survives (`driver.mjs` in the web-UI recipe is the other survivor,
   and deliberately so: it is the run's *input*, not its evidence, and a retry
   drives the same one). The consequence is the class the rest of step 0
   exists for, one level up: a re-run in the same capture directory starts
   with the previous run's manifest in place, and a run that fails before the
   worker writes a new one — the ordinary shape of a failed capture — leaves
   that manifest describing a different run, with a `## Files` section naming
   the cast, the transcript and the mp4 that step 0 just deleted. Verified
   end to end with the recipes' own capture blocks (a failed recorder start,
   the previous `manifest.md` and `recording.mp4` seeded): the mp4 goes and
   the manifest stays, naming two files that no longer exist. The manifest
   disagreeing with the directory is worse evidence than none, because the
   manifest is what a reviewer (and the report) reads to interpret the rest.
   Fix: `manifest.md` joins each step-0 clear — the tmux recipe's, the CLI
   preamble's and its scaffold's (each is pasted on its own), and the web-UI
   step-1 cleanup — with the reason written out at each site and named in the
   produced-files lists. Also corrected, same pass: `qa.md` R3 said the
   readiness/stop waits "clean up (kills the recorder/session)", which is
   false for the CLI stop timeout — R21/R27 deliberately leave the recording
   running so the larger-bound re-run its message prescribes can be applied,
   and the recipe's own edge case says so; R3 now says which failure tears
   down what. Tests:
   `test_capture_section_clears_the_previous_manifest` (both recording
   recipes, first block and scaffold), `test_a_failed_capture_leaves_no_previous_manifest`
   (both recipes, executed with a seeded manifest and a failing capture), and
   `test_web_ui_start_clears_a_previous_manifest` (executed start block); the
   web-UI step-1 text case also requires `manifest.md` in its clear. All six
   (the five new cases plus the tightened web-UI cleanup case) fail against
   the pre-fix recipes (checked by restoring them in place, then restoring the
   post-fix copies) and pass on the unmodified ones. The nominal flows are
   unaffected — re-run live in this container after the edit with real tmux
   3.2a + asciinema 2.1.0: the tmux recipe rc 0 (a ~3 KB cast,
   `recorder.status` 0, 35-byte transcript, previous manifest and mp4 gone,
   no recorder left) and the CLI scaffold rc 0 (a 162-byte cast holding the
   recorded command, status 0, previous manifest and mp4 gone). No `pm_core/`
   change; the dropped helper/prompt/verifier work stays dropped.

R48. **The web-UI port pre-check's bound is load-bearing, and the driver
   retry's cleanup missed the manifest.** Two leftovers of the PR's own class
   found by review loop ebd1 i7 — one an unproven guarantee (a mutation sweep
   over 39 weakenings of the kept recipe scope left it green), one a stale
   artifact the flow keeps:
   - **The pre-check's per-attempt bounds were pinned by nothing.** Step 1's
     port pre-check carries `--connect-timeout 2 --max-time 5`, and those
     flags are what make R27's fix reachable: curl has no default deadline
     for a server that accepted the connection and never answers, so an
     unbounded probe blocks the step instead of answering 28 and the "could
     not check … exit 28" branch never fires. Verified live in this container
     against a socket that accepts and never replies: the shipped probe exits
     1 in **5.0 s** with "could not check … (exit 28; only 'connection
     refused', 7, means the port is free) …", while the same block with the
     flags removed is still **blocked in curl at 20 s** — the unbounded wait
     this PR removes everywhere else, in the block every capture runs first.
     No case could see it: the stub `curl` answers 28 by mode whatever its
     arguments, so deleting the flags left the whole file green (200 passed).
     The stub now logs each call's argv and
     `test_the_port_pre_check_is_bounded` requires the first call (the
     pre-check) to carry both bounds; it fails with the flags removed. The
     pre-check's comment now says why they cannot be dropped.
   - **The driver block's attempt cleanup left the manifest.** Step 2 is
     pasted on its own when a driver is adapted and retried, and its cleanup
     clears this attempt's mp4, webm, trace, DOM dump and screenshots — but
     not `manifest.md`, the document that *presents* them. An attempt that
     already reached the finalize step leaves a manifest whose `## Files`
     names `recording.mp4`; a retry then deletes the video and, if it fails,
     ends with a manifest describing files that are gone — the exact
     disagreement R47 cleared step 1 and the recording recipes' step 0 for,
     in the one block R47 did not touch. Verified with the recipe's own block
     and a driver that throws: the pre-fix block exits 1 leaving only
     `driver.mjs`, `node_modules` and the earlier attempt's `manifest.md`
     (its `## Files` naming the deleted mp4); with `./manifest.md` in the
     cleanup the directory holds only the run's input and the link.
     `test_web_ui_driver_failure_is_reported_and_clears_stale_outputs` seeds
     the manifest with the other stale outputs and requires it gone (it fails
     against the pre-fix block).
   The sweep's other survivors are benign and recorded here rather than
   "fixed": step 5's `test -s` on the cast weakened to `-e` (asciinema 2.1.0
   writes its 115-byte header the moment recording starts — verified with
   `-c 'sleep 3'` and `-c 'true'` — so a 0-byte cast is not a reachable state,
   and a killed recorder is caught by the status check), the readiness
   timeout's `kill-session` on the tmux recorder (the next run's step 0 clears
   it), the CLI's `kill-server` cleanups (a leftover empty server is harmless,
   and the shared-socket collision is R27/R34's documented limitation),
   `--overwrite` (step 0 clears the cast, so a leftover one aborts loudly),
   the `10#` on the CLI stop bound (a leading zero is not a state a worker
   types), and the `~/` alternative in the path guard (a stricter guard would
   refuse a spelling the prose accepts; no reachable false pass). No
   `pm_core/` change; the dropped helper/prompt/verifier work stays dropped.

R49. **Three guards the recipes carry had no case.** Found by review loop ebd1
   i8, all in the kept recipe scope and all the PR's own class (a step acting
   on a path it has not validated, a canonicalization the prose claims but
   nothing exercises, and a cleanup whose order a failure message depends on).
   No recipe change: the guards are correct, the coverage was missing.
   - **The CLI preamble's absolute-path guard.** `cli-recording.md` opens the
     Capture section with a block that creates and clears the capture
     directory "before any of the forms below" (the paste a worker following
     the recipe top-down makes), and that block carries its own copy of the
     `case "<capture-dir>" in /* | "~"/*` guard. The scaffold's copy is
     execution-tested (`test_capture_dir_must_be_absolute`) and the
     preamble's `mkdir` guard is (`test_cli_preamble_refuses_an_uncreatable_capture_dir`),
     but nothing ran the *preamble* with a relative path: deleting its `case`
     guard left the whole file green (**201 passed**, the count before these
     cases existed — verified by mutating the recipe in place and restoring
     it), and the preamble then exited **0**
     with `relcap/run` created (and its `rm` run) in the worker's cwd — the
     exact "writes where the checks never look" state the guard exists for,
     in the block that precedes every recording form. The scaffold's own
     copy refuses the path, but only after the preamble has already written
     into it.
   - **Step 2's `pwd -P` canonicalization.** The claim comparison is
     `claim_dir=$(cd <capture-dir> && pwd -P)`, and the prose claims `pwd -P`
     "collapses a trailing slash and a symlinked path". The `~/` spelling had
     a case (`test_a_shared_dir_is_recognized_through_a_tilde_spelling` /
     `test_a_retry_is_not_refused_by_its_own_tilde_claim`); the symlink half
     did not. Replacing all three code sites (`claim_dir`, the stored claim's
     `claimed_dir`, the scan's `vd`) with plain `pwd` also left the file green
     (**201 passed**, the same pre-fix count). The state it prevents is real: a second session that
     reaches one capture directory through a symlink while the claim stores
     the real path is not refused, and both runs write the same cast, status
     and transcript; the mirror case refuses a retry that is not a collision.
   - **Step 1's cleanup runs before the port pre-check.** The web-UI start
     block clears the previous run's outputs (mp4, webm, trace, screenshots,
     `server.pid`, `manifest.md`) and then probes the port; the busy-port
     refusal says "Its pid is no longer in server.pid (this step cleared it)".
     The cleanup's *list* is pinned as text
     (`test_web_ui_clears_a_previous_video`), but nothing observed the refusal
     path: moving the whole `rm` below the pre-check left the file green
     (**204 passed**, the count before this case). A start refused
     for a busy port then leaves the previous run's `server.pid` — the handle
     the recipe's own teardown reads — so a worker who runs the teardown next
     signals whatever process has since reused that pid, while the message
     that sent them there says the file is gone. The success path cannot see
     this: its own `printf` overwrites the pid.
   Fix: four execution cases, all against the recipes' own blocks —
   `test_cli_preamble_refuses_a_relative_capture_dir` (preamble, relative
   path: rc non-zero, "must be an absolute path", nothing created),
   `test_a_shared_dir_is_recognized_through_a_symlink` (whole tmux block,
   capture dir reached through a symlink, another session's claim on the real
   path: refused naming that session),
   `test_a_retry_is_not_refused_through_a_symlink` (the same session's claim
   on the real path, step pasted with the symlinked one: proceeds) and
   `test_a_refused_start_clears_the_previous_pid` (web-UI start block, stale
   `server.pid` seeded, port already answering: refused and the pid file is
   gone). Each fails against its mutated recipe and passes on the unmodified
   one; file **205 passed** (was 201). Also corrected, same pass: `qa.md`'s
   edge-case list for the driver step still enumerated the attempt cleanup
   without `manifest.md`, which R48 added to that `rm` — the document
   disagreed with the block it describes, the class R47/R48 exist for.

R50. **The capture-directory claim's own handles were the last bare session
   targets, and the write's guard could not fire.** Found by review loop ebd1
   i9, in the kept tmux-recipe scope, the PR's own class (a handle that
   matches the wrong thing). Step 2 asserts the exact target, then reads,
   writes and releases `@pm_capture_dir` with a plain `-t "$TARGET"`, on the
   strength of the comment's claim that `show-options`/`set-option` cannot
   take `=` and that "exact-match-wins" makes the plain target mean the
   session. The first half is only true of the *bare* form: the `=pm-test:0.0`
   pane form is accepted and exact (verified on tmux 3.2a on a private
   `TMUX_TMPDIR` — `show-options`/`set-option -t '=pm-test:0.0'` round-trip on
   the real session and answer "no such session" with only `pm-test~1` on the
   server), and the second half fails exactly when the exact session is gone,
   which is the case the write's guard exists for.
   - **The write.** With the target ended between the assert and the write and
     pm's grouped `pm-test~1` left behind, a plain
     `set-option -t pm-test @pm_capture_dir <cap>` exits **0** and writes the
     option on the grouped session (verified live with the recipe's own step-2
     block: the probe log shows the claim on `pm-test~1` right after the
     call). The "could not claim … the session went away" guard therefore
     never fires, the run goes on with its claim where the exact read above
     can never see it (the collision guard silently off), and the pipe attach
     then fails as "could not stream … — check that pane exists" — a pane
     named for a session that went away, the misdiagnosis R45's `claimgone`
     case exists to prevent, in the shape where a grouped session is present.
     The stub modelled only the other shape (`claimgone`: nothing matches the
     prefix, so even a bare write fails).
   - **The read and the release.** The same prefix match makes the read take a
     grouped session's claim for this session's, and makes the release — a
     best-effort no-op once the target has ended — clear a grouped session's
     option instead. The step-5 comment stated the opposite ("a release
     against a session that is gone is a no-op").
   Fix: every claim handle takes `"=$TARGET:0.0"` — the read, the write and
   all fourteen releases — so the write fails with "no such session" exactly
   when the target is gone (the guard fires with the right message and nothing
   is written to the grouped session) and the release is the no-op it claims
   to be. The `:0.0` spec only makes the target exact — tmux resolves the
   session part and does not require that pane to exist (verified with a
   session whose window 0 was killed: `set-option`, `show-options` and
   `set-option -u` all succeed), so the handles add no failure mode the
   recipe's `pipe-pane -t "=$TARGET:0.0"` does not already have.
   The step-2 and step-5 comments now say why, and name the verified
   facts. The stub `tmux` strips the pane spec for `show-options`/`set-option`
   the way it already did for the pane-target commands, and gains the
   `claimgap` mode (the target ends at the write, a grouped session is left,
   which a bare write succeeds against).
   Case: `test_a_claim_written_to_a_prefix_session_is_reported` runs the whole
   block in `claimgap` with another run's claim seeded on `pm-test~1`; it
   requires "could not claim", not "could not stream" and not "already being
   recorded", and the grouped session's claim unchanged. With every claim
   handle reverted to the bare form it fails on exactly that (rc 1,
   "could not stream … — check that pane exists"), and
   `test_tmux_session_handles_are_exact` now also rejects the three bare forms
   and requires the three exact ones; `test_the_claim_is_released_only_after_
   the_pipe_is_stopped` follows the new release spelling. Nominal flow re-run
   live with real tmux 3.2a and the recipe's own step 2: rc 0, the claim on
   the target and not on the grouped session beside it. File **206 passed**
   (was 205).

R51. **The driver block's "is the driver here" check accepted an empty
   driver.** Found by review loop ebd1 i10, in the kept web-UI-recipe scope,
   the PR's own class (a completion check that cannot tell a real input from a
   dead one, and a failure whose prescribed remedy cannot work).
   `web-ui-recording.md` step 2 checked `[ -f driver.mjs ]` before running
   `node driver.mjs`. That is the only stage-input check in this PR that is
   not `-s`: R46 established the rule for the render/finalize inputs (an
   artifact that exists but is empty is not an input the next stage can use)
   and R32/i4 fixed the *missing* `driver.mjs`, but the **0-byte** file was
   never modelled, by the block or by a case. It is not benign: an empty file
   is a valid ES module, so `node driver.mjs` exits **0** having run nothing
   (verified with node 22 in this container), the driver block prints
   "playwright ok" and exits 0 — a step reported as success that did nothing —
   and the finalize step then fails with "there is no webm to transcode — the
   driver wrote no video; re-run step 2 and check the driver's recordVideo
   option": a remedy that cannot work, because step 2 passes again and
   `recordVideo` was never the problem. Reproduced end to end with the
   recipe's own two fenced blocks and an empty `driver.mjs`: step 2 rc **0**
   with "playwright ok", step 3 rc 1 with that message.
   Fix: the check is `[ -s driver.mjs ]` and its message says the file is
   empty as well as missing ("there is no driver.mjs in $CAPDIR (or it is
   empty)"), with the reason written out at the site. No other input check in
   the three recipes needed the change — every other one is already `-s`, and
   `-d`/`-e` are used only for the capture directory and the `node_modules`
   link, where emptiness is not a state.
   Case: `test_web_ui_driver_block_refuses_a_missing_driver` is parametrized
   over "no file" and "0-byte file" (the shape R46 used for the cast/gif/webm
   checks). The 0-byte case fails against the pre-fix block — verified by
   restoring `-f` in place: rc **0** with "playwright ok" and no message —
   and both shapes pass with `-s`. File **207 passed** (was 206).

R52. **The `agg` install guard answered a binary that does not run.** Found by
   review loop ebd1 i11, in the kept render-step scope, the PR's own class (a
   remedy that runs but cannot work, in a loop). R10/R16 gave both recording
   recipes an `agg` install block guarded on `command -v agg`, and R31 made it
   stop when the binary it wrote does not *resolve*. The guard tests
   resolvability, not execution: a **truncated** `agg` — the exact file R16
   and the block's own comment record ("a dropped transfer replaced a working
   agg with a 500-byte file") — still resolves, so the block does nothing. The
   render then fails with "render produced no mp4 — agg failed on the cast —
   is 'agg' installed?", whose only remedy is that same block: pasting it
   again is another no-op, and the worker loops. A download the worker
   interrupted (Ctrl-C, a supervisor timeout) leaves that file without ever
   reaching the block's `rm -f`, so the state is reachable, not theoretical.
   Verified in this container with the recipes' own extracted blocks and a
   500-byte truncation of the real agg 1.9.0 release binary in
   `~/.local/bin` (ahead on PATH): pre-fix install rc **0** with the file
   unchanged, render rc 1 with "… is 'agg' installed?", install again rc **0**
   with the file still 500 bytes; post-fix install replaces it with the real
   binary and the render exits 0 with a playable H.264 mp4
   (`ffprobe`: `h264,1580,1120`). Fix: the guard is `agg --version`, which a
   working agg answers 0 (verified with agg 1.9.0) and a truncated or
   wrong-architecture binary fails to execute (rc 126), so R16's protection
   holds — verified: the fixed block leaves a working agg untouched (same
   mtime and size) — and the truncated one is replaced. A download that
   itself arrives broken (truncated, or for another architecture) resolves
   and still fails to execute, so the post-install check now names the binary
   to remove and stops instead of exiting 0 with the render's question
   unchanged — the same loop one shape further in. Both recipes' prose said
   to install `agg` "when `command -v agg` prints nothing" and now says when
   `agg --version` fails. Cases: `test_renderer_install_replaces_an_agg_that_does_not_run`
   (a resolvable, non-running agg must be downloaded over; the pre-fix block
   skips it) and `test_renderer_install_names_an_agg_that_still_does_not_run`
   (a download that leaves such a binary must stop naming it; the pre-fix
   block exits 0), plus the static guard assertion in
   `test_render_documents_how_to_get_the_renderer` and an `agg_body` knob on
   `_run_install_block` to seed the truncated binary. All six fail against
   `HEAD`'s recipes (checked by restoring them in place, then restoring the
   post-fix copies). File **211 passed** (was 207); full suite
   `env -u PM_HOST_HOME PATH=/usr/bin:/bin pytest tests/ -q --deselect
   tests/test_merge_publish.py --deselect tests/test_signoff_integration.py`
   -> **4605 passed, 1 skipped, 92 deselected, 0 failed** (403.39 s, with
   the pytest 8.4.2 and markdown deps on the scratch path).

R53. **The driver retry's attempt cleanup left the Layer 2 protocol logs.**
   Found by review loop ebd1 i12, in the kept web-UI-recipe scope, the PR's
   own class (stale evidence presented as this run's) — the same shape R47/R48
   fixed for the manifest, in the last two files that cleanup does not take.
   Step 2 is pasted on its own when a driver is adapted and retried, and its
   cleanup clears this attempt's mp4, `*.webm`, trace, DOM dump, screenshots
   and manifest. An attempt that already reached the Layer 2 protocol block
   leaves `http.log` and `sse.log` beside them, and the manifest's `## Files`
   names both as this capture's evidence. The retry drives the UI again, but
   the protocol layer is *supplementary* — the recipe calls it that and a
   worker may not re-run it — so a retried capture presents the earlier
   attempt's route snapshots and event stream as this run's. Step 1 clears
   them for a fresh run for exactly that reason ("a run that never re-captures
   the protocol would otherwise present the earlier run's http.log and sse.log
   as this run's evidence"); the step-2-only retry was the one path that did
   not. Verified with the recipe's own block and a driver that throws: with
   `http.log`/`sse.log` seeded beside the other stale outputs, the pre-fix
   block exits 1 leaving both files in the capture directory; with them in the
   cleanup the directory holds only the run's input (`driver.mjs`) and the
   `node_modules` link. Fix: `./http.log ./sse.log` join step 2's cleanup,
   with the reason written out beside the manifest's. Also corrected, same
   pass: the test module's docstring still described the `agg` install as
   "guarded on `command -v agg`" — the pre-R52 state that i11 replaced — so a
   reader would have reintroduced the inert-remedy bug R52 exists to prevent
   (the two per-test docstrings and the recipes were updated in i11; the
   module header was missed). And the tmux recipe's step-2 comment claimed
   "every claim handle below takes" the exact `=…:0.0` form; the cross-session
   scan is the one claim handle that keeps a bare `-t "$s"`, and that is
   correct there (the names come from `list-sessions`, so exact match wins,
   and a grouped `<base>~N` session carries no claim of its own) — the comment
   now says so instead of overstating the rule. Tests:
   `test_web_ui_driver_failure_is_reported_and_clears_stale_outputs` seeds the
   two logs with the earlier attempt's other outputs and requires them gone
   (it fails against the pre-fix block, which leaves both); file 211 passed
   (unchanged count — the case is extended, not added). Full suite
   `env -u PM_HOST_HOME PATH=/usr/bin:/bin pytest tests/ -q --deselect
   tests/test_merge_publish.py --deselect tests/test_signoff_integration.py`
   -> **4605 passed, 1 skipped, 92 deselected, 0 failed** (410.20 s, with the
   pytest 8.4.2 and markdown deps on the scratch path). Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i12/` (`probe.log`,
   `suite.log`, `README.md`, `scripts/`). No `pm_core/` change; the dropped
   helper/prompt/verifier work stays dropped.

R54. **`mkdir -p` answers 0 for a capture directory that cannot be written.**
   Found by review loop ebd1 i13, in the kept recipe scope, the PR's own class
   (a step that cannot do its job must say so where it fails, instead of
   failing later as something else and naming evidence that cannot exist).
   Both recipes guard the capture directory by creating it — `mkdir -p … ||`
   refuses a path that cannot be created, and the comment beside it promises
   that "every later step writes into it, and their failures read as something
   else". A directory that already exists and cannot be written is that state
   one shape over, and `mkdir -p` answers **0** for it, so the creation guard
   passes. Every write into it then fails in a *pane's* shell rather than in
   the step: the transcript pipe's `cat >>` and the recorder's `2>` and
   `echo $? >` redirects cannot be opened, so the recorder dies before it
   draws and the run ends with "recorder exited before it drew — see the cast
   and <capture-dir>/recorder-stderr.log", naming a cast and a stderr log that
   cannot exist. Verified live in this container on tmux 3.2a with a mode-500
   capture directory and the recipes' own blocks extracted verbatim: the
   pre-fix tmux block exits 1 with that message and the directory stays empty
   (no cast, no stderr log, no status, no transcript), and the pre-fix CLI
   scaffold exits 1 with "asciinema wrote no cast — see
   …/recorder-stderr.log", again for a file that cannot exist. Step 2 pasted
   on its own — the recipe's "re-attach the transcript" paste — is the same
   hole for a path that is not there at all: it exited 0 with the claim on the
   session and no transcript written, and left the claim for the next attempt
   to clear by hand. Fix: both recipes' capture-directory steps check that the
   directory is writable and enterable (`[ -w … ] && [ -x … ]`) and stop with
   "capture directory … cannot be written — check the path and its
   permissions" — the tmux recipe in step 0 (before the shared `pm-recorder`
   clear, so a block refused for its path still makes no tmux call, R34/R36)
   and in step 2 (the paste-alone case, before the claim is taken); the CLI
   recipe in the preamble and in the scaffold (before the shared `rec` clear).
   The `claim_dir` fallback's comment now says it covers only a directory that
   disappears between the guard and the `cd`. Tests:
   `test_step_two_refuses_a_capture_dir_it_cannot_write` (both shapes,
   missing and mode-500: no claim, no pipe), and
   `test_a_capture_dir_that_cannot_be_written_stops_the_run` (both recipes;
   the refused block must make **no** tmux call at all), and
   `test_cli_preamble_refuses_a_capture_dir_it_cannot_write`; the permission
   shapes skip under root, which can write a mode-500 directory. All five fail
   against the pre-fix recipes. Two guards that had no case are covered in the
   same pass: `test_cli_recorder_that_never_writes_a_cast_fails` now requires
   the CLI readiness timeout's `recorder-pane.log` to exist and hold what the
   recorder drew (only the message text was pinned — deleting the
   `capture-pane` line left the file green at 211 passed, and the message then
   named a file nothing writes), and `test_a_tilde_capture_dir_is_accepted`
   runs the tmux step-0 block and the CLI preamble with `~/cap` (both guards
   accept `~/` and the prose says so, but every case used an absolute path, so
   narrowing the pattern to `/*` left the file green and refused a
   documented-valid path). File **218 passed** (was 211). Full suite
   `env -u PM_HOST_HOME PATH=/usr/bin:/bin pytest tests/ -q --deselect
   tests/test_merge_publish.py --deselect tests/test_signoff_integration.py`
   -> **4612 passed, 1 skipped, 92 deselected, 0 failed** (401.91 s, with
   the pytest 8.4.2 and markdown deps on the scratch path). Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i13/`
   (`probe.log`, `mutation-check.log`, `suite.log`, `README.md`, `scripts/`).
   No `pm_core/` change; the dropped helper/prompt/verifier work stays dropped.

R55. **The web-UI recipe's capture directory was never checked for
   writability.** Found by review loop ebd1 i14, in the kept web-UI-recipe
   scope, the PR's own class (a step that cannot do its job must say so where
   it fails) — and the one recipe R54 did not reach. Step 1 guards the
   directory by creating it (`mkdir -p … ||`), and the comment beside that
   guard promises to stop the run because "several of them report success
   while writing nothing when it is not there"; a directory that exists and
   cannot be written is that state one shape over, and `mkdir -p` answers
   **0** for it. Verified live in this container with a mode-500 capture
   directory and the recipe's own fenced blocks extracted verbatim:
   - step 1 exits **0**, starts the app, writes no `server.pid` and leaves the
     previous run's `recording.mp4`, `recording.webm`, `manifest.md` and
     screenshots in place — the clear that exists to remove stale evidence
     never ran, and the teardown later refuses for a missing pid;
   - step 2's driver block exits 1 with "playwright does not resolve beside
     driver.mjs — … link the global install" after `ln` printed "Permission
     denied": a remedy that cannot work, the shape R31/R32 fixed for the
     `agg` install and the nested `node_modules`;
   - step 3's finalize block exits 1 with "transcode produced no mp4 — ffmpeg
     failed on the driver's webm", blaming the encoder and the recording;
   - the Layer 2 block exits **0** having written neither `http.log` nor
     `sse.log` — the "a run with no protocol capture reads as success"
     failure its own guard comment describes, which its `[ -d "$CAPDIR" ]`
     check cannot see because the directory is there.
   Fix: all four blocks require the directory to be writable and enterable
   (`[ -w … ] && [ -x … ]`) and stop with "capture directory … cannot be
   written — … check the path and its permissions", matching R54's wording —
   step 1 right after its `mkdir` guard (before the stale clear, so a refused
   block writes nothing) and the three paste-alone blocks after their existing
   `[ ! -d ]` check. Tests: four new execution cases, each of which fails
   against the pre-fix recipe (verified with the pre-fix recipe restored in
   place):
   `test_an_unwritable_capture_dir_stops_the_start` (the block refuses before
   launching the app; `_run_web_ui_start` gains a `capdir_mode` knob) and
   `test_web_ui_{driver,finalize,layer2}_block_refuses_a_capture_dir_it_cannot_write`
   (the driver case also requires that the Playwright remedy is *not* what the
   worker sees, and the Layer 2 case is the one whose pre-fix run exits 0).
   File **222 passed** (was 218). The permission shapes skip under root,
   which can write a mode-500 directory.

R56. **Step 2's pipe runs in the pm session's directory, so a relative
   `<capture-dir>` puts the transcript where step 5 never looks.** Found by
   review loop ebd1 i15, in the kept tmux-recipe scope, the PR's own class (a
   step that cannot do its job must say so where it fails — and a path that
   resolves against a different directory than the one the step checked).
   Step 0 refuses a relative `<capture-dir>` because tmux runs the transcript
   pipe's command in the pm session's directory, and step 2 is pasted on its
   own when a run re-attaches its transcript — its own comment says so, and it
   carries its own `$TARGET` re-derivation and directory guards for that
   reason — but it had no path guard. A relative path that exists beside the
   worker passed the writability check, the claim was taken on the worker's
   *canonical* absolute path, and the pipe's command then ran in the session's
   directory. Verified live on tmux 3.2a with the recipe's own step-2 block
   extracted verbatim and a stub `tmux` that runs `pipe-pane` commands in the
   session's cwd: the pre-fix block exits **0**, writes the claim
   `…/worker/relcap`, and the session's shell answers "cannot create
   relcap/transcript.log: Directory nonexistent" — so the run has no
   transcript anywhere and step 5 reports "transcript.log is empty — the
   pipe-pane stream never wrote to it" for a pipe that never had a writable
   target, the exact failure step 0's guard exists to prevent. Fix: step 2
   carries step 0's `case` guard (`/* | "~"/*`) before the claim, with a
   message that names the pipe's directory. Tests:
   `test_step_two_refuses_a_relative_capture_dir` runs step 2 alone from a
   worker directory holding `relcap` and requires the refusal, no claim and no
   pipe attach (the pre-fix block exits 0 with the claim on the canonical
   path). File **223 passed** (was 222). Steps 4 and 5 and the render blocks
   were checked and dismissed: their only capture-dir uses are worker-side
   redirects and reads, which resolve in the worker's own shell and so agree
   with themselves; the mismatch was unique to step 2's tmux-side pipe.
   `qa.md`'s "both recording
   recipes … refuse a relative `<capture-dir>`" is now true of the
   paste-alone step as well.

R57. **The render blocks write into the capture directory without checking it
   is there and writable.** Found by review loop ebd1 i16, in the kept recipe
   scope, the PR's own class (a step that cannot do its job must say so where
   it fails — and a remedy that runs but cannot work). R54/R55 gave the
   capture steps and the web-UI finalize/driver/Layer 2 blocks a
   missing/unwritable capture-directory guard; the two recording recipes'
   render blocks are the remaining blocks that *write* into that directory
   (the intermediate gif and the mp4) and had neither check. Verified live in
   this container with real agg 1.9.0 and ffmpeg 4.4.2 and the recipes' own
   render blocks extracted verbatim:
   - a mode-500 capture directory holding a cast: `rm -f` fails silently (the
     earlier run's `recording.mp4` survives), `agg` cannot create its gif, and
     the block exits 1 with "render produced no mp4 — agg failed on the cast —
     is 'agg' installed?" — a remedy that cannot work, because agg is
     installed and the directory is the problem. The install block the message
     sends the worker to is guarded on `agg --version` and exits 0 without
     changing anything (verified), so the worker loops;
   - a capture directory that does not exist: the cast check reports "there is
     no cast to render (the recording wrote nothing)" for a path that is
     simply not there — the shape the web-UI finalize's missing-directory
     guard exists for (R21).
   Fix: both render blocks derive the cast's directory (`cast_dir=${cast%/*}`,
   which is `<capture-dir>` in the tmux recipe and `<capture-dir>/<short-name>`
   in the CLI one) and stop with "capture directory … does not exist — create
   it and run the capture step first" or "capture directory … cannot be
   written — the render writes the mp4 and the intermediate gif there; check
   the path and its permissions", before the `rm` (so a refused block leaves
   the earlier run's outputs alone). Tests:
   `test_render_refuses_a_capture_dir_it_cannot_write` (both recipes; the
   refusal must name the directory and must not be the "is 'agg' installed"
   message; the permission shape skips under root) and
   `test_render_names_a_missing_capture_dir` (both recipes; must say the
   directory does not exist and not "the recording wrote nothing");
   `_run_render` gains `capture`, `capdir_mode` and `create_capture_dir`
   knobs. All four cases fail against the pre-fix recipes (verified with
   HEAD's render blocks restored in place). File **227 passed** (was 223).
   Healthy render re-verified live after the fix: rc 0, ffprobe
   `h264,1580,1120`. Full suite `env -u PM_HOST_HOME PATH=/usr/bin:/bin
   pytest tests/ -q --deselect tests/test_merge_publish.py --deselect
   tests/test_signoff_integration.py` -> **4621 passed, 1 skipped, 92
   deselected, 0 failed** (393.79 s). Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i16/` (`probe.log`,
   `mutation-check.log`, `suite.log`, `README.md`, `scripts/`). No
   `pm_core/` change; the dropped helper/prompt/verifier work stays
   dropped.

R58. **The web-UI driver block's writability guard sat behind its `cd`.** Found
   by review loop ebd1 i17, in the kept recipe scope, the PR's own class (a
   step that cannot do its job must say so where it fails). R55 gave the
   driver block a missing-directory check and a writability check, in that
   order, but both *after* `cd "$CAPDIR"`. A capture directory that exists
   and cannot be *entered* (mode 400, say) therefore failed the `cd` with
   "Permission denied" and the block reported "capture directory … does not
   exist — create it and run step 1": the worker is sent to create a
   directory that is already there and to re-run the step that created it.
   Verified live in this container (uid 1000, mode-400 directory): pre-fix
   rc 1 with bash's `cd: … Permission denied` followed by that message, while
   the finalize and Layer 2 blocks — which never `cd` — name the same
   directory "cannot be written — … check the path and its permissions".
   Fix: the `-d` check runs first (a missing directory is still "does not
   exist"), then `-w`/`-x` ("cannot be written"; `-x` is the half the `cd`
   needs), and the `cd` runs last, for a directory that passed both — its
   failure now says the directory "could not be entered — it may have been
   removed after the checks above". Test:
   `test_web_ui_driver_block_refuses_a_capture_dir_it_cannot_enter` (mode
   400, skips under root) requires "cannot be written" and rejects "does not
   exist"; it fails against the pre-fix block (verified with the recipe
   restored in place, then the fixed copy restored). File **228 passed**
   (was 227). No `pm_core/` change; the dropped helper/prompt/verifier work
   stays dropped.

R59. **Three guards the kept recipes carry had no case.** Found by review loop
   ebd1 i18 by mutating them, with no recipe change. (1) Every
   capture-directory writability guard is `[ -w … ] && [ -x … ]`, but every
   case modelled the missing *write* bit (mode 500) only: a directory that
   exists with the write bit and no *search* bit (mode 600, `rw-------`)
   passes `[ -w ]` and is refused only by the `-x` half, and removing that
   half from all ten sites left the file green (228 passed). Verified live in
   this container (uid 1000) with the recipes' own blocks and a mode-600
   capture directory: the tmux step-0 block with the `-x` half removed runs
   on, clears the shared `pm-recorder` session — the concurrent-capture
   handle the clear-after-the-guard ordering exists to protect — and only
   then exits 1 on `rm`'s "Permission denied"; the render block reports
   "there is no cast to render (the recording wrote nothing)" for a cast that
   is there; the web-UI start block launches the app and exits 0 having
   written no `server.pid`; the driver block's `cd` fails and reports "could
   not be entered"; the finalize block reports "there is no webm to
   transcode — the driver wrote no video"; and the Layer 2 block exits 0
   having written neither log. Fix: the eight writability cases run in both
   shapes (`UNWRITABLE_MODES`, ids `no-write-bit`/`no-search-bit`); with the
   `-x` halves removed exactly the ten `no-search-bit` cases fail, and every
   mode-500 case still passes.
   (2) The render blocks' pre-render `rm -f "${cast%.cast}.mp4" "$cast.gif"`
   was pinned only through `render_fail`, which removes both on every other
   failure path: the missing-encoder stop is the one render failure that
   exits before `agg` runs and never calls `render_fail`, so with the `rm`
   removed a previous run's mp4 and gif survive it (verified live: same rc 1
   and message, both files still in the capture directory). The
   missing-encoder case now seeds the previous run's outputs and requires
   both gone.
   (3) The Layer 2 protocol block's `kill "$SSE_PID"` — its own "then stop
   the reader" step, which the route-bound case's docstring already relies on
   as the normal stop (`--max-time` is the backstop) — had no case: removing
   it left the file green. A new execution case stubs the SSE reader with a
   `TERM` trap and requires the stop to arrive; with the line removed the
   block returns with the reader still writing into `sse.log`.
   Tests: file **239 passed** (was 228). Each mutation fails exactly its
   cases: `all_x` (every `-x` half removed) → the ten `no-search-bit` cases;
   `render_rm` → the two missing-encoder cases; `sse_kill` → the new case.
   Full suite `env -u PM_HOST_HOME PATH=/usr/bin:/bin pytest tests/ -q
   --deselect tests/test_merge_publish.py --deselect
   tests/test_signoff_integration.py` -> **4633 passed, 1 skipped, 92
   deselected, 0 failed** (401.56 s).
   No `pm_core/` change; the dropped helper/prompt/verifier work stays
   dropped.

R60. **Integration with master (#249, 2026-10-31).** origin/master merged
   #249 (`eaf3372e`), which replaced both recording recipes' inline render
   block with a reusable `render_cast` function: `agg`, then `ffmpeg` with
   `-vsync vfr -enc_time_base 1/100 -video_track_timescale 100` and a
   `tpad`/`setpts` final-frame hold (a constant-rate encode of a sparse TUI
   cast took more than 10 minutes where VFR took about 2), writing
   `recording.mp4.partial.mp4` and renaming it to `recording.mp4` only after
   a successful encode, with `-nostdin` so a batch loop cannot lose file
   names to ffmpeg's stdin. The merge keeps that machinery and this PR's
   guards:
   - the block still starts from `cast=<capture-dir>/recording.cast` (the
     tests locate the block and its cast path by that line);
   - the capture-directory missing/unwritable checks (R57/R59) and the
     pre-render `rm -f` of this run's mp4, gif and partial run first, so a
     refused render acts on nothing and a missing-encoder stop (which never
     reaches `render_fail`) still clears the previous run's outputs;
   - `render_fail` removes the gif, the mp4 and the partial, and the stage
     checks keep their messages: "there is no cast to render", "ffmpeg is
     not installed", "agg failed on the cast — is 'agg' installed?", "agg
     wrote no gif", "ffmpeg failed on the gif", "ffmpeg wrote no mp4";
   - `render_cast` returns non-zero rather than exiting, so a batch caller
     can keep going; the recipe's own call is `render_cast "$cast" ||
     render_fail …`, so the block exits non-zero.
   The one policy clash was the stale video: master's note said a failed
   render keeps an older completed `recording.mp4` ("do not delete it"),
   while R8 requires the render step to clear this run's outputs so an
   earlier run's video cannot be presented as this run's evidence. The
   merged block keeps R8 (the pre-render `rm` and `render_fail`), and the
   "Partial output is never published" note was rewritten to say so;
   master's partial-publish guarantee (the `.partial` file is renamed only
   on success) is kept. `pm/project.yaml` auto-merged; it was verified
   structurally (571 PR ids, none lost or duplicated, every entry equal to
   the side that changed it; `project` and `plans` equal master). Tests: the
   recipe file is **239 passed**; `test_qa_artifact_web_ui_recording.py` and
   `test_qa_loop.py` **145 passed**.

## Non-goals
- **No product polling loop.** There is no checked-in `pgrep` loop to fix.
- **No new helper, prompt block, verifier text, or QA-loop change.** Those
  were the dropped scope above.
- **No new `claude -p` usage** (session rule).

## Files

| File | Change |
|---|---|
| `pm/qa/artifacts/tmux-screen-recording.md` | capture-dir mkdir (checked), stale cast + transcript + recorder status removal, recorder readiness, bounded stop + cast check, recorder-status handle so a recorder killed while the target session also ended is not a success, bounded pm-session poll on `has-session -t "=$TARGET"`, failed `pipe-pane` reported + `transcript.log` checked, stale render outputs cleared + renderer exit statuses checked + mp4 checked, `agg` prerequisite + install line, asciinema's own stderr + the pane's last screen saved on failure (R11), step 5 re-derives `$TARGET` and saves the pane inline because it is pasted on its own (R13); the pm-session readiness failure says its output was discarded instead of pointing at it, the `agg` install creates `~/.local/bin` first (R14), a failed `new-session` is reported as a start failure (R15), the `agg` install is guarded on `agg --version` so it cannot replace a working binary and does replace a truncated one that still resolves (R16, R52), the produced-files list names the flow's diagnostics (R17), and the driving step says a failed `pm tui send` means the scenario never ran, so the capture must not be accepted, and re-derives `$TARGET` (refusing an empty one) so its sends cannot auto-detect a different TUI (R20); the `agg` install download carries `--connect-timeout`/`--max-time` and removes a partial binary on failure (R21), and the driving step's example sends are checked in the block, not only in the prose above them (R22); step 0 also clears the earlier run's `recording.mp4`/`recording.cast.gif`, because a capture that fails exits before the render step's own cleanup, and the render block names a missing `ffmpeg` instead of reporting it as a bad gif (R23); step 2 claims the capture directory in a session option *before* attaching the pipe and refuses a session recording a different directory, or a directory another live session is recording, releasing the claim if the pipe cannot be attached and in step 5 (after the pipe is stopped, so the cleanup cannot close a later run's pipe), and re-derives `$TARGET` like steps 4 and 5 (R24); every failure path after the claim is taken releases it again — including the driving step's failed send, which saves the recorder pane, kills the recorder, stops the pipe and releases the claim, because a stale pane-registry entry fails the send while the session, its pipe and the recorder live on — and the cross-session refusal names the clear command for the other session (R25); step 5 detaches with the prefix the server reports (`tmux show-options -gv prefix`) instead of a literal `C-b`, names that key in the stop-timeout message, and the step-0 prose records that the `pm-recorder` name is shared by every run on one server, so captures run in sequence or on separate servers (R26); step 0 refuses a relative `<capture-dir>` — tmux runs the transcript pipe in the pm session's directory, so a relative path writes the transcript where step 5 never looks — and the produced-files list also names `recorder-pane.log` for a failed driving send (R27); step 0 clears the real intermediate, `recording.cast.gif` (the render block's `$cast.gif`), not the `recording.gif` nothing writes (R28); step 2 compares the capture-directory claim as a canonical directory (`cd` + `pwd -P`, with a stored claim's `~/` prefix expanded) instead of as the text typed, so one directory spelled two ways is one claim — the cross-session collision and the same-session false refusal it caused (R29); step 2's claim scan skips a session that holds no claim instead of normalizing the empty answer (`cd ""` stays in the worker's cwd, which made every other session look like it recorded into the directory step 2 was pasted from) — R30; the `agg` install now verifies that the binary it wrote resolves on PATH and stops with the `~/.local/bin` fix instead of exiting 0, so the render's "is 'agg' installed?" cannot send the worker back to a remedy that already ran (R31); a failed detach is a hard failure only while the target session is still alive — when the session is gone too (the scenario's quit raced the detach) the cast/status/transcript checks decide, so a complete recording is not reported as incomplete (R33); the step-0 prose no longer claims a duplicate recorder session would pass the readiness wait, which the start check now stops (R33); and step 0 creates the capture directory *before* it clears the shared `pm-recorder` session, so a block refused for an uncreatable `<capture-dir>` cannot end a concurrent capture's recorder (R36); and step 1's readiness wait, step 2's claim read/write and pipe attach, and step 5's two witness checks and every pipe stop now name the session with tmux's `=` prefix, because a bare target is *prefix*-matched (verified on 3.2a) and pm's grouped `<base>~N` session stood in for the target — the wait passed, the whole run recorded and reported that session, and it exited 0 on a capture of a session pm never created (R37); and every recorder-session handle (step 0's clear, the readiness and settle checks, the pane saves, the detach send and the stop waits/kills) and the recorder's own `tmux attach` name the session with `=`, because a bare `pm-recorder` is prefix-matched by pm's `pm-<repo>-<hash>` session for a repo named `recorder…` — step 0's clear ran on every capture and killed it silently, and a dead recorder could be replaced by that session in the readiness/stop checks (R39); and the render block checks the gif `agg` wrote (`[ -s "$cast.gif" ]`) before handing it to ffmpeg, so a renderer that reports success and writes nothing is named instead of surfacing as "ffmpeg failed on the gif" (R40) and the cleanup order — this run's pipe stop before the claim release, with only the recorder kill between them — is pinned at every release, because a later run in the session can take the claim the instant it is released and have its pipe closed by this run's cleanup (R45); and step 0 also clears the previous run's `manifest.md`, the one produced file it did not clear, so a re-run that fails before the worker writes a new one cannot leave a manifest describing the previous run and naming the cast and video step 0 just deleted (R47); and every capture-directory claim handle — the read, the write and all fourteen releases — now names the target exactly (`-t "=$TARGET:0.0"`), because a plain `-t "$TARGET"` is prefix-matched when the target has ended: the write then succeeds on a grouped `<base>~N` session and exits 0, so the "could not claim … the session went away" guard never fires and the run fails one step later as "could not stream … — check that pane exists" (R50); and step 0 (before the shared `pm-recorder` clear) and step 2 (before the claim) refuse a capture directory that cannot be written or entered, because `mkdir -p` answers 0 for one that already exists and every later write into it fails in the pane as "recorder exited before it drew", naming a cast and a stderr log that cannot exist (R54); and step 2 (the paste-alone re-attach) also refuses a relative `<capture-dir>`, because its claim is canonicalized while the pipe's command runs in the pm session's directory — the block exited 0 with the claim on the worker's absolute path and the pipe's redirect failing in the session's directory, so the run had no transcript anywhere and step 5 reported an empty transcript for a pipe that never had a writable target (R56); and the render block refuses a capture directory that is missing or cannot be written, before it removes anything or runs `agg`, so an unwritable directory is not reported as "is 'agg' installed?" and a path that is not there is not reported as a recording that wrote nothing (R57) |
| `pm/qa/artifacts/cli-recording.md` | same capture fixes; no-TTY scaffold rewritten (cast path, readiness, `exit` stop, bounded wait + cast check, escaped command form, recorder-status handle so a killed recorder is not a success); stale render outputs cleared + renderer exit statuses checked + mp4 checked + no-cast failure named; `agg` prerequisite + install line; stop failure names the interactive remedy; `'\''` escape documented; `tee` fallback reconciled with the hard-failing render; asciinema's own stderr + the pane's last screen saved on failure (R11), saved inline in step 4 for the same paste-alone reason (R13); the `agg` install creates `~/.local/bin` first (R14); the capture-dir `mkdir` and the recorder `new-session` are checked (R15); the `agg` install is guarded on `agg --version`, so a working binary is kept and a truncated one that still resolves is replaced (R16, R52); the produced-files list names the flow's diagnostics (R17); the `tee` fallback writes its transcript into the capture directory, with the produced-files list naming it (R20); and `RECORDER_STOP_TIMEOUT` is validated as whole seconds before the arithmetic (a non-numeric value left the deadline empty and the stop wait unbounded in an interactive shell), with the deadline read as `10#`, the `agg` install download bounded and cleaned up on failure (R21), and the driving step warning that a failed `send-keys` means the recorded shell died before the behaviour under test, which step 4 cannot see (R22); the preamble and scaffold also clear the earlier run's `recording.mp4` and its intermediate gif and the `tee` fallback's `transcript.log`, and the render block names a missing `ffmpeg` (R23); the preamble and scaffold refuse a relative `<capture-dir>` (the pane command and step 4 resolve it against their own pastes), and the stop step's two failures — the timeout and a mistyped bound — leave the recorder running for the re-run they prescribe instead of killing it, so the documented remedy works, and the step-1 prose records that the `scaffold` socket name is shared by every run on the host, so captures run in sequence (R27); the preamble and scaffold clear the real intermediate, `recording.cast.gif` (the render block's `$cast.gif`), not the `recording.gif` nothing writes (R28); the `agg` install verifies that the binary it wrote resolves on PATH and stops with the `~/.local/bin` fix instead of exiting 0 (R31); and the preamble no longer claims a duplicate `rec` session would pass the readiness wait, which the scaffold's start check now stops (R33); the absolute-path guard runs *before* the host-shared `rec` session is cleared, so a block refused for its path cannot kill a concurrent capture's recorder (R34); and the step-0 prose no longer says a leftover `rec` session would let the readiness wait pass on the previous run's recorder — this recipe's wait is on the cast file, which step 0 clears, so a leftover session only burns the deadline (R35); and the `mkdir` now runs before the host-shared `rec` session is cleared, so a block refused for an uncreatable capture directory cannot kill a concurrent capture's recorder on its way out (R36); and the render block checks the gif `agg` wrote (`[ -s "$cast.gif" ]`) before handing it to ffmpeg, so a renderer that reports success and writes nothing is named instead of surfacing as "ffmpeg failed on the gif" (R40); and the preamble and scaffold also clear the previous run's `manifest.md`, so a failed re-run cannot leave a manifest naming the cast and video that were just deleted (R47); and the preamble and scaffold (before the shared `rec` clear) refuse a capture directory that cannot be written or entered, because `mkdir -p` answers 0 for one that already exists and the pane redirect then fails before asciinema runs, which step 4 reports as "asciinema wrote no cast" for a file that cannot exist (R54); and the render block refuses a capture directory that is missing or cannot be written, before it removes anything or runs `agg`, so an unwritable directory is not reported as "is 'agg' installed?" and a path that is not there is not reported as a recording that wrote nothing (R57) |
| `pm/qa/artifacts/web-ui-recording.md` | port pre-check (refuses a server already answering) then bounded `until curl` with per-attempt timeout and server cleanup; stale webm/mp4/trace/screenshots/DOM dump/protocol logs cleared before the driver + mp4 checked on ffmpeg's exit status (the webm glob is `*.webm`, so Playwright's auto-named video from a killed driver goes too — R18); finalize/driver/teardown guards stop the block (`if … exit 1`, because `${VAR:?}` only stops a scripted run); driver resolves the image's global Playwright through a conditional local `node_modules` (ESM ignores `NODE_PATH`) and stops if it does not; the driver block clears this attempt's own outputs and checks `node driver.mjs`'s exit status, so a failed driver is named where it fails instead of being misdiagnosed as an ffmpeg error and a retry cannot be finalized from an earlier attempt's webm (R18); the driver guard covers `APP_URL` too, because the driver falls back to `localhost:8000` (R13); step 1 records the app's pid in `server.pid` (cleared first, removed by the teardown) so the teardown works from a fresh shell, and the Layer 2 protocol block stops on an unset `CAPDIR`/`APP_URL` instead of redirecting to `/http.log` and `/sse.log` and exiting 0 (R14); the start block checks its `mkdir` and drops the dead pid on a failed start, and the driver block refuses a capture directory it cannot enter (R15); the Playwright link is conditional on `/usr/lib/node_modules/playwright` so a global directory without the package is not linked, and the Layer 2 route snapshots carry per-request `--connect-timeout`/`--max-time` bounds (R16); the busy-port refusal names the manual pid hunt instead of a teardown whose `server.pid` this step just cleared, and the Playwright resolution failure only offers the link when the package is there (R17); the finalize step checks that there is a `recording.webm` to transcode before running ffmpeg, so a driver that wrote no video is named instead of surfacing as an encoder failure (R19), and its "ffmpeg wrote nothing" branch removes the empty mp4 it would otherwise leave behind (R20); the finalize step also refuses a set-but-missing capture directory instead of reporting "the driver wrote no video" (R21), and the driver block clears this attempt's outputs — including the earlier attempt's `recording.mp4`, which a failed retry would otherwise leave as the manifest's only video — *before* its Playwright resolution check, so that failure path cannot leave an earlier attempt's artifact for the finalize step (R21); the finalize step stops on a missing `ffmpeg` instead of reporting it as a failed transcode of the driver's webm, and the Tooling section names the encoder and how to install it (R22); the readiness poll uses plain `curl` (no `-f`), so an app that answers 404 at `/` counts as up instead of being reported as not answering after the full deadline and killed (R23); the port pre-check stops on any curl status other than 7, so a listener that accepts and never answers (28), a wrong URL (6) or a missing curl (127) is named instead of surfacing as "app did not answer" after the deadline and killing the app (R27); the produced-files list and the manifest's `## Files` example also name the `node_modules` link step 2 creates beside the driver, so the manifest matches the capture directory (R17's rule, one file over); step 1 resolves the captures root through a checked `pm qa captures-path` and refuses a failed or empty answer, which otherwise became `/scenarios/1/web-ui` at the filesystem root (R31); the driver block refuses a missing `driver.mjs` instead of reporting it as a driver that ran and failed, and its Playwright resolution failure says to remove a `node_modules` that does not hold the package before linking, because a bare link nests inside it (R32); and the driver block names a missing `node` before it links anything, because without the runtime its Playwright resolution failure offers remedies that need node, and the Tooling section names Node.js (R38); and the produced-files list names `server.pid` (present when a run stopped before the teardown) and the `recording.webm` the finalize step keeps on a failed transcode, so the manifest can name whichever survives (R44) and the manifest's `## Files` example names `server.pid` and `recording.webm` too, so the example a worker copies into the manifest matches the produced-files list instead of leaving them out (R45); and step 1's cleanup also clears the previous run's `manifest.md`, while `driver.mjs` stays because it is the run's input rather than its evidence (R47); the port pre-check's comment says why its per-attempt bounds cannot be dropped (without them a listener that never answers blocks the probe instead of answering 28, so the "could not check … exit 28" diagnosis is unreachable), and step 2's attempt cleanup clears `manifest.md` with this attempt's outputs, so a retried driver that fails cannot leave the earlier attempt's manifest naming the `recording.mp4` that cleanup just deleted (R48); and the driver block's "is `driver.mjs` here" check is `-s`, not `-f`, because a 0-byte driver is a valid ES module — `node` exits 0 having run nothing, so the block reported success and the finalize step then blamed the driver's `recordVideo` option with a re-run that passes again (R51); and step 2's attempt cleanup also clears the earlier attempt's Layer 2 logs (`http.log`/`sse.log`), which the protocol block rewrites only if the retried run re-runs it — so a retried capture cannot present the earlier attempt's route snapshots and event stream as this run's evidence (R53); and step 1 (before the stale clear), the driver block, the finalize block and the Layer 2 block refuse a capture directory that exists and cannot be written or entered, because `mkdir -p` answers 0 for one that already exists and each block then failed as something else — step 1 as a successful start that wrote no pid file and left the previous run's evidence in place, the driver as "playwright does not resolve" (with a link command that fails the same way), the finalize as a failed transcode of the driver's webm, and the Layer 2 block as a silent success with neither log (R55); and the driver block's existence and permission checks now run *before* its `cd`, so a capture directory that exists and cannot be entered is named "cannot be written — … check the path and its permissions" instead of "does not exist — create it and run step 1" (R58) |
| `tests/test_qa_artifact_recording_recipes.py` | **new** regression tests for the kept recipe fixes, including R21's four cases (the non-numeric stop bound — which hangs against the pre-fix recipe; the bounded `agg` download with a partial-file cleanup; the finalize step's missing-directory guard; the resolution-failure cleanup), a lenient pty decode so a readline redraw cannot fail the interactive-paste cases, R22's three cases (a mid-sequence failed send, the CLI driving warning, the missing encoder), and R23's cases (a failed capture clearing the earlier run's mp4/gif in both recipes and the CLI's transcript, the render block naming a missing `ffmpeg` on a `PATH` without one — and not running `agg` first — and the web-UI readiness poll accepting an app that answers 404 at `/`, driven through a stub `curl` that models `-f` as exit 22), and R24's five cases (step 2 writes the claim; the claim exists at the moment `pipe-pane` runs, so it is taken before the pipe it guards; a second capture directory on one session is refused; a directory another live session records into is refused; a finished run releases its claim) plus the empty-`$TARGET` refusal, with the stub `tmux` modelling `show-options`/`set-option`/`list-sessions` and recording the claim state seen by `pipe-pane`; and R25's cases (each of the nine failing modes releases the claim — `midbothbad` passes both ways by design, because a session's death takes its options with it, which the stub now models; a failed driving send leaves no recorder session, no claim and a saved pane; the cross-session refusal names the clear for the other session), and the web-UI driver block's failure case seeds the earlier attempt's `recording.mp4` and requires the attempt cleanup to remove it; R26's case runs the tmux stop block alone against a stub server whose prefix is `C-a`, which must still end the recording (the stub ends it only for the prefix the server reports) and must ask the server for it — against the pre-fix block the same run times out with the recorder up; R27's cases: the web-UI start block with a stub `curl` that times out on the pre-check (exit 28) must refuse before launching the app; each recording recipe's scaffold with a relative `<capture-dir>` must stop at its absolute-path guard without creating the directory; and the CLI stop block run alone must leave the `rec` session alive on both a timed-out bound and a non-numeric one, so the re-run its message prescribes can be applied; R28's cases derive the intermediate's name from the render block's `cast=` and `"$cast.gif"` and require the step-0 cleanup (both recipes, and the CLI scaffold) to remove that name and not the `recording.gif` nothing writes, with the execution case seeding the real intermediate; R29's cases: a capture directory claimed on another session through a `~/` spelling must be refused (the pre-fix step 2 ran on), and a retry must not be refused by its own `~/` claim (the pre-fix step 2 did), plus the two step-5 branches no mode reached with the pm session alive (`detachnocast`, `detachnostatus`) releasing the claim, which fails when the release is removed from either branch; R30's case runs the step-2 block from the capture directory against a second session that holds no claim, which must proceed and claim the directory (the pre-fix block refused it as a collision), with `_run_block` gaining a `cwd` argument so a case can say where the block is pasted from; R31's cases: both recording recipes' `agg` install run with `~/.local/bin` off `PATH` must fail with the message that names the fix (the pre-fix block exits 0 with an `agg` nothing can run), and the web-UI start block run with a failing `pm qa captures-path` and with a silent one must stop before `mkdir` (a logging `mkdir` stub asserts nothing was attempted) and never start the app (the pre-fix block ran `mkdir -p /scenarios/1/web-ui`); R32's two cases: the driver block run with no `driver.mjs` must stop with the message that names it and must not report "the driver failed", and the block run with an empty `node_modules` and a fake global Playwright must name the removal (`rm -rf node_modules`) and, once applied, resolve the package and run the driver; R33's two cases: the detach failing as the target session ends too (stub mode `detachboth`, status 0, complete cast and transcript) must pass, and the same with a killed recorder (`detachbothbad`, status 137) must still fail on the status message — both fail against `HEAD`'s step 5; R34's case: the CLI scaffold run with a relative `<capture-dir>` against a logging stub `tmux` must make no tmux call at all (the pre-fix block killed the shared `rec` session before refusing), and `pipefail` is added to the claim-release parametrization, because the pipe-attach failure was the one path whose release no case asserted; `test_stale_recorder_is_cleared_before_start`'s docstring now gives the current reason for the clear (a duplicate `new-session` stops the run at the start check) and records the pre-R15 failure mode as history, since the readiness wait can no longer pass on the previous recorder (R35); and R36's case: the uncreatable-capture-dir case now runs with the stub `tmux` logging its calls (`STUB_TMUX_LOG`) and requires that no `kill-session` reach the shared recorder session (the pre-fix blocks cleared `rec`/`pm-recorder` before refusing); R37's cases run against a stub `tmux` that resolves session targets exact-then-prefix (with `=` forced exact, as real 3.2a does) — the whole capture block with only `pm-test~1` on the server must fail at the readiness wait, and step 2 alone must refuse with "no session named exactly" and leave no claim on `pm-test~1` (both pass against `HEAD`, which records the grouped session and exits 0); the text assertions that pinned the bare target now require the `=` form; R38's case runs the web-UI driver block with a `PATH` that has the shell and its other tools but no `node`, and requires the runtime message, no Playwright misdiagnosis and no `node_modules` link (fails against `HEAD`'s block); the tmux stop-timeout case now also requires the message to say the cast is incomplete (the branch kills the recorder and leaves a truncated cast); R39's three cases (`test_tmux_session_handles_are_exact`, `test_step_zero_does_not_kill_a_pm_session_that_shares_the_prefix`, `test_a_prefix_session_is_not_the_recorder`) and the stub `tmux`'s exact-then-prefix resolution and pane-spec stripping; R40's case (`test_render_names_a_renderer_that_writes_no_gif`, both recipes, with an `ffmpeg` stub that fails on a missing input); and R41's pair: the text guard now also rejects a bare `pipe-pane -t "$TARGET` and requires `pipe-pane -t "=$TARGET:0.0"`, and `test_the_transcript_pipe_targets_the_exact_session` runs the whole block in the new stub mode `pipegap` (the target and its claim vanish as the claim is written and a grouped `pm-test~1` is left), which must fail at "could not stream …", write no transcript and leave no claim — with a bare pipe target the same run exits 0 on the grouped session's transcript; and R42's pair: both exit-status tests now require the *derived* status path (the file the pane command writes) to be removed by the `rm` statement itself — the old assertion searched everything up to `new-session`, where step 1's comment also mentions `recorder.status`, so deleting the clear left the file green — and `test_a_stale_recorder_status_is_not_read_as_this_runs` seeds the earlier run's `0` in modes `detachnostatus`/`nostatus` and requires "recorder status is missing"; without the clear the run exits 0 on the previous run's status (all four fail against the pre-fix recipes); and R43's three harness fixes: the stub `tmux`'s `capture-pane` resolves its target and fails once the session is gone (so moving the stop-timeout / `send_failed` pane saves after their `kill-session` fails three cases), the two driver-guard fixtures seed a `driver.mjs` in the worker's cwd (so removing the `CAPDIR` guard's `exit 1` fails both), and `test_every_deadline_is_a_real_bound_and_its_message_agrees` pins every arithmetic bound at ≥ 10 s and every "within Ns" to a bound the code uses — the value no execution case can see, because `_run_block` rewrites it; and R44's two cases: `test_step_one_refuses_an_empty_target` runs the whole tmux block with `pm session name` printing nothing and requires step 1's guard message (removing the guard makes it fail at the deadline with "pm session  did not appear within 60s"), and `test_web_ui_produced_files_list_names_the_files_a_failed_run_keeps` requires `server.pid` and `recording.webm` in the web-UI produced-files list (it fails against the pre-fix list) and R45's cases: the web-UI manifest example must name both files, read from the indented `## Files` heading because the section's `## Commands` line and the prose above the template both mention `recording.webm` (a first-match assertion passed with the example's line deleted, verified); the new stub mode `claimgone` ends the session as the claim is written, and the run must stop with "could not claim" rather than the pipe-attach message (it fails with the guard removed, rc 1 at "could not stream …"); and `test_the_claim_is_released_only_after_the_pipe_is_stopped` requires every claim release to follow this run's pipe stop, with step 2's failed attach the one exception (it fails when the release is moved above the stop); and R46's cases: the no-cast, no-gif and no-webm cases are parametrized over "no file" and "0-byte file", with the `ffmpeg` stub modelling real ffmpeg's contract for a missing *and* an empty input, so weakening any of the three `test -s` checks to `-e` fails exactly the new case (it previously left the whole file green); `test_render_names_an_encoder_that_writes_no_mp4` covers the recording recipes' final `test -s` (a stub `ffmpeg` that exits 0 after creating its output must fail with "ffmpeg wrote no mp4" and leave no mp4; deleting the check makes the block exit 0 on a 0-byte video); and `test_cli_preamble_refuses_an_uncreatable_capture_dir` runs the CLI preamble block — the one fenced block no case executed — which must stop with "could not create" (weakening its guard to `|| true` leaves the file green otherwise); and R47's cases: `test_capture_section_clears_the_previous_manifest` requires `manifest.md` in both recording recipes' first-block and scaffold `rm` statements, `test_a_failed_capture_leaves_no_previous_manifest` runs both recipes' capture blocks with a seeded manifest and a failing recorder and requires it gone (it survives against the pre-fix recipes), `test_web_ui_start_clears_a_previous_manifest` runs the web-UI start block with a seeded manifest, and `test_web_ui_clears_a_previous_video` now requires `manifest.md` in step 1's clear command; and `test_web_ui_layer2_route_snapshots_are_bounded` now also requires the SSE reader's `--max-time`, the block's other (unbounded-stream) request, whose best-effort `kill` is the only thing that would otherwise stop it; and R48's pair: the stub `curl` logs each call's argv, and `test_the_port_pre_check_is_bounded` requires the first call — the port pre-check — to carry `--max-time` and `--connect-timeout` (the stub answers 28 by mode whatever its arguments, so deleting the flags left the file green), and `test_web_ui_driver_failure_is_reported_and_clears_stale_outputs` seeds `manifest.md` with the earlier attempt's other outputs and requires the driver block's cleanup to remove it (it fails against the pre-fix block, which left the manifest naming the mp4 the cleanup deleted); and R49's four cases: `test_cli_preamble_refuses_a_relative_capture_dir` runs the CLI preamble (the first block under `## Capture`, never executed with a relative path before) and requires the guard message and that nothing was created — deleting its `case` guard left the file green (201 passed); `test_a_shared_dir_is_recognized_through_a_symlink` runs the whole tmux block with the capture directory reached through a symlink and another session's claim on the real path, which must be refused naming that session; `test_a_retry_is_not_refused_through_a_symlink` runs it with the same session's claim on the real path, which must proceed — both fail when every `pwd -P` in step 2 is weakened to `pwd`; and `test_a_refused_start_clears_the_previous_pid` seeds a stale `server.pid` and runs the web-UI start block against a taken port, which must refuse and leave the file gone — moving the cleanup below the pre-check left the file green (204 passed at that point); and R50's case: the stub `tmux` strips the pane spec for `show-options`/`set-option` (as it already did for `capture-pane`/`pipe-pane`/`send-keys`) and gains `claimgap` (the target ends at the claim write, a grouped `pm-test~1` is left, which a bare write succeeds against); `test_a_claim_written_to_a_prefix_session_is_reported` runs the whole block in that mode with another run's claim seeded on the grouped session and requires "could not claim", not "could not stream" and not "already being recorded", with the grouped session's claim unchanged — it fails with every claim handle reverted to the bare form (verified: rc 1 at "could not stream … — check that pane exists"); `test_tmux_session_handles_are_exact` also rejects `show-options -t "$TARGET"`, `set-option -t "$TARGET"` and `set-option -u -t "$TARGET"` and requires the three `=…:0.0` forms; and `test_the_claim_is_released_only_after_the_pipe_is_stopped` follows the new release spelling; and R51's parametrization of `test_web_ui_driver_block_refuses_a_missing_driver` over "no file" and "0-byte file", so the `-s` check that rejects an empty driver is exercised (the 0-byte case fails against the pre-fix `-f` check, which exits 0 with "playwright ok"); and R52's pair: `_run_install_block` gains an `agg_body` knob so a case can seed the truncated binary an interrupted download leaves, `test_renderer_install_replaces_an_agg_that_does_not_run` requires the block to download over a resolvable but non-running agg (the pre-fix `command -v` guard skips it), `test_renderer_install_names_an_agg_that_still_does_not_run` requires a download that leaves such a binary to stop naming it (the pre-fix block exits 0), and `test_render_documents_how_to_get_the_renderer` pins the `agg --version` guard before the download; and R53's case: `test_web_ui_driver_failure_is_reported_and_clears_stale_outputs` also seeds the earlier attempt's `http.log` and `sse.log` and requires the driver block's cleanup to remove them (it fails against the pre-fix block, which leaves both); and R54's cases: `test_step_two_refuses_a_capture_dir_it_cannot_write` (both shapes, missing and mode-500: the refused step takes no claim and attaches no pipe), `test_a_capture_dir_that_cannot_be_written_stops_the_run` (both recipes, and the refused block makes no tmux call at all), `test_cli_preamble_refuses_a_capture_dir_it_cannot_write`, the strengthened `test_cli_recorder_that_never_writes_a_cast_fails` (the readiness timeout's `recorder-pane.log` must exist and hold what the recorder drew) and `test_a_tilde_capture_dir_is_accepted` (the tmux step-0 block and the CLI preamble run with `~/cap`), all of which fail against the pre-fix recipes or the mutated guard; and R55's four cases: `test_an_unwritable_capture_dir_stops_the_start` (the web-UI start block with a mode-500 capture directory must refuse before launching the app, via the new `capdir_mode` knob on `_run_web_ui_start`) and `test_web_ui_driver_block_refuses_a_capture_dir_it_cannot_write` / `test_web_ui_finalize_refuses_a_capture_dir_it_cannot_write` / `test_web_ui_layer2_block_refuses_a_capture_dir_it_cannot_write` (each must name the directory and must not report its own misdiagnosis — the Playwright remedy, a failed transcode, or the silent success of a Layer 2 block that exits 0 writing neither log), all four failing against the pre-fix recipe; and R56's case: `test_step_two_refuses_a_relative_capture_dir` runs step 2 alone from a worker directory holding `relcap` and requires the path refusal with no claim and no pipe attach (the pre-fix block exits 0 with the claim on the canonical path, while its pipe's command fails in the session's directory); and R57's four cases: `test_render_refuses_a_capture_dir_it_cannot_write` runs each recipe's render block with a mode-500 capture directory holding a cast and requires the refusal to name the directory and not to be the "agg failed on the cast — is 'agg' installed?" message (the pre-fix block reports exactly that, and the install block it prescribes runs and changes nothing), and `test_render_names_a_missing_capture_dir` runs it against a capture directory that is not there and requires "does not exist" rather than "the recording wrote nothing" — both fail against the pre-fix recipes, with `_run_render` gaining `capture`, `capdir_mode` and `create_capture_dir` knobs so a case can say where the block is pointed and what state that directory is in; and R59's cases: every capture-directory writability case runs in both permission shapes (`UNWRITABLE_MODES`: mode 500, no write bit, and mode 600, the write bit and no search bit), so the guards' `-x` half is pinned — removing it from all ten sites fails exactly the ten `no-search-bit` cases and leaves every mode-500 case green; `test_render_names_a_missing_encoder` seeds a previous run's mp4 and gif and requires the pre-render `rm` to remove them (that stop is the one render failure that never calls `render_fail`); and `test_web_ui_layer2_stops_the_sse_reader_it_started` requires the protocol block to stop its `curl -N` reader, whose `kill` had no case |
| `pm/specs/pr-b19db15/impl.md` | this spec |
| `pm/specs/pr-b19db15/qa.md` | reduced QA scope (recipe fixes only), with the intermediate gif named `recording.cast.gif` as the render block writes it (R28), the claim's canonical comparison — one directory under two spellings is one claim, refused across sessions and not refused for a retry (R29) — and R3's stale-session clause stating what the clear actually prevents: a duplicate session stopping the run at the start check, not the readiness wait passing on the previous recorder (R35) |

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
   failing execution mode (`pipefail`, `nostart`, `norec`, `dies`,
   `failedattach`, `stuck`, `notranscript`, `midadied`, `detachfail`,
   `midbothbad`) must leave no claim on the pm session, a failed driving send
   must leave no recorder session, no claim and a saved
   `recorder-pane.log`, and the cross-session refusal must name `tmux
   set-option -u -t <other> @pm_capture_dir`. Eight of the ten failing modes
   and both message/teardown cases fail against `HEAD`'s recipe
   (`midbothbad` passes both ways by design: the session's death takes the
   claim with it, and `pipefail` is the one path the pre-R25 recipe already
   released — it is asserted for coverage, R34). R26's case: the
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
5. R33's detach-race check: the two execution cases (`detachboth` with status
   0 must pass, `detachbothbad` with status 137 must still fail on the status
   message) fail against `HEAD`'s step 5; the live probe
   (`$(pm qa captures-path pr-b19db15)/review-7c9c-i5/scripts/live-race.sh`)
   reproduces the pre-fix false failure on a complete recording and the
   post-fix pass, and the killed-recorder case still fails.
6. R34's two checks: the CLI scaffold run with a relative `<capture-dir>`
   against a logging stub `tmux` makes no tmux call at all (against `HEAD`'s
   block it runs `-L scaffold kill-session -t rec` and then refuses), and the
   `pipefail` execution case fails when the claim release is removed from the
   pipe-attach failure branch (checked by deleting the line in place and
   restoring the recipe afterwards).
7. R35's check: with a leftover `rec` session and an empty cast, the CLI
   recipe's own readiness block (extracted verbatim, deadline shortened) must
   fail at its deadline — it cannot pass on the previous run's recorder
   because its handle is the cast file — while the tmux block passes at once
   on the leftover `pm-recorder`'s pane content. The corrected statements in
   `cli-recording.md`, R2, `qa.md` R3 and the test docstring say that, and
   name the start check (R15) as what stops a duplicate session now.
8. R36's check: with a concurrent capture's `pm-recorder` (tmux) / `rec`
   (CLI, on `-L scaffold`) up on a private tmux server, each recipe's own
   capture block pasted with `<capture-dir>` under a regular file must exit 1
   at "could not create …" *without* touching that session — the pre-fix
   blocks killed it first (verified live: `RESULT … KILLED` before,
   `SURVIVED` after). The execution case runs the same block with the stub
   `tmux` logging its calls and requires no `kill-session`; both cases fail
   against `HEAD`'s recipes. The nominal flows were re-run after the edit
   (tmux rc 0 / cast 3029 / status 0 / transcript 12 / claim released; CLI
   rc 0 / cast 143 / status 0).
9. R37's check: on a private `TMUX_TMPDIR` with only `pm-test~1` on the
   *default* server (the one the recipe uses) and a stub `pm` whose `pm
   session` creates nothing, `HEAD`'s block exits 0 with a cast,
   `recorder.status` 0 and a transcript — the readiness wait matched the
   grouped session by prefix — while the fixed block exits 1 at "pm session
   pm-test did not appear within 60s" and leaves `pm-test~1`'s claim
   untouched. `tmux has-session -t pm-test` exits 0 and `-t '=pm-test'` exits
   1 on that server; `pipe-pane -t '=pm-test:0.0'` exits 1 while
   `-t '=pm-test~1:0.0'` exits 0; `show-options`/`set-option -t '=pm-test'`
   answer "no such session: =pm-test". The nominal flow was re-run with the
   fixed block (rc 0, 2816-byte cast, `recorder.status` 0, 50-byte
   transcript, claim released).
10. R38's check: the driver block run with `PATH` holding the shell and its
   other tools but no `node` now exits 1 with "node is not installed — …" and
   creates no `node_modules`; with `node` on `PATH` it prints "playwright ok"
   and runs the driver (rc 0). Against `HEAD`'s block the same no-`node` run
   exits 1 with "playwright does not resolve beside driver.mjs" and the two
   remedies that need node.
11. R39's check, live on tmux 3.2a with a private `TMUX_TMPDIR`: with only
   `pm-recorder-abc123` on the server, `has-session -t pm-recorder` exits 0,
   `capture-pane -p -t pm-recorder` prints its pane, `send-keys -t pm-recorder`
   delivers, and `kill-session -t pm-recorder` kills it (taking the server
   down); the `=` forms (`"=pm-recorder"` for the session commands,
   `"=pm-recorder:0.0"` for the pane-target ones) all resolve on the real
   `pm-recorder` and all fail with only the prefix session present. The
   recipe's own step-0 block, run against a `pm-recorder-abc123` session, left
   it alive (the pre-fix block removed it, rc 0, no message). `tmux attach -t
   pm-test` with only `pm-test~1` proceeds (prefix match) while
   `-t '=pm-test'` answers "can't find session". The nominal flow was re-run
   end to end with the fixed block (real tmux 3.2a + asciinema 2.1.0, stub
   `pm`): rc 0, 3044-byte cast, `recorder.status` 0, 126-byte transcript,
   recorder session gone, claim released. The three new cases
   (`test_tmux_session_handles_are_exact`,
   `test_step_zero_does_not_kill_a_pm_session_that_shares_the_prefix`,
   `test_a_prefix_session_is_not_the_recorder`) fail against `HEAD`'s recipe
   (checked by restoring it in place, then restoring the post-fix copy).
   Evidence: `$(pm qa captures-path pr-b19db15)/review-7c9c-i10/`.
12. R40's check: both recording recipes' own render blocks, run with a stub
   `agg` that exits 0 and writes no gif and an `ffmpeg` stub that models the
   real contract (fails on a missing input), must exit non-zero with "agg
   wrote no gif" and must not say "ffmpeg failed on the gif"; against
   `HEAD`'s blocks the same runs print real ffmpeg's "No such file or
   directory" plus "render produced no mp4 — ffmpeg failed on the gif". The
   new case `test_render_names_a_renderer_that_writes_no_gif` fails against
   `HEAD`'s recipes (checked by restoring them in place, then restoring the
   post-fix copies).
13. R41's check: on a private `TMUX_TMPDIR` with only `pm-test~1` on the
   server, `has-session -t "=pm-test"` exits 1 while `-t pm-test` exits 0,
   `pipe-pane -t "=pm-test:0.0"` answers "can't find session: pm-test" and
   exits 1, and `pipe-pane -t "pm-test:0.0"` attaches to `pm-test~1` and
   writes its output into the capture directory. The harness case
   `test_the_transcript_pipe_targets_the_exact_session` (stub mode `pipegap`:
   the target session and its claim go as the claim is written, and a
   grouped `pm-test~1` is left) exits 1 at "could not stream …" with the
   recipe's exact pipe target and **0** with every one of the fourteen
   handles made bare — the same run reporting success on the grouped
   session's transcript. Both that case and the text guard
   `test_tmux_session_handles_are_exact` fail against the bare form (checked
   by mutating the recipe in place, then restoring it). Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i1/`.
14. R42's check: with `<capture-dir>/recorder.status` deleted from the tmux
   recipe's step-0 `rm` list (and from the CLI scaffold's own list), the file
   at `HEAD` stays green (**178 passed**) — the old assertion was satisfied
   by step 1's comment — while the tightened tests fail exactly four cases
   (the two text guards, the two execution cases) and pass on the unmodified
   recipes (180 passed). The false pass itself: stub `tmux`/`pm`, the recipe's
   own block, mode `detachnostatus`, `recorder.status` seeded as `0` — rc 1
   "recorder status is missing" as shipped, rc **0** with the clear removed.
   Evidence: `$(pm qa captures-path pr-b19db15)/review-ebd1-i2/` (`probe.log`
   sections A–F).
15. R43's checks: with the stub `tmux`'s `capture-pane` resolving its target,
   moving the tmux recipe's stop-timeout and `send_failed` pane saves after
   their `kill-session` fails `test_tmux_stop_timeout_saves_the_pane`,
   `test_a_failed_send_tears_the_run_down` and the tmux
   `test_stop_block_pasted_alone_saves_the_pane` (6 passed on the unmodified
   recipe); removing the web-UI driver block's `CAPDIR` guard `exit 1` fails
   `test_web_ui_driver_guard_stops_an_interactive_paste` and
   `test_web_ui_driver_block_refuses_an_unset_capdir` (4 passed with it); and
   the bound guard fails when the tmux pm-session bound is retuned 60 → 1 or
   the web-UI message says 90s while the code waits 120s (3 passed on the
   unmodified recipes). Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i2/` (`probe.log` sections
   G–K).
16. R44's checks: with step 1's empty-target guard removed in place, the whole
   tmux block run with `pm session name` printing nothing exits 1 at its
   deadline with "pm session  did not appear within 60s" and
   `test_step_one_refuses_an_empty_target` fails; with the guard restored the
   same case passes (1 passed). The web-UI produced-files case passes on the
   fixed list and fails against `HEAD`'s list ("the produced-files list never
   names server.pid"), checked by restoring the pre-fix recipe in place and
   then restoring the fixed copy. Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i3/` (`probe.log` sections
   A–B, `scripts/probe.sh`).
17. R45's checks: three mutations run against the whole file. Replacing step
   2's claim guard with `|| true` fails
   `test_a_claim_that_cannot_be_written_is_reported` (the stub ends the
   session as the claim is written, and the run then stops at "could not
   stream …" instead of "could not claim …"); moving the final cleanup's
   claim release above the pipe stop fails
   `test_the_claim_is_released_only_after_the_pipe_is_stopped`; and deleting
   the manifest example's `recording.webm` line fails
   `test_web_ui_produced_files_list_names_the_files_a_failed_run_keeps`. Each
   case passes on the unmodified files (187 passed). The manifest case was
   first written against the whole `## Manifest format` section, where the
   `## Commands` ffmpeg line already names `recording.webm`, and passed with
   the example's line deleted; the section is now read from the indented
   `    ## Files` heading. Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i4/` (`probe.log`).
18. R46's checks: a mutation sweep of ~55 weakenings of the kept recipe
   guarantees (every `test -s` stage-input check weakened to `-e`, the
   `render_fail`/guard lines deleted, the claim and cleanup order moved, the
   exact-session handles made bare) found twelve survivors — eight benign by
   design (listed in R46), four real (the gif, cast and webm checks, and the
   CLI preamble's `mkdir` guard) — and the two final-mp4 deletions, checked
   separately, were real too. Each real one is now caught by exactly one new
   case, and those cases pass on the unmodified recipes (195
   passed): the gif, cast and webm checks weakened to `-e` fail
   `test_render_names_a_renderer_that_writes_no_gif[0-byte-file]`,
   `test_render_says_when_there_is_no_cast[0-byte-file]` (both recipes) and
   `test_web_ui_finalize_says_when_there_is_no_webm[0-byte-file]`; deleting
   the final mp4 check fails `test_render_names_an_encoder_that_writes_no_mp4`
   (both recipes); and weakening the CLI preamble's `mkdir` guard to `|| true`
   fails `test_cli_preamble_refuses_an_uncreatable_capture_dir`. Verified live
   with the recipes' own blocks: a 0-byte cast → real agg "Error: empty file"
   → "agg failed on the cast — is 'agg' installed?"; a 0-byte gif → real
   ffmpeg "Invalid data found" → "ffmpeg failed on the gif"; a 0-byte webm →
   real ffmpeg "EBML header parsing failed" → "ffmpeg failed on the driver's
   webm"; and an `ffmpeg` that exits 0 and writes nothing → rc 0 with a
   0-byte `recording.mp4` once the final check is removed. Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i5/` (`probe.log`,
   `README.md`, `scripts/`).
19. R47's checks: each recipe's own step-0 clear run verbatim over a capture
   directory seeded with every artifact its produced-files list names leaves
   exactly one artifact behind — `manifest.md` (plus `driver.mjs` in the
   web-UI recipe, kept on purpose as the run's input). Both recording
   recipes' capture blocks then run end to end with the previous manifest and
   mp4 seeded and a failing recorder: the mp4 goes and the manifest stays,
   naming two files that no longer exist. After the fix the same probes clear
   it, and the nominal flows were re-run live in this container with real
   tmux 3.2a + asciinema 2.1.0: the tmux recipe rc 0 (a ~3 KB cast,
   `recorder.status` 0, 35-byte transcript, previous manifest and mp4 gone,
   no recorder session left) and the CLI scaffold rc 0 (a 162-byte cast
   holding the recorded command, status 0, previous manifest and mp4 gone).
   The five new cases and the tightened web-UI cleanup case fail against the
   pre-fix recipes and pass on the unmodified ones. Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i6/` (`probe.log`,
   `README.md`, `scripts/`).
20. R48's checks: a mutation sweep of 39 weakenings over the kept recipe
   scope (guards deleted, `test -s` → `-e`, handles made bare, orderings and
   bounds moved) found two real survivors — the web-UI port pre-check's
   per-attempt bounds and the driver block's manifest — plus the benign ones
   listed in R48. Live: the recipe's own pre-check block run against a socket
   that accepts and never replies exits 1 in 5.0 s with "could not check …
   (exit 28; …)" and, with the flags removed, is still blocked in curl at
   20 s; the driver block run with a seeded manifest and a driver that throws
   exits 1 leaving `driver.mjs`, `node_modules` and the earlier attempt's
   `manifest.md` (whose `## Files` names the deleted `recording.mp4`), and
   with `./manifest.md` in the cleanup leaves only the input and the link.
   Both mutations now fail exactly the new case
   (`test_the_port_pre_check_is_bounded`,
   `test_web_ui_driver_failure_is_reported_and_clears_stale_outputs`) and
   pass on the unmodified files. Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i7/` (`probe.log`,
   `README.md`, `scripts/`).
21. R49's checks: three mutations of the recipes, each run against the whole
   test file. Deleting the CLI preamble's `case "<capture-dir>"` guard leaves
   the file green (**201 passed**, before the new cases) and the preamble, run
   with a relative `<capture-dir>` from a scratch cwd, exits **0** with
   `relcap/run` created
   (the scaffold's copy of the guard refuses the same path, but only after
   this block has written); with the new
   `test_cli_preamble_refuses_a_relative_capture_dir` the same mutation fails
   exactly that case (**1 failed, 203 passed**) and the unmodified preamble
   passes. Replacing all three `pwd -P` code sites in step 2 (`claim_dir`,
   `claimed_dir`, `vd`) with `pwd` leaves the file green (**201 passed**, the
   pre-fix count) and makes both symlink cases fail (**2 failed, 202 passed**);
   on the unmodified recipe they pass. Moving the web-UI start block's cleanup
   `rm` below the port pre-check leaves the file green (**204 passed**, the
   count before this case) and makes
   `test_a_refused_start_clears_the_previous_pid` fail (**1 failed, 204
   passed**); the refusal message's "this step cleared it" is false in that
   state, and the seeded pid survives for the teardown to read. On the
   unmodified recipes the file is **205 passed** at that point (206 with R50's
   case). The recipe text is unchanged in all three.
22. R50's checks, live on real tmux 3.2a with a private `TMUX_TMPDIR` and the
   recipe's own step-2 block (a `tmux` wrapper ends the target as the claim
   write is issued and leaves pm's grouped `pm-test~1` behind):
   `show-options`/`set-option -t '=pm-test:0.0'` round-trip on the real session
   and answer "no such session: =pm-test:0.0" with only the grouped session on
   the server; a plain `set-option -t pm-test @pm_capture_dir <cap>` in that
   state exits **0** and the probe log shows the claim on `pm-test~1`
   immediately after the call. The pre-fix block therefore exited 1 at
   "could not stream pm-test:0.0 … — check that pane exists" (the guard never
   fired); the fixed block exits 1 at "could not claim … on pm-test — the
   session went away" and writes nothing on `pm-test~1`. Nominal, with both
   `pm-test` and `pm-test~1` on the server, the fixed block exits 0 and the
   claim is on `pm-test`, not on the grouped session beside it. Mutation: every
   claim handle reverted to the bare form fails
   `test_a_claim_written_to_a_prefix_session_is_reported` (rc 1 at
   "could not stream …"), `test_tmux_session_handles_are_exact` and
   `test_the_claim_is_released_only_after_the_pipe_is_stopped` (**3 failed**),
   while `test_a_claim_that_cannot_be_written_is_reported` still passes (the
   `claimgone` shape fails a bare write too). On the unmodified recipes the
   file is **206 passed**.
23. R51's checks: the recipe's own two fenced blocks, extracted and run with
   real `node` 22 in this container (`probe.log` sections A-E). (A) `node` on a
   0-byte `.mjs` exits **0** — an empty file is a valid ES module. (C) With a
   0-byte `driver.mjs`, the **pre-fix** (committed) driver block exits **0**
   printing "playwright ok" and leaves only the driver and the `node_modules`
   link — a step reported as success that ran nothing. (D) The unchanged
   finalize block then exits 1 with "there is no webm to transcode — the
   driver wrote no video; re-run step 2 and check the driver's recordVideo
   option", the remedy that cannot work. (B/E) Post-fix, the same 0-byte
   `driver.mjs` — and the absent file — both stop at "there is no driver.mjs
   in … (or it is empty)". Mutation: the check reverted to `-f` in place fails
   exactly `test_web_ui_driver_block_refuses_a_missing_driver[0-byte-file]`
   (**1 failed, 1 passed**) with rc 0 and "playwright ok"; restored, both
   shapes pass and the file is **207 passed**. Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i10/` (`probe.log`,
   `mutation-check.log`, `suite.log`, `README.md`, `scripts/`).
24. R52's checks: both recipes' own `agg` install blocks (byte-identical)
   extracted and run in this container with a 500-byte truncation of the real
   agg 1.9.0 release binary in `~/.local/bin`, ahead on PATH (`probe.log`
   sections A-E). The truncated file answers `agg --version` with rc **126**
   while `command -v agg` resolves it. Pre-fix (committed `HEAD`): install
   rc **0** with the file unchanged, render rc 1 with "render produced no mp4
   — agg failed on the cast — is 'agg' installed?", install again rc **0**
   with the file still 500 bytes — the remedy that message names, doing
   nothing. Post-fix: install replaces it with agg 1.9.0 (13,797,992 bytes),
   the render exits 0 with a 3,371-byte mp4 (`ffprobe`: `h264,1580,1120`),
   and a second install leaves the working binary untouched (same mtime and
   size, so R16's protection holds). A download that still does not run is
   named and stopped (rc 1, "the agg on PATH (…) does not run — remove it").
   Mutation: HEAD's recipes restored in place fail exactly the two new cases
   and the guard-text assertion (**6 failed** — two cases and one text check,
   per recipe); restored, **6 passed**, and the whole file is **211 passed**
   (was 207). Evidence: `$(pm qa captures-path pr-b19db15)/review-ebd1-i11/`
   (`probe.log`, `mutation-check.log`, `suite.log`, `README.md`, `scripts/`).
25. R53's checks: the web-UI driver block's own fenced block, extracted and run
   in this container with the earlier attempt's `http.log`/`sse.log` seeded
   beside its other stale outputs and a driver that throws (`probe.log`, the
   pre-fix and post-fix runs). Pre-fix: the block exits 1 leaving `driver.mjs`,
   `node_modules`, `http.log` and `sse.log` in the capture directory — the
   protocol logs the manifest presents as this run's. Post-fix: only the input
   and the link survive, and the block's own "the driver failed" message is
   unchanged. The extended case was run against the pre-fix recipe first (it
   fails on `http.log`) and after the fix (it passes); file **211 passed**.
   Evidence: `$(pm qa captures-path pr-b19db15)/review-ebd1-i12/`
   (`probe.log`, `suite.log`, `README.md`, `scripts/`).

26. R54's checks: both recipes' own blocks extracted verbatim and run in this
   container on real tmux 3.2a (a private `TMUX_TMPDIR`) with a mode-500
   capture directory — pre-fix the tmux block exits 1 at "recorder exited
   before it drew — see the cast and …/recorder-stderr.log" and the CLI
   scaffold at "asciinema wrote no cast — see …/recorder-stderr.log", each
   naming a file that cannot exist, with the directory empty in both; post-fix
   both exit 1 at "capture directory … cannot be written — check the path and
   its permissions" and the tmux block leaves the target session untouched (no
   recorder started, the shared `pm-recorder` clear not reached) and the CLI
   block starts no scaffold server at all. Step 2 alone, with the capture
   directory missing and then mode-500: pre-fix rc 0 with the claim on the
   session and no transcript, post-fix rc 1 naming the directory with no claim
   and no pipe. The nominal path was re-run after the edit (step 0 rc 0,
   directory created; the stub suite's two `*_recording_completes` cases cover
   the rest). Mutation checks: restoring the pre-fix recipes fails exactly the
   five new guard cases; deleting the CLI readiness timeout's `capture-pane`
   line fails exactly the strengthened case; narrowing `/* | "~"/*` to `/*` in
   both recipes fails exactly the two `~/` cases. File **218 passed**; full
   suite **4612 passed, 1 skipped, 92 deselected, 0 failed** (401.91 s).
   Evidence: `$(pm qa captures-path pr-b19db15)/review-ebd1-i13/`.

27. R55's checks: the web-UI recipe's four fenced blocks extracted verbatim
   (`step 1`, the driver block, the finalize block, the Layer 2 block) and run
   in this container against a mode-500 capture directory holding an earlier
   run's `recording.mp4`/`recording.webm`/`manifest.md`/screenshot, with stub
   `pm`/`curl`/`my-app`/`ffmpeg` and the real `node`/`ln`. Pre-fix: step 1 rc
   **0** with the app launched, no `server.pid` and every earlier file still
   in place; the driver block rc 1 with "playwright does not resolve beside
   driver.mjs" (and `ln`'s "Permission denied" above it); the finalize block
   rc 1 with "transcode produced no mp4 — ffmpeg failed on the driver's
   webm"; the Layer 2 block rc **0** with neither log written. Post-fix: all
   four rc 1 at "capture directory … cannot be written", the app never
   started, no curl/ffmpeg/link attempted. Mutation: the pre-fix recipe
   restored in place fails exactly the four new cases (and passes the three
   R54 cases, which are unaffected); restored again, all seven pass. File
   **222 passed** (was 218). Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i14/`.

28. R56's checks: the tmux recipe's own step-2 block extracted verbatim, run
   from a worker directory holding `relcap`, against a stub `tmux` that
   resolves session targets like 3.2a and runs `pipe-pane` commands in the
   *session's* directory. Pre-fix: rc **0**, the claim written on the worker's
   canonical `…/worker/relcap`, and the session's shell answering "cannot
   create relcap/transcript.log: Directory nonexistent" — no transcript in
   either directory. Post-fix: rc 1 at "relcap must be an absolute path (or
   start with ~/) …" with no claim and no pipe; the same block with an
   absolute path still exits 0, claims the directory and writes the
   transcript. Mutation: the pre-fix recipe restored in place fails exactly
   `test_step_two_refuses_a_relative_capture_dir` (rc 0); restored again, the
   file's **223 passed** (was 222). Related suites
   (`test_qa_artifact_web_ui_recording`, `test_qa_instructions`,
   `test_qa_loop`) **175 passed**; full suite **4617 passed, 1 skipped, 92
   deselected, 0 failed** (404.55 s). Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i15/`.

29. R57's checks: both recipes' render blocks extracted verbatim and run in
   this container with real agg 1.9.0 and ffmpeg 4.4.2. Pre-fix, a mode-500
   capture directory holding a cast: rc 1 with "render produced no mp4 — agg
   failed on the cast — is 'agg' installed?", the earlier run's
   `recording.mp4` surviving the failed `rm`, and the recipe's own install
   block exiting 0 without downloading or changing anything (the loop the
   message prescribes); a missing capture directory: "there is no cast to
   render (the recording wrote nothing)". Post-fix, the same two shapes exit 1
   with "capture directory … cannot be written — …" / "… does not exist —
   …", naming the directory, with no `agg` run and the earlier run's outputs
   untouched, and a healthy render still exits 0 with an ffprobe
   `h264,1580,1120` mp4. Mutation: HEAD's render blocks restored in place
   fail exactly the four new cases
   (`test_render_{refuses_a_capture_dir_it_cannot_write,names_a_missing_capture_dir}`
   × both recipes); restored again, the file's **227 passed** (was 223);
   full suite **4621 passed, 1 skipped, 92 deselected, 0 failed**
   (393.79 s). Evidence:
   `$(pm qa captures-path pr-b19db15)/review-ebd1-i16/`.

30. R58's check: the web-UI driver block extracted verbatim and run in this
   container (uid 1000) against a mode-400 capture directory. Pre-fix: rc 1
   with bash's `cd: … Permission denied` and "capture directory … does not
   exist — create it and run step 1" — the directory is there. Post-fix: rc 1
   with "capture directory … cannot be written — … check the path and its
   permissions", and a missing directory still gets "does not exist". The new
   case `test_web_ui_driver_block_refuses_a_capture_dir_it_cannot_enter` fails
   against the pre-fix block (recipe restored in place) and passes after;
   restored again, the file's **228 passed** (was 227).

31. R59's three mutation checks, each applied to a throwaway copy of the tree
   and run against the whole file: removing the `-x` half from all ten
   capture-directory guards (`all_x`) fails exactly the ten `no-search-bit`
   cases and leaves every mode-500 case green; removing the render blocks'
   pre-render `rm` (`render_rm`) fails the two missing-encoder cases, which
   now seed a previous run's mp4 and gif; removing the Layer 2 block's
   `kill "$SSE_PID"` (`sse_kill`) fails the new execution case, whose stub
   reader traps `TERM`. The live probe
   (`$(pm qa captures-path pr-b19db15)/review-ebd1-i18/scripts/probe.sh`)
   reproduces each pre-fix behaviour with the recipes' own blocks and a
   mode-600 capture directory.

## Evidence notes

- Review loop ebd1 i18 (R59) mutated the three guards no case proved, in this
  container (uid 1000) with the recipes' own fenced blocks extracted verbatim.
  A mode-600 capture directory (`rw-------`: the write bit and no search bit)
  passes `[ -w ]` and is refused only by the guard's `[ -x ]` half; with that
  half removed from all ten sites the file stayed green (228 passed) and the
  blocks ran on: tmux step 0 cleared the shared `pm-recorder` session and then
  exited 1 on `rm`'s "Permission denied", the render block said "there is no
  cast to render (the recording wrote nothing)" for a cast that is there, the
  web-UI start block launched the app and exited 0, and the Layer 2 block
  exited 0 having written neither log. With the `-x` half present every block
  refuses with its own "cannot be written — … check the path and its
  permissions" and makes no tmux call. The render block's pre-render `rm` is
  load-bearing on the missing-encoder path alone (that stop exits before
  `agg` and never calls `render_fail`): with it removed, a seeded previous
  mp4 and gif survive the same rc-1 message. The Layer 2 `kill "$SSE_PID"` is
  the block's normal stop for its `curl -N` reader: with it removed the block
  returns while the reader still writes into `sse.log` (a `TERM`-trapping
  stub never records the stop). Tests: file **239 passed** (was 228); the
  three mutations (`all_x`, `render_rm`, `sse_kill`) each fail exactly their
  cases. Evidence: `$(pm qa captures-path pr-b19db15)/review-ebd1-i18/`
  (`probe.log`, `probe-webui.log`, `mutation-check.log`, `suite.log`,
  `README.md`, `scripts/`).
  No `pm_core/` change; the dropped helper/prompt/verifier work stays
  dropped.

- Review loop ebd1 i16 (R57) reproduced the render block's unwritable- and
  missing-capture-directory misdiagnoses in this container with real agg
  1.9.0 (release binary, `agg --version` → 1.9.0) and ffmpeg 4.4.2, and the
  recipes' own render blocks extracted verbatim: a mode-500 capture directory
  holding a minimal valid cast gives rc 1 with "render produced no mp4 — agg
  failed on the cast — is 'agg' installed?" (and the earlier run's mp4
  survives), a missing directory gives "there is no cast to render (the
  recording wrote nothing)", and the recipe's install block run with a working
  agg on PATH exits 0, creates no `~/.local`, and changes nothing. Post-fix
  the same blocks stop with "capture directory … cannot be written — …" /
  "… does not exist — …" before the `rm`, and a healthy render still produces
  an H.264 mp4 (ffprobe `h264,1580,1120`, rc 0). Evidence:
  `$(pm qa captures-path pr-b19db15)/review-ebd1-i16/` (`probe.log`,
  `mutation-check.log`, `suite.log`, `README.md`, `scripts/`).
- Review loop ebd1 i13 (R54) reproduced the unwritable-capture-directory
  misdiagnosis in this container. Both recipes guard the directory by
  creating it, and `mkdir -p` answers 0 for one that already exists, so a
  mode-500 capture directory passed the guard and every write into it failed
  in the pane: the pre-fix tmux capture block exits 1 at "recorder exited
  before it drew — see the cast and <capture-dir>/recorder-stderr.log" and the
  pre-fix CLI scaffold at "asciinema wrote no cast — see
  …/recorder-stderr.log", with the directory empty in both cases (no cast, no
  stderr log, no status). The tmux recipe's step 2, pasted on its own, is the
  same hole for a path that is not there: it exited 0 having taken the
  capture-directory claim on a directory nothing can be written into and
  attached a pipe that wrote nothing. After the fix both recipes refuse the
  directory where the path is known ("capture directory … cannot be written —
  check the path and its permissions"), before the shared recorder session is
  cleared, and step 2 refuses it before the claim; the nominal flows were
  re-run (tmux step 0 rc 0 with the directory created, and the stub suite's
  completion cases). Two coverage gaps closed in the same pass: the CLI
  readiness timeout's pane save was unpinned (the message named the file and
  nothing required it — deleting the `capture-pane` line left the file green
  at 211 passed), and the `~/` half of both absolute-path guards was unpinned
  (narrowing the pattern to `/*` left the file green and refused a
  documented-valid path). Evidence:
  `$(pm qa captures-path pr-b19db15)/review-ebd1-i13/` (`probe.log`,
  `mutation-check.log`, `suite.log`, `README.md`, `scripts/`). No `pm_core/`
  change; the dropped helper/prompt/verifier work stays dropped.
- Review loop ebd1 i14 (R55) reproduced the same unwritable-directory
  misdiagnosis in the *web-UI* recipe, which R54 did not reach: with a
  mode-500 capture directory the start block exits 0 (app launched, no
  `server.pid`, the earlier run's evidence untouched), the driver block
  reports Playwright not resolving after `ln` was refused, the finalize block
  blames the driver's webm, and the Layer 2 block exits 0 having written
  neither log. The four blocks now refuse the directory where it is
  established or entered; the four new execution cases fail against the
  pre-fix recipe and pass after the fix. Evidence:
  `$(pm qa captures-path pr-b19db15)/review-ebd1-i14/` (`probe.log`,
  `mutation-check.log`, `suite.log`, `README.md`, `scripts/`). No `pm_core/`
  change; the dropped helper/prompt/verifier work stays dropped.
- Review loop ebd1 i15 (R56) reproduced the relative-path misplacement of
  step 2's transcript in this container with the recipe's own step-2 block
  extracted verbatim and a stub `tmux` that resolves session targets like
  3.2a and runs `pipe-pane` commands in the *session's* directory (the fact
  step 0's prose records). With `<capture-dir>` = `relcap` beside the worker,
  the pre-fix block exits **0**, takes the claim on the worker's canonical
  `…/worker/relcap`, and the session's shell answers "cannot create
  relcap/transcript.log: Directory nonexistent" — no transcript in either
  directory, so step 5's `test -s` reports "transcript.log is empty — the
  pipe-pane stream never wrote to it". Post-fix the same run exits 1 with
  "relcap must be an absolute path (or start with ~/) — the transcript pipe's
  command runs in the pm session's directory …" and takes no claim; the same
  block with an absolute path still exits 0, claims the directory and writes
  the transcript (`probe.log` sections A-C). Steps 4 and 5 and the render
  blocks were checked and dismissed: their capture-dir uses are worker-side
  redirects and reads, so they resolve in the worker's own shell. File **223
  passed** (was 222); related suites 175 passed; full suite **4617 passed, 1
  skipped, 92 deselected, 0 failed** (404.55 s). Evidence:
  `$(pm qa captures-path pr-b19db15)/review-ebd1-i15/` (`probe.log`,
  `mutation-check.log`, `suite.log`, `README.md`, `scripts/`). No `pm_core/`
  change; the dropped helper/prompt/verifier work stays dropped.

- Review loop ebd1 i12 (R53) found the driver retry's attempt cleanup left the
  Layer 2 protocol logs. Reproduced with the recipe's own step-2 block in this
  container: with `http.log` and `sse.log` seeded beside the earlier attempt's
  mp4/webm/trace/DOM/screenshots/manifest and a driver that throws, the
  pre-fix block exits 1 with its "the driver failed" message and leaves both
  logs in the capture directory; with `./http.log ./sse.log` in the cleanup
  the directory holds only `driver.mjs` and the `node_modules` link. The same
  pass corrected the test module's docstring, which still said the `agg`
  install was "guarded on `command -v agg`" (the pre-R52 state), and the tmux
  recipe's step-2 comment, which claimed every claim handle takes the exact
  `=…:0.0` form even though the cross-session scan correctly keeps a bare
  `-t "$s"` — its names come from `list-sessions`, where exact match wins, and
  a grouped `<base>~N` session carries no claim of its own. Evidence:
  `$(pm qa captures-path pr-b19db15)/review-ebd1-i12/` (`probe.log`,
  `suite.log`, `README.md`, `scripts/`). No `pm_core/` change; the dropped
  helper/prompt/verifier work stays dropped.
- Review loop ebd1 i11 (R52) reproduced the inert `agg` remedy in this
  container with both recipes' own fenced install/render blocks and a
  500-byte truncation of the real agg 1.9.0 release binary in `~/.local/bin`
  ahead on PATH: the file resolves (`command -v agg` succeeds) and does not
  run (`agg --version` rc 126). The committed install block exits **0**
  leaving it in place, the render fails with "agg failed on the cast — is
  'agg' installed?", and pasting the install block again — the only remedy
  that message names — exits 0 again, so the worker loops. With the guard on
  `agg --version` the block replaces the truncated binary with agg 1.9.0 and
  the same render block exits 0 with a playable H.264 mp4; a working agg is
  left untouched (same mtime and size). A download that arrives broken is
  named ("the agg on PATH (…) does not run — remove it …") and stops.
  Mutation (HEAD's recipes) fails exactly the two new cases and the guard
  text; file **211 passed**. Evidence:
  `$(pm qa captures-path pr-b19db15)/review-ebd1-i11/` (`probe.log`,
  `mutation-check.log`, `suite.log`, `README.md`, `scripts/`).
  Also checked and dismissed this pass, so a later one does not re-open it: a
  host with no `asciinema` at all needs no guard. Both recipes' pane command
  redirects the command's own stderr into `recorder-stderr.log`, so the
  shell's "asciinema: command not found" lands in the file the failure
  messages name (verified with a PATH without asciinema: the log holds
  `bash: line 1: asciinema: command not found` and `recorder.status` is 127),
  and the recipe already documents the `| tee` fallback for that host.

- Review loop ebd1 i10 (R51) reproduced the empty-driver false success in this
  container with the recipe's own two fenced blocks and real `node` 22: the
  committed driver block, run with a 0-byte `driver.mjs`, exits **0** and
  prints "playwright ok" (an empty file is a valid ES module, and `node` on
  one exits 0), leaving only `driver.mjs` and the `node_modules` link; the
  unchanged finalize block then exits 1 with "there is no webm to transcode —
  the driver wrote no video; re-run step 2 and check the driver's
  recordVideo option", a remedy a re-run of step 2 cannot satisfy. Post-fix
  the block stops on both shapes ("there is no driver.mjs in … (or it is
  empty)"). The check is `-s`; no other input check in the three recipes
  needed changing (all the stage-input checks are already `-s`; `-d`/`-e` are
  used only for the capture directory and the `node_modules` link, where
  emptiness is not a state). Mutation (back to `-f`) fails exactly the new
  0-byte case; file **207 passed**. Evidence:
  `$(pm qa captures-path pr-b19db15)/review-ebd1-i10/` (`probe.log`,
  `mutation-check.log`, `suite.log`, `README.md`, `scripts/`).
  Also checked and dismissed this pass, so a later one does not re-open it:
  every tmux pane gets `TMUX` set, and a *bare* `tmux attach` in a pane is
  refused ("sessions should be nested with care, unset $TMUX to force", rc 1,
  verified on tmux 3.2a in a private `TMUX_TMPDIR`, including through a plain
  `sh -c`). The recipe's form is not affected — `asciinema rec -c 'tmux attach
  -t =X'` in a pane attaches and renders the target, verified in isolation and
  by a full run of the recipe's capture block (rc 0, the cast holds the
  target's screen and "[detached (from session pm-test)]",
  `recorder.status` 0) — so no change.
- Review loop ebd1 i9 (R50) verified the claim handles live in this container
  (real tmux 3.2a, private `TMUX_TMPDIR`, the recipe's own step-2 block with a
  `tmux` wrapper that ends the target at the claim write and leaves pm's
  grouped `pm-test~1`): `show-options`/`set-option -t '=pm-test:0.0'`
  round-trip on the real session and answer "no such session: =pm-test:0.0"
  with only the grouped session on the server, while a plain
  `set-option -t pm-test @pm_capture_dir <cap>` in that state exits **0** and
  puts the claim on `pm-test~1` (the probe log records the option on the
  grouped session right after the call). Pre-fix the block exited 1 at
  "could not stream pm-test:0.0 … — check that pane exists"; post-fix it exits
  1 at "could not claim … on pm-test — the session went away" and writes
  nothing on the grouped session. Nominal (both sessions present): rc 0, the
  claim on `pm-test`. Mutation (every claim handle bare): the new case and the
  two updated ones fail (**3 failed**), the `claimgone` case still passes.
  File **206 passed**. Evidence:
  `$(pm qa captures-path pr-b19db15)/review-ebd1-i9/` (`probe.log`,
  `mutation-check.log`, `suite.log`, `README.md`, `scripts/`).
- Review loop ebd1 i8 (R49) mutated the three guards the kept recipes carry
  and found no case behind any of them. (1) The CLI preamble's absolute-path
  guard: deleting its `case` block left the whole file green (201 passed),
  and the preamble run with a relative `<capture-dir>` from a scratch cwd
  exited 0 with `relcap/run` created and its `rm` executed there — the state
  the guard exists for, in the block a worker following the recipe top-down
  pastes before any recording form (the scaffold's copy refuses the path, but
  only after the preamble has written). The new case runs the preamble block
  itself (extracted by a new `_cli_preamble_block` helper, shared with the
  existing uncreatable-dir case) and fails with the guard removed.
  (2) Step 2's `pwd -P`: replacing all three code sites with `pwd` also left
  the file green (201 passed) even though the prose claims the symlink
  collapse and only the `~/` spelling had a case. The new pair runs the whole
  tmux block with the capture directory reached through a symlink and
  asserts the cross-session refusal (the other session's claim stored as the
  real path) and the same-session retry (not refused); both fail under the
  `pwd` mutation. (3) The web-UI start block's cleanup-before-pre-check
  order: moving the `rm` below the port pre-check left the file green (204
  passed at that point, the count before this case), and a refused start then
  leaves the previous run's `server.pid` — which the recipe's teardown reads
  — while the refusal message says the step cleared it. The new
  `test_a_refused_start_clears_the_previous_pid` seeds the pid and runs the
  start block against a taken port; it fails under the reorder and passes on
  the unmodified recipe. The recipes themselves are unchanged — these were
  coverage holes, not behavior bugs. Also corrected `qa.md`'s driver-step
  edge case, which still enumerated the attempt cleanup without
  `manifest.md` (R48). Tests: file 205 pass (was 201); each mutation fails
  exactly its case and those cases pass on the unmodified files. No
  `pm_core/` change; the dropped helper/prompt/verifier work stays dropped.
- Review loop ebd1 i7 (R48) swept the kept recipe scope by mutation — 39
  weakenings, including a control set that the file catches — and two
  survivors were real. The web-UI port pre-check's `--connect-timeout 2
  --max-time 5` is what makes its own "exit 28" diagnosis reachable (curl has
  no default deadline for a server that accepted the connection), and nothing
  pinned it: the stub `curl` answers by mode, not by arguments, so deleting
  the flags left the whole file green (200 passed). Verified live against a
  socket that accepts and never replies: the shipped probe exits 1 in 5.0 s
  with "could not check … (exit 28; only 'connection refused', 7, means the
  port is free) …", and without the flags curl is still blocked at 20 s — the
  unbounded wait this PR removes everywhere else, in the block every capture
  runs first. The stub now logs each call's argv and the new case pins the
  first (the pre-check). The second: step 2's attempt cleanup clears this
  attempt's mp4, webm, trace, DOM dump and screenshots but left
  `manifest.md`, so a retried driver that fails ends with the earlier
  attempt's manifest naming the `recording.mp4` the cleanup just deleted —
  R47's disagreement, in the one block R47 did not touch (verified with the
  recipe's own block: only `driver.mjs`, `node_modules` and the manifest
  survive a failing retry; after the fix, only the input and the link). The
  sweep's other survivors are benign and listed in R48 (notably step 5's cast
  `-s`, which no reachable state can distinguish: asciinema 2.1.0 writes its
  115-byte header the moment recording starts, verified with `-c 'sleep 3'`
  and `-c 'true'`). No `pm_core/` change; the dropped helper/prompt/verifier
  work stays dropped. Evidence:
  `$(pm qa captures-path pr-b19db15)/review-ebd1-i7/`.
- Review loop ebd1 i6 (R47) ran each recipe's own step-0 clear verbatim over
  a capture directory seeded with every artifact its produced-files list
  names. Exactly one artifact survived in every recipe: `manifest.md` — the
  document that says what the capture is — while `driver.mjs` survived in the
  web-UI recipe on purpose (it is the run's input, not its evidence). Both
  recording recipes' capture blocks then run end to end with the previous
  manifest and `recording.mp4` seeded and a failing recorder (`norec`): the
  mp4 is gone and the manifest is still there, its `## Files` naming
  `recording.cast` and `recording.mp4`, neither of which exists — a manifest
  that disagrees with the directory it describes. After the edit the same
  probes clear it, and the nominal flows were re-run live in this container
  with real tmux 3.2a + asciinema 2.1.0: the tmux recipe rc 0 (cast,
  `recorder.status` 0, transcript, previous manifest and mp4 gone, no
  recorder session left) and the CLI no-TTY scaffold rc 0 (cast holding the
  recorded command, status 0, previous manifest and mp4 gone). The five
  new/tightened cases fail against the pre-fix recipes and pass on the
  unmodified ones. Evidence:
  `$(pm qa captures-path pr-b19db15)/review-ebd1-i6/` (`probe.log`,
  `probe-pre-fix.log`, `mutation-check.log`, `live-nominal.log`, `README.md`,
  `scripts/`). No `pm_core/` change; the dropped helper/prompt/verifier work
  stays dropped.
- Review loop ebd1 i5 swept the kept recipe guarantees by mutation (R46):
  ~55 weakenings, each applied to a copy of the recipe tree and run against
  the whole test file. Twelve survived, and **every one of them was a
  `test -s` stage-input check weakened to `test -e`** (plus the CLI
  preamble's `mkdir` guard, in the one fenced block no case executed) — i.e.
  the file proved that each stage names a *missing* input but not that it
  rejects an *empty* one, which is the state each message actually names
  ("the recording wrote nothing", "or a 0-byte gif"). Verified live with the
  recipes' own blocks: a 0-byte cast reaches real agg ("Error: empty file")
  and the run says "agg failed on the cast — is 'agg' installed?"; a 0-byte
  gif and a 0-byte webm reach real ffmpeg ("Invalid data found") and the run
  blames the encoder; and with the final mp4 check removed an `ffmpeg` that
  exits 0 and writes nothing leaves a 0-byte `recording.mp4` with **rc 0**.
  The no-cast, no-gif and no-webm cases are now parametrized over both
  shapes (with an `ffmpeg` stub that models a missing *and* an empty input),
  `test_render_names_an_encoder_that_writes_no_mp4` covers the final check,
  and `test_cli_preamble_refuses_an_uncreatable_capture_dir` runs the
  preamble block. Each mutation fails exactly the new case and the unmodified
  recipes pass (195). The sweep's other survivors are benign and are listed
  in R46. Evidence: `$(pm qa captures-path pr-b19db15)/review-ebd1-i5/`.

- Review loop ebd1 i4 found the manifest example one section over from R44
  (R45) and two more guarantees no case proved, in the same shape as i1–i3.
  The web-UI manifest's `## Files` example listed `node_modules` (pinned by
  `test_web_ui_produced_files_list_names_the_playwright_link`) but neither of
  the two files R44 had just added to the produced-files list, and it has no
  `<any extra file>` catch-all like the recording recipes' examples — so the
  worker copying the example still left them out. Step 2's "could not claim"
  guard and the cleanup order (this run's pipe stop before the claim release,
  which the Files table above describes as R24's design) were both unproven:
  the guard replaced with `|| true`, and the release moved above the stop,
  each left all 185 cases green. All three are pinned now, and each mutation
  fails exactly the case it names.

- Review loop ebd1 i3 found one more guard no case proved (R44), in the same
  shape as R43's harness findings: **step 1's empty-target refusal was the
  only one of the four `$TARGET` guards without an execution case**, and
  deleting it left the whole file green because the run still fails — just at
  the readiness deadline, with "pm session  did not appear within 60s" naming
  an empty session. The new case runs the recipe's own block with
  `pm session name` printing nothing; with the guard removed it fails on the
  message (`probe.log` section A). R44's second half is a manifest gap, not a
  code one: `server.pid` and the kept `recording.webm` were absent from the
  web-UI produced-files list, so the manifest and the directory could
  disagree for exactly the runs the recipe tells the worker to stop
  (a failed driver, a failed transcode); the new list case fails against
  `HEAD`'s list (`probe.log` section B). Evidence:
  `$(pm qa captures-path pr-b19db15)/review-ebd1-i3/`.
- Review loop ebd1 i2 also audited the harness itself (R43). **Three
  guarantees the file claimed were not provable, and one comment claimed a
  guard that did not exist**: the stub `tmux`'s `capture-pane` ignored its
  target and always printed the pane, so a recipe that saved the pane after
  its teardown still wrote content (real tmux answers "can't find session"
  once the recorder is killed — the reason the saves come first); the two
  driver-guard fixtures had no `driver.mjs` in the cwd, so the block stopped
  at R32's missing-driver check before it could link and the
  `node_modules`-in-the-cwd assertion could not fail; and `_run_block`'s
  comment claimed the recipes' bounds were "asserted as text above" although
  no test pinned a bound's value (a 1 s readiness deadline would have passed
  everything). Fixed by modelling `capture-pane` (target resolution and a
  session-gone failure), seeding a `driver.mjs` in those two fixtures, and
  pinning every arithmetic bound at ≥ 10 s with every "within Ns" message
  tied to a bound the code uses; each mutation fails exactly the cases it
  names and those cases pass on the unmodified recipes (183 passed). Evidence:
  `$(pm qa captures-path pr-b19db15)/review-ebd1-i2/` (`probe.log` sections
  G–K).
- Review loop ebd1 i2 verified R42 in this container (the test harness for the
  run; no live tmux needed — the finding is a *guard* that did not guard).
  **The stale-status clear was the one completion guard no test made, and the
  assertion that claimed to was satisfied by a comment**: the tmux exit-status
  test searched everything from `rm -f ` to `new-session`, a range that also
  holds step 1's comment "(verified live — rc 0, cast, `recorder.status` 0,
  transcript, with …)", so deleting `<capture-dir>/recorder.status` from the
  step-0 clear left the file green (178 passed). The false pass it leaves
  open is the PR's own class: with an earlier run's `recorder.status` of `0`
  seeded and a recorder that never writes one (stub mode `detachnostatus`),
  the recipe as shipped exits 1 at "recorder status is missing" and the same
  block with that one `rm` argument removed exits **0** on the previous run's
  status — a recording that never finished reported as a completed one. Both
  tests now derive the status path from the pane command and require the `rm`
  statement itself to remove it, and
  `test_a_stale_recorder_status_is_not_read_as_this_runs` runs the seeded case
  for both recipes (`detachnostatus`/`nostatus`); all four fail against the
  pre-fix recipes and pass with them (180 passed). A 15-mutation sweep of the
  kept recipe guarantees caught thirteen of them and found this one; the
  other uncaught mutation is dropping `--overwrite` from the CLI scaffold,
  which is not a completion guard — step 0 clears the cast first, and
  without the flag a leftover cast makes `asciinema rec` abort loudly, so the
  run fails at its bounded readiness wait instead of passing. Evidence:
  `$(pm qa captures-path pr-b19db15)/review-ebd1-i2/` (`probe.log` sections
  A–F, `README.md`, `scripts/`).
- Review loop ebd1 i1 verified R41 in this container (real tmux 3.2a on a
  private `TMUX_TMPDIR`; the test harness for the run). **The transcript
  pipe's exact target was the one handle no test guarded**: with all fourteen
  `pipe-pane -t "=$TARGET:0.0"` sites made bare, the whole file still passed
  (177 green). On a server holding only the grouped `pm-test~1` (what pm
  leaves behind when the target ends, and the state step 2's exact-session
  assert and the pipe attach can straddle), `has-session -t "=pm-test"`
  exits 1 while `-t pm-test` exits 0, `pipe-pane -t "=pm-test:0.0"` answers
  "can't find session: pm-test", and `pipe-pane -t "pm-test:0.0"` attaches
  to `pm-test~1` and writes its output into the capture directory (65 bytes
  of `grouped-out`). In the harness the same whole block exits **0** with
  the bare handle — a cast, a status and a transcript that came from a
  session pm never started — and 1 at "could not stream …" with the exact
  one. New: the text guard rejects a bare pipe target and requires the `=`
  form, and `test_the_transcript_pipe_targets_the_exact_session` runs the
  block in the new stub mode `pipegap`; both fail against the bare form
  (mutation-checked, the recipe restored afterwards). File 178 pass.
  Evidence: `$(pm qa captures-path pr-b19db15)/review-ebd1-i1/` (`probe.log`
  with the live probe and the mutation check, `scripts/`).
- Review loop 7c9c i11 verified R40 live in this container with the recipes'
  own extracted render blocks. **A renderer that wrote nothing was reported as
  an encoder failure**: with a stub `agg` that exits 0 without writing its
  output (and an `ffmpeg` stub that models the real contract — it fails on a
  missing input), both blocks exited 1 with real ffmpeg's "…recording.cast.gif:
  No such file or directory" above "render produced no mp4 — ffmpeg failed on
  the gif", so the worker is sent to the encoder for an `agg` that wrote
  nothing; post-fix both stop with "render produced no mp4 — agg wrote no gif
  (the renderer reported success and wrote nothing)" and never invoke
  ffmpeg.
  The healthy render is unchanged (rc 0, mp4 written, gif dropped). Evidence:
  `$(pm qa captures-path pr-b19db15)/review-7c9c-i11/` (`probe.log` with the
  pre/post runs of both recipes and the mutation check).
- Review loop 7c9c i10 verified R39 live in this container (real tmux 3.2a,
  private `TMUX_TMPDIR`). Prefix matching: with only `pm-recorder-abc123` on
  the server, `has-session -t pm-recorder` exits 0, `capture-pane -p -t
  pm-recorder` prints its pane, `send-keys -t pm-recorder` delivers, and
  `kill-session -t pm-recorder` kills it and takes the server down; the
  recipe's own step-0 block did the same (rc 0, no message), while the fixed
  block left the session alive. Exact forms: `has-session -t "=pm-recorder"`
  exits 1 and `capture-pane`/`send-keys -t "=pm-recorder:0.0"` fail with only
  the prefix session present, and all four resolve on the real `pm-recorder`.
  `tmux attach -t pm-test` with only `pm-test~1` proceeds while
  `-t '=pm-test'` answers "can't find session". Nominal flow re-run end to
  end with the fixed block: rc 0, 3044-byte cast, `recorder.status` 0,
  126-byte transcript, recorder gone, claim released. Evidence:
  `$(pm qa captures-path pr-b19db15)/review-7c9c-i10/`.
- Review loop 7c9c i9 verified R37 and R38 live in this container (real tmux
  3.2a). R37: `has-session -t pm-test` exits 0 with only `pm-test~1` on the
  server, `-t pm` matches `pm-testX`, and `-t '=pm-test'` exits 1; `pipe-pane
  -t '=pm-test:0.0'` exits 1 while `-t '=pm-test~1:0.0'` exits 0;
  `show-options`/`set-option -t '=pm-test'` answer "no such session:
  =pm-test". With only `pm-test~1` on the default server and a stub `pm`
  whose `pm session` creates nothing, `HEAD`'s capture block exited 0 (cast,
  `recorder.status` 0, transcript) and the fixed block exited 1 at the
  readiness wait; the nominal flow was re-run with the fixed block (rc 0,
  2816-byte cast, status 0, 50-byte transcript, claim released). R38: the
  driver block with no `node` on `PATH` reported "node is not installed — …"
  and created no link; with `node` it printed "playwright ok" and ran the
  driver. Evidence: `$(pm qa captures-path pr-b19db15)/review-7c9c-i9/`.
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
- Review loop 7c9c i5 verified R33 live in this container with real tmux 3.2a
  + asciinema 2.1.0 on a private `TMUX_TMPDIR`, the recipe's own step-3
  recorder and a `tmux` shim that reports step 5's "is the recorder still
  up?" check as true exactly once (the race instant; the failed `send-keys`,
  the wait and the cast/status checks are real tmux). **A quit that raced the
  detach was reported as a truncated recording**: after the fake pm session
  was ended (the attach followed it out; `recorder.status` 0, a 2623-byte
  cast), the pre-fix step 5 exits 1 with "recorder exited before the detach —
  the cast is incomplete, not a finished recording"; the fixed block exits 0
  on the same state. The widened branch does not pass a killed recorder: with
  asciinema SIGKILLed and the session gone too, the fixed block still exits 1
  with "asciinema exited 137 — the cast is incomplete" (status 137, 2386-byte
  cast). The nominal capture block was re-run end to end after the edit (rc
  0, cast + transcript + `recorder.status` 0, claim released). Tests: two new
  execution cases (stub modes `detachboth`/`detachbothbad`), both failing
  against `HEAD`'s step 5 (checked by restoring the pre-fix recipe in place,
  then restoring the post-fix copy); the target-still-alive detach failure and
  the server-prefix case pass unchanged. File 167 pass. Evidence:
  `$(pm qa captures-path pr-b19db15)/review-7c9c-i5/` (`probe.log` with the
  three live runs and the mutation check, `README.md`, `scripts/`). No
  `pm_core/` change; the dropped helper/prompt/verifier work stays dropped.
- Review loop 7c9c i6 verified R34 in this container with the recipes' own
  extracted blocks and stub `tmux`. **The refused CLI block killed a
  concurrent capture's recorder first**: run with `<capture-dir>` = `relcap`
  and a stub `tmux` that logs its argv, `HEAD`'s scaffold calls
  `-L scaffold kill-session -t rec` and *then* refuses with "must be an
  absolute path" — the `-L scaffold` socket name is shared by every CLI
  capture on the host (the recipe says so), so a worker who pasted the block
  with an unsubstituted placeholder ended another run's recorder, which then
  failed as "recorder status is missing". The fixed block makes no tmux call
  at all before the refusal; the tmux recipe's step 0 already guarded first.
  **The pipe-attach failure's claim release was untested**: with
  `tmux set-option -u -t "$TARGET" @pm_capture_dir` deleted from that
  branch, the whole file still passed; with `pipefail` added to the
  release parametrization the same deletion fails exactly that case (and the
  unmodified branch passes, leaving no `claim.pm-test`). The nominal flows
  are unaffected (the guard move changes only the refusal path; the scaffold
  still clears `rec` before `new-session`). Tests: file 169 pass; related
  suites (`test_qa_artifact_web_ui_recording`, `test_qa_instructions`,
  `test_qa_loop`) 175 pass; full suite (`env -u PM_HOST_HOME
  PATH=/usr/bin:/bin pytest tests/ -q --deselect
  tests/test_merge_publish.py --deselect tests/test_signoff_integration.py`,
  with the `markdown` dep on the scratch path) 4563 passed, 1 skipped, 92
  deselected, 0 failed (400 s). Evidence:
  `$(pm qa captures-path pr-b19db15)/review-7c9c-i6/` (`probe.log`, the
  pre/post scaffold blocks and the mutation check). No `pm_core/` change; the
  dropped helper/prompt/verifier work stays dropped.
- Review loop 7c9c i7 verified R35 live in this container (real tmux 3.2a on
  private `TMUX_TMPDIR`s, the recipes' own readiness blocks extracted
  verbatim with `<capture-dir>` substituted and the deadline shortened).
  **The CLI readiness wait cannot pass on a leftover `rec` session**: with a
  `rec` session up (`sleep 60` in its pane) and an empty `recording.cast` —
  what step 0 leaves — the block exits 1 with "recorder did not start within
  30s" and saves the pane; its handle is the cast file, so a leftover
  session only burns the deadline. The **tmux** block, whose handle is the
  recorder pane's content, passes at once on the leftover `pm-recorder`
  (rc 0) — which is why the tmux recipe's counterfactual wording is right
  and the CLI's was not. The stale claim survived in four places after
  R33's correction: `cli-recording.md`'s step-0 prose, this spec's R2,
  `qa.md`'s R3 and `test_stale_recorder_is_cleared_before_start`'s
  docstring; all four now say the clear keeps a re-run from stopping at the
  start check ("could not start the recorder session", R15) and record the
  pre-R15 behaviour as history. No behaviour change and no new assertion —
  the behaviour is already covered by
  `test_recorder_session_that_never_starts_is_reported` and the readiness
  execution cases. Evidence: `$(pm qa captures-path pr-b19db15)/review-7c9c-i7/`
  (`probe.log` with the two live runs, `scripts/` — the extracted readiness
  blocks and the probe driver). No `pm_core/` change; the dropped
  helper/prompt/verifier work stays dropped.
- Review loop 7c9c i8 verified R36 live in this container (real tmux 3.2a,
  private `TMUX_TMPDIR`, the recipes' own capture blocks extracted verbatim
  with `<capture-dir>` substituted). **A refused block ended a concurrent
  capture's recorder**: with a `pm-recorder` session up (`sleep 300`, a
  stand-in for the other run's recorder) and `<capture-dir>` under a regular
  file, the pre-fix tmux block exits 1 with "could not create …" *after*
  `kill-session -t pm-recorder` — `tmux has-session` answers gone — and the
  same for the CLI scaffold's `-L scaffold kill-session -t rec`, so the
  concurrent run then fails as "recorder exited while the TUI was still
  running" / "recorder status is missing", a failure it cannot connect to the
  other worker's paste. Post-fix both blocks exit 1 with the same message and
  the concurrent recorder survives (`probe-prefix.log` / `probe-postfix.log`).
  The nominal flows were re-run end to end after the edit on the same
  container (tmux: rc 0, 3029-byte cast, `recorder.status` 0, 12-byte
  transcript, claim released, recorder gone; CLI one-shot: rc 0, 143-byte
  cast, status 0), and both recipes' step-0/step-1 prose now say why the
  clear follows the `mkdir`. Tests: the uncreatable-capture-dir case runs
  with the stub `tmux` logging its calls (new `STUB_TMUX_LOG`) and requires
  no `kill-session`; both cases fail against `HEAD`'s recipes (checked by
  restoring them in place, then restoring the post-fix copies). File 169
  pass. Evidence: `$(pm qa captures-path pr-b19db15)/review-7c9c-i8/`
  (`probe-prefix.log`, `probe-postfix.log`, `nominal.log`, `scripts/`). No
  `pm_core/` change; the dropped helper/prompt/verifier work stays dropped.
