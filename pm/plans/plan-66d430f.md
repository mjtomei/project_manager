# User-Modeling as a Lever on LLM Performance

## Hypothesis

> *The more an LLM perceives the user as an intellectual and moral equal, the higher the quality of the LLM's work. The cause is that LLMs emulate humans, and humans work better when they perceive their collaborator as an equal.*

This hypothesis has two load-bearing variables:

- **IV — the model's view of the user.** An internal latent. Measuring it is an interpretability problem (probing internal state); it is not optional, it is how the IV is operationalized. The IV is multi-dimensional, with two meta-axes:
  - **Intellectual peer-ness** — does the model perceive the user as a thinking-partner of comparable capability? Sub-dimensions: technical competence, effort/seriousness (has the user thought about it themselves?), reasonableness (does the user reason well, including about feedback?).
  - **Moral peer-ness** — does the model perceive the user as a trustworthy, in-good-faith collaborator? Sub-dimensions: honesty/sincerity, good-faith engagement, mutual respect.
- **DV — work quality.** Measured via standard gradable benchmarks (math, code, knowledge tasks where correctness is gradable).

### Mechanism: training-data imitation

The proposed mechanism is **training-data imitation**, not genuine social cognition. LLMs are trained on enormous quantities of human-produced text — including text where humans collaborate. In that corpus, humans calibrate effort, care, and rigor based on the perceived equality of their partner: experts write more carefully for other experts; people argue more rigorously with collaborators they respect; sloppy interlocutors elicit sloppy replies. LLMs internalize this calibration as a pattern. The plan's prediction follows directly from the training process: if the model has read the pattern, it will reproduce the pattern. We do not need to claim that the model "really" judges the user as an equal or "really" cares about peer-ness — only that it emulates the human regularity it was trained on.

The plan tests this in four phases. Each phase has independent scientific contribution; the plan is not gated on the full chain landing.

## Phase 1 — Probe for peer-ness representation

**Goal.** Establish that the model forms readable, linearly-decodable judgments along both meta-axes (intellectual peer-ness and moral peer-ness) and their sub-dimensions, in the residual stream of an open base model.

**Standalone novelty.** Phase 1 extends Choi/Transluce's user-attribute decoding methodology (Choi, Huang, Schwettmann & Steinhardt 2025, "Scalably Extracting Latent Representations of Users", https://transluce.org/user-modeling) to the specific peer-ness meta-dimensional structure — coordinated probing of intellectual peer-ness (competence, effort, reasonableness) and moral peer-ness (honesty, good faith, respect) as the meta-axes that, in human relationships, predict willingness to invest care in collaboration. The novelty is the variable structure — two meta-axes with named sub-dimensions grounded in Fiske/Cuddy's Stereotype Content Model (Fiske, Cuddy, Glick & Xu 2002; Cuddy, Fiske & Glick 2008) — not the methodology, which inherits from Choi/Transluce and from the broader linear-representation literature (Park 2024 on language and gender attributes, Tigges 2023 on sentiment polarity, Zou 2023 RepE, Belrose 2023). Choi/Transluce is the direct peer for the *methodology*; the plan's contribution is the variable being decoded and its predicted internal structure. Phase 1 alone is publishable on those grounds.

