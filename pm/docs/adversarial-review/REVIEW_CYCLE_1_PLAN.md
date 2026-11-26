# Review Cycle 1: plan-regression.md (Adversarial)

Date: 2026-05-14
Artifact under review: `pm/plans/plan-regression.md` (385 lines, 25 pending PRs across Phases 6-10, 12 merged in Phases 1-5).
Reviewer: blind, fresh session. Has read the plan, the literature review, and spot-checked the merged Phase 1-5 code under `pm_core/watchers/` and `pm_core/prompt_gen.py` to confirm or refute architectural claims.

This review is deliberately tough. Where the plan is well-argued, that is noted briefly; the bulk of the effort goes to what is weak, missing, or hand-waved.

---

## Block 1 — Substance

### 1. Novelty: what is and isn't new

What is genuinely new, and the plan should foreground more confidently:

- **The compounding regression library** (`pr-2680fbf` + `pr-06a96fa`). CodaMosa and Fuzz4All produce throwaway suites; OSS-Fuzz has a durable corpus but it is fuzz-derived, not LLM-authored. A planner that drafts a regression markdown on demand, commits it to the branch, and hands it to a scheduler is, as far as the literature review surveys, not published. This is the most defensible novelty claim in the plan.

What the plan calls novel but is at best a reframing:

- **Three-watcher architecture.** The plan presents this as an architectural contribution. It is structurally Dependabot/Renovate + a polling QA bot — three queues with the same polling shape, different prompts. The Reflexion architecture (Actor, Evaluator, Self-Reflection) is closer in spirit than the plan admits. Calling the three-watcher count an "architecture" overstates it; they are three instances of one class. The novelty (if any) is the dynamic-prioritization choice, not the count.
- **"Post-run integrity audit"** in `pr-e2b7fdf`. The literature review correctly cites NIST CAISI as doing exactly this shape (LLM-reviewer over a transcript with allowlist semantics). The capstone's contribution is the *allowlist-narrowed* variant on a single task envelope, not the audit pattern itself. The plan should claim narrower novelty here.
- **"Mocks at the authoring surface."** This is a UX placement choice, not a research contribution. The plan reads as if Phase 10's mocks-awareness reroute is a discovery; in code terms it is moving a prompt block from one builder to another. Phrasing this as a "load-bearing surface choice" inflates its weight.

What the plan implicitly ignores from the watcher-bot tradition:

- **Mergify, Kodiak, bulldozer** (auto-merge gating bots). The plan's improvement-fix watcher's gated-merge behavior is exactly the policy these tools encode. Not citing them lets the plan position the gated-merge as new design when it is a known pattern.

### 2. Weakest contributions

1. **The "compounding" framing.** The plan calls compounding "the load-bearing change" (line 48) and re-asserts it five times across the document. But the compounding argument is currently *prospective*. There is no measurement of how many regression tests get authored per N QA runs, what fraction of subsequent runs reuse them, or how much the library grows before saturation. Without a target (e.g. "after 50 QA runs, ≥30 distinct regression markdowns exist; ≥60% of run-1 scenarios bind to an existing test") the claim is unfalsifiable. Compounding is being treated as definitional rather than as an empirical prediction; it reads like post-hoc justification for Phase 10's existence.

2. **The capstone PR (`pr-e2b7fdf`).** The single weakest pending contribution. It bundles five distinct things (leader prompt, task envelope format, adapter CLI, integrity audit, Dockerfile) under one PR, depends on five other pending PRs (`pr-ca6859f`, `pr-6f9301e`, `pr-ed10ac4`, `pr-b3b8df0`, `pr-fbda1a8`), and is positioned as the load-bearing realism check while resting on an LLM-as-auditor design with no calibration data. ImpossibleBench's 42-50% sensitivity number is mentioned in the literature review but not engaged with in the plan: the plan does not say what target sensitivity the audit needs to clear, how the audit will be evaluated for false negatives, or what happens if the auditor itself was contaminated. The PR also conflates two questions ("did the agent fetch the reference impl?" and "did the run actually produce a working result?") under a single "realistic" framing.

