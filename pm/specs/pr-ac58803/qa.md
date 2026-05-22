# QA Spec: pr-ac58803 — QA artifact recipe: web UI recording (browser video + HTTP/SSE)

## Nature of this PR

This is a **pure QA-documentation PR**. It adds one new artifact recipe,
`pm/qa/artifacts/web-ui-recording.md`, plus a test module. It changes no
runtime code. The recipe is a *procedure a QA session follows* to capture
evidence of a rendered web UI: a Playwright driver-script skeleton (Layer 1 —
Chromium video + trace + screenshots + DOM dump) and a curl-based protocol
capture (Layer 2 — `http.log` + `sse.log`), plus a `manifest.md`.

Because the deliverable is a recipe consumed by a QA session, "exercising it
like an end user" means two distinct surfaces:

1. **Discovery surface** — the recipe shows up wherever the QA library is
   browsed (CLI `pm qa list` / `pm qa show`, the TUI QA pane, the planner
   prompt) and resolves when referenced by stem/filename in a scenario's
   `ARTIFACT:` field.
2. **Execution surface** — a QA session that *follows the recipe end-to-end*
   against a real web UI: saves and runs the driver, drives Chromium with the
   documented container-safe flags, and produces every artifact the recipe
   promises (`recording.webm`, `trace.zip`, screenshots, `dom.html`,
   `http.log`, `sse.log`, `manifest.md`) — all of them genuinely created and
   valid, not just described.

The recipe is intentionally generic (no walker/UI specifics; no ffmpeg/mp4
transcode — `recording.webm` is the single load-bearing video). The repo
ships **no** web UI of its own, so any end-to-end execution scenario must
stand up a small representative web UI to drive — that is exactly the
"adapt the marked spots" step the recipe expects of its user.

## 1. Requirements (Given / When / Then)

### R1 — Recipe is listed in the CLI QA library
- **Given** a checkout of this branch (the recipe is committed under
  `pm/qa/artifacts/`).
- **When** the user runs `pm qa list`.
- **Then** the "Artifact Recipes" section includes a `web-ui-recording`
  entry whose title and one-line description render from the recipe's
  frontmatter (alongside the existing `cli-recording` and
  `tmux-screen-recording`).

### R2 — Recipe body is printable via the CLI
- **Given** the same checkout.
- **When** the user runs `pm qa show web-ui-recording` (and the
  `web-ui-recording.md` filename form).
- **Then** the full recipe body prints — the When-to-use, Tooling,
  What-this-produces, both Capture layers, the Manifest format, and the
  Reviewing sections — with a resolvable on-disk path.

### R3 — Recipe appears in the TUI QA pane
- **Given** a running pm session showing the TUI.
- **When** the user opens the QA pane.
- **Then** the recipe is listed under Artifact Recipes with its title and
  description, consistent with the CLI listing.

### R4 — Recipe resolves when referenced from a scenario
- **Given** a QA scenario that names `web-ui-recording` (or
  `web-ui-recording.md`) in its `ARTIFACT:` field.
- **When** the QA runner provisions that scenario.
- **Then** the reference resolves to the `artifacts` category and the recipe
  body is made available to the scenario worker (copied into its scratch dir
  / surfaced in its prompt).

### R5 — Following the recipe produces the rendered browser recording (Layer 1)
- **Given** a representative web UI running on a known port, and the recipe's
  `driver.mjs` saved verbatim with the marked spots adapted to that UI's
  locators/interactions.
- **When** the user runs the driver with `CAPDIR`/`APP_URL` set, as the
  recipe documents.
- **Then** the capture dir gains a non-empty, playable `recording.webm`
  (context-level video of the walk-through), a `trace.zip` openable with
  `npx playwright show-trace`, one or more key-state `*.png` screenshots, and
  a `dom.html` DOM dump.

### R6 — Chromium launches container-safe
- **Given** the recipe's driver running inside the QA container (as a
  non-privileged or root container user, no usable `/dev/shm`).
- **When** the driver calls `chromium.launch` with `--no-sandbox` and
  `--disable-dev-shm-usage` as documented.
- **Then** Chromium starts and the navigation succeeds (no sandbox/crash
  failure), and the run completes through to artifact finalization.

