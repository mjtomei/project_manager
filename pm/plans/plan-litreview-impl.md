# Plan: Implement the Literature Review Flow + Walker UI

Implementation plan for the methodology in `pm/docs/adversarial-review/LITERATURE_REVIEW_FLOW.md` and the walker design in `pm/plans/plan-litreview-ui.md`. The end state: a `pm litreview` subcommand that takes any pm plan file (e.g., `pm/plans/plan-regression.md`) and produces a literature review for that plan, runnable fully automatically or with walker-mediated human review at any point.

The final PR is the end-to-end auto-run smoke test on a real plan, intended to be safe to launch as a long-running auto-run from pm itself.

## Integration shape

- **Input:** a pm plan file. The plan's content (PR descriptions, design rationale, prose body) is what Phase 3's key-phrase derivation seeds the iteration-1 candidate set from.
- **Output:** `pm/docs/literature-review-<plan-id>.md`, the assembled lit review for that plan. Plus the full set of process artifacts (`INITIAL_SCAN_*.md`, `WORK_REVIEW_*.md`, `CRAWL_*.md`, `SYNTHESIS_*.md`, `CYCLE_REVIEW_*.md`, `NOTES_*.md`, `READY_TASKS_*.md`) under `pm/docs/adversarial-review/`.
- **CLI surface:**
  - `pm litreview start <plan-file>` — initialize the artifact, register it with pm's project state.
  - `pm litreview run <plan-file> [--auto] [--strict] [--max-iterations N]` — drive the iteration loop. `--auto` is auto-run mode (default); without it, the runner stops at the first human gate and surfaces the URL of the walker.
  - `pm litreview ui [--port]` — start the walker server pointing at the current artifact state.
- **pm integration:** the runner registers itself as a PR-style workunit so pm's watchers can pick it up. Auto-run iterations complete one at a time so progress is visible in `pm status`.

## Architecture

```
pm/
  litreview/
    __init__.py
    state.py            # artifact / iteration / mode state, JSON-backed
    md_parser.py        # response-block + interaction-log + per-doc parsers
    md_writer.py        # response-block writes, interaction-log appends, doc appends
    agents/
      scan.py           # Phase 1 — initial-scan agent dispatch + result parsing
      work_review.py    # Phase 2 — work-review agent dispatch (Tier 1 / Tier 2)
      crawl.py          # Phase 3 — citation-crawl agent dispatch
      synthesis.py      # synthesis-claim tracking + dependency graph + auto-accept gate
      suggester.py      # suggester sub-agent dispatch (per-entry + standing-block variant)
      standing.py       # standing whole-doc reviewer dispatch
      assembly.py       # Phase 5 — assemble lit review from synthesis claims + work-reviews
    runner.py           # iteration driver, auto-run loop, convergence detection
    ui/
      server.py         # FastAPI single-file server, mounts all walker routes
      md_views.py       # per-doc walker render helpers
      templates/        # Jinja2 templates per walker
      static/           # one CSS file, one JS file
    cli.py              # pm-litreview subcommand entrypoints
```

State lives in two layers:
- **Markdown** (`pm/docs/adversarial-review/*.md`) is canonical for entries, responses, claims, interactions. The runner and the UI both read and write here.
- **JSON state** (`pm/docs/adversarial-review/.state/<artifact>.json`) is a derived index — iteration count, mode, per-iteration funnel ratios, dependency graph cache. Rebuilt from the markdown if missing. Lets the dashboard render fast without re-parsing everything.

## PRs

### PR 1: Foundations — md format, interaction log, state, CLI skeleton

Stand up `pm/litreview/` with the data-layer primitives.

- `state.py` — JSON-backed artifact + iteration + mode tracking. Auto-rebuild from markdown if absent.
- `md_parser.py` — parsers for the response-block fenced HTML comment (with `suggested-*` / `human-*` / `status` / `interactions:` fields), the doc-level parsers (scan, work-review, crawl, synthesis, cycle-review entries), and the dependency-graph extraction.
- `md_writer.py` — atomic appends to markdown (response-block updates, interaction-log appends, doc appends with iteration markers). All writes go through a single `update_response_block` / `append_interaction` / `append_entry` API so the format is consistent.
- `cli.py` — `pm litreview start <plan-file>` that initializes the artifact (creates the state file, picks the artifact id from the plan filename, prints the next-step command).
- Tests: response-block round-trip, interaction-log append concurrency, state-rebuild-from-markdown.

Dependencies: none. Ships the data layer the rest of the plan builds on.

### PR 2: Phase 1 agent — initial scan + suggester pass

