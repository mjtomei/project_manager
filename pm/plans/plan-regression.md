# Automated Regression and Bug Fix Loop

Establish a continuous quality improvement loop where the existing Claude-based regression tests surface bugs and improvements, two implementation watchers drive the fix flows, and humans observe via a chat-driven review session.

## Goals

- Reduce manual effort in finding and fixing regressions and UX issues
- Ensure findings discovered during review/QA don't get lost
- Enforce a disciplined reproduce-first bug fix flow
- Give humans a conversational surface for checking in on the autonomous loops
- Close the loop: an autonomous sign-off step that reviews behavior, gates merges, and routes each PR forward to merge or back to the right step — with the human optional, not required (Phase 11)

> See `pm/docs/literature-review.md` for context on the academic and industry work surrounding this plan — benchmarks, autonomous coding agents, LLM-driven test generation, self-improving loops, integrity audits, and watcher architectures. Includes pointers to what's reused, what's adapted, and where this plan is making its own bet.
>
> See `pm/docs/adversarial-review/METHODOLOGY.md` for an adversarial-review protocol (ported from the Omerta paper's by-hand review loop) that can subject this plan and the literature review to systematic criticism through fresh, blind reviewer cycles. Worked examples from the Omerta runs live alongside the methodology doc.

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

> **Phase 11 generalization (forward reference)**: watchers 2 and 3 are generalized into a single **plan auto-start watcher**, parameterized per plan (gated vs autonomous, mandated checks like the improvements taste-check, a watcher-chosen max-in-flight-PR count), and the `auto-start` monitoring watcher folds into it. That watcher also becomes the auto-start *engine*, replacing the programmatic `auto_start.py` orchestration; per-PR decisions defer to the Phase 11 sign-off step. The discovery supervisor (watcher 1) is unchanged and still schedules regression runs; any session (regression, review, QA, sign-off, impl) auto-files bug/improvement PRs, and the per-plan watchers for `bugs` and `ux` close the loop. Per-watcher work logs are recast as **plan notes** (carried in the plan files, surfaced in the behavior review interface). See Phase 11.

**Prioritization is dynamic.** Each watcher tick judges priority based on prompt-supplied generic guidance (severity, recurrence, age, taste signals) plus user-specified guidance automatically injected from `notes.txt` Watcher section. No persisted priority field, no separate pool config.

**Work logs** live at `pm/watchers/discovery.log`, `pm/watchers/bug-fix-impl.log`, `pm/watchers/improvement-fix-impl.log`. Each tick's prompt instructs Claude to read the log first for context and append a one-line summary before exiting. Continuity between ticks lives in the file. *(Phase 11 recasts the plan-watcher logs as plan notes carried in the plan files — see the generalization note above.)*

**Human surface** — `pr-e84b43c`, a Claude session launched from the TUI that reads the three work logs, summarizes recent activity, and is conversational from there. *(Phase 11 adds a second surface: the behavior review interface (`pr-8e693f6`) makes plan notes, PR descriptions, and PR notes reachable alongside the behavior reports.)*

## How the QA flow evolves (Phase 10 lookahead)

The architecture above describes the system as Phases 1-5 shipped it: three watchers, the discovery supervisor scheduling regression tests, scenarios driven by INSTRUCTION+ARTIFACT scaffolding. Phase 10 reshapes the underlying scenario model — that's the most consequential pending change in this plan and it affects how to read the later phases. In short:

- **Before Phase 10**: scenarios = INSTRUCTION (setup) + ARTIFACT (drive/capture). Regression tests are a separate library the discovery supervisor runs on its own cadence. Mocks library exists (`pr-942aa21`, plan-qa, merged) but its prompt injection at scenario planning was stripped (`pr-6be8ee6` / commit `3eb89e6`) because it produced noise.
- **After Phase 10**: scenarios bind to regression tests as their canonical flow driver (`pr-06a96fa`). When no regression fits, the planner authors one inline (`pr-2680fbf`) and the drafted regression becomes a durable library entry the discovery supervisor will rerun. Mocks awareness reconnects at the new-regression authoring surface (`pr-51586d2`) — diff-scoped, surface-declared — instead of the indiscriminate scenario-prompt injection that didn't work. INSTRUCTION+ARTIFACT remains as a fallback only for one-shot probes/oracles.

This is the load-bearing change: the regression library starts to *compound* — every QA run that hits a new surface adds a regression test, which subsequent QA runs reuse, which the discovery supervisor exercises on its own schedule. Phase 6 (the bridge PR), Phase 7 (coverage gates), and Phase 9 (headless / scenario quality supervisor) all interact with this new model.

**Reading order tip**: if you're picking up the plan cold, read Phase 10 first; the other pending phases assume its model lands or measure against it.

## Status

**Merged (12)** — Phases 1-5 plus the Phase 7 prerequisite:
- Phase 1: pr-3b2847c, pr-539110b, pr-30588a7, pr-e58459b
- Phase 2: pr-47940bc, pr-97ddabf, pr-271cb3a
- Phase 3: pr-e3a711c, pr-d39a7fb
- Phase 4: pr-e84b43c
- Phase 5: pr-d60d185
- Phase 7 prereq: pr-6be8ee6 (#190, tracked under improvements)

**Pending (28)** — Phases 6-11:
- Phase 6 — test backfill (1): pr-fbda1a8
- Phase 7 — evidence-gated bug fix loop (4): pr-b42059d, pr-8ed578d, pr-8422dea, pr-c2397e2
- Phase 8 — post-activation refinements + regression-corpus expansion (4): pr-b77702b, pr-2c060b2, pr-70d02ed, pr-a1f267a
- Phase 9 — headless / unsupervised hardening + single-prompt capstone (7): pr-ca6859f, pr-6f9301e, pr-ed10ac4, pr-b3b8df0, pr-98f670e, pr-e2b7fdf (realistic capstone), pr-0cf3626 (exact-ProgramBench offshoot)
- Phase 10 — QA loop surface improvements (8): pr-9603d04, pr-7d5d036, pr-06a96fa, pr-2680fbf, pr-51586d2, pr-b59f0c7, pr-0b14f2c, pr-f4dc8a2
- Phase 11 — sign-off / acceptance gate (3): pr-2d5f712, pr-8e693f6, pr-ff9b728 (buildable now; soft-aligns with Phase 10)

**Cross-phase sequencing note**: Phase 7 (evidence + coverage gates on the existing scenario model) and Phase 10 (scenarios → regression-test bindings, new-regression authoring, mocks at authoring surface) both reshape the QA loop. Phase 10 changes the underlying scenario model that Phase 7's gates measure against. Recommended order: land Phase 10's regressions-as-scenarios chain (pr-7d5d036 → pr-06a96fa → pr-2680fbf → pr-51586d2) before Phase 7's coverage stack (pr-b42059d → pr-8ed578d → pr-8422dea → pr-c2397e2), so the coverage gates measure the post-Phase-10 flow. If sequenced the other way, Phase 7 PRs may need amendment after Phase 10 lands.

**Phase 11 supersessions**: the bug-fix (`pr-e3a711c`) and improvement-fix (`pr-d39a7fb`) watchers are generalized into one plan auto-start watcher and the programmatic `auto_start.py` orchestration is removed (both in `pr-ff9b728`); `pr-b77702b`'s per-plan `auto_merge` gating is subsumed by sign-off + per-plan gating, but its **dep-merge preamble survives** (rescoped, stays in the impl session's start prompt). The merged watchers stay in history; their plan-specific code is replaced.

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

### PR: Auto-sequence chain: TUI keypress + programmatic CLI ✅ MERGED (#172)
`pr-e58459b`

Chain start → review → QA on a single PR, halting at existing pause conditions and stopping before merge. Two entry points: TUI keypress (human use) and `pm pr auto-sequence <id>` CLI (watcher use). The CLI is essential — without it, watcher Claude sessions would have to drive the chain via tmux send-keys against the TUI.

## Phase 2: Discovery (after Phase 1)

### PR: Regression test sessions file bugs and improvements into correct plans ✅ MERGED (#171)
`pr-47940bc` (depends on: pr-539110b)

Prompt-addendum at the launch-path wrapper in `launch_qa_item()` so the existing Claude-based regression test sessions know to file findings via `pm pr add --plan bugs` or `--plan ux`. Mirror of `pr-539110b` for regression tests. Verdicts unchanged.

### PR: Watcher-target window for regression test launches ✅ MERGED (#173)
`pr-97ddabf` (depends on: pr-47940bc)

Add an optional `target_window` parameter to `launch_qa_item()` so watcher-driven launches stay in the watcher's pane and human launches keep their current main-window behavior.

### PR: Discovery supervisor watcher (BaseWatcher subclass) ✅ MERGED (#174)
`pr-271cb3a` (depends on: pr-47940bc, pr-97ddabf)

New `pm_core/watchers/discovery_supervisor.py` subclass + `generate_discovery_supervisor_prompt()`. Each tick reads `pm/watchers/discovery.log` and decides whether to launch a regression test, monitors in-flight tests, reconciles newly-filed bug/improvement PRs (dedup against open PRs in the target plan), appends to the log, emits READY or INPUT_REQUIRED. User guidance flows in automatically via the Watcher notes section.

## Phase 3: Implementation watchers (after Phase 1)

### PR: Bug-fix implementation watcher (BaseWatcher subclass) ✅ MERGED (#177)
`pr-e3a711c` (depends on: pr-e58459b)

New `pm_core/watchers/bug_fix_impl_watcher.py` + `generate_bug_fix_impl_prompt()`. Each tick reads its work log, scans `plan=bugs` for pending PRs, picks the best candidate dynamically (severity + recurrence + work-log signals + user notes), advances via `pm pr auto-sequence`, and auto-merges on QA PASS. Detects stuck/loop-failing PRs and escalates via INPUT_REQUIRED.

### PR: Improvement-fix implementation watcher (BaseWatcher subclass) ✅ MERGED (#176)
`pr-d39a7fb` (depends on: pr-e58459b)

Mirror of `pr-e3a711c` against `plan=ux`. Differences: longer cadence, gated merge (PRs that PASS QA are advanced to ready-for-merge and held for human taste check), taste-shaped prioritization guidance.

## Phase 4: Human surface (after Phases 2-3)

### PR: Watcher review session: Claude pane with work-log access ✅ MERGED (#175)
`pr-e84b43c` (depends on: pr-271cb3a)

Dedicated Claude session launched from the TUI with read access to all three watchers' work logs at `pm/watchers/*.log`, current plan/PR state, and per-test transcripts. Opens with a summary of recent activity, then chat-driven. Write actions (notes additions, pausing a watcher) require explicit confirmation.

## Phase 5: Activation (final)

### PR: End-to-end QA review and auto-start command ✅ MERGED (#178)
`pr-d60d185` (depends on: pr-271cb3a, pr-e3a711c, pr-d39a7fb, pr-e84b43c)

Final integration PR. Single command (`pm watcher start regression-loop` or similar) that brings up all three watchers with sensible defaults — without this, users have to start each watcher individually. Also serves as the end-to-end QA pass: once everything else has merged, exercise the full autonomous loop and catch integration gaps the per-PR reviews can't see.

## Phase 6: Test backfill — and bridge between old and new QA flows

### PR: Bridge old and new QA flows — tests for merged watchers under Phase 10 model
`pr-fbda1a8` (depends on: pr-d60d185, pr-06a96fa, pr-2680fbf, pr-51586d2)

The three concrete watcher classes and four new prompt builders shipped without direct unit tests — covered only by the BaseWatcher framework tests and the live operator markdown. **And** they shipped under the old INSTRUCTION+ARTIFACT scenario model. This PR is the bridge between Phases 1-5 and Phase 10: it adds the missing tests using FakeClaudeSession (`pr-abcf70f`) and FakeGitHubBackend (`pr-9603d04`, Phase 10), AND it re-exercises every merged Phase 1-5 feature against the new regressions-as-scenarios flow.

Scope:
1. Per-class watcher tests (`tests/test_{discovery_supervisor,bug_fix_impl_watcher,improvement_fix_impl_watcher}.py`) — scenarios bind to regression tests (via `pr-06a96fa`) or trigger new-regression authoring (via `pr-2680fbf`), not INSTRUCTION+ARTIFACT.
2. Prompt-string assertions for the four new prompt builders (discovery_supervisor, bug_fix_impl, improvement_fix_impl, watcher_review_session) — verifying mocks awareness is wired at the new-regression authoring surface (`pr-51586d2`) and NOT at scenario planning.
3. Auto-sequence integration backstop covering the three paths flagged in `pr-e58459b`'s review.
4. Behavioral tests for `launch_qa_item`'s `target_window` (`pr-97ddabf`) and the regression-filing addendum (`pr-47940bc`).
5. **End-to-end re-validation of Phases 1-5 features under Phase 10's flow** — discovery supervisor launch+reconcile, bug-fix watcher pick-and-advance, improvement-fix watcher gated-merge, auto-sequence halt-at-pause, watcher review session opening, regression-filing routing. Prefer existing regression tests (`REGRESSION: <id>`); use `NEW_REGRESSION: <slug>` via `pr-2680fbf` where none exist, growing the library rather than expanding scaffolding.

This is the checkpoint that confirms the merged Phase 1-5 features still behave correctly under the new model before declaring the regression loop ready for unsupervised operation.

## Phase 7: Evidence-gated bug fix loop (post-activation hardening)

Goal: tighten the bug-fix flow until the loop can run unsupervised. The earlier phases got reproduce→fix→verify into the prompt; these PRs make each step produce on-disk evidence the watcher / verdict gate can hard-check.

**Sequencing with Phase 10**: five of the six PRs in this phase add coverage and verdict gates on the QA scenario model. Phase 10 changes that model. Recommended: land Phase 10's regressions-as-scenarios chain first so the coverage gates measure the new flow; otherwise the Phase 7 gates need amendment after Phase 10 lands (see the cross-phase sequencing note in Status).

### PR: Bug-fix flow surface TUI QA repro instructions in session prompt ✅ MERGED (#190)
`pr-6be8ee6` (plan=improvements)

Adds a "did you reproduce on pre-fix code?" gate to `_BUG_FIX_FLOW_BLOCK` and references `pm/qa/instructions/tui-manual-test.md` for TUI bugs. Tracked under improvements; the bug-fix repro/verify captures land in `$(pm qa captures-path)/impl/` (per `bug_fix_prompts.py`).

> **Closed — `pr-eb450a0` (persist pre-fix/post-fix evidence as `pm/evidence/*.md`):** its premise — a deterministic gate over session-written repro artifacts — is unsound, because nothing binds a session-written capture to the code state that produced it (the sha in the file is self-reported, not proof). The *verifiable* machine-checkable repro is the **harness-run regression test** (Phase 10: fails at the pre-fix parent sha, passes at the fix sha, both run by the runner), and the qualitative "is this real evidence / no shortcuts" judgment is the **sign-off step** (Phase 11). Repro/verify captures already persist to `/impl/`; no separate `pm/evidence/` store.

### PR: QA code coverage of exercised lines factors into PASS verdict
`pr-b42059d` (pending)

Per-line coverage data emitted from QA scenario runs and surfaced into the verdict. Foundation for the fix-line gate below.

### PR: Fix-line coverage gate ties coverage to the diff
`pr-8ed578d` (depends on: pr-b42059d)

PASS additionally requires that the lines added/modified by the PR were executed by at least one QA scenario. Closes the loophole where overall coverage passes while the fix code never runs. Surfaces a separate "fix-line coverage" percentage; uncovered changed lines must be explicitly justified in PR notes.

### PR: Extended coverage measures (path, user-story)
`pr-8422dea` (depends on: pr-8ed578d)

Beyond line coverage: branch/path coverage on the diff and user-story coverage of QA scenarios. Strengthens the verdict signal once line and fix-line gates are in place.

### PR: QA refinement prompt asks for additional steps that improve coverage
`pr-c2397e2` (depends on: pr-0b14f2c)

When coverage gates fail, the refinement prompt asks the QA planner for additional scenarios specifically targeting the uncovered fix-line set. Closes the loop between gate failure and scenario growth.

**Interaction with `pr-0b14f2c`** (Phase 10 — planner adds/replaces scenarios mid-run): both PRs extend planner behavior after the initial plan emits. `pr-0b14f2c` is the user-driven (`+` / `r` / `R` keypress) path; `pr-c2397e2` is the verdict-gate-driven (coverage-gap-detected) path. They share the same underlying "add scenarios to a running batch" machinery — implementing `pr-0b14f2c` first gives `pr-c2397e2` the splice/re-aggregate primitives for free, and `pr-c2397e2`'s coverage-targeted prompt becomes a new programmatic caller of that primitive rather than a parallel mechanism. Sequence: `pr-0b14f2c` first, `pr-c2397e2` builds on top.

## Phase 8: Post-activation refinements + regression-corpus expansion

PRs added after the loop landed, addressing gaps surfaced once the watchers were running in anger. Two themes — a dep-merge-on-start refinement (`pr-b77702b`, rescoped — see below) and three regression-corpus expansion PRs (`pr-2c060b2`, `pr-70d02ed`, `pr-a1f267a`).

### Theme 1: workflow refinement

#### PR: Dep-merge preamble in the PR start/impl prompt for unmerged deps
`pr-b77702b` (pending)

Injects a dep-merge preamble into the **implementation session's** start prompt when the PR has unmerged `depends_on` deps: it lists the unmerged deps + their branches and instructs the session to merge each into its workdir before working, so iteratively-developed chains stay coherent without each PR landing on master first. The merge must run in the impl session because the workdir is set up programmatically at start and is only available there — not to the plan watcher, which only decides *when* to start. Omitted entirely when all deps are already merged or there are none.

*(Rescoped: the per-plan `auto_merge=false` half of this PR's original scope is superseded by Phase 11 — the plan auto-start watcher's per-plan gated config + the sign-off step's gated mode. See Phase 11.)*

### Theme 2: regression-corpus expansion (3 PRs)

Three Claude-driven regression-corpus expansion PRs, filed together. Same pattern (markdown in `pm/qa/regression/`, run via `launch_qa_item`, scheduled by the discovery supervisor `pr-271cb3a`), split for tight QA scope per PR. All three are independent of Phase 10 code-wise but land more usefully after `pr-06a96fa` (downstream QA scenarios exercising these surfaces bind to these regression tests via `REGRESSION: <id>` rather than INSTRUCTION+ARTIFACT).

#### PR: Claude-based regression test — CLI output rendering at varied terminal widths
`pr-2c060b2` (pending)

`pm/qa/regression/cli-output-widths.md` — resizes a tmux pane to randomly-chosen widths (60–180, seeded RNG, plus edge values), captures `pm pr list` / `pm pr ready` / `pm plan list` output, asks Claude to flag layout bugs (overflow, mid-word breaks, miscounted wide-char icons) and improvements (technically-correct-but-ugly). Motivated by two real bugs from a single manual session that unit tests cannot enumerate.

#### PR: Regression coverage — watcher behavior and review session
`pr-70d02ed` (pending)

Four new markdowns covering the watcher / observation surfaces from Phases 2-4:
- `discovery-supervisor-tick.md` — tick against fixture state; verify work-log read, regression-test launch in watcher window (`pr-97ddabf`), dedup + reconcile, log append, READY emit; variants for cold start / rolling context / in-flight continuation
- `bug-fix-watcher-pick-and-advance.md` — pick correct candidate via prioritization + Watcher notes, invoke `pm pr auto-sequence`, advance impl→review→QA→auto-merge; variants for at-cap, stuck NEEDS_WORK loop, reproduce-failure
- `improvement-fix-watcher-gated-merge.md` — same shape against `plan=ux`; stops at qa-pass, human merges between ticks, no re-attempt
- `watcher-review-session-summary.md` — opening summary across all three watchers, follow-up query, remediation flow (add Watcher-section note, verify next tick picks it up)

Folds in the opportunistic audit: as scenarios run, Claude is asked to flag *other* uncovered surfaces and file improvement PRs proposing regression tests, complementing `pr-f4dc8a2`'s static auditor.

#### PR: Regression coverage — auto-sequence chain pause conditions
`pr-a1f267a` (pending)

`pm/qa/regression/auto-sequence-halt-conditions.md` — exercises every documented pause condition of the chain (`pr-e58459b`) on both entry points (TUI `O` keypress + `pm pr auto-sequence <id>` CLI): impl idle-no-spec, review INPUT_REQUIRED, QA INPUT_REQUIRED, stop-before-merge (auto-merge=false or improvement-gated), review NEEDS_WORK loop, QA NEEDS_WORK loop, max-iterations hit. Verifies each pause halts correctly and resumes from the right state.

## Phase 9: Headless and unsupervised hardening + single-prompt capstone

Push the loop from "autonomous with a human in reserve via INPUT_REQUIRED" to "autonomous and recoverable with no human in the path." Then exercise the hardened loop end-to-end as the realistic single-prompt task evaluation (`pr-e2b7fdf`) — the capstone of Phases 1-10. An exact-ProgramBench offshoot (`pr-0cf3626`) runs the same machinery against ProgramBench's public benchmark for leaderboard submission.

Three pieces of hardening (self-recovery playbooks, no-progress detection, headless runtime), one scenario-quality safety net (false-PASS supervisor), and the auto-synthesis primitive that produces QA instructions from a task envelope. The capstone PR composes all of them.

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

### PR: Realistic single-prompt task — internet + directive + post-run integrity audit (CAPSTONE)
`pr-e2b7fdf` (depends on: pr-ca6859f, pr-6f9301e, pr-ed10ac4, pr-b3b8df0, pr-fbda1a8).

The end-to-end goal of Phases 1-10: a single-prompt task evaluation that mirrors how a real engineer works. Layer pm on top of a cleanroom image; a leader Claude session uses pm itself as its orchestration tool, files plan + PRs, drives them through the Phase 10 QA flow, produces a working result.

Inspired by ProgramBench (https://programbench.com) but deliberately not its exact shape. ProgramBench's offline-only constraint (no internet, only `/workspace/executable` + docs) is artificial; real engineers have the internet. The realistic version uses three constraints instead:

1. **Internet access** — agent has the same web access a real engineer would. No artificial sandboxing of common knowledge.
2. **Directive + provided materials** — task envelope (`pm/tasks/<id>/`) contains a written `directive.md`, `materials/` (the docs / reference behavior / examples), and an `allowlist.yaml` describing what may be consulted.
3. **Post-run integrity audit** — `pm_core/bench/audit.py` walks the leader's tool-use transcript (web fetches, file reads, command executions) against the allowlist and emits a structured `audit.md`. Verifies the agent did NOT reference the reference implementation's source, task-specific test cases, or task walkthroughs. This is the load-bearing realism check — with internet, agents could trivially Google the answer if findable; the audit is what makes the score meaningful.

Pieces: leader prompt template (sibling of `generate_prompt` / `generate_review_prompt`), task envelope format, adapter CLI (`pm bench realistic --task <path>`), integrity audit module, reproducibility Dockerfile, end-to-end fixture test. Reuses the auto-synthesis primitive (`pr-b3b8df0`) to produce QA instructions from the task envelope.

**Depends on `pr-fbda1a8`** (the bridge PR): the leader spawns the full autonomous loop, so any silently-regressed Phase 1-5 feature would make the leader fail for reasons unrelated to the task. The bridge confirms the loop is sound under Phase 10's flow before this PR depends on it end-to-end.

### PR: Offshoot — exact ProgramBench task as a separate runnable
`pr-0cf3626` (depends on: pr-e2b7fdf, pr-b3b8df0)

Same machinery as the capstone above, but with the realism constraints flipped to match ProgramBench's defined shape: internet blocked at the network-namespace boundary (model API only), inputs are `/workspace/executable` (chmod 111) + docs, verification is ProgramBench's binary-behavior comparison, submission is the `/workspace/` tarball. Adapter CLI variant: `pm bench programbench --task <id>`. Filed as an offshoot because (a) the realistic version is the primary goal of the loop and (b) ProgramBench's offline constraint is more of an opportunistic public-leaderboard target than a realistic working mode. Reuses the leader prompt + adapter CLI + headless runtime from the capstone; the only ProgramBench-specific pieces are the stricter firewall, the binary-comparison verdict path, and the tarball extraction shape.

## Phase 10: QA flow redesign — regressions as scenarios, mocks at the authoring surface

The most consequential pending phase: replaces the underlying QA scenario model. Where Phases 1-5 built the autonomous-loop substrate and Phases 7-9 hardened it, Phase 10 changes what the loop is *scheduling against*. After this phase lands, the regression library compounds — every QA run that hits a new surface adds a regression test, and every subsequent QA run reuses what's accumulated. This is what turns the loop from "an automation around the existing scenario format" into a system that gets stronger over time.

Filed in two waves: most during `pr-6be8ee6`'s QA iteration once the loop was exercised in anger (pr-7d5d036, pr-06a96fa, pr-b59f0c7, pr-0b14f2c, pr-f4dc8a2); the rest (pr-9603d04, pr-2680fbf, pr-51586d2) during a plan-review session on 2026-05-14 that surfaced the regressions-as-scenarios + new-regression-authoring + mocks-at-authoring chain.

The chain (PRs that together form the redesign): `pr-9603d04` (GitHub mock substrate) and `pr-abcf70f` (FakeClaudeSession, plan-regression, in_review) → `pr-7d5d036` (regression-runner containment cleanup) → `pr-06a96fa` (scenarios bind to regression tests) → `pr-2680fbf` (planner authors a new regression when none fits) → `pr-51586d2` (mocks awareness at the new-regression authoring surface). Other Phase 10 PRs (`pr-b59f0c7`, `pr-0b14f2c`, `pr-f4dc8a2`) are independent improvements that compose with the chain.

> **Re-testing obligation for Phases 1-5**: every PR in Phases 1-5 was implemented and QA'd under the *pre-Phase-10* QA flow — INSTRUCTION+ARTIFACT scenarios, mocks injected at scenario planning (later stripped by `pr-6be8ee6` / commit `3eb89e6`), no regression-test binding, no new-regression authoring step. When Phase 10's chain lands (`pr-06a96fa` → `pr-2680fbf` → `pr-51586d2`), the regression library becomes the canonical surface and the QA loop's verdicts mean something different. Every merged feature in Phases 1-5 (the three watchers, the auto-sequence chain, the discovery supervisor, the regression-filing addendum, watcher-target windows, the human review session, the auto-start command) needs to be re-exercised under the new flow. The bridge PR that performs this re-validation is `pr-fbda1a8` (Phase 6 — see below), which depends on Phase 10's chain so it runs only after the new flow lands.

### PR: GitHub backend mock for regression tests
`pr-9603d04` (pending)

Sibling of `pr-abcf70f` (FakeClaudeSession) for the GitHub side. Provides a scriptable `FakeGitHubBackend` (or transport-level fake) so regression tests can exercise github-backend code paths — PR create, status sync, draft↔ready transitions, comments, merge, post-merge pull, rate-limit / conflict / merged-elsewhere responses — without hitting the real GitHub API. Without this, regression coverage stops at the GitHub boundary and bug-fix watchers cannot reproduce GitHub-specific bugs deterministically.

### PR: Bug: `pm tui test` hardcodes "testing against the pm tmux session"
`pr-7d5d036` (depends on: pr-abcf70f, pr-9603d04)

The regression-runner harness assumes the test target is the host pm tmux session; wrong for containers and for non-pm targets. Cleanup of the runner's surface framing and containment model so regression runs don't leak state into the caller's repo. Adds FakeClaudeSession + FakeGitHubBackend as dependencies so the cleaned-up runner can drive both Claude and GitHub deterministically from the start. Prerequisite for using regression tests as durable QA flow drivers (`pr-06a96fa`).

### PR: QA scenarios reuse regression tests as their flow driver
`pr-06a96fa` (depends on: pr-7d5d036)

Switch QA scenarios from "instruction (setup) + artifact recipe (drive/capture)" pairs to binding directly to a regression test, with per-scenario assertions layered on top. The library of exercised user flows grows by accumulation rather than per-PR effort; the same flow is driven the same way across PRs so behavior drift gets caught; captures from regression runs feed both the regression history and the QA evidence record. INSTRUCTION/ARTIFACT remain as a fallback for one-shot probes/oracles; the new-regression-authoring step (`pr-2680fbf`) is the preferred path when no existing regression fits.

### PR: QA scenario planner authors a new regression test when none fits
`pr-2680fbf` (depends on: pr-06a96fa)

When the planner classifies a scenario's flow and no existing regression test in `pm/qa/regression/` drives that flow, it authors a new regression test as part of the QA run instead of falling through to INSTRUCTION+ARTIFACT scaffolding. Planner emits `NEW_REGRESSION: <slug>` alongside the existing `REGRESSION: <id>` field; a sub-step drafts `pm/qa/regression/<slug>.md` following existing conventions; the scenario binds to the drafted regression by slug. The drafted file commits to the PR's branch and is automatically in scope for the discovery supervisor (`pr-271cb3a`) on subsequent ticks. This is the step that makes the regression library compound — without it, the planner takes the easy INSTRUCTION+ARTIFACT path and the library never accumulates new drivers. This is also the load-bearing surface for mocks awareness — see `pr-51586d2`.

### PR: Mocks awareness in the new-regression authoring flow
`pr-51586d2` (depends on: pr-abcf70f, pr-9603d04, pr-06a96fa, pr-2680fbf)

The shared mocks library, `pm/qa/mocks/` directory, `pm qa mocks` CLI, frontmatter convention, and loader helpers already exist (shipped by `pr-942aa21`, plan-qa, PR #125, merged March 2026). The prompt-side wiring was deliberately stripped by `pr-6be8ee6` (#190, commit `3eb89e6`) because indiscriminate injection at scenario planning produced noise — workers invented mocks the diff didn't need or followed spec-level mock guidance disconnected from what they were driving. The mocks belonged at a different surface.

This PR reconnects the library at the right surface: the new-regression authoring prompt introduced by `pr-2680fbf`. A regression test specifies a flow against a surface, so the moment a regression is being drafted is exactly when "which mocks apply to this surface?" is well-posed. Two constraints: (1) **diff-scoped enumeration** — the mocks block lists only mocks whose declared `target_surface` overlaps with files in the PR's diff; (2) **no fallback to scenario-prompt injection** — the injection point is the new-regression authoring prompt, period. The pr-942aa21-era pattern of injecting at scenario planning stays gone. FakeClaudeSession (`pr-abcf70f`) and FakeGitHubBackend (`pr-9603d04`) register as the bootstrap entries when they merge. Note `note-a1c6f30` on `pr-942aa21` has the original rationale; commit `3eb89e6` has the strip rationale this PR's surface choice answers.

### PR: Capture reason strings for non-PASS verdicts
`pr-b59f0c7` (depends on: pr-6be8ee6)

Generalize the per-scenario `verdict_reason` field added for the refiner-rejection path to every place a non-PASS verdict comes out of an automated loop (main scenario workers, review-loop, watcher). Reasons land in `state.scenario_verdict_reasons[idx]`, flow into `qa_status.json` and `verdict.md`, and render as a one-line "↳ <reason>" continuation under each non-PASS verdict in status panes. Triage stops requiring pane-scrollback archaeology.

### PR: QA scenario planner allows adding scenarios mid-run or after initial plan
`pr-0b14f2c` (depends on: pr-6be8ee6, pr-2680fbf)

Let the planner add scenarios beyond the initial plan and let users re-run NEEDS_WORK scenarios or replace INPUT_REQUIRED ones, so coverage gaps and earlier failures resolve without restarting QA. The overall verdict can transition from INPUT_REQUIRED or NEEDS_WORK back to PASS as added/replaced scenarios settle. New `+` / `r` / `R` keys in the scenarios pane pull the latest `QA_PLAN_START/END` block from the planner pane's transcript. Replaced scenarios' prior captures preserved under `scenarios/<n>/prior-N/`.

**Interaction with the regressions-as-scenarios flow**: a newly-added or replacement scenario may emit `REGRESSION: <id>` (existing) or `NEW_REGRESSION: <slug>` (planner authors one inline via `pr-2680fbf`). When it's `NEW_REGRESSION`, the authoring sub-step runs first — drafts `pm/qa/regression/<slug>.md` (with mocks-awareness from `pr-51586d2` if applicable), commits to the PR branch — and only then does the scenario itself run. Without this handoff, mid-run additions for surfaces lacking a regression would fall back to INSTRUCTION+ARTIFACT and defeat the Phase 10 redesign. The scenarios pane shows a per-scenario sub-status ("authoring regression…" → "running scenario…") so users see why a freshly-added scenario takes longer than an existing-regression-bound one.

Manual testing: drive the keypress flow against a real run with at least one NEEDS_WORK and one INPUT_REQUIRED scenario; also exercise an add-scenario that triggers NEW_REGRESSION and verify the regression file lands on the branch before the scenario runs; INPUT_REQUIRED is appropriate for the human-judged "load this plan block" moments.

### PR: QA library auditor — propose regression-test fills (with attached mocks)
`pr-f4dc8a2` (pending)

Static project-wide counterpart to `pr-2680fbf` (which authors regressions on-demand per scenario). Scans the project's user-visible surfaces (CLI subcommands, TUI keybindings, watcher entrypoints, backends), intersects with what `pm/qa/regression/` already covers, and proposes a markdown audit report with three tiers reflecting the Phase 10 hierarchy:

1. **Regression tests (primary)** — missing regression-test drafts for uncovered surfaces. Same proposal shape as `pr-2680fbf`'s runtime authoring, just batch.
2. **Mocks (attached to regressions)** — for each proposed or existing regression, mockable external dependencies that lack registry entries. Mocks never proposed standalone — they attach to a regression-test surface, consistent with `pr-51586d2`.
3. **Instructions / artifact recipes (fallback-only)** — flag legacy INSTRUCTION+ARTIFACT scaffolding that should migrate to regression tests; do not propose new entries except for genuine one-shot probes/oracles.

Proposals go to a report (no auto-apply) for human or scenario-author follow-up. Can be invoked manually (`pm qa audit`) or scheduled via the discovery supervisor (`pr-271cb3a`) as a periodic stale-library check.

## Phase 11: Sign-off / acceptance gate — the verdict router that closes auto-run

Everything before this phase produces verdicts; nothing decides what to *do* with them without a human. Phase 11 is the capstone: a first-class **sign-off step** — its own lifecycle status (`sign_off`) and its own window — that runs after QA finalization, reviews every scenario and step, and maps every terminal QA outcome to a next hop, so a PR can advance from QA all the way to merge — or back to the right earlier step — unattended. This is the literal mechanism behind the plan's thesis and the pitch's decisive open question (*can pm drive its own defect count down without a human reviewing every change?*): gated and autonomous are the same code path behind a flag, and flipping to autonomous and watching the bug count is the experiment.

It is distinct from the review loop. Review asks *is the code correct/clean*; sign-off asks *does the captured evidence prove the behavior, with no shortcuts, and is it mergeable*. It reviews PRs **by behavior** (BDD), which is why its human-facing surface is an HTML behavior report rather than a diff. Because it walks *all* scenarios and steps and aggregates evidence across every stage — including implementation captures, not just final QA (bug-fix PRs write repro/verify evidence to `$(pm qa captures-path <pr-id>)/impl/`) — it is a real step with its own window, not a quick inline gate.

It is also a **concretization** of the taste-check / merge-gating the impl watchers improvise today. Phase 11 doesn't run beside that machinery — it replaces it, and consolidates the two impl watchers into a single plan auto-start watcher that *is* the auto-start engine (see *Supersedes and consolidates* below). The division of labor: the **plan auto-start watcher shepherds a plan** (what to start, how many PRs in flight, high-level issues, keeping the plan accurate); the **sign-off step shepherds a single PR and its immediate implications** (the per-PR merge/route decision).

**The regression loop stays and closes through the plan watchers.** The discovery supervisor keeps scheduling regression runs, and *any* session — regression, review, QA, sign-off, impl — auto-files bug/improvement PRs (building on `pr-539110b` and `pr-47940bc`). Those land in the `bugs` and `ux` plans, where the per-plan auto-start watchers pick them up and drive them through sign-off. That's the closed loop: discovery → auto-filed PR → plan watcher → sign-off → merge (or back).

**Two invariants that make autonomy trustworthy:**

- **Router-only.** The checkoff never edits code. It judges, annotates (`pm pr note`), files follow-up PRs, and sets the next hop. Every code edit happens in impl/qa, so it always passes back through review+qa — including edits the checkoff prompted. A judge that never writes the code it approves is what makes an autonomous merge defensible.
- **Conservative toward not-merging.** Misclassifying a real gap as "scenario error → re-qa" merges incomplete work (the predicted failure mode); the reverse only wastes an impl cycle. So on genuine ambiguity the checkoff *raises INPUT_REQUIRED itself* and escalates rather than merging.

**Supersedes and consolidates earlier work (and removes the dead code):**

Sign-off concretizes the taste-check / merge-gating the impl watchers improvise today, so Phase 11 *replaces* that machinery rather than sitting beside it; the superseded code is removed (`pr-ff9b728`).

- **The two impl watchers generalize into one plan auto-start watcher.** `pr-e3a711c` (bug-fix, merged) and `pr-d39a7fb` (improvement-fix, merged) become a single watcher parameterized per plan — gated vs autonomous, mandated checks (the improvements *taste* check), and a watcher-chosen **max in-flight PR** count. Same functionality, one class; the two plan-specific watchers and their near-duplicate prompt builders are removed.
- **That plan watcher *is* the auto-start.** It replaces the programmatic engine in `pm_core/tui/auto_start.py` (`check_and_start`, `_auto_start_review_loops`, `_auto_start_qa_loops`, `auto_sequence_for_pr`, the one-shot `_transitive_deps` walk). The watcher starts ready PRs from its plan, runs the per-PR auto-sequence chain (`pr-e58459b`, kept), resolves high-level issues, and keeps the plan working as implementation + sign-offs proceed. The TUI auto-start toggle starts/stops this watcher; the old programmatic orchestration is removed. The existing `AutoStartWatcher` (pane monitoring) folds into this watcher's "resolve high-level issues" duty.
- **Sign-off owns the per-PR decision; the watcher shepherds the plan.** Per-PR merge/route decisions defer to the sign-off step. `pr-b77702b`'s per-plan `auto_merge=false` and the improvement watcher's gated-at-QA-PASS are subsumed by the watcher's per-plan gated config + sign-off's gated mode. Its **dep-merge preamble is not absorbed** — that stays in the implementation session's start prompt (the workdir is programmatic, only available to the impl session); `pr-b77702b` is rescoped to just that part.
- **Real-code feedback flows back into the plan.** The watcher integrates what implementation/sign-off learns into the plan file (the dynamic plan/graph mutation), so the plan stays accurate as reality diverges from the original design.
- **Watcher work logs become plan notes.** Per-watcher continuity (`pm/watchers/*.log`) is recast as **plan notes** carried in the plan files (analogous to PR notes), so a plan watcher's state is human-readable in the plan and reachable from the behavior interface. The flat log files are removed.

Three earlier mechanisms are *absorbed*, not duplicated:
- **Meta-QA builds on the scenario quality supervisor (`pr-98f670e`).** `98f670e` catches false-PASS per scenario, inline; sign-off's anti-shortcut pass is the PR-level review over scenarios it already vetted (cross-scenario gaps + mergeability), trusting per-scenario depth to `98f670e`.
- **The loop guard reuses the no-progress primitive (`pr-ed10ac4`).** `ed10ac4` is within-loop; the loop guard is its across-bounce counterpart and reuses the hashing rather than a parallel mechanism.
- **Evidence is the captures + the harness-run regression results** — `/impl/` and `/scenarios/` captures plus the Phase 10 regression test's pre-fix-fails / post-fix-passes result; sign-off judges them. Provenance comes from the harness running the regression at a known sha, not from a session-written file (which is why the `pm/evidence` gate idea was dropped — see Phase 7).

### PR: Sign-off step — dedicated window + lifecycle status + comprehensive verdict router
`pr-2d5f712` (buildable now — no hard deps; *soft*: aligns with `pr-b59f0c7` reason strings and the `pr-06a96fa` evidence model when they land, but reads the current verdict+capture surface and degrades gracefully)

A distinct flow step, not embedded logic. **New `sign_off` lifecycle status** — extend the enum `{pending, in_progress, in_review, qa, merged, closed}` (`pm_core/cli/pr.py:169`, `:314`) across store validation, `--status` choices, the `qa_status` color map, the tech tree, and the transition points (qa-finalize → `sign_off`; `sign_off` → merged or back to in_progress/in_review/qa on a bounce). **Dedicated window** like review/qa (pane registry, role-based dedup, the now-fixed window-switch path): a Claude pane drives the review and the behavior report (`pr-8e693f6`) is the surface shown there; approve/reject + discussion happen in this window.

**Comprehensive + cross-stage evidence.** Walk *every* scenario and *every* step, and read the *whole* per-PR captures dir — not just final-QA captures. Implementation generates evidence too: bug-fix PRs follow reproduce→fix→verify and write to `$(pm qa captures-path <pr-id>)/impl/` (the "primary evidence" per `bug_fix_prompts.py`), QA scenarios under `scenarios/<n>/`. Sign-off includes impl + qa (+ review) so a bug-fix's repro and post-fix verification are part of the record.

Then the verdict router runs after QA finalization over every scenario's verdict + reason (`pr-b59f0c7`), the aggregated captures/evidence, the diff vs master, and the PR's scope. Two evaluations — (1) does the captured behavior support the diff's claims; (2) meta-QA / anti-shortcut: was the QA itself rigorous (thin evidence, a scenario that drove a mock instead of the real path, an obvious uncovered edge case) — then routes:

- **PASS** (verified) → evidence + anti-shortcut review → merge (or human gate).
- **PASS** (unverified, e.g. the verifier-cwd case) → harness problem → re-qa; do *not* bounce to impl.
- **NEEDS_WORK** (scenario fixed it itself) → a code change happened → back through review **and** qa; validate the fix is real and shortcut-free.
- **INPUT_REQUIRED** → classify the cause and route: misframed/mistaken scenario → note for next qa run → re-qa (qa-gen reads notes, so this closes); real gap → note → back to impl; assumed-missing feature → agent decides between filing a new PR + `depends_on` (block) or expanding scope; nice-to-have → agent decides defer-to-new-PR vs include-if-trivial; impossible/out-of-scope → note the limitation → accept or bounce with the constraint.

Every classification + chosen hop is recorded as a `pm pr note` (audit trail, prefer-pm-pr-notes), so an autonomous merge is inspectable after the fact. Gated vs autonomous is a config flag on this path. Loop-guard + re-loop wiring (and the plan auto-start watcher) are `pr-ff9b728`; the per-PR behavior report + dashboard are `pr-8e693f6`.

This step **supersedes** the existing taste-check / gated-merge handling — the improvement watcher's gated-at-QA-PASS, `pr-b77702b`'s `auto_merge` gating, and any ad-hoc sign-off/approve code. That logic moves here; the old paths are removed (cleanup lives in `pr-ff9b728`).

### PR: Sign-off UI — per-PR BDD report + all-PR behavior dashboard (HTML)
`pr-8e693f6` (depends on: `pr-2d5f712` — the report is the surface shown in the sign-off window; forward-compatible with the `pr-06a96fa` evidence model)

The human-facing surface for sign-off — the per-PR report plus the dashboard that indexes them, combined since they share a generator and storage layout.

**Per-PR report (BDD):** A self-contained HTML report written **alongside** the captures it references (`~/.pm/sessions/<tag>/captures/<pr_id>/report.html`), pointing directly at the real webm/png/html evidence — no copy. (There is no capture GC today: `cleanup_pr_resources` never touches the captures dir, so co-locating is safe for v1; a future GC phase would snapshot instead.) BDD-shaped: per behavior, the flow (STEPS / Given-When-Then), the verdict + reason, and the evidence inline/linked, plus a top-of-page status summary and the checkoff's recommendation/next hop. Terminal panes can't show webm — so the browser page is the sign-off surface; the tmux checkoff window holds the discussion + approve/reject. Generated at sign-off time.

**Dashboard:** A single top-level HTML index where all PRs are reviewed **by behavior + short status summaries** — fits the BDD goal. Lists every PR with a one-line behavior/status summary linking to its per-PR `report.html`; simple client-side **filtering** by merged/unmerged and by status, so reports for both merged and unmerged PRs are reviewable and each PR's position in the flow is visible. **Detect-missing**: when a per-PR report is absent (never generated, or removed by a future GC) the index shows that state instead of a dead link, with a **regenerate flow** to rebuild it on demand from retained verdicts/evidence (re-running a capture only if needed). Static export (open a file, no server) is the v1 lean; co-located with the captures.

**Reachable context.** The interface surfaces the written record alongside the behavior, so a reviewer can sign off without leaving it: each PR's **description** and **PR notes**, and per plan the **plan notes** (the plan auto-start watcher's continuity, recast from the old work logs in `pr-ff9b728`). PR descriptions/notes are available today; plan notes land with `pr-ff9b728`.

### PR: Plan auto-start watcher — generalize the impl watchers; become the auto-start engine
`pr-ff9b728` (depends on: pr-2d5f712)

Replaces the two plan-specific impl watchers **and** the programmatic auto-start with a single **plan auto-start watcher** that shepherds a plan while sign-off shepherds each PR. (Heaviest PR in the phase, kept as a single PR per the design.)

**Generalize the impl watchers.** Fold `pr-e3a711c` (bug-fix) and `pr-d39a7fb` (improvement-fix) into one watcher parameterized per plan: gated vs autonomous, mandated checks (the improvements *taste* check), prioritization guidance. Same functionality, one class; the two concrete watchers and their near-duplicate prompt builders are removed.

**Become the auto-start engine.** This watcher *is* the auto-start. Remove the programmatic orchestration in `pm_core/tui/auto_start.py` (`check_and_start`, `_auto_start_review_loops`, `_auto_start_qa_loops`, `auto_sequence_for_pr`, the one-shot `_transitive_deps` walk). The watcher picks ready PRs from its plan (deps satisfied), runs the per-PR **auto-sequence chain** (`pr-e58459b`, kept — now with the `qa → sign_off → merge` tail), and stops. The TUI auto-start toggle becomes start/stop for this watcher.

**Dep-merge on start.** When a PR's `depends_on` PRs aren't merged yet, its dependency branches must be merged into the workdir before work begins — this stays in the **implementation session's** start prompt (`pr-b77702b`), *not* the watcher. The workdir is set up programmatically at start and is only available to the impl session, so the watcher can only decide *when* to start the PR; the merge happens inside the session. (Omitted when all deps are already merged.)

**Max in-flight PRs (new).** The watcher chooses how many PRs to drive concurrently rather than walking one target's dependency tree serially — a change to auto-start. Bounded, watcher-judged each tick from plan state + guidance.

**Defer per-PR decisions to sign-off.** The watcher does not decide merge/route per PR — the sign-off step does. The watcher handles plan-level concerns: what to start, concurrency, resolving high-level issues, and keeping the plan correct as work lands.

**Real-code feedback into the plan (dynamic plan/graph mutation).** When sign-off (or the watcher) finds the plan needs a new PR — a missing dependency, an assumed-missing feature, a new feature — the watcher files the PR(s) + sets `depends_on` (insert upstream); **additively** edits the plan file to add the `### PR:` section(s) (no plan-file writer exists today — `plan_parser` only reads; never reword/delete existing content); re-resolves which PRs are ready so newly-inserted upstream work starts before the blocked PR; commits plan + `project.yaml` atomically and records a `pm pr note`. Cycle detection on dependency insertion; gated mode surfaces the plan edit before starting; additive-only is the autonomous-mode guarantee.

**Watcher continuity = plan notes.** The watcher's per-tick continuity (today `pm/watchers/<name>.log`) is recast as **plan notes** carried in the plan file — analogous to PR notes, human-readable in the plan, and surfaced in the behavior interface (`pr-8e693f6`). The flat log files go away.

**Loop safety.** Re-loop invariant: any code/content change routes back through review **and** qa before merge; note-only actions (incl. notes on *other* PRs) don't re-trigger review. Loop guard: default **10** bounces/PR (configurable), reset on real progress; repeated root cause escalates to INPUT_REQUIRED early. Reuses `pr-ed10ac4`'s no-progress hashing at the across-bounce layer.

**Single-PR mode.** The same per-PR auto-sequence chain (`qa → sign_off → merge`) run on demand for one PR — `pm pr auto-sequence <id>` extended past merge, with a thin `pm pr signoff <id>` to enter just the sign-off step. No parallel `pm pr auto` command.

**Removed (dead code):** `auto_start.py`'s programmatic orchestration; `bug_fix_impl_watcher.py` + `improvement_fix_impl_watcher.py` and the `AutoStartWatcher` (all folded into the plan watcher); the `pm/watchers/*.log` flat files (replaced by plan notes); the improvement watcher's gated-at-QA-PASS path and `pr-b77702b`'s `auto_merge` gating (superseded by sign-off + per-plan config — its dep-merge preamble stays in the impl session, rescoped as `pr-b77702b`); any ad-hoc taste-check/sign-off code the sign-off step now owns.

## Success criteria

**Autonomous loop (Phases 1-5, met today):**
- Discovery runs unattended via the existing watcher framework, surfacing both bugs and improvements
- Findings are deduplicated post-hoc by the discovery supervisor and routed to the correct plan
- Bug fixes follow reproduce→fix→verify and land without manual kickoff
- UX fixes auto-sequence to ready-for-merge then wait for human taste check
- Implementation watchers detect and handle stuck/loop-failing fix sessions
- Users influence watcher behavior by editing `notes.txt` Watcher section, not by reaching into watcher state directly
- Humans interact with the loops via the watcher review session and `notes.txt`, not by direct watcher manipulation

**Evidence-gated bug fix (Phase 7, pending):**
- Bug-fix PRs cannot advance without machine-checkable pre-fix repro and post-fix verification artifacts on disk
- QA verdicts incorporate line, fix-line, path/branch, and user-story coverage signals
- Coverage gate failures trigger targeted scenario growth via the planner, not silent NEEDS_WORK loops

**Headless / unsupervised hardening + single-prompt capstone (Phase 9, pending):**
- INPUT_REQUIRED rate on a representative bug-fix corpus drops measurably after the self-recovery audit
- Autonomous loops can run end-to-end with no human-reachable surface (headless / benchmark_mode)
- No-progress safety stop short-circuits spinning review/QA loops before max-iterations
- Scenario quality supervisor catches false-PASS scenarios in headless mode before verdicts propagate
- **Capstone**: a single-prompt task (`pr-e2b7fdf`) produces a working result via the full Phase 10 autonomous loop under realistic constraints — internet on, written directive + provided materials, post-run integrity audit confirming no out-of-bounds references. The exact-ProgramBench offshoot (`pr-0cf3626`) succeeds on the public leaderboard.

**QA flow redesign (Phase 10, pending — the most consequential):**
- Regression library compounds: every QA run for an uncovered surface either binds to an existing regression test or authors a new one via `pr-2680fbf`; INSTRUCTION+ARTIFACT scaffolding decays toward zero except for genuine one-shot probes/oracles
- Mocks awareness is wired at the new-regression authoring surface only (`pr-51586d2`); the pre-strip scenario-planning injection pattern stays gone
- The QA library auditor (`pr-f4dc8a2`) periodically proposes fills aligned with the same hierarchy
- All Phase 1-5 features re-validated under the new flow via the bridge PR (`pr-fbda1a8`) before the regression loop is declared unsupervised-ready

**Sign-off / acceptance gate (Phase 11, pending — closes auto-run):**
- Sign-off is a first-class step with its own `sign_off` status and window (`pr-2d5f712`); it reviews every scenario and step and aggregates evidence across all stages, including implementation captures (`impl/`), not just final QA
- Every PR that finalizes QA gets an auto-generated BDD behavior report, and the dashboard (both `pr-8e693f6`) reviews all PRs by behavior + status with merged/unmerged filtering and regenerates missing reports
- The verdict router (`pr-2d5f712`) maps every terminal verdict to a next hop, edits no code, and escalates to INPUT_REQUIRED on genuine ambiguity rather than merging incomplete work
- A single **plan auto-start watcher** (`pr-ff9b728`) replaces the two impl watchers, the `AutoStartWatcher`, and the programmatic `auto_start.py` engine: it starts PRs from a plan, chooses max-in-flight concurrency, resolves high-level issues, and defers per-PR merge/route decisions to sign-off; the superseded watchers, gated-merge/taste-check, and `pr-b77702b` `auto_merge` code are removed
- The regression loop is closed end to end: discovery still schedules regression runs, any session auto-files bug/improvement PRs, and the per-plan watchers for `bugs` and `ux` drive them through sign-off. Plan-watcher continuity is carried as **plan notes** in the plan files (the old `pm/watchers/*.log` recast), and the behavior interface (`pr-8e693f6`) surfaces plan notes, PR descriptions, and PR notes alongside the reports
- The gate runs both on a single PR on demand and via the plan watcher; auto-run re-loops through review+qa on any code change, never on note-only actions; the loop guard (default 10) + repeated-root-cause escalation prevent infinite bounce loops
- When the router needs a new PR mid-run (missing dependency / assumed-missing feature / new feature), auto-start mutates the plan and graph live — files the upstream PR(s), inserts plan sections additively, re-resolves the dependency tree, and starts the new upstream work before resuming the blocked target — a case static auto-start can't handle today
- With the gate in autonomous mode, the measured defect count trends **down** without per-change human review — the pitch's decisive open question answered in the affirmative
