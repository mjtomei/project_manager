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

## Lock states — when modifications are allowed

The walker enforces a single rule: **modifications to responses are allowed only in the `awaiting-human-review` phase of the current cycle.** Every other state is read-only.

The cycle's phase lives in `STATE_<artifact>.md`, a small markdown file the session updates at phase transitions:

```yaml
current-cycle: 3
current-phase: awaiting-human-review
# one of: review | audit | response | awaiting-human-review | applying | complete
last-transition: 2026-05-20T14:32:00Z
```

The walker reads this file on every page load, and the server pushes updates via SSE (see *Server-pushed updates* below) whenever the file changes — so the walker reacts to phase transitions in <100ms. Editable controls (accept / edit / bulk-accept / skip / reopen) are enabled only when `current-phase` is `awaiting-human-review` *and* the walker is rendering the current cycle. In every other state the same controls render as read-only badges showing what state they would carry if modifications were allowed.

### The Apply button — the only UI → session signal

When the human is done editing in `awaiting-human-review` mode, they click an **Apply** button on the walker. The walker writes `STATE_<artifact>.md`, transitioning `current-phase` from `awaiting-human-review` to `applying`. The session — which is itself watching the state file — sees the transition and proceeds with the apply step. That single state-file write is the entire UI → session communication channel for the cycle.

In **auto-run mode** the walker isn't a gate. The session transitions `response` → `applying` directly without waiting for the human; the walker is then post-hoc viewing only. The Apply button is hidden in auto-run mode (there's nothing for it to signal — the apply has already happened or is about to).

The phases:
- **review** — REVIEW_CYCLE_N.md being written by the review session. Prior cycles viewable; current cycle has no proposed changes yet. Walker fully read-only.
- **audit** — citation audit loop iterating. Same as review.
- **response** — REVIEW_RESPONSE_CYCLE_N.md being written. Still read-only — the response is mid-flight.
- **awaiting-human-review** — response file written. **Modification window.** Accept/edit/bulk-accept/skip/reopen all work; interaction log records every action.
- **applying** — apply step is consuming the response. Read-only — modifications now would race with the apply.
- **complete** — cycle archived. Read-only.

Previous cycles are always read-only regardless of their state — they're history.

## Previous-cycle viewing

The dashboard has a cycle selector (dropdown, latest first). Selecting a prior cycle navigates every walker view to that cycle's files. The selector defaults to the current cycle; selecting a prior cycle is the only way to leave it.

## Phase indication — breadcrumb and status panel

A small breadcrumb on every walker page tells the human three things at once: which cycle they're looking at, what phase the session is in, and what (if anything) the human can do right now. The breadcrumb is phase-aware:

| Phase | Breadcrumb (current cycle) | What the human can do |
|---|---|---|
| `review` | `Cycle 3 · review in progress` | Wait or browse prior cycles. |
| `audit` | `Cycle 3 · audit loop running · N citations audited` | Wait or browse prior cycles. |
| `response` | `Cycle 3 · response in progress` | Wait or browse prior cycles. |
| `awaiting-human-review` | `Cycle 3 · ready for your review · editable` | Walk the proposed changes; click **Apply** when done. |
| `applying` | `Cycle 3 · applying accepted changes` | Wait or browse prior cycles. |
| `complete` | `Cycle 3 · complete · read-only` | Browse this cycle's history, or move to cycle 4 when it starts. |

Prior-cycle breadcrumbs are always `Cycle N · <phase> · read-only` regardless of how the cycle ended.

The dashboard mirrors this with a larger **Status** panel: the current phase, what's happening, a one-line indication of what the human can do, and (when applicable) a progress hint such as the audit-loop round count. The panel updates instantly via SSE when phase transitions land in `STATE_<artifact>.md`.

This is also where the conversation surface (the session, in the tmux pane) and the visual surface (the walker) stay in sync — the human can see at a glance whether they're being asked to look or to act, without having to context-switch into the session to find out.

## Session-controlled UI focus

The session can direct the walker's view via a focus file (`UI_FOCUS_<artifact>.md`):

