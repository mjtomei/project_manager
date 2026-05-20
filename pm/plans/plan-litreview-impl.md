# Plan: Implement the Literature Review Flow + Walker UI

What we're really doing: **formalize the methodology we've been using in conversation** (now in `pm/docs/adversarial-review/LITERATURE_REVIEW_FLOW.md` and companion files) and **add a web interface for reviewing the files those sessions produce** — because the volume of generated material is now too much to walk by eye. The flow itself runs as a Claude session, the same way we've been running it in conversation throughout this design discussion. We're not building a new runner; we're building two CLI commands that launch sessions, a web UI that reads the files those sessions produce, and an inbox mechanism so the UI can send messages back to the running session.

## Integration shape

- **`pm litreview <target>`** — launches a fresh Claude Code session in a new tmux pane with the methodology files loaded as context. `<target>` is any file or topic string; the session reads the target, kicks off the iteration loop using its normal tool use (Bash / Edit / Write / Agent for parallel sub-agents), and produces the structured markdown artifacts under `pm/docs/adversarial-review/`. **Not plan-specific** — the litreview command treats any text as a candidate target. (It works on plans, but it works on anything else too.)
- **`pm plan session <plan>`** — launches a discussion session in a new pane within the plan's existing tmux window. Independent of litreview. The plans pane in the TUI gets a keybinding that triggers the same command. This is for the conversational mode of working on a plan — what we've been doing in this session — and is separable from any litreview work that may also be running on the plan's text.
- **`pm litreview ui [--port]`** — launches the web walker server. The server reads the markdown artifacts the session produces and renders the walker views per `plan-litreview-ui.md`.
- **UI → session messaging.** Every walker action that needs work done (Fire ready tasks, route-to-walker, regenerate suggestion, etc.) writes to an inbox file (`READY_TASKS_<artifact>.md`). The running litreview session is configured to watch the inbox and act on its contents using its normal tool use. The UI never spawns agents directly; the session does, because the session already has the right context.

The conversational workflow we've been using stays intact — you can keep talking to the session in the pane. The web UI is parallel surface for *consuming and reacting to* the files the session has generated, for the cases where the volume is more than fits in a chat scrollback.

## Where the work actually happens

- **The Claude session is the runner.** It reads the methodology files, the target artifact, and the in-progress state (the markdown files under `pm/docs/adversarial-review/`), and produces outputs through `Edit` / `Write` / `Agent` tool use. Sub-agent parallelism for batched scans, work-reviews, and crawls is done via the session's own `Agent` tool calls, exactly as we've been doing in this conversation.
- **Auto-run mode** is the human telling the session "run iterations autonomously until convergence" — no new control plane. The session loops via its own tool use, pausing only when a strict block fires.
- **The web UI is observer + messenger.** It reads files, renders walker views, writes human responses back into the response blocks, and writes UI-initiated work requests into the inbox.

This means the Python implementation is *much* smaller than a full runner — it's the CLI commands, the methodology-context-loader, the web UI, the markdown format primitives, and the inbox format.

## Architecture

```
pm/
  litreview/
    __init__.py
    md_parser.py       # response-block + interaction-log + per-doc parsers
    md_writer.py       # response-block writes, interaction-log appends
    inbox.py           # READY_TASKS_<artifact>.md read/write
    cli.py             # pm litreview {<target>, ui}
    context.py         # methodology-context loader for new sessions
    ui/
      server.py        # FastAPI single-file server
      templates/       # Jinja2 walker templates
      static/          # one CSS file, one JS file
  cli/
    plan.py            # pm plan session <plan>  (new plan subcommand)
  tui/
    plans_pane.py      # extended with launch-session keybinding (existing file)
```

State is **purely file-backed**: the markdown files under `pm/docs/adversarial-review/` are canonical for entries, responses, claims, interactions. There's no JSON state cache, no database. The dashboard re-parses on each load (cheap — moderate-sized reviews are a few hundred KB total).

