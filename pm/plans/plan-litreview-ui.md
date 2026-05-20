# Plan: Simple HTML Interfaces for the Literature Review Flow

The literature review flow (`pm/docs/adversarial-review/LITERATURE_REVIEW_FLOW.md`) produces structured markdown artifacts at each phase: initial-scan docs (Phase 1), audit docs (Phase 2), crawl-output docs (Phase 3). Walking those docs by eye works but doesn't scale — a moderately sized review can produce 150+ scan entries, 50+ Tier-1 audit entries, and several iterations of crawl output. Simple HTML interfaces let a human consume and intervene on each phase at speed, with the verdicts saved back into the markdown.

The interfaces are **tooling for the process**; the markdown stays canonical. The HTML reads the docs, surfaces the human-decision points, and writes the decisions back as structured annotations in the same docs (or as side files the next phase picks up).

## Design constraints

- **Simple.** Static HTML + a thin local Python server (FastAPI or Flask, single file). No build step, no framework, no database. The "state" lives in the markdown files.
- **Read-canonical, write-structured.** The interfaces never replace the markdown as the source of truth. Human decisions get appended as structured fenced blocks in the same file (e.g., `<!-- human-verdict: relevant; rationale: load-bearing for §3 -->`) or written to a sibling `*.decisions.md` file. The next-phase tooling reads those annotations.
- **One interface per phase.** Each phase has its own walker view, tuned to that phase's decision shape. Plus a dashboard tying them together.
- **Local-only.** Runs on `localhost:<port>`, started by a single `python -m pm.litreview_ui`. No auth, no deployment.
- **No JS framework.** Vanilla JS + a small CSS file. The pages are content-dense, mostly text and one or two action buttons per entry.

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

Per-entry view of a Phase 1 scan doc. Each entry shows the citation header (with the working link), the 1–2-sentence summary, the agent's verdict + rationale, and four buttons: **accept**, **override → relevant**, **override → partial**, **override → not relevant** (the last three also pop a text field for the overriding rationale).

Saves write a `<!-- human-verdict: ... -->` line under each entry. The Phase 2 / Phase 3 tooling reads `human-verdict` if present, otherwise falls back to the agent's verdict.

A "next-entry" hotkey (j/k or arrow keys) plus an "only show unreviewed" filter make 150-entry scans tractable.

Files: `templates/scan.html`, walker route in `server.py`, `md_parser.parse_scan_doc`, `md_writer.append_scan_verdict`.

### PR: Work-review walker (with synthesis-claim integration)

Per-entry view of a Phase 2 `WORK_REVIEW_<artifact>.md` doc — generative, not audit framing. (For the audit-mode walker on the four pre-flow audit docs, the same template renders against the existing `CITATION_AUDIT_*.md` files with the rewrite-acceptance flow.) Shows the citation header, doc passage, what the source actually says, verdict, proposed rewrite, **plus a "Synthesis claims produced" panel and a "Dependencies declared" panel** (see `SYNTHESIS.md`).

Buttons on the rewrite: **accept rewrite**, **reject**, **modify**.

Buttons on each produced claim:
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

Bulk-list view of a Phase 3 crawl doc. One row per surfaced candidate: title + link + the brief "why surfaced" note from the crawl. Three buttons per row: **feed to scan** (default), **skip — known stale**, **must-include**. Multi-select via checkbox + bulk action above the list.

Saves write a `<!-- human-triage: ... -->` line per candidate. The next iteration's Phase 1 scan only enqueues candidates marked feed-to-scan or must-include; skipped ones stay in the crawl doc with the rationale visible.

Files: `templates/crawl.html`, `md_parser.parse_crawl_doc`, `md_writer.append_crawl_triage`.

### PR: Synthesis-claim walker

Dedicated view of `SYNTHESIS_<artifact>.md`. List of claims, filterable by status (`pending` / `auto-accepted` / `human-accepted` / `contested` / `superseded`) and sortable by dependent-count.

Each claim row shows: id, claim text, supporting citations (with links), status, dependent count + dependents list (click-through to the dependent audit entries).

Per-claim actions mirror the audit walker's claim actions (accept / modify / reject / merge / split / contest). A claim being resolved here propagates to the audit walker's block-status display.

Pending claims sorted by dependent-count descending are the actionable backlog — resolving the most-depended-on claim first unblocks the most downstream work.

Files: `templates/synthesis.html`, `md_parser.parse_synthesis_doc`, `md_writer.update_claim_status` (shared with audit walker), `md_parser.compute_dependent_graph`.

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

## Non-goals

- Multi-user collaboration. Local-only, one human at a time.
- Persistent database. The markdown is the database.
- Replacing the pm TUI. The TUI is for PR / plan management; this tooling is for the lit review process and lives alongside it. They may eventually share a launcher pane, but the interfaces are independent.
- Rendering the eventual literature review prose. Phase 5 synthesis is by hand or by a separate prose agent; this tooling stops at producing the structured audit material.

## Sequencing note

PR 1 (skeleton) must land first. PRs 2–5 (scan walker, audit walker with synthesis integration, crawl triage, synthesis-claim walker) can land in any order after the skeleton, though the audit walker and synthesis walker share `md_writer.update_claim_status` so are easier to land together. PR 6 (dashboard upgrade with synthesis blocking) depends on all four walkers being able to write decisions. PR 7 (smoke test) is the final acceptance gate before the new flow is used for a real from-scratch literature review.

The audit walker without synthesis integration is *not* a valid stopping point — the flow's correctness depends on the auto-accept / block gate being live. Either ship the audit walker with synthesis or hold both for the same PR.
