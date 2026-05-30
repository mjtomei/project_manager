# QA Spec: pr-8e693f6 — Sign-off UI (per-PR BDD report + all-PR dashboard)

> **2026-05-30 rewrite.** The implementation was redesigned after the original
> spec was written (see PR note "dashboard-as-server" + the actual code). The
> dashboard is now a **localhost HTTP server**, not a static `index.html`
> generator; there is **no `report.json` sidecar** (the dashboard reads the
> sign-off verdict from a single `<meta name="pm-signoff-verdict">` tag in each
> agent-written `report.html`); the dashboard table is **minimal** (one flat
> table, columns PR / Title / Verdict / Report — no plan grouping, no status
> icons, no QA-tally / loop badges, no client-side filtering); and there is **no
> `pm pr report` command** (the per-PR report is purely agent-written). A new
> `pm md-render` CLI renders `.md` evidence to body-only HTML for the agent to
> embed. This spec has been brought in line with that code.

## Scope under test (user-visible surfaces this PR owns)

1. `pm pr dashboard [--port N] [--bind ADDR] [--open]` — starts a **blocking
   localhost HTTP server** (default `127.0.0.1:8765`) that rebuilds the all-PR
   index HTML on every `/` request from `project.yaml` + the captures dir, and
   serves each PR's agent-written `report.html` and its evidence siblings
   straight from `~/.pm/sessions/<tag>/captures/<pr_id>/`.
2. The dashboard index page itself: one row per PR with the pm id (+ GitHub
   `#N` when present), the title (read fresh from `project.yaml`), the sign-off
   verdict marker (icon + keyword, extracted from `report.html`'s head meta
   tag), and either an "open report" link (when `report.html` exists) or a
   "no report yet" empty state with a copyable `pm pr signoff <id>` command.
3. Liveness: a `report.html` that appears (or changes) after the server starts
   shows up on the next page load with no restart and no regeneration step.
4. The sign-off prompt extension (the prompt `pm pr signoff` shows the agent) —
   it directs the agent to write `$CAP/report.html` as a deliverable, names the
   `<meta name="pm-signoff-verdict" content="SIGNOFF_*">` dashboard contract,
   and specifies the evidence-rendering policy (embed video/img/audio/asciinema
   inline; `pm md-render` for `.md`; link `.html`/large binaries).
5. `pm md-render <path>` — renders a `.md` file to body-only HTML on stdout
   (CommonMark + tables + fenced code), used by the sign-off agent to inline
   markdown evidence.
6. The `sign_off` status across all status surfaces: `pm status`, `pm pr list`,
   and the TUI tech tree show the `sign_off` icon and (once a verdict is
   recorded on `pr['signoff']`) the matching sign-off verdict marker.
7. The sign-off routing flow under auto-sequence: a QA PASS advances the PR to
   `sign_off`, the router's verdict is recorded and adopted, and each verdict
   routes to the correct next hop (`SIGNOFF_MERGE` → `ready_to_merge` and the
   PR stays in `sign_off`; `SIGNOFF_IMPL`/`SIGNOFF_REVIEW`/`SIGNOFF_REQA` bounce
   back; `SIGNOFF_BLOCKED` pauses).
8. Forward-compatibility plumbing: `qa_loop` writes `scenarios/<n>/scenario.json`
   (`index / title / focus / steps / verdict / reason`) alongside `verdict.md`.

Out of scope (owned upstream by pr-2d5f712, already merged in): the sign-off
window's internal layout and the actual agent authoring the report.

## Requirements (Given / When / Then)

### R1 — Dashboard server serves the all-PR index
* GIVEN a pm project with several PRs in mixed states and NO `report.html`
  files in the captures dir yet.
* WHEN the user runs `pm pr dashboard` (e.g. with `--port 0` to pick a free
  port) and fetches `/` over HTTP.
* THEN the server prints the served URL and stays in the foreground; the page
  is a complete HTML document with one row per PR from `project.yaml`, each row
  showing the pm id, the title, a "verdict unknown / —" cell, and a "no report
  yet" empty state containing a copyable `pm pr signoff <pr_id>` command.

