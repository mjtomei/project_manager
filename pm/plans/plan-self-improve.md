# Recursive pm Tournament Across Targets

Run a population of pm variants in parallel, score them by an external fitness metric, and let winners graduate to higher-stakes work. Targets are pluggable — pm itself, the plan-002 benchmark set, OSS repos with QA harnesses. The tournament is itself a pm prompt and evolves through the same loop as anything else; safety comes from external evaluation rather than code-level carve-outs.

This plan is intentionally underspecified. Many design choices should draw on prior work in evolutionary algorithms (selection pressure, population diversity, anchor strategies, novelty search, multi-objective fitness) and will be worked out collaboratively before phase breakdown.

## Goals

- Use pm to improve any project that exposes a Claude-based fitness metric, including pm itself.
- Make the tournament generic across targets — adding a new target is configuration, not new infrastructure.
- Avoid self-confirmation collapse: a variant never grades itself; anchor variants and held-out corpora bound the loop.
- Route compute toward variants likely to do good work on stakes-bearing targets.

## Prerequisites

- Bug-fix loop demonstrably unsupervised — regression-loop Phase 7 evidence and coverage gates landed.
- Benchmark loaders from plan-002 — held-out slices for variant evaluation come from here.
- Per-plan auto-merge=false (`pr-b77702b`) so variant branches stage as candidates.
- Container isolation for variants (already in plan-qa).

## Core concepts

### Target

A project the tournament operates against. Provides: a checkout, a Claude-based test harness that emits a numeric metric, and a held-out evaluation corpus the loop is not allowed to peek at. pm itself, benchmark sets, and OSS repos are all targets; the infrastructure does not know which is which.

### Variant

A pm checkout at a specific commit, possibly with prompt or model overrides. Variants are produced by the existing bug-fix and improvement-fix watchers operating on a target's self-modification plan. The same variant can compete on multiple targets — overfitting one target shows up as poor cross-target performance.

### External fitness

A variant is never graded by itself. Sources include the target's own metric, cross-variant review (sibling variants score each other), and agreement with anchor variants on cases where ground truth is settled. Cost is a tiebreaker. Specific weighting and combination is a design choice we should work through with the evolutionary-algorithms framing, not pin down here.

### Anchor

At least one variant per target is pinned to a known-good ancestor and never retires. Anchors are the safety boundary: they periodically re-run the tournament as a sanity check, they sit in the population as a fitness reference, and they catch population-wide drift that cross-variant agreement alone would miss.

### Recursive tournament

The tournament is a pm prompt. Variants can propose changes to it. The variant evaluating a tournament tick is never the variant being scored. A meta-tournament selecting tournament-runners is possible at the next level up; the recursion bottoms out at a human-pinned anchor.

### Champion and promotion

Each target has a champion — the variant currently used for production work against it. Promotion is gated: a challenger must beat the champion by some margin for some duration before replacing it, with a human confirm step. The exact gate parameters are a design choice for later.

## Open questions to work through before phase breakdown

- Selection and population dynamics: tournament size, replacement strategy, diversity preservation, novelty vs. fitness tradeoff. The previous evolutionary-algorithms work should inform this directly.
- Held-out corpus hygiene: rotation strategy, meta-held-out reserved for sanity checks, detection of leakage.
- Anchor advancement: anchors can't stay frozen forever or all variants legitimately diverge. Rolling anchor under human approval, or anchor lineage that advances when consensus among non-anchor winners is strong.
- Cross-variant collusion: if all non-anchor variants drift together, sibling agreement stops being a signal. The anchor's weight in composite fitness has to be meaningful.
- Tournament-prompt sabotage: a variant could propose a tournament change that subtly favors itself. Anchor-run tournaments on identical populations should produce close-to-identical rankings; large divergence triggers rollback.
- Cost ceiling and budget allocation across targets and population size.
- Champion rollback: if a graduated champion is later found regressed, rollback is a normal pm revert PR — but the fitness signal that missed the regression also needs review.