3. **`pr-fbda1a8` (the bridge PR).** Asks one PR to re-validate every Phase 1-5 feature under Phase 10's new flow. Scope items (1)-(5) in the PR description list at least 12 distinct test surfaces. The plan is asking a single PR to do work that, by the plan's own decomposition principle elsewhere (see `pr-2c060b2`/`pr-70d02ed`/`pr-a1f267a` filed as three PRs for tight QA scope), should be split into multiple. The bridge will either be too big to land or will silently drop scope.

4. **`pr-98f670e` (scenario quality supervisor).** The fix for false-PASS scenarios is to ask the same model "what did you actually verify?" in a follow-up turn. Self-Refine's well-documented failure mode is precisely that the same model is a bad judge of its own work. The plan's defense (a per-scenario amendment cap of 2) addresses runaway loops but not the underlying failure mode. There is no proposal for cross-model supervision (e.g. a different model family for the supervisor) and no empirical baseline for what fraction of false PASSes the supervisor catches.

5. **`pr-c2397e2` (coverage-gap-driven scenario growth).** The interaction with `pr-0b14f2c` (sequence first, build on top) is explained well, but neither PR specifies the stopping criterion for the growth loop. If coverage gate keeps failing because the diff covers an irreducibly hard line, the loop adds scenarios indefinitely. The fix-line coverage gate (`pr-8ed578d`) needs an explicit "justified exemption" path beyond "explicitly justified in PR notes" (line 182) — who validates the justification?

### 3. Methodological flaws and unrealistic assumptions

- **No measurement plan.** Phase 9's success criteria say "INPUT_REQUIRED rate drops measurably." Measurably against what baseline? On what corpus? With what statistical test? The single word "measurably" carries the entire empirical claim. The plan needs either a published baseline (e.g. SWE-Bench Verified, ProgramBench, or a held-out internal corpus of 20 bugs) or it has no claim.
- **No false-PASS data.** The scenario-quality supervisor is justified by "scenarios reliably produce thin artifacts" (plan line 267). "Reliably" is not quantified anywhere. If the rate is 5%, the supervisor is overkill. If 50%, the loop is broken. Without a measured rate, the PR is shooting in the dark.
- **Concurrency cap is hand-tuned.** The bug-fix watcher prompt hardcodes `concurrency_cap = 2` (`prompt_gen.py:1012`). The plan does not say why 2, not 1 or 5, or how the operator should tune it. With dynamic priority re-evaluation every tick, two PRs in flight may compete for the same fix; no analysis of the contention is offered.
- **Mocks-diff-scoping is underspecified.** `pr-51586d2` says mocks are enumerated "where declared `target_surface` overlaps with files in the PR's diff" (plan line 331). How is `target_surface` defined? File path globs? Module qualified names? Imports? Each choice has known failure modes (globs miss refactors; module names miss test files; imports require static analysis). The plan needs to pick one and defend it.
- **Auto-merge for bugs is asymmetric.** Bugs auto-merge on QA PASS; improvements wait for human taste check. The asymmetry assumes bug-fix quality is fully captured by tests but improvement quality is not. That assumption is load-bearing for the loop's safety, and no PR validates it. A 1-week pilot where bug auto-merges are sampled by a human reviewer would be the minimum to support it.
- **No rollback story.** What happens when an auto-merged bug-fix breaks master? The plan never discusses revert paths, post-merge regression detection, or the policy for when the discovery supervisor catches a regression introduced by a recently merged auto-fix. This is a gaping hole in an "unsupervised" loop.

### 4. Specific challenges asked by the calling prompt

#### Challenge 1: Is "compounding" load-bearing or post-hoc?

