# Plan: Walker UI for the Augmented Adversarial-Review Cycle

The augmented cycle (`pm/docs/adversarial-review/METHODOLOGY.md` § The augmented cycle) produces three artifacts per cycle: `REVIEW_CYCLE_N.md`, `CITATION_AUDIT_CYCLE_N.md`, `REVIEW_RESPONSE_CYCLE_N.md`. The response file carries proposed changes — some flowing from review findings (`provenance: reviewer-comment`), some from per-citation audit entries (`provenance: audit-entry`). The walker is the human acceptance surface between the response session producing those proposed changes and the apply step.

The walker is **optional** — auto-run mode applies the response session's recommendations directly. The walker is there for when the human wants to read, accept, edit, or reject proposed changes before they land.

## Design constraints

- **Simple.** FastAPI single-file server. No build step. No framework. Vanilla JS + one CSS file. The markdown files stay canonical.
- **Read-canonical, write-structured.** Walker writes back into the response file's response blocks (a fenced HTML comment per proposed change). No sidecar files for decisions; the response file *is* the decision record.
- **One main walker view + one sub-view.** Main: proposed-changes walker that surfaces every proposed change (from both review and audit) as a response-block. Sub: citation-audit browse view organized per citation, click-through from any audit-sourced proposed change.
- **Local-only.** Runs on `localhost:<port>`; one-line CLI start.

## Interaction model

Every proposed change in the response file has a response block, pre-filled with the response session's recommended verdict and rationale. The human reacts: accept (one click), edit in place, add commentary, or skip. Bulk-accept-per-filter clears the routine cases. Every action appends to the change's `interactions:` log.

### Response-block format on each proposed change

```markdown
<!-- proposed-change
id: change-<n>
provenance: reviewer-comment   # reviewer-comment | audit-entry
source-anchor: <link back to the originating review finding or audit entry>
target-section: §3 — sycophancy framing
before: |
  the artifact's current passage (verbatim, with line-range anchor)
after: |
  the response session's proposed replacement
suggested-verdict: accept       # accept | reject | modify
suggested-rationale: |
  the response session's reasoning for the recommended verdict
human-verdict:                  # blank until the human acts
human-rationale:                # blank
human-commentary:               # blank
status: pending                 # pending | accepted-as-suggested | edited | skipped | auto-accepted
interactions:                   # append-only log of walker interactions
-->
```

The walker reads each proposed-change block, renders it as a paginated entry with the before/after diff inline, surfaces the suggested verdict + rationale, and lets the human act.

### Logged actions

- `viewed` (with `duration-ms` ≥ 1s)
- `accept-as-suggested` — single-click per-entry accept
- `bulk-accept` — accepted via bulk action; `scope` records the filter
- `edit` — field-tagged; re-edits append a new event
- `comment-added` — note recorded even if commentary is later edited away
- `skip` — explicit skip, distinct from never-viewed
- `reopen` — already-acted entry reopened
- `auto-accepted` — auto-run mode applied the recommendation; `mode` recorded

### Auto-run mode

The walker is not required for the cycle to advance. In auto-run mode, the response session's recommendations apply directly: each proposed change is treated as `auto-accepted`, an interaction log entry is appended, the apply step runs. The walker still shows the changes (with the `auto` badge) if the human later opens it, and a `auto-accepted, never human-viewed` filter exists so the human can target unattended entries.

Per-cycle dashboard records the cycle's mode (`auto-run` / `human-reviewed` / `mixed`) and the engagement signals (bulk-accept ratio, median view-time, suggester-confidence distribution for auto-run cycles).

## What the walker covers

- **Proposed-changes walker** — paginated view of every proposed change in `REVIEW_RESPONSE_CYCLE_N.md`. Filterable by provenance (`reviewer-comment` / `audit-entry`), target section, suggested verdict, status. Click-through from `source-anchor` to the originating review finding or audit entry.
- **Citation-audit browse view** — per-citation view of `CITATION_AUDIT_CYCLE_N.md`. One section per audited citation, showing the audit entry (tier, doc passage, source content, verdict, proposed rewrite, surfaced citations). Click-through to the proposed change(s) in the proposed-changes walker.
- **Dashboard** — per-cycle status: review / audit-loop convergence / response readiness; mode tag; engagement signals; convergence indicator for the audit loop (zero newly-surfaced citations in the last round).
- **General-comments surface** (`NOTES_<artifact>.md`) — free-text journal across all walkers, section-tagged, append-only with timestamps. The response session reads the notes file as part of its context.

That's the full scope. No separate scan walker, work-review walker, synthesis walker, crawl-triage walker, cycle-review walker, or proposed-edits walker — the proposed-changes walker subsumes the propose-and-accept flow for both review and audit sources.

