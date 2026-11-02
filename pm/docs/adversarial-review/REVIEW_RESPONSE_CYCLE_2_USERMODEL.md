# Review Response — Cycle 2 (user-model literature review)

Date: 2026-05-14
Responding to: `REVIEW_CYCLE_2_USERMODEL.md`

Six substantive findings to work through. We push back on #1 (sycophancy entanglement), accept #2-#6 with edits. The pushback is the most consequential piece because it reflects how the plan's experimental logic actually works — Cycle 2 mis-framed sycophancy as a confound to eliminate when it is in fact an alternative hypothesis the experiment is designed to distinguish.

## Bucket A — substantive pushback (1 item)

### A1. Sycophancy entanglement is not a confound. It is an alternative hypothesis the experiment naturally distinguishes.

The reviewer argues: contrast pairs (polite vs dismissive) align with RLHF polarity; the "affective stance" direction we extract will be entangled with the sycophancy direction; the plan is measuring the wrong thing.

**Disagree.** This frames sycophancy as a confound the experimental design must eliminate up front. In reality, the experiment's primary measurement (performance change under framing) is *insensitive* to which mechanism is responsible, in exactly the regime that matters.

**The argument in three steps:**

1. **The plan's first-tier claim is behavioral**: does treating the model as a colleague produce a measurable performance improvement on tasks where accuracy is gradable? This question doesn't depend on the mechanism. If polite framing produces no performance change, the plan's hypothesis is falsified at the behavioral level, and the question of "which direction would have been the mediator if there were an effect" is moot. There is no effect to attribute.

2. **If there is a performance effect, the mediation analysis is what distinguishes the candidate mechanisms.** Specifically, we run interchange-intervention on three candidate directions: (a) the contrast-pair-extracted "affective stance" direction, (b) a sycophancy direction extracted via independent contrast pairs that vary politeness with no competence-signal, (c) the orthogonalized residual after subtracting (b) from (a). If (a) alone fully accounts for the effect, the plan can't yet distinguish affective stance from sycophancy — but neither can the alternative-hypothesis literature. If (b) alone accounts for it, the mediator is sycophancy and that itself is a publishable result ("framing-induced performance gains are RLHF-sycophancy artifacts"). If (c) accounts for the effect *after orthogonalization*, the plan has found a sycophancy-orthogonal affective-stance direction — the strongest version of its claim.

3. **Sycophancy as an alternative hypothesis, not a confound, is the right framing.** A confound is something that obscures a real effect; the plan's design treats sycophancy as a competing causal explanation that the mediation analysis adjudicates between. The performance measure is the gatekeeper: no performance effect, no mechanism question. The mechanism question gets asked only when there's something to mechanize, and at that point the three-direction comparison (raw, sycophancy-only, orthogonalized residual) gives a clean read.

**What this means for the lit review.** The §4 / §7 prose should not treat sycophancy as a problem the plan must defeat. It should treat sycophancy as one of two leading mechanism hypotheses the plan's mediation step adjudicates. Add explicit text describing the three-direction analysis above as the experimental disambiguation, and frame Perez 2022 and Sharma 2023 sycophancy work as setting up the rival hypothesis rather than as a methodological threat.

**What this means for the plan.** `plan-66d430f.md` should add a "Predicted outcomes and how we interpret each" subsection that enumerates the four possible result configurations:

| Performance change | Mediation result | Interpretation |
|---|---|---|
| No | (not measured) | Hypothesis falsified at behavioral level |
| Yes | Sycophancy direction alone explains it | Result: framing-induced gains are RLHF sycophancy artifacts. Publishable. |
| Yes | Affective-stance direction alone (post-orthogonalization) | Result: framing-induced gains have a sycophancy-orthogonal social mediator. Strongest version of the plan's claim. |
| Yes | Mixed (both contribute) | Result: partial sycophancy, partial affective stance. The interesting middle case; quantify each component. |

Every cell is a real finding. The "wrong" outcome is hypothesis falsification at the behavioral level — and that is itself useful information. Sycophancy *cannot* hurt us; it can only sharpen the mediation read.

**Edit (lit review)**: rewrite §5's sycophancy passage to position Perez/Sharma as setting up the rival hypothesis the plan tests against rather than as a confound to eliminate. Cross-reference the predicted-outcomes table in the plan.

