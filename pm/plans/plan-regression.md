# Automated Regression and Bug Fix Loop

Establish a continuous quality improvement loop where the existing Claude-based regression tests surface bugs and improvements, two implementation watchers drive the fix flows, and humans observe via a chat-driven review session.

## Goals

- Reduce manual effort in finding and fixing regressions and UX issues
- Ensure findings discovered during review/QA don't get lost
- Enforce a disciplined reproduce-first bug fix flow
- Give humans a conversational surface for checking in on the autonomous loops

## Reuse: existing infrastructure

The autonomous loops are deliberately built on existing primitives. New code is limited to per-watcher subclasses, prompt templates, and one CLI extension.

- **Watcher framework** (`pr-3032fb6`, merged): `BaseWatcher` runs as a background thread polling on a configurable interval. Each tick spawns a new Claude session in a tmux window with a generated prompt. Verdict (`READY` to continue, `INPUT_REQUIRED` to escalate) is extracted from the session transcript via the existing `idle_prompt` hook. New watchers are subclasses; example: `pm_core/watchers/auto_start_watcher.py`.
- **Notes infrastructure** (`pr-83b98d5`, merged): `notes.txt` has sections including `Watcher`. `notes_for_prompt(root, "watcher")` returns the General + Watcher blocks already; new watchers get user-specified guidance for free without any per-watcher work. Users can leave guidance like "always run the auth-regression test daily" or "prioritize fixing memory leaks before UI polish" and it flows into every tick automatically.
- **Regression test list**: `pm/qa/regression/*.md`, loaded by `qa_instructions.list_all()`, launched via `launch_qa_item()` (`pm_core/tui/pane_ops.py`).
- **Verdict collection**: `poll_for_verdict()` (`pm_core/loop_shared.py`) and `extract_verdict_from_transcript()` (`pm_core/verdict_transcript.py`).
- **Plans as pools**: a "pool of PRs" is just a pm plan (`plan=bugs`, `plan=ux`). No new pool construct, no priority field. Watchers judge priority dynamically each tick using prompt-supplied generic guidance plus user notes from the Watcher section.
- **Unified pm log** (`pr-9bf8b0b`, merged) is available for project-wide visibility; per-watcher continuity uses dedicated text files at `pm/watchers/<name>.log` so each watcher's tick has tight, relevant context to read.

## Architecture

**Three watchers**, each a `BaseWatcher` subclass with its own interval, prompt generator, and work log:

1. **Discovery supervisor** (`pr-271cb3a`) — schedules runs of the existing regression tests at `pm/qa/regression/*.md`. Test sessions themselves file findings via `pm pr add` (taught by `pr-47940bc`); the supervisor reconciles post-hoc (dedup, route confirmation, work-log).
2. **Bug-fix implementation watcher** (`pr-e3a711c`) — drives the bug-fix flow against `plan=bugs`. Picks the best candidate dynamically each tick, advances PRs through `pm pr auto-sequence`, auto-merges on QA PASS.
3. **Improvement-fix implementation watcher** (`pr-d39a7fb`) — same shape against `plan=ux`. Gated merge — PRs that PASS QA are held for a human taste check.

**Prioritization is dynamic.** Each watcher tick judges priority based on prompt-supplied generic guidance (severity, recurrence, age, taste signals) plus user-specified guidance automatically injected from `notes.txt` Watcher section. No persisted priority field, no separate pool config.

**Work logs** live at `pm/watchers/discovery.log`, `pm/watchers/bug-fix-impl.log`, `pm/watchers/improvement-fix-impl.log`. Each tick's prompt instructs Claude to read the log first for context and append a one-line summary before exiting. Continuity between ticks lives in the file.

**Human surface** — `pr-e84b43c`, a Claude session launched from the TUI that reads the three work logs, summarizes recent activity, and is conversational from there.

## Status

- ✅ Merged (11): all original plan PRs (pr-3b2847c, pr-539110b, pr-30588a7, pr-e58459b, pr-47940bc, pr-97ddabf, pr-271cb3a, pr-e84b43c, pr-d39a7fb, pr-e3a711c, pr-d60d185)
- ⏳ Pending (1): `pr-fbda1a8` (test backfill — added 2026-05-02 after observing gaps)

## Prerequisites

- Watcher framework (`pr-3032fb6`, merged)
- Notes addendum infrastructure (`pr-83b98d5`, merged)
- Unified pm log (`pr-9bf8b0b`, merged)

## Phase 1: Foundation (independent, can start now)

### PR: QA planner: consolidate related assertions into fewer scenarios ✅ MERGED (#167)
`pr-3b2847c`

Prompt-only change to reduce scenario count by grouping related assertions.

### PR: Review and QA agents file bugs for out-of-scope issues via pm pr add ✅ MERGED (#168)
`pr-539110b`

Teach review and QA agents to use `pm pr add --plan bugs` when they spot issues outside the current PR's scope. Filing is a side effect, not a verdict change.

### PR: Bug fix flow: reproduce with test, fix, verify 🔨 IN PROGRESS (#169)
`pr-30588a7`

