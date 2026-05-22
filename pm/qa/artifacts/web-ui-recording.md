---
title: Web UI Recording (browser video + HTTP/SSE)
description: Record a rendered web UI end-to-end with Playwright (Chromium video + trace + screenshots) and capture the HTTP/SSE protocol underneath
---

## When to use

A scenario needs evidence of a **rendered** web UI behaving correctly —
not a terminal transcript but the actual browser: navigation, hotkeys,
live server-pushed updates (SSE / websockets) reflected in the DOM,
animations, and state / lock transitions. A still screenshot can't show
motion and a curl log can't show the render, so this recipe captures two
layers:

1. **Rendered browser recording (primary)** — headless Chromium driven
   by Playwright, captured as context-level video + a step-through
   trace + key-state screenshots + a DOM dump.
2. **Protocol capture (supplementary)** — `http.log` / `sse.log` as
   lightweight, greppable proof of the server contract underneath.

For terminal/CLI surfaces use `cli-recording.md`; for the pm TUI use
`tmux-screen-recording.md`. This recipe is for any browser-rendered UI.

## Tooling

Needs Playwright + its bundled Chromium. The QA container image ships
these; elsewhere install with `npm i -D playwright && npx playwright
install --with-deps chromium`.

## What this recipe produces

Write into `<capture-dir>/<short-name>/` (the scenario prompt
substitutes the per-PR captures directory — `$(pm qa captures-path
<pr-id>)/...` — for `<capture-dir>`):

- `recording.webm` — Playwright's native context-level video; the
  rendered walk-through (**load-bearing**).
- `trace.zip` — Playwright trace (DOM snapshots + network + console);
  step through with `npx playwright show-trace trace.zip`.
- `*.png` — key-state screenshots (one per demonstrated state).
- `dom.html` — a DOM dump at a representative state (grep/diff target).
- `http.log` — curl snapshots of the UI's routes.
- `sse.log` — `curl -N` transcript of the SSE endpoint (if the UI is
  SSE-driven).
- `manifest.md` — frontmatter + prose per the standard recipe format,
  with a `## Files` section listing every file above.

## Capture — Layer 1: rendered browser recording

### 1. Start the UI under test

```bash
# Placeholders: set these for your capture.
PR_ID=pr-xxxxxxx             # the PR under QA (keys the captures dir)
CAPDIR="$(pm qa captures-path "$PR_ID")/scenarios/1/web-ui"   # <capture-dir>/<short-name>
PORT=8000                    # the port your app serves on
APP_URL="http://localhost:$PORT"
mkdir -p "$CAPDIR"

# Launch the web UI on the chosen port and background it; keep the pid so
# we can stop it in teardown. Replace APP_START with your app's command.
APP_START="my-app serve"
$APP_START --port "$PORT" &
SERVER_PID=$!

# Wait for the server to answer before driving it (no fixed sleep).
until curl -sf -o /dev/null "$APP_URL/"; do sleep 0.2; done
```

### 2. Drive Chromium with the Playwright driver

Save the skeleton below as `driver.mjs`, then run it with the capture dir
and base URL in the environment:

```bash
CAPDIR="$CAPDIR" APP_URL="$APP_URL" node driver.mjs
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

## Capture — Layer 2: protocol capture

Greppable proof of the server contract underneath the rendered demo.

```bash
# http.log — snapshot each route you care about. -sS keeps it quiet but
# shows errors; -w records the status line per route.
{
  for route in "/" "/some-view" "/another-view"; do
    echo "===== GET $route ====="
    curl -sS -w '\n[HTTP %{http_code}]\n' "$APP_URL$route"
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

```bash
kill "$SERVER_PID" 2>/dev/null || true
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
        curl -N "$SSE_URL" > sse.log   # protocol layer

    ## What this demonstrates

    <one paragraph: which UI behavior is shown — the navigation, the
    interaction, any SSE-driven update / state transition — and what to
    look for in the recording, trace, and sse.log.>

    ## Files

    - `recording.webm` — Playwright native context video; the rendered
      walk-through (load-bearing).
    - `trace.zip` — Playwright trace; `npx playwright show-trace trace.zip`.
    - `01-loaded.png` … `NN-*.png` — key-state screenshots.
    - `dom.html` — DOM dump at a representative state.
    - `http.log` — curl snapshots of the UI's routes.
    - `sse.log` — SSE event-stream transcript.

## Reviewing

```bash
npx playwright show-trace "$CAPDIR/trace.zip"   # step through every action
```

Or play `recording.webm` directly, read `sse.log` to confirm the push
events arrived, and grep `http.log` / `dom.html` for the rendered
contract. The manifest tells reviewers what they're looking at without
re-deriving it from the driver script.
