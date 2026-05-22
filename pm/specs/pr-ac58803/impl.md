# Spec: pr-ac58803 — QA artifact recipe: web UI recording (browser video + HTTP/SSE)

## Summary

Add one new QA artifact recipe, `pm/qa/artifacts/web-ui-recording.md`, that
tells a Claude-driven QA session how to capture evidence of the walker UI
(plan-litreview) behaving correctly. Two complementary capture layers:

1. **Rendered browser recording (primary)** — a Playwright (Node) driver
   script that drives headless Chromium through the walker, capturing a
   context-level video (`recording.webm` → `recording.mp4`), a Playwright
   trace (`trace.zip`), key-state PNG screenshots, and a DOM dump.
2. **Protocol capture (supplementary)** — `http.log` (curl route snapshots)
   and `sse.log` (`curl -N` transcript of `/events?review=<id>`).

Plus a `manifest.md` per the standard recipe format, and a new test module
covering frontmatter/discoverability, command well-formedness, and the
driver-script contract.

This is a **pure QA-doc PR** (one markdown recipe + tests). It changes no
runtime code. It documents capture procedure against a walker server that
is built by a separate PR (plan-litreview PR 3, `pr-d887f4c`); QA *execution*
of the recipe needs that server, but the recipe itself lands independently.

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
A Claude-authored Node Playwright driver-script skeleton in the recipe that:
- Launches Chromium container-safe:
  `chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] })`
  (matches pr-37073ad's documented runtime note).
- Records native context-level video:
  `browser.newContext({ recordVideo: { dir } })` → `recording.webm`,
  resolved via `page.video().path()` after `context.close()`; transcoded to
  `recording.mp4` with `ffmpeg` (optional).
- Captures a Playwright trace:
  `context.tracing.start({ screenshots: true, snapshots: true })` …
  `context.tracing.stop({ path: 'trace.zip' })`.
- Captures key-state PNG screenshots (`page.screenshot({ path })`) and a DOM
  dump (`page.content()` → `dom.html`).
- Drives the walker end-to-end through the canonical views — dashboard →
  proposed-changes (review) walker → audit browse → citations — using
  role/text locators with auto-wait (no brittle `sleep`s), per the
  plan-litreview "What the walker covers" section.
- Exercises hotkeys `j` / `k` / `a` / `m` / `s` (next / prev / accept /
  modify / skip) via `page.keyboard.press`.
- Triggers SSE-driven updates (a side shell edits `STATE.md` / appends audit
  entries) and waits for the view to react live via a Playwright auto-waiting
  locator — demonstrating the activity indicator animating and the Apply /
  lock-state transitions.
- References the `/events?review=<id>` SSE endpoint and the canonical view
  routes (keyed by review id), consistent with plan-litreview § Server-pushed
  updates and PR 3's route layout.
- Reuses the fixture / phase-driving setup from the `review-walker-ui`
  instruction (pr-5db0e85): register a review, materialize a multi-cycle
  fixture directory, launch `pm review ui --port <ephemeral>`, walk phases by
  editing `STATE.md`.

### R3 — Layer 2: protocol capture (curl)
- `http.log` — curl snapshots of the canonical walker routes.
- `sse.log` — `curl -N "$BASE/events?review=$ID"` transcript captured while a
  side shell mutates `STATE.md` / appends audit entries, proving the
  server-push contract underneath the rendered demo.
- Lightweight, greppable; supplementary to the rendered recording.

### R4 — Manifest
- Standard manifest frontmatter (`pr`, `workdir`, `captured_at`, `recipe`)
  per `qa_library.md` § Manifest.
- A `## Files` section listing every produced file with a one-line
  description: `recording.mp4` / `recording.webm`, `trace.zip`, the
  screenshots, the DOM dump (`dom.html`), `http.log`, `sse.log`.

### R5 — Requirements/pairing callouts
- Recipe states it requires pr-37073ad (Playwright + Chromium + ffmpeg
  pre-installed in the container image) and pairs with pr-5db0e85 (fixture
  setup instruction).

### R6 — Tests
New `tests/test_qa_artifact_web_ui_recording.py`:
- Recipe has valid frontmatter (`title`, `description` present, non-empty).
- Recipe is discoverable via the loader (`list_artifacts`, `get_instruction`
  with `category="artifacts"`, `resolve_instruction_ref`).
- Documented commands are well-formed: every `bash`/`sh` fenced block passes
  `bash -n`; the Node driver block passes `node --check` (skip if the
  interpreter is unavailable).
- The driver skeleton references the canonical view routes and the
  `/events?review=<id>` endpoint, records **both** video (`recordVideo`) and
  trace (`tracing.start`), and launches Chromium with container-safe flags
  (`--no-sandbox`, `--disable-dev-shm-usage`).
- The recipe's manifest/files section lists the required artifacts
  (recording, trace, screenshots, DOM dump, http.log, sse.log).

## 2. Implicit Requirements

- **Self-consistent fence parsing.** The test extracts fenced code blocks by
  language tag; the recipe must avoid nested triple-backtick fences (use
  4-space indentation for inner examples inside the manifest section) so the
  parser doesn't mis-pair fences. Language tags must be accurate: `bash` for
  shell, `javascript` for the Node driver, `text` for manifest/format
  examples.
- **`bash -n`-clean shell blocks.** Shell blocks use shell variables
  (`$CAPDIR`, `$PORT`, `$ID`, `$BASE`) with example assignments rather than
  `<...>` angle-bracket placeholders inside command position, so blocks parse
  cleanly and stay copy-pasteable. (`<...>` happens to pass `bash -n` too,
  but variables are unambiguous.)
- **`node --check`-clean driver.** The driver is wrapped in an async IIFE (or
  `async function main()` + call) so it is syntactically valid standalone;
  `node --check` validates syntax only, so Playwright/ffmpeg need not be
  installed for the test.
- **Capture-dir convention.** Writes land under the per-PR captures dir
  (`$(pm qa captures-path <pr-id>)/...`, the `<capture-dir>` placeholder used
  by the sibling recipes), never committed to the repo.
- **Video flush ordering.** Playwright only finalizes the webm on
  `context.close()`; the driver must resolve `page.video().path()` after
  closing and rename/transcode afterward. The recipe must call this out.

## 3. Ambiguities (resolved)

- **A1 — "review_browse" in the task's navigation list
  (`dashboard → changes walker → review_browse → audit_browse → citations`).**
  plan-litreview's template/view set is dashboard, changes (proposed-changes
  walker), audit_browse, citations, notes_pane — there is no separate
  "review_browse" view. **Resolution:** treat "review_browse" as the
  proposed-changes / review walker (`changes`) — i.e. browsing the review's
  proposed changes — and label it as such in the recipe. The navigation flow
  visits dashboard → changes (review/proposed-changes walker) → audit_browse
  → citations, with the notes pane mentioned as a side panel.