- `agents/scan.py` — scan-agent dispatch. Takes a list of candidate works + the plan text + the relevance criteria; spawns one agent per chunk of 10–20 candidates; writes scan entries into `INITIAL_SCAN_<artifact>_iter<N>.md` per `INITIAL_SCAN.md` methodology.
- `agents/suggester.py` — generic suggester-pass dispatch (per `SUGGESTION_PASS.md`). After a scan agent completes, fires a separate suggester sub-agent against each entry to populate the response block's `suggested-*` fields. Carries the skeptical disposition prompt verbatim.
- Tests: fixture-driven scan over a known-small candidate set, golden-file response-block content.

Dependencies: PR 1.

### PR 3: Phase 2 agent — work-review + synthesis tracking + suggester pass

- `agents/work_review.py` — work-review-agent dispatch. For each Phase-1 *relevant* / *partially relevant* entry, fires a deep-read (Tier 1) or abstract-level (Tier 2) agent per `WORK_REVIEW.md`. Output entries carry the full per-work entry shape including target-audience notes, proposed cuts/downgrades, synthesis-claim production, dependency declarations.
- `agents/synthesis.py` — synthesis-claim tracking. Reads work-review output for claim production blocks; appends to `SYNTHESIS_<artifact>.md`; computes the dependency graph; applies the auto-accept / block gate per `SYNTHESIS.md`.
- Suggester pass integrated — per-entry suggester after each work-review completes.
- Tests: work-review against a fixture work (a known-shape arXiv abstract + intro + conclusion), synthesis-claim production parsing, auto-accept-vs-block gate decision on synthetic claim sequences.

Dependencies: PR 1, PR 2.

### PR 4: Phase 3 agent — citation crawl + suggester pass

- `agents/crawl.py` — crawl-agent dispatch. For each Phase-2 *relevant* work, fires a sub-agent that walks Google Scholar forward + backward at the configured depth, derives 3–5 key phrases, runs the non-academic key-phrase searches per `CITATION_CRAWL.md`. Writes `CRAWL_<artifact>_iter<N>.md` with the coverage section.
- Iteration-1 seed handling: when the plan has no inline references, run the key-phrase derivation directly on the plan text to produce the iteration-1 candidate set.
- Suggester pass produces triage suggestions per candidate (feed-to-scan / skip / must-include).
- Tests: crawl against a fixture seed paper (cached Scholar response), key-phrase derivation produces specific-not-generic phrases.

Dependencies: PR 1, PR 2.

### PR 5: Standing whole-doc reviewer pass

- `agents/standing.py` — standing-reviewer dispatch. Fires a single sub-agent per cycle that reads the artifact's current state (all work-reviews, synthesis claims, the assembled draft so far, the notes file, the interaction-log aggregates) and answers the eight standing whole-document tasks in one pass per `LITERATURE_REVIEW_FLOW.md` § Standing whole-document tasks. Output is `CYCLE_REVIEW_<artifact>_iter<N>.md`.
- Reviewer carries the skeptical disposition (per `SUGGESTION_PASS.md`).
- Mode-adaptive prompting (auto-run vs human-reviewed) per `plan-litreview-ui.md` § Auto-run mode.
- Tests: standing pass against a fixture mid-iteration state, mode-conditional prompt branches.

Dependencies: PR 1, PR 3.

### PR 6: Iteration driver + auto-run mode + convergence detection + Phase 5 assembly

- `runner.py` — the iteration loop. Sequences Phase 1 → Phase 2 (with interleaved synthesis) → Phase 3 → standing pass; checks convergence (citation funnel empty + all synthesis claims terminal); produces Phase 5 assembly when converged.
- Auto-run mode: applies suggester suggestions automatically per the permissive/strict policy, fires downstream ready tasks immediately.
- `agents/assembly.py` — Phase 5 assembly: reads accepted synthesis claims + their supporting work-reviews; composes the lit review prose using each work-review's `draft prose` + target-audience notes; outputs `pm/docs/literature-review-<plan-id>.md`.
- CLI: `pm litreview run <plan-file> [--auto] [--strict] [--max-iterations N]`. Default `--auto --permissive`. Without `--auto`, the runner stops at the first human gate and prints the walker URL.
- Tests: small synthetic plan + cached agent responses run to convergence in ≤3 iterations producing a valid output; mode toggles applied correctly per iteration.

Dependencies: PR 2, PR 3, PR 4, PR 5.

### PR 7: Web server skeleton + dashboard (read-only)

