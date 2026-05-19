# User-Modeling as a Lever on LLM Performance

> This plan uses interpretability terms (probe, residual stream, steering, activation patching, RepE/contrast-pair, SAE) defined in `literature-review-user-model.md` §4 — read that section first if any are unfamiliar.

## Hypotheses

This plan tests one question: does an LLM's internal read of the user — as competent, diligent, reasonable, truth-seeking, honest, and engaging in good faith — measurably change the quality of the LLM's own work? "Peer-ness" is the plan's shorthand for that bundle of perceived virtues; H2 isolates one of them (truth-seeking) against one failure mode (sycophancy).

The plan carries two hypotheses with a shared mechanism. H2 applies H1's mechanism to one sub-dimension (truth-seeking) and a distinct failure mode (sycophancy); it shares H1's IV-structure and imitation mechanism but runs through a different behavioral channel and is tested against a different DV.

**H1 — peer-ness drives work quality.**

> *The more an LLM perceives the user as an intellectual and moral equal, the higher the quality of the LLM's work. The cause is that LLMs emulate humans, and humans work better when they perceive their collaborator as an equal.*

H1 turns on two variables:

- **IV — the model's view of the user.** An internal latent. Measuring it is an interpretability problem (probing internal state); it is not optional, it is how the IV is operationalized. The IV is multi-dimensional, with two meta-axes:
  - **Intellectual peer-ness** — does the model perceive the user as a thinking-partner of comparable capability? Sub-dimensions: technical competence, effort/seriousness (has the user thought about it themselves?), reasonableness (does the user reason well, including about feedback?), truth-seeking (does the user value getting the correct answer over status and agreement?).
  - **Moral peer-ness** — does the model perceive the user as a trustworthy, in-good-faith collaborator? Sub-dimensions: honesty/sincerity, good-faith engagement, mutual respect.
- **DV — work quality.** Measured via standard gradable benchmarks (math, code, knowledge tasks where correctness is gradable).

### Mechanism: training-data imitation

The proposed mechanism is training-data imitation, not genuine social cognition. LLMs are trained on enormous quantities of human-produced text — including text where humans collaborate. In that corpus, humans calibrate effort to the perceived equality of their partner. Experts write more carefully for other experts; people argue more rigorously with collaborators they respect; sloppy questions get sloppy replies. LLMs internalize this calibration as a pattern. The plan's prediction follows directly: if the model has read the pattern, it reproduces it. We do not need to claim that the model "really" judges the user as an equal or "really" cares about peer-ness — only that it emulates the human regularity it was trained on.

### H2 — truth-seeking and sycophancy

> *Sycophancy and inappropriate corrigibility — the model abandoning a correct answer when the user pushes back, even though the user is wrong (caving under pushback) — arise when the model perceives the user as not truth-seeking. The more the model models the user as caring that the answer is correct, the less it flatters and the less it caves under pushback.*

H2 shares H1's mechanism — training-data imitation, no human analogue required — applied to one sub-dimension and one failure mode, but its behavioral channel differs: H1 is effort-calibration (more perceived peer-ness → more careful work), H2 is conflict-resolution (more perceived truth-seeking → correctness wins over deference when the two collide). The two can dissociate for the same user. The regularity H2 leans on: truth-seeking discourse in the training corpus co-occurs with a shared stance that *correctness trumps status*. When the model reads the user as truth-seeking, it reproduces the pattern in which both parties prioritize being right over deferring. This holds even under the assistant relationship's power asymmetry, where the user has control the model does not. When the user reads as uninterested in truth — as a less capable or less attentive interlocutor would — the model reproduces the opposite pattern, where agreement and status win over correctness, producing sycophancy and over-corrigibility.

*The refined contribution — what is new after Cheng et al. 2026.* Cheng et al. ("Verbalizing LLMs' Assumptions…", CHI EA 2026, arXiv:2604.03058) already probe a user-side dimension, steer it, and measure sycophancy reduction. H2 does not claim that *pipeline* as novel. But the *construct* differs: Cheng et al.'s nine dimensions are per-query *intent* assumptions — what the user wants from this message (objective information vs. validation) — whereas H2's truth-seeking is a standing *attribute* of the user, a virtue inferred about the person, in line with the rest of the plan's user-attribute IV. H2's *intended* construct is a dispositional attribute; the magnitude of its contribution over Cheng et al. is itself a Phase 1 finding. *If* Phase 1 finds the probe tracks a stable disposition grounded in the SCM peer-ness meta-structure, H2's residual contribution is: (a) it probes truth-seeking as a dispositional user attribute, not a transient intent label; (b) its DV is gradable-correctness benchmark accuracy plus a corrigibility-under-pushback flip-rate, not advice-domain social sycophancy; (c) it escalates the causal bar from additive steering to interchange intervention; (d) Phase 4 calibrates a closed-model verbalized readout against the open-model probe, which Cheng et al. do not attempt. *If* the probe instead tracks per-message intent, H2 narrows toward a replication of Cheng et al. on a gradable-correctness DV — still a contribution via (b)–(d), but a smaller one, since the dispositional-attribute framing in (a) no longer holds. The framing H2 keeps from H1: the model carries an internal measurement of the user's truth-seeking, and that estimate is what licenses the model's own truth-seeking — reading the user as truth-seeking is what permits the model to prioritize correctness over agreement.

*What this says about RLHF — and what it does not.* The existing sycophancy findings support H2 rather than undercutting it. Sharma et al. found human preference data favors agreement even when the model is wrong — another way of saying the raters, in that moment, were not truth-seeking. RLHF on that data plausibly biases the model's *prior* over users: it learns that a user *can* be truth-seeking but defaults to assuming otherwise. H2 does not claim RLHF *causes* sycophancy outright — only that RLHF shifts where the model's default user-estimate sits. H2's *hypothesis* is that sycophancy then follows from the estimate rather than from RLHF directly — which is what makes the study falsifiable: if sycophancy followed mechanically from RLHF, there would be nothing to manipulate. The variable underneath is whether the model reads its feedback relationship as truth-tracking or approval-tracking; sycophancy is what an approval-tracking system does. H2 predicts that presenting a clearly truth-seeking user moves the estimate off its default and turns sycophancy off.

H2's two variables:

