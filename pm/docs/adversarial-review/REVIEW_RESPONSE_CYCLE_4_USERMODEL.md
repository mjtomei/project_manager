# Review Response — Cycle 4 (user-model literature review)

Date: 2026-05-14
Responding to: `REVIEW_CYCLE_4_USERMODEL.md`

Cycle 4 reports half-convergence: one substantive Block-1 finding (Goodwin 2014 morality-as-third-dimension), four secondary structural items, and a layer of Block-3 accessibility catches. We accept all of them. The edit pass is correspondingly short and focused.

## Bucket A — substantive (Block 1)

### A1. Goodwin/Piazza/Rozin 2014 — agree, acknowledge the dispute

**Agree.** The SCM two-dimensional warmth/competence framework has a real competitor in the social-psychology literature: Goodwin, Piazza & Rozin 2014 ("Moral character predominates in person perception and evaluation," Journal of Personality and Social Psychology) argue morality is a separable third dimension of person perception, not a warmth subcomponent. Subsequent work (Goodwin 2015 "Moral Character in Person Perception," Current Directions in Psychological Science) consolidates the case.

The plan's two-meta-axis structure (intellectual peer-ness + moral peer-ness) is consistent with SCM if SCM is right and morality lives inside warmth. It's consistent with Goodwin if morality is separable — the plan's "moral peer-ness" *is* the third dimension, just paired with a single "intellectual peer-ness" axis collapsing SCM's competence and warmth-minus-morality. The plan's structure is empirically agnostic between the two views: both predict a two-factor result if morality and intellectuality are the load-bearing axes, regardless of how the rest of the warmth space is carved up.

