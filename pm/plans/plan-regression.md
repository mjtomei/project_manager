# Automated Regression and Bug Fix Loop

Establish a continuous quality improvement loop where a Claude-based regression test surfaces both bugs and improvements, fixes are implemented in two parallel autonomous flows, and humans observe via a chat-driven review session rather than poking at the loops directly.

## Goals

- Reduce manual effort in finding and fixing regressions and UX issues
- Ensure findings discovered during review/QA don't get lost
- Enforce a disciplined reproduce-first bug fix flow
- Give humans a conversational surface for checking in on the autonomous loops

## Reuse: existing QA infrastructure

The autonomous loops drive the same Claude-based regression tests a human runs from the QA pane — not parallel infrastructure, not a new test runner.

- **Test list**: `pm/qa/regression/*.md`. Each test is a markdown file with YAML frontmatter and a body that already contains its prompt for the Claude session it spawns. Loaded by `qa_instructions.list_all()` (`pm_core/qa_instructions.py`).
- **Launch path**: `launch_qa_item()` (`pm_core/tui/pane_ops.py`) wraps the markdown body with session context and spawns Claude via `build_claude_shell_cmd()`. The QA pane's Enter key invokes this for human launches.
- **Verdict collection**: existing `poll_for_verdict()` (`pm_core/loop_shared.py`) and `extract_verdict_from_transcript()` (`pm_core/verdict_transcript.py`). PASS / NEEDS_WORK / INPUT_REQUIRED parsing is unchanged.
- **Status surface**: per-session transcript files plus the supervisor's own work log. Implementation watchers and the watcher review session read these directly — same surface a human watches.

What this plan adds:
- A small prompt addendum at the launch-path layer that teaches the spawned regression-test sessions to file bugs (`plan=bugs`) and improvements (`plan=ux`) when they discover them — analogous to `pr-539110b` for review/QA agents.
- A `target_window` option on `launch_qa_item()` so watcher-driven launches stay in the watcher's pane while human launches keep their current main-window behavior.
- The autonomous machinery (scheduling with throughput limits, post-hoc dedup, prioritization, work-log, dynamic priority).

What this plan does **not** add:
- New worker prompts (existing test markdown bodies stay as-is).
- A new test execution path (the existing `launch_qa_item()` flow is reused).
- New verdict shapes or IPC surfaces.

## Architecture

**Three watchers** total:

1. **Discovery supervisor** (`pr-271cb3a`) — schedules runs of the existing Claude-based regression tests at `pm/qa/regression/*.md` with throughput constraints. The test sessions themselves discover and file bugs/improvements directly via `pm pr add` (taught by `pr-47940bc`); the supervisor reconciles the filed PRs post-hoc (dedup, prioritize, route confirmation), maintains the work-log, and handles stuck/crashed test sessions.
2. **Bug-fix implementation watcher** (`pr-e3a711c`) — supervises the bug-fix pool's execution. Health checks, dynamic priority, implementation metrics, throttle.
3. **Improvement-fix implementation watcher** (`pr-d39a7fb`) — same shape as the bug-fix watcher, but for the UX pool. Separate watcher because flow-specific signals (taste-driven, gated merge) justify independent tuning.

**No discovery worker.** The existing test list is the discovery surface; each test already spawns its own Claude session through `launch_qa_item()`. This plan adds a prompt addendum (`pr-47940bc`) and a target-window option (`pr-97ddabf`); it does not introduce a new worker.

**Pools** (two parallel) — `pr-ea3c851` (bug-fix, auto-merge on) and `pr-84e6510` (UX, merge-gated). Generic execution layer; reads priority but doesn't set it.

**Human surface** — `pr-e84b43c`, a Claude session launched from the TUI that has read access to all three watchers' work-logs. Opens with a summary of recent activity, then chat-driven for follow-ups and remediation (priority bumps, pool pause/resume) with explicit confirmation for writes.

## Status

- ✅ Merged (2): `pr-3b2847c` (QA planner consolidate), `pr-539110b` (agents file out-of-scope bugs)
- 🔨 In progress (1): `pr-30588a7` (bug fix flow reproduce-fix-verify)
- ⏳ Pending (11): everything else
- Phase 1 is mostly done; the auto-sequence button (`pr-e58459b`) and auto-pool (`pr-45db518`) are the next foundation pieces to start. Phase 2+ unblocks once foundations land.

## Prerequisites

- Watcher framework (`pr-3032fb6`, merged)

## Phase 1: Foundation (independent, can start now)

### PR: QA planner: consolidate related assertions into fewer scenarios ✅ MERGED (#167)
`pr-3b2847c`

Prompt-only change to reduce scenario count by grouping related assertions. Unblocks faster QA runs which makes the whole loop more practical.

### PR: Review and QA agents file bugs for out-of-scope issues via pm pr add ✅ MERGED (#168)
`pr-539110b`

