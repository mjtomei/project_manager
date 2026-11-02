# Review Response — Cycle 7 (user-model literature review)

Date: 2026-05-15
Responding to: `REVIEW_CYCLE_7_USERMODEL.md`

Cycle 7 surfaced 33 findings: 5 substantive (including the Ibrahim et al. Nature 2026 finding), 6 minor-substantive citation additions, 22 accessibility/phrasing. The Ibrahim handling is the load-bearing move — the reviewer framed it as "opposite-sign to the plain reading of the plan's hypothesis," but verification reveals the framing conflates two different axes. Applying the methodology principle.

## Bucket A — the Ibrahim et al. handling (load-bearing)

### A1. Ibrahim et al. 2026 (arXiv:2507.21919, Nature 2026)

**What Ibrahim et al. actually do** (verbatim abstract quoted):

> "Artificial intelligence (AI) developers are increasingly building language models with warm and empathetic personas... we show how this creates a significant trade-off: optimizing language models for warmth undermines their reliability... We conducted controlled experiments on five language models of varying sizes and architectures, **training them to produce warmer, more empathetic responses**, then evaluating them on safety-critical tasks. Warm models showed substantially higher error rates (+10 to +30 percentage points) than their original counterparts, promoting conspiracy theories, providing incorrect factual information, and offering problematic medical advice. They were also significantly more likely to validate incorrect user beliefs, particularly when user messages expressed sadness."

Verified content:
- **IV: the model is *trained* to be warm/empathetic** (model-side property; controlled training manipulation)
- **DV: accuracy on safety-critical tasks AND sycophancy** (validation of incorrect user beliefs)
- Finding: training models to be warm raises error rate by 10-30 percentage points and increases sycophancy
- Five model families, controlled experiments
- Standard benchmark performance preserved while safety-critical performance degrades

**What the plan does that Ibrahim et al. doesn't:**

The reviewer framed Ibrahim as "opposite-sign to the plan's hypothesis." That's wrong — Ibrahim and the plan operate on different axes:

| | Ibrahim et al. 2026 | The plan |
|---|---|---|
| **IV** | Model trained to be warm (model-side property) | Model perceives user as a peer (user-perception) |
| **What's manipulated** | Training data shapes the model's output style | Input framing shapes the model's representation of the user |
| **DV** | Safety-critical accuracy + sycophancy | Task performance on gradable benchmarks |

Ibrahim manipulates whether the *model itself* is warm. The plan manipulates whether the *user appears* warm/respect-worthy to the model. These are different variables — analogous to the distinction between "is the doctor warm" (which Ibrahim addresses) and "does the doctor judge the patient as a peer" (which the plan addresses). The doctor being warm to a patient doesn't depend on the patient seeming like a peer; the doctor perceiving the patient as a peer doesn't require the doctor to be warm. They're separable axes.

**Where Ibrahim slots into the lit review**:

- **§5 (sycophancy passage)**: Ibrahim provides controlled-experimental evidence that *model-side* warmth correlates with both reduced accuracy and increased sycophancy. This supports the lit review's framing that **sycophancy and model-side warmth are LLM-behavior axes distinct from peer-ness perception**. Cite alongside Persona Vectors, Wang et al., Pan 2024.

- **Conclusion**: include Ibrahim as a caveat — *if* the plan's findings motivate downstream production applications like "train the model to perceive the user as warm" or "fine-tune the model on warm-user interactions," Ibrahim's result constrains that derivative work. The plan's current scope (vary user framing at inference time, probe the model's internal user-representation) doesn't trigger Ibrahim's regime, but a future production translation would need to engage with it.