**Edit (plan)**: surface the predicted-outcomes table to `plan-66d430f.md`. This is a plan-owner action, not a lit-review action, but the lit review should point at it.

## Bucket B — substantive agreements (5 items)

### B1. Tigges et al. 2023 (linear sentiment representations) — agree, add

**Agree.** Cycle 1's reviewer flagged it; the Cycle 1 edit pass did not add it. This is the most directly-adjacent peer — linear representation of sentiment in LLMs is the exact methodological template the plan applies to affective stance.

**Edit**: cite Tigges, Hollinsworth, Geiger, Nanda (2023, arXiv:2310.15154) "Linear Representations of Sentiment in Large Language Models" in §4. Frame: "The methodological template — extract a sentiment direction via contrast pairs, validate it as a linear representation, steer to confirm causal influence on output — is the exact recipe the plan applies to affective stance toward the user. Tigges et al. is the closest published peer on the variable axis; the plan's contribution is the specific variable (affective stance) and the specific outcome (task performance) the steering effect is measured against."

### B2. Strachan 2024 / Shapira 2023 (ToM-skeptic literature) — agree, add

**Agree.** §1 currently leans on Kosinski's ToM claims and Andreas 2022 without acknowledging the skeptic literature. That asymmetry overstates the case for "LLMs maintain user models" as established science.

**Edit**: cite Strachan et al. 2024 ("Testing theory of mind in large language models and humans," Nature Human Behaviour) and Shapira et al. 2023 ("Clever Hans or Neural Theory of Mind? Stress Testing Social Reasoning in Large Language Models," arXiv:2305.14763). Frame in §1 as the principled skepticism the plan engages with: ToM-like behavior in LLMs is documented but contested; the plan's experimental setup does not rest on the strong "LLMs have ToM" claim, only on the weaker "LLMs have linearly-representable social state about the conversational partner" claim, which is what Tigges et al. and the emotion-mediation works empirically support.

### B3. §4-vs-§7 internal inconsistency — agree, upgrade the success criterion

**Agree.** §4 sets the bar at mediation-grade evidence (interchange intervention); §7's success criterion is steering-grade (≥50% of framing effect reproduced by steering). Steering is necessary but not sufficient for causal-mediation claims.

**Edit**: upgrade §7's success criterion to: "interchange intervention on the candidate direction accounts for ≥X% of the framing effect, with X to be calibrated by the orthogonality of the candidate direction against the sycophancy direction (per A1's three-direction analysis)." Steering alone becomes a *preliminary* check — a positive steering result motivates running interchange-intervention; only the interchange result counts as evidence the direction is the mediator. This aligns §7 with §4's stated standard.

### B4. LatentQA content mischaracterization — agree, re-fetch and rewrite

**Agree.** The Cycle 1 edit pass corrected the attribution to Pan/Chen/Steinhardt 2024 (arXiv:2412.08686) and the arXiv ID verified clean. But the characterization of what the paper *does* is still wrong. The Cycle 2 reviewer does not say what the correct characterization is, only that the current one is wrong.

**Edit**: re-fetch arXiv:2412.08686, read the abstract and section structure, and rewrite the characterization to match what the paper actually demonstrates. If after re-fetch the paper turns out *not* to be the closest factual-user-belief-decoding peer, drop it and search for the correct LatentQA-style decoder paper. The original Cycle 1 review's claim "decoding model beliefs about a user" should be the operational anchor — we want the paper that actually does that.

### B5. Wrong-kind growth (deduplication, Karpathy walk-back cut) — agree

**Agree.** Three specific cuts:

1. **Duplicated inline glosses on top of front glossary**: terms defined in the bulleted introductory glossary should not be re-glossed at first body use *if* the glossary stays. The Cycle 1 edit pass added belt-and-suspenders glosses; this was over-correction. Cut the inline gloss when a term is already in the front glossary; keep inline glosses only for terms *not* in the front glossary.

2. **Four-axis "what we're not measuring" taxonomy repeated verbatim across §7 and Conclusion**: pick one place to state it. §7 is the substantive home; Conclusion gets a one-line callback. Cut the verbatim repetition.