**Post-hoc.** The plan refers to compounding as load-bearing five times (lines 48, 50, 298, 324, 382) without ever proposing a measurement. Phase 10 could be valuable for reasons that have nothing to do with compounding (e.g. consistency of QA flow across PRs, ability to deterministically replay a flow via FakeClaudeSession). The compounding framing is doing rhetorical work — it makes Phase 10 sound like a research result rather than a refactor. A more honest framing would be "Phase 10 unifies the QA scenario format with the regression library; a side-effect is that the library may grow faster than under the old flow; whether it actually compounds we will measure in Phase 11."

#### Challenge 2: Is dynamic priority better than a priority queue, or underspecified?

**Underspecified.** Confirmed against `pm_core/prompt_gen.py:1085-1107`: priority is a free-form prompt instruction asking Claude to weigh severity, recurrence, age, and notes. The plan presents this as a deliberate bet (line 89 of lit-review: "a bet the literature does not really speak to"), but the prompt does not:
- specify a tie-breaker (two equally severe bugs);
- pin the weights (today's tick may prefer recurrence, tomorrow's age);
- log the reasoning so operators can audit picks.

AutoGen's explicit priority queue, in contrast, lets the operator inspect what is queued and why. The plan's choice is defensible *if* the loop measures the resulting churn (does the same bug get picked four ticks running because the LLM disagrees with itself?). With no measurement, the bet is invisible. The right strengthening is not "switch to a queue" but "log per-tick the candidate set + chosen PR + a one-line rationale, then audit over 50 ticks for thrash."

#### Challenge 3: Will the post-run integrity audit work?

**Unlikely at the bar the plan sets, given current monitor sensitivity.** ImpossibleBench's 42-50% sensitivity on complex multi-file cheating is the only comparable empirical anchor and it is grim. The plan's audit faces a *harder* problem (web fetch transcripts can be paraphrased, summarized, or laundered through a second-step "what should I implement?" reflection that strips evidence of the lookup). The plan does not propose:
- a calibration corpus (known-cheating runs the auditor must catch);
- a known-clean corpus to bound false positives;
- adversarial training of the auditor against expected agent evasions;
- a non-LLM trip-wire (e.g. URL pattern matching against a denylist that does not need to reason).

A defensible bar: the audit clears at ≥80% sensitivity on a 20-run calibration set with ≤10% false positive rate on a 20-run clean set, before the capstone score is reported. The plan as written claims novelty for the audit without committing to any such bar.

#### Challenge 4: Is three watchers the right count?

Three is defensible, but the plan does not defend it. The choice reads as "one discovery role + one per fix-flow plan." If a third plan were added (`plan=docs`, say), would a fourth watcher follow? If so, three is an instantiation of "one watcher per plan-type" — that is the actual design rule and it should be named. If not, the asymmetry (one supervisor, two implementation watchers, but no "review supervisor") needs justification: review is currently part of `auto-sequence`, but in a fully unsupervised loop the lack of a review watcher means review-quality drift is invisible to the supervisory layer. Two watchers (collapsing bug/improvement under one with a per-plan policy field) would be a smaller and more uniform design; four (adding a review-quality supervisor distinct from the QA scenario-quality supervisor) would be more thorough. The plan picks the middle without arguing against the neighbors.

#### Challenge 5: Are dep graph edges real?

Several look narrative rather than functional:

- `pr-fbda1a8` depends on `pr-06a96fa`, `pr-2680fbf`, `pr-51586d2`. The PR is "tests for merged Phase 1-5 features under Phase 10's flow." The dep on `pr-51586d2` (mocks awareness) is justified only if Phase 1-5 features touch mock-able surfaces in the bridge tests; if the bridge tests use FakeClaudeSession + FakeGitHubBackend directly (and they should), the mocks-awareness PR is not a functional prerequisite. **Likely fake.**
- `pr-e2b7fdf` depends on `pr-fbda1a8`. Plan argues this is to confirm the loop is sound under Phase 10's flow. But the capstone could run against the *current* (post-Phase-1-5) flow and still produce a meaningful score; it just would not exercise the Phase 10 model. The dep is real *if* the capstone must use the post-Phase-10 flow, fake if it can degrade gracefully. The plan elides this.
- `pr-98f670e` depends on `pr-b3b8df0` (auto-synthesis) and `pr-6f9301e` (headless). The dep on `pr-b3b8df0` is not motivated anywhere in the body of `pr-98f670e`'s entry; the supervisor is described as operating between scenario completion and verdict-emit, with no obvious touch-point with the setup-time auto-synthesis primitive. **Likely fake (narrative ordering).**