```yaml
view: audit-browse            # changes | audit-browse | citations | dashboard | notes
cycle: 3                      # which cycle's data to display
target: citation-2024-xxxxx   # optional anchor — entry id to scroll to
timestamp: 2026-05-20T15:30:00Z
```

The server watches this file via `watchdog` (filesystem inotify) and pushes an SSE event the moment it changes. The walker's client receives the event in <100ms, navigates to the indicated view + cycle, and (if `target` is set) scrolls to the anchor and highlights it briefly.

**Use case.** The human asks the session "why did we end up classifying paper X as low-confidence?" The session reads the audit history, answers in chat, and updates `UI_FOCUS_<artifact>.md` to point at the audit entry for paper X. The walker navigates there essentially instantly; the human sees the entry being discussed without manual navigation.

## Server-pushed updates (SSE + watchdog)

Walker server uses `watchdog` to watch three files per artifact:

- `STATE_<artifact>.md` — phase transitions; walker locks/unlocks editing controls.
- `UI_FOCUS_<artifact>.md` — session-directed navigation; walker navigates + scrolls.
- `REVIEW_RESPONSE_CYCLE_N.md` (for the current cycle) — session-side edits to the response file mid-write; walker refreshes the rendered entries.

When `watchdog` fires on any of these, the server pushes an SSE event to all connected walker clients via a single `/events?artifact=<id>` endpoint. Clients use the browser-native `EventSource` API to react in <100ms.

No polling. The walker still makes no outbound calls — all session → UI updates flow through SSE pushes triggered by filesystem changes.

Symmetrically, the session uses its own filesystem watch (its `watchdog`/`Bash`/`Read` tool calls, or a `Monitor` style polling pattern) to watch `STATE_<artifact>.md` for the Apply button's `applying` transition. That's the entire UI → session channel.

## What the walker covers

- **Proposed-changes walker** — paginated view of every proposed change in `REVIEW_RESPONSE_CYCLE_N.md`. Filterable by provenance (`reviewer-comment` / `audit-entry`), target section, suggested verdict, status. Click-through from `source-anchor` to the originating review finding or audit entry.
- **Citation-audit browse view** — per-cycle view of `CITATION_AUDIT_CYCLE_N.md`. One section per audited citation in that cycle, showing the audit entry (tier, doc passage, source content, verdict, proposed rewrite, surfaced citations). Click-through to the proposed change(s) in the proposed-changes walker.
- **Citations status view** — *cross-cycle*, citation-centric. One row per citation that has ever been considered for the artifact (currently in it, audited, proposed for addition by the review, proposed for removal). Per-citation fields: title + authors + year, **clickable link that opens the source in a new tab**, current tier (1 / 2 / 3), current classification (faithful / over-characterizes / under-characterizes / mischaracterizes / unverified), argument for that classification (verdict rationale + the load-bearing verbatim quote from source), most-recent-audit cycle, and status in the artifact (`in-artifact` / `proposed-addition` / `proposed-removal` / `superseded`). Filterable by any of those fields. Click a row to expand the most recent audit entry inline. The view is *derived* from the union of `CITATION_AUDIT_CYCLE_*.md` files plus the in-artifact citation list — re-derived per request, no separate state file.
- **Dashboard** — per-cycle status: review / audit-loop convergence / response readiness; mode tag; engagement signals; convergence indicator for the audit loop (zero newly-surfaced citations in the last round).
- **General-comments surface** (`NOTES_<artifact>.md`) — free-text journal across all walkers, section-tagged, append-only with timestamps. The response session reads the notes file as part of its context.

That's the full scope. No separate scan walker, work-review walker, synthesis walker, crawl-triage walker, cycle-review walker, or proposed-edits walker — the proposed-changes walker subsumes the propose-and-accept flow for both review and audit sources.

## PRs

### PR: Walker primitive + proposed-changes walker

The main walker. Renders `REVIEW_RESPONSE_CYCLE_N.md`'s proposed-change blocks. Per-entry buttons: accept Claude's suggestion / save edits / skip. Page-level: bulk-accept-per-filter (provenance, target section, suggested verdict, status).

