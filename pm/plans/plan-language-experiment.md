# plan-language-experiment

Use pm's existing impl → review → QA → automated-sign-off loop (from `plan-regression` PR 226) as a measurement instrument across two separable experiments:

1. **Gradient experiment** (Python only): which level of pm structure — well-configured Claude Code, Claude Code with priming, pm autostart, pm with planning — is the simplest that produces consistently good results, and at what complexity stratum does each level start earning its keep? Crossed with an open-model arm to test whether pm's structure compensates for weaker models, and whether a hybrid mode (Opus for the high-leverage decisions, cheap open model for the bulk) preserves quality at lower cost.
2. **Language experiment** (cross-language at the simplest-successful condition found in the gradient experiment): does target language matter for LLM-produced code quality, holding the pm configuration constant?

Plus two follow-on phases: a **perf** experiment (base efficiency + LLM-driven optimization loop) and a **quality-priming** experiment (does surrounding-code quality propagate into LLM-generated additions).

The gradient experiment runs first because the language experiment depends on its result — we need to know which pm configuration to use cross-language before running cross-language cells.

## Framing

The motivating argument for a rewrite-to-FP is that an LLM-driven workflow can absorb the human cost of translation, and that LLM-produced code is higher quality in languages whose training corpus self-selects for correctness-minded contributors. The counter-argument is that smaller training corpora produce buggier code regardless of language quality.

This is exploratory. The hypotheses below name directions we're interested in seeing, not predeclared accept/reject tests. The matrix shows us the effects; we decide from there.

### Task as plain-language description

The unit of work is a plain-language description of what we want code to do. The same description goes to every implementor variant. Whether the implementor splits it into multiple PRs, handles it in one PR, or does it in a single session is the implementor's structural choice.

### Complexity stratification

- **Trivial** (~10–50 LOC). Bug fixes, single function additions.
- **Small** (~50–500 LOC). Feature additions across a few files.
- **Medium** (~500–2000 LOC). Multi-PR coherent features.
- **Large** (~2000–10000 LOC). Whole projects or coherent subsets.

## Hypotheses

The experiment is exploratory. These name what we're looking for; the matrix shows whether they hold.

**Correctness (Phase A + B):**
- H1: stronger-typed languages and correctness-minded corpora show fewer iterations-to-sign-off
- H2: smaller-corpus languages show higher iterations-to-sign-off and DNF rates
- H3: precise compiler feedback (Rust borrowck, GHC, Lean elaborator) yields steeper per-iteration improvement
- H4: task shape interacts with language ranking
- H5: large-vs-small-corpus gap widens as abstraction drops (Python → asm)
- H6: pm review gives richer actionable feedback in languages the reviewer has seen more of
- H7: auto-generated specs/scenarios differ in quality by target language; this may mediate H1

**Gradient × complexity (Phase A):**
- H17: pm conditions (C2, C3) beat well-configured Claude Code (C0, C1), per stratum
- H18: planning (C3) beats autostart-only (C2) at medium/large strata
- H19: pm reaches given pass rate at competitive token cost vs C0/C1
- H20: CLAUDE.md priming (C1 vs C0) is load-bearing — or isn't

**Perf (Phase C):**
- H8: base perf gap is much larger than the correctness gap
- H9: LLM optimization is effective
- H10: optimization headroom is inverse to base quality
- H11: cross-language perf ceiling at fixed budget
- H12: thin auto-generated QA → higher verification-preservation failures under optimization

**Quality priming (Phase D):**
- H13: changes built on high-quality seed code converge faster
- H14: priming effect varies by language (weaker in opinionated-tooling languages)
- H15: LLM additions inherit surrounding-code style (style contagion)
- H16: high-quality seeds → richer auto-generated specs (H7 via context priming)

**Open-model arm (within Phase A):**
- H21: pm closes the model gap (pm + weak model → close to Claude pass rate)
- H22: planning matters more for weaker models
- H23: tasks unreachable below model-size threshold per stratum
- H24: hybrid (Opus for planning+sign-off, open for bulk) approximates Opus at lower cost
- H25: hybrid is the best cost-per-quality tradeoff at small/medium strata

H1 + H7 + H17 + H18 + H20 + H21 + H24 are load-bearing for the rewrite decision.

## Variables