- `ui/server.py` — FastAPI single-file. Routes for file discovery, dashboard, per-walker stubs (return 501 until implemented).
- `ui/templates/dashboard.html` — list artifacts, iteration count + mode, funnel-ratio numbers, convergence indicator (two lights: citation funnel + synthesis). All read-only at this stage.
- `ui/static/style.css`, `ui/static/walker.js` — minimal CSS + vanilla JS (no framework).
- CLI: `pm litreview ui [--port]` starts the server bound to the current artifact state.
- Tests: dashboard route returns the expected counts for a fixture artifact state.

Dependencies: PR 1.

### PR 8: Walker primitive + initial-scan walker

- `ui/md_views.py` — shared walker rendering: response-block field rendering, Blocking-view rendering, bulk-accept-per-filter, hotkeys, interaction-log writes (`viewed` with duration, `accept-as-suggested`, `bulk-accept` with scope, `edit`, `comment-added`, `skip`, `reopen`).
- `ui/templates/scan.html` — initial-scan walker per `plan-litreview-ui.md`.
- Filter set: `un-acted`, `auto-accepted-never-viewed`, `edited`, `low-confidence-suggester`, `by-cluster`.
- Tests: walker route renders a fixture scan doc; response-block edits round-trip back to markdown; interaction log appends correctly.

Dependencies: PR 2 (for scan doc to render), PR 7.

### PR 9: Work-review walker + audit-mode (preserves CITATION_AUDIT_*.md)

- `ui/templates/work_review.html` — work-review walker with synthesis-claim panel, dependencies panel, block-status indicator. Per `plan-litreview-ui.md`.
- Audit-mode rendering: when pointed at a `CITATION_AUDIT_*.md` file (existing pre-flow audits), the same template renders the rewrite-acceptance variant of the entry shape. Both the four existing audits and any new work-reviews use the same walker.
- Tests: walker renders `CITATION_AUDIT_REGRESSION.md` (existing fixture) correctly with audit-mode buttons; walker renders a fixture work-review doc with synthesis-claim panel.

Dependencies: PR 3, PR 8.

### PR 10: Crawl-triage walker + synthesis-claim walker

Two thin walkers sharing the primitive from PR 8.

- `ui/templates/crawl.html` — bulk-list view with per-row response blocks; bulk-tag with multi-select.
- `ui/templates/synthesis.html` — claim list with dependent-count sort, status filters, per-claim resolution actions (accept / modify / reject / merge / split / contest).
- Tests: each walker renders fixture docs; resolution actions update both the claim status and the dependency graph.

Dependencies: PR 4 (crawl), PR 3 (synthesis), PR 8.

### PR 11: Cycle-review walker + general-comments surface

- `ui/templates/cycle_review.html` — per-cycle standing-task responses with route-to-walker buttons + iteration-history sidebar.
- `ui/templates/notes_pane.html` — collapsible side panel included in all walker pages. Reads/writes `NOTES_<artifact>.md` with section-tagged entries and timestamps.
- Notes file is loaded into the standing-reviewer context (per PR 5) so the human's general comments shape what the next cycle's reviewer attends to.
- Tests: cycle-review walker renders standing-pass output correctly; notes-pane round-trips edits; notes file loads into standing-pass prompt fixture.

Dependencies: PR 5, PR 8.

### PR 12: Proposed-edits walker

- `ui/templates/edits.html` — diff view (inline word-level) with before/after, *Why this edit?* provenance section with click-through links, response block.
- Provenance graph (`md_parser.compute_edit_provenance`) traverses from work-review draft prose, synthesis-claim prose implications, and audit-mode rewrites back to the originating entries.
- Apply flow: accepted edits → `EDITS_<artifact>.applied.md` → `apply-edits` CLI produces unified diff with provenance preserved in commit-message body.
- Conflict detection on overlapping line ranges blocks apply.
- Tests: edits walker renders fixture proposed-edits; provenance click-through resolves; apply produces a valid diff; overlap detection blocks correctly.

Dependencies: PR 9, PR 10.

### PR 13: Ready-task execution + Claude-session integration

- `ui/inbox.py` — `READY_TASKS_<artifact>.md` writer with the two-block prompt format (standing-tasks block + specific-tasks block) per `plan-litreview-ui.md` § Ready-task execution.
- "What's ready to run?" panel partial included in every walker; "Fire ready tasks" endpoint writes the inbox file.
- `ui/static/walker.js` polls for `READY_TASKS_<artifact>.results.md` updates and refreshes the walker when new entries land.
- Session-side hook documented in a small `.claude/litreview-session-hook.md` file: instructions for the Claude session that watches the inbox to launch sub-agents per the existing parallelization conventions (`INITIAL_SCAN.md`, `WORK_REVIEW.md`, `CITATION_CRAWL.md`).
- Tests: inbox file format round-trip; ready-task graph traversal on fixture state; auto-fire-on-accept mode toggle.

