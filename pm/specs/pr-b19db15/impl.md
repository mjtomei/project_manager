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
   reproduced ~7 times in 40 tight iterations).

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
   gap failing the same way, and the recorder readiness wait carrying its own
   deadline (the pm-session poll's `deadline` would otherwise satisfy a
   looser assertion).
   The capture flow is also *executed*, not only matched as text
   (`TestCaptureFlowExecution`): each recipe's fenced capture block runs
   against stub `tmux`/`pm` that drive a session table, so the readiness and
   stop logic is exercised. Cases: CLI completes; a recorder that never
   writes a cast fails at its bound; a recorder that dies without a cast
   fails; tmux completes (and prints no tmux error while stopping the pipe);
   a recorder that exits before drawing fails; a failed attach that drew its
   error text fails; a recorder that died mid-scenario fails on its
   truncated cast; a detach that fails because the recorder vanished in the
   check-to-send gap fails; and a recording that ended with the session
   itself passes.
   Each of those fails when its fix is reverted (checked by mutation: dropping
   the settle re-check, the mid-scenario branch, the detach-failure branch,
   the CLI cast check, and the `2>/dev/null` on the pipe stop each fail
   exactly one case).
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

R8. **A failed render must not leave the previous run's video, and the
   recorded command must survive the scaffold's quoting.**
   - The render steps delete this run's outputs before rendering:
     `rm -f "${cast%.cast}.mp4" "$cast.gif"` in both recording recipes, and
     `rm -f "$CAPDIR/recording.webm" "$CAPDIR/recording.mp4" "$CAPDIR/trace.zip"
     "$CAPDIR/dom.html" "${CAPDIR:?}"/*.png` before the
     web-UI driver (plus the mp4 again before the transcode). The `${CAPDIR:?}`
     on the glob is the guard that keeps an unset variable from expanding the
     pattern against the filesystem root. `ffmpeg` does
     not touch an existing output when it fails (verified: a missing input
     leaves the old mp4 byte-for-byte), so without this a render that failed
     — `agg` missing, unreadable cast, failed transcode — still ends with a
     `recording.mp4` that the manifest and the report present as this run's
     evidence; the stale gif likewise lets a failed `agg` encode an earlier
     run. The web-UI driver's trace, screenshots and DOM dump are cleared
     with the webm for the same reason: a driver that dies at the first
     locator writes none of them, so the earlier run's files would be listed
     as this run's evidence. This is the same bug class as rendering a stale
     cast (R2), one level up.
   - Each render step then `test -s` the mp4 and exits 1 with an actionable
     message ("render produced no mp4 — check 'agg' is installed and the cast
     is readable" / "transcode produced no mp4 — check the driver's webm")
     instead of exiting 0 with no video. The web-UI step keeps the webm until
     the mp4 exists so a failed transcode can be retried.
   - The CLI scaffold's `<command-to-record>` sits inside single quotes
     inside the outer double-quoted `new-session` argument, so the recipe
     documents the *escaped* form for the `bash -c` command form:
     `-c 'bash -c \"set -x; cmd-one; cmd-two\"'` (and notes the outer shell
     expands `$` first). Pasting the double-quoted form unescaped ends the
     outer string — verified live: the shell splits the command into stray
     words, the recorder exits immediately and the scaffold fails with
     "asciinema wrote no cast". The escaped form was verified end to end with
     real asciinema + tmux (rc 0, the cast holds the recorded output).

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
   /usr/lib/node_modules ]`): the recipe offers a *local* `npm i playwright`
   as the alternative, and an unconditional `ln -sfn` creates a link named
   after the target's basename *inside* an existing `node_modules` (verified:
   `node_modules/global` for a substituted target, `node_modules/node_modules`
   for the image's), and with no global install it leaves a dangling
   `node_modules` beside the driver that breaks that same fallback. And the
   resolution check now *gates* the run (`|| { …; exit 1; }`): without it the
   worker got the same `ERR_MODULE_NOT_FOUND` twice — once from the check,
   once from the driver — and no statement of what to do about it (verified:
   the old block continues into the driver after the check fails). Evidence:
   `/pm-captures/review-419c-i8/`.

## Non-goals

- **No product polling loop.** There is no checked-in `pgrep` loop to fix.
- **No new helper, prompt block, verifier text, or QA-loop change.** Those
  were the dropped scope above.
- **No new `claude -p` usage** (session rule).

## Files

| File | Change |
|---|---|
| `pm/qa/artifacts/tmux-screen-recording.md` | capture-dir mkdir, stale cast + transcript removal, recorder readiness, bounded stop + cast check, bounded pm-session poll on `has-session -t "$TARGET"`, stale render outputs cleared + mp4 checked |
| `pm/qa/artifacts/cli-recording.md` | same capture fixes; no-TTY scaffold rewritten (cast path, readiness, `exit` stop, bounded wait + cast check, escaped command form); stale render outputs cleared + mp4 checked |
| `pm/qa/artifacts/web-ui-recording.md` | port pre-check (refuses a server already answering) then bounded `until curl` with per-attempt timeout and server cleanup; stale webm/mp4/trace/screenshots/DOM dump cleared before the driver + mp4 checked; driver resolves the image's global Playwright through a conditional local `node_modules` (ESM ignores `NODE_PATH`) and stops if it does not |
| `tests/test_qa_artifact_recording_recipes.py` | **new** regression tests for the kept recipe fixes |
| `pm/specs/pr-b19db15/impl.md` | this spec |
| `pm/specs/pr-b19db15/qa.md` | reduced QA scope (recipe fixes only) |

## Verification plan

1. Run `tests/test_qa_artifact_recording_recipes.py` — all pass (including
   the execution tests: a failed render with stub `agg`/`ffprobe`/`ffmpeg`
   leaves no mp4/gif and exits non-zero, the scaffold's documented
   escaped command form reaches asciinema's `-c` intact, and the capture
   flow runs end to end against a stub `tmux`/`pm` for its success and
   failure paths).
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
