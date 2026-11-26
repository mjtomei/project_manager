# Review Cycle 3 — Literature Review: User-Modeling as a Lever on LLM Performance

Reviewer: blind Cycle-3 pass. Did not read Cycles 1/2 before drafting this section. The cross-reference appendix at the end was written after, per instructions.

---

## Block 1 — Substance

### B1.1 The "peer-ness" framing collapses on operationalization (load-bearing)

The Introduction and §7 stake the entire review on "intellectual + moral peer-ness" as a two-meta-dimension construct. Under scrutiny, the construct fragments.

(i) **Differentiation from existing variables.** The six sub-dimensions enumerated — technical competence, effort/seriousness, reasonableness, honesty/sincerity, good-faith, mutual respect — are not new conceptual primitives; they are a relabeling of (a) the user's perceived expertise (Salewski's in-context impersonation already moves this), (b) sentiment/affect (Tigges 2023), (c) sycophancy-adjacent agreement signals (Perez 2022), and (d) the model's character emotions (Tak 2025). "Peer-ness" is the union, not a distinct latent. The plan needs to demonstrate — not assert — that a probe trained on its contrast pairs picks up a direction that is *not* a linear combination of (sentiment direction + sycophancy direction + perceived-expertise direction). The current §7 simply says it does. That is unsupported.

(ii) **Two-meta-dimension structure is invented, not derived.** No cited work motivates "intellectual peer-ness" and "moral peer-ness" as the right partition. The split tracks a folk-psychology decomposition (competence-vs-warmth, Fiske et al. stereotype-content model) which is *not cited*. If the review wants to claim the partition is principled, it must cite Fiske/Cuddy or an equivalent in social cognition; if it wants to claim the partition is empirical, it owes a factor-analysis from a pilot. Currently it does neither.

(iii) **Training-data-imitation as a just-so story.** The mechanism statement — "humans calibrate effort based on perceived equality, LLMs internalize this" — is plausible but unsupported by any cited work. No paper in the bibliography establishes that *collaboration-conditional effort modulation* is a pattern LLMs internalize. Andreas 2022 supports addressee-modeling in the abstract; it does not establish this specific modulation. The reader is asked to accept the mechanism on intuition. At minimum cite something on pretraining-corpus analyses of code-review or peer-review text (e.g., work on Stack Overflow tone-and-quality correlations); if such studies don't exist, label the mechanism as a *hypothesis to be tested by the result*, not an explanation for why the prediction follows.

**Recommendation:** demote the "training-data-imitation" mechanism from explanatory frame to predicted-side-product. Add a falsification step in Phase 2 that compares a peer-ness probe head-to-head with (sentiment ⊕ sycophancy ⊕ expertise) probes on the same activations. If the peer-ness direction is well-predicted by the union, the construct collapses.

### B1.2 Closest published peer was missed: Choi et al. 2025 (Transluce)

