# Spec: Sign-off UI — per-PR BDD report + all-PR behavior dashboard (HTML)

PR: pr-8e693f6 · Plan: plan-regression
Depends on: pr-2d5f712 (sign-off step/window/status — **NOT yet merged**),
pr-06a96fa (evidence model — **NOT yet merged**, forward-compatible).

## Context discovered in the codebase

- **`sign_off` status and the sign-off step do not exist yet.** `VALID_PR_STATES`
  (`pm_core/pr_utils.py:7`) is `{pending, in_progress, in_review, qa, merged,
  closed}`. No sign-off window, no verdict router, no `signoff`/`checkoff` code
  anywhere. pr-2d5f712 adds all of that. **Consequence:** this PR ships the
  report/dashboard *generator* as a standalone, forward-compatible component
  (a module + CLI), so pr-2d5f712 can call it "at sign-off time" once it lands,
  and a human can run it today.
- **Captures layout** (`pm_core/paths.py:69` `captures_dir`):
  `~/.pm/sessions/<tag>/captures/<pr_id>/` with `scenarios/<n>/` per scenario.
  `_persist_scenario_verdicts` (`qa_loop.py:1417`) writes
  `scenarios/<n>/verdict.md` = `# Scenario <n>: <title>\n\n<verdict>\n\n<reason>`.
  Bug-fix flows write `impl/` (pre-fix/post-fix); scenario artifact recipes write
  evidence subdirs under `scenarios/<n>/` with `.webm/.png/.html/.txt/.json`.
  qa_status.json lives in the **ephemeral** workdir
  (`~/.pm/workdirs/qa/<pr>-<loop>/qa_status.json`), not in captures — so it is
  NOT a durable regeneration source.
- **`QAScenario`** (`qa_loop.py:125`) carries `index, title, focus, steps`
  (steps is free-form GIVEN/WHEN/THEN text, not parsed into fields).
- **PR fields** (`cli/helpers.py` `_make_pr_entry`): `id, title, description,
  branch, status, plan, depends_on, gh_pr, gh_pr_number, created_at, updated_at,
  started_at, reviewed_at, merged_at, notes[]`. Notes are
  `{id, text, created_at, last_edited}`. Display id = `#<gh_pr_number>` else
  `pr-NNN` (`_pr_display_id`).
- **Plans** (`store.py:218` `make_plan_entry`): `id, name, file, status, parent`.
  **No `notes` field yet** — plan notes land with pr-ff9b728. Read defensively.
- **`cleanup_pr_resources`** (`pr_cleanup.py`) never touches captures → co-located
  reports are safe for v1 (matches the PR premise).
- No existing HTML generation, no jinja. We generate HTML with the stdlib only
  (`html.escape`), matching the project's no-extra-deps style.

## Requirements (grounded)

### R1 — Per-PR BDD report generator
A new module `pm_core/behavior_report.py` produces a self-contained
`report.html` written **into the captures dir**:
`~/.pm/sessions/<tag>/captures/<pr_id>/report.html`. Evidence is referenced by
**relative path** (no copy), so the file opens over `file://`.

Contents, BDD-shaped:
- **Top-of-page status summary**: PR display id + title + status; behavior verdict
  tally (PASS / NEEDS_WORK / INPUT_REQUIRED / pending counts); an overall
  **recommendation / next hop**.
- **Per behavior** (= per scenario): title + focus; the **flow** (STEPS rendered
  as Given/When/Then when parseable, else verbatim); **verdict + reason**;
  **evidence** inline (`.webm`→`<video controls>`, images→`<img>`, small
  text/json inlined in `<details>`, `.html` and large files→links), each relative
  to the report.
- **Implementation evidence** section: walk `impl/` (bug-fix pre-fix/post-fix)
  and render its evidence generically.
- **Reachable context** (so a reviewer signs off without leaving the page):
  PR **description**, PR **notes**, and the **plan** name + **plan notes**
  (plan notes read defensively; omitted cleanly when absent today).