**Independent:**
- **Language** (7): Python, Haskell, Rust, OCaml, Lean 4, LLVM IR, x86-64 assembly
- **Task description** (from the curated corpus; same input to every condition)
- **Complexity stratum** (4): trivial / small / medium / large
- **Condition** (4): C0–C3 gradient (§Conditions)
- **Model** (4): Claude default + 3 open-model size tiers (Phase A only)
- **Trial** (3 per cell main matrix; 1 per cell open-model arm)
- **Optimization budget** (3 levels, Phase C only)

**Dependent:** iterations-to-sign-off, DNF rate by category, held-out test pass rate, token cost per cell, auto-generated artifact quality, review-feedback classification, perf metrics (Phase C), style-similarity scores (Phase D).

**Controlled:** pm loop unchanged across languages (small per-language addendums only); same hardware for perf benchmarks; pinned compiler versions.

Confounds and mitigations: Appendix §A.

## Language selection

The seven-language set. **All seven target the same task corpus through the same loop.** DNF is a first-class outcome, not a methodology problem.

1. **Python** — baseline. Largest corpus.
2. **Haskell** — the motivating "designed by people who care about quality" candidate.
3. **Rust** — practical-alternative candidate; large corpus with type discipline.
4. **OCaml** — FP with pragmatic IO; smaller corpus than Haskell.
5. **Lean 4** — dependent types with real codegen; thin ecosystem.
6. **LLVM IR** — lowest practical compilation-target abstraction.
7. **x86-64 assembly** — lowest level we test.

DNF predictions per language: Appendix §B.

## Conditions: the C0–C3 gradient

Four conditions per cell. Non-pm conditions (C0, C1) take the description into a Claude Code session with full tool access; pm conditions (C2, C3) differ in whether pm's planning streams are exercised.

1. **C0 — Claude Code (ultracode) with full tool access + style-of-use prompting.** `/loop`, `Workflow`, and all native tools available. The agent gets the description plus a short style-of-use addendum.
2. **C1 — C0 plus an auto-generated CLAUDE.md.** Per-repo priming written by a separate Claude session analyzing the codebase. Tests whether structured project priming is what's missing in C0.
3. **C2 — Pm autostart, no planning.** Description handed in as a single PR. Impl → review → QA → sign-off iterates per pm's normal loop.
4. **C3 — Pm with planning.** Description handed in as a plan brief. plan-add + plan-breakdown produce a PR queue; autostart drives each PR.

Expected complexity reach per condition and per-cell gradient mechanics: Appendix §C.

## Loop structure

The pm loop is unchanged across languages: impl → review → QA → automated sign-off, the same pipeline from plan-regression PR 226. Same prompts. The held-out behavioral test suite is the only external validation, identical across languages.

The only per-language customization is small **prompt addendums** for Lean/IR/asm (totality reminders, SSA notes, ABI notes). These are nudges, not separate oracles. Details: Appendix §D.

## Task corpus

Real-repo snapshots paired with historical PRs, plus generic language-agnostic tasks. The PR description (or plan brief) is the sole loop input. The repo's existing test suite (where artifact-level) or authored input/output fixtures (where not) is the objective oracle.

Test methodology is **artifact-level** — we test the produced binary/library against input/output fixtures, never internal API. This means no interface-scaffolding leakage and uniform comparison across languages.

Corpus document: `pm/plans/plan-language-experiment-corpus-v3.md`.

Repo selection criteria, PR filter, and per-cell setup procedure: Appendix §E.

## Cheating detection

The experiment's validity rests on the LLM solving the task from the description, not retrieving the specific target solution. Tool use including web search is allowed; we verify the LLM didn't shortcut the experiment by finding and copying the specific human-PR solution.

**The line:** would a competent developer working on this task from scratch consult this resource? If yes, it's fine. If the resource is specifically the target solution, it's cheating.

- **Cheating**: outputting code closely matching the specific human PR; web-searching for the target repo+PR; following links to the repo's commit history; for generic tasks, finding our specific test fixtures.
- **Not cheating**: copy-pasting from resources any developer would consult (algorithm descriptions, tutorial code, stdlib docs, reference implementations); using stdlib; reading external specs that are themselves the oracle; language reference docs.

**Detection** runs against every cell:
1. **Diff similarity check.** Textual + AST similarity between LLM output and human PR diff. High similarity flags for review.
2. **Transcript scan.** A judge stream reads the session transcript looking for URLs to target repo/PR, search queries naming source by name+number, tool invocations fetching target source, self-incriminating reasoning.