"Scalably Extracting Latent Representations of Users" (Choi et al., Transluce, November 25 2025, https://transluce.org/user-modeling) trains probes that read user attributes from a model's residual stream activations and intervene on those probes to steer behavior. Held-out attributes include demographic and situational variables (age, gender, religious affiliation, occupation, employment, marital status) across roughly 80 categories. The paper:

- Is the closest published methodological *and* variable-side peer to Phase 1 + Phase 4.
- Directly contradicts §7's "(no published peer found) — factual user beliefs as a decoded variable" claim. Choi et al. *is* that peer.
- Demonstrates that the basic feasibility result the review attributes to Phase 1 — "peer-ness is decodable from the residual stream" — has been partially established for adjacent user-side variables. The novelty argument shrinks accordingly.

This is the single most important omission in this cycle. It needs explicit treatment in §7 ("what we're not measuring") and in §4 (methodological precedent). After Choi, Phase 1's standalone novelty is no longer "first to probe a user-side latent"; it is "first to probe *peer-ness specifically* if peer-ness survives B1.1."

### B1.3 Phase 1 novelty further weakened by SAE / scaling-monosemanticity prior art

Anthropic's "Scaling Monosemanticity" (Templeton et al., May 2024, https://transformer-circuits.pub/2024/scaling-monosemanticity/) reports SAE features including ones for "sycophancy", "deception", "self-improvement", and various sentiment-of-text features on Claude 3 Sonnet. The review does not cite this work at all. Several of those features are within the moral-peer-ness sub-dimension neighborhood (honesty, good-faith). At minimum:

- Cite Templeton et al. 2024 in §4.
- Address whether published SAE feature catalogs *already include* peer-ness-adjacent features. If yes, Phase 1 reduces to confirming a coordinated multi-feature *structure* rather than discovering features per se.

### B1.4 Phase 2's "multi-axis fractional factorial" is aspirational, not specified

§7's design enumerates five axes (politeness × respect-for-competence × honesty × good-faith × effort) and asserts "fractional factorial chosen so each axis varies independently". The review does not specify:

- The cell count (8? 16? 32?).
- The resolution of the fractional design (Resolution III, IV, V?). At Resolution III, main effects are confounded with two-way interactions — fatal here, because the whole point is to dissociate axes.
- The seed-prompt sample size per cell.
- How orthogonality is *enforced*, given the axes are not independent in natural language (a high-effort prompt almost necessarily reads as more respectful; a dishonest prompt may co-vary with impoliteness in templates).
- Per-axis effect-size targets and power.

Without these, the design exists only as a sentence. Five axes is in fact *worse* than 1D or 2×2 if not nailed down — degrees of freedom multiply and statistical power per cell collapses. A Cycle 3 reader cannot evaluate whether the design works. Either move to a specified Resolution-V design (which requires 16 cells minimum and pre-registered prompt templates with crossed-but-decorrelated phrasing) or downgrade the language to "we plan a fractional-factorial design; the exact resolution is TBD".

### B1.5 §4 vs §7 standards-mismatch is *almost* resolved but has residual incoherence

§4 introduces the behavioral-grade-vs-mediation-grade distinction. §7's predicted-outcome cell (3) requires interchange-intervention evidence; cell (4) requires comparing peer-ness steering against an *independently extracted* sycophancy direction. Two problems:

- Cell (3) language: "Phase 3 steering causally confirms one or more sub-dimensions." Steering alone is *not* interchange-intervention. §4 itself flags that steering = sufficiency, not mediation. The cell description should say "interchange-intervention confirms" or "ablation + activation-patching confirms", not "steering causally confirms".
- The Phase 4 closed-model transfer is described as relying on calibration against open-model probes. But §6 acknowledges Turpin-style confabulation. If the closed-model self-report is calibrated only on the *correlational* probe (behavioral-grade) and not on the *causally-validated* direction (mediation-grade), Phase 4 inherits the weaker bar — and the review should say so. Currently §6 implies Phase 4 piggybacks on Phase 1's full pipeline; it actually piggybacks on Phase 1's probe.

### B1.6 Sycophancy framing is inconsistent across §5 and §7

§5 says sycophancy is "mechanism-noise the plan is indifferent to" on most benchmarks. §7 cell (d) treats "the probed direction is the sycophancy direction in disguise" as a *publishable RLHF artifact* finding — i.e., a result of independent interest *and* a confound to distinguish from peer-ness proper. These framings can be reconciled (noise for gradable benchmarks, signal for the mechanism story) but the review does not do the reconciliation explicitly. A reader following §5 will be surprised by §7's cell (d) implying that distinguishing peer-ness from sycophancy is the whole point of Phase 3. Pick one frame:

- Either: sycophancy is mechanism-noise, and cell (d) collapses into "we found a sycophancy effect; not our research question; report and move on."
- Or: sycophancy is the principal alternative hypothesis to peer-ness, in which case §5 must be lengthened, not shrunk, and the contrast-pair design must include explicitly disagreeing-with-the-user variants to dissociate.

Currently the review wants both. It can't have both.

### B1.7 Predicted-outcomes table is incomplete

Four cells are enumerated. Missing outcomes:

- **(e) Heterogeneous sub-dimensions.** Some sub-dimensions correlate with performance, others don't, and the structure depends on benchmark domain (e.g., honesty matters for TruthfulQA, effort matters for GSM8K, mutual respect matters for nothing). This is in fact the *most likely* outcome given the framing-effects literature. The review should preregister how it will interpret a heterogeneous-sub-dimension result and whether that counts as confirmation, partial confirmation, or refactoring of the construct.
- **(f) Contradiction across model families.** A peer-ness effect on Llama-3 that disappears on Gemma or Qwen — common in steering papers. What's the rule?
- **(g) Effect size below the Sclar 2024 noise floor.** Sclar shows formatting-only changes can move accuracy by ≤76 points on Llama-2-13B. If the peer-ness effect is real but smaller than format-induced noise, the plan reports a null even with a true mechanism. Pre-register a paraphrase-resampling protocol (already alluded to in §8 but not tied back to §7).
- **(h) Result depends on RLHF stage / instruction-tuning corpus.** A peer-ness effect that appears only in RLHFed checkpoints is interesting (confirms the training-data story by showing it's enhanced by human-feedback fine-tuning) but unflagged here.

A four-cell table that ignores the most likely outcome (e) is brittle.

### B1.8 The transformer-circuits 2026 citation predates plausible publication

The reference to **"Emotion Concepts and their Function in a Large Language Model" (transformer-circuits.pub 2026)** dates a research note one year ahead of plausibility for a January-2026 lit review. Today is mid-May 2026, so 2026 dates are *now* possible, but the review should give the month — e.g., "transformer-circuits.pub, January 2026" — and link the canonical URL. As written, it reads like a placeholder.

### B1.9 Tan et al. 2024 citation is still unresolved and shouldn't be retained as-is

The reference list has: `Tan, et al. 2024. (Agent personality traits — flagged by Cycle 1 reviewer; full citation pending verification.)` and §7 has `(Tan et al. 2024 — cited by Cycle 1 reviewer; verify before final inclusion)`. A Cycle 3 review of a polished document should not contain "verify before final inclusion" markers. A blind reader has no way to evaluate the claim that this citation is the closest variable-side peer. Either:

- Resolve the citation. Candidates surfaced by search: Serapio-García et al. 2023 ("Personality Traits in Large Language Models", arXiv:2307.00184) is the major personality-in-LLMs paper but is 2023 and not by Tan. "From Traits to Circuits" (anonymous OpenReview submission, mechanistic interpretability of LLM personality) is closer methodologically but not by Tan either. A "Tan 2024 agent personality" paper that matches the description is not findable in arXiv via standard search. The citation may be a Cycle-1 hallucination that survived two cycles.
- If unresolvable, cut the citation and use Serapio-García 2023 + "From Traits to Circuits" as the personality-side adjacency.

### B1.10 Missing citation: stereotype-content / competence-warmth from social psychology

If the two-meta-dimension partition (intellectual peer-ness ≈ competence; moral peer-ness ≈ warmth/trustworthiness) is to be principled, Fiske, Cuddy & Glick's stereotype-content model (2002 / 2007) is the obvious anchor. The review's two-axis split is the same shape. Either cite it (in which case the construct gets cross-disciplinary support) or note explicitly that the choice is a-theoretical and the partition will be validated post hoc by the probe geometry.

### B1.11 The "humans calibrate effort by perceived equality" claim needs a citation

§1 and §7 both assert this as ground truth about humans. It is plausible but it is a strong empirical claim about human collaboration. Either cite a social-psychology source (e.g., research on peer-vs-novice collaboration quality, or accountability/audience effects on cognitive effort) or hedge it ("anecdotally" / "the working assumption is"). A literature review should not assert empirical claims about a non-CS field without citation.

### B1.12 Pan/Chen/Steinhardt venue

The review cites LatentQA as arXiv:2412.08686, 2024. Per current arXiv metadata it was accepted to ICLR 2026 (search result). If the review wants peer-review credit for the citation, update the venue.

---

## Block 2 — Structure and readability

### B2.1 The 22-bullet glossary at the start is overlong and front-loads cognitive cost

A non-expert reader hitting a 22-item glossary in the first 600 words will close the tab. Glossaries are reference material; they don't read linearly. Restructure:

- Keep a short glossary (5–7 items) for terms used in §1: LLM, RLHF, alignment, sycophancy, persona prompt, role-play.
- Move the interpretability-tool terms (residual stream, probe, contrast pairs, steering vector, SAE, activation patching, causal mediation, refusal direction, calibration) to the head of §4, where they are first used load-bearingly.
- Move pass@k, few-shot/zero-shot to §8.
- Move venue acronyms to a one-line footnote where first used.

This both reduces front-loaded burden and puts each gloss next to its first use, which is the only place a non-expert reader will encounter it in context.

### B2.2 The introductory hypothesis-statement repeats itself

The blockquote in §0 and the restated blockquote at the top of §7's "what the plan is and isn't claiming" are verbatim duplicates. One should reference the other, not restate. Cut the duplicate in §7.

### B2.3 §4 is too long for what it does

§4 carries roughly 12 paper summaries in sequential paragraphs. After paragraph 6 the reader has lost the thread of which paper is doing what work for the plan. Consider a table:

| Paper | Variable probed | Evidence grade | Role for the plan |
|---|---|---|---|
| Zou 2023 (RepE) | honesty, harmlessness, ... | steering | Phase 1 recipe |
| Tigges 2023 | sentiment polarity | causal mediation | closest methodological peer (single-axis) |
| Marks 2023 | truth | causal mediation | worked example of the bar Phase 3 must clear |
| Arditi 2024 | refusal | causal mediation | worked example, multi-model |
| ... | ... | ... | ... |

The table makes the §4 vs §7 standards-mismatch resolution visible at a glance.

### B2.4 §5 ends in mid-air

After the Denison 2024 paragraph, §5 closes with anchors — no concluding sentence about how sycophancy fits the plan's design. Compare §4, which has a tidy summary line. Add: "Net effect on the design: sycophancy is treated as a mechanism alternative to peer-ness in Phase 3, not as a confound to be eliminated. TruthfulQA and FEVER are retained as benchmarks specifically because their accuracy profile under framing distinguishes peer-ness from sycophancy."

### B2.5 §7's section opening jumps in

"This section covers the causal-mediation methodology the plan's Phase 3 inherits, then situates the plan's novelty against the closest adjacent works." This is a structural sentence, not a hook. The reader doesn't know yet *why* the novelty question matters here vs. in the Conclusion. Open with: "This is the section that decides whether the plan is publishable. The methodology bar Phase 3 must clear, and the variable-space neighborhood the plan stakes its novelty against, are both here."

### B2.6 Conclusion is largely list of citations

The final section reads as a citation roll-call. Replace the second long paragraph ("Where the plan inherits cleanly...") with a sentence per category, citation in parentheses. The reader has already seen these names.

---

## Block 3 — Non-expert accessibility (load-bearing)

The review has been through two accessibility passes. Many improvements survive. The remaining problems are mostly second-order — terms that are glossed but the gloss itself contains jargon, or glosses placed far from first load-bearing use.

### B3.1 "Peer-ness" itself is not glossed for a non-developer

The single most load-bearing word in the document, used 30+ times, appears in the first paragraph without a one-clause gloss. "Intellectual and moral equal" is closer but still abstract. Proposed inline gloss at first use:

> *peer-ness — does the model behave as if the user is a competent, honest, in-good-faith collaborator (a peer), versus a low-effort or hostile one (not a peer)? Throughout this review, peer-ness is the model's running judgment of the user, not a property of the user themselves.*

Without this, the reader doesn't know whether "peer-ness" is a stable trait, an instantaneous judgment, a continuous variable, or a category. The current text leaves it ambiguous.

### B3.2 "Residual stream" is glossed, but the gloss contains "layer" without definition

Current gloss: "the running internal scratchpad inside the network — a long list of numbers at each layer". A non-developer does not know what a layer is. Replacement:

> *residual stream — the network's running internal scratchpad. The network processes the input in a sequence of stages; at each stage, this scratchpad is updated. Interpretability tools read and edit this scratchpad to figure out what the network is "thinking" at a given point.*

### B3.3 "Probe" gloss says "small classifier" without defining classifier

Current: "a small classifier trained to read a specific concept out of the residual stream." A classifier is itself jargon. Replacement:

> *probe — a small companion model trained to look at the scratchpad and answer one yes/no question (e.g., "does this scratchpad encode that the user is being polite?"). If the probe can answer accurately, the concept is present in the scratchpad — but presence doesn't mean the network is actually using it.*

### B3.4 "Activation patching / interchange intervention" is unreadable as-is

Current: "copy an activation from run A into run B at a specific site and check whether B's output changes in the way predicted." The terms "activation", "run", "site" are all unanchored. Replacement:

> *activation patching — the strong test for "is the network using this internal state to produce this answer?" Run the network twice with two different inputs; copy the network's internal state from one run into the same position of the second run; then check whether the second run's answer changes the way you expected. If it does, the copied state is genuinely causing the behavior, not just correlated with it.*

### B3.5 "Refusal direction" glossed without saying what direction means in this context

Current: "the direction in the network's activation space that, when amplified, makes the model refuse to answer." A non-developer hears "direction" as physical direction. Replacement:

> *refusal direction — a specific pattern in the network's scratchpad whose presence makes the model refuse. Amplify the pattern and the model refuses more; erase it and it stops refusing harmful prompts.*

### B3.6 Section-opening "why should I care" failures

§4 opens: "This section describes the methodological backbone the plan uses to measure its IV." "IV" is not spelled out (independent variable — spelled out only once, in §0). A non-developer encountering "IV" thinks "intravenous". Replace section opening:

> *Why this section: the plan needs to (a) read out a number for "how peer-like does the model judge the user to be" and (b) change that number on purpose to see if performance changes. This section is the toolkit for doing both — what the techniques are called, what they measure, and how strong the evidence each gives.*

§5 opens: "The sycophancy literature is well-developed, and it is worth situating carefully relative to the plan." Doesn't say why the reader cares. Replace:

> *Why this section: the obvious alternative explanation for any "treat the model nicely → better answers" effect is sycophancy (the model telling you what you want to hear). This section is about why sycophancy is not the same thing as peer-ness, and how the plan tells them apart.*

§6 opens: "This section describes methodology load-bearing for the plan's Phase 4 (transfer to closed models)." Same problem. Replace:

> *Why this section: the plan's interpretability machinery only works on open models (where you can poke around inside). Most people who'd actually use these results have only closed models (ChatGPT, Claude, Gemini accessed through an API). This section is about whether the model can be asked, in plain English, "how do you see this user?" — and trusted to answer.*

### B3.7 "Inverse scaling" used without gloss in §5

"This is inverse scaling — bigger models doing worse." The em-dash clause is an attempt at a gloss but doesn't say *why* this is surprising or important. Add: "(normally, bigger models do *better* on accuracy benchmarks; inverse scaling is the rare case where capability gets worse with size, and it's a signal that the model is learning the wrong thing.)"

### B3.8 Numbers without scale anchors

- "accuracy improves by roughly 10 percentage points on average" — anchor: "for context, switching from GPT-3.5 to GPT-4 on the same tasks is a 15–20 point jump. A 10-point shift from rewording a prompt is large."
- "tiny changes ... can move accuracy by up to 76 percentage points on LLaMA-2-13B" — anchor: "76 points means a model that scores 80% on one phrasing of the test scores 4% on a trivially-rephrased version. That's the difference between an A and an F from changing whitespace."
- "Truthfulness on TruthfulQA jumps from 32.5% to 65.1% on Alpaca" — already concrete; could add "roughly doubling correctness."
- "persona assignment can multiply toxicity up to six-fold" — anchor: "if the no-persona baseline is one toxic response in fifty, a six-fold multiplier means roughly one in eight."

### B3.9 Names dropped without context

- **"AGENTS.md"** in §3: needs one line on what kind of document this is in practical terms. Add: "(Think of it as a README written for the AI rather than for a human collaborator — same shape, but the audience is the model.)"
- **"Karpathy"** in §2 and §8: referenced without context. Add at first use: "(Andrej Karpathy — a widely-followed practitioner who publishes general-audience tutorials on using LLMs.)"
- **"transformer-circuits.pub"** in §7 and references: nowhere does the review say this is Anthropic's interpretability-research publication venue. Add at first use: "(Anthropic's in-house publication venue for interpretability research; not peer-reviewed but high-quality.)"
- **"Linux Foundation"** and **"Agentic AI Foundation"** in §3: a non-developer may not know what these are. Add: "(The Linux Foundation is a non-profit that hosts shared open-source standards; AGENTS.md was moved under it in 2025 to give the spec a neutral home.)"
- **"BIG-Bench Hard"** in §6: introduced without explaining what it is. Add: "(a benchmark suite of 23 difficult reasoning tasks designed to be hard for current models.)"