- A link back to the dashboard (`../index.html`).

### R2 — Recommendation / next hop (forward-compatible with the verdict router)
pr-2d5f712 owns the real verdict router. Until it lands, the generator:
- reads an optional `signoff.json` in the captures dir root
  (`captures/<pr_id>/signoff.json`) — the seam pr-2d5f712 can populate with
  `{verdict, recommendation, next_hop, summary}` — and renders it when present;
- otherwise **derives** a heuristic recommendation from the scenario verdicts
  (all PASS → "Ready for sign-off / merge"; any INPUT_REQUIRED → "Input
  required before sign-off"; any NEEDS_WORK → "Needs work — bounce back"; no
  behaviors → "No recorded behaviors yet"), clearly labelled as derived.

### R3 — Durable regeneration source
Extend `_persist_scenario_verdicts` (`qa_loop.py`) to additionally write
`scenarios/<n>/scenario.json` = `{index, title, focus, steps, verdict, reason}`
so the per-PR report can be **rebuilt from retained captures alone** (the
DETECT-MISSING / REGENERATE requirement) after the workdir is gone. The report
reader prefers `scenario.json`, falls back to parsing `verdict.md` (steps then
shown as "not recorded"). Additive; old captures still render.

### R4 — All-PR dashboard
`pm_core/behavior_report.py` also produces a single top-level
`~/.pm/sessions/<tag>/captures/index.html`:
- Lists **every PR** in project.yaml, grouped **by plan** (plan name + plan
  notes header per group; unplanned PRs in their own group), each row showing
  display id, title, status, and a **one-line behavior/status summary** (verdict
  tally / recommendation), linking to `<pr_id>/report.html`.
- **Client-side filtering** (pure JS, no server): by **merged/unmerged**
  (`merged_at` presence) and by **status**. Rows carry `data-status` /
  `data-merged` attributes; filter controls toggle row visibility.
- **DETECT-MISSING**: when `<pr_id>/report.html` is absent, the row shows a
  "No report" state instead of a dead link, with a **REGENERATE** control that
  surfaces the exact command `pm pr report <pr_id>` (copy-to-clipboard). Static
  export can't execute server-side, so "regenerate on demand" = surface the
  one command the reviewer runs, then refresh — consistent with the v1 lean.

### R5 — CLI surface (and programmatic API)
Add to the `pr` group (`cli/pr.py`):
- `pm pr report PR_ID [--open]` — generate that PR's `report.html` (+ refresh the
  dashboard), print the path, optionally open in a browser.
- `pm pr report --all [--open]` — generate every PR's report + the dashboard.
- `pm pr dashboard [--open]` — (re)generate just the dashboard index.

Programmatic API (what pr-2d5f712 calls at sign-off time):
- `generate_pr_report(root, pr_id, *, session_tag=None) -> Path | None`
- `generate_dashboard(root, *, session_tag=None) -> Path | None`

Add `captures_root(session_tag=None) -> Path | None` to `paths.py` (the
`captures/` dir that holds every per-PR dir + `index.html`), mirroring
`captures_dir`'s tag resolution.

