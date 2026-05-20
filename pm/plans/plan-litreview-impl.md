# Plan: Implement the Walker UI for the Augmented Adversarial-Review Cycle

Implementation plan for `plan-litreview-ui.md`. The augmented cycle (`pm/docs/adversarial-review/METHODOLOGY.md` § The augmented cycle) runs in a Claude session via its normal tool use; the Python side is the walker UI, the CLI commands to launch sessions, and the markdown format primitives.

## What this implements

- **CLI: `pm review session <target>`** — launches a Claude session in a new tmux pane with the augmented-cycle methodology context (`METHODOLOGY.md` + `CITATION_USE_AUDIT.md` + `CITATION_CRAWL.md` + skepticism rules) and a target artifact. Target is any file or topic string; the session runs the review / audit-loop / response cycle using its normal `Bash` / `Edit` / `Write` / `Agent` tool use.
- **CLI: `pm plan session <plan>`** — launches a discussion session in a new pane within a plan's tmux window. Independent of the review-cycle work; for the conversational mode of working on a plan. Plans pane in the TUI gets a keybinding for the same command.
- **CLI: `pm review ui [--port]`** — launches the walker server.
- **Walker UI** — proposed-changes walker + citation-audit browse + dashboard + general-comments surface (per `plan-litreview-ui.md`).
- **Markdown format primitives** — response-block parser/writer, interaction-log appender, audit-doc parser, response-doc parser with provenance tags.

The Claude session is the runner. No Python runner, no auto-loop driver — auto-run is the human telling the session "run the cycle until convergence."

## Architecture

```
pm/
  review/
    __init__.py
    md_parser.py       # response-block + interaction-log + audit-doc + response-doc parsers
    md_writer.py       # response-block writes, interaction-log appends
    cli.py             # pm review {session, ui}
    context.py         # methodology-context loader (METHODOLOGY + CITATION_USE_AUDIT + CITATION_CRAWL + skepticism)
    ui/
      server.py        # FastAPI single-file server
      templates/       # Jinja2 walker templates (changes, audit_browse, dashboard, notes_pane)
      static/          # one CSS file, one JS file
  cli/
    plan.py            # pm plan session
  tui/
    plans_pane.py      # keybinding for plan-session launch (existing file)
```

State is purely file-backed. Markdown files under `pm/docs/adversarial-review/` are canonical; no JSON cache, no database.

## PRs

### PR 1: `pm plan session <plan>` + TUI keybinding

Smallest, independent. Lets you open a discussion session in a plan's window from CLI or the plans pane.

- `pm/cli/plan.py` — `pm plan session <plan>` subcommand. Resolves the plan's tmux window via existing pane-management code; opens a new pane running `claude`. Role: `plan-session`.
- `pm/tui/plans_pane.py` — keybinding (default `s`) invokes the same command for the selected plan.
- Tests: pane created with the right role; keybinding routes correctly.

Dependencies: none. Independent of the review work.

### PR 2: `pm review session <target>` + methodology context loader

Launches a session with the augmented-cycle context loaded.

- `pm/review/context.py` — concatenates `METHODOLOGY.md`, `CITATION_USE_AUDIT.md`, `CITATION_CRAWL.md`, and a target preamble. The framing instruction: "you are running the augmented adversarial-review cycle on the target below; produce REVIEW_CYCLE_N.md, then the audit loop, then REVIEW_RESPONSE_CYCLE_N.md, per the methodology files."
- `pm/review/cli.py` — `pm review session <target>` subcommand. Opens a new tmux pane running `claude` with the context as initial input. Target accepts file paths or topic strings.
- Artifact-id derivation: file basename for file targets; slugified prefix for string topics.
- Tests: context-build produces a valid prompt; file vs string target handled; pane launched in role `review`.

Dependencies: none.

### PR 3: Markdown format primitives

The data layer the UI builds on.

- `md_parser.py` — response-block parser (fenced HTML comment with `proposed-change` header, structured fields), interaction-log parser, audit-doc parser (per-citation entries with `surfaced-citations:` lists), response-doc parser (proposed changes with `provenance:` tags).
- `md_writer.py` — atomic response-block updates (`update_response_block`), append-only interaction-log entries (`append_interaction`), notes-file appends (`append_note`). All writes through these so format consistency is guaranteed.
- Tests: response-block round-trip; interaction-log append concurrency; audit-doc parsing on the four existing `CITATION_AUDIT_*.md` files; response-doc parsing with mixed-provenance changes.

Dependencies: none. Ships independently.

### PR 4: Web server skeleton + dashboard + proposed-changes walker

- `pm/review/ui/server.py` — FastAPI single-file. File-discovery routes (artifacts, per-cycle docs), dashboard route, proposed-changes walker route.
- `templates/dashboard.html` — per-cycle status, mode tag, audit-loop convergence indicator, engagement signals.
- `templates/changes.html` — paginated proposed-changes walker per `plan-litreview-ui.md`. Filterable by provenance, target section, suggested verdict, status. Per-entry accept/edit/skip actions; page-level bulk-accept-per-filter.
- `static/style.css`, `static/walker.js` — minimal CSS, vanilla JS for hotkeys + bulk-accept + view-time tracking.
- CLI: `pm review ui [--port]`.
- Tests: dashboard renders correctly against a fixture multi-cycle state; proposed-changes walker renders fixture proposed changes and round-trips edits.

Dependencies: PR 3.

### PR 5: Citation-audit browse view + general-comments surface