### R7 — A server-pushed (SSE) update reaches the rendered DOM
- **Given** an SSE-driven web UI under capture and a side channel that
  triggers a server push (a mutating request or a watched-file write).
- **When** the change is triggered while the driver is on the page.
- **Then** the driver's auto-waiting locator observes the resulting DOM
  change (no fixed sleep), and a screenshot at that state shows the update —
  proving the live push is captured in the recording.

### R8 — Following the recipe produces the protocol capture (Layer 2)
- **Given** the same running web UI.
- **When** the user runs the Layer-2 commands: the curl route loop and the
  `curl -sS -N` SSE reader (with a side-channel trigger fired while it
  streams).
- **Then** `http.log` contains a labelled snapshot per route with its HTTP
  status, and `sse.log` contains the streamed event(s) including the one
  caused by the triggered change; the SSE reader terminates cleanly (via
  `--max-time` / kill) and flushes its transcript.

### R9 — A manifest documents the capture
- **Given** a completed capture under the capture dir.
- **When** the user writes `manifest.md` per the recipe's Manifest-format
  section.
- **Then** it carries the standard frontmatter (`pr`, `workdir`,
  `captured_at`, `recipe`, plus `app_url`) and a `## Files` section listing
  every produced file (`recording.webm`, `trace.zip`, the screenshots,
  `dom.html`, `http.log`, `sse.log`).

### R10 — Documented commands are copy-pasteable and well-formed
- **Given** the recipe as shipped.
- **When** the user copies a shell block or the driver block and runs it
  (with placeholders filled).
- **Then** each shell block is syntactically valid (`bash -n`) and the
  driver block is valid ESM (`node --check`), so the commands run rather than
  erroring on parse — the recipe is followable verbatim.

## 2. Setup

Cross-cutting setup for the execution scenarios (R5–R10):

- **Tooling.** Node, the `playwright` package + its bundled Chromium, `curl`,
  and `npx` available — the recipe claims the QA container image ships these
  (pr-37073ad). The host used for planning lacks chromium/playwright, so the
  execution scenarios must run where the container image is in effect; their
  success *is* the validation of the tooling claim.
- **A representative web UI.** The repo ships no web UI, so the scenario
  stands up a minimal one: a server with a root route that renders a heading
  and some content, an `/events` SSE endpoint, and a side channel to trigger a
  server push (e.g. a mutating POST or a watched file). A non-SSE variant
  (root route only) is needed for the edge case. Standing this up is the
  recipe's intended "adapt the marked spots" step.
- **Capture dir.** `$(pm qa captures-path pr-ac58803)/scenarios/<n>/...`,
  bind-mounted into the scenario container; all artifacts land there.

For the discovery scenarios (R1–R4): a pm checkout of this branch is enough;
the TUI sub-story additionally needs a running `pm session`.

## 3. Edge Cases (Given / When / Then)

### E1 — Non-SSE web UI (SSE layer is optional)
- **Given** a plain request/response web UI with no event stream.
- **When** the user follows the recipe, skipping the server-push spot and the
  `sse.log` step ("if the UI is SSE-driven").
- **Then** Layer 1 (video, trace, screenshots, DOM) and the `http.log` half
  of Layer 2 still complete, and the recipe reads sensibly without the SSE
  parts — the optionality holds.

### E2 — Concurrent subscribers on the shared `/events` endpoint
- **Given** an SSE web UI under capture with the Playwright browser connected
  to `/events`, **and** a second subscriber (a `curl -N` reader, and/or a
  second browser context) connected to the same endpoint at the same time.
- **When** a single side-channel change is triggered.
- **Then** every subscriber observes the push: the browser DOM updates *and*
  the curl transcript records the event — the shared event-stream surface
  fans out to all concurrent readers without one starving another. This is
  the recipe's own Layer-1 + Layer-2 simultaneous capture exercised as a
  genuine multi-subscriber test.

### E3 — Video finalization ordering
- **Given** the driver as written (resolves `page.video().path()` *after*
  `context.close()`, then renames to `recording.webm`).