Teach review and QA agents to use `pm pr add --plan bugs` when they spot issues outside the current PR's scope. No verdict changes — agents still PASS/NEEDS_WORK on the PR itself, but file bugs as a side effect.

### PR: Bug fix flow: reproduce with test, fix, verify 🔨 IN PROGRESS (#169)
`pr-30588a7`

Different impl prompt for bug PRs: write a failing test first, fix the code, verify the test passes. Reviewers check that a reproduction test exists. Session-end reconcile is verification-only — primary dedup is owned by the discovery supervisor (post-hoc, after test sessions file).

### PR: Auto-sequence button: chain start → review → QA on a single PR
`pr-e58459b`

TUI keypress that chains start → done (review) → qa loop on one PR, halting at existing pause conditions and stopping before merge. Shared primitive used by both autonomous tracks.

### PR: Auto-pool executor: rate-limited PR queue with prioritization
`pr-45db518` (depends on: pr-e58459b)

Foundational queue primitive consumed by every autonomous track. Watches a configurable PR source, drives selected PRs through the auto-sequence chain under a rate limit, orders by per-PR `priority`. Auto-merge mode is per-pool. Priority is set by the discovery supervisor and the implementation watchers; the pool itself is agnostic.

## Phase 2: Discovery (after Phase 1)

### PR: Regression test sessions file bugs and improvements into correct plans
`pr-47940bc` (depends on: pr-539110b)

Prompt-addendum change at the launch-path wrapper in `launch_qa_item()` so the existing Claude-based regression test sessions know to file findings via `pm pr add --plan bugs` or `--plan ux`. Mirror of pr-539110b but for regression tests instead of review/QA agents. Verdicts (PASS/NEEDS_WORK/INPUT_REQUIRED) unchanged — filing is a side effect.

### PR: Watcher-target window for regression test launches
`pr-97ddabf` (depends on: pr-47940bc)

Add an optional `target_window` parameter to `launch_qa_item()` so watcher-driven launches stay in the watcher's pane and human launches from the QA pane keep their current main-window behavior.

### PR: Discovery supervisor watcher (unified for bugs and improvements)
`pr-271cb3a` (depends on: pr-47940bc, pr-97ddabf, pr-45db518)

Drives the existing test list at `pm/qa/regression/*.md` directly via `qa_instructions.list_all()` and `launch_qa_item()`. Owns scheduling with throughput constraints, post-hoc dedup of bug/improvement PRs the test sessions filed, priority assignment, structured work-log, and exception handling. No new worker, no new prompt — just a scheduler over an existing list.

## Phase 3: Pool configurations (after Phase 1)

### PR: Bug-fix pool config (auto-merge on)
`pr-ea3c851` (depends on: pr-30588a7, pr-47940bc, pr-45db518)

Pool config: source = `plan=bugs`, auto-merge on. Picks up bug PRs filed by the regression test sessions (and curated by the discovery supervisor) and runs them through the bug-fix flow.

### PR: UX pool config (merge-gated)
`pr-84e6510` (depends on: pr-47940bc, pr-45db518)

Pool config: source = `plan=ux`, auto-merge gated. UX PRs auto-sequence to ready-for-merge then wait for a human taste check.

## Phase 4: Implementation watchers (after Phase 3)

### PR: Bug-fix implementation watcher
`pr-e3a711c` (depends on: pr-45db518, pr-ea3c851)

Supervises the bug-fix pool's execution: stuck/crashed sessions, repeated NEEDS_WORK, reproduce-step failures, dynamic priority, implementation metrics, throttle.

### PR: Improvement-fix implementation watcher
`pr-d39a7fb` (depends on: pr-45db518, pr-84e6510)

Mirror of `pr-e3a711c` for the UX pool. Tuned for taste-driven, gated-merge concerns.

## Phase 5: Human surface (after Phase 2)

### PR: Watcher review session: Claude pane with work-log access
`pr-e84b43c` (depends on: pr-271cb3a)

Dedicated Claude session launched from the TUI with read access to all three watchers' work-logs. Opens with a summary of recent activity, then chat-driven. Write actions (priority bumps, pool pause/resume) require explicit confirmation in the session.

## Phase 6: Reporting

### PR: Regression loop summary reporting
`pr-558ca3f` (depends on: pr-271cb3a)

Periodic markdown digests rendered from the discovery supervisor's work-log. Complementary to the review session — the session is for ad-hoc check-ins, the digests for archival/standup use.

## Success criteria

- Discovery runs unattended under throughput constraints, surfacing both bugs and improvements
- Findings are deduplicated post-hoc by the discovery supervisor and routed to the correct plan
- Bug fixes follow reproduce→fix→verify and land without manual kickoff
- UX fixes auto-sequence to ready-for-merge then wait for human taste check
- Implementation watchers detect and handle stuck/loop-failing fix sessions
- Humans interact with the loops via the watcher review session, not by reaching into watcher state directly
