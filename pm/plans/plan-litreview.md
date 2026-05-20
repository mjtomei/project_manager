# Plan: Walker UI for the Augmented Adversarial-Review Cycle

The augmented cycle (`pm/docs/adversarial-review/METHODOLOGY.md` § The augmented cycle) produces three artifacts per cycle: `REVIEW_CYCLE_N.md`, `CITATION_AUDIT_CYCLE_N.md`, `REVIEW_RESPONSE_CYCLE_N.md`. The response file carries proposed changes — some flowing from review findings (`provenance: reviewer-comment`), some from per-citation audit entries (`provenance: audit-entry`). The walker is the human acceptance surface between the response session producing those proposed changes and the apply step.

The walker is **optional** — auto-run mode applies the response session's recommendations directly. The walker is there for when the human wants to read, accept, edit, or reject proposed changes before they land.

The cycle itself runs in a Claude session via its normal tool use; the Python side is the walker UI, the CLI commands to launch sessions, and the markdown format primitives.

## What this implements

- **CLI: `pm review <target>`** — launches a Claude session in a new tmux pane with the augmented-cycle methodology context (`METHODOLOGY.md` + `CITATION_USE_AUDIT.md` + `CITATION_CRAWL.md`) and a target artifact. Target is any file or topic string; the session runs the review / audit-loop / response cycle using its normal `Bash` / `Edit` / `Write` / `Agent` tool use.
- **CLI: `pm plan literature-review <plan>`** — launches a literature-review session in a new pane within a plan's tmux window. Same methodology context as `pm review`, but the session lives inside the plan's existing tmux window (next to any other plan-related panes) rather than its own window. Plans pane in the TUI gets a keybinding for the same command.
- **`pm review ui [--port]`** — launches the walker server.
- **Walker UI** — proposed-changes walker + citation-audit browse + citations status view + dashboard + general-comments side panel.
- **Markdown format primitives** — response-block parser/writer, interaction-log appender, audit-doc parser, response-doc parser with provenance tags, state-file parser/writer (`STATE.md`), focus-file parser/writer (`UI_FOCUS.md`), notes-file appender (`NOTES.md`).

The Claude session is the runner. No Python runner, no auto-loop driver — auto-run is the human telling the session "run the cycle until convergence."

## Architecture

```
pm/
  review/
    __init__.py
    md_parser.py       # response-block + interaction-log + audit-doc + response-doc + state + focus parsers
    md_writer.py       # response-block writes, interaction-log appends, state/focus/notes writes
    registry.py        # project.yaml reviews-list read/write (resume vs create logic)
    paths.py           # review-id → directory resolution; per-review file paths
    cli.py             # pm review <target> | pm review ui
    context.py         # methodology-context loader (METHODOLOGY + CITATION_USE_AUDIT + CITATION_CRAWL)
    ui/
      server.py        # FastAPI single-file server with SSE
      templates/       # Jinja2 walker templates (changes, audit_browse, citations, dashboard, notes_pane)
      static/          # one CSS file, one JS file
  cli/
    plan.py            # pm plan literature-review
  tui/
    plans_pane.py      # keybinding for plan literature-review launch (existing file)
```

