---
title: Web UI Recording (browser video + HTTP/SSE)
description: Record the walker web UI end-to-end with Playwright (Chromium video + trace + screenshots) and capture the HTTP/SSE protocol underneath
---

## When to use

A scenario needs evidence of the **rendered** walker web UI
(plan-litreview: `pm review ui`) behaving correctly — not a terminal
transcript but the actual browser: hotkey navigation, SSE → DOM
reactivity, the activity indicator animating, the Apply / lock-state
transitions. A still screenshot can't show motion and a curl log can't
show the render, so this recipe captures both layers:

1. **Rendered browser recording (primary)** — headless Chromium driven
   by Playwright, captured as context-level video + a step-through
   trace + key-state screenshots + a DOM dump.
2. **Protocol capture (supplementary)** — `http.log` / `sse.log` as
   lightweight, greppable proof of the server contract underneath.

For terminal/CLI surfaces use `cli-recording.md`; for the pm TUI use
`tmux-screen-recording.md`. This recipe is specifically for the web UI.

## Requirements

- **pr-37073ad** — the QA container image pre-installs Playwright + its
  bundled Chromium (`npx playwright install --with-deps chromium`) and
  `ffmpeg`. Node 22 is already present. Outside that image, install with
  `npm i -D playwright && npx playwright install --with-deps chromium`.
- **pr-5db0e85** (`review-walker-ui` instruction) — the fixture / phase-
  driving setup this recipe reuses: register a review, materialize a
  multi-cycle fixture directory under
  `pm/docs/adversarial-review/reviews/<id>/` (canonical-format `STATE.md`,
  `UI_FOCUS.md`, `NOTES.md`, and per-cycle `REVIEW_CYCLE_N.md` /
  `CITATION_AUDIT_CYCLE_N.md` / `REVIEW_RESPONSE_CYCLE_N.md`), then launch
  `pm review ui --port <ephemeral>`. Drive behavior by editing `STATE.md`
  to walk phases and by appending to the review/audit files.

## What this recipe produces

Write into `<capture-dir>/<short-name>/` (the scenario prompt
substitutes the per-PR captures directory — `$(pm qa captures-path
<pr-id>)/...` — for `<capture-dir>`):

- `recording.mp4` — the rendered walk-through (transcoded from
  `recording.webm` if `ffmpeg` is available).
- `recording.webm` — Playwright's native context-level video
  (**load-bearing** — keep it even when you also produce the mp4).
- `trace.zip` — Playwright trace (DOM snapshots + network + console);
  step through with `npx playwright show-trace trace.zip`.
- `*.png` — key-state screenshots (one per demonstrated state).
- `dom.html` — a DOM dump at a representative state (grep/diff target).
- `http.log` — curl snapshots of the canonical walker routes.
- `sse.log` — `curl -N` transcript of `/events?review=<id>`.
- `manifest.md` — frontmatter + prose per the standard recipe format,
  with a `## Files` section listing every file above.

## Canonical routes

