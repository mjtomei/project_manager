# Plan: Implement the Walker UI for the Augmented Adversarial-Review Cycle

Implementation plan for `plan-litreview-ui.md`. The augmented cycle (`pm/docs/adversarial-review/METHODOLOGY.md` § The augmented cycle) runs in a Claude session via its normal tool use; the Python side is the walker UI, the CLI commands to launch sessions, and the markdown format primitives.

## What this implements

- **CLI: `pm review <target>`** — launches a Claude session in a new tmux pane with the augmented-cycle methodology context (`METHODOLOGY.md` + `CITATION_USE_AUDIT.md` + `CITATION_CRAWL.md` + skepticism rules) and a target artifact. Target is any file or topic string; the session runs the review / audit-loop / response cycle using its normal `Bash` / `Edit` / `Write` / `Agent` tool use.
- **CLI: `pm plan session <plan>`** — launches a discussion session in a new pane within a plan's tmux window. Independent of the review-cycle work; for the conversational mode of working on a plan. Plans pane in the TUI gets a keybinding for the same command.
- **`pm review ui [--port]`** — launches the walker server (PR 3).
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
    cli.py             # pm review <target> | pm review ui
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

### PR 1: Session-launching CLI commands — `pm plan session` + `pm review <target>`

Two CLI commands that launch Claude sessions in new tmux panes. Share the pane-management code so they land together.

- `pm/cli/plan.py` — `pm plan session <plan>` subcommand. Resolves the plan's tmux window via existing pane-management code; opens a new pane running `claude`. Role: `plan-session`. For the conversational mode of working on a plan, independent of any review work.
- `pm/tui/plans_pane.py` — TUI keybinding (default `s`) on the plans pane invokes `pm plan session` for the selected plan.
- `pm/review/context.py` — methodology-context loader. Concatenates `METHODOLOGY.md`, `CITATION_USE_AUDIT.md`, `CITATION_CRAWL.md`, and a target preamble. The framing instruction: "you are running the augmented adversarial-review cycle on the target below; produce REVIEW_CYCLE_N.md, then the audit loop, then REVIEW_RESPONSE_CYCLE_N.md, per the methodology files."
- `pm/review/cli.py` — `pm review <target>` subcommand. Opens a new tmux pane running `claude` with the methodology context as initial input. Target accepts file paths or topic strings. The `ui` subcommand (`pm review ui`, PR 3) is the only other dispatch under `pm review` — anything else is treated as a target. Role: `review`.
- Artifact-id derivation (for `pm review`): file basename for file targets; slugified prefix for string topics.
- Tests:
  - `pm plan session`: pane created with the right role; plans-pane keybinding routes correctly.
  - `pm review <target>`: context-build produces a valid prompt; file vs string target handled; pane launched in role `review`; `ui` argument routes to the server rather than being treated as a target named "ui".

Dependencies: none. Independent of the UI work.

### PR 2: Markdown format primitives

The data layer the UI builds on.

- `md_parser.py` — response-block parser (fenced HTML comment with `proposed-change` header, structured fields), interaction-log parser, audit-doc parser (per-citation entries in the canonical format with `surfaced-citations:` lists), response-doc parser (proposed changes with `provenance:` tags), state-file parser (`STATE_<artifact>.md` — current cycle + phase), focus-file parser (`UI_FOCUS_<artifact>.md` — view + cycle + target + timestamp).
- `md_writer.py` — atomic response-block updates (`update_response_block`), append-only interaction-log entries (`append_interaction`), notes-file appends (`append_note`), state-file write (`update_state` for the session to call at phase transitions), focus-file write (`update_focus` for the session to call when directing UI attention).
- Tests: response-block round-trip; interaction-log append concurrency; canonical-format audit-doc parsing; response-doc parsing with mixed-provenance changes; state-file phase transitions; focus-file timestamp ordering.

Dependencies: none. Ships independently.

### PR 3: Web server skeleton + dashboard + proposed-changes walker + lock states + cycle navigation + SSE pushes + Apply button

- `pm/review/ui/server.py` — FastAPI single-file. File-discovery routes (artifacts, per-cycle docs), dashboard route, proposed-changes walker route. Watches `STATE_<artifact>.md`, `UI_FOCUS_<artifact>.md`, and the current cycle's `REVIEW_RESPONSE_CYCLE_N.md` via `watchdog` (filesystem inotify) per artifact. Exposes a single `/events?artifact=<id>` SSE endpoint that pushes events when any watched file changes.
- `templates/dashboard.html` — per-cycle status, mode tag, audit-loop convergence indicator, engagement signals, **cycle selector** (dropdown, latest first; defaults to current cycle).
- `templates/changes.html` — paginated proposed-changes walker per `plan-litreview-ui.md`. Filterable by provenance, target section, suggested verdict, status. Per-entry accept/edit/skip actions; page-level bulk-accept-per-filter.
- **Apply button.** Visible only when `STATE_<artifact>.md`'s `current-phase` is `awaiting-human-review` and the rendered cycle is the current cycle. Clicking it writes `STATE_<artifact>.md`, transitioning the phase to `applying` (using `md_writer.update_state`). The session — watching the same file — sees the transition and proceeds with the apply step. This is the entire UI → session communication channel.
- **Lock-state enforcement.** Walker editable controls (accept / edit / bulk-accept / skip / reopen / Apply) are enabled only when `current-phase` is `awaiting-human-review` *and* the rendered cycle is the current cycle. In every other state the controls render as read-only badges. The breadcrumb on every walker page shows cycle number + phase + editable/read-only.
- **Cycle navigation.** The cycle selector on the dashboard, and the breadcrumb on every walker page, lets the user jump between cycles. Prior cycles are always read-only regardless of state.
- **SSE-pushed updates.** Client-side JS uses `EventSource('/events?artifact=...')` to subscribe. When the server's `watchdog` observer detects a change to `STATE_<artifact>.md`, `UI_FOCUS_<artifact>.md`, or the current `REVIEW_RESPONSE_CYCLE_N.md`, the server pushes an event to all connected clients. On a STATE event the walker locks/unlocks controls; on a FOCUS event the walker navigates to the indicated view + cycle + target; on a RESPONSE event the walker re-fetches and re-renders entries.
- `static/style.css`, `static/walker.js` — minimal CSS, vanilla JS for hotkeys + bulk-accept + view-time tracking + SSE event handling + lock-state UI states (badges vs editable controls).
- Dependency: `watchdog` (Python lib, wraps inotify on Linux).
- CLI: `pm review ui [--port]`.
- Tests: dashboard renders correctly against a fixture multi-cycle state; proposed-changes walker renders fixture proposed changes and round-trips edits when state is `awaiting-human-review`; walker shows read-only badges (no round-trip) when state is `review` / `audit` / `response` / `applying` / `complete`; Apply button writes the state transition correctly and is hidden outside `awaiting-human-review`; cycle selector navigates between cycles; SSE event for a STATE-file change locks the walker in <200ms; SSE event for a FOCUS-file change navigates within <200ms.