State is purely file-backed. Markdown files (under each review's directory; see *Project registration and directory layout* below) are canonical; no JSON cache, no database.

## Project registration and directory layout

Reviews are first-class entities in `pm/project.yaml`, alongside plans and PRs. Each review gets an `id` (short kebab-case slug, like a plan id), a registration entry, and its own per-review directory holding the cycle files.

### `pm/project.yaml` schema addition

```yaml
reviews:
  - id: regression
    target: pm/plans/plan-regression.md   # path to starting file, or a topic-string for from-topic reviews
    target-type: plan                     # plan | file | topic
    status: active                        # active | archived
```

The dynamic cycle state (`current-cycle`, `current-phase`, `mode`, `last-transition`) lives in `STATE.md` inside the review's directory — not in `project.yaml`. The yaml entry is the registration; `STATE.md` is the source of truth for what's happening in the cycle right now.

Reviews can target:

- **A plan** (`target-type: plan`) — `target` is the plan's path (or, by convention, its id). Launched by `pm plan literature-review <plan>`. The review's artifact id is the plan's filename stem.
- **An arbitrary file** (`target-type: file`) — `target` is the file path. Launched by `pm review <path>`. The review's artifact id is the file's basename (slugified).
- **A topic** (`target-type: topic`) — `target` is a topic string with no underlying file. Launched by `pm review "<topic string>"`. The review's artifact id is a slug of the topic.

### Per-review directory layout

```
pm/docs/adversarial-review/
  METHODOLOGY.md                       # methodology files at the top level (shared across all reviews)
  CITATION_USE_AUDIT.md
  CITATION_CRAWL.md

  reviews/
    <review-id>/                        # one subdirectory per review
      STATE.md                          # current cycle + phase + mode + last-transition
      UI_FOCUS.md                       # session-controlled focus target
      NOTES.md                          # general comments (free-text journal)
      REVIEW_CYCLE_1.md
      CITATION_AUDIT_CYCLE_1.md
      REVIEW_RESPONSE_CYCLE_1.md
      REVIEW_CYCLE_2.md
      CITATION_AUDIT_CYCLE_2.md
      ...

  # legacy files from before the per-review directory layout:
  CITATION_AUDIT_REGRESSION.md          # pre-flow audits stay at top level
  CITATION_AUDIT_USERMODEL.md
  CITATION_AUDIT_USERMODEL_EXTENSION.md
  CITATION_AUDIT_LIVING_ARTIFACTS.md
  REVIEW_CYCLE_*.md                     # legacy per-cycle files (pre-augmented-cycle)
```

The per-review subdirectory means the filenames don't need an `<artifact>` suffix — `STATE.md` instead of `STATE.md`. The directory itself disambiguates. Walker code references files via `<reviews-root>/<review-id>/<filename>` rather than parsing artifact ids out of filenames.

The four pre-flow audit files and any prior cycle files stay at the top level as historical archives; new reviews live under `reviews/`.

### CLI behavior on existing vs new reviews

When `pm review <target>` or `pm plan literature-review <plan>` is invoked:

1. Compute the artifact id from the target (file stem or slugified topic).
2. Look up `id` in `project.yaml`'s `reviews:` list.
   - **If found and `status: active`**: resume the existing review. Open a new pane against its directory (`pm/docs/adversarial-review/reviews/<id>/`). The session reads the existing `STATE.md` and either continues the current phase or starts the next cycle.
   - **If found and `status: archived`**: print a warning, ask the user to either unarchive or pick a new id.
   - **If not found**: create a new entry in `project.yaml`, create the directory, write an initial `STATE.md` (no cycles yet), launch the session.

The walker UI's dashboard lists every review from `project.yaml` (active first, archived collapsed), with cycle counts and the current phase from each `STATE.md`.

### Cross-referencing plans and reviews

A plan can have a review pointing at it (`target-type: plan, target: <plan-id>`). The pm TUI's plans pane can show which plans have active reviews (small badge next to the plan name). The `r` keybinding on a plan with an active review resumes the review; on a plan with no review, it starts a new one.

## Design constraints

- **Simple.** FastAPI single-file server. No build step. No framework. Vanilla JS + one CSS file. The markdown files stay canonical.
- **Read-canonical, write-structured.** Walker writes back into the response file's response blocks (a fenced HTML comment per proposed change). No sidecar files for decisions; the response file *is* the decision record.
- **One main walker view + sub-views.** Main: proposed-changes walker that surfaces every proposed change (from both review and audit) as a response-block. Sub-views: citation-audit browse, citations status, dashboard, notes pane.
- **Local-only.** Runs on `localhost:<port>`; one-line CLI start.

## Markdown formats

### Response-block format on each proposed change

In `REVIEW_RESPONSE_CYCLE_N.md`, every proposed change carries a fenced HTML comment with structured fields:

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

### State file (`STATE.md`)

The session writes this file at every phase transition; the walker reads it on every page load and reacts to live changes via SSE.

```yaml
current-cycle: 3
current-phase: awaiting-human-review
# one of: review | audit | response | awaiting-human-review | applying | complete
mode: human-reviewed              # auto-run | human-reviewed
last-transition: 2026-05-20T14:32:00Z
```

### Focus file (`UI_FOCUS.md`)

The session writes this to direct the walker's view; the walker watches via `watchdog` and reacts via SSE in <100ms.

```yaml
view: audit-browse            # changes | audit-browse | citations | dashboard | notes
cycle: 3                      # which cycle's data to display
target: citation-2024-xxxxx   # optional anchor — entry id to scroll to
timestamp: 2026-05-20T15:30:00Z
```

### Notes file (`NOTES.md`)

Free-text journal across all walkers, section-tagged, append-only with timestamps. The response session reads the notes file as part of its context, so general comments influence the next cycle's response recommendations.

## Interaction model

Every proposed change in the response file has a response block, pre-filled with the response session's recommended verdict and rationale. The human reacts: accept (one click), edit in place, add commentary, or skip. Bulk-accept-per-filter clears the routine cases. Every action appends to the change's `interactions:` log.

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

The dashboard records each cycle's mode (`auto-run` or `human-reviewed`; the `mixed` tag, when shown, applies at the artifact level across multiple cycles — early cycles often `auto-run`, later cycles `human-reviewed`) and the engagement signals (bulk-accept ratio, median view-time, suggester-confidence distribution for auto-run cycles).

## Lock states — when modifications are allowed

The walker enforces a single rule: **modifications to responses are allowed only in the `awaiting-human-review` phase of the current cycle.** Every other state is read-only.

The walker reads `STATE.md` on every page load, and the server pushes updates via SSE (see *Server-pushed updates* below) whenever the file changes — so the walker reacts to phase transitions in <100ms. Editable controls (accept / edit / bulk-accept / skip / reopen) are enabled only when `current-phase` is `awaiting-human-review` *and* the walker is rendering the current cycle. In every other state the same controls render as read-only badges showing what state they would carry if modifications were allowed.

### The Apply button — the only UI → session signal

When the human is done editing in `awaiting-human-review` mode, they click an **Apply** button on the walker. The walker writes `STATE.md`, transitioning `current-phase` from `awaiting-human-review` to `applying`. The session — which is itself watching the state file — sees the transition and proceeds with the apply step. That single state-file write is the entire UI → session communication channel for the cycle.

In **auto-run mode** the walker isn't a gate. The session transitions `response` → `applying` directly without waiting for the human; the walker is then post-hoc viewing only. The Apply button is hidden in auto-run mode (there's nothing for it to signal — the apply has already happened or is about to).