Missing deps:

- `pr-eb450a0` (evidence artifacts) should depend on `pr-b59f0c7` (verdict reason strings) — both touch the verdict serialization surface and conflict-resolution will be painful if they land in arbitrary order.
- `pr-c2397e2` (coverage-driven scenario growth) should depend on `pr-b42059d` (per-line coverage), which is upstream of `pr-8ed578d` which it depends on transitively. Adding the direct dep makes the chain explicit.
- `pr-0b14f2c` (mid-run scenario add) and `pr-c2397e2` share machinery per the plan's own interaction note (line 194), but only the soft "sequence first, build on top" guidance is given. This should be a hard dep edge.

#### Challenge 6: Is the bridge PR's scope achievable?

**Probably not as a single PR.** Phase 1-5 shipped 12 merged PRs with at least seven distinct user-visible surfaces (three watchers, auto-sequence chain, discovery supervisor, regression filing, watcher review session). Re-validating each under the new flow with both `REGRESSION:` binding and `NEW_REGRESSION:` authoring paths means at minimum 12 new regression markdowns plus the test scaffolding. The plan's own decomposition principle (e.g. `pr-2c060b2`/`pr-70d02ed`/`pr-a1f267a` filed separately for tight QA scope) cuts the opposite way. Either:

- split `pr-fbda1a8` into 3-4 sub-PRs (per-feature-cluster), or
- explicitly accept that the "bridge" lands incomplete and document which Phase 1-5 features will be deferred to Phase 11.

The current framing — "re-exercise every merged Phase 1-5 feature against the new flow" in one PR — is an unbounded promise.

#### Challenge 7: Has scope sprawled?

**Yes.** 25 pending PRs across 5 phases is a lot. More telling: Phase 9 alone holds 7 PRs and bundles three distinct concerns (hardening, capstone, leaderboard offshoot). Three signals of sprawl in the plan as written:

1. The cross-phase sequencing note (line 69) reading "Phase 10 may force amendments to Phase 7 PRs if sequenced wrong" — this is a circular-dep smell in the plan structure itself.
2. The plan repeatedly says "Phase 10 reshapes the model; everything else measures against it" — but Phase 10 is filed *fifth* in the plan structure, after Phases 6-9. Reading order tip on line 50 ("read Phase 10 first") is a code smell: the document is structured against its own reading order.
3. The "filed in two waves" note on line 300 reveals Phase 10 PRs are post-hoc additions during plan review, not part of the original design. That is fine, but combined with 25 pending PRs it suggests the plan is being grown rather than scoped.

A tighter plan would either (a) ship Phase 10's chain as Phase 6, before the rest of the post-activation work that depends on it, or (b) split into two plans: `plan-regression-loop-core` (Phases 1-5 + Phase 6 bridge) and `plan-regression-loop-redesign` (Phase 10 + dependent work). The current single-plan-with-25-PRs structure obscures the actual phase ordering.

### 5. Missing citations and unacknowledged prior work

The literature review is thorough; the plan itself under-uses it. Specifically:

- **Mergify, Kodiak, Bulldozer** (auto-merge bots). Should be cited in the description of the bug-fix watcher's auto-merge behavior and the improvement-fix watcher's gated-merge. They are the closest prior art and the plan reads as if it invented gated auto-merge.
- **TestRigor, Mabl** (AI-driven test generation in industry). The "regression library compounds" claim has industry peers in continuous-test-discovery products. Not citing them lets the plan claim more novelty than is warranted.
- **GitHub Copilot Workspace** (closed-beta agentic workspace, 2024-2025). The closest closed-source analog to the capstone PR's "single-prompt task envelope" framing. Not engaging with it is a gap.
- **AutoCodeRover, Agentless** (2024). Lightweight non-agentic SWE-Bench solvers that achieve competitive scores without the heavy agent harness. The plan assumes a Claude-Code-style agent is the right substrate; the Agentless line of work argues the opposite. Worth at least a paragraph in Section 2 of the lit review on why the plan picks the agent path.
- **CodeReviewer (Li et al. 2022)** and **CodeT5+ for code review.** The implicit assumption that LLM review is well-calibrated is uncited; there is a small literature on LLM-as-reviewer that should be engaged with given the plan's "auto-merge on PASS" trust model.

