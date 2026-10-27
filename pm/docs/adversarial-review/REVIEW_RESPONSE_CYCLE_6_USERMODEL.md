# Review Response — Cycle 6 (user-model literature review)

Date: 2026-05-15
Responding to: `REVIEW_CYCLE_6_USERMODEL.md`

Cycle 6 surfaced 16 findings: 9 substantive (including 3 new prior-art finds + 1 cross-link + 5 framing pressure-tests) plus 7 phrasing/structure. The substantive moves apply the new METHODOLOGY.md principle: **narrow the contribution; don't collapse it.**

## Bucket A — new prior art (3 finds + 1 cross-link)

### A1. Cabello & Neplenbroek 2025 "Reading Between the Prompts" (EMNLP 2025, arXiv:2505.16467)

**What Cabello & Neplenbroek actually do** (verbatim abstract quoted):

> "Generative Large Language Models (LLMs) infer user's demographic information from subtle cues in the conversation — a phenomenon called implicit personalization. ... we systematically explore how LLMs respond to stereotypical cues using controlled synthetic conversations, by analyzing the models' latent user representations through both model internals and generated answers to targeted user questions. ... this form of stereotype-driven implicit personalization can be effectively mitigated by intervening on the model's internal representations using a trained linear probe to steer them toward the explicitly stated identity."

Verified content:
- Linear probes on hidden states for **user-side variables**: yes
- Variable probed: **user demographic identity** (gender, race, etc.) — *specific factual attributes*
- DV: **response quality** (specifically, the gap in quality for minority groups) — *not task performance on gradable benchmarks*
- Steering intervention: yes — they steer the probed direction and measure downstream effect on the quality gap
- Methodology: "trained linear probe"; abstract does *not* specify contrast-pair/RepE

**What the plan does that Cabello & Neplenbroek doesn't:**
1. **Variable**: probes *peer-ness* — relational/affective + competence judgment grounded in SCM/Goodwin's social-psychology frameworks. Cabello & Neplenbroek probes specific *factual demographic attributes*. These are different variables on the same kind-of-axis (model's perception of user) but at different levels of abstraction.
2. **DV**: task performance on gradable benchmarks (math, code, knowledge). Cabello & Neplenbroek measures response-quality bias against minority groups. Both are response-side measures but neither subsumes the other.
3. **Multi-axis fractional-factorial design**: politeness × respect-for-competence × honesty × good-faith × effort at Resolution V (16 cells per benchmark). Cabello & Neplenbroek uses synthetic conversation contrasts in a specific demographic-stereotype setup.
4. **Closed-model transfer**: Phase 4 calibrates a verbalized readout against the open-model probe (with NLA as the formal precedent). Cabello & Neplenbroek operates on open-model internals only.

**Replacement contribution statement** (to go into §7 and the Conclusion):

> "Cabello & Neplenbroek (2025) is the closest published peer on the *probe-user-representation + steer + measure-output-effect* axis. They probe linear directions for user demographic identity, steer them, and measure the steering's effect on response-quality bias against minority groups. The plan extends this lineage with four residual contributions: (a) the *variable* — peer-ness perception grounded in social-psychology frameworks (SCM, Goodwin) — rather than demographic identity; (b) the *DV* — task performance on standard gradable benchmarks — rather than response-quality bias; (c) a *multi-axis fractional-factorial design* (Resolution V, 16 cells, 5 framing axes) for systematic IV manipulation; (d) Phase 4's *closed-model transfer* via calibrated verbalized readout (NLA precedent). The methodology of probe extraction is no longer claimed as a contribution — Cabello & Neplenbroek's abstract doesn't specify their probe technique, so a contrast-pair-specific contribution claim isn't defensible without comparing methodology details, which the lit review hasn't done."

Note: this drops the prior "contrast-pair extraction" residual contribution (S4 was right; that claim was special-pleading).

**Edits**:
- §1: cite as the published precedent for probing user-side representations with a steering intervention
- §4: full paragraph after the Choi/Transluce + Deas/McKeown paragraphs as a methodological peer cluster
- §7 novelty: replace the four-contribution residual with the four-contribution residual *above* (different from the prior four)
- §7 "what we're not measuring" taxonomy: under user-attribute decoding, alongside Choi/Transluce, with the demographic-identity vs. peer-ness distinction explicit
- References