3. **130-word Karpathy walk-back**: the Cycle 1 edit downgraded Karpathy to "general-audience guidance" and added a substantial explanatory passage. The Cycle 2 reviewer is right that this is now clutter — the downgrade was the right edit, but the walk-back is heavier than what's left to say. Cut to one sentence: "Karpathy's 'How I Use LLMs' (2025) is the most-cited general-audience prompting guidance; the plan does not benchmark a specific prompt from it, since pinning the exact artifact has not been done." Total impact: cuts ~120 words.

## Items NOT addressed in this response

A few Cycle 2 findings I am leaving as Cycle 3 work because they're either downstream of A1's reframe or genuinely small:

- The phase → inherited methodology → caveat table (Cycle 1 reviewer recommended; Cycle 1 edit pass didn't add). The Cycle 2 reviewer didn't escalate this. Possibly fine; can be revisited if a Cycle 3 reviewer pushes again.
- §7's "worked example of what an interchange intervention on the affective-stance direction would look like" — the A1 reframe partially addresses this by introducing the three-direction analysis. A full worked example is still a useful addition but is a follow-up if Cycle 3 demands it.

## Edits checklist

Before any text changes land in `literature-review-user-model.md`:

1. **§4/§5 sycophancy reframe**: rewrite the Perez 2022 / Sharma 2023 passage to position sycophancy as the rival hypothesis the plan tests against (not a confound to defeat). Add a forward pointer to the predicted-outcomes table to be added to the plan.
2. **Cite Tigges et al. 2023** (arXiv:2310.15154) in §4 as the closest peer on linear-sentiment-representation methodology.
3. **Cite Strachan 2024** (Nature Human Behaviour) and **Shapira 2023** (arXiv:2305.14763) in §1 as the ToM-skeptic literature the plan engages with.
4. **§7 success criterion**: upgrade from steering-grade to interchange-intervention-grade. Steering becomes a preliminary check; interchange is the bar for "this direction is the mediator."
5. **Re-fetch arXiv:2412.08686 and recharacterize LatentQA** — read the abstract carefully and rewrite to match the paper's actual content. If the paper isn't actually the closest factual-user-belief decoder, replace with the correct paper.
6. **Cut duplicate inline glosses** for terms already in the front glossary.
7. **Cut the verbatim "what we're not measuring" taxonomy** from one of §7 or Conclusion (keep in §7, one-line callback in Conclusion).
8. **Cut the 130-word Karpathy walk-back** to one sentence.

## Notes for the plan owner

Two items the lit review's edits surface that require updates to `pm/plans/plan-66d430f.md`:

1. **Add the predicted-outcomes table.** Under "Hypothesis" or as a new "Predicted outcomes" subsection, enumerate the four cells from A1's analysis (no performance change → falsified; performance change explained by sycophancy alone → publishable result on RLHF artifact; performance change explained by orthogonalized residual → strongest version of the plan's claim; mixed → quantify components). This is the framing that makes sycophancy a feature of the experimental design rather than a problem with it.

2. **Specify the three-direction extraction protocol.** The plan's methodology should explicitly call for extracting three candidate directions per the A1 analysis: raw contrast-pair affective-stance direction, sycophancy-only direction (independent contrast pairs varying politeness with no competence signal), and orthogonalized residual. The mediation analysis runs interchange intervention on each. This adds rigor to the Phase 2/3 design.

Both items belong as edits to the plan, not the lit review. The lit review's edits cross-reference them.

## Notes for Cycle 3

After applying these edits, Cycle 3 should expect:

- The sycophancy reframe is now load-bearing. Cycle 3 should pressure-test whether the three-direction analysis is genuinely sound or whether the orthogonalized residual is itself contaminated (e.g., what if the contrast-pair variation is itself a sycophancy variation in disguise?).
- The §7 success criterion is now interchange-grade. Cycle 3 should check whether the plan's described methodology actually supports running interchange intervention or whether that requires capabilities the plan doesn't yet have (open-model access, activation patching tooling, ground-truth labels).
- The LatentQA citation will have been re-fetched and recharacterized. Cycle 3 should verify the new characterization is accurate.
- Tigges, Strachan, Shapira will be in. Cycle 3 should check whether the way they're framed actually engages their content rather than just listing them.
