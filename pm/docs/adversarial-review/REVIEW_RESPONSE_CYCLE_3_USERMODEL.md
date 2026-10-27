# Review Response — Cycle 3 (user-model literature review)

Date: 2026-05-14
Responding to: `REVIEW_CYCLE_3_USERMODEL.md`

Cycle 3 surfaced a load-bearing prior-art correction (Choi/Transluce) and a construct-validity concern that the user's framing actually sharpens. We accept most findings with edits and use the response to also clarify a recurring terminology issue about sycophancy that the prior cycles' framings have been muddling.

## Sycophancy is the LLM's behavior, not a component of the IV

Reading both this cycle's findings and the prior cycles' back-and-forth, there's a recurring terminology slippage worth fixing once across the whole review-loop history. The plan's IV is *the LLM's representation of the user's properties* — competence, honesty, good faith, effort, respect, reasonableness. **Sycophancy is not one of those properties.** Sycophancy is a *property of the LLM's behavior toward the user* (the LLM agrees more readily, hedges less, etc.). It sits on the opposite side of the causal arrow from the IV.

Sycophancy connects to the plan downstream: if the LLM perceives the user as a trustworthy peer (high peer-ness), one prediction is the LLM will be *less* sycophantic — confident enough to push back rather than agree-with-anything. That's a side effect of the same view-quality relationship the plan tests, not a component of the IV.

This clarification ripples through the review and the prior responses:

- The Cycle 2 "three-direction analysis" (raw / sycophancy-only / orthogonalized residual) was a sensible disambiguation step under the assumption that sycophancy and peer-ness might be the same axis in disguise. With the clarification, they're on different sides of the causal arrow and the disambiguation is unnecessary in the headline experiment.
- The Cycle 2 response's predicted-outcomes (d) cell ("sycophancy direction does the work") needs rewriting. The corrected (d) is something like "the contrast-pair extraction picks up an LLM-behavior direction rather than a user-modeling direction" — still a possible outcome of a noisy extraction, still publishable, but with the right vocabulary.
- The Cycle 3 reviewer's worry that peer-ness "may collapse into sentiment ⊕ sycophancy ⊕ perceived-expertise" partially defangs once sycophancy is moved out of the IV bag. It still leaves sentiment and perceived-expertise — those are real construct-validity concerns the response addresses below.

**Edit (lit review)**: rewrite the sycophancy passages and the predicted-outcomes table to reflect the LLM-behavior framing. Don't put sycophancy in the IV vocabulary.

## Bucket A — substantive findings (Block 1)

### A1. Choi/Transluce 2025 is real and the closest peer for Phase 1 — agree, sharpen the novelty

**Agree. Big finding.**

The Cycle 1 edit-application agent treated "Choi et al. 2025" as unverifiable and substituted Pan/Chen/Steinhardt 2024 (LatentQA). It was wrong. The actual Choi paper exists: **Transluce's "Scalably Extracting Latent Representations of Users" (Choi et al., Nov 2025)**. It directly probes user attributes from residual-stream activations. This is the direct prior peer for Phase 1.

The plan's Phase 1 novelty claim was "first to probe for the user-judgment representation." That overstates. Choi/Transluce probes user-attribute representations — broadly. The plan's novelty narrows to:

> Phase 1 extends Choi/Transluce's user-attribute decoding methodology to the specific *peer-ness* meta-dimensional structure — coordinated probing of intellectual peer-ness (competence, effort, reasonableness) and moral peer-ness (honesty, good faith, respect) as the meta-axes that, in human relationships, predict willingness to invest care in collaboration. The variable structure (two meta-axes with named sub-dimensions, grounded in social-psychology priors) is the specific contribution.

**Edit**: rewrite §7's novelty section. Cite Choi et al. 2025 (Transluce) as the direct methodological peer. Narrow the novelty claim to the specific peer-ness *structure*, not "first to probe a user-modeling variable." Drop the "no published peer found" claim about factual user beliefs entirely — it was wrong.

**Edit (plan)**: `plan-66d430f.md`'s Phase 1 "Standalone novelty" statement also needs to narrow. Surface to plan owner.

### A2. Peer-ness construct validity needs operational backing — agree, cite Fiske/Cuddy + add falsification step