### A2. Vennemeyer et al. 2025 "Sycophancy Is Not One Thing" (Sept 2025, arXiv:2509.21305)

**What Vennemeyer et al. actually do** (verbatim abstract quoted):

> "We decompose sycophancy into sycophantic agreement and sycophantic praise, contrasting both with genuine agreement. Using difference-in-means directions, activation additions, and subspace geometry across multiple models and datasets, we show that: (1) the three behaviors are encoded along distinct linear directions in latent space; (2) each behavior can be independently amplified or suppressed without affecting the others; and (3) their representational structure is consistent across model families and scales."

Verified content:
- Three distinct sycophancy-related directions: *sycophantic agreement*, *sycophantic praise*, *genuine agreement* (the contrast)
- Causally independent: each can be steered without affecting the others
- Activation additions used for the causal test
- Robust across model families and scales

**Implications for the lit review**:

This breaks §5's current single-direction framing of sycophancy. The lit review treats sycophancy as one axis distinct from peer-ness; that's still right at the variable level, but at the *representation* level sycophancy is actually three causally-independent directions, not one. The §5 passage on Pan et al. + Sharma + Perez should be updated to acknowledge this internal structure.

The predicted-outcomes table row 5 ("contrast-pair extraction picks up an LLM-behavior direction rather than a user-modeling direction") needs updating too: the LLM-behavior direction is *plural*. The plan's contrast-pair extraction could pick up sycophantic-agreement, sycophantic-praise, or both — and each is independently steerable in Phase 3. This actually *strengthens* Phase 3's value: by steering each candidate direction independently, the plan can disambiguate "we caught a sycophancy sub-direction" from "we caught a peer-ness direction" at finer resolution than previously possible.

**Edits**:
- §5: cite Vennemeyer as the recent decomposition result; acknowledge sycophancy is plural at the representation level
- §7 predicted-outcomes table row 5: update to "contrast-pair extraction picks up one of several LLM-behavior directions (sycophantic agreement, sycophantic praise, etc., per Vennemeyer 2025) rather than a user-modeling direction"
- References

### A3. Jaipersaud et al. 2025 "How Do LLMs Persuade?" (Aug 2025, arXiv:2508.05625)

Adjacent prior art on persuasion-probe-and-steer methodology. Briefly cite in §4 as part of the broader probe-then-steer-on-social-variables lineage; do not lean on it heavily. The lit review hasn't verified the abstract directly; the edit agent will fetch and verify before adding.

### A4. AuditBench cross-link

The sibling regression-loop lit review cites AuditBench (Anthropic, March 2026) for its tool-to-agent gap finding. That finding bears on **Phase 4 self-report calibration**: AuditBench's empirical result is that LLM-as-judge auditors miss things their human counterparts catch. Phase 4 calibrates a verbalized self-report against the open-model probe; AuditBench's finding suggests this calibration is necessary precisely because the verbalized readout alone is unreliable.

**Edits**:
- §6 (introspection / verbalized readout section): cite AuditBench as the empirical motivation for Phase 4's calibration step
- References

## Bucket B — framing pressure-tests (5 findings)

### B1. S4 — Contrast-pair extraction was special-pleading

**Agree.** The Cycle 3 / walk-era novelty claim included "(a) contrast-pair extraction over a multi-axis fractional-factorial design" as a residual contribution against Deas & McKeown. Both Cabello & Neplenbroek and Deas & McKeown have probe extraction methodology that the abstracts don't fully specify — so claiming contrast-pair *specifically* is novel against them requires methodology-level comparison the lit review hasn't done. **The multi-axis fractional-factorial design is a real residual contribution; the contrast-pair extraction part isn't defensible at the abstract level. Drop the methodology-detail claim; keep the design claim.**

This is incorporated into A1's replacement contribution statement above.

### B2. S5 — "Informal NLA" framing overstates equivalence