Dependencies: PR 2.

### PR 4: Citation-audit browse view + general-comments surface

- `templates/audit_browse.html` — renders `CITATION_AUDIT_CYCLE_N.md` (per-cycle) in the canonical format, organized per citation, with click-through to the proposed changes the entry produced. The four pre-flow `CITATION_AUDIT_*.md` files are not targeted (no backwards compat — see `plan-litreview-ui.md` § Non-goals).
- `templates/notes_pane.html` — collapsible side panel included in all walker pages. Reads/writes `NOTES_<artifact>.md` with section-tagged entries and timestamps.
- Notes file loadable into the session context so general comments influence next cycle's response.
- Tests: audit-browse renders a fixture `CITATION_AUDIT_CYCLE_N.md` in canonical format correctly; notes-pane round-trips edits.

Dependencies: PR 3.

### PR 5: Citations status view (cross-cycle citation dashboard)

The cross-cycle citation-centric view per `plan-litreview-ui.md`. One row per citation that has ever been considered for the artifact, derived from the union of all per-cycle audit files plus the artifact's current citation list.

- `templates/citations.html` — sortable + filterable table view. Per-row: title + authors + year, clickable source link (opens in new tab), current tier, current classification, argument (verdict rationale + load-bearing verbatim quote), most-recent-audit cycle, status (`in-artifact` / `proposed-addition` / `proposed-removal` / `superseded`). Click-to-expand for the full audit entry inline.
- `md_parser.derive_citation_status` — cross-file union pass. Walks all `CITATION_AUDIT_CYCLE_*.md` files plus the artifact's citation list; deduplicates by citation identity (arXiv id / DOI / a normalized author+year+title key); returns one record per citation with the most-recent audit's tier + classification + argument + cycle, and the current status in the artifact.
- `md_parser.extract_artifact_citations` — parses the artifact (e.g., a literature review markdown) for inline citations and the bibliography section.
- Filter set: tier, classification, status, cycle audited, has-working-link, *needs-audit* (status `in-artifact` or `proposed-addition` with no audit entry).
- No state file; view is derived per request.
- Tests: deduplication on a fixture with the same citation in two cycles' audit files; correct most-recent selection; "needs-audit" filter surfaces the right set on a fixture artifact.

Dependencies: PR 2, PR 4.

## Sequencing

PR 1 and PR 2 are independent of each other and can land in any order. PR 3 needs PR 2. PR 4 needs PR 3. PR 5 needs PR 2 and PR 4 (the citations-status view shares the cross-file derivation work with the audit browse).

A reasonable serial path: 1 → 2 → 3 → 4 → 5.

A parallel-friendly path: PR 1 + PR 2 in parallel; then PR 3; then PR 4; then PR 5.

Each PR's tests cover the slice it ships — there's no separate end-to-end smoke PR. PR 4's tests cover canonical-format audit-doc rendering; PR 5's tests cover the citations-status derivation.

## Open questions to validate during PR 2

1. **Response-block placement.** Plan picks inline-on-the-proposed-change in `REVIEW_RESPONSE_CYCLE_N.md`. Alternative: a sibling `*.decisions.md` file (keeps the response file pristine but detaches decisions from their source). Inline preferred — the response file is canonical.
2. **Audit-doc canonical format.** PR 2's parser targets only the new canonical format. The four pre-flow `CITATION_AUDIT_*.md` files use an older format and stay in the repo as historical archives but aren't rendered by the walker.
3. **Inbox file format for UI → session messages.** Some walker actions (regenerate suggestion, re-run audit on a specific citation) need to message the session. Plan defers to a later PR; for the initial UI scope, walker decisions just write back to the markdown and the next cycle picks them up.

## Non-goals

- A Python iteration runner. The Claude session runs the cycle via its normal tool use.
- Auto-run as a CLI flag on a Python command. Auto-run is the human telling the session to loop.
- Multi-user collaboration. Single user, local-only.
- Persistent database. Markdown is the database.
- Replacing the four existing pre-flow `CITATION_AUDIT_*.md` audits — they render in the audit-browse view as worked examples of cycle-1-style standalone audits.
