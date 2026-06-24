# Spec: Sign-off UI — per-PR BDD report + all-PR behavior dashboard

PR: pr-8e693f6 (#226) · Plan: plan-regression
Depends on: pr-2d5f712 (sign-off step / window / `signoff` session type — **MERGED**)
Forward-compatible with: pr-06a96fa (evidence model), pr-ff9b728 (plan notes).

## Architecture (post-clarification — note-537e1a0, note-a8bc547; sidecar dropped 2026-05-30; dashboard moved from static file to local server 2026-05-30)

The original description read like a deterministic Python renderer for both
surfaces. Two scope-clarification notes mid-loop pinned the actual mechanism,
a later refactor (commit fca8c07d) dropped the JSON sidecar entirely, and a
follow-up clarification replaced the static `index.html` with a local HTTP
server so liveness is dynamic:

* **Per-PR `report.html` is AGENT-WRITTEN.** Captures are heterogeneous enough
  that coherent per-behavior framing requires the same semantic pass that
  produces the routing verdict — the sign-off agent itself. So #226's main
  work is **extending pr-2d5f712's sign-off prompt** to require the agent to
  write `$CAP/report.html` on every sign-off pass, with the BDD section schema
  + relative-link discipline + top-of-page bullets. **No per-PR HTML rendering
  in code.** The report is framed as a *replacement* for human code review:
  it must stand on its own (carry the diff, the evidence, the recommendation)
  so a reviewer can trust the verdict without opening the diff, with full
  depth folded behind `<details>` for auditing.
* **No JSON sidecar.** `report.html` is the canonical artifact. The single
  piece of structured data the dashboard needs — the routing verdict — is
  embedded as a `<meta name="pm-signoff-verdict" content="SIGNOFF_*">` tag in
  the report's `<head>` and read back at dashboard-generation time. This makes
  the dashboard's verdict and the report's verdict impossible to disagree.
  (The earlier `report.json` sidecar duplicated `project.yaml` / QA-status
  state and its only agent-derived fields — loop badge counts — were chrome,
  so it was removed.)
* **The dashboard is served, not written.** `pm pr dashboard` starts a small
  localhost HTTP server (`pm_core/dashboard_server.py`, stdlib `http.server`)
  bound to `127.0.0.1` only. Every `/` request rebuilds the index from
  `project.yaml` + the captures dir at request time so liveness is implicit
  — a new report shows up on the next page load with no regeneration step.
  Per-PR `report.html` and its evidence siblings are served straight from
  `<captures>/<pr_id>/...`. The page lists one row per PR (pm id, GitHub #,
  title, verdict, link to `report.html`) and **never interprets captures**
  beyond reading the one verdict meta tag from each `report.html`. PR
  runtime state (title) is read fresh from `project.yaml` at request time
  so it can't go stale. **No on-disk `index.html`** — there is nothing to
  commit and nothing to keep in sync.
* **Regenerate-the-report = plain `pm pr signoff <id>`.** No "write-only"
  mode. Outside auto-sequence, manual sign-off is recommendation-only (the
  manual-never-acts invariant pr-2d5f712 established in note-1a982f3 /
  note-942fa37), so re-running is safe — the agent re-emits the report and
  may adopt an existing fresh verdict per the adoption rule (note-511d725)
  without triggering another action.

## Requirements (grounded)

### R1 — Sign-off prompt extension (the producer)
Extend `pm_core.prompt_gen.generate_signoff_prompt` with a new "Write the
sign-off report (deliverable)" step before the route step. The extension
specifies:

* **One deliverable file** the agent must write into `$CAP = $(pm qa
  captures-path <id>)`: `report.html` (human-facing BDD report). Evidence
  files live alongside it; the report references them by relative path so the
  page opens over `file://`. No JSON sidecar.
* **`report.html` structure** (suggested shape — the prompt frames the
  sections as a recommendation the agent adapts, not a rigid prescription):
  1. **Header** — title, routing verdict marker via `SIGNOFF_VERDICT_ICONS` /
     `SIGNOFF_VERDICT_STYLES`, one-line Recommendation with the
     `ready_to_merge` framing (sign-off recommends, never merges; the plan
     watcher decides), link back to `../index.html`. **Hard requirement:** a
     `<meta name="pm-signoff-verdict" content="SIGNOFF_*">` tag in `<head>`
     carrying the routing verdict — the dashboard's only machine-readable
     contract.
  2. **Table of contents** — anchor links into every section.
  3. **Top-of-page summary — "what this PR delivers + proof it works"**
     (the headline; what the reviewer reads first). Two paired bullet
     lists, **one line per item, plain English, no internal jargon**:
     * **What this PR delivers** — every user-visible behaviour, interface,
       or code area shipped. Treated as the PR's release notes; one line per
       item, linked to its diff anchor / commit.
     * **Demonstrations** — for every "delivers" bullet above, embed the
       inline evidence right there (prefer `.webm` screen captures over
       text logs). A bullet with no demonstration must say so explicitly
       and explain why (e.g. "schema-only change, verified via type-check
       evidence below"); silent omission reads as incomplete verification.
     * **Bounce rule** — if the agent can't enumerate what the PR delivered
       or a delivered behaviour has no watchable evidence (and isn't a
       justifiable text-only exception), the agent routes `SIGNOFF_REQA`
       and leaves a `pm pr note add <pr_id> '...'` entry naming exactly
       what's missing. QA owns producing demonstration evidence; sign-off
       never papers over an undemonstrated feature. The `SIGNOFF_REQA`
       verdict definition picks up "every behaviour this PR delivers has a
       watchable demonstration recorded" as an explicit QA acceptance
       criterion.
     * **Loop findings & project-level implications** (secondary, below the
       headline; context the planner needs but the immediate reviewer
       doesn't have to read first): bugs the review/QA loop found and
       fixed in this branch with the area of code they hid in; spec
       ambiguities resolved (question / answer / who decided) and
       *unresolved* (flagged for human input); open questions and
       follow-up PRs to file.
  4. **Per-step sections** (Implementation / Review / QA) — each with explicit
     **acceptance criteria** and the evidence paired with them. Bug PRs render
     Implementation as Before (pre-fix: bug reproduces) / After (post-fix:
     symptom gone), flagging a missing phase.
  5. **Code change (the diff)** — there is no web UI for the diff elsewhere,
     so the report carries it: a per-file inline TOC, then one collapsed
     `<details>` per file with HTML-escaped `<pre><code class="diff">` output.
  6. **Context for sign-off** — PR description, PR notes, plan name + notes.
* **Two reading depths in one page** — top-line content (header,
  recommendation, "what this PR delivers" + demonstrations, per-step
  conclusions) is enough for a brief read to trust the verdict; full
  depth (diff, scenario evidence, captures) is folded behind `<details>`
  collapsed by default for the auditing reviewer.
* **Evidence rendering** — embed-first: `<video>` for `.webm`, `<img>`
  for images, `<audio>` for audio, `<details><pre>` for small text/log;
  for `.md`, run `pm md-render <path>` and embed the body-only fragment
  inline; link as-is for `.html` and large binaries.
* **No audit-trail step** — the report itself is the audit surface
  (per-step sections + linked evidence). Earlier iterations of the prompt
  asked the agent to also create one `pm pr note add` entry per routing
  decision; that was dropped because it duplicates the report and
  clutters the notes list without adding inspectable content. The agent
  only writes a note when the bounce rule above fires (to name what's
  missing for QA).
* **Single sources of truth** — match the TUI tech tree + `pm pr list` by
  pointing the agent at `signoff.SIGNOFF_VERDICT_ICONS` /
  `SIGNOFF_VERDICT_STYLES`.

### R2 — All-PR dashboard (served locally)
`pm_core/behavior_report.py` builds the dashboard HTML in-memory:
`gather_dashboard_rows(data, captures_root_dir)` walks `project.yaml` + the
captures dir and `render_dashboard_html(rows)` produces the HTML string. The
table has six columns:

* **PR** — pm canonical id (`pr-XXXXXXX`) + GitHub `#NNN` label when present.
* **Title** — read fresh from `project.yaml` at request time, never cached.
* **Status** — PR lifecycle status (`pending`, `in_progress`, `in_review`,
  `qa`, `sign_off`, `merged`, `closed`), with the icon from
  `helpers.PR_STATUS_ICONS` (single source shared with `pm pr list` and the
  TUI tech tree). Sorted by a lifecycle rank (`_STATUS_RANK`):
  `closed < merged < pending < in_progress < in_review < qa < sign_off`. The
  column header carries `data-default-dir="desc"` so the first click puts
  `sign_off` at the top (then `qa`, `in_review`, …), the natural "what
  needs my attention now" view; the second click flips to lifecycle ASC.
* **Last modified** — relative time (`Xs ago` / `Xm ago` / `Xh ago` / `Xd ago`)
  derived from the `report.html` mtime. The cell title attribute carries the
  absolute UTC timestamp; the cell's `data-sort` is the raw unix mtime so the
  JS sorter has a numeric key. **Default sort:** this column descending —
  most recently regenerated report at the top. Rows with no report sort to
  the bottom.
* **Verdict** — `SIGNOFF_*` keyword read at request time from a single
  `<meta name="pm-signoff-verdict" content="SIGNOFF_*">` tag in each PR's
  `$CAP/<pr_id>/report.html` (`_extract_verdict`). When the report exists
  but carries no meta tag, the cell shows "verdict unknown". The marker
  reuses `signoff.SIGNOFF_VERDICT_ICONS` / `SIGNOFF_VERDICT_STYLES` (mapped
  to CSS via `_RICH_COLOR_CSS`) so the dashboard matches the TUI and
  `pm pr list`.
* **Report** — when present, a link to `<pr_id>/report.html`; when absent,
  a single plain-text "no report yet" cell. **No regenerate command and no
  copy button** — the dashboard is read-only chrome, not a launcher; a
  reviewer who wants a report runs `pm pr signoff <id>` themselves.

Every header is click-to-sort (`pmSort(col)`); the JS reads each cell's
`data-sort` attribute (falling back to text content). `pmSort` toggles
asc/desc on repeat clicks; first-click direction comes from the header's
`data-default-dir` (default `asc`, except Status and Last modified which
both default `desc`). Sort indicators (▲/▼) render on the active column
via CSS classes on the `<th>`.

A search input above the table (`pmFilter()`) hides rows whose visible
text doesn't contain the query (case-insensitive substring across all
columns). Empty query shows everything.

`_extract_verdict` reads only the first 256 KB of `report.html`
(`_HEAD_READ_CAP`) so the dashboard doesn't slurp a multi-MB body — the
diff is embedded in the page but the verdict tag lives in `<head>`. It
only scans the `<head>` region (so a verbatim verdict keyword in `<body>`
text isn't a false match) and parses the meta tag's `name` / `content`
attributes independently of their order.

`pm_core/dashboard_server.py` exposes `serve(pm_root, captures_root_dir, *,
host="127.0.0.1", port, open_browser)`. It runs a `ThreadingHTTPServer`
bound to localhost; `/` rebuilds the dashboard fresh on every request,
everything else falls through to `SimpleHTTPRequestHandler` rooted at
`captures_root_dir` so `report.html` and its evidence siblings are served
straight from disk. An `Address already in use` failure surfaces as a
one-line hint instead of a traceback.

**Note — scope evolution vs the original description.** The description
called for client-side filtering (by status, by merged/unmerged), plan
grouping with plan-notes pass-through, QA-verdict tallies, and loop badges.
The 2026-05-30 refactor (commit fca8c07d) removed all of these along with
the JSON sidecar. Subsequent follow-up requests brought sort and a single
text filter back in (rather than the original multi-select filter
controls), and added Status + Last modified columns; plan grouping, QA
tallies, and loop badges remain out of scope. The dashboard is read-only
chrome and never interprets captures beyond the verdict meta tag.

### R3 — CLI surface
* **Remove** the retired `pm pr report` / `pm pr signoff-record` commands.
* **`pm pr dashboard [--port N] [--bind HOST] [--open]`** — starts the
  local dashboard server. Default port `8765`, default bind `127.0.0.1`
  (never `0.0.0.0` by default — security). `--open` launches the user's
  browser at the served URL. Foreground / blocking; Ctrl-C shuts down
  cleanly. No file is written.
* **Add** `pm md-render <path>` — body-only HTML for the sign-off agent
  to embed `.md` evidence inline.
* **`pm pr merge`** gains `--no-signoff-check`. The default behaviour now
  refuses to merge a PR unless `pr["signoff"]["verdict"] == SIGNOFF_MERGE`
  *and* the recorded sha matches current HEAD (i.e. the verdict is fresh
  — code hasn't moved since sign-off ran). The override is for propagation
  / recovery flows and similar cases where the gate is explicitly being
  bypassed. The internal `--propagation-only` flag implicitly bypasses the
  gate too (it skips the workdir merge step).

### R3.5 — Sign-off → merge gate
`pm pr merge` enforces the merge gate inline (no separate watcher). The
check sits between the existing pending/merged status guards and the
backend-specific merge logic, and uses `signoff.fresh_recorded_verdict`
to decide. Failure modes surface distinct messages so the operator knows
exactly why the gate fired:

* **No verdict recorded** → "no sign-off verdict recorded yet. Run
  `pm pr signoff <pr_id>` first, or pass --no-signoff-check to override."
* **Stale SIGNOFF_MERGE** (recorded sha ≠ current HEAD) → "recorded
  sign-off verdict SIGNOFF_MERGE is stale (HEAD moved since). Re-run
  `pm pr signoff <pr_id>` against current HEAD, or pass
  --no-signoff-check to override."
* **Non-merge verdict** (`SIGNOFF_IMPL`, `SIGNOFF_REVIEW`, `SIGNOFF_REQA`,
  `SIGNOFF_BLOCKED`) → "sign-off verdict is `<VERDICT>`, not
  SIGNOFF_MERGE. Run `pm pr signoff <pr_id>` to re-route, or pass
  --no-signoff-check to override."

The gate is a CLI-level enforcement; the auto-sequence merge path goes
through the same `pm pr merge` code, so it inherits the gate
automatically (auto-sequence flips status only after a SIGNOFF_MERGE
verdict adoption, so the gate is a no-op in the happy auto path).

### R4 — Forward-compat captures
Keep the additive `scenarios/<n>/scenario.json` write in
`qa_loop._persist_scenario_verdicts` so the sign-off agent can synthesize the
per-behavior BDD section without re-parsing `verdict.md`. Old captures still
work (the agent reads whatever's there).

### R5 — Safety / robustness
* Dashboard HTML escapes all dynamic text (`html.escape`); the sign-off agent
  is instructed to do likewise in its own `report.html`.
* Missing `report.html` → dashboard row renders a plain-text "no report yet"
  cell; never crashes the index.
* `_extract_verdict` reads at most `_HEAD_READ_CAP` bytes (256 KB), only
  scans the `<head>` region (so a verbatim verdict keyword in `<body>` text
  isn't a false match), and parses the meta tag's `name` / `content`
  attributes independently of their order.
* The dashboard server binds `127.0.0.1` by default — an explicit `--bind`
  is required to expose it on a non-loopback interface. Port-already-in-use
  surfaces as a one-line hint, not a traceback.
* `pm pr merge`'s sign-off gate fails closed: any branch that doesn't
  produce a fresh `SIGNOFF_MERGE` verdict blocks merge. `--no-signoff-check`
  is the explicit escape hatch.

### R6 — Sign-off window shape
The sign-off tmux window holds a single Claude router pane (role
`signoff-claude` in the pane registry). No separate "evidence" shell pane:
the agent reads captures directly (`pm qa captures-path`), writes
`report.html` with the diff inline + evidence rendered, and the dashboard
server (R2) is where any human-facing browsing happens.

## Implicit requirements
* The server binds localhost-only by default; an explicit `--bind` flag is
  required to expose it on a non-loopback interface.
* Each `/` request is independent — no cached state between requests, so a
  new `report.html` shows up on the next page load.
* Captures-root resolution mirrors `captures_dir` so the server serves the
  same per-PR dirs the sign-off agent writes to (`paths.captures_root`).

## Ambiguities (resolved)
* **Who writes `report.html`?** → the sign-off agent, via the prompt
  extension; not a Python renderer (note-537e1a0).
* **How does the dashboard get the verdict?** → from a
  `<meta name="pm-signoff-verdict">` tag the agent embeds in the report's
  `<head>`; no sidecar (commit fca8c07d).
* **Regenerate mechanism?** → plain `pm pr signoff <id>`; safe because manual
  sign-off is recommendation-only (no "write-only" mode).
* **Top-of-page bullets source?** → derived during the same sign-off pass
  from review-loop / QA commits and notes (no new inputs needed —
  note-a8bc547).

## Edge cases
* **PR in `project.yaml` with no report yet** → renders a row with a
  plain "no report yet" cell in the Report column. Stays in the dashboard
  so reviewers see the gap rather than the PR vanishing. The dashboard
  doesn't surface a regenerate command — the reviewer runs
  `pm pr signoff <id>` themselves if they want to produce one.
* **report.html present, no verdict meta tag** → verdict cell shows "verdict
  unknown"; the report link still works.
* **Bug PR missing pre-fix or post-fix capture** → the sign-off agent flags
  the gap in its `report.html` (and #225 hard-bounces a bug PR to impl when
  either is missing — note-22f1fb3).

## Out of scope (owned by dependencies)
* The sign-off step / window / verdict router / lifecycle status / icons
  (pr-2d5f712, merged) — we *consume* its seams, never redefine them.
* Capture GC / snapshotting (future).
* Plan notes data model (pr-ff9b728); we read forward-compatibly.