The phases:
- **review** — `REVIEW_CYCLE_N.md` being written by the review session. Prior cycles viewable; current cycle has no proposed changes yet. Walker fully read-only.
- **audit** — citation audit loop iterating. Same as review.
- **response** — `REVIEW_RESPONSE_CYCLE_N.md` being written. Still read-only — the response is mid-flight.
- **awaiting-human-review** — response file written. **Modification window.** Accept/edit/bulk-accept/skip/reopen all work; interaction log records every action.
- **applying** — apply step is consuming the response. Read-only — modifications now would race with the apply.
- **complete** — cycle archived. Read-only.

Previous cycles are always read-only regardless of their state — they're history.

**When no cycle has started yet** (`STATE.md` is absent), the walker renders a "no cycles yet" placeholder on each view with a one-line hint to run `pm review <target>` or `pm plan literature-review <plan>` to start one. The dashboard's cycle selector is empty and the status panel shows "no cycles yet."

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

The dashboard mirrors this with a larger **Status** panel: the current phase, what's happening, a one-line indication of what the human can do, and (when applicable) a progress hint such as the audit-loop round count. The panel updates instantly via SSE when phase transitions land in `STATE.md`.

This is also where the conversation surface (the session, in the tmux pane) and the visual surface (the walker) stay in sync — the human can see at a glance whether they're being asked to look or to act, without having to context-switch into the session to find out.

## Session-controlled UI focus

The session can direct the walker's view via `UI_FOCUS.md` (format above). The server watches it via `watchdog` and pushes an SSE event the moment it changes. The walker's client receives the event in <100ms, navigates to the indicated view + cycle, and (if `target` is set) scrolls to the anchor and highlights it briefly.

**Use case.** The human asks the session "why did we end up classifying paper X as low-confidence?" The session reads the audit history, answers in chat, and updates `UI_FOCUS.md` to point at the audit entry for paper X. The walker navigates there essentially instantly; the human sees the entry being discussed without manual navigation.

## Server-pushed updates (SSE + watchdog)

Walker server uses `watchdog` to watch three files per artifact:

- `STATE.md` — phase transitions; walker locks/unlocks editing controls.
- `UI_FOCUS.md` — session-directed navigation; walker navigates + scrolls.
- `REVIEW_RESPONSE_CYCLE_N.md` (for the current cycle) — session-side edits to the response file mid-write; walker refreshes the rendered entries.