- `templates/audit_browse.html` — renders `CITATION_AUDIT_CYCLE_N.md` (per-cycle) organized per citation, with click-through to the proposed changes the entry produced.
- `templates/notes_pane.html` — collapsible side panel included in all walker pages. Reads/writes `NOTES_<artifact>.md` with section-tagged entries and timestamps.
- Notes file loadable into the session context so general comments influence next cycle's response.
- Tests: audit-browse renders all four existing `CITATION_AUDIT_*.md` files correctly with no regressions; notes-pane round-trips edits.

Dependencies: PR 4.

### PR 6: Citations status view (cross-cycle citation dashboard)

The cross-cycle citation-centric view per `plan-litreview-ui.md`. One row per citation that has ever been considered for the artifact, derived from the union of all per-cycle audit files plus the artifact's current citation list.

- `templates/citations.html` — sortable + filterable table view. Per-row: title + authors + year, clickable source link (opens in new tab), current tier, current classification, argument (verdict rationale + load-bearing verbatim quote), most-recent-audit cycle, status (`in-artifact` / `proposed-addition` / `proposed-removal` / `superseded`). Click-to-expand for the full audit entry inline.
- `md_parser.derive_citation_status` — cross-file union pass. Walks all `CITATION_AUDIT_CYCLE_*.md` files plus the artifact's citation list; deduplicates by citation identity (arXiv id / DOI / a normalized author+year+title key); returns one record per citation with the most-recent audit's tier + classification + argument + cycle, and the current status in the artifact.
- `md_parser.extract_artifact_citations` — parses the artifact (e.g., a literature review markdown) for inline citations and the bibliography section.
- Filter set: tier, classification, status, cycle audited, has-working-link, *needs-audit* (status `in-artifact` or `proposed-addition` with no audit entry).
- No state file; view is derived per request.
- Tests: deduplication on a fixture with the same citation in two cycles' audit files; correct most-recent selection; "needs-audit" filter surfaces the right set on a fixture artifact.

Dependencies: PR 3, PR 5.

### PR 7: End-to-end smoke validation (auto-runnable target)

Four validation paths, runnable as a long-running auto-run from pm.

1. **Walker rendering smoke.** Run `pm review ui` against the four existing pre-flow `CITATION_AUDIT_*.md` files. Each renders correctly in the citation-audit browse view; no regressions.
2. **Citations-status view smoke.** Same four files plus a fixture artifact citation list. The citations status view derives correctly: deduplicated rows, correct most-recent-audit selection per citation, "needs-audit" filter surfaces the right set, click-through opens links in new tabs.
3. **Proposed-changes round-trip.** Construct a fixture `REVIEW_RESPONSE_CYCLE_N.md` with mixed reviewer-comment and audit-entry proposed changes. The walker renders them, accepts a few, edits a few, skips a few; the written markdown round-trips through the parser correctly.
4. **End-to-end cycle in auto-run mode.** A small fixture artifact (a markdown document with 5–10 citations is sufficient — the smoke isn't validating literature-review quality, just integration). Launch a `pm review session` on it; instruct the session to run the augmented cycle in auto-run mode. Verify:
   - `REVIEW_CYCLE_1.md`, `CITATION_AUDIT_CYCLE_1.md`, `REVIEW_RESPONSE_CYCLE_1.md` all appear with the right format.
   - The audit loop converges (last round surfaces zero new citations).
   - The response file's proposed changes have `status: auto-accepted` and matching interaction-log entries.
   - The dashboard shows cycle 1 complete with mode `auto-run`.
   - All walker views (proposed-changes, audit-browse, citations-status, dashboard) render every produced file without errors.

Idempotent and re-runnable: re-running validates that the existing artifact state still parses and renders correctly after any incremental changes.

Acceptance criteria: all four paths pass; no regressions on the four existing pre-flow audit docs; smoke-test cycle completes within reasonable wall-clock.

Dependencies: PR 1–6.

## Sequencing

PR 1 + PR 2 + PR 3 are independent and can land in any order. PR 4 needs PR 3. PR 5 needs PR 4. PR 6 needs PR 5 (citations-status view shares the cross-file derivation work with the audit browse). PR 7 needs everything.

A reasonable serial path: 1 → 2 → 3 → 4 → 5 → 6 → 7.

A parallel-friendly path: PR 1 + PR 2 + PR 3 in parallel; then PR 4; then PR 5; then PR 6; then PR 7.

## Open questions to validate during PR 3

1. **Response-block placement.** Plan picks inline-on-the-proposed-change in `REVIEW_RESPONSE_CYCLE_N.md`. Alternative: a sibling `*.decisions.md` file (keeps the response file pristine but detaches decisions from their source). Inline preferred — the response file is canonical.
2. **Audit-doc format standardization.** The four existing `CITATION_AUDIT_*.md` files use a similar but not identical format. PR 3's parser should accept both the existing format and the new format-with-`provenance`-tagged proposed-changes; PR 5 may need to render minor variations.
3. **Inbox file format for UI → session messages.** Some walker actions (regenerate suggestion, re-run audit on a specific citation) need to message the session. Plan defers to a later PR; for the initial UI scope, walker decisions just write back to the markdown and the next cycle picks them up.

## Non-goals

- A Python iteration runner. The Claude session runs the cycle via its normal tool use.
- Auto-run as a CLI flag on a Python command. Auto-run is the human telling the session to loop.
- Multi-user collaboration. Single user, local-only.
- Persistent database. Markdown is the database.
- Replacing the four existing pre-flow `CITATION_AUDIT_*.md` audits — they render in the audit-browse view as worked examples of cycle-1-style standalone audits.
