# Minimal Sufficient Inference — Branching, Recall, and Decomposition as Partial-Context Compilation

(an optimality target for efficient reasoning: a collection of streams and a single large-model-with-full-context are two ends of one equivalence. Measure any branching / recall / decomposition method by how close it comes to supplying only the **minimal sufficient context, experts, critical-path, and inter-node communication** needed to reproduce a reference oracle's output. The same equivalence runs *backwards* — a big model decomposes into a collection of small ones — which lifts small-model performance, recurses, and predicts the shape of the next frontier system.)

> Status: first draft. Companion to `literature-review-user-model-extension.md` §4.1 (the anti-sycophancy *branch* move) and to [[plan-memory]] (involuntary recall). Where §4.1 is about *generating* good reasoning, this is about *compressing* known-good reasoning to its efficient form. Citations are `unverified` until the augmented adversarial-review cycle audits them. Depends on a new plan-mind primitive (`BranchRequest`, §5).

## 1. Why this

The motivation to branch — or to recall, or to spin up sub-agents — is **efficiency and latency**, not capability in principle. In principle, any collection of cooperating streams could be replaced by a single larger model with a larger context that arrives at the *same output*. That hypothetical larger-model-with-everything is the **reference oracle**. Once it is fixed, every orchestration technique becomes measurable as a single question: *does it reproduce the oracle's output while supplying less?* — less context, fewer active experts, a shorter critical path, less communication between parts.

This turns a pile of heuristics (branch here, recall that, fan out, summarize) into approximations of one well-posed object: **the minimal sufficient inference for a given output.** The oracle's output is the ground truth; context / experts / path / communication are the costs; the optimum is the method that reproduces the output at least cost.

The equivalence is **bidirectional**, and the backward direction is where the leverage is:

- **Streams → oracle.** The reference: a collection of streams is *understood* as an approximation of one big model with full context.
- **Big model → collection of small ones.** The construction: a big model's computation is *decomposed* into a collection of smaller models, each handed only its minimal sufficient context. This is not merely a compression of the big model — it is a **constructive capability-lift for small models**: a collection of small models, orchestrated with the right minimal contexts, can reproduce outputs none of them produces alone.

Because the decomposition can be applied **recursively**, and because each application is an efficiency win, the efficient equilibrium is self-similar: **if the assumptions hold, the next "big model" should itself look like a recursively-decomposed collection of smaller models** orchestrated by branch-emit-join over minimal-sufficient contexts — a compound system, not a monolith. And such a collection is **runnable on more distributed, loosely-coupled, commodity hardware**, which is a *dollar-cost* win distinct from (and on top of) the FLOP / memory-bandwidth wins — feeding a second, economic flywheel.

## Core claims

- **C1 — Oracle equivalence.** For a given output, a collection of streams has an equivalent single-model-with-full-context oracle, *holding side-effect-gathered information and search/variance fixed* (those are separate value sources; see §2.3).
- **C2 — Branching/recall are partial-context approximations.** Their quality is closeness to the **minimal sufficient context + minimal sufficient experts** (the economy axis) and to the **minimal critical path** (the latency axis).
- **C3 — Bidirectional / small-model lift.** The same equivalence run backwards (big → collection-of-small) is a *constructive* method to make small models perform like big ones, not only an analysis of big ones.
- **C4 — The optimum is uncomputable, so amortize it.** The optimal decomposition is a recursive Bellman fixed point (infinite regress) and, in the limit, Kolmogorov-uncomputable. The target is approached by training a committing **policy ("intuition")** that decides in a forward pass; *not allowing backtracking (much)* is what makes it both learnable and low-latency.
- **C5 — Perplexity is a bootstrap, not the objective.** Perplexity-gated decomposition cheaply generates committed traces (a training-compute optimization). The real objective is efficiency + latency (+ dollar-cost) directly in the loss; perplexity then drops to scaffolding.
- **C6 — The bootstrap is self-supplying.** Decomposition is latent in the pretraining corpus (every proof, modular codebase, tutorial is a human decomposition) and cheaply verifiable (perplexity), so the model generates and curates its own training traces — *it works on itself*. The fixed oracle anchors this to **efficiency-only** self-improvement (capability-preserving).
- **C7 — Minimal emissions ⇒ distributability ⇒ dollar-cost win.** The emissions between branches *are* the inter-node messages. Minimal sufficient emissions mean minimal inter-node bandwidth, which is exactly what lets the collection run on cheap, loosely-coupled hardware. The same compression that buys context-economy buys distributability.
- **C8 — Frontier prediction.** Recursively applied, the efficient-equilibrium architecture is a decomposed collection of small models; the next frontier system should look like this if C1–C7 hold. Its concrete architectural form is branching into *specialized* models with tight information-bottleneck interfaces (§4.7) — MoE generalized to run cross-machine.
- **C9 — Generate then compress, never fused.** Low-perplexity is the *opposite* of §4.1's anti-sycophancy goal; they coexist only as sequential stages — generate-well (exogenously gated) then compress-well (perplexity-gated) — with the output pinned to the oracle so compression never moves it.
- **C10 — Compute-shape-adaptive deployment.** The target is frontier-level performance on **ephemeral swarms of consumer hardware** *and* of **custom hardware** — specialists small enough to hard-code onto single-layer packages, single chips, or FPGAs — while **adapting to the exact compute shape available**. These are two things a monolithic frontier model cannot do today: it needs one large, fixed, tightly-coupled machine, and it cannot reshape itself to the hardware on hand. Enabled by C7 — minimal emissions make the branch-emit-join DAG a cheap *mapping target* for heterogeneous, changing hardware graphs.
- **C11 — Speculation hides sequential latency.** A trunk can *predict* a branch's emission `ĉ_i` and proceed before the branch returns, verifying on arrival (`ĉ_i ≈ c_i` → keep the speculative downstream work, the branch's latency fully hidden; mismatch → squash and recompute). This extends span-reduction to *irreducibly sequential* chains that parallelism cannot help, and it is the principled form of §2.4's bounded backtracking — commit forward on a guess, backtrack only on a verified miss. Its payoff scales with emission *predictability*: the same low-perplexity that makes an emission compressible (C2) makes it speculatable (high acceptance).