The walker server (plan-litreview PR 3) serves per-review views keyed by
the review id, plus one SSE endpoint. The driver prefers click-through
navigation (role/text locators auto-track the server's real routes), and
uses these constants only for the initial dashboard load and the SSE
stream:

| View | Route | Notes |
|---|---|---|
| dashboard | `/` | lists every review; click into one |
| changes (review / proposed-changes walker) | `/review/<id>/changes` | the main walker; "review browse" of proposed changes |
| audit browse | `/review/<id>/audit` | per-cycle `CITATION_AUDIT_CYCLE_N.md` |
| citations | `/review/<id>/citations` | cross-cycle citation status |
| notes pane | `/review/<id>/notes` | collapsible side panel |
| SSE events | `/events?review=<id>` | `EventSource`; STATE / FOCUS / RESPONSE pushes |

## Capture — Layer 1: rendered browser recording

### 1. Stand up the fixture + server (per pr-5db0e85)

```bash
# Placeholders: set these for your capture.
CAPDIR="$(pm qa captures-path "$PR_ID")/scenarios/1/web-ui"   # <capture-dir>/<short-name>
ID=regression-fixture        # the registered review id
PORT=8765                    # an ephemeral free port
BASE="http://localhost:$PORT"
mkdir -p "$CAPDIR"

# Follow the review-walker-ui instruction (pr-5db0e85) to register the
# review and materialize a multi-cycle fixture directory, then launch the
# server bound to the ephemeral port. Background it; capture its pid so we
# can stop it at the end.
pm review ui --port "$PORT" &
SERVER_PID=$!

# Wait for the server to answer before driving it (no fixed sleep).
until curl -sf -o /dev/null "$BASE/"; do sleep 0.2; done
```

### 2. Drive Chromium with the Playwright driver

Save the skeleton below as `driver.mjs`, then run it with the capture
dir, review id, and base URL in the environment:

```bash
CAPDIR="$CAPDIR" REVIEW_ID="$ID" WALKER_URL="$BASE" node driver.mjs
```

The driver records the video and trace, walks the views, exercises the
hotkeys, and proves SSE-driven live updates. It uses role/text locators
with auto-wait — no brittle `sleep`s — so it tolerates render timing.

```javascript
// driver.mjs — Playwright walker-UI recording driver (skeleton).
// Records context-level video + a trace, walks dashboard -> changes
// (review) -> audit browse -> citations, exercises hotkeys, and proves
// SSE-driven live updates by mutating STATE.md in a side process.
import { chromium } from 'playwright';
import { promises as fs } from 'fs';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileP = promisify(execFile);

const capDir = process.env.CAPDIR;
const reviewId = process.env.REVIEW_ID;
const base = process.env.WALKER_URL || 'http://localhost:8765';

// Canonical routes (see the recipe's "Canonical routes" table). The
// driver prefers click-through via locators; these back the initial load
// and the SSE endpoint, and document the contract being exercised.
const routes = {
  dashboard: `${base}/`,
  changes: `${base}/review/${reviewId}/changes`,
  auditBrowse: `${base}/review/${reviewId}/audit`,
  citations: `${base}/review/${reviewId}/citations`,
  notes: `${base}/review/${reviewId}/notes`,
  events: `${base}/events?review=${reviewId}`,
};

const shot = (page, name) =>
  page.screenshot({ path: path.join(capDir, `${name}.png`), fullPage: true });

(async () => {
  // Container-safe launch flags (pr-37073ad): no sandbox, no /dev/shm.
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

  // 1. Dashboard -> click into the review.
  await page.goto(routes.dashboard);
  await page.getByRole('link', { name: new RegExp(reviewId, 'i') }).click();
  await shot(page, '01-dashboard');

  // 2. Proposed-changes (review) walker. Auto-waiting locator, no sleep.
  await page.goto(routes.changes);
  await page.getByRole('heading', { name: /proposed change/i }).waitFor();
  await shot(page, '02-changes');

  // Hotkeys: j/k navigate, a accept, m modify, s skip. These act only in
  // the awaiting-human-review phase of the current cycle (lock state).
  for (const key of ['j', 'j', 'k']) await page.keyboard.press(key);
  await page.keyboard.press('a');           // accept Claude's suggestion
  await shot(page, '03-after-accept');
  await page.keyboard.press('m');           // modify
  await page.keyboard.press('s');           // skip

  // 3. SSE-driven live update. A side process mutates STATE.md; the walker
  // receives the push on /events?review=<id> and reacts. Wait on the DOM
  // reflecting the new phase instead of sleeping. (Swap this execFile for
  // a concurrently-running side shell if you prefer; either works.)
  await execFileP('pm', ['review', 'set-phase', reviewId, 'applying']);
  await page
    .getByText(/applying accepted changes/i)
    .waitFor({ timeout: 5000 });
  await shot(page, '04-sse-phase-applying');

  // Activity indicator animating + Apply / lock-state transition: capture
  // the editable -> read-only flip the phase change produced.
  await page.getByRole('button', { name: /apply/i }).waitFor({ state: 'hidden' });

  // 4. Audit browse, then citations (click-through where the UI links).
  await page.goto(routes.auditBrowse);
  await page.getByRole('heading', { name: /audit/i }).waitFor();
  await shot(page, '05-audit-browse');

  await page.goto(routes.citations);
  await page.getByRole('table').waitFor();
  await shot(page, '06-citations');

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

### 3. Transcode webm -> mp4 (optional)

```bash
# Playwright records .webm natively. Transcode to .mp4 for convenience;
# if ffmpeg is unavailable, keep recording.webm as the load-bearing
# artifact and note the fallback in the manifest.
if command -v ffmpeg >/dev/null; then
    ffmpeg -y -i "$CAPDIR/recording.webm" -c:v libx264 -pix_fmt yuv420p \
        "$CAPDIR/recording.mp4"
fi
```

## Capture — Layer 2: protocol capture

Greppable proof of the server contract underneath the rendered demo.

```bash
# http.log — snapshot each canonical route. -sS keeps it quiet but shows
# errors; -w records the status line per route.
{
  for route in "/" "/review/$ID/changes" "/review/$ID/audit" \
               "/review/$ID/citations"; do
    echo "===== GET $route ====="
    curl -sS -w '\n[HTTP %{http_code}]\n' "$BASE$route"
  done
} > "$CAPDIR/http.log" 2>&1

# sse.log — transcript of the SSE stream while a side shell drives phase
# transitions. Start the reader in the background, mutate STATE.md, give
# the pushes a moment to land, then stop the reader.
curl -N --max-time 15 "$BASE/events?review=$ID" > "$CAPDIR/sse.log" 2>&1 &
SSE_PID=$!
pm review set-phase "$ID" awaiting-human-review
pm review set-phase "$ID" applying
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
    review_id: <review id the capture targeted>
    walker_url: <base URL the driver used>
    ---

    ## Commands

        CAPDIR=... REVIEW_ID=... WALKER_URL=... node driver.mjs
        ffmpeg -i recording.webm ... recording.mp4   # if transcoded
        curl -N "$BASE/events?review=$ID" > sse.log   # protocol layer

    ## What this demonstrates

    <one paragraph: which walker behavior is shown — the hotkey
    navigation, the SSE-driven phase transition and the lock-state /
    Apply flip, the activity indicator — and what to look for in the
    recording, trace, and sse.log.>

    ## Files

    - `recording.mp4` — rendered walk-through (transcoded).
    - `recording.webm` — Playwright native context video (load-bearing).
    - `trace.zip` — Playwright trace; `npx playwright show-trace trace.zip`.
    - `01-dashboard.png` … `06-citations.png` — key-state screenshots.
    - `dom.html` — DOM dump at a representative state.
    - `http.log` — curl snapshots of the canonical routes.
    - `sse.log` — `/events?review=<id>` event-stream transcript.

## Reviewing

```bash
npx playwright show-trace "$CAPDIR/trace.zip"   # step through every action
```

Or play `recording.mp4` / `recording.webm` directly, read `sse.log` to
confirm the push events arrived, and grep `http.log` / `dom.html` for the
rendered contract. The manifest tells reviewers what they're looking at
without re-deriving it from the driver script.