## PRs

### PR 1: `pm plan session <plan>` + TUI keybinding

Smallest, independent PR. Lets you open a discussion session in a plan's window from the CLI or from the plans pane.

- `pm/cli/plan.py` — new `pm plan session <plan>` subcommand. Resolves the plan's tmux window from the existing pane-management code (per project memory: `_launch_pane()` with role-based deduplication), opens a new pane in that window running a fresh `claude` invocation. Role: `session`.
- `pm/tui/plans_pane.py` — new keybinding on the plans pane (default `s`) that invokes the same command for the selected plan.
- Tests: pane is created with the right role; keybinding routes correctly.

Dependencies: none. Ships independently of any litreview work.

### PR 2: `pm litreview <target>` + methodology context loader

The litreview command that launches a session with the right context.

- `pm/litreview/context.py` — builds the methodology context for a new session: concatenates `LITERATURE_REVIEW_FLOW.md`, `INITIAL_SCAN.md`, `WORK_REVIEW.md`, `CITATION_CRAWL.md`, `SYNTHESIS.md`, `SUGGESTION_PASS.md`, `CITATION_USE_AUDIT.md` (audit mode), and a target-artifact preamble. Output is a single prompt string with the framing instruction "you are running a literature review session on the target below; consult the companion methodology and produce the artifacts as described."
- `pm/litreview/cli.py` — `pm litreview <target>` subcommand. Opens a new tmux pane running `claude` with the context as initial input. Target accepts file paths or topic strings; if a path, the file content is included in the preamble; if a string, used as the topic seed for iteration-1 key-phrase derivation.
- Artifact-id derivation: file basename for file targets; a slugified prefix for string topics.
- Tests: context-build produces a valid prompt; file vs string target handled; pane launched in role `litreview`.

Dependencies: none (uses existing pane-management code).

### PR 3: Markdown format primitives + inbox file format

- `pm/litreview/md_parser.py` — response-block fenced-comment parser (suggested-* / human-* / status / interactions); per-doc parsers (initial-scan, work-review, crawl, synthesis, cycle-review, proposed-edits, notes); dependency-graph extraction from synthesis docs.
- `pm/litreview/md_writer.py` — atomic response-block updates (`update_response_block`), append-only interaction-log entries (`append_interaction`), append-only entry adds (`append_entry`). All writes go through these functions so format consistency is guaranteed.
- `pm/litreview/inbox.py` — `READY_TASKS_<artifact>.md` read/write with the two-block prompt format (standing-tasks + specific-tasks) per `plan-litreview-ui.md` § Ready-task execution. Also reads `READY_TASKS_<artifact>.results.md` for UI refresh.
- Tests: response-block round-trip; interaction-log append concurrency; dependency-graph extraction on fixture docs.

Dependencies: none. Ships the data layer the UI builds on.

### PR 4: Web server skeleton + read-only dashboard

- `pm/litreview/ui/server.py` — FastAPI single-file. File-discovery routes (list artifacts, list iteration docs per artifact). Dashboard route renders artifact list + iteration count + mode + funnel-ratio numbers + convergence two-lights. All read-only at this stage.
- `pm/litreview/ui/templates/dashboard.html`, `static/style.css`, `static/walker.js` — minimal scaffolding.
- CLI: `pm litreview ui [--port]` (added to `cli.py`).
- Tests: dashboard renders correctly against fixture markdown.

Dependencies: PR 3.

### PR 5: Walker primitive + initial-scan walker

- Shared rendering helpers in `pm/litreview/ui/md_views.py`: response-block field rendering, Blocking-view rendering, bulk-accept-per-filter, hotkeys, interaction-log writes (`viewed` with duration, `accept-as-suggested`, `bulk-accept` with scope, `edit`, `comment-added`, `skip`, `reopen`, `auto-accepted` badging).
- `templates/scan.html` — initial-scan walker per `plan-litreview-ui.md`.
- Filter set: `un-acted`, `auto-accepted-never-viewed`, `edited`, `low-confidence-suggester`, `by-cluster`.
- Tests: walker renders fixture scan doc; response-block edits round-trip; interaction log appends correctly.