### R2 — Dashboard surfaces an agent-written report
* GIVEN a PR whose captures dir contains a `report.html` with a
  `<meta name="pm-signoff-verdict" content="SIGNOFF_MERGE">` tag in its `<head>`
  and some evidence siblings (e.g. a `.png`).
* WHEN the user runs `pm pr dashboard` and loads `/` then the report link.
* THEN the PR's row shows the `SIGNOFF_MERGE` verdict marker (icon + keyword,
  matching `signoff.SIGNOFF_VERDICT_ICONS` used by the TUI / `pm pr list`) and
  an "open report" link; following the link serves the agent's `report.html`
  over HTTP, and its evidence siblings resolve from the same captures root.

### R3 — Liveness (rebuild per request)
* GIVEN the dashboard server is already running and a PR shows the "no report
  yet" empty state.
* WHEN a `report.html` for that PR appears in the captures dir (or its verdict
  meta tag changes) and the user reloads `/`.
* THEN the row flips to the populated state (verdict marker + open-report link)
  on the next load with no server restart; the verdict shown tracks the meta
  tag's current value.

### R4 — Sign-off prompt instructs the agent
* GIVEN a PR in `qa`/`sign_off` status with a workdir.
* WHEN `pm pr signoff <pr_id>` builds the sign-off prompt the agent receives.
* THEN the prompt names `$CAP/report.html` as a required deliverable, states the
  dashboard's single-meta-tag verdict contract verbatim
  (`<meta name="pm-signoff-verdict" content="...">`), enumerates the five
  routing verdicts, and gives the evidence-rendering policy (inline embeds for
  media; `pm md-render` for markdown; link `.html`/large binaries). It does
  NOT mention a `report.json` sidecar.

### R5 — `sign_off` status across status surfaces
* GIVEN a project with a PR in `sign_off` and a recorded sign-off verdict on
  `pr['signoff']`.
* WHEN the user runs `pm status`, `pm pr list`, and opens the TUI tech tree.
* THEN `pm status` lists the `sign_off` count with its icon; `pm pr list` and
  the TUI tech tree render the PR with the `sign_off` status icon plus the
  recorded sign-off verdict marker — all sourced from
  `signoff.SIGNOFF_VERDICT_ICONS` so they agree with each other and the
  dashboard. Other statuses are unaffected.

### R6 — Sign-off routing under auto-sequence
* GIVEN a PR that has passed QA (auto-sequence advances it to `sign_off`),
  driven against fake-Claude so the router pane emits a chosen `SIGNOFF_*`
  verdict.
* WHEN the auto-sequence driver ticks the `sign_off` PR.
* THEN the verdict is recorded on `pr['signoff']` (origin auto-sequence) and the
  routed hop happens: `SIGNOFF_MERGE` reports `ready_to_merge` and leaves the
  PR in `sign_off`; `SIGNOFF_IMPL` bounces to impl; `SIGNOFF_REVIEW` returns to
  review; `SIGNOFF_REQA` re-runs QA; `SIGNOFF_BLOCKED` pauses. A bounce retires
  the stale sign-off window + transcript so re-entry runs a fresh router.

### R7 — `pm md-render` renders markdown evidence
* GIVEN a `.md` file with a heading, a table, and a fenced code block.
* WHEN the user runs `pm md-render <path>`.
* THEN stdout is a body-only HTML fragment (no `<html>`/`<head>`/`<style>`
  shell) with the table and fenced code rendered as HTML.

### R8 — qa_loop persists `scenario.json` alongside `verdict.md`
* GIVEN a PR run through a QA loop (driven by fake-Claude) producing scenario
  verdicts.
* WHEN QA completes and the captures dir is inspected.
* THEN each scenario's capture dir contains both `verdict.md` and a
  `scenario.json` carrying `index / title / focus / steps / verdict / reason`.

## Edge Cases

### E1 — Verdict meta-tag extraction is robust
* GIVEN per-PR `report.html` files that variously: put `content` before `name`
  in the meta tag; use lowercase/mixed-case attribute quoting; mention a
  `SIGNOFF_*` keyword only in the `<body>` (not the head meta tag); have no
  meta tag at all; or are unreadable/garbage.
