# Automated Regression and Bug Fix Loop

Establish a continuous quality improvement loop where tests run automatically, bugs are filed from failures, and fixes are implemented with minimal human involvement.

## Goals

- Reduce manual effort in finding and fixing regressions
- Ensure bugs discovered during review/QA don't get lost
- Enforce a disciplined reproduce-first bug fix flow
- Deliver regular summaries of what was found and fixed

## Architecture

Two autonomous flows (regression bug-fix, UX improvement), each with three layers:

- **Worker** — dumb component that runs the discovery action on demand and emits raw findings (test failures or UX candidates). No scheduling, dedup, prioritization, or logging.
- **Supervisor watcher** — owns scheduling with throughput constraints, dedup against open PRs and recent work-log, prioritization on filings, work-log of all decisions, and exception handling for stuck/crashed workers.
- **Pool** — generic rate-limited PR executor (start → review → QA chain) ordered by per-PR priority. The pool reads priority; it doesn't care who set it.

This separation lets each layer be tuned independently and keeps the workers minimal.

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

Different impl prompt for bug PRs: write a failing test first, fix the code, verify the test passes. Reviewers check that a reproduction test exists. The session-end reconcile step is verification-only — primary dedup is owned by the supervisor (pr-271cb3a) at file time.

### PR: Auto-sequence button: chain start → review → QA on a single PR
`pr-e58459b`

TUI keypress that chains start → done (review) → qa loop on one PR, halting at existing pause conditions and stopping before merge. Shared primitive used by both autonomous tracks.

### PR: Auto-pool executor: rate-limited PR queue with prioritization
`pr-45db518` (depends on: pr-e58459b)

Foundational queue primitive consumed by every autonomous track. Watches a configurable PR source, drives selected PRs through the auto-sequence chain under a rate limit (max-concurrent and/or max-per-window), orders by per-PR `priority`. Auto-merge mode is per-pool. Priority is set by supervisors via `pm pr edit --priority`; the pool is agnostic to who sets it.

## Phase 2: Workers (after Phase 1)

### PR: Regression test-runner worker
`pr-47940bc` (depends on: pr-539110b)

Dumb worker that runs pytest and guided scenarios on demand and emits raw failure records. No scheduling or filing — that's the supervisor's job.

### PR: UX-review worker
`pr-1766d74`

Dumb worker that runs a UX-review pass over recent merges and current state and emits raw candidate records. No scheduling or filing — that's the supervisor's job.

## Phase 3: Supervisors (after Phase 2)

### PR: Regression-flow supervisor watcher
`pr-271cb3a` (depends on: pr-47940bc, pr-45db518)

Owns scheduling (with throughput constraints), dedup against open bug PRs and the work-log, priority assignment on new filings, structured work-log, and exception handling for the regression worker. Decides drop / merge / file-new for each raw failure the worker emits.

### PR: Improvement-flow supervisor watcher
`pr-d39a7fb` (depends on: pr-1766d74, pr-45db518)

Mirror of the regression supervisor for the UX flow. Separate watcher because cadence and judgment criteria (confidence-based vs. severity-based) differ enough to keep tuning independent.

### PR: Regression loop summary reporting
`pr-558ca3f` (depends on: pr-47940bc)

Renders the supervisors' work-logs into periodic markdown digests. Mostly a presentation layer — the source of truth lives in the supervisor's log.

## Phase 4: Pool configurations (after Phase 3)

### PR: Bug-fix pool config (auto-merge on)
`pr-ea3c851` (depends on: pr-30588a7, pr-47940bc, pr-45db518)

Pool config: source = `plan=bugs`, auto-merge on. Picks up bug PRs filed by the regression supervisor and runs them through the bug-fix flow.

### PR: UX pool config (merge-gated)
`pr-84e6510` (depends on: pr-1766d74, pr-45db518)

Pool config: source = `plan=ux`, auto-merge gated. UX PRs auto-sequence to ready-for-merge then wait for a human taste check.

## Success criteria

- Regression suite runs unattended under throughput constraints
- Bugs from test failures are filed with reproduction steps and deduplicated against existing PRs at file time
- Bug fixes follow reproduce→fix→verify and land without manual kickoff
- Supervisors maintain a structured work-log; summary reporting renders it for human review