Dependencies: PR 3, PR 4.

### PR 6: Work-review walker (with audit-mode preservation)

- `templates/work_review.html` — work-review walker with synthesis-claim panel, dependencies panel, block-status indicator.
- Audit-mode: when the target file matches `CITATION_AUDIT_*.md`, the same template renders the rewrite-acceptance variant. Both the four existing pre-flow audits and any new work-reviews use this walker.
- Tests: walker renders `CITATION_AUDIT_REGRESSION.md` (existing fixture) with audit-mode buttons; walker renders a fixture work-review doc with synthesis-claim panel; mode auto-detection works.

Dependencies: PR 5.

### PR 7: Crawl-triage + synthesis-claim walkers

Two thin walkers sharing the primitive.

- `templates/crawl.html` — bulk-list view with per-row response blocks, multi-select bulk-tag.
- `templates/synthesis.html` — claim list with dependent-count sort, status filters, per-claim resolution actions.
- Tests: each renders fixture docs; resolution actions update both the claim status and the dependency graph in the markdown.

Dependencies: PR 5.

### PR 8: Cycle-review walker + general-comments surface

- `templates/cycle_review.html` — per-cycle standing-task responses with route-to-walker buttons + iteration-history sidebar.
- `templates/notes_pane.html` — collapsible side panel included in all walker pages. Reads/writes `NOTES_<artifact>.md`.
- Tests: cycle-review walker renders standing-pass output; notes-pane round-trips edits.

Dependencies: PR 5.

### PR 9: Proposed-edits walker

- `templates/edits.html` — diff view (inline word-level) with before/after, *Why this edit?* provenance with click-through links, response block.
- Provenance graph (`md_parser.compute_edit_provenance`) traverses from work-review draft prose, synthesis-claim implications, and audit-mode rewrites back to originating entries.
- Apply flow: accepted edits → `EDITS_<artifact>.applied.md` → produces unified diff for review-before-commit.
- Conflict detection on overlapping line ranges blocks apply.
- Tests: walker renders fixture proposed-edits; provenance click-through resolves; apply produces a valid diff; overlap detection blocks correctly.

Dependencies: PR 6, PR 7.

### PR 10: UI → session inbox messaging (Fire ready tasks)

The wire between walker actions and the running session.

- "What's ready to run?" panel partial included in every walker (per `plan-litreview-ui.md`); shows specific tasks + standing tasks.
- `POST /fire-ready-tasks` endpoint writes a structured request to `READY_TASKS_<artifact>.md` (two-block format).
- `walker.js` polls `READY_TASKS_<artifact>.results.md` for updates and refreshes the walker when new entries land.
- **Session-side hook**: a small `pm/docs/adversarial-review/litreview-session-hook.md` documenting what the running litreview session must do — watch the inbox, parse the two blocks, dispatch the appropriate sub-agents (scan / work-review / crawl / standing pass per the methodology), write results back into the canonical markdown, signal completion via `results.md`. The session is responsible for execution because it has the right context; the UI just queues work.
- Tests: inbox round-trip; ready-task graph traversal on fixture state.

Dependencies: PR 5–9.

### PR 11: Dashboard upgrade — convergence, funnel, blocking, engagement signals

- Dashboard expanded with: per-iteration mode + funnel-ratio chart (single SVG, no library); convergence two-lights (citation funnel + synthesis); blocking-dependencies view (top-N pending claims by dependent-count with quick-resolve buttons); pending-decisions backlog per phase; engagement signals (bulk-accept ratio + median view-time per cycle for human-reviewed iterations, suggester-confidence distribution for auto-run cycles).
- Tests: dashboard returns expected aggregates for a fixture multi-iteration state.

Dependencies: PR 10.

