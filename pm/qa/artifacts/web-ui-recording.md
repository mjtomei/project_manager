---
title: Web UI Recording (browser video + HTTP/SSE)
description: Record a rendered web UI end-to-end with Playwright (Chromium video + trace + screenshots) and capture the HTTP/SSE protocol underneath
---

## When to use

A scenario needs evidence of a web UI behaving correctly. This recipe
captures two layers:

1. **Rendered browser recording (primary)** — headless Chromium driven
   by Playwright, captured as context-level video + a step-through
   trace + key-state screenshots + a DOM dump.
2. **Protocol capture (supplementary)** — `http.log` / `sse.log` as
   lightweight, greppable proof of the server contract underneath.

For terminal/CLI surfaces use `cli-recording.md`; for the pm TUI use
`tmux-screen-recording.md`. This recipe is for any browser-rendered UI.

## Tooling

Needs Playwright + its bundled Chromium. The QA container image ships
both — Playwright globally under `/usr/lib/node_modules`, its Chromium
under `/opt/ms-playwright` — and advertises the global install through
`NODE_PATH`, which Node's *ES module* resolver ignores. A driver saved as
`driver.mjs` (an ES module, as below) therefore has to resolve the package
locally; step 2 links it beside the driver and checks the import. Elsewhere,
install with `npm i playwright && npx playwright install --with-deps chromium`.
The driver runs under `node`, so Node.js has to be on `PATH` too — step 2
checks for it before it links anything, because without the runtime the import
check fails exactly as a missing Playwright does and both remedies it offers
(the global link, `npm i playwright`) need the thing that is missing.

The finalize step (step 3) transcodes with `ffmpeg`, which the QA container
image ships; install it (`apt-get install ffmpeg`) on a host without it. The
block checks for it, because without the check a missing encoder is reported
as a failed transcode of the driver's webm.

## What this recipe produces

Write into `<capture-dir>/<short-name>/` (the scenario prompt
substitutes the per-PR captures directory — `$(pm qa captures-path
<pr-id>)/...` — for `<capture-dir>`):

- `recording.mp4` — the rendered walk-through (the primary artifact).
  Playwright records VP8 webm natively; the finalize step transcodes it
  to H.264 mp4 so it plays everywhere including iOS Safari (VP8/VP9
  webm does not decode on iOS).
- `recording.webm` — Playwright's native video. The finalize step drops it
  once the mp4 exists, so it survives only when the transcode failed (it is
  kept deliberately, so the step can be retried without re-driving the UI) —
  mention it in the manifest when it does.
- `driver.mjs` — the driver that produced this capture: the adapted
  skeleton (locators, interactions, side-channel trigger). Keep it in the
  capture directory so a reviewer can see what was actually driven.
- `trace.zip` — Playwright trace (DOM snapshots + network + console);
  step through with `npx playwright show-trace trace.zip`.
- `*.png` — key-state screenshots (one per demonstrated state).
- `dom.html` — a DOM dump at a representative state (grep/diff target).
- `http.log` — curl snapshots of the UI's routes.
- `sse.log` — `curl -N` transcript of the SSE endpoint (if the UI is
  SSE-driven).
- `node_modules` — a link to the image's global Playwright install, created
  by step 2 when the driver needed it and there was no local install (the
  ES-module resolver ignores `NODE_PATH`); it stays in the capture directory,
  so the manifest names it.
- `server.pid` — the pid of the app step 1 started, which the teardown reads
  when `SERVER_PID` is gone from its shell. The teardown removes it, so it
  survives only when a run stopped before the teardown (a failed driver,
  which step 2 says not to finalize) — mention it in the manifest when it
  does.
- `manifest.md` — frontmatter + prose per the standard recipe format,
  with a `## Files` section listing every file above.

## Capture — Layer 1: rendered browser recording

### 1. Start the UI under test

