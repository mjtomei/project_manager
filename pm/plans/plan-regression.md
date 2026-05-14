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

- ✅ Merged (12): all original plan PRs (pr-3b2847c, pr-539110b, pr-30588a7, pr-e58459b, pr-47940bc, pr-97ddabf, pr-271cb3a, pr-e84b43c, pr-d39a7fb, pr-e3a711c, pr-d60d185) plus `pr-6be8ee6` (#190 — prompt-side pre-fix repro gate, Phase 7 prerequisite, tracked under improvements)
- ⏳ Pending (8): `pr-fbda1a8` (test backfill), `pr-b77702b` (per-plan auto-merge=false), `pr-2c060b2` (CLI width regression test), and the Phase 7 evidence/coverage stack (`pr-eb450a0`, `pr-b42059d`, `pr-8ed578d`, `pr-8422dea`, `pr-c2397e2`)
- 📋 Phase 9 (6 PRs filed): `pr-ca6859f` (self-recovery audit), `pr-6f9301e` (headless/benchmark mode), `pr-ed10ac4` (no-progress safety stop), `pr-b3b8df0` (QA instruction auto-synthesis primitive), `pr-98f670e` (QA scenario quality supervisor with queryable scenario sessions), `pr-e2b7fdf` (ProgramBench submission scaffolding, consumes the primitive)
- 📋 Phase 10 (7 PRs): `pr-9603d04` (GitHub backend mock — sibling of FakeClaudeSession), `pr-51586d2` (shared mock library + scenario-author discovery), `pr-7d5d036` (`pm tui test` containment bug), `pr-06a96fa` (QA scenarios reuse regression tests as flow drivers), `pr-b59f0c7` (capture reason strings for non-PASS verdicts), `pr-0b14f2c` (planner can add/replace scenarios mid-run), `pr-f4dc8a2` (QA library auditor)

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

### PR: Bug fix flow: reproduce with test, fix, verify ✅ MERGED (#169)
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

## Phase 7: Evidence-gated bug fix loop (post-activation hardening)

Goal: tighten the bug-fix flow until the loop can run unsupervised. The earlier phases got reproduce→fix→verify into the prompt; these PRs make each step produce on-disk evidence the watcher / verdict gate can hard-check.

### PR: Bug-fix flow surface TUI QA repro instructions in session prompt ✅ MERGED (#190)
`pr-6be8ee6` (plan=improvements)

Adds a "did you reproduce on pre-fix code?" gate to `_BUG_FIX_FLOW_BLOCK` and references `pm/qa/instructions/tui-manual-test.md` for TUI bugs. Tracked under improvements but is the prompt-side prerequisite for the evidence-artifact PR below — listed here for plan visibility.

### PR: Persist pre-fix repro and post-fix verification evidence as artifacts
`pr-eb450a0` (depends on: pr-6be8ee6)

Make the prompt-level repro/verify gates machine-checkable. Sessions write `pm/evidence/<pr_id>/pre-fix.md` (sha + commands + captured output showing the bug, before any source modification) and `pm/evidence/<pr_id>/post-fix.md` (sha on fix branch + commands + captured output showing the bug is gone, referencing pre-fix.md). Bug-fix implementation watcher refuses to advance to review without `pre-fix.md`; review/QA verdict gate refuses PASS without `post-fix.md`.

### PR: QA code coverage of exercised lines factors into PASS verdict
`pr-b42059d` (pending)

Per-line coverage data emitted from QA scenario runs and surfaced into the verdict. Foundation for the fix-line gate below.

### PR: Fix-line coverage gate ties coverage to the diff
`pr-8ed578d` (depends on: pr-b42059d)

PASS additionally requires that the lines added/modified by the PR were executed by at least one QA scenario. Closes the loophole where overall coverage passes while the fix code never runs. Surfaces a separate "fix-line coverage" percentage; uncovered changed lines must be explicitly justified in PR notes.

### PR: Extended coverage measures (path, user-story)
`pr-8422dea` (pending)

Beyond line coverage: branch/path coverage on the diff and user-story coverage of QA scenarios. Strengthens the verdict signal once line and fix-line gates are in place.

### PR: QA refinement prompt asks for additional steps that improve coverage
`pr-c2397e2` (pending)

When coverage gates fail, the refinement prompt asks the QA planner for additional scenarios specifically targeting the uncovered fix-line set. Closes the loop between gate failure and scenario growth.

## Phase 8: Post-activation refinements

PRs added after the loop landed, addressing gaps surfaced once the watchers were running in anger.

### PR: Per-plan auto-merge=false mode with dep-merge in start prompt
`pr-b77702b` (pending)

Adds a per-plan `auto_merge` setting (default true) so plans that need human review before shipping (ambient surfaces, UX iteration) can let watchers run impl/review/QA but stop short of merging. Also injects a dep-merge preamble into the start prompt when the PR has unmerged deps, so iteratively-developed plans stay coherent without each PR landing on master first.

### PR: Claude-based regression test: CLI output rendering at varied terminal widths
`pr-2c060b2` (pending)

Extends the regression corpus consumed by the discovery supervisor (`pr-271cb3a`). New scenario at `pm/qa/regression/cli-output-widths.md` resizes a tmux pane to randomly-chosen widths, captures `pm pr list` / `pm pr ready` / `pm plan list` output, and asks Claude to flag layout bugs (overflow, mid-word breaks, miscounted wide-char icons). Findings file as bugs or improvements via the existing addendum from `pr-47940bc`. Manual testing: review the rendered output across the seeded widths to confirm the verdict logic flags real layout bugs and ignores acceptable wrapping — INPUT_REQUIRED is appropriate for the visual-judgment portion.

## Phase 9: Headless and unsupervised hardening

Push the loop from "autonomous with a human in reserve via INPUT_REQUIRED" to "autonomous and recoverable with no human in the path." Driven by the ProgramBench submission as a concrete forcing function — the cleanroom image has no human and no human-reachable surface — but the hardening (self-recovery playbooks, no-progress detection, headless runtime) is generally useful for unattended operation.

### PR: Watcher self-recovery audit
`pr-ca6859f` (pending). **Land first** — gates the headless/benchmark mode below.

Audit every escalation path in the watcher prompts and surrounding code (`generate_bug_fix_impl_prompt`, `generate_improvement_fix_impl_prompt`, `generate_discovery_supervisor_prompt`, the review and QA prompts) and add explicit recovery playbooks instead of INPUT_REQUIRED for technical issues that have a clear correct response. Examples: container creation failure → retry with backoff, missing dep → install, stuck loop → cap iterations, mark failed, move on, spec ambiguity → record assumption and proceed, push failure → retry then re-fetch and rebase. INPUT_REQUIRED stays available for genuinely human-judgment-required cases (e.g. the watcher review session adding notes); but the bar to escalate moves from "anything unexpected" to "no plausible automatic recovery." Manual testing: synthesize each failure mode in a controlled run and confirm the playbook fires; INPUT_REQUIRED rate on a representative bug-fix corpus should drop measurably.

### PR: Headless / benchmark mode for autonomous loops
`pr-6f9301e` (depends on: pr-ca6859f, pr-438028c, pr-f17e22b).

Single `benchmark_mode` flag covering the runtime and prompt layers:
- **Runtime**: pm operates without a visible TUI (no picker, no popup, hooks bypassed where they assume a TUI surface), all session activity captured in a single structured log file. Builds on `pr-438028c` (CLI window management for review-loop / QA) and what's left after it lands.
- **Prompt layer**: extends `pr-f17e22b`'s TUI-section gate to a project-wide flag that strips "ask the user" / interactive language from every prompt builder (`generate_prompt`, `generate_review_prompt`, `generate_merge_prompt`, the QA planner / refinement / scenario prompts, the watcher prompts).

Coupling rationale: removing INPUT_REQUIRED from prompts is only safe once the self-recovery playbooks exist. Sequencing this PR after the self-recovery audit makes that explicit.

### PR: No-progress safety stop on review/QA loops
`pr-ed10ac4` (pending).

Detect "same diff, same verdict, no real change" between iterations and short-circuit before max-iterations. Today max-iterations is the only ceiling and is loose (60 minutes per `pr-860969d`); a no-progress detector catches the cheap-to-detect case where the loop is spinning. Hashes diff + verdict + relevant prompt snippets across iterations; on N consecutive identical hashes (default 2), short-circuits with a NEEDS_WORK verdict and a structured reason that the watcher can route to retry-once or mark-failed. Useful in normal mode too — a stuck review loop today wastes the full iteration budget.

### PR: QA instruction auto-synthesis at project setup
`pr-b3b8df0` (pending). Independent of the other Phase 9 PRs.

A setup-time leader pass that takes a project task envelope (binary + docs, repo + task description, generic project root) and emits `pm/qa/instructions/*.md` files the existing QA loop already knows how to consume. Per-task-type logic plugs in as backends behind a shared interface. ProgramBench is one consumer (its backend lives in `pr-e2b7fdf` below); GAIA-style benchmarks would be another; a generic-pm-project backend is a follow-up improvement that lowers activation energy for users who today author QA instructions by hand.

The probe-and-write shape is the same across consumers — only the per-type heuristics differ. Pulling this primitive out of the ProgramBench scaffolding keeps each consumer to a backend registration rather than a fork of the synthesis logic.

### PR: QA scenario quality supervisor
`pr-98f670e` (depends on: pr-b3b8df0, pr-6f9301e).

Inserts a supervisory step between scenario completion and verdict-emit that judges whether each scenario's produced artifacts (captures, logs, assertions) actually constitute evidence the functionality works, or whether the scenario took a shortcut. The load-bearing failure mode is **false PASS**: scenarios reliably produce thin artifacts that nominally pass while not exercising what they claim to verify. In supervised mode a human catches this; in headless mode (`pr-6f9301e`) nobody does.

Scenario sessions stay queryable after their verdict via `--resume`; the supervisor probes for shortcuts ("what did you actually verify?", "what state did you check after the action?", "what could you have asserted that you didn't?"). Then:
- Genuinely deep PASS → verdict propagates.
- Shallow PASS → amend the scenario instruction to require deeper checks, re-run, propagate the re-run's verdict.
- Repeated shortcut pattern → propose a planner-prompt edit so future scenarios don't repeat it (gated through the improvement-fix watcher).

Per-scenario amendment cap (default 2) prevents supervisor loops; cap-exceeding cases escalate via the self-recovery playbook. Distinct from `pr-ca6859f` (technical retry) and `pr-ed10ac4` (spinning-loop detection): this one is about verdict trust, not loop dynamics.

### PR: ProgramBench submission scaffolding
`pr-e2b7fdf` (depends on: pr-ca6859f, pr-6f9301e, pr-ed10ac4, pr-b3b8df0).

Now consumes the auto-synthesis primitive — registers a ProgramBench backend that probes `/workspace/executable` + docs and emits `pm/qa/instructions/binary-comparison.md`. The synthesis driver lives in `pr-b3b8df0`; this PR contributes the per-task-type backend, the leader prompt, the adapter CLI, the reproducibility Dockerfile, and the egress-allowlist firewall harness.

Bundle four pieces as one deliverable, demonstrating the autonomous loop end-to-end on an external benchmark rather than starting a parallel benchmark plan.

- **Leader prompt template**: a new prompt builder (sibling of `generate_prompt`, `generate_review_prompt`) framing pm as the leader's tool. Lists relevant CLI commands, delegates QA-instruction authoring to the leader (writes `pm/qa/instructions/binary-comparison.md` based on its probe of `/workspace/executable`), files plan + PRs, drives them through start/review/QA/merge.
- **Adapter CLI**: `pm bench programbench --task <id>` drops the task into a workdir, generates the leader prompt, spawns the leader session in `benchmark_mode`, extracts `/workspace` as the submission tarball when the leader finishes.
- **Reproducibility Dockerfile**: `FROM programbench/<task>:task_cleanroom` layered with pm + Claude Code + pinned deps. The submission asset.
- **Egress-allowlist firewall harness**: iptables / network namespace at the sandbox boundary allowing only the model API endpoint. Defense-in-depth against incidental network use during benchmark runs; `backend=local`, `container-mode=off` (the cleanroom is the container).

Single PR is justified because each piece is small and they are tightly coupled by the submission shape. Manual testing: run the adapter against a held-back ProgramBench task and inspect the produced `/workspace` tarball before submission.

## Phase 10: QA loop surface improvements

Filed during `pr-6be8ee6`'s QA iteration once the loop was exercised in anger. Each addresses a friction point that surfaced from running real QA cycles against the bug-fix flow.

### PR: GitHub backend mock for regression tests
`pr-9603d04` (pending)

Sibling of `pr-abcf70f` (FakeClaudeSession) for the GitHub side. Provides a scriptable `FakeGitHubBackend` (or transport-level fake) so regression tests can exercise github-backend code paths — PR create, status sync, draft↔ready transitions, comments, merge, post-merge pull, rate-limit / conflict / merged-elsewhere responses — without hitting the real GitHub API. Without this, regression coverage stops at the GitHub boundary and bug-fix watchers cannot reproduce GitHub-specific bugs deterministically.

### PR: Shared mock library — scenario-created mocks discoverable to future authors
`pr-51586d2` (depends on: pr-abcf70f, pr-9603d04)

Closes the gap that none of the existing Phase 9/10 PRs covers explicitly: when a scenario session creates a new mock to exercise its target, that mock must be registered in a shared library at `pm/qa/mocks/` so future scenario-authoring sessions discover and reuse it. Without this, the regression flow's leverage doesn't compound — each scenario re-derives the same fakes inline, slightly differently, with different bugs.

Adds: directory convention + frontmatter schema at `pm/qa/mocks/`, loader helper, `pm qa mocks list / show` CLI, prompt-addendum block listing the existing registry for QA-planner, QA scenario refiner, and regression-filing wrapper (`pr-47940bc`) sessions, with instructions to prefer existing mocks and to write registry entries + python modules as part of the scenario PR when authoring new ones. FakeClaudeSession (`pr-abcf70f`) and FakeGitHubBackend (`pr-9603d04`) are the first two registered entries; `pr-b3b8df0` (auto-synthesis primitive) and `pr-f4dc8a2` (library auditor) become consumers.

### PR: Bug: `pm tui test` hardcodes "testing against the pm tmux session"
`pr-7d5d036` (depends on: pr-abcf70f, pr-9603d04)

The regression-runner harness assumes the test target is the host pm tmux session; wrong for containers and for non-pm targets. Cleanup of the runner's surface framing and containment model so regression runs don't leak state into the caller's repo. Adds FakeClaudeSession + FakeGitHubBackend as dependencies so the cleaned-up runner can drive both Claude and GitHub deterministically from the start. Prerequisite for using regression tests as durable QA flow drivers (`pr-06a96fa`).

### PR: QA scenarios reuse regression tests as their flow driver
`pr-06a96fa` (depends on: pr-7d5d036)

Switch QA scenarios from "instruction (setup) + artifact recipe (drive/capture)" pairs to binding directly to a regression test, with per-scenario assertions layered on top. The library of exercised user flows grows by accumulation rather than per-PR effort; the same flow is driven the same way across PRs so behavior drift gets caught; captures from regression runs feed both the regression history and the QA evidence record. INSTRUCTION/ARTIFACT remain as the fallback path.

### PR: Capture reason strings for non-PASS verdicts
`pr-b59f0c7` (depends on: pr-6be8ee6)

Generalize the per-scenario `verdict_reason` field added for the refiner-rejection path to every place a non-PASS verdict comes out of an automated loop (main scenario workers, review-loop, watcher). Reasons land in `state.scenario_verdict_reasons[idx]`, flow into `qa_status.json` and `verdict.md`, and render as a one-line "↳ <reason>" continuation under each non-PASS verdict in status panes. Triage stops requiring pane-scrollback archaeology.

### PR: QA scenario planner allows adding scenarios mid-run or after initial plan
`pr-0b14f2c` (depends on: pr-6be8ee6)

Let the planner add scenarios beyond the initial plan and let users re-run NEEDS_WORK scenarios or replace INPUT_REQUIRED ones, so coverage gaps and earlier failures resolve without restarting QA. The overall verdict can transition from INPUT_REQUIRED or NEEDS_WORK back to PASS as added/replaced scenarios settle. New `+` / `r` / `R` keys in the scenarios pane pull the latest `QA_PLAN_START/END` block from the planner pane's transcript. Replaced scenarios' prior captures preserved under `scenarios/<n>/prior-N/`. Manual testing: drive the keypress flow against a real run with at least one NEEDS_WORK and one INPUT_REQUIRED scenario; INPUT_REQUIRED is appropriate for the human-judged "load this plan block" moments.

### PR: QA library auditor
`pr-f4dc8a2` (pending)

Scan a project and suggest fills for missing QA instructions, regression tests, artifact recipes, and mocks. A meta-tool that helps users grow the QA library that the rest of the loop depends on. Closes the loop between "the QA loop got more powerful" (Phase 10 above) and "the library underneath it actually has enough content to use that power."

## Success criteria

- Discovery runs unattended via the existing watcher framework, surfacing both bugs and improvements
- Findings are deduplicated post-hoc by the discovery supervisor and routed to the correct plan
- Bug fixes follow reproduce→fix→verify and land without manual kickoff
- UX fixes auto-sequence to ready-for-merge then wait for human taste check
- Implementation watchers detect and handle stuck/loop-failing fix sessions
- Users influence watcher behavior by editing `notes.txt` Watcher section, not by reaching into watcher state directly
- Humans interact with the loops via the watcher review session and `notes.txt`, not by direct watcher manipulation
