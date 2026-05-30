# Spec: Sign-off UI — per-PR BDD report + all-PR behavior dashboard

PR: pr-8e693f6 (#226) · Plan: plan-regression
Depends on: pr-2d5f712 (sign-off step / window / `signoff` session type — **MERGED**)
Forward-compatible with: pr-06a96fa (evidence model), pr-ff9b728 (plan notes).

## Architecture (post-clarification — note-537e1a0, note-a8bc547; sidecar dropped 2026-05-30)

The original description read like a deterministic Python renderer for both
surfaces. Two scope-clarification notes mid-loop pinned the actual mechanism,
and a later refactor (commit fca8c07d) dropped the JSON sidecar entirely:

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
* **The dashboard is the deterministic part.** A single top-level `index.html`
  at the captures root lists one row per PR (pm id, GitHub #, title, verdict,
  link to `report.html`). It **never interprets captures** beyond reading the
  one verdict meta tag from each `report.html`. PR runtime state (title) is
  read fresh from `project.yaml` at generation time so it can't go stale.
* **Regenerate = plain `pm pr signoff <id>`.** No "write-only" mode. Outside
  auto-sequence, manual sign-off is recommendation-only (the
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
  3. **"What this loop found and decided" — top-of-page summary**
     (note-a8bc547). Bulleted entry points, **one line per item, plain
     English, no internal jargon**, written so a reader **UNFAMILIAR** with
     the PR's description / notes / commits can scan and decide whether to
     look closer. Each bullet links to its commit / scenario / note. Groups:
     * **Bugs found and fixed by review/QA during the loop** — with which
       area of code/behaviour the bug hid in.
     * **Spec ambiguities** — resolved (question / answer / who decided) and
       *unresolved* (flagged for the reviewer).
     * **Open questions / project-level implications** — follow-up PRs,
       decisions that constrain future plan items.
  4. **Per-step sections** (Implementation / Review / QA) — each with explicit
     **acceptance criteria** and the evidence paired with them. Bug PRs render
     Implementation as Before (pre-fix: bug reproduces) / After (post-fix:
     symptom gone), flagging a missing phase.
  5. **Code change (the diff)** — there is no web UI for the diff elsewhere,
     so the report carries it: a per-file inline TOC, then one collapsed
     `<details>` per file with HTML-escaped `<pre><code class="diff">` output.
  6. **Context for sign-off** — PR description, PR notes, plan name + notes.
* **Two reading depths in one page** — top-line content (header,
  recommendation, summary, per-step conclusions) is enough to trust the
  verdict; full depth (diff, scenario evidence, captures) is folded behind
  `<details>` collapsed by default for the auditing reviewer.
* **Evidence rendering** — embed-first, single positive default: `<video>`
  for `.webm`, `<img>` for images, `<audio>` for audio, asciinema-player for
  `.cast`, `<details><pre>` for small text/log; for `.md`, run
  `pm md-render <path>` and embed the body-only fragment inline; link as-is
  for `.html` and large binaries.
* **Single sources of truth** — match the TUI tech tree + `pm pr list` by
  pointing the agent at `signoff.SIGNOFF_VERDICT_ICONS` /
  `SIGNOFF_VERDICT_STYLES`.

### R2 — All-PR dashboard (the only deterministic generator)
`pm_core/behavior_report.py` produces a single top-level
`~/.pm/sessions/<tag>/captures/index.html` — **intentionally minimal**:
* One row per PR in `project.yaml`. Columns: PR id (+ GitHub #), title
  (from `project.yaml`), verdict, Report cell.
* **Verdict** is read at generation time from the `pm-signoff-verdict` meta
  tag in each PR's `$CAP/<pr_id>/report.html` (`_extract_verdict`). When the
  report is missing the row shows a "no report yet" empty state with the
  **regenerate command** `pm pr signoff <pr_id>` (and a copy button); when the
  report exists but carries no meta tag the verdict cell shows "verdict
  unknown".
* The dashboard **never interprets captures** beyond that one meta tag. An
  unreadable / tag-less `report.html` degrades gracefully (empty verdict),
  never crashes the index.
* The verdict marker reuses `signoff.SIGNOFF_VERDICT_ICONS` /
  `SIGNOFF_VERDICT_STYLES` (mapped to CSS via `_RICH_COLOR_CSS`) so the
  dashboard matches the TUI and `pm pr list`.

**Note — scope reduction vs the original description.** The description called
for client-side filtering (by status, by merged/unmerged), plan grouping with
plan-notes pass-through, QA-verdict tallies, and loop badges. The 2026-05-30
refactor (commit fca8c07d) deliberately removed all of these along with the
sidecar, leaving the flat 4-column table. This is an intentional
simplification, recorded here so the divergence from the description is
explicit.

### R3 — CLI surface
* **Remove** the retired `pm pr report` / `pm pr signoff-record` commands.
* **Keep** `pm pr dashboard [--open]` — (re)generates `index.html`.
* **Add** `pm md-render <path>` (hidden helper) — body-only HTML for the
  sign-off agent to embed `.md` evidence inline.

### R4 — Forward-compat captures
Keep the additive `scenarios/<n>/scenario.json` write in
`qa_loop._persist_scenario_verdicts` so the sign-off agent can synthesize the
per-behavior BDD section without re-parsing `verdict.md`. Old captures still
work (the agent reads whatever's there).

### R5 — Safety / robustness
* Dashboard HTML escapes all dynamic text (`html.escape`); the sign-off agent
  is instructed to do likewise in its own `report.html`.
* Missing report.html → dashboard row renders the empty state with a
  regenerate command; never crashes the index.
* `_extract_verdict` only scans the `<head>` region (so a verbatim verdict
  keyword in `<body>` text isn't a false match) and parses the meta tag's
  `name` / `content` attributes independently of their order.

## Implicit requirements
* The dashboard opens with no web server and no network.
* Generation is idempotent (re-running overwrites `index.html`).
* Captures-root resolution mirrors `captures_dir` so the dashboard finds the
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
* **PR in `project.yaml` with no report yet** → renders the empty-state row
  with the `pm pr signoff <id>` regenerate command. Stays in the dashboard so
  reviewers see the gap rather than the PR vanishing.
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