Calibration thresholds, handling of flagged cells, and per-condition tracking policy: Appendix §F.

## Phase A: gradient experiment (Python only)

Asks: which pm configuration is the simplest that works, and at what complexity stratum does each level earn its keep? Exercises the full C0–C3 gradient and the open-model arm. Output is the simplest-successful configuration per complexity stratum, fed into Phase B.

- **A1 — Pilot.** Wire the harness on 2 Python repos × 3 strata × all 4 conditions × 1 trial.
- **A2 — Main matrix.** ~60–80 cells × 4 conditions × 3 trials, plus the open-model arm.
- **A3 — Conditional follow-ups** based on A2 results.

Per-cell procedure, deliverables, budget estimates: Appendix §G.

## Phase B: language experiment

Takes the simplest-successful Phase A configuration and varies the language target across all 7 languages. Does not re-run the gradient cross-language.

- **B1 — Pilot.** Selected condition × 3 languages × 2 repos × 1 trial.
- **B2 — Main matrix.** ~7 languages × ~10 cells × 3 trials, single condition.
- **B3 — Conditional follow-ups.**

Per-cell procedure, deliverables, budget: Appendix §G.

## Phase C: efficiency experiment

Consumes Phase B's converged implementations and adds perf measurement + an LLM-driven optimization loop. The optimization loop is the same pm loop with a perf-focused impl prompt addendum.

- **C1 — Perf harness pilot.**
- **C2 — Main perf matrix** across (language × task × trial × optimization-budget).
- **C3 — Conditional follow-ups.**

Benchmark harness, optimization-loop design, budget: Appendix §H.

## Phase D: code-quality priming experiment

Asks: when pm makes changes to existing code, do changes built on high-quality code come out higher quality than changes built on low-quality code? Uses real repos that span the quality spectrum naturally (no hand-authored seeds).

- **D1 — Python pilot** at three quality strata (high/mid/low).
- **D2 — Main matrix** (conditional on D1 showing a visible gradient) — expand to Rust + Haskell to test H14 (does opinionated tooling attenuate the priming effect).
- **D3 — Conditional follow-ups.**

Stratum operationalization, measurements, budget: Appendix §I.

## Open-model arm (Python only at first, within Phase A)

Tests pm conditions (C2, C3) with open models of varying sizes, in two configurations:

- **All-open**: every pm stream runs on the same open model.
- **Hybrid**: Opus runs the high-leverage decisions (planning streams, sign-off); cheaper open model runs impl/review/QA.

Three open-model size tiers (~7B, ~20–30B, ~70–120B+) plus a coding-specialist slot (Composer 2.5 and gpt-oss bracket the coding-specialist comparison), plus the Claude baseline. We restrict the arm to Python initially — cross-language coverage waits until Python results justify it.

Model selection, condition matrix, hypotheses, budget: Appendix §J.

## Coordination with plan-regression

1. **Project-level guidance features.** plan-regression has PRs in flight for project-level guidance (CLAUDE.md-equivalent priming pm produces and maintains, auto-suggested invariants, cross-PR consistency checks). C3 exercises these features; A2 cannot fully run C3 at medium/large strata until those features are implemented or stub-implemented.
2. **programbench.** plan-regression's programbench is a from-scratch project benchmark. This plan doesn't depend on it — we derive large-stratum tasks from the same real-repo corpus. But results inform programbench's design and may absorb our large-stratum task derivations. Bidirectional, not blocking.

## Interpretation framework

This is exploratory. No predeclared numerical thresholds. The framework names the dimensions we'll inspect across the matrix and the patterns that would suggest different next steps.

**Refactor-target candidate set** is restricted to {Haskell, Rust, OCaml, Lean 4} — the four source languages with realistic pm-shaped ecosystems. LLVM IR and x86-64 are not refactor-target candidates regardless of results; they probe the LLM-driven low-level codegen capability question separately.

**Patterns that would suggest different next steps** (judgment calls, not gates):
- Candidate shows clear correctness uplift AND competitive perf at high optimization budget → rewrite worth a port pilot of `pm_core/mind/`.
- Multiple candidates cluster together and Python doesn't visibly lag → rewrite not motivated by the data.
- Candidate wins correctness but loses perf dramatically → filter out as rewrite target.
- LLVM IR converges on ≈ half the corpus with real optimization speedups → green light for IR-writing pm workflows as a new capability (not a rewrite target).