**Agree, partially.** The reviewer's concern is that the two-meta-dimension partition (intellectual + moral peer-ness) is asserted without evidence. The plan currently claims the structure on intuitive grounds — that's not enough.

Two complementary fixes:

(a) **Cite Fiske and Cuddy's Stereotype Content Model (SCM)** (Fiske, Cuddy, Glick & Xu 2002 "A Model of (Often Mixed) Stereotype Content: Competence and Warmth Respectively Follow from Perceived Status and Competition," Journal of Personality and Social Psychology) and Cuddy/Fiske/Glick 2008 "Warmth and Competence as Universal Dimensions of Social Perception" (Advances in Experimental Social Psychology). The SCM is the canonical social-psychology result that perceivers cluster their judgments of others on two meta-dimensions: **competence** and **warmth**. The plan's "intellectual peer-ness" maps onto competence; "moral peer-ness" maps onto warmth (trustworthiness, good faith). The SCM has been replicated across cultures and decades. This is the empirical backing the construct claim needs.

   **Note on the warmth terminology issue**: the user has flagged that "warmth" can read ambiguously (the LLM's own state vs the LLM's perception of someone else). Fiske/Cuddy's warmth is unambiguously the *perceiver's perception of the perceived* — i.e., the LLM perceives the user as warm or cold. That maps cleanly onto the plan's IV (the LLM's perception of the user). When the lit review uses "warmth" it should use Fiske/Cuddy's perceiver-of-perceived sense and not lapse into the LLM-own-state reading.

(b) **Add an operational falsification step to the plan's Phase 1**. Specifically: after extracting probe directions per sub-dimension, run factor analysis to test whether the sub-dimensions cluster into the predicted two meta-axes (intellectual / moral). If the factor structure is not two-dimensional, the construct's hypothesized structure is falsified at Phase 1, regardless of whether the dimensions exist individually. This is the kind of "operational falsification step" the reviewer asks for. Pre-register the predicted two-factor structure with sub-dimension loadings before running the experiment.

**Edit (lit review)**: cite Fiske/Cuddy (both 2002 and 2008 papers) in §1 or §7 as the social-psychology framework for the two-meta-axis IV structure. Frame: "the plan's two-meta-axis IV is not a free invention; it maps onto the Stereotype Content Model's competence/warmth dimensions, which are the established social-psychology framework for two-dimensional social perception."

**Edit (plan)**: surface the factor-analysis falsification step to Phase 1 in `plan-66d430f.md`. The pre-registration of predicted loadings is also a plan-owner item.

### A3. Fractional-factorial design is unspecified — agree, specify or admit aspirational

**Agree.** The lit review and the plan both name a multi-axis fractional-factorial design (politeness × respect × honesty × good-faith × effort) without specifying resolution, cell count, or axis-orthogonality enforcement.

For five axes at two levels each, a full factorial is 32 cells. Reasonable fractional-factorial choices:
- Resolution V (no two-factor interactions aliased with main effects or with each other): 16 cells. Lets all main effects and all two-factor interactions be estimated separately. Strong design.
- Resolution III (main effects clean of each other but aliased with two-factor interactions): 8 cells. Minimum design; only main effects clean.

**Recommendation**: Resolution V at 16 cells per benchmark. Gives the design statistical room to detect two-factor interactions (e.g., "honesty matters more when politeness is high"), which is exactly the kind of finding that would make Phase 2's correlation analysis interesting.

**Edit (lit review)**: state explicitly that the design is Resolution V at 16 cells per benchmark; if the plan chooses differently, the lit review will update.

**Edit (plan)**: pin the fractional-factorial choice in `plan-66d430f.md`'s methodology section. The "16-32 cells, owner-decided" range I left earlier should resolve to Resolution V at 16.

### A4. Predicted-outcomes table missing heterogeneous-sub-dimension cells — agree, expand

**Agree.** The four-cell table assumes a homogeneous result across sub-dimensions (peer-ness as a whole correlates or doesn't, causes or doesn't). The likeliest real result is heterogeneous: some sub-dimensions matter, others don't. The current table doesn't have a cell for that.

**Edit**: expand the predicted-outcomes table:

| Sub-dimension result | Phase 3 result | Interpretation |
|---|---|---|
| No sub-dimension correlates with performance | — | Hypothesis falsified at the behavioral level |
| Some sub-dimensions correlate; structure is *meta-axis-coherent* (all intellectual or all moral) | Causation in correlating sub-dimensions | Strong version of the claim with a refinement: one meta-axis matters more than the other |
| Some sub-dimensions correlate; structure is *cross-meta* (mix of intellectual and moral) | Causation per-dimension | The two-meta-axis partition is empirically too clean; revise the construct |
| All sub-dimensions correlate uniformly | Causation across the board | Strongest version of the original claim |
| Correlation present | Steering finds an LLM-behavior direction (e.g., sycophancy) rather than a user-modeling direction | Contrast-pair extraction caught an LLM-state direction; the user-modeling direction needs different extraction. Publishable on the LLM-behavior axis. |

The new third row is what the reviewer was asking for: heterogeneity that complicates the construct but doesn't falsify the relationship. The fifth row replaces the old (d) cell with the corrected sycophancy framing.

### A5. Templeton 2024 SAE feature catalog uncited — agree, cite

**Agree.** Templeton et al. 2024 "Scaling Monosemanticity" documents specific SAE features in Claude 3 Sonnet that are directly relevant to peer-ness: sycophantic praise (an LLM-behavior feature, not peer-ness), inner conflict, deception, bias features. The lit review's earlier draft cited specific feature labels here ("the user is upset", "talking to a child") that turned out to be misremembered. The Cycle 1 edit corrected to verifiable features. Cycle 3 is asking for more — explicit citation of the catalog itself as evidence that SAE features map onto social variables generally, which is the upstream evidence that peer-ness might be a probable feature.

**Edit**: add Templeton et al. 2024 citation to §4 (probing methodology) and §1 (motivation) with the SAE-features-map-onto-social-variables framing. Explicitly note that the catalog includes LLM-behavior features (sycophantic praise) and user-state-or-character features (inner conflict, deception) — i.e., the kind of features the plan's Phase 1 expects to find for peer-ness sub-dimensions.

### A6. Tan 2024 citation unresolved — drop

**Agree, drop.** The Cycle 1 reviewer mentioned Tan et al. 2024 personality traits work; the Cycle 1 edit added it with "pending verification." Cycle 2 didn't resolve it. Cycle 3 confirms the placeholder remains. Time to drop it unless someone can pin the exact paper.

**Edit**: remove the Tan et al. 2024 reference unless the actual paper can be identified. If it's removed, the four-axis "what we're not measuring" taxonomy loses one axis — but with Choi/Transluce added as the closer peer on user-attribute decoding, the taxonomy structure changes anyway. Rework the taxonomy as:

- Model's own emotion states (transformer-circuits 2026)
- Character emotions (Findings ACL 2025)
- Sentiment / affective valence (Tigges 2023)
- General user-attribute decoding (Choi et al. 2025 Transluce) — **closest peer on Phase 1's variable**; the plan extends to the specific peer-ness structure
- LLM-own-behavior features (Templeton 2024 — sycophantic praise, inner conflict; categorized as LLM-state, not user-state)

This is a cleaner taxonomy: it cleanly separates "the model's own state" (Templeton, transformer-circuits) from "the model's perception of others" (Choi, Tigges, Findings ACL).

## Bucket B — structural findings (Block 2)

Per the Cycle 3 reviewer's six structural findings (I'm working from the summary; the review file has the specific text):

**B1**: agree to apply per-finding edits. Whatever the reviewer's specific section-flow and bridge-prose suggestions are, accept them.

**B2**: if the reviewer flagged the "Predicted outcomes" subsection as missing or misplaced, the expanded table from A4 above is the replacement.

**B3-B6**: trust the reviewer's structural taste; apply.

## Bucket C — Block 3 accessibility

### Most load-bearing finding: "peer-ness" itself is never glossed for non-developers

**Agree.** The lit review uses "peer-ness" as a primary term but doesn't define it for the target audience.

**Edit**: add a first-use gloss in the Introduction:
> "Peer-ness — how much the model perceives the user as an equal partner, in the same way a colleague perceives another colleague as a fellow professional rather than as a client or a beginner. Specifically, this review uses peer-ness to mean two meta-dimensions of the model's internal representation of the user: (a) *intellectual peer-ness* — whether the model judges the user as a thinking partner of comparable capability, and (b) *moral peer-ness* — whether the model judges the user as someone engaging in good faith and worth treating with respect."