### R7 — Step-evidence against acceptance criteria; bug before/after (note-e1ff391)
Added mid-implementation by the orchestrator (not in the original description):
the report must present **each step's evidence against that step's acceptance
criteria**, not just final-QA scenarios — and **bug PRs** must surface the
**pre-fix capture (bug reproduced)** and **post-fix capture (bug gone)** so the
before/after is visible. Coordinated with the sign-off step (#225 / pr-2d5f712).

- **Bug detection** reuses the single source of truth
  `bug_fix_prompts._is_bug_pr(pr)` (`plan == "bugs"` or `type == "bug"`).
- **Implementation step** renders as a first-class step. For bug PRs (or whenever
  `impl/pre-fix/` or `impl/post-fix/` captures exist) it shows a two-column
  **before/after**: *Before — pre-fix* (acceptance: "the bug reproduces") and
  *After — post-fix* (acceptance: "the symptom no longer reproduces"), each paired
  with its captures. A missing phase is flagged ("No pre/post-fix capture
  recorded — the before/after is incomplete") instead of silently dropped. Phase
  is detected from a `pre-fix`/`post-fix` directory component (the layout
  `bug_fix_prompts.py` writes under `$CAP/impl/`), tolerating `pre_fix` spelling
  and ignoring filenames. Non-bug PRs keep a flat implementation-evidence block.
- **QA behaviors** now render explicit **Acceptance criteria** (the THEN clauses,
  incl. trailing AND/BUT and sub-bullets, parsed from the scenario steps) above
  the evidence, making the criteria→evidence pairing explicit. A bug-fix scenario
  that captured `pre-fix`/`post-fix` evidence is also shown before/after.
- **Coordination with #225**: pr-2d5f712's sign-off window deliberately keeps its
  second pane a plain evidence-summary shell and links to *this* report as the
  rich surface; its router reads the same `impl/` (bug "primary evidence") +
  `scenarios/<n>/` captures. Our report organizes exactly those into the
  step→acceptance→evidence shape the router/human reviews against.

### R6 — Safety / robustness
- All user/derived text (titles, descriptions, notes, reasons, steps, file
  names) is `html.escape`d. No untrusted HTML injected.
- Missing captures dir, empty scenarios, unreadable files → graceful (section
  omitted or "none recorded"), never a crash.
- Evidence links use POSIX relative paths from the report's directory; binary
  evidence is never read into memory (only linked / `<video>`/`<img>` src).

## Implicit requirements
- The report must open with no web server and no network (inline CSS/JS, no CDN).
- Generation is idempotent — re-running overwrites `report.html` / `index.html`.
- The dashboard's per-PR captures path resolution must match `captures_dir`
  (same session tag) so links resolve.
- Generating one report should refresh the dashboard so the "missing" state
  flips to a live link without a separate command.

## Ambiguities (resolved)
- **Dashboard location** → `captures/index.html` (captures root), so relative
  links to `<pr_id>/report.html` and back (`../index.html`) work over file://.
- **"Regenerate on demand" in a static page** → surface + copy the
  `pm pr report <pr_id>` command (no server to call). Documented as the v1 lean.
- **Steps not in durable captures** → R3 writes `scenario.json`; reader falls
  back to verdict.md.
- **Recommendation before the verdict router exists** → R2: read optional
  `signoff.json`, else derive heuristically, labelled as derived.
- **Which PRs on the dashboard** → all PRs in project.yaml (grouped by plan).
  Pending PRs with no captures simply show the missing-report state.
- **Inlining .html evidence** → link (open in new tab), not iframe — simpler and
  avoids file:// iframe quirks.

## Edge cases
- PR with no captures dir → report still generated from project.yaml metadata
  (description/notes), behaviors section says "No recorded behaviors yet".
- Old captures with only `verdict.md` (no `scenario.json`) → parsed; steps shown
  as "not recorded".
- Evidence file whose name collides with relative traversal → escaped + path is
  built with `os.path.relpath`/`Path`, never from untrusted absolute input.
- `gh_pr_number` present → display id `#N`; report filename stays `report.html`
  keyed by canonical `pr_id` dir.
- Plan notes present in a future shape (list of dicts or string) → reader handles
  both; absent → section omitted.

## Out of scope (owned by dependencies)
- The `sign_off` lifecycle status, the sign-off window, the comprehensive verdict
  router, cross-stage aggregation policy (pr-2d5f712). This PR provides the seam
  (`signoff.json`) + the human-facing surface only.
- Capture GC / snapshotting (future phase). Co-location is safe today.
- Plan notes data model (pr-ff9b728); we only *read* it forward-compatibly.
