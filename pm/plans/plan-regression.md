# Automated Regression and Bug Fix Loop

Establish a continuous quality improvement loop where tests run automatically, bugs are filed from failures, and fixes are implemented with minimal human involvement.

## Goals

- Reduce manual effort in finding and fixing regressions
- Ensure bugs discovered during review/QA don't get lost
- Enforce a disciplined reproduce-first bug fix flow
- Deliver regular summaries of what was found and fixed

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

Different impl prompt for bug PRs: write a failing test first, fix the code, verify the test passes. Reviewers should check that a reproduction test exists. At session end, reconcile against other open bugs and add cross-reference notes for likely overlap.

### PR: Auto-sequence button: chain start → review → QA on a single PR
`pr-e58459b`

TUI keypress that chains start → done (review) → qa loop on one PR, halting at existing pause conditions and stopping before merge. Shared primitive used by both the bug fix loop and the UX taste loop.

### PR: Auto-pool executor: rate-limited PR queue with prioritization
`pr-45db518` (depends on: pr-e58459b)

Foundational queue primitive consumed by every autonomous track in this plan. A pool watches a configurable PR source (plan id, status filter), drives selected PRs through the auto-sequence chain under a configurable rate limit (max-concurrent and/or max-per-window), and orders them by a per-PR `priority` field. Auto-merge mode is per-pool (on for bug fixes, gated for UX). Priority is adjustable via `pm pr edit --priority`, so the regression runner, UX watcher, and bug-fix reconcile step can all influence ordering.

## Phase 2: Regression runner (after Phase 1)

### PR: Regression runner watcher: run tests on schedule and report failures
`pr-47940bc` (depends on: pr-539110b)

New watcher that runs pytest and guided scenarios on a schedule, files bugs from failures. Dedup is deferred to the bug fix flow (see `pr-30588a7`) — the watcher files freely and overlap is reconciled at fix-completion time.

### PR: Regression loop summary reporting
`pr-558ca3f` (depends on: pr-47940bc)

Periodic digests of loop activity: tests run, bugs filed, fixes landed.

## Phase 3: Autonomous loop (after Phase 2 + bug fix flow + auto-pool)

### PR: Auto-start bug fix PRs from regression failures
`pr-ea3c851` (depends on: pr-30588a7, pr-47940bc, pr-45db518)

Configure the auto-pool (pr-45db518) for bug fixes: source = `plan=bugs`, auto-merge on, priority from failure severity. Mostly pool configuration plus glue to wire severity → initial priority and let the reconcile step bump priority on overlapping bugs.

## Phase 4: Taste-driven loop (parallel track)

Mirrors Phases 2–3 for UX-quality issues that LLMs miss during spec design — features that work correctly but read as broken (e.g. children created without deps, no parent indicator). Discover via review pass rather than test failure, auto-implement but gate on human review.

### PR: UX-review watcher: file UX-quality candidates into ux plan
`pr-1766d74`

Watcher that does a UX-review pass over recent merges and current state, files candidates via `pm pr add --plan ux`. Same file-freely / reconcile-later dedup pattern as `pr-47940bc`.

### PR: UX pool: merge-gated auto-sequence for UX candidates
`pr-84e6510` (depends on: pr-1766d74, pr-45db518)

Configure the auto-pool (pr-45db518) for UX fixes: source = `plan=ux`, auto-merge gated, priority from watcher confidence. UX PRs auto-sequence to ready-for-merge then wait for a human taste check; the human merge cadence is the throttle.

## Success criteria

- Regression suite runs unattended on a configurable schedule
- Bugs from test failures are automatically filed with reproduction steps
- Bug fixes follow reproduce→fix→verify and land without manual kickoff
- Daily/weekly summary shows what was found, fixed, and still open