```bash
# Placeholders: set these for your capture.
PR_ID=pr-xxxxxxx             # the PR under QA (keys the captures dir)
# Resolve the captures directory through pm, and check the answer before it
# becomes a path. `pm qa captures-path` prints nothing on stdout when it fails
# — its error goes to stderr ("PR 'pr-xxxxxxx' not found." for an
# unsubstituted id, "No project.yaml found" when the step is pasted outside
# the project) and it exits non-zero — so a bare
# `CAPDIR="$(...)/scenarios/1/web-ui"` would be `/scenarios/1/web-ui`, at the
# *filesystem root* (an answer that exits 0 and prints nothing is the same
# empty path, so the check is on the value, not only on the status).
# `mkdir -p` creates it when the worker is root (QA
# container workers are), the whole capture then lands there while every later
# check passes on those files, and the manifest points at a directory the
# report never reads — the same "a promised artifact written where nothing
# looks" bug as the relative `<capture-dir>` the recording recipes refuse.
cap_root=$(pm qa captures-path "$PR_ID") || cap_root=
if [ -z "$cap_root" ]; then
    echo "could not resolve the captures directory for $PR_ID — run 'pm qa" \
        "captures-path $PR_ID' in the project to see why (a failed lookup" \
        "prints its error on stderr; the capture directory would otherwise" \
        "be /scenarios/1/web-ui at the filesystem root)" >&2
    exit 1
fi
CAPDIR="$cap_root/scenarios/1/web-ui"   # <capture-dir>/<short-name>
PORT=8000                    # the port your app serves on
APP_URL="http://localhost:$PORT"
# Every step below writes into the capture directory, and several of them
# report success while writing nothing when it is not there (the redirects
# fail, the driver's outputs go nowhere). Stop here instead.
mkdir -p "$CAPDIR" || {
    echo "could not create $CAPDIR — check the path and its permissions" >&2
    exit 1
}
# A previous run's outputs must not survive a failed driver or transcode: the
# finalize step would otherwise turn an earlier run's webm into a
# fresh-looking mp4 of that run, and the driver's trace, screenshots and DOM
# dump would sit in the capture directory as this run's evidence while this
# run never produced them (a driver that dies at the first locator writes
# none of them). Every *.webm goes, not just recording.webm: the driver
# renames Playwright's auto-named video onto that name, so a driver that dies
# before the rename (a supervisor, OOM or crash — the rename never runs)
# leaves `page@<hash>.webm` behind, and that file is a *valid, playable*
# partial recording (observed in this container: ffprobe reports a real
# duration) that no other step clears. The Layer 2 logs go with them: a run
# that never re-captures the protocol would otherwise present the earlier
# run's http.log and sse.log as this run's evidence.
# The `${CAPDIR:?}` on the globs (not `$CAPDIR`) makes the whole `rm` command
# abort if the variable is unset: the expansion fails before `rm` runs, so the
# command never executes — even in an interactive shell, unlike the
# `: "${CAPDIR:?}"` form below. Without it `"$CAPDIR"/*.png` and `*.webm`
# would expand against the filesystem root and the cleanup would target every
# PNG and webm there.
# `server.pid` (written below) goes too: a stale one would make the teardown
# signal whatever process has since reused that pid.
rm -f "$CAPDIR/recording.mp4" \
      "$CAPDIR/trace.zip" "$CAPDIR/dom.html" \
      "$CAPDIR/http.log" "$CAPDIR/sse.log" "$CAPDIR/server.pid" \
      "${CAPDIR:?}"/*.webm "${CAPDIR:?}"/*.png

# Fail fast if something is *already* answering on the port. A previous run's
# server — or another scenario using the same default port — would satisfy the
# readiness wait below, and the driver would then record *that* app while this
# run's app never bound the port: a capture of the wrong build, presented as
# this run's evidence. `curl` without `-f` on purpose: any HTTP answer,
# including a 404, means the port is taken.
# Only "connection refused" (curl exit 7) means the port is *free*. Any other
# failure is not a free port: a timeout (28) means something accepted the
# connection and did not answer — a previous run's hung server would satisfy
# the readiness wait below as soon as it did — and a usage or resolution error
# (1, 6, 127, …) means the URL or the tool is wrong. Treating those as free
# starts this run's app on a port it cannot bind, and the failure then
# surfaces at the readiness deadline as "app did not answer — check its
# startup output", which names neither the cause nor the process holding the
# port (verified: with a listener that accepts and never answers, the app's
# own "Address already in use" was reported that way, after the full 120 s).
if curl -s -o /dev/null --connect-timeout 2 --max-time 5 "$APP_URL/"; then
    # The cleanup above already removed server.pid, and the server answering
    # is not necessarily this capture's (another scenario may hold the port),
    # so this block must not stop it and the teardown has no pid left to read:
    # name a remedy that works instead of pointing at a teardown that cannot.
    echo "something already answers on $APP_URL — a previous run's server or" \
        "another scenario holds the port. Its pid is no longer in server.pid" \
        "(this step cleared it): find it with 'ss -ltnp' on the port and stop" \
        "it, or pick another PORT" >&2
    exit 1
else
    curl_rc=$?
    if [ "$curl_rc" != 7 ]; then
        echo "could not check $APP_URL with curl (exit $curl_rc; only" \
            "'connection refused', 7, means the port is free): something may" \
            "be listening without answering, the URL may be wrong, or curl" \
            "may not be installed. Find a listener with 'ss -ltnp' on the" \
            "port and stop it, or pick another PORT" >&2
        exit 1
    fi
fi

# Launch the web UI on the chosen port and background it; keep the pid so
# we can stop it in teardown. Replace APP_START with your app's command.
APP_START="my-app serve"
$APP_START --port "$PORT" &
SERVER_PID=$!
# The app outlives this shell, and every block below is pasted into a fresh
# one, so `$SERVER_PID` is normally gone by the time the teardown runs: write
# it beside the capture for that step to read. Re-running *this* block is not
# a remedy for a lost pid — its own app now answers the port pre-check above.
printf '%s\n' "$SERVER_PID" > "$CAPDIR/server.pid"

# Wait for the server to answer before driving it (no fixed sleep), but
# bound it: an unbounded poll hangs the worker forever when the app never
# comes up, so stop with the reason and stop the server we started. Bound
# each attempt too — a server that accepts the connection but never answers
# would otherwise block inside one curl call and the deadline would never
# be consulted. No `-f`, like the port pre-check above: readiness means "the
# server answers", not "the root path returns 2xx". An app whose UI lives at
# a subpath answers 404 at "/" and is up — with `-f` this poll runs out its
# deadline, reports "app did not answer", and kills a healthy server
# (verified: `curl -sf` exits 22 on that app while plain `curl` exits 0).
deadline=$(( $(date +%s) + 120 ))
until curl -s --connect-timeout 2 --max-time 5 -o /dev/null "$APP_URL/"; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "app did not answer on $APP_URL within 120s — check its startup output" >&2
        kill "$SERVER_PID" 2>/dev/null || true
        # The pid is dead now, so the file must go with it: the teardown
        # falls back to it, and a recycled pid would make it signal an
        # unrelated process (the same reason step 1 clears a stale one).
        rm -f "$CAPDIR/server.pid"
        exit 1
    fi
    sleep 0.2
done
```

### 2. Drive Chromium with the Playwright driver

Save the skeleton below as `driver.mjs` in the capture directory, then run
it with the capture dir and base URL in the environment:

```bash
# Both variables come from step 1; a fresh shell has neither, and
# `cd ""` silently stays put — the link below would then be created in
# whatever directory the worker happens to be in (e.g. the PR workdir), the
# resolution check would pass on *that* link, and the driver would fail with
# a bare "Cannot find module …/driver.mjs". Stop the block instead, as the
# finalize step does. This has to be an `if … exit 1`, not `: "${CAPDIR:?}"`:
# in an *interactive* shell the `:?` form prints the error, aborts only its
# own command, and the next line still runs (verified) — it only stops a
# scripted run.
if [ -z "${CAPDIR:-}" ] || [ -z "${APP_URL:-}" ]; then
    echo "CAPDIR/APP_URL are unset — set the placeholders from step 1 first;" \
        "the node_modules link below would otherwise land in the worker's" \
        "cwd, and the driver falls back to http://localhost:8000, recording" \
        "whatever answers there as this run's evidence" >&2
    exit 1
fi
# A set-but-missing CAPDIR is the same hole: `cd` fails, the shell stays in
# the worker's cwd, and the link and the driver run there (verified: the
# link landed in the cwd and the resolution check passed on it).
cd "$CAPDIR" || {                            # where driver.mjs lives
    echo "capture directory $CAPDIR does not exist — create it and run step 1" >&2
    exit 1
}
# Clear this attempt's outputs *before* anything below can fail. This block is
# pasted on its own whenever a driver is adapted and retried, so the *previous*
# attempt's webm, trace, screenshots and DOM dump are still here; any failure
# from this point on — a resolution check that cannot find Playwright, a driver
# that dies part-way — would otherwise leave the earlier attempt's complete
# webm for the finalize step to transcode into this run's recording. Step 1
# clears them for a fresh run; this covers step 2 alone. Every *.webm goes: a
# killed driver leaves Playwright's auto-named `page@<hash>.webm` rather than
# the renamed recording.webm, and that partial video is valid enough to pass
# any file check. The mp4 goes too: an earlier attempt that was already
# finalized leaves the primary artifact, and a retry that fails would then end
# with that video as the only recording the manifest can present as this
# run's. The paths are relative because the `cd` above succeeded.
rm -f ./recording.mp4 ./*.webm ./trace.zip ./dom.html ./*.png
# The driver this block runs is the one the prose above says to save here.
# Without it `node driver.mjs` answers "Cannot find module …/driver.mjs" and
# the run-failure message below would report that as a driver that ran and
# failed — the same misdiagnosis as reporting a missing webm as an encoder
# failure, and it sends the worker to debug a driver that is simply not there
# (or was saved in the workdir instead of the capture directory). Name the
# missing input where it is missing.
[ -f driver.mjs ] || {
    echo "there is no driver.mjs in $CAPDIR — save the recipe's driver" \
        "skeleton as driver.mjs here (step 2's prose) before running this" \
        "block" >&2
    exit 1
}
# The driver is a Node.js program, and this block's only tools are `node` and
# (when it links) `ln`. Without the runtime the import check below fails the
# same way a missing Playwright does — "playwright does not resolve beside
# driver.mjs" — and every remedy that message offers (link the global install,
# or `npm i playwright`) needs the runtime that is not there: a remedy that
# cannot work, repeated, in the shape R31/R32 fixed for the `agg` install and
# the nested `node_modules`. Name the missing runtime where it is missing, and
# before the link below so a run without `node` creates nothing.
command -v node >/dev/null || {
    echo "node is not installed — driver.mjs runs under Node.js; install it" \
        "(e.g. 'apt-get install nodejs') and re-run this step" >&2
    exit 1
}
# The driver is an ES module, and Node's ES-module resolver ignores
# NODE_PATH, so with only the image's global Playwright a bare
# `node driver.mjs` fails at once with "ERR_MODULE_NOT_FOUND: Cannot find
# package 'playwright'". A node_modules beside the driver that resolves the
# package fixes it — the image's global install, or `npm i playwright` here.
# Link only when needed: with no global install `ln -sfn` would leave a
# *dangling* node_modules that then breaks the `npm i playwright` fallback,
# and with a local install already in place it would create a nested
# node_modules/node_modules. The test is the package directory, not just the
# global node_modules: linking a directory that does not hold `playwright`
# leaves a node_modules that cannot resolve, which then sends a later
# `npm i playwright` into the global install instead of this capture dir.
if [ ! -e node_modules ] && [ -d /usr/lib/node_modules/playwright ]; then
    ln -sfn /usr/lib/node_modules node_modules
fi
# Check before running the driver, and stop here on failure: otherwise the
# worker gets this error twice (once here, once from the driver) with no
# indication of what to do about it.
node -e "import('playwright').then(() => console.log('playwright ok'))" || {
    # The link only helps when the image's global install actually holds the
    # package; offering it unconditionally sends a worker on a host without
    # one to a remedy that cannot work (the same hole the guard above closes).
    # The same goes for an existing node_modules the guard above refused to
    # touch: a partial `npm i playwright` leaves the directory without the
    # package, and a bare `ln -sfn … node_modules` then creates
    # node_modules/node_modules — a link that still does not resolve, so the
    # worker repeats it (verified: the nested link answers
    # ERR_MODULE_NOT_FOUND exactly as before). Say to remove it first.
    echo "playwright does not resolve beside driver.mjs — if" \
        "/usr/lib/node_modules/playwright exists, remove a node_modules here" \
        "that does not hold it and link the global install ('rm -rf" \
        "node_modules; ln -sfn /usr/lib/node_modules node_modules');" \
        "otherwise run 'npm i playwright' here" >&2
    exit 1
}
CAPDIR="$CAPDIR" APP_URL="$APP_URL" node driver.mjs || {
    # The driver's own exit status is the handle that says this attempt
    # finished: it writes the video, trace, screenshots and DOM dump as it
    # goes, so a run that fails leaves a partial set (or, killed before
    # closing the context, none at all). Without this check the failure
    # surfaces one block later as "ffmpeg failed on the driver's webm" — a
    # misdiagnosis that sends the worker to the encoder — or, when a partial
    # webm is there, as a successful transcode of an incomplete recording.
    echo "the driver failed — this run's video, trace and screenshots are" \
        "incomplete; do not finalize this attempt" >&2
    exit 1
}
```

It records video and trace, walks the UI, and (for SSE/websocket UIs)
proves a server-pushed update reaches the DOM. Adapt the marked spots —
locators, interactions, and the side channel that triggers live updates —
to your UI. It uses auto-waiting role/text locators, not sleeps, so it
tolerates render timing.

```javascript
// driver.mjs — Playwright web-UI recording skeleton.
// Records context-level video + a trace, walks the UI, exercises an
// interaction, and (if the UI is server-pushed) proves a live update
// reaches the DOM. Replace the marked spots with your UI's specifics.
import { chromium } from 'playwright';
import { promises as fs } from 'fs';
import path from 'path';

const capDir = process.env.CAPDIR;
const appUrl = process.env.APP_URL || 'http://localhost:8000';

const shot = (page, name) =>
  page.screenshot({ path: path.join(capDir, `${name}.png`), fullPage: true });

(async () => {
  // Container-safe launch flags: no sandbox, no /dev/shm.
  const browser = await chromium.launch({
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });

  // Native context-level video recording -> <capDir>/<auto>.webm.
  const context = await browser.newContext({
    recordVideo: { dir: capDir, size: { width: 1280, height: 800 } },
  });
  // Trace for step-through evidence (screenshots + DOM/network snapshots).
  await context.tracing.start({ screenshots: true, snapshots: true });

  const page = await context.newPage();

  // 1. Load the UI and capture the entry state. Prefer auto-waiting
  // role/text locators over sleeps. (Adapt the locator to your UI.)
  await page.goto(appUrl);
  await page.getByRole('heading').first().waitFor();
  await shot(page, '01-loaded');

  // 2. Exercise the behavior under test — clicks, keyboard shortcuts, form
  // input. (Replace with your UI's interactions.)
  await page.keyboard.press('j');           // e.g. a navigation hotkey
  await shot(page, '02-after-interaction');

  // 3. Server-pushed (SSE/websocket) UIs: prove a live update reaches the
  // DOM. Trigger the change through whatever side channel your app exposes
  // (a mutating request, a watched-file write — see Layer 2 for a
  // curl-driven equivalent), then wait on the resulting DOM, not a sleep:
  //   await triggerServerSideChange();
  //   await page.getByText(/updated/i).waitFor({ timeout: 5000 });
  await shot(page, '03-after-update');

  // DOM dump at a representative state.
  await fs.writeFile(path.join(capDir, 'dom.html'), await page.content());

  // Flush the trace and the video. Playwright finalizes the webm only on
  // context.close(); resolve its path *after* closing.
  await context.tracing.stop({ path: path.join(capDir, 'trace.zip') });
  const video = page.video();
  await context.close();
  await browser.close();
  if (video) {
    const webm = await video.path();
    await fs.rename(webm, path.join(capDir, 'recording.webm'));
  }
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
```

### 3. Finalize: transcode the video to H.264 mp4

Playwright's native recording is VP8 webm, which iOS Safari cannot
decode. Transcode to H.264 and keep only the mp4:

```bash
# The placeholders above are shell variables; a block pasted into a fresh
# shell has no CAPDIR, and `"$CAPDIR/recording.mp4"` then becomes
# `/recording.mp4` — the cleanup and ffmpeg would run against the filesystem
# root. Stop the block instead (step 1's cleanup guards its glob the same
# way). An `if … exit 1` rather than `: "${CAPDIR:?}"`: in an *interactive*
# shell the `:?` form prints the error, aborts only its own command, and the
# `rm -f` below still runs against `/recording.mp4` (verified).
if [ -z "${CAPDIR:-}" ]; then
    echo "CAPDIR is unset — set the placeholders from step 1 first; the" \
        "cleanup and ffmpeg below would otherwise aim at the filesystem root" >&2
    exit 1
fi
# A set-but-missing directory is the same hole one line later, and it is
# misdiagnosed: both the `rm` and the webm check below fail for their own
# reasons, and the block reports "the driver wrote no video" for a path that
# simply is not there (the driver and Layer 2 blocks guard this the same way).
if [ ! -d "$CAPDIR" ]; then
    echo "capture directory $CAPDIR does not exist — create it and run step 1" >&2
    exit 1
fi
# Drop the old mp4 first: ffmpeg leaves an existing output untouched when it
# fails, so a failed transcode would otherwise keep the previous run's video
# as this run's recording.
rm -f "$CAPDIR/recording.mp4"
# No webm means there is nothing to transcode, and that is *not* an ffmpeg
# problem: the driver block checks the driver's exit status, but a driver that
# exits 0 without recording (`recordVideo` dropped while adapting it, or a
# `video` that came back null) writes no video at all, and the failure below
# would otherwise blame the encoder — the same misdiagnosis as reporting a
# missing cast as an `agg` problem in the recording recipes. Say which it is.
[ -s "$CAPDIR/recording.webm" ] || {
    echo "there is no webm to transcode — the driver wrote no video; re-run" \
        "step 2 and check the driver's recordVideo option" >&2
    exit 1
}
# A missing encoder is not a bad webm. Without this check the shell answers
# "ffmpeg: command not found" (status 127), the branch below reports it, and
# the worker is told the driver's webm failed to transcode (verified) — the
# same misdiagnosis as reporting a missing cast as an `agg` problem in the
# recording recipes. Name the actual cause and how to get it.
command -v ffmpeg >/dev/null || {
    echo "ffmpeg is not installed — the finalize step needs it; install it" \
        "(e.g. 'apt-get install ffmpeg') and re-run this step" >&2
    exit 1
}
# Check ffmpeg's own exit status as well as the file. A failed or killed
# transcode leaves a *partial* mp4 behind (verified: a killed ffmpeg leaves a
# non-empty output), which the `test -s` below accepts — the same
# header-only-cast problem as the recording step, one artifact over.
ffmpeg -y -i "$CAPDIR/recording.webm" -c:v libx264 -profile:v high \
    -pix_fmt yuv420p -crf 18 -movflags +faststart \
    "$CAPDIR/recording.mp4" || {
    rm -f "$CAPDIR/recording.mp4"
    echo "transcode produced no mp4 — ffmpeg failed on the driver's webm" >&2
    exit 1
}
# The mp4 is the required artifact: fail here, visibly, rather than leaving
# the caller to notice the video is missing later. The webm is kept until the
# mp4 exists so a failed transcode can be retried without re-driving the UI.
# A renderer that reports success and writes nothing leaves an *empty* mp4
# behind, and an output that is left on a failed step is what the recording
# recipes' render step removes for the same reason (verified: this branch
# exits 1 but used to leave a 0-byte recording.mp4 the manifest could list as
# this run's video).
test -s "$CAPDIR/recording.mp4" || {
    rm -f "$CAPDIR/recording.mp4"
    echo "transcode produced no mp4 — ffmpeg wrote nothing; check the" \
        "driver's webm" >&2
    exit 1
}
rm -f "$CAPDIR/recording.webm"
```

(`-movflags +faststart` puts the moov atom up front so playback starts
before the full download; the 1280x800 recording size is already even,
as H.264 requires.)

## Capture — Layer 2: protocol capture

Greppable proof of the server contract underneath the rendered demo.

```bash
# Both come from step 1, and this block is pasted into a fresh shell: with
# CAPDIR unset `"$CAPDIR/http.log"` is `/http.log`, so the redirects either
# write into the filesystem root (as root) or fail — and the block still exits
# 0, so a run with no protocol capture reads as success. Stop here instead, as
# the driver, finalize and teardown blocks do.
if [ -z "${CAPDIR:-}" ] || [ -z "${APP_URL:-}" ]; then
    echo "CAPDIR/APP_URL are unset — set the placeholders from step 1 first;" \
        "the redirects below would otherwise aim at the filesystem root" >&2
    exit 1
fi
# A set-but-missing directory is the same failure one step later: both
# redirects fail, neither curl runs, and the block still exits 0 (verified)
# — a run with no protocol capture that reads as success. Stop instead.
if [ ! -d "$CAPDIR" ]; then
    echo "capture directory $CAPDIR does not exist — create it and run step 1" >&2
    exit 1
fi
# http.log — snapshot each route you care about. -sS keeps it quiet but
# shows errors; -w records the status line per route. Each request is
# bounded, like the step-1 readiness poll: a route that accepts the
# connection but never answers would otherwise block this block forever.
# A timed-out route is recorded in the log as curl's own error with status
# 000 — that is the evidence for that route, not a hang.
{
  for route in "/" "/some-view" "/another-view"; do
    echo "===== GET $route ====="
    curl -sS --connect-timeout 2 --max-time 10 \
         -w '\n[HTTP %{http_code}]\n' "$APP_URL$route"
  done
} > "$CAPDIR/http.log" 2>&1

# sse.log — for an SSE-driven UI, record the event stream while a side
# shell triggers a server-pushed change, then stop the reader. Point
# SSE_URL at your app's event endpoint.
SSE_URL="$APP_URL/events"
curl -sS -N --max-time 15 "$SSE_URL" > "$CAPDIR/sse.log" 2>&1 &
SSE_PID=$!
# ... trigger a change here (a mutating request, a watched-file write) ...
sleep 2
kill "$SSE_PID" 2>/dev/null || true
```

### Teardown

Run this after the driver and the protocol layer. The app outlives the shell
that started it, and every block in this recipe is pasted into a fresh one,
so `SERVER_PID` from step 1 is normally gone by the time this runs — step 1
also writes the pid to `server.pid` in the capture directory, which this step
falls back to. Re-running step 1 is not a remedy for a lost pid: its own app
now answers the port pre-check. A kill against a pid that no longer exists is
a silent no-op, so the app would keep holding the port and the *next* run's
pre-check would refuse with "something already answers", which looks like
someone else's server. Stop with that reason instead (an `if … exit 1`,
because the `: "${SERVER_PID:?}"` form only stops a *scripted* run — in an
interactive shell it prints the error and the next line still runs).

```bash
# The pid file lives in the capture directory, so CAPDIR has to be set even
# when SERVER_PID is.
if [ -z "${CAPDIR:-}" ]; then
    echo "CAPDIR is unset — set the placeholders from step 1 first; the pid" \
        "step 1 recorded is in <capture-dir>/server.pid" >&2
    exit 1
fi
SERVER_PID=${SERVER_PID:-$(cat "$CAPDIR/server.pid" 2>/dev/null)}
if [ -z "${SERVER_PID:-}" ]; then
    echo "SERVER_PID is unset and $CAPDIR/server.pid holds no pid — find the" \
        "app's pid (e.g. 'ss -ltnp' for the port) and stop it; it keeps the" \
        "port otherwise" >&2
    exit 1
fi
kill "$SERVER_PID" 2>/dev/null || true
rm -f "$CAPDIR/server.pid"
```

## Manifest format

Standard manifest frontmatter plus a `## Files` section. Note the inner
blocks below are indented (not fenced) so the recipe stays one level of
fencing deep:

    ---
    pr: <pr-id>
    workdir: <absolute path>
    captured_at: <ISO date>
    recipe: pm/qa/artifacts/web-ui-recording.md
    app_url: <base URL the driver used>
    ---

    ## Commands

        CAPDIR=... APP_URL=... node driver.mjs
        ffmpeg -i recording.webm ... recording.mp4   # H.264 finalize
        curl -N "$SSE_URL" > sse.log   # protocol layer

    ## What this demonstrates

    <one paragraph: which UI behavior is shown — the navigation, the
    interaction, any SSE-driven update / state transition — and what to
    look for in the recording, trace, and sse.log.>

    ## Files

    - `recording.mp4` — the rendered walk-through, transcoded to H.264
      from Playwright's native webm.
    - `recording.webm` — Playwright's native video; kept only when the
      transcode failed, so step 3 can be retried without re-driving the UI.
    - `driver.mjs` — the Playwright driver that produced this capture (the
      adapted skeleton: locators, interactions, side-channel trigger).
    - `trace.zip` — Playwright trace; `npx playwright show-trace trace.zip`.
    - `01-loaded.png` … `NN-*.png` — key-state screenshots.
    - `dom.html` — DOM dump at a representative state.
    - `http.log` — curl snapshots of the UI's routes.
    - `sse.log` — SSE event-stream transcript.
    - `node_modules` — link to the image's Playwright install (if step 2
      created one).
    - `server.pid` — the app's pid, present only when the run stopped
      before the teardown (the teardown removes it).

## Reviewing

```bash
npx playwright show-trace "$CAPDIR/trace.zip"   # step through every action
```

Or play `recording.mp4` directly, read `sse.log` to confirm the push
events arrived, and grep `http.log` / `dom.html` for the rendered
contract. The manifest tells reviewers what they're looking at without
re-deriving it from the driver script.