Pagination one-entry-per-page for review pace; a denser list view for bulk-accept passes. Hotkeys j/k for next/previous, a for accept, m for modify, s for skip.

Files: `templates/changes.html`, walker route in `server.py`, `md_parser.parse_response_doc`, `md_writer.update_response_block`, `md_writer.append_interaction`.

### PR: Citation-audit browse view

Renders `CITATION_AUDIT_CYCLE_N.md` organized per citation in *that cycle*, with click-through to the proposed changes the audit entry produced. Read-only on the audit content itself (the audit is the source of truth; decisions live on the proposed change in the response file).

Files: `templates/audit_browse.html`, route, `md_parser.parse_audit_doc`.

### PR: Citations status view

Cross-cycle citation-centric view. Renders one row per citation that has ever been considered for the artifact, derived from the union of all `CITATION_AUDIT_CYCLE_*.md` files and the artifact's current citation list.

Per-row content:
- **Title + authors + year**, formatted compactly.
- **Clickable link** that opens the source in a new tab (`target="_blank" rel="noopener"`).
- **Current tier** (1 / 2 / 3) — from the most-recent audit entry. Empty if not yet audited.
- **Current classification** — `faithful` / `over-characterizes` / `under-characterizes` / `mischaracterizes` / `unverified`. From the most-recent audit entry's verdict.
- **Argument** — the verdict rationale plus the load-bearing verbatim quote from the source (the "what the source actually says" field of the audit entry). Truncated to one line in the table; full text on row expansion.
- **Most-recent-audit cycle** (e.g., "cycle 2" or "—" if never audited).
- **Status in artifact** — `in-artifact` (currently cited) / `proposed-addition` (a review or audit proposes adding) / `proposed-removal` (a review proposes removing) / `superseded` (a later citation supersedes this one per a prior accepted change).

Filterable by: tier, classification, status, cycle audited, presence-or-absence of a working link. Sortable by any column. A "needs audit" filter surfaces citations with status `in-artifact` *or* `proposed-addition` that have no audit entry yet.

Click-to-expand a row to show the most recent audit entry inline (doc passage + source content + verdict + proposed rewrite + any surfaced citations) and links to that cycle's `CITATION_AUDIT_CYCLE_N.md` for the full audit context.

The view is *derived* from disk on each request — no separate state file. The cost is one parse pass over all the audit files plus the artifact's citation list, which for moderate-sized reviews is a few hundred KB total and well within a fast page-load budget.

Files: `templates/citations.html`, route, `md_parser.derive_citation_status` (cross-file union), `md_parser.extract_artifact_citations`.

### PR: Dashboard

Per-cycle status view: review readiness (REVIEW_CYCLE_N.md exists), audit-loop convergence (most recent audit-loop round surfaced zero new citations), response readiness (REVIEW_RESPONSE_CYCLE_N.md exists), mode tag (auto-run / human-reviewed / mixed), engagement signals (bulk-accept ratio, median view-time, suggester-confidence distribution for auto-run cycles).

Files: `templates/dashboard.html`, dashboard route in `server.py`.

### PR: General-comments surface

`NOTES_<artifact>.md` collapsible side panel, included in all walker pages. Section-tagged entries with timestamps, append-only. Loaded as response-session context so general comments influence the next cycle's response recommendations.

Files: `templates/notes_pane.html`, notes-write endpoint.

### PR: Auto-run mode + interaction-log integration

Auto-run mode bypasses the walker — response-session recommendations apply directly with interaction-log entries of action `auto-accepted`. CLI flag on the session-launch command toggles auto vs walker-mediated. Walker reads the interaction log for the engagement signals on the dashboard.

Files: state-file write in `md_writer.py` (`update_state` to transition the phase from `awaiting-human-review` to `applying`), interaction-log readers in dashboard route.

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
- **Backwards compatibility with the four existing pre-flow `CITATION_AUDIT_*.md` files.** They use a format that predates the augmented cycle and are kept in the repo as historical archives, but the audit-browse view targets only the new canonical format. Subsequent audits (`CITATION_AUDIT_CYCLE_N.md` under the new cycle) use the canonical format from the start.
