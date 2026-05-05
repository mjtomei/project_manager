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