### 6. Logical jumps (the weakest links)

1. **"Compounding → autonomous → benchmark-credible."** The plan chains "regression library compounds" (Phase 10) → "loop runs unsupervised" (Phase 9) → "capstone passes a realistic single-prompt task" (Phase 9 capstone). Each link is asserted rather than derived. The strongest claim — compounding enables unsupervised operation — is unsupported: an LLM-authored regression test could be wrong, narrow, or game-able, and an *accumulating* library of wrong tests is worse than a small hand-curated one. The plan needs a quality-of-authored-regressions checkpoint.
2. **"Self-recovery audit reduces INPUT_REQUIRED rate."** `pr-ca6859f` proposes converting INPUT_REQUIRED to explicit recovery playbooks. This is value if the playbooks correctly handle the failure modes; risk if they paper over genuine problems. The plan does not commit to a regression test that ensures recovery playbooks are *correct*, not just present.
3. **"Coverage gate failures → planner adds scenarios → gate passes."** Assumes planner can author scenarios that close the coverage gap. If the gap is in error-handling code that requires unusual inputs, the LLM may not propose those inputs without seed examples. The plan does not say what happens after N gate-failure rounds.

### 7. Architectural rigor — what is missing

- **No state diagram for the watchers.** Three watchers, each with INPUT_REQUIRED escalation paths, auto-sequence chain interactions, and gated merges. A formal state diagram (or even a Mermaid flow) would surface race conditions (e.g. discovery supervisor files a bug while bug-fix watcher is mid-sequence on a related PR) that prose currently hides.
- **No invariants stated.** Examples worth pinning: "at most one watcher edits a PR's status at a time"; "auto-merge fires iff QA verdict is PASS *and* fix-line coverage ≥ X%"; "evidence files for `<pr_id>` are immutable after merge." Without invariants, regressions in Phase 1-5 features are invisible to the bridge PR.
- **No threat model for the capstone.** What can the agent do under the "internet on" constraint? Can it edit `audit.py`? Can it inject into the allowlist via filesystem writes? Can it run `pm` commands that disable the audit? The plan does not enumerate.
- **No data-flow diagram for evidence artifacts.** `pr-eb450a0`'s pre-fix.md / post-fix.md flow is described in prose. Where they are stored, who reads them, who can modify them, what happens on revert — all underspecified.

### 8. Empirical data the plan should have collected before now

- A 5-bug pilot: drive the merged Phase 1-5 loop against 5 known bugs and measure (a) time-to-merge, (b) iterations, (c) human interventions. None of these data points appear in the plan. The plan is asking for 25 more PRs without ever publishing the baseline performance of the system as it stands.
- A coverage-baseline for `pm` itself: before claiming Phase 7's coverage gates will help, the plan should publish current line, branch, and fix-line coverage of the existing test suite. Otherwise the gates are aspirational.
- A "thin artifact" rate measurement (per Section 3 above): how often do current QA scenarios PASS with weak evidence? Without this, `pr-98f670e` is unjustified.

---

## Block 2 — Structure and readability

### What ideas are not clear

