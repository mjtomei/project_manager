# QA Spec: pr-8e693f6 — Sign-off UI (per-PR BDD report + all-PR dashboard)

## Scope under test (user-visible surfaces this PR owns)

1. `pm pr dashboard [--open]` — generates an HTML `index.html` at the captures
   root listing every PR grouped by plan, with status icons / sign-off verdict
   markers / QA-tally badges / loop-discovery badges, and client-side filtering
   by status and merged/unmerged.
2. The dashboard's empty-state behavior for PRs that have no agent-written
   `report.json` sidecar yet (renders "no report yet" + a copyable
   `pm pr signoff <id>` regenerate command).
3. The dashboard's link-out to the agent's per-PR `report.html` when a sidecar
   is present.
4. The sign-off prompt extension (the prompt that `pm pr signoff` shows the
   agent) — its content tells the agent to produce `report.html` and
   `report.json` deliverables in `$CAP`.
5. The TUI tech tree + `pm status` recognizing the `sign_off` status and its
   verdict markers.
6. Forward-compatibility plumbing: `qa_loop` now writes
   `scenarios/<n>/scenario.json` alongside `verdict.md`.

Out of scope (owned upstream by pr-2d5f712, already merged in): the actual
sign-off window, the verdict router, the agent writing the report.

## Requirements (Given / When / Then)

### R1 — Generate the dashboard from scratch
* GIVEN a fresh pm project with a few PRs in mixed states (some in
  `in_progress`, some `sign_off`, some `merged`) and NO `report.json` sidecars
  anywhere yet.
* WHEN the user runs `pm pr dashboard --open`.
* THEN the command prints a path under `~/.pm/sessions/<tag>/captures/index.html`,
  the file exists, and (when xdg-open is available) the file opens in a browser.
  The page shows every PR from `project.yaml` grouped under its plan heading,
  each row showing the status icon used by `pm pr list`, an explicit "no report
  yet" cell, and a copyable `pm pr signoff <pr_id>` command.

### R2 — Dashboard surfaces an agent-written sidecar
* GIVEN a PR whose captures dir already contains a well-formed
  `report.json` (verdict `SIGNOFF_MERGE`, non-zero tally, a non-zero
  `bugs_fixed_in_loop`) and a co-located `report.html`.
* WHEN the user runs `pm pr dashboard` and opens the resulting `index.html`
  in a browser.
* THEN the PR's row shows the sign-off verdict marker (icon + label matching
  the TUI / `pm pr list`), the QA tally as colored badges, a 🐞 loop badge with
  the fixed count, and an "open report" link. Clicking the link loads the
  agent's `report.html` over `file://` without a server.

### R3 — Filter by status and merged/unmerged
* GIVEN the dashboard rendered with a mix of statuses (at least one
  `in_progress`, one `sign_off`, one `merged`).
* WHEN the user selects "merged" in the merged filter and then "sign_off" in
  the status filter.
* THEN only rows matching the selected combination remain visible (rows for
  other statuses / merged states are hidden). Resetting both filters to "all"
  restores every row.

### R4 — Regenerate via `pm pr signoff`
* GIVEN the dashboard shows a PR with no sidecar yet (empty-state row with the
  copyable `pm pr signoff <id>` command).
* WHEN the user actually runs that command (driven against a fake-Claude
  sign-off session so the agent's deliverables are simulated by writing a
  `report.json` + `report.html` under `$CAP`) and re-runs `pm pr dashboard`.
* THEN the row flips from the empty state to a populated row with an open-report
  link (re-running is idempotent — `index.html` is overwritten cleanly).

### R5 — Sign-off prompt instructs the agent
* GIVEN a PR currently in `qa` status with workdir present.
* WHEN the user runs `pm pr signoff <pr_id>` and inspects the prompt the agent
  receives.