Different impl prompt for bug PRs: write a failing test first, fix the code, verify the test passes. Reviewers check that a reproduction test exists. Session-end reconcile step is verification-only — primary dedup is owned by the discovery supervisor post-hoc.

### PR: Auto-sequence chain: TUI keypress + programmatic CLI
`pr-e58459b`

Chain start → review → QA on a single PR, halting at existing pause conditions and stopping before merge. Two entry points: TUI keypress (human use) and `pm pr auto-sequence <id>` CLI (watcher use). The CLI is essential — without it, watcher Claude sessions would have to drive the chain via tmux send-keys against the TUI.

## Phase 2: Discovery (after Phase 1)

### PR: Regression test sessions file bugs and improvements into correct plans
`pr-47940bc` (depends on: pr-539110b)

Prompt-addendum at the launch-path wrapper in `launch_qa_item()` so the existing Claude-based regression test sessions know to file findings via `pm pr add --plan bugs` or `--plan ux`. Mirror of `pr-539110b` for regression tests. Verdicts unchanged.

### PR: Watcher-target window for regression test launches
`pr-97ddabf` (depends on: pr-47940bc)

Add an optional `target_window` parameter to `launch_qa_item()` so watcher-driven launches stay in the watcher's pane and human launches keep their current main-window behavior.

### PR: Discovery supervisor watcher (BaseWatcher subclass)
`pr-271cb3a` (depends on: pr-47940bc, pr-97ddabf)

New `pm_core/watchers/discovery_supervisor.py` subclass + `generate_discovery_supervisor_prompt()`. Each tick reads `pm/watchers/discovery.log` and decides whether to launch a regression test, monitors in-flight tests, reconciles newly-filed bug/improvement PRs (dedup against open PRs in the target plan), appends to the log, emits READY or INPUT_REQUIRED. User guidance flows in automatically via the Watcher notes section.

## Phase 3: Implementation watchers (after Phase 1)

### PR: Bug-fix implementation watcher (BaseWatcher subclass)
`pr-e3a711c` (depends on: pr-e58459b)

New `pm_core/watchers/bug_fix_impl_watcher.py` + `generate_bug_fix_impl_prompt()`. Each tick reads its work log, scans `plan=bugs` for pending PRs, picks the best candidate dynamically (severity + recurrence + work-log signals + user notes), advances via `pm pr auto-sequence`, and auto-merges on QA PASS. Detects stuck/loop-failing PRs and escalates via INPUT_REQUIRED.

### PR: Improvement-fix implementation watcher (BaseWatcher subclass)
`pr-d39a7fb` (depends on: pr-e58459b)

Mirror of `pr-e3a711c` against `plan=ux`. Differences: longer cadence, gated merge (PRs that PASS QA are advanced to ready-for-merge and held for human taste check), taste-shaped prioritization guidance.

## Phase 4: Human surface (after Phases 2-3)

### PR: Watcher review session: Claude pane with work-log access
`pr-e84b43c` (depends on: pr-271cb3a)

Dedicated Claude session launched from the TUI with read access to all three watchers' work logs at `pm/watchers/*.log`, current plan/PR state, and per-test transcripts. Opens with a summary of recent activity, then chat-driven. Write actions (notes additions, pausing a watcher) require explicit confirmation.

## Phase 5: Activation (final)

### PR: End-to-end QA review and auto-start command
`pr-d60d185` (depends on: pr-271cb3a, pr-e3a711c, pr-d39a7fb, pr-e84b43c)

Final integration PR. Single command (`pm watcher start regression-loop` or similar) that brings up all three watchers with sensible defaults — without this, users have to start each watcher individually. Also serves as the end-to-end QA pass: once everything else has merged, exercise the full autonomous loop and catch integration gaps the per-PR reviews can't see.

## Phase 6: Test backfill

### PR: Claude-based tests for watcher classes and prompt generation gaps
`pr-fbda1a8` (depends on: pr-d60d185)

The three concrete watcher classes and four new prompt builders shipped without direct unit tests — covered only by the BaseWatcher framework tests and the live operator markdown. This PR backfills using FakeClaudeSession (`pr-abcf70f`, merged) so watchers can be exercised deterministically: per-class watcher tests, prompt-string assertions for the new builders, integration backstop for the three auto-sequence paths flagged during `pr-e58459b`'s review, and behavioral tests for `launch_qa_item`'s new `target_window` parameter and regression-filing addendum.

## Success criteria

- Discovery runs unattended via the existing watcher framework, surfacing both bugs and improvements
- Findings are deduplicated post-hoc by the discovery supervisor and routed to the correct plan
- Bug fixes follow reproduce→fix→verify and land without manual kickoff
- UX fixes auto-sequence to ready-for-merge then wait for human taste check
- Implementation watchers detect and handle stuck/loop-failing fix sessions
- Users influence watcher behavior by editing `notes.txt` Watcher section, not by reaching into watcher state directly
- Humans interact with the loops via the watcher review session and `notes.txt`, not by direct watcher manipulation