1. **What "scenarios bind to regression tests" actually means in code.** Plan line 319 says scenarios become "regression test + per-scenario assertions layered on top." This is the load-bearing data-model change in Phase 10 and it gets one sentence. A code-shape sketch (before: `scenario = {instruction, artifact_recipe}`; after: `scenario = {regression_id|new_regression_slug, assertions}`) would make Phase 10 readable in seconds; absent it, the reader has to reconstruct from `pr-06a96fa` and `pr-2680fbf`.
2. **"Dynamic priority" — what does the watcher *do* on a tie or on disagreement with the prior tick?** Verified against `pm_core/prompt_gen.py:1085`: the prompt says "judge priority" without tie-breakers or churn protection. The plan should either name this as a known limitation or specify the resolution.
3. **The cross-phase sequencing note (line 69) is the most important paragraph in the document and is buried in "Status."** It should be promoted to its own section, with a sequencing diagram. Right now, the reader needs to backtrack from Phase 7's body to find it.
4. **"Regression-corpus expansion (3 PRs)" in Phase 8.** Why these three surfaces (CLI width, watcher behavior, auto-sequence pauses)? Why not the other obviously-uncovered surfaces (e.g. notes.txt parsing, github-backend auth flows)? The selection rationale is absent.

### Overly verbose sections

- **Phase 5 entry for `pr-d60d185`.** Long paragraph explaining why the auto-start command exists; could be one sentence ("Single command to bring up all three watchers; integration smoke test").
- **Phase 9's `pr-e2b7fdf` description** (lines 276-289). Repeats the "internet + integrity audit" framing four times in different words. Cut to two: one stating the realism flip, one stating the audit's role.
- **`pr-51586d2`'s history paragraph** (lines 329-331). Two-thirds of the entry is recounting how `pr-942aa21` and `pr-6be8ee6` arrived at the current state. That belongs in a git-log archaeology note, not in the PR description. Trim to one line: "Reconnects the mocks library at the new-regression authoring surface (not at scenario planning); see `note-a1c6f30` and commit `3eb89e6` for history."

### Content repeated that shouldn't be

- "**Phase 10 reshapes the underlying QA scenario model**" or close variants appears at lines 41, 43, 48, 50, 69, 162, 296, 298, 304, 343. Once in the intro, once in Status, once in the Phase 10 header would be plenty.
- The compounding claim (see Block 1 §2) is asserted five times. Once with a measurement target would be infinitely more valuable.
- The pre-Phase-10 vs post-Phase-10 contrast (lines 45-46 and again 304) is restated in two slightly different forms. Pick one canonical statement.

### Content not repeated but should be

- **The success criteria block (lines 358-385) is the only place specific outcomes are listed.** It should be referenced from each phase header. Right now you read 380 lines of plan before discovering what success looks like.
- **The capstone's depend-on-bridge link** (the loop must be sound before the leader spawns it) is the single most important architectural insight in the plan. It is one sentence at line 289. Promote it.
- **The "internet on, audit catches lookup"** framing in `pr-e2b7fdf` is the plan's biggest research bet, and the literature review correctly flags ImpossibleBench's 42-50% sensitivity as a sobering anchor — but the plan body never engages with that number. The 42-50% should appear in the capstone PR's body.

### Structural changes for readability

1. **Reorder phases by dependency, not by phase number.** Phase 10's chain is a prerequisite for Phase 6's bridge, for parts of Phase 7's coverage stack, and indirectly for Phase 9's capstone. The plan acknowledges this twice (line 50, line 69) and then ignores it. Either renumber (Phase 10 chain becomes Phase 6) or split into two plans (see Block 1 §4 challenge 7).
2. **Add a phase-dep diagram.** A 10-node Mermaid graph at the top of the doc would replace four paragraphs of prose sequencing notes.
3. **Move "How the QA flow evolves" out of a side note and into Section 1.** It is the most important framing in the doc and currently lives between the Architecture section and the Status table.
4. **Collapse the "Status" PR-id soup** (lines 54-67) into a table with columns (id, phase, plan, dep). The current bullet list is unreadable.

### Flow between sections