### PR 12: End-to-end smoke validation (the auto-runnable target)

The final-acceptance PR. Safe to launch as a long-running auto-run from pm.

Three validation paths, run in order:

1. **CLI launch smoke.** `pm litreview <some-test-file>` opens a pane with a session that has the methodology context. Verify the pane is created, the session has the right framing, the artifact-id is correct.
2. **Walker rendering smoke.** Run `pm litreview ui` against the four existing pre-flow audit docs (`CITATION_AUDIT_*.md`) — the audit-mode work-review walker should render them with no errors. This validates the walker against real, large, structured artifacts that already exist.
3. **End-to-end session run** (manual or semi-automated). On a fresh test file (a small markdown document with 5–10 citations is sufficient — the smoke test isn't validating literature review *quality*, just integration), launch a litreview session, instruct it to run auto-permissively until convergence with `--max-iterations 3`. Verify:
   - `INITIAL_SCAN_*.md`, `WORK_REVIEW_*.md`, `CRAWL_*.md`, `SYNTHESIS_*.md`, `CYCLE_REVIEW_*.md` all appear.
   - Every response block has `status: auto-accepted` and a matching `interactions:` entry.
   - The dashboard's convergence two-lights turn green within the iteration budget.
   - The walker renders every produced file without errors.
   - The Fire-ready-tasks endpoint writes a valid inbox file.

This PR is **idempotent and re-runnable** — re-running validates that the existing artifact state still parses and renders correctly after any incremental changes.

Acceptance criteria:
- All three validation paths pass.
- Walker renders every existing `CITATION_AUDIT_*.md` correctly (no audit-mode regressions on the four pre-flow audits).
- Smoke-test artifact converges within 3 iterations.
- No critical findings in the smoke run's final cycle review.

Dependencies: PR 1 through PR 11.

## Sequencing

PR 1 and PR 2 are independent of each other and of PR 3+ (they're just CLI / pane work). They can land first in any order.

PRs 3–11 are the web UI track. PR 3 (data layer) is foundational; PR 4 (server skeleton) builds on PR 3; PRs 5–9 (walkers) build on PR 4; PR 10 (inbox messaging) requires PRs 5–9; PR 11 (dashboard upgrade) requires PR 10.

PR 12 (smoke test) requires everything.

Reasonable parallel-friendly path: PR 1 + PR 2 + PR 3 in parallel (three independent surfaces); then PR 4; then PRs 5–9 in parallel (different walker templates, mostly independent); then PR 10 + PR 11 + PR 12 serially.

## Why this is small

The previous draft of this plan was 15 PRs covering a full Python runner that drove the iteration loop. That was the wrong shape — the iteration loop is already happening in our conversation here, mediated by Claude's tool use, and the methodology files have formalized it. The Python implementation just needs the CLI commands, the file-format primitives, the web UI, and the inbox wire. Everything else lives in the methodology and the session.

## Non-goals

- A Python iteration runner. The Claude session is the runner. There's no `pm litreview run --auto` Python command; auto-run is the human telling the session to loop.
- Multi-user collaboration. Single user, local-only.
- Persistent database. Markdown is the database.
- Replacing the four existing pre-flow `CITATION_AUDIT_*.md` audits. The work-review walker's audit mode renders them as-is.

## Open questions to validate during PR 1 or PR 2

1. **Pane role naming.** Plan picks role `session` for `pm plan session` and role `litreview` for `pm litreview`. Verify these don't collide with existing roles in `_launch_pane()`.
2. **Methodology-context preamble shape.** Plan picks "concatenate the methodology files + a target preamble + a framing instruction." Alternative: pre-build a single distilled `LITREVIEW_PROMPT.md` that summarizes the methodology, faster for the session to read but easier to drift out of sync.
3. **Inbox transport stability.** Plan picks the filesystem inbox over `RemoteTrigger`. If the running session sometimes misses inbox updates, fall back is documented in PR 10.
