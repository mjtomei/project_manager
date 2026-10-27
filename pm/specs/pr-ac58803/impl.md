# Spec: pr-ac58803 — QA artifact recipe: web UI recording (browser video + HTTP/SSE)

> **Update note (review-loop 9451):** the recipe was deliberately
> *genericized* during implementation (commits 4bf1a5a5 / 0d4aa824 /
> 24a1ebc2: "drop PR-referencing Requirements section", "genericize
> remaining walker jargon", "drop walker example + transcoding, fully
> genericize"). It is now a **reusable, web-UI-agnostic** recipe — matching
> the sibling recipes (`cli-recording.md`, `tmux-screen-recording.md`),
> which are likewise generic library entries, not plan-scoped. This spec has
> been rewritten to describe the delivered generic recipe rather than the
> walker-specific draft. A walker QA session consumes this generic recipe
> together with the fixture-setup instruction (pr-5db0e85), adapting the
> marked spots in the driver.

## Summary

Add one new QA artifact recipe, `pm/qa/artifacts/web-ui-recording.md`, that
tells a Claude-driven QA session how to capture evidence of any **rendered
web UI** behaving correctly. Two complementary capture layers:

1. **Rendered browser recording (primary)** — a Playwright (Node) driver
   skeleton that drives headless Chromium through the UI, capturing a
   context-level video (`recording.webm`), a Playwright trace (`trace.zip`),
   key-state PNG screenshots, and a DOM dump (`dom.html`).
2. **Protocol capture (supplementary)** — `http.log` (curl route snapshots)
   and `sse.log` (`curl -N` transcript of the SSE endpoint, for
   server-pushed UIs).

Plus a `manifest.md` per the standard recipe format, and a new test module
covering frontmatter/discoverability, command well-formedness, and the
driver-script contract.

This is a **pure QA-doc PR** (one markdown recipe + tests). It changes no
runtime code. The recipe is generic; QA *execution* against the
plan-litreview walker pairs it with the fixture-setup instruction
(pr-5db0e85) and needs the walker server (pr-d887f4c), but the recipe itself
is independent of any one UI.

## 1. Requirements (grounded in the codebase)

### R1 — Recipe file + discoverability via the QA artifact-library loader
- File: `pm/qa/artifacts/web-ui-recording.md`.
- Must have YAML frontmatter with `title` and `description` (the two
  required fields per `pm_core/docs/qa_library.md` § Frontmatter fields).
- The loader is `pm_core/qa_instructions.py`:
  - `_parse_frontmatter()` parses `---`-delimited YAML.
  - `list_artifacts(pm_root)` → `_list_dir(artifacts_dir(pm_root))` discovers
    every `*.md` under `pm/qa/artifacts/`; the new file must appear with a
    non-empty `title` and `description`.
  - `get_instruction(pm_root, "web-ui-recording", category="artifacts")`
    must return the parsed body.
  - `resolve_instruction_ref(pm_root, "web-ui-recording")` must resolve to
    `("artifacts", "web-ui-recording.md")` (exact + bare-stem matching).
- Body conventions follow the existing recipes
  (`pm/qa/artifacts/cli-recording.md`, `tmux-screen-recording.md`) and
  `qa_library.md` § Artifact recipes: **When to use / What this recipe
  produces / Capture / Manifest format / Reviewing** sections.

### R2 — Layer 1: rendered browser recording (Playwright driver skeleton)
A Claude-authored, **UI-agnostic** Node Playwright driver skeleton in the
recipe that:
- Launches Chromium container-safe:
  `chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] })`.
- Records native context-level video:
  `browser.newContext({ recordVideo: { dir } })`, resolved via
  `page.video().path()` after `context.close()` and renamed to
  `recording.webm`. (No ffmpeg/`.mp4` transcode — `recording.webm` is the
  single load-bearing video; it plays in browsers and in
  `playwright show-trace`. The transcode step was dropped during
  genericization.)
- Captures a Playwright trace:
  `context.tracing.start({ screenshots: true, snapshots: true })` …
  `context.tracing.stop({ path: 'trace.zip' })`.
- Captures key-state PNG screenshots (a `shot()` helper wrapping
  `page.screenshot({ path })`) and a DOM dump (`page.content()` →
  `dom.html`).
- Drives the UI via auto-waiting role/text locators (no brittle `sleep`s):
  `page.goto(appUrl)`, a `waitFor()` on an entry-state locator, an example
  interaction (`page.keyboard.press('j')`), and a clearly-marked
  server-pushed-update spot (trigger the change through a side channel, then
  `await locator.waitFor(...)` on the resulting DOM).
- Reads `CAPDIR` / `APP_URL` from the environment; wrapped in an async IIFE
  with a `.catch()` that logs and `process.exit(1)` so the skeleton is valid
  standalone and fails loudly.
- Every UI-specific detail (locators, the interaction, the side channel that
  triggers live updates) is marked as a replace-spot for the QA author to
  adapt — including, for the walker, the `/events?review=<id>` endpoint and
  the `j/k/a/m/s` hotkeys, supplied at adaptation time rather than baked in.

### R3 — Layer 2: protocol capture (curl)
- `http.log` — a loop of `curl -sS -w` snapshots over the routes of interest.
- `sse.log` — `curl -sS -N --max-time <n>` transcript of the SSE endpoint
  (`$APP_URL/events` in the generic skeleton), captured in the background
  while a side channel triggers a server-pushed change, then the reader is
  killed.
- Lightweight, greppable; supplementary to the rendered recording.

### R4 — Manifest
- Standard manifest frontmatter (`pr`, `workdir`, `captured_at`, `recipe`,
  plus `app_url`) per `qa_library.md` § Manifest, shown as a 4-space-indented
  (not fenced) example so the recipe stays one fence level deep.
- A `## Files` section listing every produced file with a one-line
  description: `recording.webm`, `trace.zip`, the screenshots, the DOM dump
  (`dom.html`), `http.log`, `sse.log`.

### R5 — Tooling callout
- A **Tooling** section states the recipe needs Playwright + its bundled
  Chromium, notes the QA container image ships them, and gives the
  non-container install fallback
  (`npm i -D playwright && npx playwright install --with-deps chromium`).
  (PR-id references — pr-37073ad for the container image, pr-5db0e85 for the
  walker fixture — were intentionally dropped from the recipe body during
  genericization, since recipes are generic library entries; the pairing is
  recorded in this spec instead.)

### R6 — Tests
New `tests/test_qa_artifact_web_ui_recording.py`:
- Recipe has valid frontmatter (`title`, `description` present, non-empty).
- Recipe is discoverable via the loader (`list_artifacts`, `get_instruction`
  with `category="artifacts"`, `resolve_instruction_ref` for bare-stem and
  filename forms).
- Documented commands are well-formed: every `bash`/`sh` fenced block passes
  `bash -n`; the Node driver block passes `node --check` (skip if the
  interpreter is unavailable).
- The driver skeleton records **both** video (`recordVideo`) and trace
  (`tracing.start`), launches Chromium with container-safe flags
  (`--no-sandbox`, `--disable-dev-shm-usage`), navigates and interacts
  (`page.goto`, a screenshot, a keyboard/click), and dumps the DOM
  (`page.content()`).
- The protocol layer is present (`http.log`, `sse.log`, `curl`, the `-N`
  streaming flag).
- The manifest/files section lists the required artifacts (`recording.webm`,
  `trace.zip`, `dom.html`, `http.log`, `sse.log`, and `.png` screenshots).

## 2. Implicit Requirements

- **Self-consistent fence parsing.** The test extracts fenced code blocks by
  language tag; the recipe must avoid nested triple-backtick fences (inner
  examples in the manifest section use 4-space indentation) so the parser
  doesn't mis-pair fences. Language tags are accurate: `bash` for shell,
  `javascript` for the Node driver.
- **`bash -n`-clean shell blocks.** Shell blocks use shell variables
  (`$CAPDIR`, `$PORT`, `$APP_URL`, `$SSE_URL`) with example assignments so
  blocks parse cleanly and stay copy-pasteable.
- **`node --check`-clean driver.** The driver is wrapped in an async IIFE so
  it is syntactically valid standalone; `node --check` validates syntax only,
  so Playwright/ffmpeg need not be installed for the test.
- **Capture-dir convention.** Writes land under the per-PR captures dir
  (`$(pm qa captures-path <pr-id>)/...`, the `<capture-dir>` placeholder used
  by the sibling recipes), never committed to the repo.
- **Video flush ordering.** Playwright only finalizes the webm on
  `context.close()`; the driver resolves `page.video().path()` *after*
  closing and renames afterward. The recipe calls this out in a comment.

## 3. Ambiguities (resolved)

- **A1 — walker navigation list / "review_browse".** Mooted by
  genericization: the recipe no longer hardcodes the walker's
  dashboard → changes → audit → citations flow. The driver provides a
  generic navigate-and-interact skeleton; the QA author maps it onto the
  walker's real views at adaptation time.
- **A2 — exact page-route URLs.** Mooted by genericization: the skeleton
  drives an `APP_URL` base and prefers auto-waiting role/text locators
  (click-through) over hardcoded routes, so it tracks whatever routes the
  server-under-test exposes. The walker's `/events?review=<id>` SSE endpoint
  is supplied when the recipe is adapted, not baked in.
- **A3 — where the SSE-triggering edit happens.** The skeleton documents a
  marked "trigger through a side channel" spot (a mutating request or a
  watched-file write) plus a curl-driven Layer-2 equivalent, then waits on an
  auto-waiting locator reflecting the post-edit DOM — no brittle sleeps.

No **[UNRESOLVED]** ambiguities.

## 4. Edge Cases

- **No mp4 / ffmpeg.** `recording.webm` is the single load-bearing video; no
  transcode step. (ffmpeg from pr-37073ad's image is simply unused by this
  recipe.)
- **asciinema/tmux recipes unaffected.** This recipe is additive; the
  existing `cli-recording.md` / `tmux-screen-recording.md` cover terminal/CLI
  and pm-TUI surfaces and remain the right choice there. The "When to use"
  section distinguishes: use this recipe only for a rendered (browser) web UI.
- **Non-SSE UIs.** The SSE layer and the driver's server-push spot are
  explicitly optional ("if the UI is SSE-driven"), so the recipe applies to
  plain request/response web UIs too.
- **ffmpeg / interpreter absent at test time.** `bash -n` / `node --check`
  tests skip cleanly when the interpreter is missing; the driver needs no
  Playwright install to pass `node --check`.
- **Loader robustness.** The new recipe is a normal `*.md` with valid
  frontmatter, so `list_all` / summary rendering keep working and existing
  loader tests are unaffected.