## Success criteria

- A continuous variant population competes on multiple targets simultaneously, with per-target champions determined by the tournament rather than manual selection.
- Adding a new target is a configuration change plus a harness wrapper.
- The tournament prompt is evolvable through the loop, bounded by anchors and held-out corpora.
- The operator can ask "for target T, which variant is the current champion, why, and what is it working on" and get a coherent answer.

## Appendix: Workflow A/B candidates (deferred)

Multi-agent orchestration (Claude Code's Workflow tool, or an equivalent built in pm Python) is a candidate axis for variants once the tournament substrate exists. We are not adopting it now because we cannot yet measure whether it meaningfully improves output quality vs. the current single-prompt approach, and adopting it has real costs: reduced portability to non-Claude-Code backends (including local LLMs behind Claude) and reduced visibility (you cannot attach to a workflow mid-run the way you can attach to a tmux pane in the QA flow).

Once regression-test infrastructure (plan-regression Phase 7 + plan-002 benchmarks) gives us a stable quantitative metric, the following sites are worth running as A/B variants — single-prompt champion vs. multi-agent challenger — and promoting only if the challenger wins by margin:

- **`adversarial_review`** — current single-prompt review vs. parallel skeptic finders + independent voter quorum. Quality hypothesis: independent skeptics catch false positives a single review prompt rationalizes past. Measure: review precision/recall against curated bug fixtures.
- **`review_qa_benchmark` harness** — sequential per-case scoring vs. fan-out per case with deterministic aggregation. Hypothesis: pure throughput win, not quality; promote only if dev-time to build the harness in pm Python is meaningfully higher than wiring it through Workflow.
- **`adversary-runner` / `plan-gen-integration` / `spec-gen-integration`** — single plan/spec gen prompt vs. three-lens fan-out (internal-consistency / external-skeptic / cross-reference) with loop-until-quiescence. Hypothesis: lens diversity catches gaps a single prompt misses. Measure: human-graded plan/spec quality on a held-out corpus, and downstream rework rate.
- **`external-fitness` + `anchor-variants`** — this tournament's own scheduler. Whether the variant grid runs as Workflow vs. pm-Python orchestration is itself an A/B once the metric exists. Hypothesis: Workflow's built-in journaling/resume/concurrency-cap is a dev-time win; quality should be identical.
- **`prior-work-survey` (plan-living-artifacts)** — single deep-research prompt (or the existing `deep-research` skill) vs. fan-out per-area + adversarial citation verifier. Hypothesis: citation hallucination rate drops with an independent verifier pass. Measure: cite-check precision against the produced bibliography.
- **Citation audit loop (plan-litreview augmented cycle).** Per-citation fan-out vs. the current single sequential session walking the citation list. The audit already writes one entry per citation to disk as it runs, so visibility cost is low. Hypothesis: independent per-citation judgment is better calibrated than a single pass, especially for `over-characterizes` / `under-characterizes` verdicts. Measure: agreement with held-out human-graded verdicts on a fixture artifact; false-faithful rate on seeded mischaracterizations. See [[plan-quality#appendix-same-question-across-many-pieces-of-text]] for the per-citation framing.
- **`signoff` two-evaluation router** — current single sign-off prompt vs. parallel (evidence-supports-diff) + (anti-shortcut/meta-QA) subagents gated by a deterministic Python router. Hypothesis: independent evaluations catch shortcuts the merged prompt rationalizes. Measure: false-PASS rate on injected shortcut fixtures.

For each candidate, the A/B must control for token spend — a workflow that wins only because it spent 5× the tokens isn't a real win unless the cost ceiling explicitly allows it. The tournament's existing per-target cost ceiling is the right place to enforce this.

Visibility cost is part of the cost side of the ledger: workflows that hide debuggable session state should clear a higher quality bar than ones (like batch eval harnesses) that nobody attaches to mid-run anyway.