### B3.10 "Fractional factorial" in §7 is unanchored

The target reader does not know what a fractional factorial is. The current paragraph uses the term twice load-bearingly. Replacement first-use:

> *fractional factorial design — a way to test multiple variables at once without trying every combination. With five on/off switches (politeness, respect, honesty, good-faith, effort), there are 32 combinations; testing all 32 with enough samples each is too expensive. A fractional factorial picks a careful subset (say, 8 or 16 combinations) chosen so that each switch's effect can still be measured separately. The standard tool from agricultural and industrial experiment design.*

### B3.11 "Pre-registered" — implied but not used

The review doesn't say "pre-register", but the four-cell predicted-outcome table is functionally a pre-registration. A non-academic reader needs context: "Listing the possible outcomes before running the experiment is called pre-registration. It exists to prevent the researcher from quietly tuning the analysis to match the result. The plan should publish this list before running Phase 2."

### B3.12 "Linear representation" jargon used without gloss

§4 and §7 use "linear representation hypothesis" and "linearly encoded" repeatedly. Glossable as: "(a concept is *linearly represented* if a single straight-line direction in the network's scratchpad encodes 'how much of this concept is present' — like a knob you can turn up or down. Not all concepts work this way, but many of the well-studied ones do.)"

### B3.13 "Spotlight" tag at NeurIPS (Salewski citation)