- Phases 6 → 7 transition is fine (test backfill → evidence-gated loop).
- Phases 7 → 8 transition is awkward: Phase 7 is "evidence gates" and Phase 8 is "post-activation refinements + regression corpus." There is no narrative reason Phase 8 follows Phase 7 except calendar order. A one-line motivator at the head of Phase 8 ("Phase 7 closes the verdict loop; Phase 8 broadens the surface the loop sees") would help.
- Phases 8 → 9 is abrupt: regression-corpus expansion suddenly jumps to "headless hardening and capstone." A sentence on the connecting logic (corpus broad enough → loop ready for unsupervised → time to stress-test) would smooth this.
- Phase 9 → Phase 10 ordering is internally inconsistent (Phase 10 should precede Phase 9 in a dependency sense; see above).

### Hooks and punchy lines that would help

The plan reads like an internal engineering doc. A few sharper openings:

- Plan opening line: replace "Establish a continuous quality improvement loop..." with something like "Turn an existing test suite into a self-extending one: the discovery supervisor reruns regressions, the bug-fix watcher fixes what they surface, and Phase 10 ensures every QA run leaves behind a new regression to rerun next time."
- Phase 10 opening: replace "The most consequential pending phase: replaces the underlying QA scenario model" with "Phase 10 is the line between 'automation around a fixed test format' and 'a test suite that grows by itself.' Without this phase, the loop is a scheduler. With it, it is a self-extending corpus."
- Capstone opening: lead with the bet, not the inheritance. "Real engineers use the internet; benchmarks that ban it measure an unrealistic situation. The capstone's bet is that you can keep the agent honest with a post-run audit instead of a sandbox. ImpossibleBench says 42-50% sensitivity is the bar; the audit needs to clear it."

### Figures, tables, diagrams that should be added

1. **Phase-dependency graph (Mermaid).** Ten nodes, one diagram, replaces three paragraphs of sequencing prose.
2. **Watcher state diagram.** Three watchers, their tick states, INPUT_REQUIRED escalation paths, interactions with the auto-sequence chain. Replaces approximately a page of prose distributed across Phases 2-4 and 9.
3. **Data-model before/after table for Phase 10.** Columns: surface, pre-Phase-10 shape, post-Phase-10 shape. Two rows (scenario, mocks-injection-point) make the entire Phase 10 redesign legible at a glance.
4. **Status table.** Replace the bullet soup in "Status" (lines 54-67) with a real table.
5. **Capstone audit decision flow.** Even a four-box diagram (transcript → allowlist check → audit verdict → score gate) would dramatically reduce the prose required to describe `pm_core/bench/audit.py`.

### Things the plan does well (briefly)

- The cross-phase sequencing note (line 69), buried as it is, accurately calls out the Phase 7 / Phase 10 ordering risk. Good catch.
- The interaction paragraph between `pr-c2397e2` and `pr-0b14f2c` (line 194) is a model of how PR-to-PR interactions should be documented: shared mechanism, sequencing recommendation, downstream rebuild as a programmatic caller.
- The reuse list at the head of the Architecture section (lines 16-25) is concise and correct (verified against `pm_core/watchers/` and `pm_core/prompt_gen.py`). It is the most defensible section in the document.
- Distinguishing `pr-ca6859f`, `pr-ed10ac4`, and `pr-98f670e` (technical retry vs. spinning-loop vs. verdict-trust) on line 274 is a clean three-way distinction worth more emphasis — it deserves to be in the Phase 9 opener.

---

## Summary of the highest-leverage fixes

If the author addresses only five things from this review, do these:

1. Quantify the compounding claim with a measurable target, or downgrade it to a hypothesis.
2. Engage with ImpossibleBench's 42-50% sensitivity number in the capstone PR; commit to a calibration corpus.
3. Split `pr-fbda1a8` into per-feature-cluster bridges, or accept (and document) partial coverage.
4. Add a phase-dependency diagram and reorder phases by dependency.
5. Specify what "dynamic priority" does on a tie and how thrash will be measured.

The plan is well-organized at the section level and the reuse-first principle is sound. The weaknesses are in *unsupported quantitative claims*, *unbounded PR scope* (bridge, capstone), and *narrative ordering that fights the dep graph*. None are fatal; all should be addressed before Phase 10 lands.