**Agree, partial.** The current §6 framing claims Phase 4 is "informal NLA" of the same operation. The reviewer is right that this overstates: closed models don't expose activations, so there is *no activation* for Phase 4's verbalizer to verbalize. Phase 4's verbalized readout reads the model's *self-report* about user state, not its activation directly. NLA's AV+AR loop operates on activations; Phase 4 operates on outputs.

**The honest framing**: Phase 4 is *inspired by* NLA's read-activations-as-text framing, but the mechanism is fundamentally different — Phase 4 cannot use a reconstructor in the NLA sense because there's no activation to reconstruct. Phase 4's calibration against the open-model probe is the closed-model substitute for NLA's reconstruction loop.

**Edit**: rewrite the §6 NLA passage. Replace "Phase 4 is informal NLA" with: "Phase 4's design is inspired by NLA's read-activations-as-text framing, but the mechanism is fundamentally different. Closed models do not expose activations, so Phase 4 reads the model's *self-report* about user state via meta-prompt rather than verbalizing an internal activation. The role NLA's reconstructor plays — enforcing faithfulness of the verbalization — is played in Phase 4 by *calibration against the open-model probe*: the open-model probe provides ground truth on matched inputs, and the closed-model self-report is calibrated against it. The Anthropic NLA stack remains the formal precedent for activation-to-text, applicable when activations are available."

### B3. Persona Vectors doing triple duty

**Acknowledge, accept.** The reviewer notes Persona Vectors is asked to carry the model-side-sycophancy point in §4 + §5 + §7. That's defensible — same paper does cover all three contexts — but should be lean on cross-references rather than restating the same content.

**Edit**: tighten the three appearances. Full treatment in §4 (Anthropic methodology); brief cross-references in §5 (sycophancy is a model-side trait) and §7 (LLM-own-behavior bullet) pointing back to §4 rather than restating.

### B4 & B5. Three additional sycophancy/persuasion framing points

Roll into the §5 rewrite that already happens for A2 (Vennemeyer integration).

## Bucket C — phrasing/structure (7 findings)

Roll up into the edit pass without per-item analysis.

## Edits checklist

1. Add Cabello & Neplenbroek to §1, §4, §7 (novelty + taxonomy), References. **Update §7 novelty's four-contribution residual to the new four (variable, DV, multi-axis design, closed-model transfer; drop contrast-pair extraction)**.
2. Add Vennemeyer to §5 + References. Update predicted-outcomes table row 5 to reflect sycophancy as plural.
3. Add Jaipersaud to §4 (briefly) + References. Edit agent verifies abstract before writing.
4. Add AuditBench to §6 + References (cross-link from sibling regression-loop review).
5. Rewrite §6 NLA passage per B2 — Phase 4 is *inspired by* NLA, not "informal NLA"; calibration is the closed-model substitute for NLA's reconstructor.
6. Tighten Persona Vectors triple duty per B3.
7. Apply the 7 phrasing/structure findings per the Cycle 6 review's specific text.

## Post-edit forward walk

After the edits land, do a **forward citation walk** on the three new seeds (Cabello & Neplenbroek, Vennemeyer, Jaipersaud) plus AuditBench. Anything found that bears on the plan triggers a Cycle 8 mini-pass; otherwise declare convergence and close the loop.

## Plan-owner items

- Phase 3 description should acknowledge that sycophancy at the representation level is plural per Vennemeyer 2025 — each of the three sycophancy directions is a candidate the contrast-pair extraction might pick up, and Phase 3 can independently steer each.

## Convergence note

This is the third loop iteration where a citation-graph walk surfaces a "closest peer" that further narrows the novelty claim:
- Cycle 3: Choi/Transluce → narrow to peer-ness specifically
- Walk: Deas & McKeown → narrow to four residual contributions (variable/DV/methodology/transfer)
- Cycle 6: Cabello & Neplenbroek → narrow further (drop the methodology-detail contribution, retain variable/DV/design/transfer)

Each narrowing has been real and defensible. The pattern validates the new "narrow the contribution, don't collapse it" principle: the residual continues to exist and continues to shrink. If Cycle 8 surfaces a fourth "closest peer" that also probes peer-ness with the multi-axis design on task performance, the loop continues. If Cycle 8 surfaces only phrasing nits, convergence.