When `watchdog` fires on any of these, the server pushes an SSE event to all connected walker clients via a single `/events?review=<id>` endpoint. Clients use the browser-native `EventSource` API to react in <100ms.

No polling. The walker still makes no outbound calls — all session → UI updates flow through SSE pushes triggered by filesystem changes.

Symmetrically, the session uses its own filesystem watch (its `watchdog`/`Bash`/`Read` tool calls, or a `Monitor` style polling pattern, or `ScheduleWakeup` at generous intervals while in `awaiting-human-review`) to watch `STATE.md` for the Apply button's `applying` transition. That's the entire UI → session channel.

## What the walker covers

- **Proposed-changes walker** — paginated view of every proposed change in `REVIEW_RESPONSE_CYCLE_N.md`. Filterable by provenance (`reviewer-comment` / `audit-entry`), target section, suggested verdict, status. Click-through from `source-anchor` to the originating review finding or audit entry. Pagination is one-entry-per-page for careful review; a denser list view supports bulk-accept passes. Hotkeys: `j` / `k` next/previous, `a` accept Claude's suggestion, `m` modify, `s` skip.
- **Citation-audit browse view** — per-cycle view of `CITATION_AUDIT_CYCLE_N.md`. One section per audited citation in that cycle, showing the audit entry (tier, doc passage, source content, verdict, proposed rewrite, surfaced citations). Click-through to the proposed change(s) in the proposed-changes walker.
- **Citations status view** — *cross-cycle*, citation-centric. One row per citation that has ever been considered for the artifact (currently in it, audited, proposed for addition by the review, proposed for removal). Per-citation fields: title + authors + year, **clickable link that opens the source in a new tab**, current tier (1 / 2 / 3), current classification (faithful / over-characterizes / under-characterizes / mischaracterizes / unverified), argument for that classification (verdict rationale + the load-bearing verbatim quote from source), most-recent-audit cycle, and status in the artifact (`in-artifact` / `proposed-addition` / `proposed-removal` / `superseded`). Filterable by any of those fields. Click a row to expand the most recent audit entry inline. The view is *derived* from the union of `CITATION_AUDIT_CYCLE_*.md` files plus the in-artifact citation list — re-derived per request, no separate state file.
- **Dashboard** — per-cycle status: review / audit-loop convergence / response readiness; mode tag; engagement signals; convergence indicator for the audit loop (zero newly-surfaced citations in the last round).
- **General-comments surface** (`NOTES.md`) — free-text journal across all walkers, section-tagged, append-only with timestamps.

## PRs

### PR 1: Session-launching CLI commands + project.yaml registry — `pm plan literature-review` + `pm review <target>`

Two CLI commands that launch literature-review sessions in new tmux panes plus the `project.yaml`-backed review registry. Share the pane-management code, the methodology-context loader, and the registry / path resolution, so they land together.

- `pm/review/registry.py` — read/write `project.yaml`'s `reviews:` list. APIs: `get_review(id)`, `create_review(id, target, target-type)`, `set_status(id, status)`, `list_active()`. Round-trip-preserves the surrounding yaml structure (other top-level keys like `plans`, `prs` remain untouched).
- `pm/review/paths.py` — review-id → directory resolution and per-review file paths. Constants: `REVIEWS_ROOT = pm/docs/adversarial-review/reviews/`. Functions: `dir_for(id)`, `state_path(id)`, `focus_path(id)`, `notes_path(id)`, `cycle_paths(id, n)`. Creates the per-review directory on first access.
- `pm/review/context.py` — methodology-context loader (shared by both commands). Concatenates `METHODOLOGY.md`, `CITATION_USE_AUDIT.md`, `CITATION_CRAWL.md`, the review's `STATE.md` if it exists, and a target preamble. The framing instruction: "you are running the augmented adversarial-review cycle on the target below; produce REVIEW_CYCLE_N.md, then the audit loop, then REVIEW_RESPONSE_CYCLE_N.md, per the methodology files. State lives in your review's directory at `<review-dir>/`."
- `pm/cli/plan.py` — `pm plan literature-review <plan>` subcommand. Resolves the artifact id from the plan's filename stem. Looks up the review in the registry (resume if found and active; create if not found; warn if archived). Resolves the plan's existing tmux window via the existing pane-management code; opens a new pane in *that* window running `claude` with the methodology context. Role: `literature-review`.
- `pm/tui/plans_pane.py` — TUI keybinding (default `r`) on the plans pane invokes `pm plan literature-review` for the selected plan. The pane also surfaces a small badge next to each plan that has an active review.
- `pm/review/cli.py` — `pm review <target>` subcommand. Target can be a file path (`target-type: file`), a plan id (`target-type: plan`, resolved via the plans registry), or a topic string (`target-type: topic`). Same resume-or-create flow against the registry. Opens a new tmux pane (not bound to any plan window) with the methodology context. `pm review ui` is the only other dispatch under `pm review` — anything else is treated as a target.
- **Artifact-id derivation:** file basename (slugified) for file targets; plan filename stem for plan targets; slugified topic for topic targets.
- **Resume vs create.** When `pm review` or `pm plan literature-review` is invoked, the registry decides:
  - registry has `id` with `status: active` → resume (open pane against the existing directory).
  - registry has `id` with `status: archived` → warn the user; they must explicitly unarchive or pick a new id.
  - registry has no entry → create (write the registry entry, create the directory, write an initial `STATE.md` with no cycles yet).