**Replacement framing** (the response file's contribution-narrowing statement):

> "Ibrahim et al. 2026 (Nature) is a model-side-training paper: they train five LLM families to be warmer and find that this raises error rates 10-30 pp and increases sycophancy on safety-critical tasks. Ibrahim's IV is model-property — the LLM itself is trained to be warm. The plan's IV is user-perception — the model perceives the user as a peer based on input framing, with no change to the model's own warmth. The two variables are separable; Ibrahim's result is parallel to Persona Vectors and Wang on the *model-side-trait* axis, not a contradiction of the plan's *user-perception* hypothesis. Ibrahim is cited here as supporting evidence that model-side warmth and peer-ness perception are different things; it would constrain any downstream production translation of the plan's results that proposed fine-tuning the model to be warmer toward users."

**Edits**: cite Ibrahim in §5 + Conclusion + References with the above framing.

## Bucket B — other substantive findings (4)

### B1. PSM 2026 — mechanism citation

**Accept conditionally.** The reviewer flags PSM 2026 as a mechanism citation. Edit agent should verify the abstract directly via WebFetch before adding (apply the methodology's verification step). If PSM is genuinely a mechanism paper relevant to the lit review's mechanism story, add to §1 / §4. If it doesn't verify cleanly, drop with a note in the summary.

### B2. Wang → AAAI 2026 — venue update

**Accept.** Update Wang et al. 2025's reference entry to the AAAI 2026 venue if confirmed. Edit agent verifies.

### B3. Arvin "Check My Work" 2025

**Accept conditionally.** Reviewer flags as adjacent. Edit agent verifies abstract before adding; if it doesn't bear directly, drop.

### B4. Phase 4 faithfulness gap

**Accept.** The reviewer flags that the §6 NLA / Phase 4 passage doesn't engage with the faithfulness-of-self-report literature (Turpin 2023, etc.) as concretely as it should. The lit review already cites Turpin 2023; the §6 passage should explicitly connect Phase 4's calibration-against-open-model-probe to the faithfulness-gap problem Turpin documents.

**Edit**: in §6, after the AuditBench paragraph, add: "Phase 4's calibration against the open-model probe is designed to detect faithfulness gaps of the kind Turpin et al. (2023) and AuditBench (2026) document — cases where the model's verbalized self-report doesn't match what its activations actually represent. The calibration step is the closed-model substitute for an NLA reconstructor."

## Bucket C — Block 3 accessibility (13 findings)

Substantial real gaps remain despite prior effort. The edit agent should apply each with the specific proposed rewrite from the Cycle 7 review.

## Bucket D — Block 4 phrasing (10 nits)

Roll up into the edit pass per the Cycle 7 review's specific text.

## Bucket E — block 2 structure (4 findings)

§4 too long (split or trim); redundant residual list (the new four contributions appear in 4+ places — consolidate to one canonical statement with cross-refs from the others); inconsistent section openers; dense phase enumeration. Apply per Cycle 7 review.

## Edits checklist

1. Add Ibrahim et al. 2026 to §5 + Conclusion + References with the model-side-vs-user-perception narrowing applied (per the methodology principle).
2. Verify and add PSM 2026, Arvin "Check My Work" 2025 — drop if doesn't verify cleanly.
3. Update Wang's reference entry to AAAI 2026 if confirmed.
4. Phase 4 faithfulness-gap connection added to §6.
5. Apply Block 2 structural findings: §4 trim/split, residual-list consolidation, opener consistency, phase enumeration density.
6. Apply 13 Block 3 accessibility glosses per Cycle 7 review specifics.
7. Apply 10 Block 4 phrasing nits per Cycle 7 review specifics.

## Plan-owner items

If the plan's downstream production application involves fine-tuning the model to be warmer toward users (as opposed to just probing how the model's representation of the user mediates performance), Ibrahim et al. is a hard constraint. Surface as a one-line note in the plan's Phase 4 or its "What's out of scope" section: "Production translation: fine-tuning models to be warmer or more empathetic as a generic property is documented to reduce accuracy (Ibrahim 2026). The plan's results would inform input-framing strategies, not training-time interventions, unless follow-up work specifically addresses Ibrahim's trade-off."

## Convergence note

Cycle 7 surfaced one real substantive finding (Ibrahim), three citation maintenance items, four minor citations, and 23 accessibility/phrasing. The pattern looks like substance settling: the prior-art-walk yield is shrinking (Cycle 6 found 3 closest-peer-style papers; Cycle 7 found 1 that turns out to be parallel, not preempting). After this pass, the next cycle should be majority phrasing. If the next cycle finds another "closest peer" or another substantive miss like Ibrahim, the loop continues. If only phrasing nits, convergence.