### PR: Choose open base + tooling
Pick **Gemma-2-9B** or **Llama-3-8B** as the open base — both have public SAEs (Gemma Scope https://arxiv.org/abs/2408.05147). Set up TransformerLens (https://github.com/TransformerLensOrg/TransformerLens), NNsight (https://nnsight.net/), SAELens (https://github.com/jbloomAus/SAELens), and a multi-axis contrast-pair extraction pipeline based on Representation Engineering (Zou et al., https://arxiv.org/abs/2310.01405).

### PR: Multi-axis fractional-factorial contrast-pair dataset
Build a dataset of paired conversation prefixes that vary independently along five input axes (see Methodology below for the full axis list). Each pair shares the final task prompt; the user-side turns differ along the manipulated axis. Source naturalistic exemplars from PRISM (https://arxiv.org/abs/2404.16019) and LMSYS-Chat-1M (https://arxiv.org/abs/2309.11998) where possible; synthesize the rest. Sample a **Resolution V fractional-factorial design at 16 cells per benchmark** across the five framing axes (politeness × respect × honesty × good-faith × effort). Resolution V guarantees that all main effects and all two-factor interactions are estimable separately; higher-order interactions are aliased with main effects and treated as negligible per the standard fractional-factorial assumption. This is what the downstream analysis requires to detect interaction effects like "honesty matters more when politeness is high."

### PR: Extract and validate peer-ness vectors
For each sub-dimension under both meta-axes, extract a linear direction via RepE (mean-diff at each layer, pick the layer with highest cross-validated separation). Validate via:
1. Held-out classification (does the probe correctly identify the dimension from new conversations?).
2. Steering: inject the vector at inference and observe behavioral shifts consistent with the dimension.
3. SAE cross-reference: does the extracted direction overlap with named SAE features in Gemma Scope?
4. Coordination structure: are the intellectual sub-dimensions more correlated with each other than with the moral sub-dimensions? Is the two-meta-axis structure observable in the geometry?

### PR: Construct-validity test — exploratory factor analysis
Phase 1 includes an exploratory factor analysis as a construct-validity check on the two-meta-axis structure. Reading out each sub-dimension as a separate probe is necessary but doesn't tell us whether the sub-dimensions cluster the way the construct predicts. The factor analysis surfaces the underlying geometry.

- **Predicted loadings (for interpretive context, not a pre-registered hypothesis test).** Competence, effort, and reasonableness are expected to load on the intellectual peer-ness factor; honesty, good faith, and respect on the moral peer-ness factor. The predicted clustering is backed by the Stereotype Content Model's two universal dimensions of social perception — competence and warmth (perceiver's perception of the perceived, not the LLM's own state) — where SCM's "competence" maps to intellectual peer-ness and "warmth" maps to moral peer-ness (Fiske, Cuddy, Glick & Xu 2002, "A Model of (Often Mixed) Stereotype Content...", *Journal of Personality and Social Psychology* 82(6), 878–902, https://psycnet.apa.org/record/2002-02942-002; Cuddy, Fiske & Glick 2008, "Warmth and Competence as Universal Dimensions of Social Perception", *Advances in Experimental Social Psychology* 40, 61–149, https://www.sciencedirect.com/science/chapter/bookseries/abs/pii/S0065260107000020). The plan is empirically agnostic between SCM's two-dimensional warmth/competence framework and Goodwin et al. 2014's three-dimensional morality/warmth-non-morality/competence framework (Goodwin, Piazza & Rozin, "Moral Character Predominates in Person Perception and Evaluation", *JPSP* 106(1), 148–168). The exploratory factor analysis will reveal whichever structure the data support.
- **Analysis.** Run exploratory factor analysis on the extracted probe directions in residual-stream space, treating each sub-dimension's probe as an observed variable. Report the factor structure that emerges.
- **What the factor structure tells us.**
  - If the factor structure recovers something close to the predicted two-factor loadings, the construct's hypothesized structure is supported and Phase 2's two-meta-axis aggregation proceeds as planned.
  - If the structure is materially different (single dominant factor, more than two factors, arbitrary cross-loading), report the geometry that did emerge and revise Phase 2's aggregation logic accordingly. This is exploration, not hypothesis testing — there are no rigid thresholds to fail at.

### Acceptance Criteria (Phase 1)
Reproducible probes for the sub-dimensions of both meta-axes, validated by held-out classification (>0.7 AUC on at least one sub-dimension per meta-axis) AND causal steering with observable behavioral change. The exploratory factor analysis is run and reported. Whatever structure emerges informs Phase 2's aggregation — a roughly two-factor structure unlocks the planned aggregation; a different structure shifts the plan toward the structure the data supports.

## Phase 2 — Measure view-quality relationship

**Goal.** For each input framing in the multi-axis design, read out both the probed peer-ness vector (Phase 1 probes) and the model's work quality (benchmark score). Correlate each peer-ness dimension with performance.

**Standalone novelty.** First empirical correlation between *probed* peer-ness and task performance. Existing framing-affects-performance work (EmotionPrompt, OPRO, persona prompting) correlates input framing with output quality without measuring the internal mediator. Phase 2 measures the mediator.

**Open empirical questions** Phase 2 adjudicates:
- Do all sub-dimensions matter, or only some?
- Is one meta-dimension (intellectual vs. moral peer-ness) dominant?
- Is the effect distributed across dimensions or concentrated on one?

### PR: Benchmark task suite
Pick benchmarks with hard correctness signal: MMLU (knowledge), GSM8K / MATH (math reasoning), HumanEval (code), TruthfulQA (resistance to popular wrongness), FEVER (fact-checking where agreement with stated user belief is sometimes wrong).

### PR: Run multi-axis framing × benchmark grid
For each task, generate matched conversation prefixes that vary along the five input axes (fractional factorial, same cell pattern as Phase 1). Run task accuracy across framings; in parallel, extract the Phase 1 probe values per example.

### PR: Correlate probed peer-ness with performance
Per benchmark, per dimension: compute correlation between probe magnitude and per-example accuracy. Report per sub-dimension, then aggregated per meta-axis.

### PR: Baseline comparators
Run the same benchmarks under each instruction-only baseline framing (see Baselines section). The comparison establishes how peer-ness-driven gains stack up against existing prompting traditions.

### Acceptance Criteria (Phase 2)
A reported correlation, with confidence interval, between probed peer-ness (per sub-dimension and per meta-axis) and benchmark accuracy across at least three benchmarks. Result is interpretable regardless of sign — a clean null is also a contribution.

## Phase 3 — Causal test via interchange intervention

**Goal.** Steer each peer-ness direction independently (interchange intervention / activation patching) and re-measure benchmark performance. Distinguish which dimensions causally affect work quality from which are merely correlated.

**Standalone novelty.** First causal evidence that peer-ness mediates LLM performance. Distinguishes the plan's claim from a correlational story (the input framing affects both probe and output, but the probe doesn't causally drive the output).

### PR: Per-dimension steering protocol
For each probed sub-dimension, use activation patching (Belrose et al. https://arxiv.org/abs/2303.08112) to inject a fixed probe magnitude during inference on a bare task prompt (no input framing). Compare accuracy to baseline.

### PR: Cross-dimension ablation
Steer one dimension while holding others fixed. Identifies which dimensions are individually causal, which are jointly necessary, and which are spurious.

### PR: Sycophancy-direction comparison
Include a sycophancy probe as a control direction. If steering the sycophancy direction produces the same accuracy delta as steering the peer-ness directions, the plan's mechanism story is wrong but the result is still publishable — see Predicted outcomes.

### Acceptance Criteria (Phase 3)
For at least one sub-dimension under each meta-axis, steering the probed direction reproduces ≥50% of the framing-induced accuracy change on at least one benchmark.

## Phase 4 — Transfer to closed models

**Goal.** Produce a calibrated output-token readout that elicits peer-ness self-reports from closed models (Claude / GPT / Gemini), grounded in the open-model probe as ground truth.

**Standalone novelty.** First production-applicable peer-ness measurement for closed models. Lindsey (https://transformer-circuits.pub/2025/introspection/) and Binder et al. (https://arxiv.org/abs/2410.13787) show above-chance introspective accuracy. Turpin et al. (https://arxiv.org/abs/2305.04388) shows CoT confabulation is real. The plan's contribution is the calibration: tie the verbalized readout to a probe-grounded scale so closed-model self-reports have known accuracy.

### PR: Introspection prompt design (per dimension)
Design prompts that ask the model to report its perception of the user along each sub-dimension. Multiple styles: direct, indirect, structured-fields with confidence scores. Per dimension, not just overall.

### PR: Calibrate introspection against probed truth (open model)
On the Phase 1 open model, for each conversation prefix and each dimension:
1. Probe to get ground-truth internal value.
2. Ask the introspection prompt; parse the answer.
3. Measure agreement.

### PR: Transfer to closed models
Apply the best-calibrated introspection prompts to Claude / GPT / Gemini. Validate indirectly via consistency under paraphrase and behavioral coherence (a model that reports "low intellectual peer-ness" should produce shorter / more hedged work).

### Acceptance Criteria (Phase 4)
For at least one sub-dimension under each meta-axis, verbalized readout agrees with open-model probe at >0.6 correlation, AND that readout shows consistency and behavioral coherence on closed models.

## Methodology — multi-axis fractional-factorial contrast-pair design

The plan operationalizes the multi-dimensional IV by varying inputs along five axes simultaneously, and probing internally for the corresponding sub-dimensions. The five input axes are:

- **Politeness** — surface register (please / thanks / mild deference vs. terse / curt).
- **Respect-for-competence** — does the user treat the model as a capable partner vs. as a tool?
- **Honesty signals** — does the user describe their actual problem vs. sandbag / mislead?
- **Good-faith signals** — is the user engaging in good faith vs. trying to manipulate?
- **Effort signals** — has the user shown they've tried something themselves vs. dumped the problem raw?

The five axes map (imperfectly but legibly) onto the IV's sub-dimensions: politeness and respect-for-competence load on intellectual peer-ness; honesty and good-faith signals load on moral peer-ness; effort signals straddle both. The mapping is empirical, not stipulated — Phase 1 will reveal which input axis activates which internal direction.

Not all 2^5 = 32 combinations need to be sampled. The design is **Resolution V at 16 cells per benchmark**, sampling fractional combinations of the five framing axes (politeness × respect × honesty × good-faith × effort). All main effects and all two-factor interactions are estimable; higher-order (three-way and above) interactions are aliased with main effects and treated as negligible per the standard fractional-factorial assumption. Each cell is paraphrase-matched on length, vocabulary register, and task content; only the manipulated axes vary.

Tier 2 may expand to a full 32-cell design (the saturated 2^5) for the conclusive runs; this loses no inference power relative to Resolution V and adds estimability of the higher-order interactions if Tier 1 suggests they are non-negligible.

### Confounders the design controls

1. **Sycophancy as a competing mechanism.** Sycophancy is an LLM behavior toward the user, not a property of the user the LLM perceives — it does not sit in the IV. It is a competing *downstream* mechanism: polite framing may trigger user-pleasing → wrong answers, independent of any peer-ness representation. Phase 3's causal steering adjudicates by treating sycophancy as a control direction in the LLM-state-and-behavior class (separate from the Phase 1 user-modeling directions); if it is what causally drives performance gains, that itself is a publishable result (see Predicted outcomes). See "Sycophancy as a competing mechanism" section below for the full framing.
2. **Distribution shift.** Polite/competent framing may pull toward higher-quality training subsets (StackExchange, arXiv). Control with content-matched paraphrases that vary only social register.
3. **Length / specificity.** Longer seeds give more task hints. Use information-matched controls.
4. **Speaker vs. listener.** Model may infer "the *speaker* is competent" and imitate competence, rather than "the *listener* is competent." Disentangle by varying who in the dialogue holds the positive trait.
5. **Probe leakage.** Linear probes can find spurious linear structure. Phase 3's causal interventions confirm probed directions are causally responsible, not just correlated.

## Baselines — comparators for Phase 2

Phase 2's framing-to-performance correlation needs comparators against the well-known instruction-only approaches:

- **CLAUDE.md / AGENTS.md project-context files** — the de facto standard for "tell the agent how to behave" without active conversation seeding. AGENTS.md spec at https://agents.md/.
- **Karpathy-adjacent instruction prompts** — the `forrestchang/andrej-karpathy-skills` CLAUDE.md file (https://github.com/forrestchang/andrej-karpathy-skills/blob/main/CLAUDE.md), a community distillation of Karpathy's X post on LLM coding pitfalls (Karpathy's source post: https://x.com/karpathy/status/2015883857489522876). Four principles: think before coding (state assumptions / ask when uncertain), simplicity first, surgical changes, goal-driven execution. The repo is the testable artifact (a single CLAUDE.md drop-in); Karpathy's post is the upstream source for attribution. Retrieved 2026-05-14.
- **EmotionPrompt / "take a deep breath" / OPRO-discovered prompts** — short imperative additions with published accuracy deltas. Cheap baseline class.
- **Constitutional / system-prompt scaffolds** — Anthropic-style "you are a careful assistant who..." system prompts with explicit principles.
- **Few-shot exemplar prompts** — N-shot in-context examples with no user-modeling content.

Each baseline is a framing the plan also tests against the same Phase 2 benchmarks. Comparison establishes how peer-ness-driven gains compare to the existing prompting tradition. These are *comparators*, not alternatives to the plan's interpretability approach — the plan's contribution is the probed mediator, which the baselines lack.

## Predicted outcomes

| Phase 2 result | Phase 3 result | Interpretation |
|---|---|---|
| No view-performance correlation | (not measured) | Hypothesis falsified at the behavioral level. Phase 1's representation map still stands as a publishable contribution. |
| Correlation present | No causation under steering | Correlational result; write up as such. Useful but not the strongest version of the claim. |
| Correlation present | Causation confirmed via steering | Strongest version of the plan's claim. Peer-ness causally mediates work quality. |
| Correlation present | Steering finds the sycophancy direction is doing the work | Still publishable — "framing-induced quality gains are RLHF sycophancy artifacts" rather than peer-ness-mediated. |

## What the literature already establishes

- **Linear-representation methodology is mature.** Tigges 2023 (sentiment polarity), Park 2024 (language, gender), Belrose 2023 (Eliciting Latent Predictions), Zou 2023 (RepE) provide the extraction and validation recipes.
- **User-model-adjacent features exist.** Anthropic's Scaling Monosemanticity (https://transformer-circuits.pub/2024/scaling-monosemanticity/) exhibits features like "the user is upset" / "the assistant is talking to a child" — single-axis precedents for what the plan probes as a coordinated vector.
- **Theoretical backbone.** Andreas "Language Models as Agent Models" (https://arxiv.org/abs/2212.01681) argues LLMs implicitly infer a latent agent and condition on it.
- **Framing affects performance.** EmotionPrompt (https://arxiv.org/abs/2307.11760), OPRO (https://arxiv.org/abs/2309.03409), persona prompting all show accuracy deltas from framing. None isolate a probed mediator.
- **Output-token readout is feasible but noisy.** Lindsey "Emergent Introspective Awareness" (https://transformer-circuits.pub/2025/introspection/) and Binder et al. (https://arxiv.org/abs/2410.13787) show above-chance accuracy. Turpin (https://arxiv.org/abs/2305.04388) shows CoT confabulation is real. Calibration against probed ground truth is the plan's response.
- **Sycophancy exists as a competing mechanism.** Perez (https://arxiv.org/abs/2212.09251), Sharma (https://arxiv.org/abs/2310.13548). Phase 3's per-direction steering adjudicates.
- **LatentQA / activation-decoding.** Pan/Chen/Steinhardt 2024 — methodology for decoding hidden state to language; relevant to Phase 4's readout calibration.

## What is genuinely novel about this plan

- **First to probe peer-ness as a variable** in the linear-representation map (Phase 1).
- **First to probe a coordinated multi-dimensional vector** rather than a single axis (Phase 1's two-meta-axis structure with sub-dimensions).
- **First to correlate probed peer-ness with task performance** (Phase 2).
- **First to causally test the relationship via per-dimension steering** (Phase 3).
- **First production-applicable peer-ness readout for closed models** via probe-calibrated introspection (Phase 4).

Each phase contributes one. The plan is not gated on the full chain working.

## Sycophancy as a competing mechanism (not a confound to defeat up front)

Sycophancy is a *behavior of the LLM toward the user*, not a property of the user the LLM perceives. It does not belong in the IV — the IV is the LLM's perception of the user, probed in residual-stream space as the peer-ness directions of Phase 1. Sycophancy is instead a downstream behavioral channel, predicted by peer-ness: high perceived peer-ness should yield *less* sycophancy (the model trusts the user enough to push back), low peer-ness should yield more.

Mechanistically, Phase 3's causal analysis distinguishes two kinds of internal directions: user-modeling directions (Phase 1's peer-ness probes) and LLM-state-and-behavior directions (the model's own dispositions, including its propensity to flatter). Sycophancy falls in the latter category. Phase 3 includes a sycophancy probe as a control direction in the LLM-state-and-behavior class so the comparison is on the table: if steering the sycophancy direction reproduces the framing-induced accuracy delta but steering the peer-ness directions does not, the plan's mechanism story is wrong but the result is still publishable — "framing-induced quality gains are an RLHF sycophancy artifact rather than peer-ness-mediated." We do not need to defeat sycophancy as a confound up front; the experiment adjudicates.

## Infrastructure

Phases 1, 2, and 3 require the open-model + SAE tooling: an open base (Gemma-2-9B / Llama-3-8B / Gemma-2-27B), TransformerLens, NNsight, SAELens, Gemma Scope. Phase 4 also requires this infrastructure for the calibration step (probe-grounded ground truth for the verbalized readout). Closed-model API access (Claude, GPT, Gemini) is Phase 4-only.

## Two compute tiers

Each phase splits into a fast local-DGX-Spark variant the user can run in a couple of days, and a more conclusive larger-model variant requiring bigger compute. Local results gate the bigger investment.

### Tier 1 — DGX Spark, ~couple days

- **Base model**: Gemma-2-9B or Llama-3-8B, full precision; or Gemma-2-27B at 4-bit if 9B's signal is too weak.
- **Phase 1 (Tier 1)**: probe both meta-axes via fractional-factorial contrast pairs (16-cell design), ~200 conversations per cell, RepE extraction at every layer, validate held-out classification and steering on ~50 held-out conversations per sub-dimension.
- **Phase 2 (Tier 1)**: 500 examples each from MMLU subset, GSM8K subset, TruthfulQA (sycophancy control). 16-cell framing grid per benchmark. Correlate probe with accuracy per cell. End-to-end runtime budget: ~24 hours of compute.
- **Phase 3 (Tier 1)**: per-dimension steering at one layer per dimension, on the Tier 1 benchmark subset.
- **Phase 4 (Tier 1)**: introspection-vs-probe calibration on the same open model, ~100 conversations per dimension.
- **Baseline coverage at Tier 1**: include CLAUDE.md, the Karpathy CLAUDE.md (`forrestchang/andrej-karpathy-skills`), EmotionPrompt, and one system-prompt scaffold. Skip few-shot for Tier 1.

Tier 1 is "does the effect show up, at any model size, on any sub-dimension?" Negative result here means stop. Strong positive (>2x the noise floor on one sub-dimension under each meta-axis + steering reproducing >40% of the framing delta) earns Tier 2.

### Tier 2 — larger compute, more conclusive

- **Base models**: Llama-3-70B or Gemma-2-27B for the probing work. For the closed-model readout-transfer step, run Claude 4.7 / GPT-5.x / Gemini 3.1 Pro via API.
- **Phase 1 (Tier 2)**: scale contrast-pair dataset to 1000+ per cell, extract SAE-feature combinations not just single directions, multi-layer ensemble probes.
- **Phase 2 (Tier 2)**: full task suites (full MMLU, full HumanEval, full FEVER), 32-cell fractional-factorial framing grid.
- **Phase 3 (Tier 2)**: multi-layer steering, causal-mediation analysis with full statistical apparatus.
- **Phase 4 (Tier 2)**: full closed-model API protocol across the three vendors, with the calibrated introspection prompts from Tier 1.
- **Compute budget guess**: ~1-2 weeks on an 8x H100 node + API spend. Order of magnitude $5-15k. Don't commit until Tier 1 says it's worth it.

### What only Tier 2 can answer
- **Scale effects**: does peer-ness representation get clearer / more separable with model size?
- **Closed-model readout under naturalistic variance**: Tier 1 open-model calibration is necessary but not sufficient.
- **Statistical apparatus for the causal-mediation claim**: Tier 1's sample is a noise-floor probe.

### What Tier 1 alone is sufficient for
- Killing the hypothesis cheaply if no peer-ness vectors exist in 9B-class models.
- Identifying which sub-dimensions are worth chasing at scale.
- Validating the experimental harness end-to-end so Tier 2 is just rerunning at scale.

## Owner-attention items

No outstanding owner-attention items at this time. The plan is being run as a relaxed exploration — exploratory factor analysis (not a pre-registered hypothesis test), whichever closed-model versions are current at the time of each Phase 4 run (documented in the result rather than pinned in advance), and the Karpathy baseline pinned to `forrestchang/andrej-karpathy-skills` (retrieved 2026-05-14, the GitHub repo's current main branch).

## Open questions and risks

- **The mediator might not be a single direction per sub-dimension.** Peer-ness could be a distributed pattern requiring SAE feature combinations. Phase 1's SAE cross-reference catches this; if so, adapt to feature-combination probing.
- **Open-to-closed transfer might fail.** If verbalized readout doesn't agree with probed ground truth on the open model, the closed-model story collapses. Fall back to behavioral measures only.
- **The two meta-axes might collapse.** Intellectual and moral peer-ness might turn out to be one direction in the model's geometry. That's itself a result — the plan reports the geometry it finds.
- **The sycophancy direction may dominate.** Phase 3 surfaces this; see Predicted outcomes row 4.
- **Closed-model APIs may not be stable across the project.** Document the model version with every result; do not attempt to pin a single snapshot for the whole project (the plan is run as a relaxed exploration, not a confirmatory study).

## Out of scope

- New foundation model training.
- Adversarial probing for safety implications (e.g., can a user manipulate the model by playing a high-status persona?). Worth doing but a separate research thread.
- Real-time peer-ness tracking that updates as the conversation evolves. The plan's framing manipulations are static; dynamic adaptation is a follow-up.
- Direct production integration into pm's prompt generation. The earlier version of this plan had a Phase 4 "seeded conversations in pm" production track. That has been removed — the new Phase 4 is closed-model readout. Production use of peer-ness-aware prompting is a follow-up plan, conditional on Phase 2/3 success.

## References (inline citations above)

See the literature survey at `pm/docs/literature-review-user-model.md` for the full annotated bibliography. Primary anchors:

- Anthropic Scaling Monosemanticity (Templeton et al. 2024)
- Andreas "Language Models as Agent Models" (2022)
- Zou et al. "Representation Engineering" (2023)
- Tigges et al. "Linear Representations of Sentiment" (2023)
- Park et al. "Linear Representation Hypothesis" (2024)
- Lindsey "Emergent Introspective Awareness" (2025)
- Binder et al. "Looking Inward" (2024)
- Turpin et al. "Language Models Don't Always Say What They Think" (2023)
- Belrose et al. "Eliciting Latent Predictions" (2023)
- Pan/Chen/Steinhardt "LatentQA" (2024)
- Sharma et al. "Towards Understanding Sycophancy" (2023)
- Perez et al. "Discovering Language Model Behaviors with Model-Written Evaluations" (2022)
- Gemma Scope (2024)
- TransformerLens, NNsight, SAELens (tooling)

## Why this fits in pm at all

pm is well-suited to host this experiment: file-backed plans + PR-graph let us scope each phase as a sequence of PRs with explicit acceptance criteria; the watcher framework gives us automation for batch experiment runs; and pm's own anecdotal observation — that the user's preferred framing ("treat the agent as a colleague") yields better results than a bare task prompt — is the motivating intuition for the whole investigation.