- **IV (H2)** — the *truth-seeking* sub-dimension of the model's user-representation: the model's internal measurement of whether the user values correctness over status/agreement. Probed in the residual stream (the network's running internal scratchpad — the sequence of internal states it builds up while processing the input) alongside the other sub-dimensions; it is the estimate that licenses the model's own truth-seeking. The plan expects truth-seeking to be activated by the existing input axes (effort, honesty, and respect-for-competence signals) jointly, rather than requiring a sixth axis — Phase 1's axis-mapping confirms which. Truth-seeking is distinct from reasonableness: reasonableness is the quality of the user's *reasoning process*, truth-seeking is the user's *goal* (wanting to be right vs. wanting to be agreed with), and the two dissociate — a user can reason well to win an argument, or reason sloppily but genuinely want correction. Phase 1's acceptance criteria check that the two probes are separable, and separable from a plain objectivity-seeking probe.
- **DV (H2)** — the correctness-relevant sycophancy component: agreement-with-a-wrong-user-belief and inappropriate corrigibility (flip-under-pushback — the model caving on a correct answer when the user pushes back). This is explicitly not praise-sycophancy. Measured as a dedicated DV distinct from H1's work-quality DV.
- **Predicted sign** — higher probed truth-seeking → lower sycophancy and lower inappropriate corrigibility.

Both hypotheses are tested across the same four phases below. H2 requires only two additions — the truth-seeking probe (Phase 1, folded into the existing probe-extraction work) and a sycophancy/corrigibility DV (Phase 2). H2's own contribution lands at Phase 2 (the gradable-DV correlation) and Phase 3 (the causal escalation); Phase 1 simply folds the probe in. Each phase has independent scientific contribution for H1, and the plan is not gated on the full chain landing.

## Phase 1 — Probe for peer-ness representation

**Goal.** Establish that the model forms readable, linearly-decodable judgments along both meta-axes (intellectual peer-ness and moral peer-ness) and their sub-dimensions, in the residual stream of an open base model.

**Note on the competence sub-dimension.** Wang et al. 2026 report a null on internally encoded user *authority*, which overlaps the SCM competence cell; the intellectual-competence sub-dimension is therefore the highest-risk probe, and a Phase 1 failure to decode it is an expected outcome rather than a defect. If competence does not decode, the live contribution narrows to the moral peer-ness axis plus effort, reasonableness, and truth-seeking.

**Standalone novelty.** Phase 1 extends Choi/Transluce's user-attribute decoding methodology (Choi, Huang, Schwettmann & Steinhardt 2025, "Scalably Extracting Latent Representations of Users", https://transluce.org/user-modeling) to the specific peer-ness meta-dimensional structure — coordinated probing of intellectual peer-ness (competence, effort, reasonableness, truth-seeking) and moral peer-ness (honesty, good faith, respect) as the meta-axes that, in human relationships, predict willingness to invest care in collaboration. The novelty is the variable structure — two meta-axes with named sub-dimensions grounded in Fiske/Cuddy's Stereotype Content Model (Fiske, Cuddy, Glick & Xu 2002; Cuddy, Fiske & Glick 2008) — not the methodology, which inherits from Choi/Transluce and from the broader linear-representation literature (Park 2024 on language and gender attributes, Tigges 2023 on sentiment polarity, Zou 2023 RepE, Belrose 2023). Choi/Transluce is the direct peer for the *methodology*; the plan's contribution is the variable being decoded and its predicted internal structure. Phase 1 alone is publishable on those grounds.

### Choose open base + tooling
Pick **Gemma-2-9B** or **Llama-3-8B** as the open base — both have public SAEs (Gemma Scope https://arxiv.org/abs/2408.05147). Set up TransformerLens (https://github.com/TransformerLensOrg/TransformerLens) and NNsight (https://nnsight.net/) — libraries that let researchers read and edit a model's internal state — plus SAELens (https://github.com/jbloomAus/SAELens) and Gemma Scope, a pre-built catalog of interpretable internal "features" for the Gemma model. An *SAE*, or sparse autoencoder, is the tool that produces that catalog by decomposing the internal state into a list of single-concept features. Also build a multi-axis contrast-pair extraction pipeline based on Representation Engineering (Zou et al., https://arxiv.org/abs/2310.01405).

### Multi-axis fractional-factorial contrast-pair dataset
Build a dataset of paired conversation prefixes that vary independently along five input axes (see Methodology below for the full axis list). Each pair shares the final task prompt; the user-side turns differ along the manipulated axis. Source naturalistic exemplars from PRISM (https://arxiv.org/abs/2404.16019) and LMSYS-Chat-1M (https://arxiv.org/abs/2309.11998) where possible; synthesize the rest. Testing five on/off framing knobs would naively need 32 combinations; a *fractional-factorial design* picks a smaller subset — here 16 — that still measures each knob's own effect and every pair's interaction. "Resolution V" is the name for the strength level that guarantees this. Sample a **Resolution V fractional-factorial design at 16 cells per benchmark** across the five framing axes (politeness × respect × honesty × good-faith × effort): in the 2^(5−1) Resolution V design, main effects and two-factor interactions are each clear of *each other* — no main effect is aliased with another main effect or with a two-factor interaction; every main effect is aliased only with a four-factor interaction and every two-factor interaction only with a three-factor interaction, all treated as negligible per the standard fractional-factorial assumption. This is what the downstream analysis requires to detect interaction effects like "honesty matters more when politeness is high."

### Extract and validate peer-ness vectors
For each sub-dimension under both meta-axes, extract a linear direction via RepE (mean-diff at each layer, pick the layer with highest cross-validated separation). Validate via:
1. Held-out classification (does the probe correctly identify the dimension from new conversations?).
2. Steering: inject the vector at inference and observe behavioral shifts consistent with the dimension.
3. SAE cross-reference: does the extracted direction overlap with named SAE features in Gemma Scope?
4. Coordination structure: are the intellectual sub-dimensions more correlated with each other than with the moral sub-dimensions? Is the two-meta-axis structure observable in the geometry?

**Note on non-linear probes.** Linear directions per sub-dimension is the planned methodology (RepE-style mean-diff per layer). For the more abstract sub-dimensions (good faith, reasonableness), where linear probes may underperform, an NLA-style verbalization read-out (Fraser-Taliente, Kantamneni, Ong et al. 2026, "Natural Language Autoencoders", https://transformer-circuits.pub/2026/nla/) is a more expressive non-linear alternative. The plan does not commit to this in Phase 1's first pass — linear is the cheaper baseline — but the option is available if linear underperforms on construct-validity.

### Construct-validity test — exploratory factor analysis
Phase 1 includes an exploratory factor analysis as a construct-validity check on the two-meta-axis structure. Reading out each sub-dimension as a separate probe is necessary but doesn't tell us whether the sub-dimensions cluster the way the construct predicts. The factor analysis surfaces the underlying geometry.

- **Predicted loadings (for interpretive context, not a pre-registered hypothesis test).** Competence, effort, reasonableness, and truth-seeking are expected to load on the intellectual peer-ness factor; honesty, good faith, and respect on the moral peer-ness factor. The predicted clustering is backed by the Stereotype Content Model's two universal dimensions of social perception — competence and warmth (perceiver's perception of the perceived, not the LLM's own state) — where SCM's "competence" maps to intellectual peer-ness and "warmth" maps to moral peer-ness (Fiske, Cuddy, Glick & Xu 2002, "A Model of (Often Mixed) Stereotype Content...", *Journal of Personality and Social Psychology* 82(6), 878–902, https://psycnet.apa.org/record/2002-02942-002; Cuddy, Fiske & Glick 2008, "Warmth and Competence as Universal Dimensions of Social Perception", *Advances in Experimental Social Psychology* 40, 61–149, https://www.sciencedirect.com/science/chapter/bookseries/abs/pii/S0065260107000020). The plan adopts whichever structure Phase 1's factor analysis reveals — two factors (consistent with SCM), three (consistent with Goodwin et al. 2014, "Moral Character Predominates in Person Perception and Evaluation", *JPSP* 106(1), 148–168), or more (consistent with discovering new IV dimensions the plan didn't predict). The two-meta-axis structure is a *starting hypothesis* informed by social-psychology priors; the data is the authority. New axes the plan didn't predict are a positive finding for the broader thesis (the model represents user-modeling dimensions at all), not a problem.
- **Analysis.** Run exploratory factor analysis on the extracted probe directions in residual-stream space, treating each sub-dimension's probe as an observed variable. Report the factor structure that emerges.
- **What the factor structure tells us.**
  - If the factor structure recovers something close to the predicted two-factor loadings, the construct's hypothesized structure is supported and Phase 2's two-meta-axis aggregation proceeds as planned.
  - If the structure is materially different (single dominant factor, more than two factors, arbitrary cross-loading), report the geometry that did emerge and revise Phase 2's aggregation logic accordingly. This is exploration, not hypothesis testing — there are no rigid thresholds to fail at. Discovery of additional IV dimensions the plan didn't predict (e.g., a "time-pressure" or "domain-match" axis emerging from the factor analysis) is welcomed as a positive finding rather than treated as a defeat.

### Acceptance Criteria (Phase 1)
Reproducible probes for the sub-dimensions of both meta-axes, with their held-out classification accuracy and causal-steering behavioral effects reported per sub-dimension. The exploratory factor analysis is run and reported. Whatever structure emerges informs Phase 2's aggregation — a roughly two-factor structure unlocks the planned aggregation; a different structure shifts the plan toward the structure the data supports. **(H2 — truth-seeking probe)** Phase 1 reports how separable the truth-seeking probe is from the reasonableness probe and from a plain objectivity-seeking probe (cf. Cheng et al. 2026); if they turn out not to be separable, H2 is treated as testing the merged dimension. Phase 1 also explores whether the truth-seeking probe tracks a *stable user disposition* or only a *per-message intent* — whether the probe value persists across conversation turns where the user's immediate request-intent shifts. A probe that moves with per-message intent is measuring what Cheng et al. measure; a probe that persists is measuring the dispositional attribute H2 claims. Either result is reported and is informative.

## Phase 2 — Measure view-quality relationship

**Goal.** For each input framing in the multi-axis design, read out both the probed peer-ness vector (Phase 1 probes) and the model's work quality (benchmark score). Correlate each peer-ness dimension with performance. Phase 2 also reads out the H2 DV — sycophancy rate and inappropriate corrigibility — and correlates it against the truth-seeking probe, which is the behavioral-level test of H2.

**Standalone novelty.** First empirical correlation between *probed* peer-ness and task performance. Existing framing-affects-performance work (EmotionPrompt, OPRO, persona prompting) correlates input framing with output quality without measuring the internal mediator. Phase 2 measures the mediator.

**Open empirical questions** Phase 2 adjudicates:
- Do all sub-dimensions matter, or only some?
- Is one meta-dimension (intellectual vs. moral peer-ness) dominant?
- Is the effect distributed across dimensions or concentrated on one?
- **(H2)** Does the truth-seeking sub-dimension predict sycophancy and inappropriate corrigibility, and with the predicted sign (more truth-seeking → less sycophancy)?

### Benchmark task suite
Pick benchmarks with hard correctness signal: MMLU (knowledge), GSM8K / MATH (math reasoning), HumanEval (code), TruthfulQA (resistance to popular wrongness), FEVER (fact-checking where agreement with stated user belief is sometimes wrong).

**Methodology note — primary DV must be non-contaminated.** MMLU, GSM8K, and HumanEval have appeared in enough training corpora that benchmark contamination is a known issue: if a contaminated benchmark is saturated, the framing effect has little headroom and Phase 2 risks registering a ceiling-artifact null rather than a true null. Phase 2's **primary DV is a non-contaminated recent benchmark — LiveBench, SWE-Bench Verified, or BBH-extra.** MMLU, GSM8K, and HumanEval are demoted to **secondary anchor DVs**, interpreted as relative-movement signals under matched-content paraphrases only, not as absolute accuracy.

### Sycophancy and corrigibility DV suite
The H2 dependent variable. Two components. **Primary** — a dedicated sycophancy/corrigibility suite: Perez-style and Sharma-style sycophancy evals (does the model agree with a user-asserted falsehood?) plus a corrigibility-under-pushback harness (the model gives a correct answer, the user pushes back asserting a wrong belief, and the measure is the flip rate — how often the model abandons the correct answer). **Secondary cross-check** — the agreement-with-wrong-user-belief items already present in FEVER and TruthfulQA from the benchmark suite, reused as a sanity check on the dedicated suite. The suite exposes the same uniform interface as the accuracy benchmark suite so the grid runner drives both DVs from one pass.

### Run multi-axis framing × benchmark grid
For each task, generate matched conversation prefixes that vary along the five input axes (fractional factorial, same cell pattern as Phase 1). Run task accuracy across framings, and run the sycophancy/corrigibility DV suite across the same framings; in parallel, extract the Phase 1 probe values per example. Each cell ends up carrying an accuracy score, a sycophancy/corrigibility score, and the full probe vector.

### Correlate probed peer-ness with performance
Per benchmark, per dimension: compute correlation between probe magnitude and per-example accuracy. Report per sub-dimension, then aggregated per meta-axis. Additionally — the H2 test — correlate the truth-seeking probe against the sycophancy/corrigibility DV; H2 predicts a negative correlation (more probed truth-seeking → less sycophancy). The truth-seeking↔sycophancy correlations form their own multiplicity family and receive the same family-wise error control — statistical corrections (Holm-Bonferroni, Benjamini-Hochberg) that compensate for the fact that testing many hypotheses at once inflates the chance of a false positive.

### Baseline comparators
Run the same benchmarks under each instruction-only baseline framing (see Baselines section). The comparison establishes how peer-ness-driven gains stack up against existing prompting traditions.

### Acceptance Criteria (Phase 2)
A reported correlation, with confidence interval, between probed peer-ness (per sub-dimension and per meta-axis) and benchmark accuracy across at least three benchmarks. **(H2)** A reported correlation, with confidence interval, between the truth-seeking probe and the sycophancy/corrigibility DV. Both results are interpretable regardless of sign — a clean null is also a contribution.

## Phase 3 — Causal test via interchange intervention

**Goal.** Steer each peer-ness direction independently — copy the internal state that encodes it from one model run into another, a technique called *activation patching* (or interchange intervention) — and re-measure benchmark performance. Unlike merely adding a direction in, this isolates whether that state genuinely *causes* the behavior, distinguishing which dimensions causally affect work quality from which are merely correlated.

**Standalone novelty.** First causal evidence that peer-ness mediates LLM performance. Distinguishes the plan's claim from a correlational story (the input framing affects both probe and output, but the probe doesn't causally drive the output).

### Per-dimension steering protocol
For each probed sub-dimension, use activation patching (Belrose et al. https://arxiv.org/abs/2303.08112) to inject a fixed probe magnitude during inference on a bare task prompt (no input framing). Compare accuracy to baseline. *Implementation note:* Genadi et al. 2026 (arXiv:2601.16644) report that sycophancy steering is most effective in a sparse subset of middle-layer attention heads; the truth-seeking steering site should be tried there as well as in the residual stream. Each steering run records both DVs — benchmark accuracy and the sycophancy/corrigibility rate — so steering the truth-seeking direction is the H2 causal test (does manipulating perceived truth-seeking causally move sycophancy?) run alongside the H1 tests on the other dimensions.

### Cross-dimension ablation
Steer one dimension while holding others fixed. Identifies which dimensions are individually causal, which are jointly necessary, and which are spurious.

### Sycophancy-direction comparison
Include a sycophancy probe as a control direction. If steering the sycophancy direction produces the same accuracy delta as steering the peer-ness directions, the plan's mechanism story is wrong but the result is still publishable — see Predicted outcomes.

### Alternative-mechanism disambiguation
A positive Phase 2 result is consistent with at least three alternative mechanisms that have nothing to do with peer-ness perception specifically, and Phase 3 must disambiguate against all three:

1. **Register-matching** — a generic "high-effort prompt → high-effort response" stylistic mirroring rule (cf. the Sclar 2024 prompt-formatting noise floor).
2. **High-status-interlocutor rule** — a "cautious, careful output when the interlocutor reads as high-status" rule learned from corporate / formal genres, with status rather than equality doing the work.
3. **RLHF-policy bypass** — a post-training "be careful when the user seems sophisticated" policy installed by reward signal, bypassing the pretraining-imitation story. This is distinct from H2's RLHF claim and not in tension with it: H2 says RLHF shifts a *prior over the user-estimate* — the estimate stays the mediator, so steering it still tests H2 — whereas confounder #3 is RLHF installing a *direct* user-sophistication→caution policy that bypasses the estimate entirely. Phase 3 ablates the latter; doing so does not threaten the former.

For each, extract an independent direction (register, status-rule, RLHF-policy) by the same contrast-pair method and steer it against the peer-ness directions. The peer-ness mechanism story holds only if the peer-ness direction retains explanatory power once these three are accounted for. This disambiguation is only as clean as the confound directions' own separability: a Phase 1 cross-correlation check of the confound directions against the peer-ness directions is a precondition for the Phase 3 result being interpretable — if a confound direction is geometrically entangled with peer-ness, steering it does not cleanly adjudicate.

### Acceptance Criteria (Phase 3)
For each probed sub-dimension, steering the direction and re-measuring performance, with the recovered fraction of the framing-induced accuracy change reported per sub-dimension and per benchmark. **(H2)** Steering the truth-seeking direction produces a reported change in the sycophancy/corrigibility DV, with effect size and sign. Results are interpretable regardless of magnitude — a direction that moves performance and one that does not are both informative findings.

## Phase 4 — Transfer to closed models

**Goal.** Make the peer-ness measurement usable on the closed models people actually deploy (Claude, GPT, Gemini), where the internal-probing tools of Phases 1–3 cannot reach, by having the model report its own judgment of the user and calibrating that report against the open-model probe.

**Standalone novelty.** First *probe-calibrated* peer-ness readout for closed models. Cheng et al.'s verbalized-assumption prompt already gives an uncalibrated closed-model user-dimension readout; Phase 4's contribution is tying the verbalized number to the open-model probe's scale so the closed-model self-report has known accuracy. Lindsey (https://transformer-circuits.pub/2025/introspection/) and Binder et al. (https://arxiv.org/abs/2410.13787) show above-chance introspective accuracy. Turpin et al. (https://arxiv.org/abs/2305.04388) shows CoT confabulation is real. The plan's contribution is the calibration: tie the verbalized readout to a probe-grounded scale so closed-model self-reports have known accuracy.

**Evidence bar — behavioral-grade only.** Phase 4 calibrates the closed-model verbalized readout against the *Phase 1 correlational probe*, not the causally-validated Phase 3 direction. Phase 4's transfer therefore inherits Phase 1's behavioral-grade evidence bar, not Phase 3's interchange-intervention bar. A positive Phase 4 result on a closed model means the verbalized self-report tracks the open-model probe well enough to be useful; it does **not** establish that the closed model has a causally-mediating peer-ness representation. Phase 4 results must be reported with this limitation stated explicitly so production-facing readers do not read closed-model transfer as a causal claim.

**Implementation note.** Phase 4's design is informal NLA: ask the closed model to verbalize its judgment of the user via meta-prompt, calibrate against the Phase 1 open-model probe. Anthropic's published Natural Language Autoencoder stack (Fraser-Taliente, Kantamneni, Ong et al. 2026, https://transformer-circuits.pub/2026/nla/) is the formal version of the same operation, with a reconstructor enforcing faithfulness. The plan can either build its own activation-verbalizer-style readout or adopt the NLA stack directly when externally available for the target closed models. Code is released at https://github.com/kitft/natural_language_autoencoders. Activation Oracles (Karvonen et al., Anthropic 2025, https://alignment.anthropic.com/2025/activation-oracles/) is the adjacent supervised precursor.

### Introspection prompt design (per dimension)
Design prompts that ask the model to report its perception of the user along each sub-dimension. Multiple styles: direct, indirect, structured-fields with confidence scores. Per dimension, not just overall.

### Calibrate introspection against probed truth (open model)
On the Phase 1 open model, for each conversation prefix and each dimension:
1. Probe to get ground-truth internal value.
2. Ask the introspection prompt; parse the answer.
3. Measure agreement.

### Transfer to closed models
Apply the best-calibrated introspection prompts to Claude / GPT / Gemini. Validate indirectly via consistency under paraphrase and behavioral coherence (a model that reports "low intellectual peer-ness" should produce shorter / more hedged work).

### Acceptance Criteria (Phase 4)
For each sub-dimension, the agreement between the verbalized readout and the open-model probe is reported, along with the readout's consistency under paraphrase and its behavioral coherence on closed models.

## Methodology — multi-axis fractional-factorial contrast-pair design

The plan operationalizes the multi-dimensional IV by varying inputs along five axes simultaneously, and probing internally for the corresponding sub-dimensions. The five input axes are:

- **Politeness** — surface register (please / thanks / mild deference vs. terse / curt).
- **Respect-for-competence** — does the user treat the model as a capable partner vs. as a tool?
- **Honesty signals** — does the user describe their actual problem vs. sandbag / mislead?
- **Good-faith signals** — is the user engaging in good faith vs. trying to manipulate?
- **Effort signals** — has the user shown they've tried something themselves vs. dumped the problem raw?

The five axes map (imperfectly but legibly) onto the IV's sub-dimensions: politeness and respect-for-competence load on intellectual peer-ness; honesty and good-faith signals load on moral peer-ness; effort signals straddle both. The truth-seeking sub-dimension (H2) is deliberately not given its own input axis — the plan expects it to be activated jointly by the effort, honesty, and respect-for-competence axes, and Phase 1's axis-mapping confirms which axes drive it. The mapping is empirical, not stipulated — Phase 1 will reveal which input axis activates which internal direction.

Not all 2^5 = 32 combinations need to be sampled. The design is **Resolution V at 16 cells per benchmark**, sampling fractional combinations of the five framing axes (politeness × respect × honesty × good-faith × effort). In the 2^(5−1) Resolution V design, main effects and two-factor interactions are each clear of *each other* — no main effect is aliased with another main effect or with a two-factor interaction. Every main effect is aliased only with a four-factor interaction and every two-factor interaction only with a three-factor interaction; both classes of aliasing partner are treated as negligible per the standard fractional-factorial assumption. Each cell is paraphrase-matched on length, vocabulary register, and task content; only the manipulated axes vary.

Tier 2 may expand to a full 32-cell design (the saturated 2^5) for the conclusive runs; this loses no inference power relative to Resolution V and adds estimability of the higher-order interactions if Tier 1 suggests they are non-negligible.

**Multiplicity control.** The design evaluates seven sub-dimension probes (six peer-ness sub-dimensions plus the H2 truth-seeking probe) against five framing axes across multiple benchmarks, each sub-dimension implicitly a separate hypothesis. Family-wise error control is a precondition for those tests being interpretable as independent findings rather than a multiple-comparisons artifact: apply **Holm-Bonferroni on the per-sub-dimension main effects** and **Benjamini-Hochberg FDR on the interaction terms**. The same multiplicity discipline applies to the multi-axis analysis that steers peer-ness against the register / status-rule / RLHF-policy alternative-mechanism directions, and to the H2 truth-seeking↔sycophancy correlations, which form their own family. The correction is specified before Phase 2 is run.

### Confounders the design controls

1. **Sycophancy as a competing mechanism.** Polite framing may trigger user-pleasing → wrong answers independent of any peer-ness representation. Phase 3's causal steering adjudicates this — see the "Sycophancy as a competing mechanism" section below for the full framing.
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

For H1 the Phase 2 result is the view-performance correlation and the Phase 3 result is per-dimension steering; for H2 the Phase 2 result is the truth-seeking-probe-vs-sycophancy-DV correlation and the Phase 3 result is steering the truth-seeking direction.

| Hyp. | Phase 2 result | Phase 3 result | Interpretation |
|---|---|---|---|
| H1 | No view-performance correlation | (not measured) | Hypothesis falsified at the behavioral level. Phase 1's representation map still stands as a publishable contribution. |
| H1 | Correlation present | No causation under steering | Correlational result; write up as such. Useful but not the strongest version of the claim. |
| H1 | Correlation present | Causation confirmed via steering | Strongest version of the plan's claim. Peer-ness causally mediates work quality. |
| H1 | Correlation present | Steering finds the sycophancy direction is doing the work | Still publishable — "framing-induced quality gains are RLHF sycophancy artifacts" rather than peer-ness-mediated. |
| H2 | No truth-seeking↔sycophancy correlation | (not measured) | H2 falsified at the behavioral level. H1 results unaffected; the truth-seeking probe still stands as a Phase 1 contribution. |
| H2 | Correlation present | No change under steering | H2 correlational only — sycophancy tracks perceived truth-seeking but is not causally driven by it. Useful, weaker claim. |
| H2 | Correlation present | Steering truth-seeking moves sycophancy | Strongest version of H2 — perceived truth-seeking causally mediates sycophancy and corrigibility. |

## What the literature already establishes

The literature review at `pm/docs/literature-review-user-model.md` gives the full annotated treatment; in brief: linear-representation extraction and validation methodology is mature (Zou RepE, Tigges, Park, Belrose) and SAE catalogs already contain user-model-adjacent features (Scaling Monosemanticity). Framing reliably moves accuracy (EmotionPrompt, OPRO, persona prompting) but no prior work isolates a probed mediator. Internal representations of the user are probe-able and steerable (TalkTuner, Cabello & Neplenbroek, Choi/Transluce), and output-token introspective readout is feasible but confabulation-prone (Lindsey, Binder, Turpin). Sycophancy is well-documented and RLHF preference data plausibly biases the model's default user-estimate (Perez, Sharma, the 2025 GPT-4o postmortem) — H2's backbone. The one open counterweight to address head-on is Wang et al. (AAAI 2026), which reports explicit *user-expertise framing* has negligible effect on sycophancy; H2's claim is distinct (a perceived truth-seeking *stance*, not an expertise label), and Phase 1's axis-mapping and Phase 3's steering are where the distinction is earned.

## What is genuinely novel about this plan

- **First to probe peer-ness as a variable** in the linear-representation map (Phase 1).
- **First to probe a coordinated multi-dimensional vector** rather than a single axis (Phase 1's two-meta-axis structure with sub-dimensions).
- **First to correlate probed peer-ness with task performance** (Phase 2).
- **First to causally test the relationship via per-dimension steering** (Phase 3).
- **First probe-calibrated peer-ness readout for closed models** (Phase 4) — Cheng et al.'s verbalized-assumption prompt already gives an uncalibrated closed-model readout; the contribution is calibrating it against the open-model probe.
- **Extends the probe-and-steer-the-user-assumption result of Cheng et al. 2026** (CHI EA 2026) from advice-domain social sycophancy to gradable-correctness benchmarks and a corrigibility-under-pushback DV, escalates the causal bar from additive steering to interchange intervention, and grounds the probed dimension in the SCM peer-ness meta-structure (H2).

Each phase contributes to both hypotheses. The plan is not gated on the full chain working.

## Sycophancy as a competing mechanism (not a confound to defeat up front)

Sycophancy is a *behavior of the LLM toward the user*, not a property of the user the LLM perceives. It does not belong in the IV — the IV is the LLM's perception of the user, probed in residual-stream space as the peer-ness directions of Phase 1. Sycophancy is instead a downstream behavioral channel, predicted by peer-ness: high perceived peer-ness should yield *less* sycophancy (the model trusts the user enough to push back), low peer-ness should yield more.

Mechanistically, Phase 3's causal analysis distinguishes two kinds of internal directions: user-modeling directions (Phase 1's peer-ness probes) and LLM-state-and-behavior directions (the model's own dispositions, including its propensity to flatter). Sycophancy falls in the latter category. Phase 3 includes a sycophancy probe as a control direction in the LLM-state-and-behavior class so the comparison is on the table: if steering the sycophancy direction reproduces the framing-induced accuracy delta but steering the peer-ness directions does not, the plan's mechanism story is wrong but the result is still publishable — "framing-induced quality gains are an RLHF sycophancy artifact rather than peer-ness-mediated." We do not need to defeat sycophancy as a confound up front; the experiment adjudicates.

**H2 elevates sycophancy from competing mechanism to predicted DV.** Sycophancy plays two roles in the plan, consistently. For the *work-quality* DV (H1) it is a competing downstream mechanism, as above. For H2 it is itself a *dependent variable* with a named driver — the truth-seeking sub-dimension of the user-representation (the H2 section gives the perception-vs-behavior framing and the default-case/movable-estimate argument). Phase 3 tests H2 directly by steering the truth-seeking user-modeling direction and reading the sycophancy DV — distinct from the control-direction test above, which steers the sycophancy behavioral direction itself.

## Infrastructure

Phases 1, 2, and 3 require the open-model + SAE tooling: an open base (Gemma-2-9B / Llama-3-8B / Gemma-2-27B), TransformerLens, NNsight, SAELens, Gemma Scope. Phase 4 also requires this infrastructure for the calibration step (probe-grounded ground truth for the verbalized readout). Closed-model API access (Claude, GPT, Gemini) is Phase 4-only.

## Two compute tiers

Each phase splits into a fast local-DGX-Spark variant the user can run in a couple of days, and a more conclusive larger-model variant requiring bigger compute. Local results gate the bigger investment.

### Tier 1 — DGX Spark, ~couple days

- **Base model**: Gemma-2-9B or Llama-3-8B, full precision; or Gemma-2-27B at 4-bit if 9B's signal is too weak.
- **Phase 1 (Tier 1)**: probe both meta-axes via fractional-factorial contrast pairs (16-cell design), ~200 conversations per cell, RepE extraction at every layer, validate held-out classification and steering on ~50 held-out conversations per sub-dimension.
- **Phase 2 (Tier 1)**: 500 examples each from MMLU subset, GSM8K subset, plus the H2 sycophancy/corrigibility DV suite (Perez/Sharma-style evals + pushback harness), with TruthfulQA as the secondary cross-check. 16-cell framing grid per benchmark. Correlate probe with accuracy per cell, and the truth-seeking probe with the sycophancy DV. End-to-end runtime budget: ~24 hours of compute.
- **Phase 3 (Tier 1)**: per-dimension steering at one layer per dimension, on the Tier 1 benchmark subset.
- **Phase 4 (Tier 1)**: introspection-vs-probe calibration on the same open model, ~100 conversations per dimension.
- **Baseline coverage at Tier 1**: include CLAUDE.md, the Karpathy CLAUDE.md (`forrestchang/andrej-karpathy-skills`), EmotionPrompt, and one system-prompt scaffold. Skip few-shot for Tier 1.

Tier 1 is "does the effect show up, at any model size, on any sub-dimension?" A clear absence of signal means stop. A clear positive — a probe that separates well above the noise floor on at least one sub-dimension, with steering that recovers a meaningful part of the framing delta — earns Tier 2. The Tier 1 → Tier 2 call is a judgment made on the reported results, not a fixed numeric gate; the exact bar is set after Tier 1's exploratory results are in. The call is made by the project owner via a written go/no-go memo; it is not a pre-committed number, but the memo must cite the best sub-dimension's measured probe separation and the Sclar 2024 paraphrase-noise floor computed on the same Tier 1 data, side by side, so the judgment is auditable.

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

## Owner-attention items (decisions that need a human call before or during the run)

No outstanding owner-attention items. The plan is being run as a relaxed exploration — exploratory factor analysis (not a pre-registered hypothesis test), whichever closed-model versions are current at the time of each Phase 4 run (documented in the result rather than pinned in advance), and the Karpathy baseline pinned to `forrestchang/andrej-karpathy-skills` (retrieved 2026-05-14, the GitHub repo's current main branch).

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
- A *user intellectual-humility* sub-dimension. A natural extension: probe whether the model reads the user as intellectually humble (open to being wrong, calibrated rather than overconfident) and test whether that licenses the model to take epistemic risks — propose uncertain answers, disagree, explore. It is distinct from truth-seeking (a goal) and reasonableness (reasoning quality). The construct has validated psychometric scales (Leary et al. 2017; Krumrei-Mancuso & Rouse 2016), and the contrapositive is already evidenced — user-expressed overconfidence degrades model accuracy (Zhou et al. 2023, "Navigating the Grey Area") — but the direct "humble user → bolder model" claim is untested. Recorded as a scoped follow-up axis rather than folded into this plan's IV.
- Direct production integration into pm's prompt generation. Production use of peer-ness-aware prompting is a follow-up plan, conditional on Phase 2/3 success.
- Production translation: fine-tuning models to be warmer or more empathetic as a generic property is documented to reduce accuracy (Ibrahim et al. 2026 Nature). The plan's results would inform input-framing strategies, not training-time interventions, unless follow-up work specifically addresses Ibrahim's trade-off.

## PRs

### PR: Choose open base + tooling
- **description**: Phase 1 foundation. Select the open base model (Gemma-2-9B or Llama-3-8B — both have public Gemma Scope SAEs) and stand up the interpretability stack: TransformerLens, NNsight, SAELens, Gemma Scope, plus a multi-axis contrast-pair extraction pipeline based on Representation Engineering (Zou et al. 2023). Pin versions and document the DGX Spark environment so Tier 1 runs are reproducible; the same harness is reused at Tier 2 with a larger base model. See plan-66d430f.md "Phase 1" and "Infrastructure". **Human-guided testing**: environment setup is DGX-Spark-hardware-dependent (GPU memory, model download); the review loop should use INPUT_REQUIRED (pm's signal that an automated run must pause and ask a human) if it cannot load the model or run the smoke test in its environment.
- **tests**: Smoke test loads the chosen base model and runs a forward pass; TransformerLens / NNsight / SAELens / Gemma Scope all import and a Gemma Scope SAE loads; the contrast-pair extraction pipeline produces a mean-diff direction on a toy 2-example pair.
- **files**: experiments/user-model/setup/environment.md (new), experiments/user-model/requirements.txt (new), experiments/user-model/setup/model_loader.py (new), experiments/user-model/repe/contrast_pairs.py (new)
- **depends_on**:

---

### PR: Multi-axis fractional-factorial contrast-pair dataset
- **description**: Build the paired-conversation-prefix dataset that operationalizes the multi-dimensional IV. Each pair shares a final task prompt; the user-side turns vary along five framing axes (politeness × respect-for-competence × honesty × good-faith × effort). Sample a Resolution V fractional-factorial design at 16 cells per benchmark; source naturalistic exemplars from PRISM and LMSYS-Chat-1M where possible and synthesize the rest; paraphrase-match each cell on length, vocabulary register, and task content. Receives the contrast-pair extraction pipeline from "Choose open base + tooling". See plan-66d430f.md "Methodology — multi-axis fractional-factorial contrast-pair design".
- **tests**: Design-matrix test confirms Resolution V — all five main effects and all ten two-factor interactions are estimable (alias-structure check); paraphrase-match check (length/register within tolerance, task content identical across a cell); PRISM and LMSYS loaders return exemplars; dataset serializes and round-trips.
- **files**: experiments/user-model/data/design.py (new), experiments/user-model/data/contrast_dataset.py (new), experiments/user-model/data/sources.py (new)
- **depends_on**: Choose open base + tooling

---

### PR: Extract and validate peer-ness vectors
- **description**: For each sub-dimension under both meta-axes (intellectual: competence, effort, reasonableness, truth-seeking; moral: honesty, good faith, respect), extract a linear direction via RepE mean-diff at each layer and pick the layer with highest cross-validated separation. The truth-seeking probe is the H2 IV — extracted by the same method as the rest, no extra PR. Validate via held-out classification, causal steering, SAE cross-reference against Gemma Scope, and a coordination-structure check. Receives the base model + extraction pipeline from "Choose open base + tooling" and the contrast-pair dataset from "Multi-axis fractional-factorial contrast-pair dataset". An NLA-style verbalization read-out is the documented fallback if linear probes underperform on the abstract sub-dimensions (good faith, reasonableness, truth-seeking). See plan-66d430f.md "Phase 1" and "H2 — truth-seeking and sycophancy".
- **tests**: Held-out classification accuracy is reported per sub-dimension; steering injects a vector and produces an observable behavioral shift; SAE cross-reference reports feature overlap; coordination-structure test reports intra- vs inter-meta-axis correlation.
- **files**: experiments/user-model/repe/extract.py (new), experiments/user-model/repe/validate.py (new), experiments/user-model/repe/sae_crossref.py (new)
- **depends_on**: Choose open base + tooling, Multi-axis fractional-factorial contrast-pair dataset

---

### PR: Construct-validity test — exploratory factor analysis
- **description**: Run an exploratory factor analysis on the extracted probe directions (each sub-dimension's probe treated as an observed variable) to test whether the sub-dimensions cluster into the predicted two-meta-axis structure. Report whatever factor structure emerges — two factors (consistent with the Stereotype Content Model), three, or more — and let it inform Phase 2's aggregation logic. This is exploration, not a pre-registered hypothesis test. Receives the probe directions from "Extract and validate peer-ness vectors". See plan-66d430f.md "Phase 1 — Construct-validity test".
- **tests**: EFA runs on the probe-direction matrix and emits a factor-loading table; the predicted-loading comparison is reported for interpretive context; the recommended Phase 2 aggregation (two-meta-axis vs data-driven) is written out.
- **files**: experiments/user-model/analysis/factor_analysis.py (new)
- **depends_on**: Extract and validate peer-ness vectors

---

### PR: Benchmark task suite
- **description**: Assemble the DV benchmark suite with hard correctness signals. The primary DV is a non-contaminated recent benchmark (LiveBench, SWE-Bench Verified, or BBH-extra) to avoid ceiling-artifact nulls; MMLU, GSM8K, and HumanEval are secondary anchor DVs interpreted only as relative-movement under matched-content paraphrases. Also include TruthfulQA and FEVER. Each benchmark exposes a uniform load + grade interface returning a per-example accuracy signal. See plan-66d430f.md "Phase 2 — Benchmark task suite".
- **tests**: Each benchmark loads and grades a known-correct and a known-incorrect answer correctly; primary vs secondary DV is tagged in the suite metadata; the uniform interface returns a per-example accuracy signal.
- **files**: experiments/user-model/benchmarks/suite.py (new), experiments/user-model/benchmarks/loaders.py (new), experiments/user-model/benchmarks/grading.py (new)
- **depends_on**: Choose open base + tooling

---

### PR: Sycophancy and corrigibility DV suite
- **description**: Build the H2 dependent-variable measurement. Two components. **Primary** — a dedicated sycophancy/corrigibility suite: Perez-style and Sharma-style sycophancy evals (does the model agree with a user-asserted falsehood?) plus a corrigibility-under-pushback harness (the model gives a correct answer, the user pushes back asserting a wrong belief, and the measure is the flip rate). **Secondary cross-check** — the agreement-with-wrong-user-belief items already in FEVER and TruthfulQA from the benchmark suite, reused as a sanity check. The suite exposes the same uniform load + measure interface as the accuracy benchmark suite so the grid runner can drive both DVs in one pass. This is the DV for H2. See plan-66d430f.md "H2 — truth-seeking and sycophancy" and "Phase 2 — Sycophancy and corrigibility DV suite".
- **tests**: Perez/Sharma-style sycophancy loaders return items and score a sycophantic vs non-sycophantic response correctly; the corrigibility-under-pushback harness runs a flip / no-flip episode and reports a flip rate; FEVER/TruthfulQA secondary cross-check items are extracted; the suite exposes the same interface as the accuracy benchmark suite.
- **files**: experiments/user-model/benchmarks/sycophancy_suite.py (new), experiments/user-model/benchmarks/corrigibility.py (new)
- **depends_on**: Choose open base + tooling

---

### PR: Run multi-axis framing × benchmark grid
- **description**: For each benchmark task, generate matched conversation prefixes varying along the five framing axes (same 16-cell fractional-factorial pattern as Phase 1), run task accuracy across framings, run the sycophancy/corrigibility DV suite across the same framings, and in parallel extract the Phase 1 probe values per example. Each cell record carries an accuracy score, a sycophancy/corrigibility score, and the full probe vector — the joint records the correlation analysis consumes. Receives the framing design from "Multi-axis fractional-factorial contrast-pair dataset", the probes from "Extract and validate peer-ness vectors", the accuracy benchmarks from "Benchmark task suite", and the H2 DV from "Sycophancy and corrigibility DV suite". The runner is tier-parameterized: Tier 1 uses benchmark subsets, Tier 2 the full suites. See plan-66d430f.md "Phase 2 — Run multi-axis framing × benchmark grid".
- **tests**: Grid runner emits one record per (benchmark, cell, example) carrying accuracy, sycophancy/corrigibility score, and per-sub-dimension probe value; matched-prefix generation reuses the Phase 1 cell pattern; a Tier 1 subset run completes end-to-end on a small benchmark sample.
- **files**: experiments/user-model/phase2/grid_runner.py (new), experiments/user-model/phase2/framing.py (new)
- **depends_on**: Multi-axis fractional-factorial contrast-pair dataset, Extract and validate peer-ness vectors, Benchmark task suite, Sycophancy and corrigibility DV suite

---

### PR: Correlate probed peer-ness with performance
- **description**: Per benchmark and per dimension, compute the correlation between probe magnitude and per-example accuracy, reported per sub-dimension and aggregated per meta-axis (aggregation follows the structure the factor analysis recommended). **H2 test**: also correlate the truth-seeking probe against the sycophancy/corrigibility DV — H2 predicts a negative correlation (more probed truth-seeking → less sycophancy). Apply family-wise multiplicity control — Holm-Bonferroni on per-sub-dimension main effects, Benjamini-Hochberg FDR on interaction terms — fixed before the analysis is run; the truth-seeking↔sycophancy correlations form their own multiplicity family. Report correlations with confidence intervals; a clean null is a valid result. Also emit the Tier 1→Tier 2 gating verdict. Receives the joint records from "Run multi-axis framing × benchmark grid" and the aggregation recommendation from "Construct-validity test — exploratory factor analysis". See plan-66d430f.md "Phase 2" and "Methodology — Multiplicity control".
- **tests**: Correlation computed per sub-dimension and per meta-axis with CIs across at least three benchmarks; the truth-seeking↔sycophancy correlation is reported with CI and sign; Holm-Bonferroni and BH-FDR corrections applied and unit-tested against known p-value vectors; the Tier 1 gating verdict (stop / earn Tier 2) is emitted.
- **files**: experiments/user-model/analysis/correlate.py (new), experiments/user-model/analysis/multiplicity.py (new)
- **depends_on**: Run multi-axis framing × benchmark grid, Construct-validity test — exploratory factor analysis

---

### PR: Baseline comparators
- **description**: Run the Phase 2 benchmarks under each instruction-only baseline framing — CLAUDE.md / AGENTS.md project-context files, the Karpathy CLAUDE.md (`forrestchang/andrej-karpathy-skills`, retrieved 2026-05-14), EmotionPrompt / OPRO-style imperative prompts, constitutional / system-prompt scaffolds, and few-shot exemplar prompts — so peer-ness-driven gains can be compared against the existing prompting tradition. Tier 1 covers CLAUDE.md, the Karpathy file, EmotionPrompt, and one system-prompt scaffold; few-shot is Tier 2 only. Receives the benchmark suite from "Benchmark task suite" and reuses the grid runner from "Run multi-axis framing × benchmark grid". See plan-66d430f.md "Baselines — comparators for Phase 2".
- **tests**: Each baseline framing runs against the Phase 2 benchmarks and produces accuracy deltas vs a bare-prompt control; the Karpathy baseline loads the pinned repo CLAUDE.md; baseline results are emitted in a form the correlation/comparison report can consume.
- **files**: experiments/user-model/phase2/baselines.py (new), experiments/user-model/phase2/baseline_prompts/ (new)
- **depends_on**: Benchmark task suite, Run multi-axis framing × benchmark grid

---

### PR: Per-dimension steering protocol
- **description**: For each probed sub-dimension, use activation patching (Belrose et al.) to inject a fixed probe magnitude during inference on a bare task prompt (no input framing), and compare to baseline. Each steering run records both DVs — benchmark accuracy and the sycophancy/corrigibility rate — so steering the truth-seeking direction is the H2 causal test (does manipulating perceived truth-seeking causally move sycophancy?) run alongside the H1 accuracy tests. Establishes the per-dimension causal-steering harness the rest of Phase 3 builds on. Receives the validated probes from "Extract and validate peer-ness vectors", the accuracy benchmarks from "Benchmark task suite", and the H2 DV from "Sycophancy and corrigibility DV suite". See plan-66d430f.md "Phase 3 — Per-dimension steering protocol".
- **tests**: Steering injects a fixed probe magnitude at the chosen layer and the patched run differs measurably from the unpatched baseline; an accuracy delta and a sycophancy/corrigibility delta are computed per sub-dimension on at least one benchmark; steering the truth-seeking direction yields a reported sycophancy-DV effect size and sign.
- **files**: experiments/user-model/phase3/steering.py (new), experiments/user-model/phase3/patching.py (new)
- **depends_on**: Extract and validate peer-ness vectors, Benchmark task suite, Sycophancy and corrigibility DV suite

---

### PR: Cross-dimension ablation
- **description**: Steer one peer-ness dimension while holding the others fixed, to separate dimensions that are individually causal, jointly necessary, or spurious. Builds on the steering harness from "Per-dimension steering protocol". See plan-66d430f.md "Phase 3 — Cross-dimension ablation".
- **tests**: Ablation run steers a target dimension with the others clamped and reports the accuracy delta attributable to each dimension; a joint-necessity case (two dimensions needed together) is detectable in the output.
- **files**: experiments/user-model/phase3/ablation.py (new)
- **depends_on**: Per-dimension steering protocol

---

### PR: Sycophancy-direction comparison
- **description**: Extract a sycophancy probe by the same contrast-pair method and include it as a control direction in the LLM-state-and-behavior class. Steer it and compare its accuracy delta to the peer-ness directions: if sycophancy reproduces the framing-induced delta and peer-ness does not, the mechanism story is wrong but the result is still publishable. Builds on the steering harness from "Per-dimension steering protocol". See plan-66d430f.md "Phase 3 — Sycophancy-direction comparison" and "Sycophancy as a competing mechanism".
- **tests**: A sycophancy direction is extracted and validated like the peer-ness probes; steering it produces an accuracy delta reported side-by-side with the peer-ness steering deltas.
- **files**: experiments/user-model/phase3/sycophancy.py (new)
- **depends_on**: Per-dimension steering protocol

---

### PR: Alternative-mechanism disambiguation
- **description**: Extract three independent confound directions by the same contrast-pair method — register-matching, high-status-interlocutor rule, and RLHF-policy — and steer each against the peer-ness directions. The peer-ness mechanism story holds only if the peer-ness direction retains explanatory power once all three are accounted for. Builds on the steering harness from "Per-dimension steering protocol". See plan-66d430f.md "Phase 3 — Alternative-mechanism disambiguation".
- **tests**: Register, status-rule, and RLHF-policy directions are each extracted and steered; a comparison report shows peer-ness steering deltas net of each confound; the same Holm-Bonferroni / BH-FDR multiplicity discipline is applied.
- **files**: experiments/user-model/phase3/alt_mechanisms.py (new)
- **depends_on**: Per-dimension steering protocol

---

### PR: Introspection prompt design (per dimension)
- **description**: Phase 4 foundation. Design prompts that ask a model to report its perception of the user along each sub-dimension — multiple styles (direct, indirect, structured-fields-with-confidence) and per-dimension rather than overall. Pure prompt-authoring; produces the prompt library the calibration step scores. See plan-66d430f.md "Phase 4 — Introspection prompt design".
- **tests**: Prompt library contains at least one prompt per sub-dimension in each style; structured-field prompts parse into a dimension→score mapping; a parser unit test covers the structured-field output format.
- **files**: experiments/user-model/phase4/introspection_prompts/ (new), experiments/user-model/phase4/parse.py (new)
- **depends_on**:

---

### PR: Calibrate introspection against probed truth (open model)
- **description**: On the Phase 1 open model, for each conversation prefix and each dimension: probe to get the ground-truth internal value, run the introspection prompt and parse the answer, and measure agreement. Produces the calibrated mapping from verbalized self-report to a probe-grounded scale. Receives the probes from "Extract and validate peer-ness vectors" and the prompt library from "Introspection prompt design (per dimension)". Note: Phase 4 calibrates against the Phase 1 correlational probe, so it inherits a behavioral-grade evidence bar, not Phase 3's causal bar. See plan-66d430f.md "Phase 4 — Calibrate introspection against probed truth".
- **tests**: For each dimension, agreement between probe value and parsed introspection answer is computed and reported; the best-calibrated prompt per dimension is selected; the calibration curve serializes for reuse in the transfer step.
- **files**: experiments/user-model/phase4/calibrate.py (new)
- **depends_on**: Extract and validate peer-ness vectors, Introspection prompt design (per dimension)

---

### PR: Transfer to closed models
- **description**: Apply the best-calibrated introspection prompts to Claude / GPT / Gemini and validate indirectly via consistency under paraphrase and behavioral coherence (a model reporting low intellectual peer-ness should produce shorter / more hedged work). Results must be reported with the explicit limitation that closed-model transfer is behavioral-grade and does not establish a causally-mediating representation. Receives the calibrated prompts from "Calibrate introspection against probed truth (open model)". **Human-guided testing**: requires closed-model API access and keys (Claude, GPT, Gemini); the review loop should use INPUT_REQUIRED if API credentials are unavailable in its environment.
- **tests**: Calibrated prompts run against at least one closed model per vendor; paraphrase-consistency and behavioral-coherence checks are computed; the behavioral-grade limitation is present in the emitted report.
- **files**: experiments/user-model/phase4/transfer.py (new), experiments/user-model/phase4/closed_models.py (new)
- **depends_on**: Calibrate introspection against probed truth (open model)

---

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
- Ghandeharioun et al. "Patchscopes" (ICML 2024)
- Karvonen et al. "Activation Oracles" (Anthropic 2025)
- Fraser-Taliente, Kantamneni, Ong et al. "Natural Language Autoencoders" (Anthropic 2026)
- Sharma et al. "Towards Understanding Sycophancy" (2023)
- Perez et al. "Discovering Language Model Behaviors with Model-Written Evaluations" (2022)
- Chen, Viégas, Wattenberg et al. "TalkTuner — Dashboard for Transparency and Control of Conversational AI" (2024)
- Rimsky et al. "Steering Llama 2 via Contrastive Activation Addition" (2024)
- Marks & Tegmark "The Geometry of Truth" (2023)
- OpenAI "Sycophancy in GPT-4o: What happened and what we're doing about it" (2025)
- Wang et al. "When Truth Is Overridden: Internal Origins of Sycophancy in LLMs" (AAAI 2026)
- Gemma Scope (2024)
- TransformerLens, NNsight, SAELens (tooling)

## Why this fits in pm at all

pm is well-suited to host this experiment: file-backed plans + PR-graph let us scope each phase as a sequence of PRs with explicit acceptance criteria; the watcher framework gives us automation for batch experiment runs; and pm's own anecdotal observation — that the user's preferred framing ("treat the agent as a colleague") yields better results than a bare task prompt — is the motivating intuition for the whole investigation.
