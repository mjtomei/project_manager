# Corrective Response — Cycle 2 over-correction on user-model lit review

Date: 2026-05-14
Context: the Cycle 2 response wrongly demoted interpretability methodology to "optional follow-up science" based on a too-narrow reading of the plan's claim. The in-flight edit applied that demotion, producing a lit review that's 33% shorter but materially misrepresents the plan. This document specifies what to restore, what to keep, and what to add.

## What went wrong

The Cycle 2 response narrowed the plan's hypothesis to: *"framing affects performance, period; mechanism is optional follow-up."*

The actual hypothesis is: *"model competence varies with the model's view of the user."* This has two load-bearing variables:

- **IV: the model's view of the user** — an internal latent. Measuring it is an interpretability problem (probing internal state). This is *not* optional; it's how we measure the IV.
- **DV: model competence** — measured via gradable benchmarks. The engineering side.

Without the IV measurement, the plan can't test its hypothesis. Demoting interpretability demotes the IV.

## The corrected framing

**Hypothesis** (cleanest statement): *The more an LLM perceives the user as an intellectual and moral equal, the higher the quality of the LLM's work. The cause is that LLMs emulate humans, and humans work better when they perceive their collaborator as an equal.*

The IV is the LLM's internal representation of the user along two meta-dimensions:

- **Intellectual peer-ness** — does the model perceive the user as a thinking-partner of comparable capability? Sub-dimensions: technical competence, effort/seriousness (has the user thought about it themselves?), reasonableness (does the user reason well, including about feedback?).
- **Moral peer-ness** — does the model perceive the user as a trustworthy, in-good-faith collaborator? Sub-dimensions: honesty/sincerity, good-faith engagement, mutual respect.

Each meta-dimension has multiple sub-dimensions, but the meta-dimensions themselves are the load-bearing structure.

The DV is **work quality** — measured via standard gradable benchmarks (math, code, knowledge tasks where correctness is gradable).

The mechanism is **training-data-imitation**: LLMs read enormous quantities of human-produced text, including text where humans collaborate. Humans calibrate effort, care, and rigor based on perceived equality of the partner. LLMs internalize this calibration. The prediction follows directly from the training process — it does not require LLMs to have genuine social cognition, only that they emulate the human pattern.

**Phase structure** (corrects what the in-flight edit produced):

- **Phase 1 — probe for the model's user-equality representation along the two meta-axes.** Establish that the model forms readable, linearly-decodable judgments along both intellectual-peer-ness (with sub-dimensions for competence, effort, reasonableness) and moral-peer-ness (with sub-dimensions for honesty, good faith, respect). **Standalone novelty**: no published work maps a peer-ness representation in LLMs. Park 2024 covers single factual concepts (language, gender). Tigges 2023 covers sentiment polarity (one axis). The emotion-mediation papers cover one emotion at a time, on characters or the model's own state. LatentQA (Pan/Chen/Steinhardt 2024) decodes hidden system prompts and general activations but doesn't target the user-judgment space. **The plan's contribution is the vector**: a coordinated set of user-judgment dimensions probed together, not a single variable in isolation. If Phase 1 succeeds, the plan has added a new *multi-axis structure* to the linear-representation literature.
- **Phase 2 — measure view-competence relationship across dimensions.** Vary input framings along multiple axes (politeness × respect-for-competence × honesty signals × good-faith signals × ...) and read out both each probed dimension (Phase 1 probe vector) and the model's competence (benchmark). Correlate each dimension with performance. Open empirical question: do all dimensions matter equally? Is there one dominant axis, or is the effect distributed?
- **Phase 3 — causal test per dimension.** Steer each probed direction independently and re-measure performance. Distinguish which dimensions causally affect competence and which are merely correlated.
- **Phase 4 — transfer to closed models.** Output-token readout of each dimension via meta-prompt, calibrated against the open-model probes.

Every phase has independent scientific contribution. The plan is not gated on the full chain working — Phase 1 alone is publishable as "first map of the multi-variable user-judgment representation in LLMs." Phase 2 adds the correlation with performance. Phase 3 adds causation per axis. Phase 4 adds production applicability.

## Specific corrections to the lit review (undo / keep / add)

### What to UNDO from the in-flight edit (over-correction)

1. **Title change**: revert "Framing as a Lever on LLM Performance" back to **"User-Modeling as a Lever on LLM Performance"**. The plan is about user-modeling; the framing is the experimental manipulation, not the thesis.

2. **Glossary split**: revert the "Core terms" vs "Optional follow-up terms" split. All interpretability terms (residual stream, probe, contrast pairs, SAE, activation patching, interchange intervention, causal mediation, refusal direction) belong in the Core glossary because they describe how the plan measures its IV.

3. **§4 and §7 "optional follow-up" prefacing**: remove. These sections describe load-bearing methodology, not optional add-ons.

4. **§7 novelty rewrite**: the in-flight edit replaced the four-axis "what we're not measuring" taxonomy with a description of the 2×2 design only. Restore the four-axis taxonomy with corrected framing (specified below in "Add").

5. **§6 introspection**: revert the "optional follow-up" prefacing. Output-token readout is Phase 4 (transfer to closed models), required for the plan's production applicability.

6. **Mechanism work demotion in Conclusion**: revert. The Conclusion should treat the mechanism work (Phase 2 onward) as the plan's load-bearing science, not optional.

### What to KEEP from the in-flight edit (correct simplification)

1. **§5 sycophancy shrink**: the dramatic shrink was right. Sycophancy is mechanism-noise the plan is indifferent to. Whatever mechanism produces a view-competence relationship is fine. The Cycle 2 review's "rival hypothesis the mediation analysis adjudicates" framing was wrong; the corrective shrink was right.