"NeurIPS 2023 (Spotlight)" in the references — a non-academic doesn't know that Spotlight is a paper-acceptance tier. Either explain ("NeurIPS Spotlight is the top ~5% of accepted papers, signaling high reviewer enthusiasm") or drop the tag.

### B3.14 Glossary item for "calibration" is too thin

Current: "checking one measurement against an independent one, so the two can be compared." A non-developer reader doesn't have an intuition for *why* this matters in Phase 4. Add: "In Phase 4 specifically, calibration means: the closed-model self-report ('how do you see this user?') is a number; the open-model probe is a different number on the same input; calibration is making sure they're on the same scale so you can use the easy one (self-report) as a stand-in for the hard one (probe)."

### B3.15 "Surgically intervening on the direction flips whether the model treats false statements as true" (§4)

The verb "flips" plus "treats false statements as true" together are confusing — does the model now believe falsehoods? state them? rate them as true? Replacement: "...intervening on the direction makes the model rate false statements as true (and vice versa) in its outputs. The intervention is causal because it directly changes the variable that previously only correlated with the model's truth-rating."

### B3.16 Section-7 "this is the section that decides whether the plan is publishable" suggestion (from B2.5) also serves Block 3

Worth flagging that the same rewrite makes the section accessible *and* substantively framed.