Dependencies: PR 8 through PR 12.

### PR 14: Dashboard upgrade — convergence, funnel, blocking, interaction signals

- Dashboard route expanded to show: per-iteration mode + funnel ratio chart (single SVG, no library); convergence two-lights (citation funnel + synthesis); blocking-dependencies view (top-N pending claims by dependent-count with quick-resolve buttons); pending-decisions backlog per phase; engagement signals (bulk-accept ratio + median view-time per cycle, suggester-confidence distribution for auto-run cycles).
- Tests: dashboard route returns expected aggregates for a fixture multi-iteration state.

Dependencies: PR 13.

### PR 15: End-to-end auto-run smoke test on a real plan (the auto-run target)

The final-acceptance PR. This is what you set pm to auto-run.

The PR's work:

1. Pick a real plan (default: `pm/plans/plan-regression.md`; CLI flag to override).
2. Run `pm litreview start <plan-file>`.
3. Run `pm litreview run <plan-file> --auto --permissive --max-iterations 5`.
4. Verify the convergence signal fires within the iteration budget.
5. Verify the output:
   - `pm/docs/literature-review-<plan-id>.md` exists and parses as a valid markdown document with the expected section structure (per-cluster organization, citation table, references list).
   - Every cited work has a corresponding work-review entry.
   - The interaction log shows mode `auto-run-permissive` across all iterations.
   - The synthesis doc has zero `pending` claims.
   - The standing-reviewer flagged no critical findings on the final cycle.
6. Open the walker; verify auto-accepted-never-viewed filter shows the expected count; verify the dashboard's convergence two-lights are green.
7. Commit the result and the process artifacts.

This PR is **idempotent and re-runnable** — running it again on the same plan reuses the existing artifact state, picks up at the latest iteration, and produces an updated output if any new candidates surface.

Acceptance criteria:
- Convergence reached within 5 iterations on `plan-regression.md`.
- Output lit review is between 4k and 12k words (the per-work cut-and-downgrade discipline keeps growth in check).
- Standing reviewer's final-cycle output has no findings flagged `low-confidence` *or* `load-bearing-unresolved`.
- All process artifacts present and walker-renderable.

Dependencies: PR 1 through PR 14.

## Sequencing

PR 1 must land first; PRs 2–5 can land in parallel after PR 1; PR 6 needs 2–5; PR 7 needs 1; PR 8 needs 2 + 7; PR 9 needs 3 + 8; PRs 10 and 11 need 8 + their data-layer PR; PR 12 needs 9 + 10; PR 13 needs 8–12; PR 14 needs 13; PR 15 needs everything.

A reasonable serial path for a single implementer: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15. Each PR is reviewable as a self-contained unit; the test suite at each PR validates the slice it ships.

A parallelizable path: PR 1; then PRs 2/3/4/5 in parallel (different data flows); PR 6 (integrates 2–5); PR 7; PR 8; PRs 9/10/11 in parallel (different walkers); PR 12; PR 13; PR 14; PR 15.

## Non-goals

- Multi-user collaboration. Single user, local-only.
- Persistent database. JSON state + markdown is the database.
- Integration into pm's TUI. The walker is a separate web UI; the TUI is for PR / plan management.
- Replacing the four existing pre-flow `CITATION_AUDIT_*.md` audits. Those keep their existing structure and are renderable in the work-review walker's audit mode.
- Phase 5 prose adversarial-review cycle (existing `METHODOLOGY.md`). Optional after-the-fact prose pass; not part of this implementation's scope.

## Open questions to validate during PR 1

These are choices the methodology files don't pin down — flag any to revisit before implementation:

1. **State file location.** Plan picks `pm/docs/adversarial-review/.state/<artifact>.json`. Alternative: under `pm/litreview/state/` (closer to the code).
2. **Artifact id derivation.** Plan picks the plan filename stem (e.g., `plan-regression` → artifact id `regression`). Alternative: a UUID or git-hash-based id for plans that get renamed.
3. **Sub-agent dispatch transport.** Plan picks the Agent tool's existing sub-agent mechanism, dispatched from the runner directly. Alternative: write to the inbox file and let an external Claude session pick it up (decouples implementation from session). The inbox transport is in PR 13 for walker-initiated dispatch; the runner's auto-run dispatch could use either. Default: runner uses direct dispatch in auto-run; walker uses inbox.
4. **Re-run idempotency on PR 15.** Plan picks "re-run picks up at latest iteration." Alternative: clean-slate re-run with a flag. Idempotent default keeps the artifact state stable across reruns; the flag lets the smoke-test detect regressions.