- **A2 — Exact page-route URLs.** The walker server (PR 3 / pr-d887f4c) is not
  built yet, so concrete page-route paths are not yet pinned in code; only
  `/events?review=<id>` is firmly specified by the plan. **Resolution:**
  document a canonical route convention keyed by review id (dashboard `/`,
  per-review views under `/review/<id>/{changes,audit,citations,notes}`,
  SSE `/events?review=<id>`) and note it tracks PR 3's server; have the driver
  prefer click-through navigation via role/text locators (which auto-track the
  server's real routes) over hardcoded URLs, using the route constants only
  for the initial dashboard load and the SSE endpoint. This keeps the recipe
  correct regardless of the server's final exact view paths.
- **A3 — Where the SSE-triggering edit happens.** The task says "in a side
  shell." **Resolution:** the recipe documents both — a side-shell edit
  (curl/`sed`/append) running concurrently, and, for a self-contained driver,
  an optional `child_process`/`fs` edit from within the Node script — then the
  driver waits on an auto-waiting locator reflecting the post-edit DOM, so
  there are no brittle sleeps.

No **[UNRESOLVED]** ambiguities.

## 4. Edge Cases

- **ffmpeg absent.** Transcode is optional; `recording.webm` is the
  load-bearing artifact and `recording.mp4` is the convenience copy. Recipe
  notes the fallback (keep the webm, skip transcode).
- **asciinema/tmux recipes unaffected.** This recipe is additive; the
  existing `cli-recording.md` / `tmux-screen-recording.md` cover terminal/CLI
  surfaces and remain the right choice there. The "When to use" section
  distinguishes: use this recipe only for the rendered web UI.
- **No cycles yet.** If `STATE.md` is absent the walker renders a "no cycles
  yet" placeholder; the recipe relies on pr-5db0e85's fixture to materialize a
  multi-cycle state first, so the demo has content to walk.
- **Lock states.** Editable hotkeys (`a`/`m`/`s`) only act in
  `awaiting-human-review` of the current cycle; the recipe drives `STATE.md`
  into that phase before exercising them, and demonstrates the read-only badge
  state in other phases.
- **Loader robustness.** The new recipe must not break existing loader tests:
  it is a normal `*.md` with valid frontmatter, so `list_all` / summary
  rendering keep working.
```