## PRs

### PR: Walker primitive + proposed-changes walker

The main walker. Renders `REVIEW_RESPONSE_CYCLE_N.md`'s proposed-change blocks. Per-entry buttons: accept Claude's suggestion / save edits / skip. Page-level: bulk-accept-per-filter (provenance, target section, suggested verdict, status).

Pagination one-entry-per-page for review pace; a denser list view for bulk-accept passes. Hotkeys j/k for next/previous, a for accept, m for modify, s for skip.

Files: `templates/changes.html`, walker route in `server.py`, `md_parser.parse_response_doc`, `md_writer.update_response_block`, `md_writer.append_interaction`.

### PR: Citation-audit browse view

Renders `CITATION_AUDIT_CYCLE_N.md` organized per citation, with click-through to the proposed changes the audit entry produced. Read-only on the audit content itself (the audit is the source of truth; decisions live on the proposed change in the response file).

Files: `templates/audit_browse.html`, route, `md_parser.parse_audit_doc`.

### PR: Dashboard

Per-cycle status view: review readiness (REVIEW_CYCLE_N.md exists), audit-loop convergence (most recent audit-loop round surfaced zero new citations), response readiness (REVIEW_RESPONSE_CYCLE_N.md exists), mode tag (auto-run / human-reviewed / mixed), engagement signals (bulk-accept ratio, median view-time, suggester-confidence distribution for auto-run cycles).

Files: `templates/dashboard.html`, dashboard route in `server.py`.

### PR: General-comments surface

`NOTES_<artifact>.md` collapsible side panel, included in all walker pages. Section-tagged entries with timestamps, append-only. Loaded as response-session context so general comments influence the next cycle's response recommendations.

Files: `templates/notes_pane.html`, notes-write endpoint.

### PR: Auto-run mode + interaction-log integration

Auto-run mode bypasses the walker — response-session recommendations apply directly with interaction-log entries of action `auto-accepted`. CLI flag on the session-launch command toggles auto vs walker-mediated. Walker reads the interaction log for the engagement signals on the dashboard.

Files: `inbox.py` (auto-run trigger format), interaction-log readers in dashboard route.

### PR: End-to-end smoke validation

Three validation paths:

1. **Walker rendering smoke.** Run the walker against the four existing `CITATION_AUDIT_*.md` files. Each renders correctly in the citation-audit browse view.
2. **Proposed-changes round-trip.** Construct a fixture `REVIEW_RESPONSE_CYCLE_N.md` with both reviewer-comment and audit-entry proposed changes; verify the walker renders them; accept and edit a few; verify the round-trip writes are correctly formatted.
3. **End-to-end cycle in auto-run mode.** A small fixture artifact + a session that runs the review / audit-loop / response sequence; verify the dashboard shows convergence; verify the response file's proposed changes have `status: auto-accepted` and a matching interaction-log entry.

Acceptance criteria: all three paths pass; no regressions on the four existing pre-flow audit docs; smoke-test artifact's cycle completes within reasonable wall-clock.

## Sequencing

PR 1 (proposed-changes walker) is the load-bearing piece — everything else depends on its existence or is independent of it. PRs 2 (audit browse) + 3 (dashboard) + 4 (notes) can land in parallel after PR 1. PR 5 (auto-run) needs the interaction-log writes from PR 1. PR 6 (smoke test) needs everything.

## Design decisions to validate during PR 1

1. **Decision storage: inline response-block on the proposed change vs sibling decisions file.** Plan picks inline (the response file is the canonical decision record). Alternative: a sibling `*.decisions.md` file keeps `REVIEW_RESPONSE_CYCLE_N.md` pristine, but the walker has to read two files to render and the decisions detach from their source.
2. **Bulk-accept default scope.** Plan picks *current filter* (avoid the "accidentally accepted 80 things" footgun).
3. **Auto-run failure modes.** What happens when the response session's recommendation conflicts with a prior accepted change? Plan: the response session is responsible for noticing prior-cycle commitments; if it produces a change that conflicts, the walker still renders both and the human picks one. Auto-run treats this as a `low-confidence-suggester` flag and the change is left as `pending` instead of applied. Validate during PR 5.

## Non-goals

- Multi-user collaboration. Single user, local-only.
- Persistent database. Markdown is the database.
- A Python iteration runner. The Claude session is the runner — it executes review / audit-loop / response via its normal tool use.
- Replacing the four existing pre-flow `CITATION_AUDIT_*.md` audits. The citation-audit browse view renders them as the worked examples of cycle-1-style standalone audits.