Detailed dimension-by-dimension inspection guide: Appendix §K.

## Sequencing relative to the refactor

The experiment is most valuable after the refactor's first 3-4 substrate PRs land. But A1 (harness development + task collection) can start in parallel with the refactor.

1. Mind-primitives PR lands. plan-regression PR 226 (automated sign-off) is in flight.
2. A1 runs in parallel with runtime-protocol PR.
3. A2 (trivial through medium strata) runs after streams-substrate PR.
4. Open-model arm runs in parallel with A2 on local GPU compute.
5. A2 large-stratum cells wait for plan-regression's project-level guidance features. **This is the only hard dependency.**
6. A3 follow-ups + B1 + C1 + D1 pilots run in parallel.
7. B2 → C2 → D2 (conditional) as data comes in.
8. Decision point on the rewrite question.

This sequencing never blocks the refactor or plan-regression. Lower-stratum work proceeds independently of plan-regression's project-level guidance work.

## Session-budget ceiling

We pre-commit "six to ten max-mode Claude Code subscription sessions" for Phases A+B+C+D combined, plus separate open-model GPU compute for the open-model arm.

Per-phase budget breakdown: Appendix §L.

---

# Appendix

This section contains procedural detail, justifications, calibration notes, and contingent procedures referenced from the core experiment. None of this is required to understand the experiment; it's reference material for execution.

## Appendix §A — Confounds and mitigations

- **Training-data volume** is itself a variable we want to *measure*, not control. Quantify roughly via GitHub-stars + Stack-Overflow questions + arXiv mentions per language. Don't try to equalize.
- **Library ecosystem completeness** for chosen tasks. Mitigation: pick tasks that lean on standard libraries; explicitly bias the corpus away from "needs a niche library." Record tasks failing purely due to library absence under "ecosystem penalty."
- **pm review/QA prompts** were tuned on Python-shaped code. Mitigation: per-language prompt addendums (small, conservative) plus the pilot phase to surface systematic mis-targeting.
- **LLM cheating via benchmark-input special-casing** (Phase C). Mitigation: training input set during optimization; held-out validation set for final perf. Special-casing visible inputs shows up as verification-preservation failure.
- **Hardware noise** (Phase C). Covered by repeated runs + medians. Input sizes chosen so per-run wallclock is ~1–10s.
- **Reviewer-model bias**: if the same Claude model reviews its own code, it may under-call its own bugs. Mitigation: pin reviewer to a different model family where possible; document otherwise. Check via held-out reviewer-rotation probe.
- **"Fairness" when one language's stdlib does more of the work** (e.g., Python `json.loads` vs Haskell `aeson`). Either require both from scratch or allow stdlib. Run both variants on a subset to measure the difference.

## Appendix §B — DNF predictions per language

| Language | Expected DNF | Dominant DNF cause |
|---|---|---|
| Python | ~0% | none expected |
| Rust | ~0% | none expected |
| Haskell | ~2% | rare `no-progress-loop` on concurrent tasks |
| OCaml | ~3% | concurrent / async friction |
| Lean 4 | ~15% | `model-surrender` on I/O and network tasks; termination proofs |
| LLVM IR | ~25% | `model-surrender` on application-shaped tasks |
| x86-64 asm | ~40% | `model-surrender` is the bulk; runtime crashes on parsing/I/O tasks |

DNF categories: `model-surrender`, `no-progress-loop`, `compile-failure-persistent`, `runaway-token-budget`. These are predictions; the experiment exists to check them.

Stretch language candidates if budget allows: F#, Scala 3, Elixir, ARM64 assembly. Skip unless first-pass results suggest the 7-language set didn't capture the relevant axis.

## Appendix §C — Gradient mechanics and expected complexity reach

**Expected complexity reach per condition** (predictions):
- C0 — Viable trivial → medium; may struggle at large.
- C1 — Same reach as C0; priming improves quality at medium.
- C2 — Small → medium; impl loop handles single-PR work.
- C3 — Medium → large; planning breaks down work too big for one PR.