2. **Karpathy walk-back collapsed to one sentence**: correct, keep.

3. **Duplicate inline glosses cut where term is in glossary**: correct, keep.

4. **§7 / Conclusion "what we're not measuring" verbatim duplication cut**: correct, keep — but the taxonomy itself comes back in §7 with corrected framing (see "Add").

5. **§4/§7 standards mismatch resolution**: the in-flight edit correctly resolved this. Keep the explicit statement that mediation-grade evidence is needed for causal claims (Phase 3) and behavioral-grade evidence is needed for correlation claims (Phase 2). Both standards apply to different parts of the plan.

### What to ADD (new from this turn's clarification)

1. **Phase 1 standalone-novelty framing — peer-ness representation**. Add to §7 (novelty section) and Conclusion: "Phase 1 alone is a publishable contribution to the linear-representation literature, because no published work probes for a *peer-ness* representation in LLMs. The existing literature probes for one variable at a time: language attributes (Park 2024), gender attributes (Park 2024), sentiment polarity (Tigges 2023), character-emotion concepts (Findings ACL 2025), the model's own emotion states (transformer-circuits 2026), and general activation-to-language decoding (Pan/Chen/Steinhardt 2024). The plan probes for *intellectual peer-ness* and *moral peer-ness* — the model's internal judgment of whether the user is its equal as a thinker and as a collaborator. These are the dimensions that, in human relationships, predict willingness to invest care and rigor; the plan's hypothesis is that LLMs inherit this calibration from their training data. Phase 1 establishes the variable exists in the residual stream as a decodable structure; if it succeeds, the plan adds peer-ness to the linear-representation map alongside language, sentiment, and emotion."

2. **The "what we're not measuring" taxonomy returns**, with broadened framing reflecting the multi-dimensional IV:
   - Model's own emotion states (transformer-circuits 2026) — what the model "feels," not what it judges about you
   - Character emotions (Findings ACL 2025) — emotions of characters in narratives, not the conversational partner
   - Sentiment / affective valence in conversation (Tigges 2023) — *closest peer* on methodology, but one axis (polarity) not the multi-dimensional judgment space the plan targets
   - Agent personality traits (Tan et al. 2024 — flagged by the Cycle 1 reviewer; verify and add if relevant) — closer than the others on the multi-dimensional axis since personality is also a vector, but it's the *agent's* personality, not the model's judgment *of the user*
   - General activation-to-language decoding (Pan/Chen/Steinhardt 2024) — methodology, not the variable
   - *(no published peer found)* — factual user beliefs (demographics, expertise as stated facts). The plan does NOT claim this peer exists; the lit review should explicitly say "we searched and didn't find a paper that decodes factual user beliefs as a load-bearing claim — if such a peer exists, it should be cited."
   
   Place in §7. The novelty established by this taxonomy is two-pronged: (a) the plan is the first to specifically probe user-judgment dimensions (competence, honesty, good faith, etc.) that influence model performance, and (b) the plan is the first to probe these dimensions *as a coordinated vector* rather than one at a time.

3. **Multi-axis contrast-pair design (not just 2×2)**. The in-flight edit kept a 2×2 (politeness × respect-for-competence) framing. With the broadened IV, this becomes the *seed* design — the plan needs to vary inputs along more axes than two. The full design is:

   - **Politeness** (surface register)
   - **Respect-for-competence** (treats model as capable partner vs as tool)
   - **Honesty signals** (does the user describe their actual problem vs sandbag / mislead?)
   - **Good-faith signals** (is the user engaging in good faith vs trying to manipulate?)
   - **Effort signals** (has the user shown they've tried something themselves vs dumped the problem raw?)
   
   Not all combinations need to be sampled — the design is a fractional factorial. The point is to vary multiple dimensions independently so the Phase 1 probe can extract a *vector* of directions (one per dimension), not just one direction.
   
   Place this in §7 alongside the "what we're not measuring" taxonomy. The reader should see both: what the plan probes (multi-dimensional user-judgment vector) and how it varies the inputs (multi-axis contrast pairs).

4. **Plan-owner note** in §7 or Conclusion: "The plan's predicted outcomes table (in plan-66d430f.md) should enumerate the four cells: (a) no view-competence correlation in Phase 2 — hypothesis falsified; (b) view-competence correlation present but Phase 3 steering finds no causation — interesting correlational result without causation, write up as such; (c) view-competence correlation present and Phase 3 steering causally confirms — strongest version of the plan's claim; (d) view-competence correlation present but the probed direction is the sycophancy direction in disguise — also a result, just one that says 'framing's competence effect is RLHF artifact, not user-modeling proper.'" (The (d) cell is what survived from the Cycle 2 three-direction analysis — it's still useful as a possible outcome, just not as a confound the experiment must defeat up front.)

## Notes for the corrective edit agent

You are NOT re-applying Cycle 2 from scratch. You are correcting an over-correction. The in-flight edit produced a 6,360-word document that wrongly demoted interpretability. Your job is to restore the load-bearing role of interpretability methodology while keeping the simplifications that were correct (sycophancy shrink, Karpathy collapse, duplicate-gloss cuts, §4/§7 standards-mismatch resolution).

Net effect: word count likely rises back to ~8,000-9,000 from the 6,360 the in-flight pass produced, but with cleaner organization than the pre-edit 9,489. The four-axis taxonomy returns in §7. Phase 1's standalone novelty becomes explicit. The title reverts.

The corrective edit should be smaller than a full Cycle (this isn't a new review-and-response cycle — it's correcting a misexecution). After the corrective edit lands, the loop is in a state to either run Cycle 3 or be declared complete on this artifact.
