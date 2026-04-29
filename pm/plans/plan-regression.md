# Automated Regression and Bug Fix Loop

Establish a continuous quality improvement loop where a Claude-based regression test surfaces both bugs and improvements, fixes are implemented in two parallel autonomous flows, and humans observe via a chat-driven review session rather than poking at the loops directly.

## Goals

- Reduce manual effort in finding and fixing regressions and UX issues
- Ensure findings discovered during review/QA don't get lost
- Enforce a disciplined reproduce-first bug fix flow
- Give humans a conversational surface for checking in on the autonomous loops

## Architecture

**Three watchers** total:

1. **Discovery supervisor** (`pr-271cb3a`) — drives one unified discovery worker (`pr-47940bc`) that runs Claude-based regression testing with a prompt tuned to surface both bugs and improvements. Files findings into `plan=bugs` or `plan=ux` based on type. Owns scheduling with throughput constraints, file-time dedup, prioritization, and work-log.
2. **Bug-fix implementation watcher** (`pr-e3a711c`) — supervises the bug-fix pool's execution. Health checks, dynamic priority, implementation metrics, throttle.
3. **Improvement-fix implementation watcher** (`pr-d39a7fb`) — same shape as the bug-fix watcher, but for the UX pool. Separate watcher because flow-specific signals (taste-driven, gated merge) justify independent tuning.

**Worker** (one) — `pr-47940bc`, the unified discovery worker. No separate UX-review pass.

**Pools** (two parallel) — `pr-ea3c851` (bug-fix, auto-merge on) and `pr-84e6510` (UX, merge-gated). Generic execution layer; reads priority but doesn't set it.

**Human surface** — `pr-e84b43c`, a Claude session launched from the TUI that has read access to all three watchers' work-logs. Opens with a summary of recent activity, then chat-driven for follow-ups and remediation (priority bumps, pool pause/resume) with explicit confirmation for writes.

## Prerequisites

- Watcher framework (`pr-3032fb6`, merged)

## Phase 1: Foundation (independent, can start now)

### PR: QA planner: consolidate related assertions into fewer scenarios
`pr-3b2847c`

Prompt-only change to reduce scenario count by grouping related assertions. Unblocks faster QA runs which makes the whole loop more practical.

### PR: Review and QA agents file bugs for out-of-scope issues via pm pr add
`pr-539110b`

Teach review and QA agents to use `pm pr add --plan bugs` when they spot issues outside the current PR's scope. No verdict changes — agents still PASS/NEEDS_WORK on the PR itself, but file bugs as a side effect.

### PR: Bug fix flow: reproduce with test, fix, verify
`pr-30588a7`

Different impl prompt for bug PRs: write a failing test first, fix the code, verify the test passes. Reviewers check that a reproduction test exists. Session-end reconcile is verification-only — primary dedup is owned by the discovery supervisor at file time.

### PR: Auto-sequence button: chain start → review → QA on a single PR
`pr-e58459b`

TUI keypress that chains start → done (review) → qa loop on one PR, halting at existing pause conditions and stopping before merge. Shared primitive used by both autonomous tracks.

### PR: Auto-pool executor: rate-limited PR queue with prioritization
`pr-45db518` (depends on: pr-e58459b)

Foundational queue primitive consumed by every autonomous track. Watches a configurable PR source, drives selected PRs through the auto-sequence chain under a rate limit, orders by per-PR `priority`. Auto-merge mode is per-pool. Priority is set by the discovery supervisor and the implementation watchers; the pool itself is agnostic.

## Phase 2: Discovery (after Phase 1)

### PR: Unified discovery worker
`pr-47940bc` (depends on: pr-539110b)

Dumb worker that runs Claude-based regression testing with a prompt tuned to surface both bug-shaped failures and improvement-shaped findings. Emits typed records (`type: bug | improvement`) on demand. No scheduling, dedup, priority, or filing.

### PR: Discovery supervisor watcher (unified for bugs and improvements)
`pr-271cb3a` (depends on: pr-47940bc, pr-45db518)

Owns scheduling with throughput constraints, type-based routing into `plan=bugs` / `plan=ux`, file-time dedup against open PRs and work-log, priority assignment, structured work-log, and worker exception handling.

## Phase 3: Pool configurations (after Phase 1)

### PR: Bug-fix pool config (auto-merge on)
`pr-ea3c851` (depends on: pr-30588a7, pr-47940bc, pr-45db518)

Pool config: source = `plan=bugs`, auto-merge on. Picks up bug PRs filed by the discovery supervisor and runs them through the bug-fix flow.

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
- Findings are deduplicated against existing PRs at file time and routed to the correct plan
- Bug fixes follow reproduce→fix→verify and land without manual kickoff
- UX fixes auto-sequence to ready-for-merge then wait for human taste check
- Implementation watchers detect and handle stuck/loop-failing fix sessions
- Humans interact with the loops via the watcher review session, not by reaching into watcher state directly