* WHEN the dashboard renders these rows.
* THEN the verdict is correctly extracted regardless of attribute order/case;
  a keyword only in `<body>` is NOT picked up (head-only scan → "verdict
  unknown"); a missing tag or unreadable file degrades to "verdict unknown"
  without a crash or broken HTML; the rest of the page renders normally.

### E2 — Dynamic text is HTML-escaped
* GIVEN a PR whose title contains `<script>alert(1)</script>` and shell-active
  characters.
* WHEN the dashboard page is rendered/loaded in a browser.
* THEN the title appears as literal text (no script execution, no layout
  break) and the page source shows the angle brackets escaped. The copyable
  `pm pr signoff <id>` command is likewise escaped.

### E3 — No session tag / captures root unresolvable
* GIVEN a shell not inside a pm tmux session and a cwd that yields no derivable
  session tag.
* WHEN the user runs `pm pr dashboard`.
* THEN the command exits non-zero with a clear message that the captures root
  could not be resolved — it does not start a server pointed at a bogus dir.

### E4 — Port already in use
* GIVEN a dashboard server already bound to the default port.
* WHEN the user runs a second `pm pr dashboard` on the same port.
* THEN the second exits with a friendly one-line message (cannot bind, is a
  dashboard already running, suggests `--port 0` / another port) — no
  traceback. Re-running with `--port 0` succeeds on a free port.

## Concurrency (shared resources the diff touches)

Shared resources: the dashboard TCP socket (single default port `8765`); the
captures root dir served as the HTTP document root; each PR's `report.html` +
evidence siblings; the per-PR sign-off tmux window + its single
`signoff-<id>.jsonl` transcript; the per-PR workdir-provisioning lock
(`.workdir-<id>.lock`) and sign-off launch lock
(`.signoff-launch-<session>-<id>.lock`); `pr['signoff']` in `project.yaml`.

### C1 — Concurrent requests while a report is being written
* GIVEN a running dashboard server (ThreadingHTTPServer) and several PRs.
* WHEN multiple HTTP clients hit `/` concurrently while a `report.html` is
  being (re)written under the captures root.
* THEN every response is a complete, well-formed HTML document with a row for
  every PR; no truncated/half-built page; no server crash.

### C2 — Concurrent sign-off launches don't duplicate windows or corrupt the workdir
* GIVEN a PR eligible for sign-off whose workdir does not yet exist.
* WHEN two `pm pr signoff <id>` invocations race (e.g. from two shells).
* THEN exactly one sign-off window is created (the per-PR launch lock serializes
  the check-then-create) and the workdir is cloned once (the workdir lock makes
  the loser adopt the winner's clone) — no duplicate windows, no traceback from
  one process pulling the workdir out from under the other.

## Pass/Fail Criteria
* The dashboard server serves a well-formed page whose rows / verdict markers /
  links match project state and the on-disk `report.html` files; per-PR reports
  and evidence load over HTTP from the captures root.
* No dashboard scenario produces a crash, traceback, or unescaped dynamic text.
* `pm status`, `pm pr list`, and the TUI all expose `sign_off` and its verdict
  marker consistently, without regressing other statuses.
* Sign-off routing records and acts on the verdict correctly under
  auto-sequence; a manual `pm pr signoff` never mutates state.
* `pm md-render` emits a body-only fragment with tables + fenced code rendered.
* Each QA scenario capture dir gains a `scenario.json` alongside `verdict.md`.

## Ambiguities (resolved)
* Dashboard delivery — RESOLVED as a localhost HTTP server (`pm pr dashboard`),
  not a static file. Liveness comes from rebuilding per request.
* Verdict source — RESOLVED as a single `<meta name="pm-signoff-verdict">` tag
  in the agent-written `report.html`; the `report.json` sidecar was removed.
* Per-PR report — RESOLVED as agent-written only (no deterministic renderer, no
  `pm pr report` command). Regenerate = plain `pm pr signoff <id>`.
* Dashboard scope — RESOLVED as a minimal flat table (no plan grouping, no
  status icons, no tally/loop badges, no client-side filtering).