- Tests:
  - `pm plan literature-review`: pane created in the plan's window with the right role; methodology context loaded; registry entry created on first run, resumed on second run; plans-pane keybinding routes correctly; plan badge shows when a review is active.
  - `pm review <target>`: context-build produces a valid prompt; file vs plan vs topic targets all resolve correctly; pane launched in role `literature-review`; `ui` argument routes to the server rather than being treated as a target named "ui"; resume vs create logic correct against fixture registry states; archived review produces the expected warning.

Dependencies: none. Independent of the UI work.

**Why both commands.** `pm review` and `pm plan literature-review` do the same conceptual thing (start or resume a review against a target) but differ in *where* the pane lands. `pm review` opens its own pane; `pm plan literature-review` opens inside an existing plan's window so the review session sits alongside the plan's other panes. Same code path, different pane parent.

### PR 2: Markdown format primitives

The data layer the UI builds on.

- `md_parser.py` — response-block parser (fenced HTML comment with `proposed-change` header, structured fields), interaction-log parser, audit-doc parser (per-citation entries in the canonical format with `surfaced-citations:` lists), response-doc parser (proposed changes with `provenance:` tags), state-file parser (`STATE.md` — current cycle + phase), focus-file parser (`UI_FOCUS.md` — view + cycle + target + timestamp).
- `md_writer.py` — atomic response-block updates (`update_response_block`), append-only interaction-log entries (`append_interaction`), notes-file appends (`append_note`), state-file write (`update_state` for the session to call at phase transitions), focus-file write (`update_focus` for the session to call when directing UI attention).
- Tests: response-block round-trip; interaction-log append concurrency; canonical-format audit-doc parsing; response-doc parsing with mixed-provenance changes; state-file phase transitions; focus-file timestamp ordering.

Dependencies: none. Ships independently.

### PR 3: Web server skeleton + dashboard + proposed-changes walker + lock states + cycle navigation + SSE pushes + Apply button