- **When** the run completes.
- **Then** `recording.webm` exists and is non-empty/playable — confirming the
  documented flush ordering actually yields a video (a common Playwright
  foot-gun the recipe calls out).

### E4 — Container-safe flags are load-bearing
- **Given** the same container environment.
- **When** Chromium is launched **without** `--no-sandbox` /
  `--disable-dev-shm-usage`.
- **Then** launch/navigation fails (or crashes), demonstrating the documented
  flags are required — and that the recipe's launch line is the one that
  works.

### E5 — SSE reader bounded and non-hanging
- **Given** the Layer-2 `curl -sS -N --max-time <n>` reader.
- **When** no further events arrive after the triggered one.
- **Then** the reader exits on its own at `--max-time` (and the explicit kill
  is a no-op safety net), so the capture step never hangs the scenario.

### E6 — Parallel scenarios don't collide
- **Given** two QA scenarios that each follow the recipe (each binds the
  documented `PORT`, writes to its `scenarios/<n>/web-ui` capture path).
- **When** they run at the same time, each in its own isolated container.
- **Then** neither sees the other's port, server, or captures — the
  per-container isolation makes the recipe's hardcoded port/path safe to reuse
  across scenarios.

### E7 — Tooling absent / fallback
- **Given** an environment where Playwright/Chromium is not pre-installed.
- **When** the user follows the recipe's Tooling section.
- **Then** the documented fallback (`npm i -D playwright && npx playwright
  install --with-deps chromium`) is what's needed to proceed; if it can't be
  satisfied, that is a reportable gap against the "container ships these"
  claim.

## 4. Pass/Fail Criteria

**Pass:**
- R1–R4: the recipe is discoverable in `pm qa list`, printable via
  `pm qa show` (stem and filename), shown in the TUI QA pane, and resolves
  when referenced in `ARTIFACT:`.
- R5–R10: following the recipe verbatim against a representative web UI yields
  every promised artifact, each one *valid* — `recording.webm` plays and is
  non-empty, `trace.zip` opens in the trace viewer, screenshots and `dom.html`
  reflect the demonstrated states, `http.log` shows per-route status lines,
  `sse.log` shows the pushed event, and the SSE-driven DOM update is visible
  in the recording. Chromium launches with the documented flags. The shell
  and driver blocks parse cleanly.
- Edge cases behave as described: SSE layer is cleanly optional (E1), the
  shared event stream fans out to concurrent subscribers (E2), the webm is
  produced thanks to correct flush ordering (E3), the flags are shown to be
  required (E4), the SSE reader is bounded (E5), parallel scenarios are
  isolated (E6).

**Fail (examples):**
- The recipe is missing from any discovery surface, or its description is
  blank.
- Following the recipe produces a 0-byte/absent `recording.webm`, an
  unopenable `trace.zip`, or a missing `dom.html`/screenshots.
- Chromium fails to launch with the documented flags (would mean the recipe's
  launch line is wrong for the container).
- The SSE-driven DOM update never arrives, or `sse.log` is empty / the reader
  hangs.
- A concurrent subscriber misses the push that another receives.
- A copied shell/driver block fails to parse.

## 5. Ambiguities (resolved)

- **No committed UI to drive.** The recipe is generic and the repo has no web
  UI. *Resolved:* execution scenarios stand up a minimal representative
  web UI (one with `/events` SSE, one plain) — the recipe's intended
  adaptation step — rather than depending on the (separate-PR) walker.
- **Which `ARTIFACT:` to attach to execution scenarios.** *Resolved:* the
  recipe under test, `web-ui-recording.md`, is the correct artifact for any
  scenario whose surface is a rendered web UI — the scenario exercises the
  recipe precisely by following it to produce its own artifacts. Discovery
  scenarios capture the CLI/TUI surface with `cli-recording` /
  `tmux-screen-recording`.
- **No instruction exists for "set up a web UI."** *Resolved:* execution
  scenarios carry `INSTRUCTION: none` and include the minimal-UI setup
  inline in their STEPS; discovery-via-TUI uses `tui-manual-test`.
- **ffmpeg/mp4.** *Resolved:* dropped during genericization;
  `recording.webm` is the single load-bearing video and no transcode is
  expected.

No **[UNRESOLVED]** ambiguities.