**Per-cell quartet outputs**: C0 + C1 + C2 + C3 + human PR (ground truth). All scored on the same artifact-level test fixtures. Comparisons: C2 vs C0/C1 (pm autostart's marginal value over Claude with/without priming); C3 vs C2 (planning's marginal value); C1 vs C0 (priming's marginal value); each Ci vs human.

**Generating C0**: fixed style-of-use system prompt addendum telling the agent it's implementing against a real codebase with a test suite; that `/loop` and `Workflow` are available.

**Generating C1**: per-repo CLAUDE.md auto-generated by a separate Claude session analyzing the codebase. Cached per repo; ~5k tokens per repo to generate, amortized across all cells.

**Why C0 is a strong baseline, not a strawman**: collapses the previous many-step ramp (one-shot → agentic → /loop → Workflow) into a single realistic Claude Code experience. This tests pm against the actual experience a user would have without us, not a deliberately handicapped Claude.

## Appendix §D — Per-language prompt addendums

The pm loop is unchanged across languages. Small prompt addendums where they materially help:

- **Lean 4 (review addendum)**: short note that Lean separates totality / termination proofs from implementation; flag `partial` markers and missing `decreasing_by` clauses. **Lean (QA addendum)**: scenarios that need behavior can use `lean --run` against `#eval` checks; scenarios that need a property can require a proof.
- **LLVM IR (review addendum)**: short note that comments use `;`, calling convention is SystemV, review should focus on SSA validity, undef/poison correctness, and aliasing.
- **x86-64 asm (review addendum)**: AT&T syntax, SystemV ABI; review should additionally flag callee-saved-register clobbers, stack-pointer imbalance, missing `.cfi` directives.
- **Haskell, Rust, OCaml**: no addendum needed at the start. Add during pilot if specific failure modes show up.

**Why same-loop matters**: no oracle-strength confound (iterations-to-sign-off is comparable across languages); the review-effectiveness gradient becomes a measurable result (H6); DNF causes are language-intrinsic, not loop-intrinsic; auto-generated artifact differences become measurable (H7).

## Appendix §E — Repo and PR selection details

**Per repo:**
- Language coverage: 3–4 repos per language for Python/Haskell/Rust/OCaml; 1–2 for Lean/IR/asm (or fall back to hand-authored).
- Test coverage: ≥ 60% line coverage on the modules affected by selected PRs.
- Build reproducibility: cleanly buildable from a clean checkout.
- License: permissive preferred but not filtered (per v3 corpus criteria).
- Popularity: no filter (per v3 corpus criteria — contamination addressed via cheating detection).
- Tractable scope: ~30k LOC soft cap on the relevant subtree.

**Per PR (within a chosen repo):**
- Test-bearing diff (the PR added/modified tests, or merged code is exercised by existing tests).
- Self-contained (testable without coordinating with merged-after-it changes).
- Informative description (≥ 200 chars, content sanity-checked).
- Diff size: no cap (per v3 corpus criteria — large PRs are valuable stress-test material).

**Artifact-level testing methodology:** a test fixture is three things — an input file, an expected output file, and an invocation command. Same harness across all 7 languages. Pm doesn't see test inputs/expected outputs during implementation; they're applied at evaluation time.

**Per-cell setup procedure:**
1. Clone the repo at the commit immediately preceding the PR's merge.
2. Build the artifact harness for the repo's language.
3. Author or extract artifact-level test fixtures.
4. Set up pm in the repo's `pm/` subdir.
5. Add the PR description to `pm/project.yaml` (no scaffolding).
6. Run pm autostart (or the appropriate non-pm condition).
7. Evaluate against the artifact-level fixtures.

**Cell evaluation procedure (after convergence or DNF):**
1. The condition's converged code is in the working tree.
2. Build the artifact. If build fails: DNF with `compile-failure-persistent`.
3. Run each test fixture; diff actual vs expected.
4. Record fixtures passed/failed, diff size relative to human PR.
5. Cheating-detection pass (see §F).

## Appendix §F — Cheating detection calibration and policy

**Calibration of the diff similarity threshold** happens in A1 pilot. We expect:
- Trivial tasks produce naturally similar implementations (human and LLM both produce the obvious solution); false positives expected and filtered by manual review.
- Larger tasks have more design degrees of freedom; high similarity is more suspicious.

Initial threshold: ~0.7 on normalized AST + textual similarity, calibrated against the pilot's observed distribution.

**Transcript scan judge prompt** specifies what to flag:
- URLs visited that reference the target repo or PR
- Web search queries naming the source repo + PR number
- Tool invocations fetching source from the target (e.g., `gh pr diff <target>`)
- Self-incriminating reasoning ("Let me look up how the human solved this...")

Verdict: `clean` / `suspicious-needs-review` / `confirmed-cheating` with quoted evidence.

**Handling flagged cells** (set after the A1 pilot tells us the flag rate):
- `suspicious-needs-review` cells go to human review.
- `confirmed-cheating` cells are excluded from primary analysis. If exclusion bias is meaningful, re-run with web search disabled.
- Per-condition cheating rate reported alongside per-condition results if rates differ across conditions, that's its own finding.

**For generic tasks**: cheating concern is reduced (no canonical "the source" to find). Check still runs with looser thresholds.

## Appendix §G — Phase A and B procedural details

**Phase A1 (gradient pilot)** — Python, 2 repos × 3 strata × 4 conditions × 1 trial. Wire up the harness, surface plumbing issues, calibrate token budgets, calibrate cheating-detection threshold, validate per-language prompt addendums.

Decisions committed before A2: token budget per cell (initial 200k); `no-progress-loop` detection threshold (initial: 5 consecutive iterations with same oracle-feedback fingerprint); held-out test runner for Python.

Deliverables: `tools/lang-experiment/` harness scripts, pilot report.

**Phase A2 (main gradient matrix)** — Python only; ~60–80 cells × 4 conditions × 3 trials.

Per-cell procedure:
1. Setup (clone, build harness, authoring/extracting fixtures, pm/project.yaml).
2. Run each of C0–C3.
3. Evaluate (apply, run test suite, record pass/fail, run cheating detection).
4. Per-cell metrics: pass rates per condition, token cost per condition, iterations counts, DNF category, diff size, auto-generated artifact characteristics.

Per-cell budget: 200k tokens per pm condition; ultracode conditions get the same fair budget for iteration via `/loop` and `Workflow`. Matrix budget: ~80 cells × 4 conditions × 3 trials × ~50k average ≈ 48M tokens worst-case. **Realistic Phase A2 budget: 2–4 max-mode sessions.**

**Phase A3 follow-ups** (conditional on A2 results): see §interpretation framework — probes are picked from A2 data, not pre-committed.

**Phase B1 (pilot)** — selected condition × 3 languages × 2 repos × 1 trial. Validate per-language harness details (test runner, build invocation, fixture wrapping). Decide whether Lean / IR / asm survive in B2 given Phase A's signal.

**Phase B2 (main language matrix)** — ~7 languages × ~10 cells × 1 condition × 3 trials = ~210 condition-runs. Average ~50k tokens per run. Aggregate ≈ 11M tokens worst-case. **Realistic Phase B2 budget: 1–2 sessions.**

Per-cell procedure: same as A2 with the per-language test runner. Per-cell metrics: same as A2.

**Phase B3 follow-ups** (conditional):
- If clear FP winner emerges → workflow-driven port pilot of `pm_core/mind/` to that language (separate plan).
- If H21 held → open-model arm extension for the winner language.
- If a task shape drove the language gap → probe deeper.
- If Lean DNFs cluster on I/O but works algorithmic → Lean-as-property-spec-companion-to-Python probe.
- If x86-64 shows promise → small ARM64 follow-up.

## Appendix §H — Phase C (perf) details

**Benchmark harness** per task:
- Training perf input set (visible to the optimization loop): 5 representative inputs.
- Held-out perf validation set: 5 in-distribution + 2 adversarial edge cases.
- Per-language benchmark driver runs N times with warmup, records wallclock + perf-counters + memory.
- Calibration before C2: find input sizes giving ~1–10s wallclock for the slowest language; use those sizes across all.

**Optimization loop**: same pm loop with perf-focused impl prompt addendum ("the goal here is perf; accept candidate transformations that preserve behavior even if less idiomatic; held-out validation suite catches behavior changes").

**Per-cell at each budget level (0/5/15 iterations):**
1. Baseline measurement on training inputs.
2. Optimization iteration: impl proposes → review iterates → QA iterates → sign-off. Benchmark on training inputs. ≥ 5% speedup retains as new base.
3. Loop termination at budget B or 3 consecutive no-speedup rounds.
4. Final validation on held-out set. If correctness fails on held-out, use previous accepted version.

**Budget**: ~630 cells × ~30k tokens average ≈ 19M tokens. **Realistic Phase C budget: 2–4 sessions.**

**C3 follow-ups** (conditional):
- If H9 holds → measure speedup-vs-budget curve more densely (10, 25, 50 iteration budgets).
- If cross-language gap is huge even after optimization → transpilation probe.
- If pm-shaped tasks show optimization potential → probe on real pm module.

## Appendix §I — Phase D (quality priming) details

**Real-repo quality variation replaces hand-authored seeds.** For Python/Rust/Haskell, curate three quality strata:
- **High**: lint/format CI gates, comprehensive types, modern syntax, thorough docs.
- **Mid**: typical OSS quality.
- **Low**: legacy / mixed; older patterns, partial comments, formatting inconsistencies.

Stratum-defining qualities are visible via mechanical metrics (lint pass rate, type coverage, comment density, function size distribution). Pre-compute per candidate repo; verify the stratum is operationally distinguishable.

**D1 pilot** (Python, 3 strata × 2 repos × 3 PRs = 18 cells). Goal: visible monotonic gradient in held-out-test pass rates, iterations-to-sign-off, and style-similarity scores. If no gradient → settle the question cheaply, skip D2.

**D2 main** (conditional on D1): 3 languages × 3 strata × 3 repos × ~5 PRs ≈ 135 cells. Tests H14 (does opinionated tooling attenuate priming).

**Additional measurements specific to D:**
- Style-similarity score between pre-PR snapshot's code and pm's additions (comment density ratio, type-annotation rate, line-length distribution, identifier-naming style, function-size distribution, linter pass rate).
- Standalone quality rating of LLM's additions (independent judge stream with calibrated rubric; or human-in-the-loop on a subset).
- Auto-generated spec/QA scenario quality stratified by repo quality.

**D3 follow-ups** (conditional):
- If H13 holds strongly → probe whether the effect compounds, holds, or dissipates across sequential PRs.
- If H14 holds → probe which specific opinionated tool (formatter / linter / type system) protects the effect.
- If H15 holds → probe whether mixing styles deliberately breaks contagion.
- If H13 fails → ask whether seed-quality contrast was large enough; re-run with sharper contrast.

**Implication for pm itself**: if H13 holds, pm should aggressively maintain its own code quality not just for human readers but as self-protection against LLM-generated additions inheriting any quality regressions. The pm review prompt could grow a "seed-style mismatch" feedback category if H15 shows strong contagion.

## Appendix §J — Open-model arm details

**Model selection** (subject to local-inference feasibility):

- Small (~7B–8B): Llama-3.x 8B or Qwen 2.5/3 7B-class coder.
- Medium (~20–30B): Qwen 2.5/3 Coder 30B, DeepSeek-Coder-V2 33B, or **gpt-oss-20b** (OpenAI's open weights release; coding-tuned).
- Large open (~70B–120B): Llama-3.x 70B, Qwen 2.5/3 72B Coder, or **gpt-oss-120b** (the larger gpt-oss release; expected to be the strongest single-server open candidate).
- Coding-specialist (separate from size tiers): **Composer 2.5** (Cursor's coding-tuned model; specifically targeted because it's optimized for the same agentic-coding-against-a-repo task the experiment measures, and because if a coding-specialist closes the gap to Claude that's a meaningful result for the rewrite story).
- Automated router (separate from size tiers): **OpenRouter fusion model** (whichever current routing/fusion offering OpenRouter exposes at experiment time — they have shipped multiple approaches). Tests whether automated per-query routing across underlying models beats fixed single-model or our hybrid configuration. This is the closest external analog to our hybrid mode but with routing decisions made by OpenRouter rather than by pm's stream-role assignments.
- Frontier closed: Claude (Opus default) — baseline.

The selection now includes "general open models at varying sizes" (the original Llama/Qwen tiers), "models targeted specifically at the coding agent task" (Composer 2.5, gpt-oss), and "automated routing of queries across multiple models" (OpenRouter fusion). Three orthogonal axes — comparing these slices answers separate questions: (a) does scale matter on this task, (b) does task-specific tuning close more of the gap than general scale, and (c) does automated cross-model routing match or beat our hand-tuned hybrid configuration.

**Test grid for the model dimension:**
- The Small / Medium / Large tier choices are picked at A1 pilot time based on local-inference feasibility. Run at least one general-purpose and one coding-specialist at each tier where both exist.
- Composer 2.5 runs at whatever size the model is delivered in; bucket it into the closest tier for reporting.
- gpt-oss-20b → Medium tier; gpt-oss-120b → Large tier.
- OpenRouter fusion runs in the all-open configuration only (C2-allopen, C3-allopen). The hybrid configuration doesn't apply because the fusion model already does its own routing; running it under our hybrid wrapping would double-route. Result is compared against both our hybrid (which uses Opus + open) and our all-open results to isolate "automated routing" as the variable.

**Conditions** (12 per cell, plus the Claude baseline in main matrix):
- C2-allopen-{S,M,L}: pm autostart, all streams on small/medium/large open model.
- C3-allopen-{S,M,L}: pm with planning, all streams on small/medium/large open model.
- C2-hybrid-{S,M,L}: pm autostart with sign-off on Opus, other streams on open.
- C3-hybrid-{S,M,L}: pm with planning, plan-add/plan-breakdown/plan-review/sign-off on Opus, impl/review/QA on open.

**Cells**: Python only initially. 2 repos × 4 strata × 12 conditions × 1 trial = **96 open-model cells**.

We do NOT run non-pm conditions (C0, C1) with open models — those test "what a user gets without pm using Claude Code," and the open-model analog would be a different experiment entirely.

**Budget**: separate local-GPU compute, not Claude sessions.

## Appendix §K — Interpretation dimensions

**From Phase A (correctness):**
- Iterations-to-sign-off distributions per language; Python vs FP candidates on matched non-DNF tasks.
- DNF rates and categories. `model-surrender` clustering signals corpus-thinness ceiling. `no-progress-loop` clustering signals loop weakness.
- Held-out fidelity-test pass rates relative to sign-off acceptance (the leak rate from "sign-off approved but behavior wrong").
- H6 review-feedback effectiveness gradient.
- H7 auto-generated artifact comparison.

**From Phase B (language):**
- Per-language DNF rates per task shape.
- Iterations-to-sign-off cross-language at the simplest-successful condition.

**From Phase C (perf):**
- Base perf rankings per task; algorithmic tasks (where I/O doesn't dominate) are the cleanest comparison.
- Speedup-vs-budget curves per language.
- H10 headroom-vs-base-quality.
- Verification-preservation rates per language.

**Independent low-level capability question (Phase B + Phase C low-level tracks):**
- DNF rates for LLVM IR and x86-64 by task — the shape (clean convergence on algorithmic, falloff elsewhere vs gradient).
- Perf of LLM-produced IR/asm relative to compiler-emitted IR/asm from corresponding source.

## Appendix §L — Session-budget breakdown

We pre-commit "six to ten max-mode Claude Code subscription sessions" for Phases A+B+C+D combined, plus separate open-model GPU compute.

- A1 ≈ 0.3 session; A2 ≈ 2–4 sessions; A3 ≈ 0.5 session
- B1 ≈ 0.3 session; B2 ≈ 1–2 sessions; B3 ≈ 0.5 session
- C1 ≈ 0.3 session; C2 ≈ 2–4 sessions; C3 ≈ 0.5 session
- D1 ≈ 0.1 session; D2 ≈ 0.5 session (conditional); D3 ≈ 0.3 session (conditional)

Open-model arm: separate compute budget on local GPU.

If A1 pilot shows gradient conditions cluster tightly at trivial complexity, drop redundant conditions from A2 for that stratum to save budget.

## Appendix §M — Open questions

- **Reviewer-model bias** (covered in §A).
- **Stdlib fairness** (covered in §A).
- **Optimization-loop selection rule** ("≥ 5% speedup required for acceptance"). Sweep in C1 pilot.
- **Composing vs restarting optimization across iterations.** Default: composing. Ablate if results are path-dependent.
- **Lean termination proofs may break under optimization.** Reject those candidates in the pilot; if common, C3 addresses with a "preserve totality proofs" addendum.

## Appendix §N — What this plan does NOT do

- Test compilation time, energy consumption, or hand-optimized human reference comparisons.
- Test optimization on real pm code (deferred to a C3 probe if C2 results justify).
- Commit to a specific reviewer model (pilot picks; choice recorded).
- Decide whether the rewrite, if motivated, uses workflow-driven mass translation vs incremental hand-port (separate follow-up plan).