- `pm/review/ui/server.py` — FastAPI single-file. Reads `project.yaml`'s `reviews:` list to enumerate reviews. Per-review routes (dashboard, walkers) keyed by review id; resolves files via `pm/review/paths.py`. Watches each review's `STATE.md`, `UI_FOCUS.md`, and the current cycle's `REVIEW_RESPONSE_CYCLE_N.md` via `watchdog` (filesystem inotify). Exposes a single `/events?review=<id>` SSE endpoint that pushes events when any watched file changes.
- `templates/dashboard.html` — top-level list of all reviews from the registry (active first, archived collapsed). Per-review row: name + target + current cycle + current phase + mode tag + engagement signals. Click into a review for the per-cycle status view: review/audit-loop/response readiness, audit-loop convergence indicator, **cycle selector** (dropdown, latest first; defaults to current cycle).
- `templates/changes.html` — paginated proposed-changes walker per the *What the walker covers* section. Filterable by provenance, target section, suggested verdict, status. Per-entry accept/edit/skip actions; page-level bulk-accept-per-filter.
- **Apply button.** Visible only when `STATE.md`'s `current-phase` is `awaiting-human-review` and the rendered cycle is the current cycle. Clicking it writes `STATE.md`, transitioning the phase to `applying` (using `md_writer.update_state`). The session — watching the same file — sees the transition and proceeds with the apply step. This is the entire UI → session communication channel.
- **Lock-state enforcement.** Walker editable controls (accept / edit / bulk-accept / skip / reopen / Apply) are enabled only when `current-phase` is `awaiting-human-review` *and* the rendered cycle is the current cycle. In every other state the controls render as read-only badges.
- **Phase-aware breadcrumb + Status panel** per the *Phase indication* section. Both update instantly via SSE on state-file changes.
- **Cycle navigation.** The cycle selector on the dashboard, and the breadcrumb on every walker page, lets the user jump between cycles. Prior cycles are always read-only regardless of state.
- **SSE-pushed updates.** Client-side JS uses `EventSource('/events?review=...')` to subscribe. When the server's `watchdog` observer detects a change to `STATE.md`, `UI_FOCUS.md`, or the current `REVIEW_RESPONSE_CYCLE_N.md`, the server pushes an event to all connected clients. On a STATE event the walker locks/unlocks controls; on a FOCUS event the walker navigates to the indicated view + cycle + target; on a RESPONSE event the walker re-fetches and re-renders entries.
- `static/style.css`, `static/walker.js` — minimal CSS, vanilla JS for hotkeys + bulk-accept + view-time tracking + SSE event handling + lock-state UI states (badges vs editable controls).
- Dependency: `watchdog` (Python lib, wraps inotify on Linux).
- CLI: `pm review ui [--port]`.
- Tests: dashboard renders correctly against a fixture multi-cycle state; proposed-changes walker renders fixture proposed changes and round-trips edits when state is `awaiting-human-review`; walker shows read-only badges (no round-trip) when state is `review` / `audit` / `response` / `applying` / `complete`; Apply button writes the state transition correctly and is hidden outside `awaiting-human-review`; cycle selector navigates between cycles; SSE event for a STATE-file change locks the walker in <200ms; SSE event for a FOCUS-file change navigates within <200ms.

Dependencies: PR 2.

### PR 4: Citation-audit browse view + general-comments surface

- `templates/audit_browse.html` — renders `CITATION_AUDIT_CYCLE_N.md` (per-cycle) in the canonical format, organized per citation, with click-through to the proposed changes the entry produced. The four pre-flow `CITATION_AUDIT_*.md` files are not targeted (no backwards compat — see *Non-goals*).
- `templates/notes_pane.html` — collapsible side panel included in all walker pages. Reads/writes `NOTES.md` with section-tagged entries and timestamps.
- Notes file loadable into the session context so general comments influence next cycle's response.
- Tests: audit-browse renders a fixture `CITATION_AUDIT_CYCLE_N.md` in canonical format correctly; notes-pane round-trips edits.

Dependencies: PR 3.

### PR 5: Citations status view (cross-cycle citation dashboard)

The cross-cycle citation-centric view. One row per citation that has ever been considered for the artifact, derived from the union of all per-cycle audit files plus the artifact's current citation list.

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

## Design decisions

These are the design choices baked into the spec; flag any to revisit during implementation.

1. **Decision storage: inline response-block on the proposed change, vs. sibling decisions file.** Plan picks inline — the response file is the canonical decision record. Alternative: a sibling `*.decisions.md` file keeps `REVIEW_RESPONSE_CYCLE_N.md` pristine, but the walker has to read two files to render and decisions detach from their source.
2. **Bulk-accept default scope.** Plan picks *current filter* (avoid the "accidentally accepted 80 things" footgun); whole-document bulk-accept is opt-in via an explicit "expand scope" toggle.
3. **Auto-run conflict handling.** When the response session's recommendation conflicts with a prior accepted change, the response session is responsible for noticing prior-cycle commitments. If it produces a change that conflicts, the walker still renders both and the human picks one; in auto-run mode the change is left as `pending` (not applied) with a `low-confidence-suggester` flag.

## Non-goals

- A Python iteration runner. The Claude session runs the cycle via its normal tool use.
- Auto-run as a CLI flag on a Python command. Auto-run is the human telling the session to loop.
- Multi-user collaboration. Single user, local-only.
- Persistent database. Markdown is the database.
- **Backwards compatibility with the four existing pre-flow `CITATION_AUDIT_*.md` files.** They use a format that predates the augmented cycle and are kept in the repo as historical archives, but the audit-browse view targets only the new canonical format. Subsequent audits (`CITATION_AUDIT_CYCLE_N.md` under the new cycle) use the canonical format from the start.
