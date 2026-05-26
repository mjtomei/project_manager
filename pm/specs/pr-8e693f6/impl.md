# Spec: Sign-off UI — per-PR BDD report + all-PR behavior dashboard

PR: pr-8e693f6 (#226) · Plan: plan-regression
Depends on: pr-2d5f712 (sign-off step / window / `signoff` session type — **MERGED**)
Forward-compatible with: pr-06a96fa (evidence model), pr-ff9b728 (plan notes).

## Architecture (post-clarification — note-537e1a0, note-a8bc547)

The original description read like a deterministic Python renderer for both
surfaces. Two scope-clarification notes mid-loop pinned the actual mechanism:

* **Per-PR `report.html` is AGENT-WRITTEN.** Captures are heterogeneous enough
  that coherent per-behavior framing requires the same semantic pass that
  produces the routing verdict — the sign-off agent itself. So #226's main
  work is **extending pr-2d5f712's sign-off prompt** to require the agent to
  write `$CAP/report.html` + `$CAP/report.json` on every sign-off pass, with
  the BDD section schema + relative-link discipline + top-of-page bullets.
  **No per-PR HTML rendering in code.**
* **The dashboard is the deterministic part.** A single top-level `index.html`
  globs the per-PR `report.json` sidecars and renders the index + filtering +
  badges. It **never interprets captures**; the sidecar is the only contract.
* **Regenerate = plain `pm pr signoff <id>`.** No "write-only" mode. Outside
  auto-sequence, manual sign-off is recommendation-only (the
  manual-never-acts invariant pr-2d5f712 established in note-1a982f3 /
  note-942fa37), so re-running is safe — the agent re-emits the report and
  may adopt an existing fresh verdict per the adoption rule (note-511d725)
  without triggering another action.

## Requirements (grounded)

### R1 — Sign-off prompt extension (the producer)
Extend `pm_core.prompt_gen.generate_signoff_prompt` with a new "Write the
sign-off report (deliverable)" step before the record/route steps. The
extension specifies:

* **Two deliverable files** the agent must write into `$CAP = $(pm qa
  captures-path <id>)`: `report.html` (human-facing BDD report) and
  `report.json` (structured sidecar). Both reference evidence by relative
  path so the page opens over `file://`. Atomic write (temp + rename) so
  readers never see a half-written sidecar.
* **`report.html` structure** (top-down):
  1. **Header** — title, badges (status + `sign_off` icon, merged flag,
     recorded verdict marker via `SIGNOFF_VERDICT_ICONS`, scenario tally),
     one-line Recommendation with the `ready_to_merge` framing
     (sign-off recommends, never merges; the plan watcher decides), link back
     to `../index.html`.
  2. **"What this loop found and decided" — REQUIRED top-of-page summary**
     (note-a8bc547). Two bulleted lists, **one line per item, plain English,
     no internal jargon**, written so a reader **UNFAMILIAR** with the PR's
     description / notes / commits can scan and decide whether to look closer.
     Each bullet links to its commit / scenario / note where applicable.
     * **Bugs fixed by review and QA** — defects the review-loop or QA
       scenarios found and fixed **in this PR's branch during the loop**.
     * **Spec ambiguities resolved** — places where the original scope was
       ambiguous and got pinned down (DECISION / CORRECTION / supersedes /
       "Scope addition" notes; PR-description rewrites mid-loop).
  3. **Per-step sections** (Implementation / Review / QA) — each with explicit
     **acceptance criteria** and the evidence paired with them. Bug PRs render
     Implementation as Before (pre-fix: bug reproduces) / After (post-fix:
     symptom gone), flagging a missing phase. Inline `<video>` / `<img>` /
     `<details><pre>` where possible; link `.html` / large files.
  4. **Context for sign-off** — PR description, PR notes, plan name + notes.
* **`report.json` — strict, frozen schema** (the dashboard's only contract):
  ```
  pr_id, display_id, title, status, merged,
  verdict (SIGNOFF_* | null), next_hop (ready_to_merge|qa|review|impl|blocked),
  tally {PASS, NEEDS_WORK, INPUT_REQUIRED, pending},
  bugs_fixed_in_loop, spec_clarifications,
  generated_at (UTC ISO 8601), report_html ("report.html").
  ```
* **Single sources of truth** — match the TUI tech tree + `pm pr list` by
  using `signoff.SIGNOFF_VERDICT_ICONS` / `SIGNOFF_VERDICT_STYLES` and
  `helpers.PR_STATUS_ICONS` (the `sign_off` icon).
* **Sourcing guidance** — `bugs_fixed_in_loop` from review-loop + QA commits
  since impl and finding notes; `spec_clarifications` from DECISION /
  CORRECTION / supersedes / Scope-addition notes + PR-description rewrites.

### R2 — All-PR dashboard (the only deterministic generator)
`pm_core/behavior_report.py` produces a single top-level
`~/.pm/sessions/<tag>/captures/index.html`:
* One row per PR in `project.yaml`, grouped by plan (plan notes pass-through),
  with client-side filtering by **status** and **merged/unmerged**.
* Each row's columns: PR display id, title, status (status icon + recorded
  sign-off verdict marker for sign_off PRs), QA-verdict tally, **loop badges**
  (🐞 N fixed, ❓ N clarified — from `bugs_fixed_in_loop` /
  `spec_clarifications`), and a Report cell: live link to the agent's
  `report.html` (with the next-hop line) when the sidecar exists, otherwise an
  explicit "no report yet" state + the **regenerate command**:
  `pm pr signoff <pr_id>` (with a copy button).
* The dashboard **never interprets captures** — only `report.json`. A
  garbage / partial sidecar degrades to the empty-state row rather than
  crashing the page.
* Markers reuse `signoff.SIGNOFF_VERDICT_ICONS` /
  `SIGNOFF_VERDICT_STYLES` and `helpers.PR_STATUS_ICONS` so the dashboard
  matches the TUI and `pm pr list` exactly.

### R3 — CLI surface
* **Remove** the retired `pm pr report` command (the per-PR page is
  agent-written; regenerate = `pm pr signoff <id>`).
* **Keep** `pm pr dashboard [--open]` — (re)generates `index.html`.

### R4 — Forward-compat captures
Keep the additive `scenarios/<n>/scenario.json` write in
`qa_loop._persist_scenario_verdicts` so the sign-off agent can synthesize the
per-behavior BDD section without re-parsing `verdict.md`. Old captures still
work (the agent reads whatever's there).

### R5 — Safety / robustness
* Dashboard HTML escapes all dynamic text (`html.escape`); the sign-off agent
  is instructed to do likewise in its own `report.html`.
* Missing/garbage sidecar → dashboard row renders the empty state with a
  regenerate command; never crashes the index.
* Sidecar parsing tolerates extra keys + missing optional keys (`tally` /
  counts default to 0 / empty).

## Implicit requirements
* The dashboard opens with no web server and no network.
* Generation is idempotent (re-running overwrites `index.html`).
* Captures-root resolution mirrors `captures_dir` so the dashboard finds the
  same per-PR dirs the sign-off agent writes to (`paths.captures_root`).

## Ambiguities (resolved)
* **Who writes `report.html`?** → the sign-off agent, via the prompt
  extension; not a Python renderer (note-537e1a0).
* **Sidecar location / shape?** → `<pr_id>/report.json` next to the
  agent's `report.html`; strict schema documented in the prompt + dashboard
  module docstring.
* **Regenerate mechanism?** → plain `pm pr signoff <id>`; safe because manual
  sign-off is recommendation-only (no "write-only" mode).
* **Top-of-page bullets source?** → derived during the same sign-off pass
  from review-loop / QA commits and notes (no new inputs needed —
  note-a8bc547).

## Edge cases
* **PR in `project.yaml` with no sidecar yet** → renders the empty-state row
  with the `pm pr signoff <id>` regenerate command. Stays in the dashboard so
  reviewers see the gap rather than the PR vanishing.
* **Sidecar present, captures absent** → the dashboard still links to the
  agent's `report.html`; the agent owns the inline-evidence story.
* **Bug PR missing pre-fix or post-fix capture** → the sign-off agent flags
  the gap in its `report.html` (and #225 hard-bounces a bug PR to impl when
  either is missing — note-22f1fb3).
* **Partial sidecar** (only the required-key subset) → counts default to 0,
  the row still renders.

## Out of scope (owned by dependencies)
* The sign-off step / window / verdict router / lifecycle status / icons
  (pr-2d5f712, merged) — we *consume* its seams, never redefine them.
* Capture GC / snapshotting (future).
* Plan notes data model (pr-ff9b728); we read forward-compatibly.