Place at first mention. Repeat the inline reference at first uses of "intellectual peer-ness" and "moral peer-ness."

### Other Block 3 findings

Apply per the reviewer's specific text. 16 accessibility findings is a lot but they're individually small; most are likely missed glosses, missing acronym expansions, dense paragraphs. Roll into the edit pass as a batch.

## Edits checklist

Before any text changes land in `literature-review-user-model.md`:

1. **Sycophancy reclassification** (response-wide clarification): rewrite all sycophancy passages and the predicted-outcomes table to reflect "sycophancy is LLM behavior, not a peer-ness sub-dimension." Replace the (d) cell in the predicted-outcomes table with "contrast-pair extraction picks up an LLM-behavior direction rather than user-modeling direction" framing.
2. **Choi/Transluce 2025**: cite "Scalably Extracting Latent Representations of Users" (Choi et al., Transluce, Nov 2025) in §4 and §7 as the direct methodological peer for Phase 1. Rewrite Phase 1's novelty claim to extend rather than originate.
3. **Drop "no published peer found" claim** for factual user beliefs.
4. **Fiske/Cuddy SCM**: cite Fiske et al. 2002 and Cuddy/Fiske/Glick 2008 in §1 (or §7) as the social-psychology backing for the two-meta-axis structure. State that intellectual peer-ness maps onto SCM's competence dimension and moral peer-ness onto warmth (perceiver-of-perceived, not LLM-own-state).
5. **Templeton 2024**: cite the SAE-feature catalog in §1 and §4 with the "SAE features map onto social variables, including LLM-behavior and user-state features" framing.
6. **Drop Tan 2024** placeholder; rework the §7 taxonomy with the cleaner five-axis structure (model emotion / character emotion / sentiment / user-attribute decoding via Choi / LLM-behavior features via Templeton).
7. **Fractional-factorial specification**: state Resolution V at 16 cells per benchmark.
8. **Heterogeneous-sub-dimension outcomes**: expand the predicted-outcomes table with the new third row (cross-meta-coherent vs cross-meta-mixed) and the corrected fifth row (LLM-behavior direction).
9. **"Peer-ness" gloss**: add the proposed first-use gloss in the Introduction; repeat at first uses of "intellectual peer-ness" and "moral peer-ness."
10. **Other Block 3 findings**: apply per the Cycle 3 reviewer's specific text (16 accessibility items).
11. **Block 2 structural fixes**: apply per the Cycle 3 reviewer's specific text (6 structural items).

## Notes for the plan owner

Three items the response surfaces that require updates to `plan-66d430f.md`:

1. **Phase 1 novelty claim narrows**: from "first to probe user-modeling representation" to "first to probe peer-ness as a meta-dimensional structure, extending Choi/Transluce's user-attribute decoding to the specific structure grounded in Fiske/Cuddy SCM." Update the plan's "Standalone novelty" statement for Phase 1.
2. **Phase 1 falsification step**: add factor analysis on the extracted sub-dimension probes, with pre-registered predicted two-factor loadings (intellectual vs moral). The construct's hypothesized meta-axis structure is falsifiable at Phase 1 even if the individual sub-dimensions exist.
3. **Pin the fractional-factorial choice**: Resolution V at 16 cells per benchmark (or other choice with rationale).

## Notes for Cycle 4 (predicted short)

The Cycle 3 reviewer predicted Cycle 4 should be short — Choi/Transluce + peer-ness construct validity + fractional-factorial spec being the load-bearing items, with phrasing nits beyond that. After these edits land, Cycle 4 should:

- Verify the Choi/Transluce characterization is accurate (Cycle 3 didn't directly fetch the paper; the response should fetch it before the edit pass).
- Verify Fiske/Cuddy SCM citations are pinned correctly (the canonical 2002 paper and the 2008 chapter).
- Check that the "sycophancy as LLM behavior, not IV component" reframe is consistent across the document.
- Check that the heterogeneous-sub-dimension predicted-outcome row is genuinely informative or whether it dilutes the table.
- Check that "peer-ness" is glossed consistently and that the warmth-terminology issue (Fiske's warmth vs LLM-own-warmth) is handled cleanly.

If Cycle 4 produces only phrasing nits, convergence reached. If Cycle 4 produces another substantive miss (the way Cycle 3 surfaced Choi/Transluce), the loop continues to Cycle 5.