* THEN the prompt contains the "Write the sign-off report (deliverable)"
  section that names both `report.html` and `report.json`, the frozen
  `report.json` schema fields (`pr_id`, `display_id`, `tally`,
  `bugs_fixed_in_loop`, `spec_clarifications`, `report_html`), the
  `What this loop found and decided` top-of-page section, and the
  `pm pr signoff-record <pr_id> <VERDICT>` recording instruction.

### R6 — TUI / `pm status` show the new `sign_off` status
* GIVEN a project with a PR transitioned to `sign_off` (e.g. by running
  `pm pr signoff <id>` against a `qa` PR).
* WHEN the user runs `pm status` and opens the TUI.
* THEN `pm status` lists the `sign_off` count with its icon, and the TUI tech
  tree renders the PR with the `sign_off` icon and (once a verdict is
  recorded) the sign-off verdict marker, matching the dashboard's marker.

### R7 — qa_loop persists `scenario.json` alongside `verdict.md`
* GIVEN a PR run through a QA loop (driven by fake-Claude) producing at least
  one scenario verdict.
* WHEN QA completes and the captures dir is inspected.
* THEN each scenario's capture dir contains both `verdict.md` and a new
  `scenario.json` carrying `index / title / focus / steps / verdict / reason`.

## Edge Cases

### E1 — Garbage / partial sidecar does not crash the page
* GIVEN a PR whose `report.json` is unparseable JSON, and another PR whose
  `report.json` contains only the `pr_id` and `title` fields (no tally /
  counts).
* WHEN the user runs `pm pr dashboard`.
* THEN the unparseable one degrades to the empty-state row (no crash, no
  broken HTML), and the partial one renders with zero-tally badges and zero
  loop badges (defaults). The rest of the dashboard renders normally.

### E2 — Dynamic text is HTML-escaped
* GIVEN a PR with a title containing `<script>alert(1)</script>` and a plan
  whose notes contain HTML-active characters.
* WHEN the user opens the generated dashboard in a browser.
* THEN the title and notes appear as literal text (no script execution, no
  layout breakage), and viewing source shows the angle brackets escaped.

### E3 — Dashboard groups by plan, including "Unplanned"
* GIVEN multiple plans plus at least one PR that has no `plan` set.
* WHEN the user generates the dashboard.
* THEN each plan's PRs appear under its plan heading (in the plan order
  defined by `project.yaml`), and PRs without a plan appear under an
  "Unplanned" heading at the end.

### E4 — Concurrent dashboard generation does not corrupt the index
* GIVEN a project with several PRs.
* WHEN two `pm pr dashboard` invocations run at roughly the same time (e.g.
  from different shells) against the same captures root.
* THEN both commands succeed, the final `index.html` is well-formed (parses
  as a complete HTML document and contains rows for every PR), and there is
  no half-written / truncated file left behind.

### E5 — No session tag / outside a pm session
* GIVEN a shell that is not inside a pm tmux session and a cwd that yields no
  derivable session tag.
* WHEN the user runs `pm pr dashboard`.
* THEN the command exits non-zero and prints a clear message that the
  captures root could not be resolved (rather than writing the file to an
  unexpected location or silently doing nothing).

## Pass/Fail Criteria
* Dashboard pages render without browser errors and the visible rows /
  badges / filters match the project state. Links to per-PR reports open
  over `file://`.
* No dashboard scenario produces a crash, traceback, or unescaped HTML.
* `pm status` and the TUI both expose the `sign_off` status without
  regressing the other statuses.
* The sign-off prompt explicitly names the two deliverable files and the
  sidecar schema fields.

## Ambiguities (resolved)
* "Open report" link target — resolved as the agent-written `report.html`
  co-located with the sidecar (`<pr_id>/report.html` relative to the
  dashboard). No deterministic per-PR renderer (note-a8bc547).
* Regenerate flow — resolved as plain `pm pr signoff <id>` (manual sign-off
  is recommendation-only). No special "write-only" mode.
