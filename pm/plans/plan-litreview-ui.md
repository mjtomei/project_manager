# Plan: Simple HTML Interfaces for the Literature Review Flow

The literature review flow (`pm/docs/adversarial-review/LITERATURE_REVIEW_FLOW.md`) produces structured markdown artifacts at each phase: initial-scan docs (Phase 1), per-work review docs (Phase 2, plus the four pre-flow `CITATION_AUDIT_*.md` artifacts in audit mode), crawl-output docs (Phase 3), synthesis-claim docs, per-cycle whole-document review docs, proposed-edit docs, and a free-form notes file. Walking those docs by eye works but doesn't scale — a moderately sized review can produce 150+ scan entries, 50+ Tier-1 work-review entries, eight standing-task responses per cycle, and several iterations of crawl output.

The interface covers **the full review cycle**, not just one phase. The original framing was citation-audit-only — for the four existing pre-flow audit docs — but the same walker primitive (read entry / pre-filled response / human accept-edit-comment / bulk-accept / write back to markdown) generalizes to every phase of the new flow. The citation-audit walker is preserved as one configuration of the work-review walker (against `CITATION_AUDIT_*.md` files instead of `WORK_REVIEW_*.md` files, with the rewrite-acceptance variant of the entry shape); the rest of the walkers handle the new flow's phases under the same primitive.

The interfaces are **tooling for the process**; the markdown stays canonical. The HTML reads the docs, surfaces the human-decision points, and writes the decisions back as structured annotations in the same docs (or as side files the next phase picks up).

## What the interface covers (full scope)

- **Citation-audit walker** (mode of work-review walker; reads `CITATION_AUDIT_*.md`) — preserved for the four existing pre-flow audits and any future standalone audits of pre-flow artifacts. Rewrite-acceptance flow lands on these.
- **Initial-scan walker** (Phase 1) — page through scan verdicts, edit/bulk-accept.
- **Work-review walker** (Phase 2) — read per-work entries, accept/edit synthesis claims, declare dependencies; same template renders citation-audit docs in audit mode.
- **Crawl-triage walker** (Phase 3) — bulk-tag crawl outputs before they feed the next iteration.
- **Synthesis-claim walker** — dedicated view of pending / contested / accepted claims, sortable by dependent-count.
- **Cycle-review walker** — per-cycle standing whole-document review responses (the new equivalent of running an adversarial-review cycle on the in-progress artifact).
- **Proposed-edits walker** — diff-review for prose changes flowing from work-reviews, synthesis claims, and audit-mode rewrites; bidirectional provenance.
- **General-comments surface** (`NOTES_<artifact>.md`) — free-text journal across all walkers.
- **Dashboard** — convergence indicators, funnel ratios, blocking dependencies, ready-task counts, cycle-review iteration history.

Every walker shares the same primitive: agent-suggested responses (per `SUGGESTION_PASS.md`), pre-filled into editable response blocks, with bulk-accept and per-entry Blocking views.

## Design constraints

- **Simple.** Static HTML + a thin local Python server (FastAPI or Flask, single file). No build step, no framework, no database. The "state" lives in the markdown files.
- **Read-canonical, write-structured.** The interfaces never replace the markdown as the source of truth. Human responses get appended as structured fenced blocks in the same file (see *Interaction model* below). The next-phase tooling reads those annotations.
- **One interface per phase.** Each phase has its own walker view, tuned to that phase's decision shape. Plus a dashboard tying them together.
- **Local-only.** Runs on `localhost:<port>`, started by a single `python -m pm.litreview_ui`. No auth, no deployment.
- **No JS framework.** Vanilla JS + a small CSS file. The pages are content-dense, mostly text and one or two action buttons per entry.

## Interaction model: agent-suggested, human-confirmed-or-edited

Every human-facing decision point in every walker follows the same three-part pattern:

1. **Agent suggestion (pre-populated).** When an agent writes a scan, work-review, crawl, or synthesis-claim entry, it also writes a *suggested response* for the human alongside it — the verdict the agent expects the human will land on, plus a one-line rationale. The walker renders this as a pre-filled, fully-editable field, not as a hidden agent-decision. The human sees Claude's reasoning by default; the prompt is *react to this*, not *answer from scratch*.