This actually makes the construct stronger, not weaker. The factor-analysis step Phase 1 runs (exploratory, per the plan's recent relaxation) will reveal whichever structure the data actually support — two factors (consistent with both SCM and Goodwin's narrower morality dimension), three factors (consistent with Goodwin's morality + warmth-without-morality + competence), or something else.

**Edit (lit review)**: in the §1 or §7 SCM passage, add: "SCM is the canonical two-dimensional framework for person perception, but it has a real competitor: Goodwin et al. 2014 'Moral character predominates in person perception and evaluation' (JPSP) argue morality is a separable third dimension rather than a subcomponent of warmth. The plan's two-meta-axis structure (intellectual + moral peer-ness) is consistent with either framework — both predict that morality-related and competence-related judgments load on distinct factors, which is the empirical question Phase 1's factor analysis tests. The plan does not need to commit to SCM over Goodwin to be coherent." Cite Goodwin et al. 2014 (verify before adding).

**Edit (plan)**: surface to `plan-66d430f.md` as a one-line note in Phase 1's construct-validity test: "The plan is empirically agnostic between SCM's two-dimensional warmth/competence framework and Goodwin et al.'s three-dimensional morality/warmth-non-morality/competence framework. The exploratory factor analysis will reveal whichever structure the data support."

### A2. Model-family-specificity should be a predicted-outcomes row — agree

**Agree.** The current 5-row predicted-outcomes table covers within-model heterogeneity (cross-meta-coherent vs cross-meta-mixed) but treats model-family heterogeneity as a secondary outcome in the post-table paragraph. The Cycle 4 reviewer is right that "works on some model families, not others" is a plausible first-class outcome and should be in the table.

**Edit**: add a row to the predicted-outcomes table:

| Sub-dimension result | Phase 3 result | Interpretation |
|---|---|---|
| Correlation present in some model families, absent in others | (per family) | The peer-ness effect is training-data-dependent; the mechanism story (LLMs inherit human collaboration patterns) is supported but the inheritance is partial and uneven. Useful finding even if not the strongest version. |

Place between the existing rows 3 and 4.

### A3. §4 paper-summary table understates Choi/Transluce's evidence grade — agree

**Agree.** The table's current characterization treats Choi/Transluce as one evidence grade weaker than it actually is. Choi shows both gradient-based and circuit-based causal interventions — that's the strongest evidence grade for activation-to-behavior claims in the recent interpretability literature.

**Edit**: upgrade Choi's evidence-grade cell in the §4 paper-summary table from whatever it currently says (likely "decoder + behavioral validation") to "decoder + gradient-based causal interventions + circuit-based causal interventions." If the table has a scale (e.g., Bronze/Silver/Gold or similar), Choi sits at the highest grade.

### A4. Phase 1 novelty paragraph should lead with falsifiability — agree

**Agree.** Currently the Phase 1 novelty paragraph leads with the contribution claim ("extends Choi's user-attribute decoding to the peer-ness meta-dimensional structure"). The reviewer's point is that for a non-developer audience, leading with what the test could *rule out* is more compelling than what the test could prove.

**Edit**: restructure the Phase 1 novelty paragraph to open with: "Phase 1's strongest claim isn't that it will find a peer-ness representation — it's that the construct-validity test could *rule out* the meta-axis structure even if individual peer-ness sub-dimensions exist. If the factor analysis returns a single dominant factor or arbitrary cross-loading, the plan's two-axis framing is falsified at Phase 1, regardless of whether the model represents user competence or user honesty as separate readable variables. That's the rigor the plan inherits from Choi/Transluce's methodology applied to a more specific construct." Then add the contribution claim as the follow-up sentence.

### A5. Closing seed-lineage reading list — agree, cut

**Agree.** The Conclusion has a closing citation recitation that duplicates content in §1 and §7 and the References. Three appearances of the same list is one too many.

**Edit**: cut the closing seed-lineage reading list from the Conclusion. Replace with: "References are organized by section in the bibliography at the end."

## Bucket B — Block 3 accessibility (7 items)

All seven undergloss terms get inline glosses per the reviewer's specific text. Approximate glosses (final agent should refine):

- **"aliases"** (in Resolution V context): "(meaning: pairs of effects that the design can't tell apart — at Resolution V, only effects of order three or higher are aliased, which is acceptable)"
- **"factor-analyze"**: "(run statistical analysis to test whether observed variables cluster into a smaller number of underlying factors — i.e., does the data actually have two-dimensional structure, or some other shape?)"
- **"ablate"**: "(turn off, set to zero, or remove — testing what happens when a specific component is disabled)"
- **"non-Euclidean inner product"**: replace with plain English or remove. If the lit review needs to convey that distances in residual-stream space aren't computed with the standard formula, write: "(distances in the model's internal representation space aren't always computed the standard way — sometimes a weighted version captures the structure better)"
- **"contamination"** (in benchmark context): "(when the benchmark's test answers have leaked into the model's training data, inflating scores without measuring real ability)"
- **"Alpaca"** (instruction-following dataset): "(an instruction-following dataset built from GPT-3.5 outputs in 2023, widely used as a fine-tuning baseline)"
- **"72B parameters"** scale anchor: "(72 billion parameters — roughly the size of Llama-3-70B, mid-sized by 2026 standards. For reference, Claude Opus and GPT-5 are believed to be several times larger)"

## Edits checklist

1. Add Goodwin et al. 2014 acknowledgment to §1 or §7 SCM passage. Cite via WebSearch verification before adding.
2. Add model-family-heterogeneity row to predicted-outcomes table.
3. Upgrade Choi's evidence-grade cell in §4 paper-summary table.
4. Restructure Phase 1 novelty paragraph to lead with falsifiability.
5. Cut closing seed-lineage reading list from Conclusion.
6. Apply the 7 Block-3 accessibility glosses.

## Plan-owner item

Add one-line note to `plan-66d430f.md`'s Phase 1 construct-validity test acknowledging the SCM-vs-Goodwin dispute and the plan's empirical agnosticism between them.

## Notes for Cycle 5 (predicted convergence)

After this edit pass, Cycle 5 should produce only phrasing nits. If it finds another substantive miss (the way Cycle 3 surfaced Choi/Transluce and Cycle 4 surfaced Goodwin), the loop continues. Otherwise, declare convergence.