## 2. A mechanistic account

### 2.1 The oracle and the minimal quantities

Fix an output `y` and measure everything under the oracle. Four minimal quantities, each with a formal home (anchors to verify):

- **Minimal sufficient context** `C*(y)` — smallest subset of available information that preserves the output. The **information-bottleneck / rate–distortion** quantity (Tishby, Pereira & Bialek 1999; Tishby & Zaslavsky 2015) and the **minimal sufficient statistic** (Fisher; Lehmann–Scheffé); its uncomputable limit is the **algorithmic sufficient statistic** (Kolmogorov; Gács–Tromp–Vitányi). Minimize `I(supplied ; full)` subject to `distortion(output, oracle-output) ≤ ε`.
- **Minimal sufficient experts** `E*(y)` — smallest active compute. **Conditional computation / MoE** (Shazeer et al. 2017; Switch Transformers).
- **Minimal critical path** `D*(y)` — the latency floor. **Work–span model**: latency ≥ span no matter the hardware (Brent's theorem 1974; Blelloch); the inherent **circuit depth** of producing `y`.
- **Minimal inter-node communication** `M*(y)` — smallest total message volume between parts. **Communication complexity** (Yao 1979). This is the axis that converts efficiency into *dollars* (§2.5).

"Experts" is one word at two levels — *which sub-streams to spawn* (orchestration) and *which MoE experts to route* (architecture) — both being conditional sparse selection of just-enough capacity. That coincidence is why the same measure governs orchestration today and architecture tomorrow (§2.5, C8).

### 2.2 The decomposition construction (and why emissions are the load-bearing object)

Given a reasoning chain `R` producing `y`, under the oracle:

1. Find minimal `C* ⊆ R` with `PPL(y | C*)` low — **holding `y` fixed to the oracle output** (C9).
2. `C*` has components `{c_1…c_k}`. For each, find a subset `S_i ⊆ R` with `PPL(c_i | S_i)` low. Each `(S_i → c_i)` is a **branch**; `c_i` is its **emission** back to the trunk.
3. The trunk produces `y` from the joined emissions `{c_i}`. Recurse on each `S_i` for depth.

Three properties of this structure carry the whole thesis:

- **The emissions are the Markov blanket of the output.** `{c_i}` screen off the raw context from `y`: the trunk needs the blanket, not `R`. Branches are lemma-provers; the trunk composes lemmas.
- **Perplexity is the certified-summary gate.** This sits in tension with plan-mind's **no-peer-summary / side-effect-as-truth** invariant, which forbids lossy paraphrase emissions. The reconciliation: *a low-perplexity emission is a certified-safe summary* — the perplexity gate bounds the information lost relative to the output. The invariant is refined, not broken: summaries are admissible iff they are perplexity-certified minimal-sufficient components.
- **The emission is the inter-node message.** The only thing crossing a branch boundary is its emission `c_i`. Minimizing emissions (the rate axis) therefore *directly* minimizes inter-node bandwidth — which is the technical fact behind distributability and the dollar-cost win (§2.5).

This one construction yields **both** efficiency axes at once: the DAG's *node set* is the context/expert economy; its *depth* is the span/latency; its *edge volume* is the communication cost. It also *measures a task's intrinsic parallelizability* — wide reasoning collapses to a shallow DAG (big span win), irreducibly-sequential reasoning stays a line (no span win, but possibly still a context win).

### 2.3 Bidirectionality, and what the equivalence does *not* cover

- **Forward (streams → oracle)** is the reference frame: judge a stream collection by how close it gets to the oracle at lower cost.
- **Backward (big → collection-of-small)** is the constructive program: decompose the big model's reasoning into branches a *small* model can each carry, and the collection reproduces the big model's output. This lifts small models — the practical payoff.

The equivalence is clean only for branching's **efficiency** role. Branching also does **information-gathering** (side effects: running code, fetching the web bring in information no context had) and **search / variance-reduction** (sampling many continuations and selecting). To isolate efficiency, the oracle's context must *include* the side-effect results, and the oracle must internally perform any search the branching did. The measure targets the first role; the other two are real but separate (and §4.1 is precisely about the search/anti-mirror role).

### 2.4 Uncomputable → amortized committing policy ("intuition")

To know whether a decomposition is optimal you need its sub-decompositions to be optimal, which need theirs — a **Bellman fixed point with infinite regress**; exact evaluation is intractable (exponential recursive search) and, at the limit, uncomputable (Kolmogorov). So, as in RL with an intractable value function, **amortize it into a learned policy** that approximates the fixed point in one forward pass and breaks the regress by predicting value directly instead of rolling it out. This is the **expert-iteration / AlphaZero move** one level up: an expensive search-with-backtracking (System 2) distilled into a fast committing policy (System 1).

- **No-backtracking is doubly motivated.** Backtracking is sequential rework → it lengthens the span; a committing policy is low-span *by construction*. So the constraint that makes the intuition learnable is the same one the latency objective wants.
- **"Not too much" is the System-1/2 dial**, set by the **value-of-computation** rule (metareasoning; Russell & Wefald 1991): spend a backtrack only when expected gain exceeds its span cost. The amount of allowed backtracking is itself an instance of the optimality measure, applied to the meta-decision.

**Speculation is the concrete form of bounded backtracking.** Rather than block at a branch, the trunk emits a *predicted* emission and continues; the branch runs concurrently and, on return, *verifies* the guess — accept (keep the speculative downstream work, latency fully hidden) or reject (squash and recompute). This is speculative execution (CPU branch prediction) and speculative decoding (Leviathan et al. 2023; Chen et al. 2023) generalized from token-drafting to *emission*-drafting, and it attacks exactly the case parallelism cannot — a deep, sequential chain — by predicting the link instead of waiting on it. Expected payoff = acceptance-rate × span-saved − miss-rate × wasted-work — again the value-of-computation decision; and acceptance is governed by the emission's perplexity under the trunk (predictable emissions speculate well). **Correctness rail:** a speculative emission is *provisional* — quarantined, never written to the canonical record — until the branch verifies it, so side-effect-as-truth holds (no guess escapes as truth). This needs substrate support (§5).

### 2.5 Two flywheels and the frontier prediction

- **Technical-efficiency flywheel.** Each round, the policy reproduces the oracle output more cheaply → the freed budget runs a *larger effective oracle* → better targets → more efficiency. The fixed oracle keeps each step capability-preserving; capability grows only via freed budget.
- **Economic flywheel.** A collection of small models with minimal emissions runs on **distributed, loosely-coupled, commodity** hardware — no single machine with massive HBM and fat interconnect. That is a **dollar-cost** efficiency, distinct from FLOP/memory-bandwidth efficiency, and the larger of the two: it sidesteps the memory-bandwidth wall and the cost of tight interconnect. Cheaper inference → more budget → bigger effective oracle → … the same loop, now driven by price.

Put together (C8): if recursive decomposition is an efficiency win at every level and the wins compound through both flywheels, the **efficient-equilibrium architecture is recursive decomposition** — the next frontier system should *be* a compound collection of small models orchestrated by branch-emit-join over minimal-sufficient contexts, runnable on distributed hardware. This is a falsifiable prediction about where the frontier goes, derived from the optimality measure rather than asserted.

**Compute-shape-adaptive deployment (C10).** The decomposition is not merely *distributable* — it is a **mapping target**. The branch-emit-join DAG can be scheduled onto whatever hardware graph is present and *re-mapped as nodes join and leave*, because minimal-sufficient emissions keep the inter-node links thin enough to tolerate weak, heterogeneous, or transient connections. That unlocks deployment shapes a monolith cannot reach: **ephemeral consumer swarms** (volunteer / spot / edge compute that comes and goes) and **custom-hardware swarms** down to specialists baked into single-layer packages, single chips, or FPGAs (§4.7). The system adapts the *decomposition* to the compute on hand, rather than requiring the compute to match a fixed monolithic shape — the inverse of today's deployment constraint. (Anchors, to verify: volunteer / decentralized inference — Petals, Learning@home / DeDLOC; FPGA and ASIC LLM-inference work.)

**Two timescales, and why per-hardware targeting is affordable.** Adaptivity runs at two speeds: *runtime re-mapping* (schedule the existing DAG onto whatever nodes are present — fast, online) and *architecture synthesis* (generate a fresh decomposition + specialist set + interface widths **targeted at a specific hardware shape** — offline). The second is what makes bespoke-per-hardware viable, and it is affordable precisely because of the bootstrap (C5–C6): once producing and curating specialists is cheap and self-supplying, **spinning up a new network architecture for new hardware becomes cheap and ideally fully automated** — hardware-aware synthesis as a routine, not a research project. It is the same "the model works on itself" loop pointed at silicon: the system designs its own hardware-targeted variants, and each new target widens the deployable hardware base (feeding the economic flywheel). (Anchors, to verify: hardware-aware NAS / AutoML; hardware-software co-design.)

## 3. Related work

(Subsections for the adversarial-review pass; all `unverified` until audited.)

### 3.1 Sufficiency and information
Information bottleneck (Tishby, Pereira & Bialek 1999; Tishby & Zaslavsky 2015); rate–distortion (Shannon 1948; Cover & Thomas); minimal sufficient statistic (Fisher; Lehmann–Scheffé); algorithmic / Kolmogorov sufficient statistic (Kolmogorov; Gács, Tromp & Vitányi). The formal home of "minimum sufficient context" and its uncomputable limit.

### 3.2 Parallel and communication complexity
Work–span model and Brent's theorem (1974); Blelloch's NESL work-span analyses; circuit depth / NC; communication complexity (Yao 1979). The home of "minimum critical path" and "minimum inter-node communication."

### 3.3 Conditional computation and sparsity
Mixture-of-experts (Shazeer et al. 2017; Switch Transformers, Fedus et al. 2021); early-exit / adaptive depth (BranchyNet, Teerapittayanon et al. 2016; CALM, Schuster et al. 2022); sparse attention and KV-cache eviction (StreamingLLM, Xiao et al. 2023; H2O, Zhang et al. 2023). "Minimum experts / minimum context" realized inside today's architectures.

### 3.4 Test-time compute and latency
Speculative decoding (Leviathan et al. 2023; Chen et al. 2023); parallel decoding (Medusa); Skeleton-of-Thought (Ning et al. 2023) — explicit decompose-then-parallelize for latency; tree-of-thoughts / search (Yao et al. 2023). Cross-reference `user-model-extension` §3.3 to avoid duplication; the distinction there (endogenous vs exogenous selection) applies here too.

### 3.5 Amortization and search-distillation
Amortized inference (Gershman & Goodman 2014 — the same Gershman as the computational-rationality paper); expert iteration (Anthony et al. 2017) and AlphaZero (Silver et al. 2017); STaR (Zelikman et al. 2022) as the generate→filter→retrain shape; **model collapse / curse of recursion** (Shumailov et al. 2023/2024) as the self-training failure the oracle-anchor must defeat.

### 3.6 Prompt vs. weight compilation
Automatic prompt optimization (APE, Zhou et al. 2022) and program-of-prompts compilation (DSPy, Khattab et al. 2023) — the *coarse* dual; learned control tokens (R1's `<think>`) — the *fine* form. Cross-reference §4.1's coarse/fine and [[prompt-first-then-compile-to-tokens]].

### 3.7 Compound systems and distributed inference
The compound-AI-systems thesis (Zaharia et al. 2024) — systems of models outperform monoliths; distributed inference over commodity hardware (Petals, Borzunov et al. 2023); mixture-of-agents (Wang et al. 2024); model cascades / cost-routing (FrugalGPT, Chen et al. 2023). The architectural and economic grounding for C7–C8; the memory-bandwidth wall / roofline (Williams et al.) is the cost backdrop.

## 4. Proposed method / experiments

### 4.1 Bootstrap — perplexity-gated decomposition (cheap warm-start)
Offline, over existing good reasoning chains: search for minimal `C*` and the branch decomposition by perplexity-sufficiency; emit **committed marker traces**. Sources: human-authored decompositions already in the corpus (proofs, modular code, tutorials) as seeds, plus LLM-generated-and-perplexity-filtered traces for scale (STaR loop). Cheap to generate (latent skill) and cheap to verify (one forward pass) — which is the entire reason it is a training-compute optimization rather than the objective.

### 4.2 Main objective — efficiency + latency + dollar-cost in the loss
After warm-start, optimize the real costs directly: context size / active-expert count (economy), span (latency), and **inter-node message volume** (the distributability/dollar proxy), subject to oracle-fidelity. Perplexity drops to scaffolding. Likely RL or cost-aware fine-tuning (the objective is over discrete decompositions and downstream execution).

### 4.3 The committing policy / marker model
A model that emits `<branch>` / `<emit>` / `<join>` in a single forward pass with no rollback — i.e., a no-backtrack decomposition policy. Train commitment in by penalizing backtracks (behavior-clone the search's *committed* trace, or RL with a backtrack penalty). The marker emissions are the policy's actions; the runtime executes them via `BranchRequest` (§5).

### 4.4 The prompt-learned dual (coarse, no training)
The same discovered decompositions serve as few-shot exemplars for prompt-optimization (DSPy/APE) instead of fine-tuning data — eliciting decomposition by prompt before compiling it into tokens. Coarse gates fine.

### 4.5 Evaluation
Operational proxies: context → `KL(oracle-output ‖ output-under-supplied-context)` vs token count; experts → active params/FLOPs vs distortion; latency → wall-clock span + fraction of needed context prefetched off the critical path; communication → inter-node bytes per output. Plus: **intrinsic parallelizability** (DAG depth vs chain length) and the **small-model-lift benchmark** — does a collection of small models, decomposed this way, reach the big model's output? — and matched-compute controls (per §4.1's rigor).

### 4.6 Self-distillation flywheel (instrumented for collapse)
Iterate generate → perplexity/cost-filter → retrain; let efficiency gains expand the effective oracle. Instrument for **collapse** (diversity/quality erosion) and test whether the fixed-oracle anchor (regenerating *decompositions of fixed-output reasoning*, not outputs) prevents drift.

### 4.7 Follow-up — branching into specialized models (distributable, tight-bottleneck MoE)
The natural extension of C7–C8: branch not into transient reasoning streams but into a **library of specialized models** (a specialist per sub-problem class — a lemma type, a domain) plus a decomposer that routes work to them. This generalizes MoE from specialized FFN sub-blocks to specialized *whole (small) models*. The load-bearing difference is the **interface**: conventional MoE couples its experts through a *loose* bottleneck — per-token all-to-all routing of full hidden states, bandwidth-bound, which confines it to a tight interconnect (intra-node / NVLink). Here the inter-model interface is the **minimal sufficient emission** `c_i` — a *much tighter information bottleneck* — so inter-model traffic is small and the specialists **parallelize across multiple machines**, not just within a node. That is C7's distributability made architectural and C8's frontier prediction made concrete: the dollar-cost win comes from trading fat per-token routing for thin branch-emit-join.

**Hardware endpoint.** Taken to the limit, a specialist that is small enough and has a tight enough interface need not run on a general processor at all — it can be **hard-coded into a single-layer package, a single chip, or an FPGA** as a fixed-function inference block. A swarm of such blocks plus a decomposer/router *is* a frontier system realized on custom silicon, with the minimal emissions as the only signals crossing package boundaries. This is the concrete hardware form of C10's custom-hardware swarms, and it is why the interface-tightness question below is not merely an efficiency knob but a *manufacturability* threshold.

The perplexity-decomposition traces (§4.1) already cluster by sub-problem type, which is the natural specialization signal — and the "branch then recombine specialists" training shape has direct precedent (Branch-Train-Merge, Li et al. 2022; Branch-Train-MiX, Sukhbaatar et al. 2024; DEMix, Gururangan et al. 2021 — all `unverified`). **Open question:** how tight can each specialist's interface get before fidelity drops (its rate–distortion frontier), and does tight-bottleneck specialization beat dense/loose MoE on the joint (quality, dollar-cost) frontier — the crossover C7 asserts but does not prove.

## 5. Relation to the program

- **`user-model-extension` §4.1** — the *generation* side (exogenously-gated branching against sycophancy); this is the *compression* side. Shared machinery: branch/resolve/cut tokens; analogical recall is the shared cell.
- **[[plan-memory]]** — recall is the retrieval-space sibling of branching; involuntary recall is a **span optimization** (work prefetched *off* the critical path), which this framing explains precisely. Same construction, different operator.
- **[[plan-mind]] — `BranchRequest`.** The marker model's `<branch>/<emit>/<join>` rests on a first-class primitive for a stream to spawn a child with a dynamically-generated input and a return channel (`BranchRequest`, sibling of `AttentionRequest`; budget/depth-governed — now in plan-mind §7b). `BranchTask.context_refs` = the `S_i`; the child's return emission = the `c_i`. **Speculation (C11) needs a speculative mode**: the parent supplies a *predicted* emission + a verify-callback instead of blocking on `await_join`, and the Mind tracks that emission as provisional (promote on accept, squash on miss) — proposed as an extension to the primitive.
- **[[prompt-first-then-compile-to-tokens]]** — this review is the concrete profiler→compiler pipeline that staging law predicts: perplexity-decomposition is the profiler, the marker model is the compiled artifact.
- **[[minimal-sufficient-inference-optimality]]** (memory) — the north-star statement this review develops.
- **`plan-self-improve`** — the *model-internal* analog of pm's orchestration-level recursive self-improvement; the efficiency flywheel here mirrors the tournament there.
- **Cognitive models are reproduction targets, not blueprints.** The operation set here and any borrowed model (ACT-R activation, CLS consolidation / reasoned→rote, SOAR impasse + chunking, Global-Workspace ignition) are *functionality the learned substrate must be able to arrive at* — baselines to reproduce and beat, not architectures to hard-code. They form a behavioral benchmark battery; the substrate's job is expressiveness (can it represent each, ideally via composition?), and coverage against that battery is audited separately rather than asserted here. Same move as reproducing the oracle's output without baking in the decomposition.

## 6. Open questions / falsifiers

- **Perplexity ≠ correctness.** The compress stage is safe only because `y` is pinned to the oracle; if the gate ever moves the output, confident-error compression returns (the §2.2 sycophancy failure). Is the firewall holdable in practice?
- **Self-distillation collapse.** Does iterated decomposition-distillation erode diversity/quality, and is the fixed-oracle anchor sufficient to prevent it?
- **Joint, not separable.** Minimal context and minimal experts co-depend (which experts you need depends on the context); greedy per-component minimization may miss the global optimum.
- **Oracle reference-relativity.** No canonical "largest model" — the measure is relative to a chosen reference. Does the frontier prediction (C8) survive when the reference itself is moving?
- **Which reasoning parallelizes.** Some chains are irreducibly deep (span win ≈ 0); the achievable distributability is bounded by the task's intrinsic dependency structure.
- **Latent-skill ceiling.** If decomposition quality is bounded by what's latent in the corpus, the achievable frontier is too — until the flywheel pushes past it (or fails to).
- **Does the dollar-cost win actually dominate?** C7 asserts communication-minimal collections beat monoliths on price; the crossover depends on real interconnect/HBM economics — to measure, not assume.
- **Compute-shape adaptivity — mechanism and overhead (C10).** How does the decomposition *re-map* onto a changing, heterogeneous swarm (nodes joining/leaving; GPUs vs CPUs vs FPGAs vs hard-coded packages), and does adaptive re-mapping preserve quality at acceptable scheduling/migration overhead? And how small/tight must a specialist be to fit a single chip or FPGA — the manufacturability threshold (§4.7)?
- **Automated hardware-targeted synthesis — cost and quality (C10, §2.5).** Can architecture synthesis for a given hardware shape actually be made cheap and fully automated, and does an auto-synthesized architecture match a hand-designed one's quality? If synthesis stays expensive or needs human tuning per target, bespoke-per-hardware deployment loses its economic edge.
- **Speculation economics and safety (C11).** Is the branch-emission acceptance rate high enough on real tasks that hidden latency outweighs wasted compute on mispredictions? And can speculative emissions be reliably quarantined (never escaping as canonical truth before verification) without prohibitive rollback/checkpoint overhead?

## Methodology note

All citations above are `unverified` until the augmented adversarial-review cycle (`pm/docs/adversarial-review/`, per the litreview methodology) audits them — same standard as the user-model and living-artifacts reviews. The proposed experiments are sketches; the load-bearing empirical claims (small-model lift, collapse-resistance, dollar-cost crossover) are flagged for first study.

## Appendix A — A minimal, runnable first experiment

**What it tests, cheapest first.** Two foundational claims, in cost order: that a **minimal sufficient context exists and is much smaller than the full chain while preserving the output** (C1/C2), and that **a small model decomposed into sub-contexts reaches outputs it misses when handed the whole problem at once** (C3, the headline). Phase 1 needs *one* model and *no training*; Phase 2 adds a second. Both run on a laptop with small open models (exact perplexity) or modest API spend (if logprobs are exposed).

**Dataset.** 50–200 items with short, *verifiable* answers and a decomposable chain — GSM8K is the canonical pick (line-structured steps, exact-match answer). Any short-answer multi-step QA works.

**Models.** Phase 1: one model `M` with token-logprob access (a local 1–8B HF model for exact, free PPL; or an API that returns logprobs). It plays both **oracle** (defines the target `y`) and **scorer** (computes PPL). Phase 2: add a **small** model `S` (≈1–3B) as the branch executor; `M` (or a larger API model) stays the oracle that defines `y` and the decomposition skeleton.

### Phase 1 — minimal sufficient context by perplexity-gated ablation (single model, ~1 hr)
For each item: `full = problem + chain`, `y = answer`, `base = PPL(y | full)`. Split `full` into units (sentences / chain steps) and greedily drop units that don't hurt:
```
keep = units(full)
for u in units:                                  # one pass; order = original, or by leave-one-out PPL delta
    if PPL(y | keep \ {u}) <= base * (1 + eps):   # eps ~ 0.05; y held FIXED
        keep.remove(u)
Cstar = join(keep)
```
**Measure:** compression ratio `|Cstar|/|full|`; answer preserved (exact-match still correct *and* `PPL(y|Cstar) <= base*(1+eps)`); fraction of items compressing ≥ 2×.
**Supports C1/C2 if** `Cstar` is materially smaller than `full` (say median ≤ 50%) with the answer preserved on most items. **Falsifies if** you can't drop much without the answer degrading — minimal sufficient context isn't much smaller than full for this task class. (Greedy ≠ optimal, per C4 — this is a *lower bound* on compressibility.) This pass also yields the §4.1 bootstrap traces for free: each `Cstar` + retained units is a committed-decomposition seed.

### Phase 2 — small-model lift from decomposition (two models)
Use the chain's natural steps as components `c_i`; for each, `S_i` = problem + the minimal prior steps Phase-1 ablation kept. Compare `S` in two conditions at the **same total token budget**:
- **Baseline:** `S`, problem → answer (its own CoT). For matched compute, give `S` self-consistency with `k` samples so its token spend ≈ the decomposed pipeline's.
- **Decomposed (branch-emit-join):** for each `i`, `S` given `S_i` emits `c_i'`; then `S` given `{c_i'}` composes `y'`.

**Measure:** accuracy vs gold (and vs oracle `y`) per condition; total tokens; **emission size** `Σ|c_i'|` vs `|full|` (the C7 communication proxy).
**Supports C3 (and C7) if** decomposed accuracy beats the matched-compute baseline by a real margin with `Σ|c_i'| ≪ |full|`. **Key confound:** the skeleton (which `S_i`) is oracle-derived, so some lift may be skeleton-leakage rather than decomposition itself — ablate by also running a skeleton produced by `S`; the oracle-vs-`S` skeleton gap isolates "decomposition helps" from "oracle hint."

### Phase 3 (optional) — speculation headroom (one model, tests C11)
Cheap training-free add-on: for each branch, measure how often the trunk model predicts `c_i` from `S_i` *minus the branch's own work* within `eps` — the **acceptance rate**. High acceptance ⇒ speculation can hide that branch's latency (proceed on the guess); low acceptance ⇒ the branch carries real surprise and must be waited on. The acceptance-rate distribution across branches is a direct estimate of how much *sequential* latency C11 could remove on this task class — the one axis Phase 1/2's parallelism can't.

### Cost & knobs
~50–200 items; Phase 1 is `O(units)` forward passes per item (cheap with a local small model); Phase 2 adds `O(steps)+1` short generations per item per condition. Knobs: `eps` (sufficiency tolerance), unit granularity (sentence vs step), `k` (matched-compute samples).

### Pitfalls
- **Hold `y` fixed** when scoring PPL — never let ablation change the target (the C9 firewall); otherwise you measure confident-error compression, not sufficiency.
- **Logprobs:** if the API hides them, run Phase 1 on a local HF model — PPL needs token logprobs.
- **Greedy order matters** — report it; leave-one-out scoring gives a tighter `Cstar` at the cost of more passes.
- **Tokenizer consistency** — score PPL with the same model/tokenizer that defines `y`.

**One afternoon's output** is a compression-ratio number (C1/C2) and a decomposed-vs-baseline accuracy delta at matched compute (C3) on 50–200 GSM8K items — enough to decide whether the bootstrap and the small-model-lift are real before investing in the training loop (§4.2–4.3).