2. **Human action.** For each entry the human can:
   - **Accept Claude's suggestion** with one click (records the suggestion as the human response verbatim).
   - **Edit** the suggestion freely — both the structured verdict (enum) and the free-text rationale / commentary fields. The edit replaces the suggestion in the written response.
   - **Add freeform commentary** in a dedicated `**Commentary:**` text field that travels with the entry into downstream phases (the next iteration's relevance scan sees this; the work-review walker sees the scan's commentary; the synthesis walker sees the work-review's commentary).
   - **Skip** (no action) — the entry stays *pending human review* and the dashboard backlog counts it.

3. **Bulk accept.** Every walker page has a *bulk accept Claude's suggestions* button that records the agent's suggestion as the human response for every entry on the current page (or every entry matching the current filter — e.g., "all faithful Tier-2 work-reviews in this cluster"). One click clears the routine cases; the human's attention concentrates on entries where they actually disagreed and edited.

### Markdown response format

Each entry's response block is a fenced HTML comment with structured fields the parser can round-trip. For an initial-scan entry, the block looks like:

```markdown
<!-- response
suggested-verdict: relevant
suggested-rationale: Load-bearing for §3 sycophancy framing.
human-verdict:           # blank until human acts
human-rationale:         # blank
human-commentary:        # blank
status: pending          # pending | accepted-as-suggested | edited | skipped
-->
```

On *accept Claude's suggestion*: `human-verdict` and `human-rationale` get copied from the suggested fields verbatim; `status` → `accepted-as-suggested`.

On *edit*: `human-verdict` / `human-rationale` / `human-commentary` get whatever the human typed; `status` → `edited`.

On *skip*: nothing changes; `status` stays `pending`.

Downstream tooling always reads `human-verdict` first, falls back to `suggested-verdict` when `status` is `pending`. The fall-through means a pipeline can run without human review for fast iterations (relying on Claude's suggestions throughout), but every fall-through is *visible* — the dashboard counts pending entries as the unresolved backlog so the human can come back to them.

### Per-entry blocking view

Every citation entry in every walker carries a **Blocking** section that shows, in real time, what downstream work is currently gated on this entry's decisions. This is what makes the response block first-class per citation: you see *not just* the suggestion to react to, *but also* what reacting unlocks.

For each walker, the Blocking section surfaces:

- **Initial-scan entry** — *if your verdict stays `relevant` this work proceeds to Phase 2 (work-review)*. If `not-relevant`, Phase 2 skips it. The section lists the work-review entry that would be created (or already exists, if the iteration is mid-flight) with a click-through.
- **Work-review entry** — *synthesis claims this work has produced* (each with its own dependent-count and click-through to the synthesis-walker entry) and *dependencies this work has declared on prior claims* (with click-through). A red badge on any dependency that's still `pending` or `contested` means this work-review is itself blocked.
- **Crawl entry** — *the iteration-N+1 scan entry this candidate would feed into* (predicted, before realization). Skip-marking removes the candidate from the next iteration's funnel; must-include adds it as a forced relevant.
- **Synthesis claim** — *the work-reviews that have declared dependencies on this claim* (each with click-through). Sorting the synthesis walker by dependent-count puts the most-blocking claims first.

The Blocking section is a hyperlink hub: the human can pivot from any entry to its dependents to its dependents' dependents, navigating the actual decision graph rather than the file structure. Resolving a high-blocking entry shows the satisfaction propagate — dependent entries' badges flip from red to green as their gates open.

### Why pre-populate

A blank decision field for 150 scan entries is a wall. A pre-filled field with Claude's reasoning visible turns each entry into a quick *yes / no / no-but-actually*. Most entries the human will accept-as-suggested in <1s; the entries that get edited are where the human's attention is actually adding value. The same shape applies to work-review verdicts, synthesis-claim acceptance, and crawl triage — pre-population is the primitive that makes the walker pace match the human's reading pace.

### Where suggestions come from

Suggestions are written by a **separate suggester sub-agent**, not by the entry-writing agent — see `SUGGESTION_PASS.md` for the methodology. After the entry-writing pass produces a scan summary, work-review, crawl candidate, synthesis claim, or proposed edit, a separate suggester pass reads the entry fresh, looks at the source against the artifact's current state and accepted synthesis claims, and writes the suggested response into the entry's response block.

The separation mirrors the adversarial-review pattern this directory uses elsewhere — different agents for entry-writing and reviewing avoid self-confirmation bias on the suggestion. The walker does not show an entry until its suggester pass has also completed (otherwise there's nothing to pre-fill against, defeating the primitive).

Each suggestion carries a pointer to the suggester pass's full reasoning artifact (`SUGGESTIONS_<artifact>_<phase>_iter<N>.md`), so the human can audit the suggester's reasoning by clicking through, the same way they would audit any other agent's output.

## Architecture

```
pm/
  litreview_ui/
    __init__.py
    server.py          # FastAPI app, serves the four views + save endpoints
    md_parser.py       # parse scan / audit / crawl docs into entry lists
    md_writer.py       # append human-decision annotations back into docs
    templates/         # Jinja2 templates: scan.html, audit.html, crawl.html, dashboard.html
    static/            # one CSS file, one JS file
```

The server scans `pm/docs/adversarial-review/` for files matching `INITIAL_SCAN_*.md`, `CITATION_AUDIT_*.md`, `CRAWL_*.md`. The dashboard lists them. Each view parses its file into entries and renders one entry per page (or a few-per-page for scan triage).

## PRs

### PR: Skeleton server and dashboard view

Stand up the FastAPI app, the dashboard route, and the file-discovery code. Dashboard shows: list of artifacts under review, per-artifact iteration count, links to each phase's docs, funnel-ratio numbers parsed from the scan docs, and a convergence indicator (zero new relevant in the last iteration's crawl).

Files: `server.py`, `md_parser.py` (artifact + iteration discovery), `templates/dashboard.html`, `static/style.css`.

No save behaviour yet — read-only.

### PR: Initial-scan walker

Per-entry view of a Phase 1 scan doc. Each entry shows the citation header (with the working link), the 1–2-sentence summary, and the **response block** per the *Interaction model* above — pre-filled with Claude's suggested verdict and rationale, editable in place, plus a free-text `Commentary` field.

Per-entry buttons: **accept Claude's suggestion** (one-click), **save edits**, **skip**. Page-level: **bulk-accept all on this page**, **bulk-accept all matching filter** (filter by suggested verdict, by cluster, by un-acted-on, etc.).

Saves write the structured response block under the entry per the markdown response format. The Phase 2 / Phase 3 tooling reads `human-verdict` first, falls back to `suggested-verdict` when status is `pending`.

A "next-entry" hotkey (j/k or arrow keys), an "only show un-acted" filter, and a "show only edits / disagreements" filter make 150-entry scans tractable.

Files: `templates/scan.html`, walker route in `server.py`, `md_parser.parse_scan_doc` (parses both entry content and response block), `md_writer.update_response_block`.

### PR: Work-review walker (with synthesis-claim integration)

Per-entry view of a Phase 2 `WORK_REVIEW_<artifact>.md` doc — generative, not audit framing. (For the audit-mode walker on the four pre-flow audit docs, the same template renders against the existing `CITATION_AUDIT_*.md` files with the rewrite-acceptance flow.) Shows the citation header, the work's load-bearing content, scope and conditions, alternative perspectives, optional draft prose, **plus a "Synthesis claims produced" panel and a "Dependencies declared" panel** (see `SYNTHESIS.md`).

Every editable field in the entry — draft prose, each produced claim's text and proposed status, each dependency declaration — follows the *Interaction model*: Claude pre-fills the suggestion, the human accepts (one click) or edits in place. Page-level **bulk accept** clears routine entries; the human's attention concentrates on the entries with substantive synthesis decisions.

Buttons on the draft prose / rewrite block: **accept Claude's suggestion**, **edit and save**, **reject** (drops the suggestion entirely).

Buttons on each produced claim (each is a response-block field pre-filled with Claude's suggested resolution):
- **accept as stated** (status → `human-accepted`, unblocks dependents);
- **modify** (edit claim text, flag any dependents that need re-validation);
- **reject** (status → `superseded`, dependent audits get a "re-run" badge);
- **merge with…** (picker showing other claims; resulting merge inherits the union of supporting citations + dependents);
- **split into two** (text field for the second claim);
- **mark contested** (with the prior claim it contradicts).

Buttons on auto-accepted claims: **downgrade to contested** (human disagrees after the fact — same effect as `mark contested` but applied retroactively).

The walker shows the **block status** at the top of each entry: green if all declared dependencies are accepted, red if any are pending/contested. Red entries are read-only on their rewrite/claims (you have to resolve the upstream block first) but link directly to the blocking claim.

Accepted rewrites collect into a sibling `*.rewrites.md` file (artifact-path, line-range-anchor, before, after). The `apply-rewrites` CLI produces a unified diff against the source lit review for human review before commit.

Tier-1 entries get the full per-entry view (rewrite + claims + dependencies). Tier-2 entries get a denser list view (verdict + one-click accept/reject, no claim production). Tier-3 entries are read-only.

Files: `templates/audit.html`, `md_parser.parse_audit_doc`, `md_writer.append_rewrite_decision`, `md_writer.update_claim_status`, `apply-rewrites` CLI.

### PR: Crawl triage

Bulk-list view of a Phase 3 crawl doc. One row per surfaced candidate: title + link + brief "why surfaced" + the response block per the *Interaction model* (Claude's suggested triage — `feed-to-scan` / `skip` / `must-include` — pre-filled, editable per row, with a free-text rationale column).

Multi-select via checkbox + page-level **bulk accept Claude's suggestions**. Common pattern: skim, edit the 3–5 rows where you disagree, bulk-accept the rest.

Saves write the structured response block per candidate. The next iteration's Phase 1 scan only enqueues candidates with effective verdict `feed-to-scan` or `must-include` (effective = `human-verdict` if present, else `suggested-verdict`).

Files: `templates/crawl.html`, `md_parser.parse_crawl_doc`, `md_writer.update_response_block` (shared).

### PR: Cycle-review walker + general-comments surface

Two related additions that handle whole-document concerns the per-entry walkers don't reach.

**Cycle-review walker.** Per-cycle view of `CYCLE_REVIEW_<artifact>_iter<N>.md` — the standing whole-document review output (see `LITERATURE_REVIEW_FLOW.md` § Standing whole-document tasks). One reviewer sub-agent answers the eight standing tasks in a single pass per cycle (matching the existing adversarial-review cycle shape — see `SUGGESTION_PASS.md` § Standing whole-document review). The walker presents each standing-task response as a populated response block, per the *Interaction model*: accept / edit / reject / commentary, with bulk-accept available.

Findings whose proposed actions are walker-typed get a **route to walker X** button (e.g., "route to proposed-edits walker as a prose change," "route to synthesis walker as a cluster-reorganization," "route to crawl-triage as a coverage-gap seed"). Findings that are general observations stay in the cycle-review view.

Iteration history is preserved — the walker shows all prior cycles' CYCLE_REVIEW files in a sidebar so the human can compare what the reviewer flagged last cycle versus this cycle (the convergence signal across iterations is visible here).

Files: `templates/cycle_review.html`, `md_parser.parse_cycle_review_doc`, route-to-walker action endpoints, walker sidebar history component.

**General-comments surface.** A free-text commentary area for thoughts not attached to any specific entry — overall observations, strategic concerns, cross-cutting notes, hypothesis-level reservations the human wants to leave for themselves or for the next iteration. Lives in a `NOTES_<artifact>.md` file alongside the per-walker outputs.

UI surface:
- **Persistent surface across all walkers.** A "Notes" pane accessible from any walker page (collapsible side panel or modal). The human can dump a thought without losing their place in the current entry.
- **Section-tagged entries.** Each note can be tagged with a section / cluster / iteration number, so notes about §3 sycophancy-framing don't get lost in a flat list. Untagged notes are allowed for genuinely cross-cutting observations.
- **Reviewer-visible.** The standing whole-document reviewer pass reads `NOTES_<artifact>.md` as part of its context, so the human's general comments shape what the next cycle's reviewer attends to. A note saying "I'm worried §3 is leaning too hard on Sharma 2023" becomes context the reviewer can use.
- **Append-only by default with a markdown timestamp prefix.** The human writes a new note as a new paragraph, dated. Older notes stay visible; the file is the running journal.
- **No suggester pass on the notes surface.** The notes are the human's voice — Claude doesn't pre-fill them. (A "summarize notes since iteration N" button using walker-time generation is a later optional PR.)

Files: `templates/notes_pane.html` (partial, included in all walkers), `md_writer.append_note`, `md_parser.parse_notes_doc` (for the reviewer-context loading), dashboard route to view the notes file.

### PR: Synthesis-claim walker

Dedicated view of `SYNTHESIS_<artifact>.md`. List of claims, filterable by status (`pending` / `auto-accepted` / `human-accepted` / `contested` / `superseded`) and sortable by dependent-count.

Each claim row shows: id, claim text, supporting citations (with links), status, dependent count + dependents list (click-through to the dependent work-review entries), and the response block per the *Interaction model* — Claude's suggested resolution (e.g., "accept as stated"; "merge with `prior-claim-id`"; "contest with `prior-claim-id`") pre-filled, with editable rationale and an open commentary field.

Per-claim actions: **accept Claude's suggestion**, **edit and save**, plus structured-edit shortcuts for the actions that need extra data (modify-text, merge-with, split-into-two, mark-contested-with). Bulk accept available for routine auto-accepted claims when the human is reviewing them retrospectively.

Pending claims sorted by dependent-count descending are the actionable backlog — resolving the most-depended-on claim first unblocks the most downstream work.

Files: `templates/synthesis.html`, `md_parser.parse_synthesis_doc`, `md_writer.update_response_block` (shared), `md_writer.update_claim_status`, `md_parser.compute_dependent_graph`.

### PR: Proposed-edits walker

A dedicated walker view for proposed edits to the lit review prose itself. Standard propose-and-accept diff-review, plus provenance links from each edit back to the work-review entry, synthesis claim, or audit finding that produced it.

**Sources of proposed edits.** Three, all flowing into the same walker:
1. **Work-review draft prose.** Tier-1 work-review entries' optional draft-prose lines become candidate edits to the lit review when the artifact moves toward Phase 5 assembly. Each draft is a proposed insertion (or replacement of an existing passage) anchored to a cluster and section.
2. **Synthesis-claim prose implications.** When a synthesis claim is accepted (or contested with a documented disagreement), the lit review's prose has to reflect it. The synthesis walker can emit proposed edits to existing prose that the claim contradicts, with the synthesis claim's id as provenance.
3. **Audit-mode rewrite proposals.** The four existing `CITATION_AUDIT_*.md` files contain proposed rewrites of existing pre-flow lit-review passages. These flow into the same walker so the same UI handles audit-mode and new-flow edits.

**Per-edit view.** Shows:
- **before** (verbatim passage from the lit review, with line-range anchor);
- **after** (the proposed text);
- **provenance** — a *Why this edit?* section with click-through links to the originating work-review entry, synthesis claim, or audit finding (often more than one — an edit may be supported by multiple work-reviews / claims);
- **diff visualization** — inline word-level diff so the human sees what actually changed without re-reading the whole passage;
- **response block** — Claude's suggester pass result, pre-filled with `accept` / `modify` / `reject` plus rationale and optional commentary, per the *Interaction model*.

**Provenance links from works to changes.** This is the inverse direction the user asked for — from a work-review entry, the walker shows *all proposed edits that descend from this work-review*. Click-through both directions: walk from "this edit" → "the work-reviews that produced it" and from "this work-review" → "the edits it produced." The decision graph becomes navigable from any node to any of its consequences.

**Cluster/section grouping.** Proposed edits are grouped by lit-review section (the section they target), so the human can review all edits to §3 together rather than scattering attention. Bulk-accept-within-section is the common pattern.

**Apply flow.** Accepted edits collect into a sibling `EDITS_<artifact>.applied.md` file. An **Apply accepted edits** action produces a unified diff against the lit review document for human review before commit (no direct write-through; the diff-review gate is preserved). The diff lands as a PR-ready set of changes, with edit provenance preserved as comments in the commit message.

**Conflict detection.** Two accepted edits that target overlapping line ranges flag a conflict at apply-time, blocking the apply action until the human resolves which edit wins (typically by editing one of them or by accepting both as a sequential pair the apply step orders).

Files: `templates/edits.html`, `md_parser.parse_proposed_edits` (pulls from work-review drafts, synthesis-claim implications, audit-mode rewrites), `md_parser.compute_edit_provenance` (graph traversal back to originators), `md_writer.update_response_block` (shared), `apply-edits` CLI command (produces unified diff with provenance in commit message).

### PR: Ready-task execution via Claude-session integration

The walker can identify ready tasks (entries whose dependencies are all satisfied, plus newly-must-include crawl candidates that need scanning, plus relevant works that need work-reviews). But the walker doesn't run them — it surfaces them and asks a Claude session to launch the sub-agents.

Ready tasks include both **entry-writing** tasks (for newly-must-include candidates that need scanning, newly-relevant works that need work-reviews, etc.) and **suggester-pass** tasks (queued automatically when an entry-writing task completes). The two task types are dispatched the same way — the inbox carries them as a unified queue, ordered by the dependency graph.

Every "Fire ready tasks" dispatch also bundles the **standing whole-document tasks** for the current cycle (see `LITERATURE_REVIEW_FLOW.md` § Standing whole-document tasks): structural coherence, cluster-to-cluster flow, section flow within clusters, synthesis-claim coherence, coverage gaps, verbosity overview, accessibility flow, and narrative coherence. The standing tasks run every cycle regardless of which specific tasks are queued — even an empty specific-task queue still fires the standing pass, so the button is always meaningful in an in-progress iteration.

The dispatch prompt template has two sections: a *Standing tasks* block (templated boilerplate plus the artifact's current cluster list + accepted synthesis claims as context) and a *Specific tasks* block (the ready entries the walker computed). The session launches sub-agents for the specific tasks in parallel and a dedicated sub-agent for the standing-tasks pass; outputs land in the per-entry markdown for specific tasks, and in `CYCLE_REVIEW_<artifact>_iter<N>.md` for the standing pass.

**Mechanism.** A designated Claude session — typically the session that launched the walker, or one explicitly bound via a `--session-id` flag — listens for ready-task requests from the walker. Two viable transports:

- **Filesystem inbox.** Walker writes a `READY_TASKS_<artifact>.md` file with a structured request (one fenced block per task: artifact, phase, target entries, suggested agent prompt). A Claude-side `Monitor`-style polling loop (or a hook) reads the file, launches sub-agents per the existing parallelization conventions in `INITIAL_SCAN.md` / `WORK_REVIEW.md` / `CITATION_CRAWL.md`, writes back a `READY_TASKS_<artifact>.results.md` when each completes. Walker watches the results file and surfaces updates.
- **RemoteTrigger to existing session.** Walker uses Claude Code's `RemoteTrigger` (or equivalent) to send a structured prompt to the bound session. The session reads the prompt, launches sub-agents, returns results. Lower-latency than filesystem polling; tighter coupling.

The plan picks **filesystem inbox** as the default — it's robust, debuggable (the inbox file is itself a record of what was requested and when), and doesn't require live coupling between walker and session. The session can be any Claude Code instance the user has open, configured via a one-line hook to read the inbox path.

**UI surface.** At the top of every walker page, a **What's ready to run?** panel:
- shows the count of tasks newly unblocked by decisions made in the current session (e.g., "3 work-reviews ready, 8 scans ready, 1 crawl ready");
- shows the *target entries* for each ready task with click-through to inspect what will be acted on;
- shows the standing whole-document tasks that will also fire (always present, with a one-line description of each so the human knows what runs);
- has a **Fire ready tasks** button that writes the inbox file (with both specific and standing task blocks) and surfaces a confirmation.

A **Don't fire — hold for batch** mode lets the human accumulate accepted decisions for a batch fire later, useful when working through a cluster where firing per-entry would create thrash.

**Bidirectional surface.** When a sub-agent completes and the session writes its output back into the canonical markdown (`WORK_REVIEW_<artifact>.md`, etc.), the walker's "What's ready to run?" panel refreshes — the just-completed work-review's output becomes a new entry in the work-review walker, and its newly-produced synthesis claims become new pending entries in the synthesis walker. The decision graph extends as the session works.

**No execution in the walker process.** The walker never calls the Claude API or launches sub-agents itself. The session is responsible for execution; the walker is responsible for surfacing decisions and constructing well-formed requests. This keeps the walker's process model trivial (read markdown / write markdown / serve HTML) and pushes the live-coupling complexity into the session, which already has the right context to launch sub-agents.

Files: `templates/_ready_tasks.html` (panel partial included in every walker), `server.py` route `POST /fire-ready-tasks` (writes inbox file), `inbox.py` (request and result formats), `md_parser.compute_ready_tasks` (graph traversal). A companion `.claude/` hook documented in the plan tells the session how to watch the inbox.

### PR: Dashboard with convergence, funnel ratios, and synthesis blocking

Once the four walkers exist and write back decisions, the dashboard upgrades from a static index to a full status view:

- per-iteration funnel ratio chart (candidates → relevant → new candidates from crawl);
- per-iteration synthesis-claim production rate and pending-resolution rate;
- **convergence indicator** with two lights — *citation funnel converged* (zero new relevant last iteration) and *synthesis converged* (no `pending` claims). Both green = flow complete;
- **blocking-dependencies view** — top N pending claims by dependent-count, with quick-resolve buttons (most actionable backlog);
- count of pending human decisions per phase (unreviewed scan entries; unapplied rewrites; untriaged crawl candidates; pending synthesis claims) — the global backlog;
- per-artifact "ready to advance to next iteration" signal: all Phase 1 entries have human verdicts, all relevant entries have Phase 2 audits (including their synthesis-claim production), all Phase 3 candidates have triage decisions, all synthesis dependencies that gate further audits are resolved.

A claim being resolved on the dashboard's quick-resolve flow propagates to the synthesis walker and the audit walker's block-status display.

Files: dashboard route additions, parsing helpers, a small JS chart (single SVG, no library), quick-resolve endpoint.

### PR: Smoke-test on an existing audit doc

Validate the audit walker against `CITATION_AUDIT_USERMODEL_EXTENSION.md` — the largest existing audit. Walk through its Tier-1 entries, accept / reject the proposed rewrites, produce the rewrites file, apply to the source lit review as a single PR. This is the first real exercise of the tooling end-to-end and surfaces friction points before the from-scratch flow is run.

## Design decisions to validate before implementation

These are the choices baked into the plan above; flag any to revisit:

1. **Decision storage: inline HTML-comment annotations in the source markdown vs. sibling `*.decisions.md` files.** Plan picks inline annotations for scan + crawl (the decision is tightly coupled to the entry), sibling file for audit rewrites (the decisions are diffs against a different file), and a dedicated `SYNTHESIS_<artifact>.md` file for synthesis claims (their own first-class artifact). Alternative: sibling files for everything, keeping the source markdown pristine.
2. **Walker pagination granularity.** Plan picks one-entry-per-page for scan + audit Tier-1 + synthesis, list view for audit Tier-2 + crawl. Alternative: one-entry-per-page everywhere, paying the click cost for uniformity.
3. **Apply-rewrites flow.** Plan picks "collect decisions → produce unified diff → human reviews diff → commit." Alternative: direct write-through (each accepted rewrite immediately edits the source file). Direct write-through is faster but loses the diff-review gate.
4. **Auto-accept-then-display vs. always-prompt for low-risk claims.** Plan picks auto-accept per `SYNTHESIS.md` criteria (faithful + non-contradicting + structurally simple) with after-the-fact dashboard surfacing for human disagreement. Alternative: always-prompt, slower but with no chance of an auto-accept slipping past.
5. **Block strictness.** Plan picks hard block on pending/contested dependencies (dependent audits cannot proceed). Alternative: soft block (the audit can proceed with a "**Blocked by:** [claim-id]" warning baked in, to be resolved later). Hard block is safer; soft block is faster but creates a class of "claims-pinned" audits that need re-validation when claims resolve.
6. **Hotkeys.** Plan picks j/k for next/previous, a/r for accept/reject, m for modify, s for "show blocking claim." Alternative: 1–4 number keys for verdict selection.
7. **Server model.** Plan picks FastAPI single-file. Alternative: pure-stdlib `http.server` (zero dependencies) at the cost of more boilerplate per route.
8. **Suggester-pass independence.** Plan picks *separate suggester sub-agent* per `SUGGESTION_PASS.md` — the entry-writing and suggestion-writing passes run as independent agent invocations, mirroring the adversarial-review pattern. Alternative: *same-agent suggestion* (the entry-writing agent writes both content and suggestion in one pass), which is cheaper but suffers from self-confirmation bias. Separate sub-agent is the default. A per-entry **regenerate suggestion** button (later optional PR) re-fires the suggester pass on demand for entries the human has touched in ways the suggester should know about.
9. **Bulk-accept default scope.** Plan picks *current filter* (only entries matching the active filter get bulk-accepted) — safer than *whole document*. Alternative: whole document with a confirmation modal. The current-filter default makes the bulk path opt-in to the scope, which avoids the "I clicked the wrong button and accepted 80 things" footgun.
10. **Session-integration transport.** Plan picks filesystem inbox (`READY_TASKS_<artifact>.md` + `.results.md` files) as the default. Alternative: `RemoteTrigger` to a bound Claude Code session for lower-latency coupling. Filesystem is the default because it's debuggable, doesn't require live coupling, and the inbox is itself an audit record of what was requested. `RemoteTrigger` may be added later for users who want tighter coupling.
11. **Fire mode.** Plan picks an explicit *Fire ready tasks* button (human-triggered batch). Alternative: *auto-fire on accept* — every time a decision unblocks downstream work, the unblocked tasks fire immediately. Auto-fire is convenient but creates execution thrash and makes the audit trail harder to read (which decision caused which task). Explicit-fire is the default; auto-fire is an opt-in toggle.

## Non-goals

- Multi-user collaboration. Local-only, one human at a time.
- Persistent database. The markdown is the database.
- Replacing the pm TUI. The TUI is for PR / plan management; this tooling is for the lit review process and lives alongside it. They may eventually share a launcher pane, but the interfaces are independent.
- Rendering the eventual literature review prose. Phase 5 synthesis is by hand or by a separate prose agent; this tooling stops at producing the structured audit material.

## Sequencing note

PR 1 (skeleton) must land first. PRs 2–5 (scan walker, work-review walker with synthesis integration, crawl triage, synthesis-claim walker) can land in any order after the skeleton, though the work-review walker and synthesis walker share `md_writer.update_claim_status` so are easier to land together. PR 6 (cycle-review walker + general-comments surface) is independent of the per-entry walkers — its consumption is the per-cycle standing-task output and a free-form notes file. PR 7 (proposed-edits walker) depends on the work-review and synthesis walkers, since its provenance graph reaches into both. PR 8 (ready-task execution via Claude-session integration) depends on all walkers being able to compute ready-task graphs — including suggester-pass tasks for newly-written entries and the standing-tasks reviewer pass per cycle. PR 9 (dashboard upgrade with synthesis blocking + ready-task counts + cycle-review history) depends on PR 8. PR 10 (smoke test) is the final acceptance gate before the new flow is used for a real from-scratch literature review.

The work-review walker without synthesis integration is *not* a valid stopping point — the flow's correctness depends on the auto-accept / block gate being live. Either ship the work-review walker with synthesis or hold both for the same PR.

The walkers without the session-integration PR are still useful (the human can manually copy ready-task requests into a Claude session as prompts), but the value of the response-block / pre-fill / Blocking primitive compounds with session integration — each accepted decision can immediately propagate into actual sub-agent work, turning the walker into the throttle on the flow's overall pace.