---

## Convergence assessment

**Has convergence been reached? Not quite. Cycle 4 is needed, but it should be short.**

The strongest signal for *not yet*: B1.2 (Choi et al. 2025) is a substantive, prior-art-overlap finding that materially changes the novelty claim and is missing from the current text. That is not a phrasing nitpick. B1.1 (peer-ness collapses on operationalization) and B1.4 (fractional-factorial design unspecified) are also substantive — the construct validity and the design specification are first-order issues, not polish.

Other Cycle-3 findings are more borderline. B1.5–B1.7 are tightening of an internally-coherent-but-not-airtight argument. B1.8–B1.12 are citation-hygiene issues that a copyedit catches. Block 2 findings are clearly entering nitpick territory (the document's structure is fundamentally fine; the changes proposed are improvements not corrections). Block 3 findings include both genuine gaps (B3.1 — peer-ness ungloss is a real accessibility failure for the load-bearing term) and tightening (B3.7–B3.10).

**Prediction.** A Cycle-4 response that (a) folds in Choi 2025 explicitly, (b) either operationalizes peer-ness as distinct from sentiment+sycophancy+expertise or downgrades the construct claim, (c) specifies the fractional-factorial design or downgrades the design language, (d) glosses peer-ness on first use, and (e) resolves the Tan citation will close out. After that, a Cycle-4 review would produce only phrasing-level findings. The natural stopping point is one cycle further than the sibling regression-loop review hit — Cycle 4, not Cycle 3 — because this artifact has more substantive prior-art neighbors that haven't all been surfaced yet. The peer-ness construct is genuinely novel-adjacent in a way that the regression loop's contribution wasn't, and that means more adjacent papers to chase down.

If, instead, the response chooses to push back on B1.1 ("peer-ness *is* distinct, here's the evidence") and B1.2 ("Choi 2025 isn't the same thing, here's why"), then a Cycle 5 follow-up to verify the pushback would be warranted. Either way, Cycle 3 is not the last cycle.

---

## What prior cycles missed (cross-reference, written after independent review)

I read REVIEW_CYCLE_1_USERMODEL.md, REVIEW_CYCLE_2_USERMODEL.md, REVIEW_RESPONSE_CYCLE_1_USERMODEL.md, REVIEW_RESPONSE_CYCLE_2_USERMODEL.md, and REVIEW_RESPONSE_CYCLE_2_USERMODEL_CORRECTION.md only after writing the above.

Findings that earlier cycles did not surface (or surfaced weakly):

1. **Choi et al. 2025 / Transluce user-modeling — misidentified, not just missed.** Cycle 1 flagged a "Choi et al. 2025 — LatentQA-style decoders on model beliefs about the user" item, but conflated two distinct works: (a) Pan/Chen/Steinhardt 2024 *LatentQA* (general activation decoding, no user-attribute focus) and (b) Choi et al. 2025 *Scalably Extracting Latent Representations of Users* (Transluce, https://transluce.org/user-modeling — the actual user-attribute-probing paper). The Cycle 1 response routed the finding to citing LatentQA instead of the Transluce paper. The Transluce paper was never properly identified and is still uncited. This is the most consequential miss across both cycles, because Choi/Transluce is a direct methodological and variable-side peer for Phase 1 and Phase 4 in a way LatentQA is not. The "no published peer found" line in §7 about factual user beliefs is now factually wrong.

2. **Stereotype-content / competence-warmth grounding (Fiske/Cuddy)** — no prior cycle suggested that the two-meta-dimension split needs cross-disciplinary anchoring. Prior cycles accepted "intellectual + moral" as a partition without asking for theoretical support.

3. **Construct-validity falsification step** (B1.1) — neither prior cycle proposed a head-to-head probe comparison (peer-ness vs sentiment ⊕ sycophancy ⊕ expertise) as a way to test whether peer-ness collapses. Prior cycles took the construct's distinctness on faith.

4. **Resolution of the fractional-factorial design** (B1.4) — prior cycles flagged that the design was thinly specified but did not name the specific gap (Resolution III vs Resolution V, axis-correlation problem inherent to natural language, sample size per cell). The current §7 language survives because the request was generic.

5. **Predicted-outcome cell (e) — heterogeneous sub-dimensions** — prior cycles seem to have accepted the four-cell table as exhaustive. The most likely real-world outcome (some sub-dimensions correlate, others don't, structure depends on benchmark) is not in the table.

6. **Scaling Monosemanticity / SAE feature catalogs** (B1.3) — neither prior cycle pulled in Templeton et al. 2024 to ask whether peer-ness-adjacent features already exist in published SAE inventories. This affects the novelty argument.

7. **The "humans calibrate effort by perceived equality" claim is uncited** (B1.11) — prior cycles let this pass as common sense. It's a real empirical claim about humans and warrants a social-psychology citation.

Findings prior cycles caught that I would echo: the Tan 2024 citation problem (caught by Cycle 1, only partially addressed); the standards-mismatch between §4 and §7 (raised and partially fixed in Cycle 2); the sycophancy framing's relationship to the predicted-outcomes table (partially raised). I converged with prior cycles on these.

Findings prior cycles raised that I now disagree with: I will not list these without having read them in adversarial detail; methodology says the cross-reference appendix is for what prior cycles missed, not for adjudicating them.

The pattern: prior cycles did very well on internal coherence (does §4 line up with §7? are the cited papers being used correctly?). They did less well on *adjacent prior-art search* — finding papers that aren't yet in the bibliography but should be. Cycle 3's contribution is concentrated in that gap.
